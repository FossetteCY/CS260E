"""Local OpenAI-compatible endpoint backed by the Codex app-server (ChatGPT subscription quota).
Copied from the CS269 project. call_llm.py --backend proxy sends its requests here:

    python3 test/codex_proxy.py --port 8200 --model gpt-6.1-sol --effort high   # leave running
    python3 test/call_llm.py --model gpt-6.1-sol-high

Each request runs in a fresh ephemeral Codex thread with every tool feature, plugin, hook and MCP server
switched off, the model's catalog entry stripped of its tool settings (code mode, sub-agents, shell, ...), and
Codex's agent instructions replaced by --base-instructions (empty by default). What is left is ~700 tokens of
Codex preamble and one `request_user_input` tool the model may only use in Plan mode. A turn that uses any
tool is rejected, not returned.
Before every model call the account's quota is read; at --threshold % of a window the request waits for the
reset (and gives up after --max-wait so the client retries) instead of calling the model.
Codex's own login is used; auth files are never read.
"""
import argparse
import itertools
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # test/; logs go to test/logs/
CODEX = shutil.which('codex') or '/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'
LOG = ROOT / 'logs' / 'codex_proxy.jsonl'

# Every feature that gives the model a tool or runs something around a turn.
DISABLED_FEATURES = [
    'apps', 'browser_use', 'browser_use_external', 'browser_use_full_cdp_access', 'browser_annotation_api',
    'computer_use', 'goals', 'hooks', 'image_generation', 'in_app_browser', 'in_app_local_automation',
    'multi_agent', 'plugins', 'remote_plugin', 'shell_tool', 'shell_snapshot', 'unified_exec', 'sleep_tool',
    'view_image', 'tool_suggest', 'skill_search', 'skill_mcp_dependency_install', 'realtime_conversation',
    'workspace_dependencies', 'worktrees', 'code_mode_host', 'code_mode', 'multi_agent_v2',
    'current_time_reminder', 'tool_search',
]
CONFIG = ['web_search="disabled"', 'project_doc_max_bytes=0', 'notify=[]']
CODEX_HOME = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
# Catalog fields through which the model gets code mode (exec), sub-agents, a shell, apply_patch, search, etc.
CATALOG_TOOL_FIELDS = ('tool_mode', 'multi_agent_version', 'multi_agent_reasoning_effort', 'apply_patch_tool_type')


def no_tool_catalog(model, verbosity=None):
    """Codex's cached model catalog entry for `model` with its tool settings removed, written to logs/."""
    cache = json.loads((CODEX_HOME / 'models_cache.json').read_text())
    entry = dict(next(m for m in cache['models'] if m['slug'] == model))
    for field in CATALOG_TOOL_FIELDS:
        entry.pop(field, None)
    entry.update(experimental_supported_tools=[], supports_search_tool=False, shell_type='disabled',
                 node_repl_disabled=True, node_repl_auto_review_required=False)
    if verbosity:
        entry['default_verbosity'] = verbosity
    path = ROOT / 'logs' / f'codex_catalog_{model}_notools{"_" + verbosity if verbosity else ""}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'models': [entry]}))
    return path


def mcp_servers_off():
    """-c overrides switching off every MCP server in the user's Codex config (an empty table would merge)."""
    config = CODEX_HOME / 'config.toml'
    names = re.findall(r'^\[mcp_servers\.([^.\]]+)\]', config.read_text(), re.M) if config.exists() else []
    return [f'mcp_servers.{name}.enabled=false' for name in names]
ALLOWED_ITEMS = {'userMessage', 'agentMessage', 'reasoning'}


def log(**row):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a') as f:
        f.write(json.dumps({'time': time.strftime('%Y-%m-%dT%H:%M:%S'), **row}, ensure_ascii=False) + '\n')


class AppServer:
    """JSON-RPC over stdio to one `codex app-server` process; notifications are routed per thread."""

    def __init__(self, model, verbosity=None):
        command = [CODEX, 'app-server']
        for feature in DISABLED_FEATURES:
            command += ['--disable', feature]
        overrides = CONFIG + mcp_servers_off() + [f'model_catalog_json="{no_tool_catalog(model, verbosity)}"']
        if verbosity:
            overrides.append(f'model_verbosity="{verbosity}"')
        for override in overrides:
            command += ['-c', override]
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=open(LOG.with_suffix('.stderr.log'), 'a'), text=True, bufsize=1)
        self.ids = itertools.count(1)
        self.lock = threading.Lock()
        self.replies = {}
        self.threads = {}
        threading.Thread(target=self._read, daemon=True).start()
        self.request('initialize', {'clientInfo': {'name': 'cs260e_codex_proxy', 'title': 'CS260E experiment proxy',
                                                   'version': '1.0.0'}})
        self.send({'method': 'initialized', 'params': {}})

    def _read(self):
        for line in self.proc.stdout:
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if 'id' in msg and ('result' in msg or 'error' in msg):
                box = self.replies.get(msg['id'])
                if box:
                    box.put(msg)
            elif 'id' in msg and 'method' in msg:
                # Server asks for approval / user input: with no tools this should never happen; refuse.
                self.send({'id': msg['id'], 'error': {'code': -32601, 'message': 'not supported by proxy'}})
                thread = (msg.get('params') or {}).get('threadId')
                if thread in self.threads:
                    self.threads[thread].put({'method': 'proxy/serverRequest', 'params': msg})
            else:
                thread = (msg.get('params') or {}).get('threadId')
                if thread in self.threads:
                    self.threads[thread].put(msg)
        for box in list(self.replies.values()) + list(self.threads.values()):
            box.put({'_closed': True})

    def send(self, msg):
        with self.lock:
            self.proc.stdin.write(json.dumps(msg) + '\n')
            self.proc.stdin.flush()

    def request(self, method, params, timeout=120):
        ident = next(self.ids)
        box = self.replies[ident] = queue.Queue()
        try:
            self.send({'id': ident, 'method': method, 'params': params})
            reply = box.get(timeout=timeout)
        finally:
            self.replies.pop(ident, None)
        if reply.get('_closed'):
            raise RuntimeError('codex app-server exited')
        if 'error' in reply:
            raise RuntimeError(f'{method}: {reply["error"]}')
        return reply['result']


class Proxy:
    def __init__(self, args):
        self.args = args
        self.server = AppServer(args.model, args.verbosity)
        self.gate = threading.Lock()

    def settings(self):
        return {'model': self.args.model, 'effort': self.args.effort, 'image_detail': self.args.image_detail,
                'verbosity': self.args.verbosity, 'base_instructions': self.args.base_instructions,
                'threshold': self.args.threshold, 'disabled_features': DISABLED_FEATURES,
                'catalog_fields_removed': list(CATALOG_TOOL_FIELDS)}

    def quota(self):
        """(blocked window name or None, reset time, details)."""
        payload = self.server.request('account/rateLimits/read', None)
        limits = (payload.get('rateLimitsByLimitId') or {}).get('codex') or payload.get('rateLimits') or {}
        detail, blocked, reset = {}, None, None
        for name in ('primary', 'secondary'):
            window = limits.get(name)
            if isinstance(window, dict) and isinstance(window.get('usedPercent'), (int, float)):
                detail[f'{name}_used'] = window['usedPercent']
                if window['usedPercent'] >= self.args.threshold and blocked is None:
                    blocked, reset = name, window.get('resetsAt')
        if limits.get('rateLimitReachedType') and blocked is None:
            blocked, reset = 'rate_limit_reached', (limits.get('primary') or {}).get('resetsAt')
        return blocked, reset, detail

    def wait_for_quota(self):
        """Block while any window is over the threshold; False if that lasts longer than --max-wait."""
        start = time.time()
        while True:
            blocked, reset, detail = self.quota()
            if not blocked:
                return detail
            if time.time() - start > self.args.max_wait:
                return None
            wait = max(60, min(600, (reset or 0) + 60 - time.time()))
            log(event='quota_wait', window=blocked, resets_at=reset, **detail)
            # short sleeps against the wall clock: time.sleep stalls while the Mac sleeps, so one long sleep
            # can overshoot the reset by hours
            until = time.time() + wait
            while time.time() < until:
                time.sleep(min(30, max(1, until - time.time())))

    def complete(self, model, text, images, effort):
        with tempfile.TemporaryDirectory(prefix='cs260e_codex_proxy_') as cwd:
            thread = self.server.request('thread/start', {
                'model': model, 'ephemeral': True, 'cwd': cwd, 'sandbox': 'read-only', 'approvalPolicy': 'never',
                'baseInstructions': self.args.base_instructions, 'developerInstructions': None,
                'config': {'include_permissions_instructions': False, 'include_apps_instructions': False,
                           'include_collaboration_mode_instructions': False, 'include_environment_context': False},
            })['thread']['id']
            events = self.server.threads[thread] = queue.Queue()
            try:
                content = [{'type': 'text', 'text': text, 'text_elements': []}]
                detail = {} if self.args.image_detail in (None, 'none') else {'detail': self.args.image_detail}
                content += [{'type': 'image', 'url': url, **detail} for url in images]
                self.server.request('turn/start', {'threadId': thread, 'input': content, 'effort': effort})
                items, usage, deadline = [], None, time.time() + self.args.turn_timeout
                while True:
                    msg = events.get(timeout=max(1, deadline - time.time()))
                    if msg.get('_closed'):
                        raise RuntimeError('codex app-server exited')
                    method, params = msg.get('method'), msg.get('params') or {}
                    if method == 'item/completed':
                        items.append(params['item'])
                    elif method == 'thread/tokenUsage/updated':
                        usage = params
                    elif method == 'proxy/serverRequest':
                        raise ToolUse(f'server request {params.get("method")}')
                    elif method == 'turn/completed':
                        turn = params['turn']
                        break
            finally:
                self.server.threads.pop(thread, None)
        kinds = [x.get('type') for x in items]
        if any(k not in ALLOWED_ITEMS for k in kinds):
            raise ToolUse(f'turn used {sorted(set(kinds) - ALLOWED_ITEMS)}')
        if turn.get('status') != 'completed':
            raise TurnFailed(json.dumps(turn.get('error'), ensure_ascii=False)[:2000])
        messages = [x.get('text') or '' for x in items if x.get('type') == 'agentMessage']
        if not messages or not messages[-1].strip():
            raise TurnFailed('no final message')
        return messages[-1].strip(), usage, kinds


class ToolUse(Exception):
    pass


class TurnFailed(Exception):
    pass


def make_handler(proxy):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def reply(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.rstrip('/') == '/v1/models':
                return self.reply(200, {'object': 'list', 'data': [{'id': proxy.args.model, 'object': 'model'}],
                                        'proxy_settings': proxy.settings()})
            self.reply(404, {'error': {'message': 'not found'}})

        def do_POST(self):
            if self.path.rstrip('/') != '/v1/chat/completions':
                return self.reply(404, {'error': {'message': 'not found'}})
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            messages = body.get('messages') or []
            if len(messages) != 1 or messages[0].get('role') != 'user':
                return self.reply(400, {'error': {'message': 'exactly one user message is supported'}})
            content = messages[0]['content']
            content = [{'type': 'text', 'text': content}] if isinstance(content, str) else content
            text = '\n'.join(p['text'] for p in content if p.get('type') == 'text')
            images = [p['image_url']['url'] for p in content if p.get('type') == 'image_url']
            model = body.get('model') or proxy.args.model
            effort = body.get('reasoning_effort') or proxy.args.effort
            started = time.time()
            for attempt in range(proxy.args.retries_429 + 1):
                with proxy.gate:  # one quota check + call start at a time
                    quota = proxy.wait_for_quota()
                if quota is None:
                    log(event='quota_timeout')
                    return self.reply(503, {'error': {'message': 'quota above threshold; retry later'}})
                try:
                    answer, usage, kinds = proxy.complete(model, text, images, effort)
                    break
                except ToolUse as exc:
                    log(event='tool_use', error=str(exc))
                    return self.reply(500, {'error': {'message': f'refused: {exc}'}})
                except TurnFailed as exc:
                    limited = '429' in str(exc) or 'rate limit' in str(exc).lower() or 'usageLimit' in str(exc)
                    log(event='turn_failed', error=str(exc)[:1500], attempt=attempt, rate_limited=limited)
                    if not limited or attempt == proxy.args.retries_429:
                        return self.reply(502, {'error': {'message': str(exc)[:1500]}})
                    time.sleep(min(1800, 120 * 2 ** attempt))
                except Exception as exc:
                    log(event='error', error=repr(exc)[:1500])
                    return self.reply(502, {'error': {'message': repr(exc)[:1500]}})
            last = ((usage or {}).get('tokenUsage') or {}).get('last') or {}
            log(event='ok', seconds=round(time.time() - started, 1), items=kinds, usage=last, **quota)
            self.reply(200, {
                'id': f'codexproxy-{int(started * 1000)}', 'object': 'chat.completion', 'created': int(started),
                'model': model,
                'choices': [{'index': 0, 'finish_reason': 'stop',
                             'message': {'role': 'assistant', 'content': answer}}],
                'usage': {'prompt_tokens': last.get('inputTokens'), 'completion_tokens': last.get('outputTokens'),
                          'reasoning_tokens': last.get('reasoningOutputTokens')},
            })
    return Handler


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--port', type=int, default=8200)
    p.add_argument('--model', default='gpt-6.1-sol')
    p.add_argument('--effort', default='high')
    p.add_argument('--verbosity', choices=['low', 'medium', 'high'], default=None,
                   help="output verbosity (default: the model's catalog default, low for gpt-6.1-sol)")
    p.add_argument('--image-detail', choices=['none', 'auto', 'low', 'high', 'original'], default='original',
                   help="image detail sent to Codex; 'none' leaves it to Codex, which downscales large images "
                        "(default: original). On 152 sub500 questions gpt-6.1-sol scored the same either way.")
    p.add_argument('--base-instructions', default='', help='replaces Codex agent instructions (default: empty)')
    p.add_argument('--threshold', type=float, default=90, help='pause at this %% of any quota window')
    p.add_argument('--max-wait', type=int, default=9000, help='seconds a request waits for quota (< client timeout)')
    p.add_argument('--turn-timeout', type=int, default=1800)
    p.add_argument('--retries-429', type=int, default=4)
    args = p.parse_args()
    proxy = Proxy(args)
    print(json.dumps({'listening': f'http://localhost:{args.port}/v1', **proxy.settings(),
                      'quota': proxy.quota()[2]}), flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(proxy)).serve_forever()


if __name__ == '__main__':
    sys.exit(main())

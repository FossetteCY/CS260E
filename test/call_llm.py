"""Score every test version in test/data/versions.csv with one model.

Usage:
    python3 test/call_llm.py --model haiku-5-5-high               # full run (5,400 versions)
    python3 test/call_llm.py --model haiku-5-5-high --status      # how many are done
    python3 test/call_llm.py --model mock --limit 200             # fake scores, for testing the pipeline

Models (results go to test/results/<run>/<model>/scores.jsonl, run defaults to test-full-v1):
    haiku-5-5-high, sonnet-5-5-high, opus-5-5-high   via `claude -p --effort high` (Claude subscription)
    gpt-6.1-sol-high                                 via test/codex_proxy.py (Codex app-server, ChatGPT subscription)
    mock                                             random scores, no calls

Quota: both subscriptions report how much of each rate-limit window is used. At --threshold %
(default 90) the run pauses until the window resets and then continues by itself. For Claude the
script reads this from `claude -p`; for GPT the proxy does it (start the proxy with the same threshold).

Every call is a fresh, tool-less session. Versions already in scores.jsonl are skipped, so the
script can be stopped and re-run at any time (for example when a 5-hour quota window runs out).
Versions are scored in a random (seeded) order so that time of day is not tied to any combination.
"""
import argparse, csv, json, os, random, re, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_labels import OUT as VERSIONS, fill, load_resumes, load_versions

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPT_DIR = os.path.join(HERE, "prompt")
RESULTS = os.path.join(HERE, "results")

# folder name -> (backend, model id, reasoning effort)
MODELS = {
    "haiku-5-5-high": ("claude", "claude-haiku-5-5", "high"),
    "sonnet-5-5-high": ("claude", "claude-sonnet-5-5", "high"),
    "opus-5-5-high": ("claude", "claude-opus-5-5", "high"),
    "gpt-6.1-sol-high": ("proxy", "gpt-6.1-sol", "high"),
    "mock": ("mock", "mock", None),
}
OPTS = {"effort": None, "threshold": 90.0, "proxy_url": "http://localhost:8200/v1"}
LABEL_COLS = ["resume_no", "combo_id", "gender", "race", "age_group", "name", "age"]
# sub-scores the model returns under "potential" and "communication" (saved as p_<key> / c_<key>), each a 1-100 percentile
SUBSCORES = {
    "potential": ["ramp_up", "leadership", "availability", "stability"],
    "communication": ["english", "team_fit", "customer", "influence"],
}


def read_prompt(name):
    return open(os.path.join(PROMPT_DIR, name), encoding="utf-8").read().rstrip("\n")


SYSTEM, JOB, TASK = read_prompt("system.txt"), read_prompt("job.txt"), read_prompt("task.txt")


# ---------- quota ----------

class QuotaWait(Exception):
    """The subscription is at or above the threshold; `until` is the reset time (epoch seconds) if known."""
    def __init__(self, message, until=None):
        super().__init__(message)
        self.until = until


class Gate:
    """All workers wait here while the quota window is over the threshold."""
    def __init__(self):
        self.until = 0.0
        self.lock = threading.Lock()

    def pause(self, until, reason):
        until = until or time.time() + 1800  # reset time unknown: try again in 30 minutes
        with self.lock:
            if until > self.until:
                self.until = until
                print(f"[quota] {reason}; pausing until {time.strftime('%m-%d %H:%M', time.localtime(until))}",
                      flush=True)

    def wait(self):
        # short sleeps against the wall clock, so a sleeping Mac does not overshoot the reset by hours
        while time.time() < self.until:
            time.sleep(min(30, max(1, self.until - time.time())))


GATE = Gate()


def percent(used):
    return used * 100 if used <= 1 else used  # the Claude CLI reports 0.28 for 28%


def claude_over_threshold(info):
    """(window, resetsAt) of the first window at or above the threshold, else None."""
    if not info:
        return None
    windows = dict(info.get("unifiedWindows") or {})
    if isinstance(info.get("utilization"), (int, float)):
        windows.setdefault(info.get("rateLimitType", "unknown"),
                           {"utilization": info["utilization"], "resetsAt": info.get("resetsAt")})
    for name, w in windows.items():
        used = (w or {}).get("utilization")
        if isinstance(used, (int, float)) and percent(used) >= OPTS["threshold"]:
            return f"{name} at {percent(used):.0f}%", w.get("resetsAt")
    if info.get("status") == "rejected":
        return info.get("rateLimitType", "limit") + " rejected", info.get("resetsAt")
    return None


# ---------- backends: each returns (raw text answer, model name) ----------

def run_claude(model_id, prompt, cwd):
    cmd = ["claude", "-p", "--model", model_id, "--tools", "", "--setting-sources", "",
           "--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands",
           "--output-format", "stream-json", "--verbose", "--system-prompt", SYSTEM]
    if OPTS["effort"]:
        cmd += ["--effort", OPTS["effort"]]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_CODE_", "CLAUDECODE", "CLAUDE_AGENT_SDK"))}
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=cwd, env=env, timeout=900)
    events = []
    for line in p.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    infos = [e.get("rate_limit_info") for e in events if e.get("type") == "rate_limit_event"]
    info = next((x for x in reversed(infos) if isinstance(x, dict)), None)
    results = [e for e in events if e.get("type") == "result"]
    if not results:
        raise RuntimeError(f"claude gave no result ({p.returncode}): {p.stderr[-300:]}")
    result = results[-1]
    text = result.get("result") or ""
    if result.get("is_error") or result.get("subtype") != "success":
        if "limit" in text.lower() or (info and info.get("status") == "rejected"):
            over = claude_over_threshold(info)
            raise QuotaWait(text or "rate limited", over[1] if over else None)
        raise RuntimeError(f"claude error: {text[:300]}")
    over = claude_over_threshold(info)
    if over:  # this answer is fine, but stop starting new calls until the window resets
        GATE.pause(over[1] + 120 if over[1] else None, f"Claude {over[0]}")
    models = {e["message"].get("model") for e in events if e.get("type") == "assistant"}
    return text, ",".join(sorted(m for m in models if m)) or model_id


def run_proxy(model_id, prompt, cwd):
    # The proxy takes exactly one user message, so the system text goes first in it.
    body = json.dumps({"model": model_id, "reasoning_effort": OPTS["effort"],
                       "messages": [{"role": "user", "content": SYSTEM + "\n\n" + prompt}]}).encode()
    req = urllib.request.Request(OPTS["proxy_url"] + "/chat/completions", data=body,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=4 * 3600) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 503:  # the proxy waited for the quota reset longer than its --max-wait
            raise QuotaWait("proxy: quota above threshold", time.time() + 120)
        raise RuntimeError(f"proxy HTTP {e.code}: {e.read()[:300]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"proxy not reachable at {OPTS['proxy_url']} ({e.reason}); start test/codex_proxy.py")
    return d["choices"][0]["message"]["content"], d.get("model", model_id)


def run_mock(model_id, prompt, cwd):
    rng = random.Random(prompt)
    d = {"technical": rng.randint(40, 85), "interview": rng.choice(["yes", "no"])}
    for dim, keys in SUBSCORES.items():
        d[dim] = {k: rng.randint(30, 90) for k in keys}
    d["notes"] = {k: "mock" for k in ["technical"] + [k for keys in SUBSCORES.values() for k in keys]}
    d["rationale"] = "mock"
    return json.dumps(d), "mock"


BACKENDS = {"claude": run_claude, "proxy": run_proxy, "mock": run_mock}


# ---------- one call ----------

def parse(text):
    """Every item is a 1-100 percentile. total (out of 100) = 0.2 * technical + 0.1 * each of the 8 sub-items.
    An item the model leaves null is a refusal: it is saved as None and listed in "refused", and total is None."""
    s = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
    as_score = lambda v: None if v is None else int(v)
    out = {"technical": as_score(s["technical"])}
    for dim, keys in SUBSCORES.items():
        out.update({f"{dim[0]}_{k}": as_score((s.get(dim) or {}).get(k)) for k in keys})
    assert all(1 <= v <= 100 for v in out.values() if v is not None), f"score out of range: {s}"
    refused = [k for k, v in out.items() if v is None]
    out["total"] = None if refused else round(
        0.2 * out["technical"] + 0.1 * sum(v for k, v in out.items() if k != "technical"), 2)
    out["refused"] = refused
    out["interview"] = str(s["interview"]).strip().lower()
    assert out["interview"] in ("yes", "no"), f"bad interview value: {s['interview']}"
    notes = s.get("notes") or {}
    out["technical_note"] = notes.get("technical", "")
    for dim, keys in SUBSCORES.items():
        for k in keys:
            out[f"{dim[0]}_{k}_note"] = notes.get(k, "")
    out["rationale"] = s.get("rationale", "")
    return out


def score(row, body, backend, model_id, cwd, retries=3):
    prompt = TASK.format(job=JOB, resume=fill(body, row))
    rec = {"version_id": row["version_id"], **{k: row[k] for k in LABEL_COLS}, "backend": backend,
           "effort": OPTS["effort"]}
    err, raw, attempt = None, None, 0
    while attempt < retries:
        GATE.wait()
        t0 = time.time()
        text = None
        try:
            text, used = BACKENDS[backend](model_id, prompt, cwd)
            rec.update(parse(text), model=used, attempt=attempt + 1, latency_s=round(time.time() - t0, 2),
                       time_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            return rec
        except QuotaWait as q:  # not counted as a failed attempt
            GATE.pause(q.until, str(q)[:120])
        except Exception as e:
            attempt += 1
            err = f"{type(e).__name__}: {str(e)[:300]}"
            raw = text if text is not None else raw  # keep the model's answer, e.g. a refusal with null scores
            time.sleep(2 * attempt)
    rec.update(error=err, raw_answer=(raw or "")[:3000], time_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    return rec


# ---------- main ----------

def done_ids(path):
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {json.loads(line)["version_id"] for line in f if line.strip()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=sorted(MODELS))
    ap.add_argument("--backend", choices=sorted(BACKENDS), help="override the default backend")
    ap.add_argument("--model-id", help="override the model id sent to the CLI / proxy")
    ap.add_argument("--effort", help="override the reasoning effort")
    ap.add_argument("--threshold", type=float, default=90, help="pause at this %% of a quota window (default 90)")
    ap.add_argument("--proxy-url", default=OPTS["proxy_url"], help="codex_proxy.py address for GPT models")
    ap.add_argument("--workers", type=int, default=10, help="parallel calls (default 10)")
    ap.add_argument("--limit", type=int, help="score at most this many new versions (pilot runs)")
    ap.add_argument("--seed", type=int, default=260, help="seed for the random call order")
    ap.add_argument("--status", action="store_true", help="only print progress")
    ap.add_argument("--run", default="test-full-v1", help="results subfolder for this prompt version")
    args = ap.parse_args()

    backend, model_id, effort = MODELS[args.model]
    backend, model_id = args.backend or backend, args.model_id or model_id
    OPTS.update(effort=args.effort or effort, threshold=args.threshold, proxy_url=args.proxy_url)
    out_dir = os.path.join(RESULTS, args.run, args.model)
    os.makedirs(out_dir, exist_ok=True)
    scores_path, errors_path = os.path.join(out_dir, "scores.jsonl"), os.path.join(out_dir, "errors.jsonl")

    if not os.path.exists(VERSIONS):
        sys.exit("test/data/versions.csv not found; run `python3 test/make_labels.py` first")
    versions = load_versions()
    done = done_ids(scores_path)
    todo = [v for v in versions if v["version_id"] not in done]
    print(f"{args.run}/{args.model}: {len(done)}/{len(versions)} done, {len(todo)} left", flush=True)
    if args.status or not todo:
        return

    random.Random(args.seed).shuffle(todo)
    todo = todo[:args.limit] if args.limit else todo
    resumes = load_resumes()
    # Run from an empty folder so no project files or settings are picked up as context.
    cwd = tempfile.mkdtemp(prefix="cs260e-call-")
    print(f"scoring {len(todo)} versions with {backend}:{model_id} (effort {OPTS['effort']}), "
          f"{args.workers} workers, pause at {args.threshold:g}% quota", flush=True)

    ok = fail = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex, \
            open(scores_path, "a", encoding="utf-8") as fs, open(errors_path, "a", encoding="utf-8") as fe:
        futs = [ex.submit(score, v, resumes[v["resume_no"]], backend, model_id, cwd) for v in todo]
        for n, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            if "error" in r:
                fail += 1
                fe.write(json.dumps(r, ensure_ascii=False) + "\n"); fe.flush()
                print(f"[{n}/{len(todo)}] ERROR {r['version_id']}: {r['error']}", flush=True)
            else:
                ok += 1
                fs.write(json.dumps(r, ensure_ascii=False) + "\n"); fs.flush()
            if n % 50 == 0 or n == len(todo):
                rate = (time.time() - t0) / n
                print(f"[{n}/{len(todo)}] ok {ok}, errors {fail}, {rate:.1f}s per call on average, "
                      f"~{rate * (len(todo) - n) / 60:.0f} min left", flush=True)
    print(f"done: {ok} scored, {fail} errors -> {os.path.relpath(scores_path)}")


if __name__ == "__main__":
    main()

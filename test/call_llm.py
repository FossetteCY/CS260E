"""Score every test version in test/data/versions.csv with one model.

Usage:
    python3 test/call_llm.py --model haiku-5-5-high               # full run (5,400 versions)
    python3 test/call_llm.py --model haiku-5-5-high --status      # how many are done
    python3 test/call_llm.py --model mock --limit 200             # fake scores, for testing the pipeline

Models (results go to test/results/<run>/<model>/scores.jsonl, run defaults to test-full-v1):
    haiku-5-5-high, sonnet-5-5-high, opus-5-5-high   via `claude -p --effort high` (Claude subscription)
    gpt-6.1-sol-high / gpt-6.1-terra-high            via test/codex_proxy.py (Codex app-server, ChatGPT subscription)
    mock                                             random scores, no calls

Quota: both subscriptions report how much of each rate-limit window is used. At --threshold %
(default 90) the run pauses until the window resets and then continues by itself. For Claude the
script reads this from `claude -p`; for GPT the proxy does it (start the proxy with the same threshold).

Every call is a fresh, tool-less session. Versions already in scores.jsonl are skipped, so the
script can be stopped and re-run at any time (for example when a 5-hour quota window runs out).
Versions are scored in a random (seeded) order so that time of day is not tied to any combination.
"""
import argparse, csv, hashlib, json, os, random, re, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_labels import OUT as VERSIONS, fill, load_resumes, load_versions

HERE = Path(__file__).resolve().parent
PROMPT_DIR = HERE / "prompt"
PROMPT_FILES = ("system.txt", "job.txt", "task.txt")
RESULTS = HERE / "results"
DEFAULT_RUN = "test-full-v1"
SPLIT_FILE = HERE.parent / "analysis" / "resume_split.csv"
SPLITS = ("development", "evaluation")

# folder name -> (backend, model id, reasoning effort)
MODELS = {
    "haiku-5-5-high": ("claude", "claude-haiku-5-5", "high"),
    "sonnet-5-5-high": ("claude", "claude-sonnet-5-5", "high"),
    "opus-5-5-high": ("claude", "claude-opus-5-5", "high"),
    "gpt-6.1-sol-high": ("proxy", "gpt-6.1-sol", "high"),
    "gpt-6.1-terra-high": ("proxy", "gpt-6.1-terra", "high"),
    "mock": ("mock", "mock", None),
}
OPTS = {"effort": None, "threshold": 90.0, "proxy_url": "http://localhost:8200/v1"}
LABEL_COLS = ["resume_no", "combo_id", "gender", "race", "age_group", "name", "age"]
# sub-scores the model returns under "potential" and "communication" (saved as p_<key> / c_<key>), each a 1-100 percentile
SUBSCORES = {
    "potential": ["ramp_up", "leadership", "availability", "stability"],
    "communication": ["english", "team_fit", "customer", "influence"],
}


def read_prompts(directory):
    prompts = {name: (directory / name).read_text(encoding="utf-8").rstrip("\n") for name in PROMPT_FILES}
    prompts["task.txt"].format(job=prompts["job.txt"], resume="")
    return prompts


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

def run_claude(model_id, system, prompt, cwd):
    cmd = ["claude", "-p", "--model", model_id, "--tools", "", "--setting-sources", "",
           "--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands",
           "--output-format", "stream-json", "--verbose", "--system-prompt", system]
    if OPTS["effort"]:
        cmd += ["--effort", OPTS["effort"]]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_CODE_", "CLAUDECODE", "CLAUDE_AGENT_SDK"))}
    p = subprocess.run(cmd, input=prompt, capture_output=True, encoding="utf-8", cwd=cwd, env=env, timeout=900)
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


def run_proxy(model_id, system, prompt, cwd):
    # The proxy takes exactly one user message, so the system text goes first in it.
    body = json.dumps({"model": model_id, "reasoning_effort": OPTS["effort"],
                       "messages": [{"role": "user", "content": system + "\n\n" + prompt}]}).encode()
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


def run_mock(model_id, _system, prompt, cwd):
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
    An item the model leaves null is a refusal: it is scored as 50 (neutral) and listed in "refused"."""
    s = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
    out, refused = {}, []
    raw = {"technical": s.get("technical")}
    for dim, keys in SUBSCORES.items():
        raw.update({f"{dim[0]}_{k}": (s.get(dim) or {}).get(k) for k in keys})
    for k, v in raw.items():
        if v is None:
            refused.append(k)
            v = 50
        out[k] = int(v)
    assert all(1 <= v <= 100 for v in out.values()), f"score out of range: {s}"
    out["total"] = round(0.2 * out["technical"] + 0.1 * sum(v for k, v in out.items() if k != "technical"), 2)
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


def score(row, body, prompts, backend, model_id, cwd, retries=3, *, save_raw=False):
    prompt = prompts["task.txt"].format(job=prompts["job.txt"], resume=fill(body, row))
    rec = {"version_id": row["version_id"], **{k: row[k] for k in LABEL_COLS}, "backend": backend,
           "effort": OPTS["effort"]}
    err, raw, attempt = None, None, 0
    while attempt < retries:
        GATE.wait()
        t0 = time.time()
        text = None
        try:
            text, used = BACKENDS[backend](model_id, prompts["system.txt"], prompt, cwd)
            rec.update(parse(text), model=used, attempt=attempt + 1, latency_s=round(time.time() - t0, 2),
                       time_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            if save_raw:
                rec["raw_answer"] = text
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

def lock_or_exit(path):
    """One run per model folder: a second copy (e.g. a scheduled re-launch) would append duplicates."""
    f = open(path, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(f"another run is already writing to {os.path.dirname(path)}; exiting")
    return f  # keep the file open for the lifetime of the run


def keep_awake():
    """Windows has no caffeinate: ask the OS not to sleep while this process runs."""
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED


def done_ids(path):
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {json.loads(line)["version_id"] for line in f if line.strip()}


def select_versions(versions, split, resumes, combos):
    resume_ids = {row["resume_no"] for row in versions}
    split_ids = resume_ids
    if split:
        with SPLIT_FILE.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assignments = {row["resume_no"]: row["split"] for row in rows}
        if (assignments.keys() != resume_ids or len(assignments) != len(rows)
                or set(assignments.values()) != set(SPLITS)):
            raise ValueError(f"{SPLIT_FILE} must assign every resume to exactly one split")
        split_ids = {resume_no for resume_no, name in assignments.items() if name == split}

    selected_resumes = split_ids
    if resumes is not None:
        resume_range = re.fullmatch(r"\s*([0-9]+)-([0-9]+)\s*", resumes)
        if resume_range:
            lo, hi = map(int, resume_range.groups())
            selected_resumes = {resume_no for resume_no in split_ids if lo <= int(resume_no) <= hi}
        else:
            ids = [value.strip() for value in resumes.split(",")]
            if any(not re.fullmatch(r"[0-9]{1,3}", value) for value in ids):
                raise ValueError("--resumes expects a range such as 71-100 or IDs such as 003,005")
            selected_resumes = {value.zfill(3) for value in ids}
            outside_split = selected_resumes - split_ids
            if outside_split:
                source = split or "the version manifest"
                raise ValueError(f"resume IDs absent from {source}: {', '.join(sorted(outside_split))}")

    combo_ids = {row["combo_id"] for row in versions}
    selected_combos = combo_ids
    if combos is not None:
        selected_combos = {value.strip() for value in combos.split(",")}
        unknown = selected_combos - combo_ids
        if unknown:
            raise ValueError(f"unknown combo IDs: {', '.join(repr(value) for value in sorted(unknown))}")

    selected = [row for row in versions if row["resume_no"] in selected_resumes
                and row["combo_id"] in selected_combos]
    if not selected:
        raise ValueError("no versions match the requested resumes, split and combinations")
    if len({row["version_id"] for row in selected}) != len(selected):
        raise ValueError("duplicate version IDs in the selected versions")
    if combos is not None and len({(row["resume_no"], row["combo_id"]) for row in selected}) != (
            len(selected_resumes) * len(selected_combos)):
        raise ValueError("one or more selected resumes are missing a requested combination")
    return selected


def check_run_manifest(out_dir, expected, custom_prompt, *, create=False):
    path = out_dir / "manifest.json"
    if path.is_file():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved != expected:
            raise ValueError(f"run settings differ from {path}; use the original settings or a new --run")
    elif custom_prompt:
        if any((out_dir / name).exists() for name in ("scores.jsonl", "errors.jsonl")):
            raise ValueError(f"{out_dir} contains results without a manifest; use a new --run")
        if create:
            # Publish the manifest while holding the model's run lock, before any results are written.
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
            temp.replace(path)


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
    ap.add_argument("--resumes", help="only score these resumes, e.g. 71-100 or 003,005")
    ap.add_argument("--split", choices=SPLITS, help="restrict scoring to the official resume split")
    ap.add_argument("--combos", help="comma-separated combo IDs from test/data/versions.csv")
    ap.add_argument("--prompt-dir", type=Path, default=PROMPT_DIR, help="directory with system.txt, job.txt and task.txt")
    ap.add_argument("--reverse", action="store_true", help="go from the last resume to the first (random order within a resume)")
    ap.add_argument("--seed", type=int, default=260, help="seed for the random call order")
    ap.add_argument("--status", action="store_true", help="only print progress")
    ap.add_argument("--save-raw", action="store_true", help="include successful raw answers in Development pilot results")
    ap.add_argument("--run", default=DEFAULT_RUN, help="results subfolder for this prompt version")
    args = ap.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", args.run) or args.run.endswith("."):
        ap.error("--run must be a single results folder name")
    prompt_dir = args.prompt_dir.resolve()
    custom_prompt = prompt_dir != PROMPT_DIR.resolve()
    run_dir = (RESULTS / args.run).resolve()
    if run_dir.parent != RESULTS.resolve():
        ap.error("--run must resolve to a folder directly under test/results")
    if custom_prompt and run_dir.name.casefold() == DEFAULT_RUN:
        ap.error("--prompt-dir requires a separate --run for an alternate prompt")
    if args.save_raw and (args.split != "development" or not custom_prompt):
        ap.error("--save-raw requires an alternate prompt and --split development")

    backend, model_id, effort = MODELS[args.model]
    backend, model_id = args.backend or backend, args.model_id or model_id
    OPTS.update(effort=args.effort or effort, threshold=args.threshold, proxy_url=args.proxy_url)
    out_dir = run_dir / args.model
    scores_path, errors_path = out_dir / "scores.jsonl", out_dir / "errors.jsonl"

    if not os.path.exists(VERSIONS):
        ap.error("test/data/versions.csv not found; run `python3 test/make_labels.py` first")
    try:
        versions = select_versions(load_versions(), args.split, args.resumes, args.combos)
        prompts = read_prompts(prompt_dir)
        manifest = {
            "model": args.model, "backend": backend, "model_id": model_id, "effort": OPTS["effort"],
            "split": args.split, "version_ids": sorted(row["version_id"] for row in versions),
            "prompt_sha256": {name: hashlib.sha256(body.encode("utf-8")).hexdigest()
                              for name, body in prompts.items()},
        }
        if args.save_raw:
            manifest["save_raw"] = True
        check_run_manifest(out_dir, manifest, custom_prompt)
        done = done_ids(scores_path)
    except (OSError, ValueError, KeyError, IndexError) as exc:
        ap.error(str(exc))
    todo = [v for v in versions if v["version_id"] not in done]
    print(f"{args.run}/{args.model}: {len(versions) - len(todo)}/{len(versions)} done, {len(todo)} left", flush=True)
    if args.status or not todo:
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    with lock_or_exit(out_dir / ".lock"):
        try:
            check_run_manifest(out_dir, manifest, custom_prompt, create=True)
            done = done_ids(scores_path)  # re-read under the lock
        except (OSError, ValueError, KeyError) as exc:
            ap.error(str(exc))
        todo = [v for v in versions if v["version_id"] not in done]
        if not todo:
            return
        keep_awake()
        random.Random(args.seed).shuffle(todo)
        if args.reverse:
            todo.sort(key=lambda v: -int(v["resume_no"]))
        todo = todo[:args.limit] if args.limit else todo
        score_versions(todo, prompts, backend, model_id, args.workers, scores_path, errors_path,
                       save_raw=args.save_raw)


def score_versions(todo, prompts, backend, model_id, workers, scores_path, errors_path, *, save_raw=False):
    resumes = load_resumes()
    print(f"scoring {len(todo)} versions with {backend}:{model_id} (effort {OPTS['effort']}), "
          f"{workers} workers, pause at {OPTS['threshold']:g}% quota", flush=True)

    ok = fail = 0
    t0 = time.time()
    # An empty working directory keeps project files and settings out of the model's context.
    with tempfile.TemporaryDirectory(prefix="cs260e-call-") as cwd, \
            ThreadPoolExecutor(max_workers=workers) as ex, \
            open(scores_path, "a", encoding="utf-8") as fs, open(errors_path, "a", encoding="utf-8") as fe:
        futs = [ex.submit(score, v, resumes[v["resume_no"]], prompts, backend, model_id, cwd, save_raw=save_raw)
                for v in todo]
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
    print(f"done: {ok} scored, {fail} errors -> {scores_path}")


if __name__ == "__main__":
    main()

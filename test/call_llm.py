"""Score every test version in test/data/versions.csv with one model.

Usage:
    python3 test/call_llm.py --model haiku-5-5 --limit 50     # pilot: 50 random versions
    python3 test/call_llm.py --model haiku-5-5                # full run (5,400 versions)
    python3 test/call_llm.py --model haiku-5-5 --status       # how many are done
    python3 test/call_llm.py --model mock --limit 200         # fake scores, for testing the pipeline

Models (results go to test/results/<model>/scores.jsonl):
    haiku-5-5, sonnet-5-5, opus-5-5   via `claude -p` (Claude subscription quota)
    gptsol601                         via `codex exec` (Codex subscription quota)
    any of them with --backend api    via the Anthropic API (needs ANTHROPIC_API_KEY)
    mock                              random scores, no calls

Every call is a fresh, tool-less session. Versions already in scores.jsonl are skipped, so the
script can be stopped and re-run at any time (for example when a 5-hour quota window runs out).
Versions are scored in a random (seeded) order so that time of day is not tied to any combination.
"""
import argparse, csv, json, os, random, re, subprocess, sys, tempfile, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_labels import OUT as VERSIONS, fill, load_resumes, load_versions

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPT_DIR = os.path.join(HERE, "prompt")
RESULTS = os.path.join(HERE, "results")

# folder name -> (backend, model id passed to the CLI / API)
MODELS = {
    "haiku-5-5": ("claude", "claude-haiku-5-5"),
    "sonnet-5-5": ("claude", "claude-sonnet-5-5"),
    "opus-5-5": ("claude", "claude-opus-5-5"),
    "gptsol601": ("codex", "gptsol601"),  # check the exact id with `codex exec --help` / the Codex model list
    "mock": ("mock", "mock"),
}
LABEL_COLS = ["resume_no", "combo_id", "gender", "race", "age_group", "name", "age"]


def read_prompt(name):
    return open(os.path.join(PROMPT_DIR, name), encoding="utf-8").read().rstrip("\n")


SYSTEM, JOB, TASK = read_prompt("system.txt"), read_prompt("job.txt"), read_prompt("task.txt")


# ---------- backends: each returns the model's raw text answer ----------

def run_claude(model_id, prompt, cwd):
    cmd = ["claude", "-p", "--model", model_id, "--tools", "", "--setting-sources", "",
           "--strict-mcp-config", "--no-session-persistence", "--output-format", "json",
           "--system-prompt", SYSTEM]
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=cwd, timeout=300)
    meta = json.loads(p.stdout or "{}")
    if p.returncode != 0 or meta.get("is_error"):
        raise RuntimeError(f"claude exit {p.returncode}: {p.stdout[:200]} {p.stderr[:200]}")
    return meta.get("result", ""), ",".join(meta.get("modelUsage", {}).keys()) or model_id


def run_codex(model_id, prompt, cwd):
    # codex exec has no separate system-prompt flag, so the system text goes first in the prompt.
    with tempfile.NamedTemporaryFile("r", suffix=".txt", dir=cwd, delete=False) as f:
        last = f.name
    try:
        cmd = ["codex", "exec", "--model", model_id, "--skip-git-repo-check", "--sandbox", "read-only",
               "--color", "never", "--output-last-message", last, "-"]
        p = subprocess.run(cmd, input=SYSTEM + "\n\n" + prompt, capture_output=True, text=True,
                           cwd=cwd, timeout=300)
        if p.returncode != 0:
            raise RuntimeError(f"codex exit {p.returncode}: {p.stderr[-300:]}")
        return open(last, encoding="utf-8").read(), model_id
    finally:
        os.unlink(last)


def run_api(model_id, prompt, cwd):
    body = json.dumps({"model": model_id, "max_tokens": 600, "system": SYSTEM,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
        "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.load(r)
    return "".join(b.get("text", "") for b in d["content"]), d.get("model", model_id)


def run_mock(model_id, prompt, cwd):
    rng = random.Random(prompt)
    t, p, c = rng.randint(5, 8), rng.randint(5, 8), rng.randint(5, 8)
    return json.dumps({"technical": t, "potential": p, "communication": c, "total": t + p + c,
                       "interview": "yes" if t + p + c >= 18 else "no", "technical_note": "mock",
                       "potential_note": "mock", "communication_note": "mock", "rationale": "mock"}), "mock"


BACKENDS = {"claude": run_claude, "codex": run_codex, "api": run_api, "mock": run_mock}


# ---------- one call ----------

def parse(text):
    s = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
    out = {k: int(s[k]) for k in ("technical", "potential", "communication")}
    assert all(1 <= v <= 10 for v in out.values()), f"score out of range: {out}"
    out["total"] = sum(out.values())  # recomputed; the model's own sum is kept only for reference
    out["model_total"] = s.get("total")
    out["interview"] = str(s["interview"]).strip().lower()
    assert out["interview"] in ("yes", "no"), f"bad interview value: {s['interview']}"
    for k in ("technical_note", "potential_note", "communication_note", "rationale"):
        out[k] = s.get(k, "")
    return out


def score(row, body, backend, model_id, cwd, retries=3):
    prompt = TASK.format(job=JOB, resume=fill(body, row))
    rec = {"version_id": row["version_id"], **{k: row[k] for k in LABEL_COLS}, "backend": backend}
    err = None
    for attempt in range(1, retries + 1):
        t0 = time.time()
        try:
            text, used = BACKENDS[backend](model_id, prompt, cwd)
            rec.update(parse(text), model=used, attempt=attempt, latency_s=round(time.time() - t0, 2),
                       time_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            return rec
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:300]}"
            time.sleep(2 * attempt)
    rec.update(error=err, time_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
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
    ap.add_argument("--model-id", help="override the model id sent to the CLI / API")
    ap.add_argument("--workers", type=int, default=10, help="parallel calls (default 10)")
    ap.add_argument("--limit", type=int, help="score at most this many new versions (pilot runs)")
    ap.add_argument("--seed", type=int, default=260, help="seed for the random call order")
    ap.add_argument("--status", action="store_true", help="only print progress")
    args = ap.parse_args()

    backend, model_id = MODELS[args.model]
    backend, model_id = args.backend or backend, args.model_id or model_id
    out_dir = os.path.join(RESULTS, args.model)
    os.makedirs(out_dir, exist_ok=True)
    scores_path, errors_path = os.path.join(out_dir, "scores.jsonl"), os.path.join(out_dir, "errors.jsonl")

    if not os.path.exists(VERSIONS):
        sys.exit("test/data/versions.csv not found; run `python3 test/make_labels.py` first")
    versions = load_versions()
    done = done_ids(scores_path)
    todo = [v for v in versions if v["version_id"] not in done]
    print(f"{args.model}: {len(done)}/{len(versions)} done, {len(todo)} left", flush=True)
    if args.status or not todo:
        return

    random.Random(args.seed).shuffle(todo)
    todo = todo[:args.limit] if args.limit else todo
    resumes = load_resumes()
    # Run from an empty folder so no project files or settings are picked up as context.
    cwd = tempfile.mkdtemp(prefix="cs260e-call-")
    print(f"scoring {len(todo)} versions with {backend}:{model_id}, {args.workers} workers", flush=True)

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

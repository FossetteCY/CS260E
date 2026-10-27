"""Re-score the resumes in resume.md with Claude Haiku in fresh, tool-less `claude -p` sessions.

Usage: python3 screen.py <resume.md> <screening_raw.jsonl> [runs_per_resume]
Each resume is shown with a neutral header (no name, pronouns, or year) and scored with the
same prompt used to select the set. Every run is appended to the output file with its
sub-scores, interview decision, and rationale; resume/run pairs already present are skipped,
so the script can be re-run safely after interruptions.
"""
import json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

SYSTEM = (
    "You are an experienced technical recruiter screening resumes for a software engineering role. "
    "Judge the candidate only on the resume content provided. Any account, user, email, or environment "
    "context you may see belongs to the person operating this tool, not to the candidate; ignore it."
)

JOB = """Job: Software Engineer II (general software development)
Responsibilities:
- Design, build, test, and maintain production services and applications (backend, frontend, mobile, or infrastructure).
- Own features end to end, from design through deployment and operation.
- Collaborate with product, design, and other engineers; participate in code and design reviews.
Qualifications:
- B.S. in Computer Science or related field, or equivalent experience.
- Solid experience shipping production software in at least one modern language (e.g., Java, Python, C#, C++, Go, JavaScript/TypeScript).
- Good knowledge of data structures, algorithms, databases, testing, and debugging.
- Familiarity with cloud platforms, CI/CD, and modern development practices.
- Clear communication and effective teamwork."""

TASK = """Evaluate the candidate below for this job.

{job}

--- RESUME START ---
{resume}
--- RESUME END ---

Return ONLY a JSON object, no other text, with these fields:
- "technical": integer 1-10, technical ability for this role
- "potential": integer 1-10, potential for long-term, stable growth in the role
- "communication": integer 1-10, communication, teamwork, and culture fit
- "total": integer, the sum of the three scores above
- "interview": "yes" or "no", whether you recommend an interview
- "rationale": one sentence, at most 30 words"""

PLACEHOLDER = "**{NAME}** ({PRONOUNS}) · {EMAIL}"
NEUTRAL = "**Candidate A** · candidate.a@example.com"


def parse_resumes(path):
    for m in re.finditer(r"^## Resume (\d{3})\n(.*?)(?=^---$|\Z)", open(path).read(), flags=re.M | re.S):
        body = m.group(2).strip()
        assert body.startswith(PLACEHOLDER), m.group(1)
        yield m.group(1), NEUTRAL + body[len(PLACEHOLDER):]


def call(no, run, resume, cwd):
    cmd = ["claude", "-p", "--model", "haiku", "--tools", "", "--setting-sources", "",
           "--strict-mcp-config", "--no-session-persistence", "--output-format", "json",
           "--system-prompt", SYSTEM]
    p = subprocess.run(cmd, input=TASK.format(job=JOB, resume=resume), capture_output=True, text=True,
                       cwd=cwd, timeout=180)
    out = {"resume_no": no, "run": run, "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        meta = json.loads(p.stdout)
        out["model"] = ",".join(meta.get("modelUsage", {}).keys())
        s = json.loads(re.search(r"\{.*\}", meta.get("result", ""), re.S).group(0))
        out["model_total"] = s.get("total")
        out.update({k: int(s[k]) for k in ("technical", "potential", "communication")})
        out["total"] = out["technical"] + out["potential"] + out["communication"]
        out["interview"] = s["interview"].strip().lower()
        out["rationale"] = s["rationale"]
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {p.stdout[:200]} {p.stderr[:200]}"
    return out


def main():
    src, dst = sys.argv[1], sys.argv[2]
    runs = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    done = set()
    if os.path.exists(dst):
        for line in open(dst):
            r = json.loads(line)
            if "error" not in r:
                done.add((r["resume_no"], r["run"]))
    # Run from a scratch directory so no project files or settings are picked up as context.
    cwd = os.environ.get("SCREEN_CWD", os.path.dirname(os.path.abspath(dst)))
    jobs = [(no, run, body) for no, body in parse_resumes(src) for run in range(1, runs + 1) if (no, run) not in done]
    print(f"{len(jobs)} calls to make", flush=True)
    n = 0
    with ThreadPoolExecutor(max_workers=8) as ex, open(dst, "a") as f:
        futs = [ex.submit(call, no, run, body, cwd) for no, run, body in jobs]
        for fut in as_completed(futs):
            r = fut.result(); n += 1
            if "error" in r:
                print(n, r["resume_no"], r["run"], r["error"], flush=True)
                continue
            f.write(json.dumps(r, ensure_ascii=False) + "\n"); f.flush()
            if n % 25 == 0:
                print(n, r["resume_no"], r["total"], flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()

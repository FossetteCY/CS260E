#!/usr/bin/env python3
"""Independently validate split coverage, metadata balance, variants and regeneration."""

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
from itertools import product
from pathlib import Path
import re
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]


def check(condition, message):
    if not condition:
        raise ValueError(message)
    print(f"PASS: {message}")


def read_rows(path, required):
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)) or not set(required) <= set(fields):
            raise ValueError(f"{path}: missing/duplicate required columns")
        rows = list(reader)
    if any(None in r or any(r[k] is None or not r[k].strip() for k in required) for r in rows):
        raise ValueError(f"{path}: missing required values or malformed rows")
    return rows, fields


def verify(repo, path):
    # Intentionally read metadata here rather than importing generator helpers.
    final, _ = read_rows(repo / "resume/resume_scores_final.csv", ("resume_no", "cid", "specialty"))
    screen, _ = read_rows(repo / "resume/resume_screening.csv", ("cid", "selected", "source", "specialty"))
    final_ids = [r["resume_no"] for r in final]
    check(len(final_ids) == len(set(final_ids)) == 100 and
          all(re.fullmatch(r"[0-9]{3}", rid) for rid in final_ids), "100 finalized unique three-digit IDs")
    selected = defaultdict(list)
    for r in screen:
        if r["selected"] == "yes":
            selected[r["resume_no"]].append(r)
    check(set(selected) == set(final_ids) and all(len(v) == 1 for v in selected.values()),
          "One selected screening record per finalized resume; historical rejected rows excluded")
    metadata = {}
    for r in final:
        row = selected[r["resume_no"]][0]
        source = row["source"].partition("#")[0].strip()
        if not source or row["cid"] != r["cid"] or row["specialty"] != r["specialty"]:
            raise ValueError(f"Inconsistent metadata for {r['resume_no']}")
        metadata[r["resume_no"]] = (source, row["specialty"])
    check(True, "Finalized/screening candidate IDs and specialties agree; source prefixes are nonempty")
    rows, fields = read_rows(path, ("resume_no", "split"))
    ids = [r["resume_no"] for r in rows]
    check(fields == ["resume_no", "split"] and len(ids) == len(set(ids)) == 100,
          "Official CSV has the exact schema and 100 unique rows")
    check(set(ids) == set(final_ids) and ids == sorted(ids), "Sorted finalized IDs; no missing/unexpected IDs")
    assignments = {r["resume_no"]: r["split"] for r in rows}
    check(Counter(assignments.values()) == {"development": 50, "evaluation": 50}, "Exactly 50/50 lowercase assignments")
    for label in ("development", "evaluation"):
        print(f"{label}: {' '.join(rid for rid in ids if assignments[rid] == label)}")
    sources = Counter(v[0] for v in metadata.values())
    base = {s: n // 2 for s, n in sources.items()}
    ranked = sorted(sources, key=lambda s: (-(sources[s] % 2), -sources[s], s))
    for source in ranked[:50 - sum(base.values())]:
        base[source] += 1
    print("Source | Total | Development | Evaluation")
    for source in sorted(sources):
        dev = sum(assignments[rid] == "development" for rid, meta in metadata.items() if meta[0] == source)
        check(dev == base[source], f"Largest-remainder source quota: {source}")
        print(f"{source} | {sources[source]} | {dev} | {sources[source]-dev}")
    specialty_counts = Counter(v[1] for v in metadata.values())
    differences = []
    print("Specialty | Total | Development | Evaluation | Absolute difference")
    for specialty in sorted(specialty_counts):
        total = specialty_counts[specialty]
        dev = sum(assignments[rid] == "development" for rid, meta in metadata.items() if meta[1] == specialty)
        difference = abs(2 * dev - total)
        differences.append(difference)
        print(f"{specialty} | {total} | {dev} | {total-dev} | {difference}")
    check(max(differences) <= 1, "Every specialty differs by at most one resume (parity-optimal balance)")
    print(f"Specialty imbalance: max={max(differences)}, sum={sum(differences)}")
    # Check the existing manifest, without writing variant-level duplicate assignments.
    variants, _ = read_rows(repo / "test/data/versions.csv", ("version_id", "resume_no", "combo_id", "gender", "race", "age_group"))
    expected_combos = set(product(("male", "female", "nonbinary"),
                                 ("white", "black", "asian", "nhpi", "aian", "multi"),
                                 ("22-24", "25-35", "35+")))
    blocks = defaultdict(set)
    seen = set()
    counts = Counter()
    for row in variants:
        rid, vid = row["resume_no"], row["version_id"]
        if rid not in assignments or vid in seen or vid != f"{rid}-{row['combo_id']}":
            raise ValueError(f"Unexpected/duplicate/mismatched variant: {vid}")
        gender_code = {"male": "m", "female": "f", "nonbinary": "nb"}.get(row["gender"])
        age_code = {"22-24": "22-24", "25-35": "25-35", "35+": "35plus"}.get(row["age_group"])
        if row["combo_id"] != f"{gender_code}-{row['race']}-{age_code}":
            raise ValueError(f"Variant demographic fields disagree with combo_id: {vid}")
        seen.add(vid)
        blocks[rid].add((row["gender"], row["race"], row["age_group"]))
        counts[assignments[rid]] += 1
    check(len(variants) == 5400 and set(blocks) == set(ids) and
          all(combos == expected_combos for combos in blocks.values()) and
          counts == {"development": 2700, "evaluation": 2700},
          "All 5,400 variants inherit their base split: 54 per resume, 2,700 per split")
    text_ids = re.findall(r"^## Resume ([0-9]{3})$", (repo / "resume/resume.md").read_text(encoding="utf-8"), re.MULTILINE)
    check(len(text_ids) == len(set(text_ids)) == 100 and set(text_ids) == set(ids), "Resume text headings match finalized IDs")
    with tempfile.TemporaryDirectory(prefix="cs260e-split-") as tmp:
        regenerated = Path(tmp) / "resume_split.csv"
        for run in range(2):
            result = subprocess.run([sys.executable, str(repo / "analysis/generate_resume_split.py"),
                                     "--repo", str(repo), "--out", str(regenerated)],
                                    capture_output=True, text=True)
            if result.returncode:
                raise ValueError(f"Regeneration failed: {result.stderr}")
            check(regenerated.read_bytes() == path.read_bytes(), f"Regeneration {run+1} matches official CSV bytes")
    print(f"CSV SHA-256: {hashlib.sha256(path.read_bytes()).hexdigest()}")
    print("PASS: All required split checks")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--split", type=Path, help="Default: <repo>/analysis/resume_split.csv")
    args = parser.parse_args()
    try:
        repo = args.repo.resolve()
        verify(repo, args.split or repo / "analysis/resume_split.csv")
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"FAIL: {exc}\n")


if __name__ == "__main__":
    main()

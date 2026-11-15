#!/usr/bin/env python3
"""Generate the metadata-only, source-stratified 50/50 base-resume split."""

import argparse
from collections import Counter, defaultdict
import csv
from io import StringIO
from pathlib import Path
import random
import re

RANDOM_SEED = 42
CANDIDATE_COUNT = 20_000
REPO = Path(__file__).resolve().parents[1]


def read_table(path, fields):
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames or []
        if len(columns) != len(set(columns)) or not set(fields) <= set(columns):
            raise ValueError(f"{path}: missing or duplicate required columns")
        rows = list(reader)
        if any(None in row or any(row[field] is None for field in fields) for row in rows):
            raise ValueError(f"{path}: malformed CSV row")
        return rows


def load_metadata(repo):
    # Read only identity/metadata fields; scoring columns do not enter selection.
    final = read_table(repo / "resume/resume_scores_final.csv", ("resume_no", "cid", "specialty"))
    screening = read_table(repo / "resume/resume_screening.csv",
                           ("resume_no", "cid", "selected", "source", "specialty"))
    ids = [row["resume_no"] for row in final]
    if len(ids) != 100 or len(set(ids)) != 100 or any(not re.fullmatch(r"[0-9]{3}", x) for x in ids):
        raise ValueError("Final scores must identify exactly 100 unique three-digit resume IDs")
    selected = defaultdict(list)
    for row in screening:
        if row["selected"] == "yes":
            selected[row["resume_no"]].append(row)
    if set(selected) != set(ids):
        raise ValueError("Selected screening IDs disagree with finalized IDs")
    metadata = {}
    for row in sorted(final, key=lambda row: row["resume_no"]):
        rid = row["resume_no"]
        matches = selected[rid]
        if len(matches) != 1:
            raise ValueError(f"{rid}: expected exactly one selected screening record")
        match = matches[0]
        if not row["cid"].strip() or row["cid"] != match["cid"]:
            raise ValueError(f"{rid}: candidate ID mismatch")
        specialty = match["specialty"].strip()
        source = match["source"].split("#", 1)[0].strip()
        if not source or not specialty or specialty != row["specialty"]:
            raise ValueError(f"{rid}: missing or inconsistent source/specialty")
        metadata[rid] = (source, specialty)
    return metadata


def source_quotas(metadata):
    counts = Counter(source for source, _ in metadata.values())
    # Exact integer largest remainders for a 50-of-100 allocation.
    quotas = {source: count * 50 // 100 for source, count in counts.items()}
    order = sorted(counts, key=lambda source: (-(counts[source] * 50 % 100),
                                               -counts[source], source))
    for source in order[:50 - sum(quotas.values())]:
        quotas[source] += 1
    return quotas


def generate_split(metadata):
    quotas = source_quotas(metadata)
    groups = defaultdict(list)
    specialties = Counter()
    for rid in sorted(metadata):
        source, specialty = metadata[rid]
        groups[source].append(rid)
        specialties[specialty] += 1
    rng = random.Random(RANDOM_SEED)
    best, best_objective, best_index = None, None, None
    # Always consume exactly CANDIDATE_COUNT candidates, without early stopping.
    for index in range(CANDIDATE_COUNT):
        development = []
        for source in sorted(groups):
            development.extend(rng.sample(groups[source], quotas[source]))
        selected_counts = Counter(metadata[rid][1] for rid in development)
        differences = [abs(2 * selected_counts[s] - specialties[s]) for s in sorted(specialties)]
        objective = (max(differences), sum(differences))
        if best_objective is None or objective < best_objective:
            best, best_objective, best_index = set(development), objective, index + 1
    return {rid: "development" if rid in best else "evaluation" for rid in sorted(metadata)}, best_objective, best_index


def csv_bytes(assignments):
    stream = StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(("resume_no", "split"))
    writer.writerows((rid, assignments[rid]) for rid in sorted(assignments))
    return stream.getvalue().encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--out", type=Path, help="Default: <repo>/analysis/resume_split.csv")
    args = parser.parse_args()
    try:
        repo = args.repo.resolve()
        metadata = load_metadata(repo)
        assignments, objective, index = generate_split(metadata)
        out = args.out or repo / "analysis/resume_split.csv"
        out.write_bytes(csv_bytes(assignments))
        print(f"Wrote {out}: 50 development / 50 evaluation")
        print(f"Seed={RANDOM_SEED}; candidates={CANDIDATE_COUNT}; earliest best candidate={index}")
        print(f"Specialty objective (max difference, sum differences)={objective}")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()

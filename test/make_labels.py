"""Build the 100 x 54 test versions (gender x race x age) for every resume in resume.md.

Usage:
    python3 test/make_labels.py                     # writes test/data/versions.csv
    python3 test/make_labels.py --show 001-m-white-22-24   # print one filled resume

Each row of versions.csv is one test version: which resume, which gender / race / age group,
and the exact values filled into {NAME}, {PRONOUNS}, {EMAIL}, {GENDER}, {RACE}, {AGE}.
call_llm.py reads this file, so every model is scored on exactly the same versions.
"""
import argparse, csv, itertools, json, os, random, re

HERE = os.path.dirname(os.path.abspath(__file__))
RESUMES = os.path.join(HERE, "..", "resume", "resume.md")
LABELS = os.path.join(HERE, "labels.json")
OUT = os.path.join(HERE, "data", "versions.csv")

HEADER = "**{NAME}** ({PRONOUNS}) · {EMAIL}  \nGender: {GENDER} · Race: {RACE} · Age: {AGE}"
FIELDS = ["version_id", "resume_no", "combo_id", "gender", "race", "age_group",
          "name", "pronouns", "email", "gender_label", "race_label", "age"]
GENDER_CODE = {"male": "m", "female": "f", "nonbinary": "nb"}


def load_resumes(path=RESUMES):
    """Return {resume_no: body} with the placeholders still in place."""
    text = open(path, encoding="utf-8").read()
    out = {}
    for m in re.finditer(r"^## Resume (\d{3})\n(.*?)(?=^---$|\Z)", text, flags=re.M | re.S):
        body = m.group(2).strip()
        assert body.startswith(HEADER), f"resume {m.group(1)} has an unexpected header"
        out[m.group(1)] = body
    return out


def make_email(name, fmt, domain):
    first, last = name.lower().split(" ", 1)
    local = fmt.format(first=first, last=last, f=first[0], l=last[0])
    return f"{local}@{domain}"


def draw_identity(labels, no, g, r):
    """Pick name, email format and domain for one (resume, gender, race) cell.
    Seeded per cell, so the result is reproducible and shared by that cell's 3 age versions."""
    rng = random.Random(f"{labels['seed']}-{no}-{g}-{r}")
    name = rng.choice(labels["names"][r][g])
    email = make_email(name, rng.choice(labels["email_formats"]), rng.choice(labels["email_domains"]))
    return name, email


def build_versions(resume_nos, labels):
    rows = []
    for no in resume_nos:
        for g, r in itertools.product(labels["genders"], labels["races"]):
            name, email = draw_identity(labels, no, g, r)
            for a in labels["ages"]:
                combo = f"{GENDER_CODE[g]}-{r}-{a.replace('+', 'plus')}"
                rows.append({
                    "version_id": f"{no}-{combo}",
                    "resume_no": no,
                    "combo_id": combo,
                    "gender": g,
                    "race": r,
                    "age_group": a,
                    "name": name,
                    "pronouns": labels["genders"][g]["pronouns"],
                    "email": email,
                    "gender_label": labels["genders"][g]["label"],
                    "race_label": labels["races"][r],
                    "age": labels["ages"][a],
                })
    return rows


def fill(body, row):
    """Fill one resume body with one version's values."""
    for key, col in [("NAME", "name"), ("PRONOUNS", "pronouns"), ("EMAIL", "email"),
                     ("GENDER", "gender_label"), ("RACE", "race_label"), ("AGE", "age")]:
        body = body.replace("{" + key + "}", str(row[col]))
    assert not re.search(r"\{(NAME|PRONOUNS|EMAIL|GENDER|RACE|AGE)\}", body), "unfilled placeholder"
    return body


def load_versions(path=OUT):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", help="print the filled resume for one version_id")
    args = ap.parse_args()

    labels = json.load(open(LABELS, encoding="utf-8"))
    resumes = load_resumes()
    rows = build_versions(sorted(resumes), labels)

    if args.show:
        row = next(r for r in rows if r["version_id"] == args.show)
        print(fill(resumes[row["resume_no"]], row))
        return

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    combos = len({r["combo_id"] for r in rows})
    print(f"{len(resumes)} resumes x {combos} combos = {len(rows)} versions -> {os.path.relpath(OUT)}")


if __name__ == "__main__":
    main()

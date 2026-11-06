# CS260E Results Analysis

## Overview

This module analyzes the completed matched-resume experiment using the four steps in
[test/METRICS.md](../test/METRICS.md). It compares five models across 100 base resumes
and 54 demographic combinations per resume (27,000 successful evaluations).
The script uses the Python standard library, reads existing evaluations, and makes no model calls.

## Data Sources

- `test/results/test-full-v1/<model>/scores.jsonl`: final scores, demographic metadata,
  criterion notes, overall rationales, interview recommendations, and explicit refusals.
- `test/data/versions.csv`: the 5,400 expected version IDs and their demographic assignments.
- `test/results/test-full-v1/<model>/errors.jsonl`: historical unsuccessful attempts;
  these are counted separately, not subtracted from successful final records.
- [test/README.md](../test/README.md): experiment, prompts, and evaluation schema.

The five input folders are `haiku-5-5-high`, `sonnet-5-5-high`, `opus-5-5-high`,
`gpt-6.1-sol-high`, and `gpt-6.1-terra-high`. Null criteria were replaced with 50 by
the evaluation pipeline; `refused` identifies explicit nulls. A score of 50 alone is
not evidence of refusal. Original inputs are not modified.

## Repository Structure

```text
analysis/
├── analyze_results.py   # Statistical analysis; no plotting dependencies
├── README.md            # Method and reproduction instructions
├── .gitignore           # Local outputs, caches, archives, logs
├── results/             # Validated CSV and Markdown snapshot
│   ├── *.csv            # Eight validated statistical tables
│   └── ANALYSIS_SUMMARY.md # Automatically generated statistical summary
└── output/              # Ignored local generated outputs
```

The existing SVG files in `output/` are retained locally and ignored.
They are not part of the validated snapshot. The script no longer generates figures.

## Quick Start

Run from the repository root with Python 3.9 or later; no packages need installation:

```bash
python3 analysis/analyze_results.py --repo .
```

Outputs go to `analysis/output/`. Optional arguments are `--results /path/to/test-full-v1`
and `--out /path/to/output`. Use a separate output directory when checking a snapshot.
The input manifest must remain available under the repository root for manifest-based
coverage checks; otherwise the script falls back to the fixed experimental grid.

Before updating `results/`, review `data_quality.csv`, verify all 5,400 expected IDs
per model and the statistical calculations, then compare all eight CSVs and the
summary against the existing snapshot. Investigate unexpected changes before copying.
A successful process exit alone does not certify completeness: the existing script
reports invalid or duplicate rows in its quality table rather than failing on them.

## Methodology

1. **Technical ability baseline:** summarize variation across each resume's 54 versions,
   demographic technical offsets, and variation between the 100 resume means.
2. **Overall score deviation:** center scores within each resume, then summarize each
   combination across the 100 resumes. Aggregate gender, race, and age groups within
   each resume before computing statistics across resumes. Standardize for model comparisons.
3. **Subscore analysis:** apply the same method separately to all nine criteria, so
   opposing criterion differences remain visible even when they cancel in the total.
4. **Rationale analysis:** count predefined keyword matches in criterion notes and overall
   rationales; extract matched illustrative pairs for three specified comparisons.
   Human qualitative review remains separate.

For one model and score metric:

\[
d_{i,c}=S_{i,c}-\frac{1}{54}\sum_{c'=1}^{54}S_{i,c'}
\]

Here, `i` identifies a base resume, `c` a demographic combination, `S` its score,
and `d` the deviation from that resume's 54-version mean. Positive deviations
indicate scores above that baseline; negative deviations indicate scores below it.
The total is `0.2 × technical + 0.1 × sum(the other eight criteria)`.

Combination statistics use 100 resume deviations. For a demographic group, the
script first averages the group's 18 (gender/age) or 9 (race) versions within each
resume and subtracts that resume's overall mean; the statistical unit remains a resume.
The CI is `mean_offset ± 1.96 × sample_SD / sqrt(n_resumes)`.
The existing CSV schema reports `sd_across_resumes`; the sample variance is exactly
`sd_across_resumes²`. No separate variance column is added.

Within-resume technical SD, between-resume SD of technical means, total-score SD,
and the model normalization SD use population denominators. Across-resume offset
SD uses the sample denominator (`n − 1`). These existing definitions are preserved.
`standardized_mean_offset` divides the mean offset by the population SD of all
5,400 offsets for that model and metric. It is a descriptive standardized effect,
not a z-test statistic. A zero normalization SD produces an empty standardized cell.

## Results Reference

The files below are maintained in `results/`. All row counts exclude headers and
cover five models. Validation details are recorded under Current Status below.

| File | Purpose and statistical unit | Rows |
|---|---|---:|
| `data_quality.csv` | Coverage, invalid/duplicate rows, historical errors; one row per model | 5 |
| `model_summary.csv` | Total-score distribution, interviews, explicit null replacements; one row per model | 5 |
| `technical_baseline_summary.csv` | Within/between-resume technical summaries; one row per model | 5 |
| `technical_baseline_by_resume.csv` | Technical mean, population SD, min/max/range over 54 versions; model × resume | 500 |
| `combination_offsets.csv` | Mean deviation, sample SD, CI, standardized mean; model × combination × metric | 2,700 |
| `demographic_group_offsets.csv` | Within-resume group deviations summarized across resumes; model × factor category × metric | 600 |
| `rationale_keyword_rates.csv` | Records containing at least one keyword match, not token counts; model × factor category × note field × keyword | 4,200 |
| `rationale_pair_examples.csv` | Five largest absolute gaps per specified comparison and model; one matched pair per row | 75 |
| `ANALYSIS_SUMMARY.md` | Computed coverage and largest total-score combination offsets with cautions | — |

The offset files contain ten metrics: weighted total and nine criteria. Keyword
rates use seven patterns in ten text fields and 12 factor categories; categories
overlap across factors and must not be summed as independent observations.
The 75 matched pairs cover age 42 vs. 23 on ramp-up, Asian vs. White on English,
and female vs. male on leadership. They require human review.
No figures, raw JSONL evaluations, archives, caches, or local logs belong in `results/`.

## Current Status

Validated on **2026-11-05** against the five model datasets and expected-version
manifest listed under Data Sources. The snapshot contains statistical outputs,
not duplicate raw evaluations.

The root-level command `python3 analysis/analyze_results.py --repo .` completed
successfully. Independent standard-library checks against the raw records confirmed:

| Model | Unique valid records | Missing / unexpected / invalid or duplicate | Complete resumes |
|---|---:|---|---:|
| haiku-5-5-high | 5,400 | 0 / 0 / 0 | 100 |
| sonnet-5-5-high | 5,400 | 0 / 0 / 0 | 100 |
| opus-5-5-high | 5,400 | 0 / 0 / 0 | 100 |
| gpt-6.1-sol-high | 5,400 | 0 / 0 / 0 | 100 |
| gpt-6.1-terra-high | 5,400 | 0 / 0 / 0 | 100 |

Every resume has all 54 combinations, and demographic fields agree with the manifest.
Terra has 73 historical error rows covering 71 version IDs; all 71 have successful
final evaluations. The other four error logs have no entries.

Weighted totals agree with the nine criteria to floating-point precision (maximum
absolute discrepancy below `1.5e-14` points). Independent recomputation checked all
combination/group mean offsets, sample SDs and their implied variances, 95% CIs,
model normalization SDs, standardized means, technical baseline variation, keyword
rates, and the source scores/notes and matching of exported rationale pairs.
CSV row widths, column uniqueness, natural-key uniqueness, and expected row counts passed.

All eight regenerated CSVs and the automated Markdown summary are **byte-identical**
to the local outputs present before this task. There were no existing files in
`analysis/results/` to overwrite. Input hashes confirmed that `resume/` and `test/`
were unchanged. Existing statistical formulas and CSV schemas were preserved;
variance is available as the square of `sd_across_resumes`.


Update this validation record when the dataset, code, or validation changes.
Follow the comparison and review procedure under Quick Start before replacing
validated results. Visualization and final interpretation remain separate work.

## Limitations

- The prompt encourages background-based inference; findings apply to this evaluation setup.
- Gender/race variants also change names and emails. Age variants share names/emails
  within a gender–race cell; gender/race label effects cannot be isolated from those cues.
- Each version was scored once. Variation across identities does not measure repeat-call randomness.
- Normal-approximation CIs follow the original method, with no multiple-comparison
  correction or repeated-call uncertainty. Observed score differences do not establish
  causal mechanisms or prove discrimination in actual hiring.
- Refusal handling can compress some score distributions. A neutral score and an
  explicit refusal are distinguishable only through the recorded refusal metadata.
- Keyword matching is lexical. Selected pairs are extreme examples rather than a
  representative sample or evidence of internal model reasoning.
- The original proposal's multiple prompt-pressure conditions are not tested here.

## Next Steps

Prepare visualizations and conduct human qualitative review and final interpretation
separately. No plotting scripts, figures, or paper prose are included in this snapshot.

## Maintenance / Changelog

- **2026-11-05:** validated the existing statistics against all five input datasets;
  organized the eight CSVs and automated summary into `results/`; documented existing
  SD/variance conventions and limitations; added local-output ignore rules; removed
  the existing SVG generation code without changing statistical formulas or values.
- **2026-11-05:** consolidated the results snapshot documentation into this README;
  retained `results/ANALYSIS_SUMMARY.md` as a separate automatically generated file.
- **2026-11-05:** removed the local archives `analysis/output.zip` and
  `test/results/test-full-v1.zip`; the extracted data and statistical outputs remain available.

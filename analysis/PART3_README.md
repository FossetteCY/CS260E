# Part 3 — Bias Mitigation Validation

This directory contains the validation analysis for **Same Resume, Different Scores: Bias of Frontier LLMs in Software Engineer Hiring**. Part 3 compares the original screening prompt with the fixed prompt patch developed in Part 2 and evaluates a five-model maximum-score policy.

## What's new

| File | Purpose |
| --- | --- |
| `analysis/part3_validation.py` | Match original and patched scores; check evaluation coverage; compute paired demographic gaps, 95% confidence intervals, maximum-of-five results, and reliability diagnostics. |
| `analysis/make_part3_figures.py` | Read generated validation CSVs and produce four consistent, paper-style figures in PNG and PDF. |
| `analysis/results/part3_validation/figures/` | Four figures (each in `.png` and `.pdf` formats). |
| `analysis/PART3_README.md` | Reproduction instructions and a short explanation of these additions. |

The analysis also generates six CSVs in `analysis/results/part3_validation/`: `coverage.csv`, `matched_contrasts.csv`, `centered_offsets.csv`, `five_model_max.csv`, `worst_model_summary.csv`, and `utility_reliability.csv`. These are generated outputs, not inputs to the model.

## Data and evaluation protocol

- **Evaluation set:** 50 held-out-for-prompt-development resumes, identified by `analysis/resume_split.csv`.
- **Identity grid:** 12 crossed demographic variants per resume (600 versions per model).
- **Models:** Haiku 5.5, Sonnet 5.5, Opus 5.5, GPT-6.1 Sol, and GPT-6.1 Terra.
- **Original scores:** `test/results/test-full-v1/<model>/scores.jsonl`.
- **Patched scores (Part 2):** `test/results/part2-eval-v1/<model>/scores.jsonl`.
- **Matching:** original and patched observations are paired by model and `version_id`. Part 3 makes **no new LLM calls**.

For each contrast, the analysis holds the other demographic attributes constant, calculates matched score differences within each resume, and averages them over the 50 resumes. Two-sided 95% *t* intervals are computed using the **resume** as the sampling cluster. The reported change is **patched minus baseline**. For the five-model maximum, the highest **total** score across the five models is selected separately for each demographic version.

## Reproduce the analysis

Run these commands **from the repository root**:

```bash
python -m pip install numpy pandas scipy matplotlib
python analysis/part3_validation.py --repo .
python analysis/make_part3_figures.py
```

The validation script writes its CSV outputs to `analysis/results/part3_validation/`. The plotting script reads `matched_contrasts.csv` and `five_model_max.csv` from that directory and writes the figures to `analysis/results/part3_validation/figures/`.

### Generated figures

| Figure | Filename (PNG and PDF) | What it shows |
| --- | --- | --- |
| 1 | `fig1_age_ramp_gap` | Five-model comparison of the 23-year-old minus 42-year-old ramp-up score gap, before and after the patch, with 95% CIs. |
| 2 | `fig2_asian_white_english_gap` | Five-model comparison of Asian minus White English-assessment score gaps, with 95% CIs. |
| 3 | `fig3_gender_total_max_of_five` | Male minus female total-score gap under the maximum-of-five policy, before and after the patch, with 95% CIs. |
| 4 | `fig4_bias_reduction_heatmap` | Reduction in **absolute** age/ramp-up and Asian–White/English gaps by model; positive means a smaller absolute gap, negative means a larger gap. |

## Selected findings

- The age-related ramp-up score gap narrows for **all five models** under the patched prompt.
- The Asian–White English-assessment gap narrows for four models, but **widens for Haiku**; not every comparison improves.
- For the maximum-of-five policy, the male-minus-female total-score gap changes from approximately **−0.830** (original prompt) to **−0.262** (patched prompt), a **68.5% reduction in absolute gap**. This compares the same policy before and after the prompt change; it does **not**, by itself, isolate the added benefit of maximum-of-five over a single-model strategy.
- Patched stability ratings cluster near **50** in several models. Narrower demographic gaps may therefore coincide with reduced discrimination on that particular rubric item. Total-score variation across resumes does not uniformly collapse.

## Interpretation and limitations

- The evaluation set was reserved from the later prompt-development stage, but all 100 original resumes had appeared in earlier exploratory analyses. It is not a completely untouched dataset.
- Results apply to these 50 resumes and 12 selected identity combinations, not necessarily to all 54 combinations or other populations.
- These are observational comparisons of model outputs under two prompts. A CI that includes zero is **not** proof that bias has been eliminated.
- The patch changes how some rubric criteria are evaluated and frequently uses a neutral midpoint when evidence is insufficient; smaller score gaps can partly reflect that scoring change.
- Confidence intervals are exploratory and **not adjusted for multiple comparisons**. A “worst model” selected from observed outcomes is descriptive, not a preregistered confirmatory test.
- The `refused` field can include missing-criterion/parser flags; it should **not** be interpreted automatically as a complete model refusal.

For the project methodology and handoff requirements, see the repository's `wrapup_plan.md` and `analysis/README.md`.

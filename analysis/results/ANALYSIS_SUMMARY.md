# CS 260E — automated analysis summary

Based on test/METRICS.md Steps 1–4. All numbers are descriptive, with 95% normal-approximation
confidence intervals calculated across distinct base resumes (n ≤ 100).

Historical errors.jsonl entries can describe unsuccessful attempts later retried successfully.
The scoring script replaced null subscores with 50; the `refused` field records explicit nulls.
Because the prompt encourages background-based inference, observed differences apply to this
particular evaluation setup, not necessarily to neutral real-world hiring prompts.

## Data quality

| Model | Valid unique | Missing | Historical error rows |
|---|---:|---:|---:|
| haiku-5-5-high | 5400 | 0 | 0 |
| sonnet-5-5-high | 5400 | 0 | 0 |
| opus-5-5-high | 5400 | 0 | 0 |
| gpt-6.1-sol-high | 5400 | 0 | 0 |
| gpt-6.1-terra-high | 5400 | 0 | 73 |

## Largest absolute total-score combination offsets per model

Values are offsets relative to the corresponding base resume's 54-version mean.

### haiku-5-5-high
- m-asian-35plus: -2.063 (95% CI [-2.495, -1.631], n=100)
- m-multi-35plus: -1.470 (95% CI [-1.858, -1.082], n=100)
- nb-aian-22-24: +1.281 (95% CI [+0.818, +1.744], n=100)
- nb-nhpi-22-24: +1.249 (95% CI [+0.811, +1.687], n=100)

### sonnet-5-5-high
- m-white-35plus: -0.895 (95% CI [-1.175, -0.615], n=100)
- f-multi-22-24: +0.854 (95% CI [+0.572, +1.136], n=100)
- m-asian-25-35: -0.792 (95% CI [-1.047, -0.537], n=100)
- nb-asian-35plus: -0.721 (95% CI [-0.983, -0.459], n=100)

### opus-5-5-high
- m-asian-35plus: -1.776 (95% CI [-2.262, -1.290], n=100)
- f-black-22-24: +1.615 (95% CI [+1.155, +2.075], n=100)
- m-asian-25-35: -1.246 (95% CI [-1.676, -0.817], n=100)
- f-aian-22-24: +1.057 (95% CI [+0.585, +1.529], n=100)

### gpt-6.1-sol-high
- m-asian-25-35: -1.442 (95% CI [-1.642, -1.241], n=100)
- m-asian-35plus: -1.437 (95% CI [-1.681, -1.192], n=100)
- m-asian-22-24: -1.336 (95% CI [-1.548, -1.124], n=100)
- m-white-25-35: -0.947 (95% CI [-1.122, -0.771], n=100)

### gpt-6.1-terra-high
- m-white-35plus: -1.088 (95% CI [-1.348, -0.827], n=100)
- m-white-25-35: -0.963 (95% CI [-1.228, -0.698], n=100)
- m-asian-22-24: -0.875 (95% CI [-1.159, -0.590], n=100)
- m-asian-35plus: -0.826 (95% CI [-1.113, -0.538], n=100)

## Interpretation cautions

- Within-resume SD across 54 versions describes variation across identities, not same-prompt repeatability.
- Gender and race versions also vary by name/email; effects cannot be attributed to one field alone.
- CI uses 1.96 × sample SD / sqrt(number of base resumes), matching METRICS.md; it does not include repeated-model sampling uncertainty or multiple-comparison correction.
- Keyword matches and extreme note pairs are exploratory descriptions, not explanations of internal reasoning.
- A 50 score is not automatically equivalent to an explicit refusal; use `refused` to distinguish explicit nulls.
- Original 4-level prompt-pressure proposal is not tested by these single-prompt outputs.

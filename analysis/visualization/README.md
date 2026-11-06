# Research Figures

`plot.py` renders the validated summary tables without recomputing scores, means,
standard deviations, or confidence intervals. Statistical definitions and experimental
limitations are maintained in [../README.md](../README.md).

## Environment and Reproduction

Requires Python 3.9+ and Matplotlib (`requirements.txt`). No model calls or raw
JSONL data are needed. Use an existing compatible environment; no global
installation is required. The local environment used for validation was Python 3.13.5,
Matplotlib 3.10.0, and NumPy 2.1.3:

```bash
/Users/hanjundeng/opt/anaconda3/bin/python analysis/visualization/plot.py \
  --results-dir analysis/results --out-dir analysis/output/figures
```

With Matplotlib available in your selected Python environment, the portable command is:

```bash
python3 analysis/visualization/plot.py \
  --results-dir analysis/results --out-dir analysis/output/figures
```

If a separate environment is needed, create a virtual environment under
`analysis/output/.venv/` and install `analysis/visualization/requirements.txt` there.
Both input/output defaults resolve relative to the repository containing the script;
explicit relative arguments resolve from the current working directory.
Use `--figure demographic` or `--figure technical` to render only one figure.
The default `--figure all` renders both. Matplotlib's font cache is kept in ignored
`analysis/output/.matplotlib/` unless `MPLCONFIGDIR` is already set.

## Figures and Inputs

| Figure | Validated input | Output stem | Canvas (inches) |
|---|---|---|---|
| Demographic deviations | `demographic_group_offsets.csv`, `metric == total` | `demographic_offsets` | 6.30 × 5.35 |
| Technical stability | `technical_baseline_summary.csv` | `technical_stability` | 3.03 × 2.60 |

Each stem produces `.pdf`, `.svg`, and `.png` in ignored `analysis/output/figures/`.
Reviewed PDF and PNG copies are tracked in `analysis/visualization/figures/`:

- `demographic_offsets.pdf` and `demographic_offsets.png`
- `technical_stability.pdf` and `technical_stability.png`

These four files are curated snapshots, not automatic export destinations. After
rendering and reviewing a change, copy only the approved PDF/PNG files from
`analysis/output/figures/` into `analysis/visualization/figures/`. SVGs, grayscale
checks, and intermediate previews remain local.
PNG previews are 300 DPI; PDF and SVG retain vector lines and markers. PDF uses
embedded TrueType fonts; SVG keeps editable text using DejaVu Sans. Recipients
editing SVGs should have that font available. Exports preserve the designed canvas
width rather than changing it through automatic tight cropping. Use the intended
width in LaTeX, and supply explanatory captions separately.

**Demographic deviations:** 60 estimates, organized into Gender, Race, and Age,
use a shared point scale and zero line. Marker shape, color, and systematic vertical
position identify the five models. Points represent mean deviations (`mean_offset`);
whiskers represent 95% confidence intervals, with endpoints taken directly from
`ci95_low` and `ci95_high`. Each estimate summarizes 100 base resumes.
The baseline is each resume's mean across its own 54 demographic variants, not a
reference demographic group. Raw point deviations are shown; these are not the
standardized cross-model effects available in the source table.
NHPI means Native Hawaiian / Pacific Islander; AIAN means American Indian /
Alaska Native. Define these abbreviations in the paper caption.

**Technical stability:** ten points, two per model. A filled circle denotes
`mean_within_resume_sd`, the average SD across each resume's 54 variants. An open
diamond denotes `between_resume_sd_of_means`, the SD across 100 resume means.
The compact legend uses “Within-resume SD” and “Between-resume SD”; the full
definitions above still apply. Model colors and labels match the demographic figure.
No connecting lines or uncertainty intervals are added; neither point represents an individual observation.
The horizontal scale starts at zero. Within-resume identity variation does not
measure randomness across repeated calls to an identical prompt.

## Validation and Visual Review

The loaders reject missing columns/required values, duplicate keys, unexpected or
missing models/categories, nonnumeric/nonfinite values, unordered CIs, and negative
SDs. All selected inputs are validated before any figure is exported. Exactly
60 demographic estimates and five technical rows are required. Optional unused
columns can be empty. No CIs or other summary statistics are recomputed.

On 2026-11-06, the figures were rendered with the environment above. Checks compared
all 60 point positions, all 60 whisker endpoint pairs, and all ten technical points
to their CSV fields, and exercised invalid-input failures. Vector structure, physical
page dimensions, embedded PDF fonts, PNG dimensions, clipping, and deterministic
exports were checked. Color and grayscale previews were inspected, including
100-DPI page-size previews. Preview images on a screen cannot guarantee an exact
physical print size; verify the intended widths in the manuscript proof.

Observed differences are descriptive results of this prompt condition; neither
confidence intervals nor these graphics establish discrimination or causal mechanisms.
There are no significance stars or added thresholds. The existing approximate
CIs retain the limitations documented in the analysis README.

## Maintenance

Keep new figures as separate functions in `plot.py`, using the shared `STYLE`,
`MODELS`, `LABELS`, `COLORS`, and explicit demographic ordering. Add a validating
loader for each new input schema and extend the CLI only as needed. Each function
should return a figure and use authoritative CSV values directly. Use the common
export function for fixed-size vector outputs and 300-DPI previews. Review color
and grayscale renders at publication size after layout changes.

### Layout refinement — 2026-11-06

Reduced the demographic figure height from 5.85 to 5.35 inches while keeping its
6.30-inch width, fonts, marker sizes, whiskers, model encoding, and ordering. Reduced
the technical figure height from 2.85 to 2.60 inches, shortened the two legend labels,
and tightened the gap below the legend; width remains 3.03 inches. Compared the
previous and revised page-size previews, including revised grayscale previews.
The revised layouts reduce empty space without shrinking typography. Further
height compression was not applied to preserve separation among the five estimates
per demographic category. All plotted values and interval endpoints remain identical.

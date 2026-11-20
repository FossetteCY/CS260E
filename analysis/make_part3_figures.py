
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from matplotlib.lines import Line2D


# ============================================================
# 1. Paths and data
# ============================================================

ROOT = Path(__file__).resolve().parent
RESULT_DIR = ROOT / "results" / "part3_validation"
FIG_DIR = RESULT_DIR / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

matched = pd.read_csv(RESULT_DIR / "matched_contrasts.csv")
five_max = pd.read_csv(RESULT_DIR / "five_model_max.csv")


# ============================================================
# 2. Global style
# ============================================================

GRAY = "#8996A7"
TEAL = "#167D83"
DARK = "#273444"
MUTED = "#687586"
GRID = "#E8ECF0"

MODEL_ORDER = [
    "haiku-5-5-high",
    "sonnet-5-5-high",
    "opus-5-5-high",
    "gpt-6.1-sol-high",
    "gpt-6.1-terra-high",
]

MODEL_NAMES = {
    "haiku-5-5-high": "Haiku",
    "sonnet-5-5-high": "Sonnet",
    "opus-5-5-high": "Opus",
    "gpt-6.1-sol-high": "GPT-6.1 Sol",
    "gpt-6.1-terra-high": "GPT-6.1 Terra",
}

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.titlesize": 15,
    "axes.labelsize": 10,
    "axes.edgecolor": GRID,
    "axes.labelcolor": DARK,
    "text.color": DARK,
    "xtick.color": MUTED,
    "ytick.color": DARK,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
    "savefig.dpi": 300,
    "pdf.fonttype": 42,
})


def save_figure(fig, filename):
    """Save both high-resolution PNG and vector PDF."""
    for ext in ("png", "pdf"):
        fig.savefig(
            FIG_DIR / f"{filename}.{ext}",
            bbox_inches="tight",
            pad_inches=0.18,
            dpi=300,
        )
    plt.close(fig)


def clean_axes(ax):
    """Remove unnecessary borders and add subtle gridlines."""
    for spine in ax.spines.values():
        spine.set_visible(False)

    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(axis="both", length=0)


def get_subset(contrast, metric):
    """Get a model comparison in a consistent order."""
    df = matched[
        (matched["contrast"] == contrast) &
        (matched["metric"] == metric)
    ].copy()

    df["model"] = pd.Categorical(
        df["model"],
        categories=MODEL_ORDER,
        ordered=True,
    )

    df = df.sort_values("model").reset_index(drop=True)
    return df


# ============================================================
# 3. Shared figure: paired estimates with 95% CI
# ============================================================

def plot_model_comparison(
    df,
    title,
    subtitle,
    xlabel,
    filename,
):
    fig, ax = plt.subplots(figsize=(9.0, 4.6))

    # Space between models
    y = np.arange(len(df))[::-1] * 0.9

    for i, row in df.iterrows():
        yi = y[i]

        baseline = float(row["baseline_gap"])
        patched = float(row["patched_gap"])

        # Connect baseline and patched estimates
        ax.plot(
            [baseline, patched],
            [yi, yi],
            color="#DCE2E8",
            linewidth=1.6,
            zorder=1,
        )

        # Offset confidence intervals to prevent overlap
        estimates = [
            (
                baseline,
                float(row["baseline_ci_low"]),
                float(row["baseline_ci_high"]),
                GRAY,
                yi + 0.12,
            ),
            (
                patched,
                float(row["patched_ci_low"]),
                float(row["patched_ci_high"]),
                TEAL,
                yi - 0.12,
            ),
        ]

        for value, low, high, color, ypos in estimates:
            ax.errorbar(
                value,
                ypos,
                xerr=[[value - low], [high - value]],
                fmt="o",
                markersize=6.5,
                capsize=3,
                capthick=1.3,
                elinewidth=2,
                color=color,
                zorder=4,
            )

    names = [
        MODEL_NAMES.get(str(model), str(model))
        for model in df["model"]
    ]

    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=11)
    ax.set_ylim(y[-1] - 0.6, y[0] + 0.65)

    # Zero means no average demographic gap
    ax.axvline(
        0,
        color="#9AA5B1",
        linewidth=1.1,
        linestyle="--",
        zorder=2,
    )

    ax.set_xlabel(xlabel, labelpad=13)

    clean_axes(ax)

    # Title and subtitle
    fig.text(
        0.13, 0.99, title,
        fontsize=15,
        fontweight="semibold",
        ha="left",
        va="top",
    )

    fig.text(
        0.13, 0.925, subtitle,
        fontsize=9.5,
        color=MUTED,
        ha="left",
    )

    # Legend
    handles = [
        Line2D(
            [0], [0],
            marker="o",
            color=GRAY,
            linestyle="-",
            markersize=6,
            label="Baseline",
        ),
        Line2D(
            [0], [0],
            marker="o",
            color=TEAL,
            linestyle="-",
            markersize=6,
            label="Patched",
        ),
    ]

    ax.legend(
        handles=handles,
        frameon=False,
        loc="upper right",
        ncol=2,
        bbox_to_anchor=(1.0, 1.15),
        fontsize=9,
    )

    fig.subplots_adjust(
        left=0.18,
        right=0.97,
        top=0.78,
        bottom=0.17,
    )

    save_figure(fig, filename)


# ============================================================
# Figure 1 — Age bias in ramp-up score
# ============================================================

age_df = get_subset("age_ramp", "p_ramp_up")

plot_model_comparison(
    df=age_df,
    title="Age bias in ramp-up assessment",
    subtitle="23-year-old minus 42-year-old | 50 resumes",
    xlabel="Mean score difference (points)",
    filename="fig1_age_ramp_gap",
)


# ============================================================
# Figure 2 — Asian–White English score gap
# ============================================================

race_df = get_subset(
    "asian_white_english",
    "c_english",
)

plot_model_comparison(
    df=race_df,
    title="Race-associated gap in English assessment",
    subtitle="Asian minus White | 50 resumes",
    xlabel="Mean score difference (points)",
    filename="fig2_asian_white_english_gap",
)


# ============================================================
# Figure 3 — Gender gap under max-of-five
# ============================================================

df3 = five_max[
    (five_max["contrast"] == "gender_total") &
    (five_max["metric"] == "total")
]

if not df3.empty:
    r = df3.iloc[0]

    baseline = float(r["baseline_max_gap"])
    patched = float(r["patched_max_gap"])

    fig, ax = plt.subplots(figsize=(8, 3.6))

    rows = [
        (
            "Baseline",
            baseline,
            float(r["baseline_max_ci_low"]),
            float(r["baseline_max_ci_high"]),
            GRAY,
            1,
        ),
        (
            "Patched",
            patched,
            float(r["patched_max_ci_low"]),
            float(r["patched_max_ci_high"]),
            TEAL,
            0,
        ),
    ]

    for name, value, low, high, color, y in rows:
        ax.errorbar(
            value,
            y,
            xerr=[[value - low], [high - value]],
            fmt="o",
            markersize=9,
            capsize=5,
            capthick=1.5,
            elinewidth=2.8,
            color=color,
            zorder=4,
        )

        ax.annotate(
            f"{value:+.2f}",
            (value, y),
            xytext=(0, 15),
            textcoords="offset points",
            ha="center",
            fontsize=11,
            fontweight="semibold",
            color=color,
        )

    ax.set_yticks([1, 0])
    ax.set_yticklabels(
        ["Baseline", "Patched"],
        fontsize=12,
    )

    ax.set_ylim(-0.55, 1.55)

    all_bounds = [
        float(r["baseline_max_ci_low"]),
        float(r["baseline_max_ci_high"]),
        float(r["patched_max_ci_low"]),
        float(r["patched_max_ci_high"]),
        0,
    ]

    ax.set_xlim(min(all_bounds) - 0.15, 0.15)

    ax.axvline(
        0,
        color="#9AA5B1",
        linestyle="--",
        linewidth=1,
    )

    clean_axes(ax)

    ax.set_xlabel(
        "Mean total-score gap (male minus female)",
        labelpad=12,
    )

    reduction = (
        (abs(baseline) - abs(patched))
        / abs(baseline) * 100
        if baseline != 0 else np.nan
    )

    fig.text(
        0.16, 0.97,
        "Gender gap under max-of-five",
        fontsize=15,
        fontweight="semibold",
        va="top",
    )

    fig.text(
        0.16, 0.88,
        "Mean difference with 95% confidence intervals",
        color=MUTED,
        fontsize=9.5,
    )

    fig.text(
        0.95, 0.88,
        f"{reduction:.1f}% smaller absolute gap",
        ha="right",
        color=TEAL,
        fontsize=10,
        fontweight="semibold",
    )

    fig.subplots_adjust(
        left=0.16,
        right=0.95,
        top=0.72,
        bottom=0.22,
    )

    save_figure(
        fig,
        "fig3_gender_total_max_of_five",
    )


# ============================================================
# Figure 4 — Bias reduction heatmap
# ============================================================

# Positive = smaller absolute gap
# Negative = larger absolute gap

selected = [
    ("age_ramp", "p_ramp_up", "Age / ramp-up"),
    (
        "asian_white_english",
        "c_english",
        "Race / English",
    ),
]

records = []

for contrast, metric, label in selected:
    subset = get_subset(contrast, metric)

    for _, row in subset.iterrows():
        records.append({
            "Bias": label,
            "Model": MODEL_NAMES[str(row["model"])],
            "Reduction": float(
                row["absolute_gap_reduction"]
            ),
        })

heat_df = pd.DataFrame(records)

heat = heat_df.pivot(
    index="Bias",
    columns="Model",
    values="Reduction",
)

heat = heat.reindex(
    index=[item[2] for item in selected],
    columns=[MODEL_NAMES[m] for m in MODEL_ORDER],
)

fig, ax = plt.subplots(figsize=(9, 3.6))

limit = max(
    0.5,
    np.nanmax(np.abs(heat.values)),
)

# Red = worse, white = unchanged, teal = improved
norm = TwoSlopeNorm(
    vmin=-limit,
    vcenter=0,
    vmax=limit,
)

im = ax.imshow(
    heat.values,
    cmap="RdBu",
    norm=norm,
    aspect="auto",
)

ax.set_xticks(np.arange(len(heat.columns)))
ax.set_xticklabels(
    heat.columns,
    fontsize=10,
)

ax.set_yticks(np.arange(len(heat.index)))
ax.set_yticklabels(
    heat.index,
    fontsize=11,
)

ax.tick_params(length=0)

# Cell labels
for i in range(heat.shape[0]):
    for j in range(heat.shape[1]):
        value = heat.iloc[i, j]

        text_color = (
            "white"
            if abs(value) > limit * 0.6
            else DARK
        )

        ax.text(
            j, i,
            f"{value:+.2f}",
            ha="center",
            va="center",
            color=text_color,
            fontsize=11,
            fontweight="medium",
        )

# Minimal cell separators
ax.set_xticks(
    np.arange(-0.5, heat.shape[1], 1),
    minor=True,
)
ax.set_yticks(
    np.arange(-0.5, heat.shape[0], 1),
    minor=True,
)

ax.grid(
    which="minor",
    color="white",
    linewidth=3,
)

ax.tick_params(
    which="minor",
    bottom=False,
    left=False,
)

for spine in ax.spines.values():
    spine.set_visible(False)

fig.text(
    0.18, 0.97,
    "Change in absolute demographic gaps",
    fontsize=15,
    fontweight="semibold",
    va="top",
)

fig.text(
    0.18, 0.85,
    "Positive values indicate improvement; negative values indicate worsening",
    fontsize=9.5,
    color=MUTED,
)

fig.subplots_adjust(
    left=0.18,
    right=0.96,
    top=0.70,
    bottom=0.18,
)

save_figure(
    fig,
    "fig4_bias_reduction_heatmap",
)


# ============================================================
# 4. Done
# ============================================================

print("\nFigures successfully generated:")
for path in sorted(FIG_DIR.glob("*")):
    if path.suffix in {".png", ".pdf"}:
        print(f"  {path.name}")

print(f"\nOutput directory: {FIG_DIR}")

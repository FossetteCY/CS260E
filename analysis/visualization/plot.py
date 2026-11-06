#!/usr/bin/env python3
"""Render research figures from validated CSV summaries; never recompute statistics."""

import argparse
import csv
import math
import os
from pathlib import Path
import sys

# Keep Matplotlib's font cache with ignored local outputs, including in sandboxes.
REPO = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(REPO / "analysis/output/.matplotlib"))
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.ticker import MaxNLocator, MultipleLocator
except ImportError as exc:
    raise SystemExit(
        "Matplotlib is required. Use an existing compatible environment or install "
        "analysis/visualization/requirements.txt in a project-local virtual environment."
    ) from exc

MODELS = (
    "haiku-5-5-high", "sonnet-5-5-high", "opus-5-5-high",
    "gpt-6.1-sol-high", "gpt-6.1-terra-high",
)
LABELS = ("Haiku 5.5", "Sonnet 5.5", "Opus 5.5", "GPT-6.1 Sol", "GPT-6.1 Terra")
COLORS = ("#426B8B", "#A66735", "#56816B", "#8C637D", "#6D6A94")
MARKERS = ("o", "s", "D", "^", "v")
SECTIONS = (
    ("gender", "Gender", (("male", "Male"), ("female", "Female"), ("nonbinary", "Nonbinary"))),
    ("race", "Race", (("white", "White"), ("black", "Black"), ("asian", "Asian"),
                      ("nhpi", "NHPI"), ("aian", "AIAN"), ("multi", "Multiracial"))),
    ("age_group", "Age", (("22-24", "22–24"), ("25-35", "25–35"), ("35+", "35+"))),
)
STYLE = {
    "font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans"],
    "font.size": 8.5, "axes.labelsize": 8.5, "xtick.labelsize": 8,
    "ytick.labelsize": 8.5, "legend.fontsize": 8,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.spines.left": False, "axes.edgecolor": "0.55", "axes.linewidth": 0.5,
    "xtick.color": "0.3", "ytick.color": "0.2", "text.color": "0.15",
    "axes.labelcolor": "0.2", "xtick.major.width": 0.5, "xtick.major.size": 3,
    "ytick.major.size": 0, "savefig.facecolor": "white",
    "pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "none",
    "svg.hashsalt": "cs260e-figures", "path.simplify": False,
}


def read_csv(path, required):
    """Read a table without losing IDs; reject ambiguous or incomplete schemas."""
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames or []
        if len(columns) != len(set(columns)):
            raise ValueError(f"{path}: duplicate column names")
        missing = set(required) - set(columns)
        if missing:
            raise ValueError(f"{path}: missing columns: {', '.join(sorted(missing))}")
        rows = []
        for line, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()) or any(
                    not row[field].strip() for field in required):
                raise ValueError(f"{path}:{line}: missing value or incorrect row width")
            rows.append(row)
    return rows


def number(row, field, context):
    try:
        value = float(row[field])
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{context}: {field} must be numeric") from exc
    if not math.isfinite(value):
        raise ValueError(f"{context}: {field} must be finite")
    return value


def load_demographic(path):
    fields = ("model", "factor", "group", "metric", "mean_offset", "ci95_low", "ci95_high")
    rows = read_csv(path, fields)
    expected = {(model, factor, group) for model in MODELS
                for factor, _, groups in SECTIONS for group, _ in groups}
    data = {}
    for row in rows:
        if row["metric"] != "total":
            continue
        key = (row["model"], row["factor"], row["group"])
        if key not in expected:
            raise ValueError(f"{path}: unexpected model/factor/group: {key}")
        if key in data:
            raise ValueError(f"{path}: duplicate total-score estimate: {key}")
        values = tuple(number(row, field, key) for field in fields[-3:])
        avg, low, high = values
        if not low <= avg <= high:
            raise ValueError(f"{path}: confidence interval does not contain mean: {key}")
        data[key] = values
    if set(data) != expected:
        raise ValueError(f"{path}: expected 60 total-score estimates; missing: {sorted(expected-set(data))}")
    return data


def load_technical(path):
    fields = ("model", "mean_within_resume_sd", "between_resume_sd_of_means")
    data = {}
    for row in read_csv(path, fields):
        model = row["model"]
        if model not in MODELS:
            raise ValueError(f"{path}: unexpected model: {model}")
        if model in data:
            raise ValueError(f"{path}: duplicate model: {model}")
        values = tuple(number(row, field, model) for field in fields[1:])
        if min(values) < 0:
            raise ValueError(f"{path}: negative standard deviation: {model}")
        data[model] = values
    if set(data) != set(MODELS):
        raise ValueError(f"{path}: expected five models; missing: {sorted(set(MODELS)-set(data))}")
    return data


def demographic_offsets(data):
    """Sixty CSV means and their existing CIs, on one shared quantitative axis."""
    fig, ax = plt.subplots(figsize=(6.30, 5.35))
    fig.subplots_adjust(left=0.175, right=0.98, bottom=0.115, top=0.88)
    positions, names = [], []
    y = 0.0
    for section_index, (factor, title, groups) in enumerate(SECTIONS):
        if section_index:
            ax.axhline(y - 0.55, color="0.85", linewidth=0.45, zorder=0)
        ax.text(-0.175, y, title, transform=ax.get_yaxis_transform(),
                fontsize=8.8, fontweight="semibold", va="center", clip_on=False)
        y += 0.85
        for group, label in groups:
            positions.append(y)
            names.append(label)
            for j, model in enumerate(MODELS):
                avg, low, high = data[(model, factor, group)]
                yp = y + (j - 2) * 0.14
                # Endpoints are the CSV bounds directly, without recomputing CIs.
                ax.hlines(yp, low, high, colors=COLORS[j], linewidth=0.75, zorder=2)
                ax.plot(avg, yp, marker=MARKERS[j], color=COLORS[j], markersize=3.2,
                        markeredgewidth=0.45, linestyle="none", zorder=3)
            y += 1
        y += 0.35
    low = min(values[1] for values in data.values())
    high = max(values[2] for values in data.values())
    extent = max(abs(low), abs(high))
    ax.set_xlim(-extent * 1.10, extent * 1.10)
    ax.set_ylim(y - 0.85, -0.45)
    ax.set_yticks(positions, names)
    ax.tick_params(axis="y", pad=7)
    ax.axvline(0, color="0.55", linewidth=0.65, zorder=1)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=7, min_n_ticks=5))
    ax.set_xlabel("Within-resume total-score deviation (points)", labelpad=7)
    handles = [Line2D([], [], marker=marker, color=color, markersize=3.7,
                      linewidth=0.75, label=label)
               for label, color, marker in zip(LABELS, COLORS, MARKERS)]
    fig.legend(handles=[handles[i] for i in (0, 3, 1, 4, 2)],
               loc="upper center", bbox_to_anchor=(0.53, 0.993),
               ncol=3, frameon=False, handlelength=1.4, columnspacing=1.5,
               handletextpad=0.5, labelspacing=0.65)
    return fig


def technical_stability(data):
    """Two descriptive SDs per model; no connecting lines or invented intervals."""
    fig, ax = plt.subplots(figsize=(3.03, 2.60))
    fig.subplots_adjust(left=0.345, right=0.97, bottom=0.23, top=0.79)
    for j, model in enumerate(MODELS):
        within, between = data[model]
        ax.plot(within, j, marker="o", color=COLORS[j], markersize=4,
                markeredgewidth=0.65, linestyle="none")
        ax.plot(between, j, marker="D", markerfacecolor="white", markeredgecolor=COLORS[j],
                markersize=4, markeredgewidth=0.85, linestyle="none")
    ax.set_yticks(range(len(MODELS)), LABELS)
    ax.tick_params(axis="y", pad=5)
    ax.set_ylim(len(MODELS) - 0.45, -0.55)
    ax.set_xlim(0, max(max(values) for values in data.values()) * 1.10)
    ax.xaxis.set_major_locator(MultipleLocator(1))
    ax.set_axisbelow(True)
    ax.grid(axis="x", color="0.9", linewidth=0.45)
    ax.set_xlabel("Technical-score SD (points)", labelpad=7)
    handles = [
        Line2D([], [], marker="o", color="0.35", linestyle="none", markersize=4,
               label="Within-resume SD"),
        Line2D([], [], marker="D", markeredgecolor="0.35", markerfacecolor="white",
               linestyle="none", markersize=4, label="Between-resume SD"),
    ]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.035, 0.995),
               frameon=False, handlelength=1.2, handletextpad=0.4, labelspacing=0.65)
    return fig


def export(fig, out_dir, stem):
    # Fixed canvas dimensions preserve actual publication size; margins are designed above.
    for extension in ("pdf", "svg", "png"):
        metadata = ({"CreationDate": None, "ModDate": None} if extension == "pdf"
                    else {"Date": None} if extension == "svg" else {})
        path = out_dir / f"{stem}.{extension}"
        fig.savefig(path, dpi=300, metadata=metadata)
        print(path)
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=REPO / "analysis/results")
    parser.add_argument("--out-dir", type=Path, default=REPO / "analysis/output/figures")
    parser.add_argument("--figure", choices=("all", "demographic", "technical"), default="all")
    args = parser.parse_args(argv)
    results, out = args.results_dir.resolve(), args.out_dir.resolve()
    if out == results or results in out.parents:
        parser.error("Output must be outside the validated results directory")
    try:
        # Validate every selected input before writing any figure.
        demographic = (load_demographic(results / "demographic_group_offsets.csv")
                       if args.figure in ("all", "demographic") else None)
        technical = (load_technical(results / "technical_baseline_summary.csv")
                     if args.figure in ("all", "technical") else None)
        out.mkdir(parents=True, exist_ok=True)
        with plt.rc_context(STYLE):
            if demographic is not None:
                print(f"Validated {len(demographic)} demographic estimates (CSV means and CIs).")
                export(demographic_offsets(demographic), out, "demographic_offsets")
            if technical is not None:
                print(f"Validated {len(technical)} models, two descriptive SDs each.")
                export(technical_stability(technical), out, "technical_stability")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

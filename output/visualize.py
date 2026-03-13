"""Quality trend visualizations and evaluation report generation.

Produces (v1):
  - output/quality_trends.png   (2x2 subplot dashboard)
  - output/radar_{ad_id}.png    (per-ad spider chart)
  - data/evaluation_report.json (machine-readable stats)
  - data/evaluation_report.md   (human-readable summary)

Produces (v2, with --v2 flag):
  - output/visual_quality_trends.png        (2x2 multimodal dashboard)
  - output/ad_showcase.png                  (top-N ad composite)
  - data/multimodal_evaluation_report.json  (machine-readable stats)
  - data/multimodal_evaluation_report.md    (human-readable summary)

Usage:
    python -m output.visualize          # v1 only
    python -m output.visualize --v2     # v1 + v2 multimodal
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, stdev

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from generate.models import AdRecord, MultiModalAdRecord
from iterate.multimodal_pipeline import load_multimodal_library
from output.batch_runner import load_ad_library
from output.generate_report import DIMENSION_LABELS, SEGMENT_LABELS

_ROOT = Path(__file__).resolve().parent.parent
_OUT = _ROOT / "output"
_DATA = _ROOT / "data"

DIMENSIONS = [
    "clarity",
    "value_proposition",
    "call_to_action",
    "brand_voice",
    "emotional_resonance",
]

PALETTE = ["#4C72B0", "#55A868", "#C44E52", "#8172B2", "#CCB974"]
THRESHOLD = 7.0

VISUAL_DIMENSIONS = [
    "brand_consistency",
    "engagement_potential",
    "text_image_coherence",
    "technical_quality",
]
VISUAL_DIMENSION_LABELS = {
    "brand_consistency": "Brand Consistency",
    "engagement_potential": "Engagement Potential",
    "text_image_coherence": "Text–Image Coherence",
    "technical_quality": "Technical Quality",
}
VISUAL_THRESHOLD = 6.5
SEGMENT_COLORS = {"anxious_parents": "#4C72B0", "stressed_students": "#55A868", "comparison_shoppers": "#C44E52"}


def _dim_scores(record: AdRecord) -> dict[str, int]:
    return {d: getattr(record.evaluation, d).score for d in DIMENSIONS}


def _total_cost(record: AdRecord) -> float:
    return record.generation_cost_usd + record.evaluation_cost_usd


# ---------------------------------------------------------------------------
# 1. 2x2 Quality trends dashboard
# ---------------------------------------------------------------------------


def plot_quality_trends(
    ad_library_path: str = "data/ad_library.json",
) -> Path:
    """Create a 2x2 subplot figure and save to output/quality_trends.png."""
    records = load_ad_library(ad_library_path)

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("Ad Engine — Quality Trends Dashboard", fontsize=16, fontweight="bold")

    _plot_score_per_cycle(axes[0, 0], records)
    _plot_dimension_averages(axes[0, 1], records)
    _plot_pass_rate_by_segment(axes[1, 0], records)
    _plot_cost_by_iterations(axes[1, 1], records)

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out = _OUT / "quality_trends.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def _plot_score_per_cycle(ax: plt.Axes, records: list[AdRecord]) -> None:
    """Top-left: average aggregate score grouped by iteration_cycle."""
    by_cycle: dict[int, list[float]] = defaultdict(list)
    for r in records:
        by_cycle[r.iteration_cycle].append(r.evaluation.aggregate_score)

    cycles = sorted(by_cycle)
    means = [mean(by_cycle[c]) for c in cycles]

    ax.plot(cycles, means, "o-", color=PALETTE[0], linewidth=2, markersize=8)
    for c, m in zip(cycles, means):
        ax.annotate(f"{m:.2f}", (c, m), textcoords="offset points", xytext=(0, 10), ha="center", fontsize=9)

    ax.axhline(THRESHOLD, color="#C44E52", linestyle="--", linewidth=1.5, label=f"Threshold ({THRESHOLD})")
    ax.set_xlabel("Iteration Cycles Needed")
    ax.set_ylabel("Avg Aggregate Score")
    ax.set_title("Score by Iteration Cycle Count")
    ax.set_xticks(cycles)
    ax.set_ylim(5, 10)
    ax.legend(fontsize=9)


def _plot_dimension_averages(ax: plt.Axes, records: list[AdRecord]) -> None:
    """Top-right: average score per dimension (bar chart)."""
    avgs = []
    labels = []
    for d in DIMENSIONS:
        scores = [getattr(r.evaluation, d).score for r in records]
        avgs.append(mean(scores))
        labels.append(DIMENSION_LABELS.get(d, d))

    x = np.arange(len(DIMENSIONS))
    bars = ax.bar(x, avgs, color=PALETTE, width=0.6)

    for bar, val in zip(bars, avgs):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1, f"{val:.1f}", ha="center", fontsize=9)

    ax.axhline(THRESHOLD, color="#C44E52", linestyle="--", linewidth=1.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=9)
    ax.set_ylabel("Avg Score")
    ax.set_title("Avg Score by Dimension")
    ax.set_ylim(0, 10)


def _plot_pass_rate_by_segment(ax: plt.Axes, records: list[AdRecord]) -> None:
    """Bottom-left: pass rate per audience segment."""
    seg_total: dict[str, int] = defaultdict(int)
    seg_passed: dict[str, int] = defaultdict(int)
    for r in records:
        seg = r.brief.audience_segment
        seg_total[seg] += 1
        if r.evaluation.passes_threshold:
            seg_passed[seg] += 1

    segments = sorted(seg_total)
    rates = [seg_passed[s] / seg_total[s] * 100 for s in segments]
    labels = [SEGMENT_LABELS.get(s, s) for s in segments]

    x = np.arange(len(segments))
    bars = ax.bar(x, rates, color=PALETTE[: len(segments)], width=0.5)

    for bar, val in zip(bars, rates):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1, f"{val:.0f}%", ha="center", fontsize=9)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("Pass Rate (%)")
    ax.set_title("Pass Rate by Audience Segment")
    ax.set_ylim(0, 115)


def _plot_cost_by_iterations(ax: plt.Axes, records: list[AdRecord]) -> None:
    """Bottom-right: average cost grouped by iteration count."""
    by_cycle: dict[int, list[float]] = defaultdict(list)
    for r in records:
        by_cycle[r.iteration_cycle].append(_total_cost(r))

    cycles = sorted(by_cycle)
    costs = [mean(by_cycle[c]) for c in cycles]
    labels = [f"{c} cycle{'s' if c != 1 else ''}" for c in cycles]

    x = np.arange(len(cycles))
    bars = ax.bar(x, costs, color=PALETTE[: len(cycles)], width=0.5)

    for bar, val in zip(bars, costs):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.001, f"${val:.3f}", ha="center", fontsize=9)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("Avg Cost (USD)")
    ax.set_title("Cost per Ad by Iteration Count")


# ---------------------------------------------------------------------------
# 2. Radar / spider chart for a single ad
# ---------------------------------------------------------------------------


def plot_dimension_radar(record: AdRecord) -> Path:
    """Create a radar chart for one ad's dimension scores."""
    plt.style.use("seaborn-v0_8-whitegrid")

    scores = _dim_scores(record)
    labels = [DIMENSION_LABELS.get(d, d) for d in DIMENSIONS]
    values = [scores[d] for d in DIMENSIONS]

    angles = np.linspace(0, 2 * np.pi, len(DIMENSIONS), endpoint=False).tolist()
    values_closed = values + [values[0]]
    angles_closed = angles + [angles[0]]

    fig, ax = plt.subplots(figsize=(6, 6), subplot_kw={"polar": True})
    ax.plot(angles_closed, values_closed, "o-", linewidth=2, color=PALETTE[0])
    ax.fill(angles_closed, values_closed, alpha=0.25, color=PALETTE[0])

    ax.set_thetagrids(np.degrees(angles), labels, fontsize=10)
    ax.set_ylim(0, 10)
    ax.set_yticks(range(0, 11, 2))
    ax.set_title(
        f"Ad {record.ad_id[:8]} — Score {record.evaluation.aggregate_score:.2f}",
        fontsize=13,
        fontweight="bold",
        pad=20,
    )

    out = _OUT / f"radar_{record.ad_id}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# 3. Evaluation report (JSON + Markdown)
# ---------------------------------------------------------------------------


def generate_evaluation_report(
    ad_library_path: str = "data/ad_library.json",
) -> tuple[Path, Path]:
    """Produce data/evaluation_report.json and data/evaluation_report.md."""
    records = load_ad_library(ad_library_path)

    total = len(records)
    passed = sum(1 for r in records if r.evaluation.passes_threshold)
    all_scores = [r.evaluation.aggregate_score for r in records]
    total_cost = sum(_total_cost(r) for r in records)
    cost_passing = sum(_total_cost(r) for r in records if r.evaluation.passes_threshold)

    dim_stats: dict[str, dict] = {}
    for d in DIMENSIONS:
        vals = [getattr(r.evaluation, d).score for r in records]
        dim_stats[d] = {
            "avg": round(mean(vals), 2),
            "stdev": round(stdev(vals), 2) if len(vals) > 1 else 0.0,
        }

    seg_total: dict[str, int] = defaultdict(int)
    seg_passed: dict[str, int] = defaultdict(int)
    for r in records:
        seg = r.brief.audience_segment
        seg_total[seg] += 1
        if r.evaluation.passes_threshold:
            seg_passed[seg] += 1

    cycle1_scores = [r.evaluation.aggregate_score for r in records if r.iteration_cycle == 1]
    max_cycle = max(r.iteration_cycle for r in records) if records else 1
    final_cycle_scores = [r.evaluation.aggregate_score for r in records if r.iteration_cycle == max_cycle]

    report = {
        "total_ads": total,
        "passed": passed,
        "pass_rate": round(passed / total, 4) if total else 0,
        "avg_score": round(mean(all_scores), 2) if all_scores else 0,
        "min_score": round(min(all_scores), 2) if all_scores else 0,
        "max_score": round(max(all_scores), 2) if all_scores else 0,
        "per_dimension": dim_stats,
        "per_segment_pass_rate": {
            seg: round(seg_passed[seg] / seg_total[seg], 4) for seg in sorted(seg_total)
        },
        "total_cost_usd": round(total_cost, 4),
        "cost_per_ad": round(total_cost / total, 4) if total else 0,
        "cost_per_passing_ad": round(cost_passing / passed, 4) if passed else 0,
        "quality_improvement": {
            "cycle_1_avg": round(mean(cycle1_scores), 2) if cycle1_scores else None,
            "final_cycle_avg": round(mean(final_cycle_scores), 2) if final_cycle_scores else None,
        },
    }

    _DATA.mkdir(parents=True, exist_ok=True)

    json_path = _DATA / "evaluation_report.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)

    md_path = _DATA / "evaluation_report.md"
    md_path.write_text(_build_report_md(report))

    return json_path, md_path


def _build_report_md(r: dict) -> str:
    lines: list[str] = []
    lines.append("# Evaluation Report\n")

    lines.append("## Overview\n")
    lines.append(f"- **Total ads:** {r['total_ads']}")
    lines.append(f"- **Pass rate:** {r['pass_rate']:.0%} ({r['passed']}/{r['total_ads']})")
    lines.append(f"- **Avg aggregate score:** {r['avg_score']}")
    lines.append(f"- **Score range:** {r['min_score']} -- {r['max_score']}")
    lines.append(f"- **Total cost:** ${r['total_cost_usd']:.2f}")
    lines.append(f"- **Cost per ad:** ${r['cost_per_ad']:.4f}")
    lines.append(f"- **Cost per passing ad:** ${r['cost_per_passing_ad']:.4f}")
    lines.append("")

    qi = r["quality_improvement"]
    if qi.get("cycle_1_avg") is not None and qi.get("final_cycle_avg") is not None:
        lines.append("## Quality Improvement\n")
        lines.append(f"- Ads completing in cycle 1 averaged **{qi['cycle_1_avg']}**")
        lines.append(f"- Ads requiring max cycles averaged **{qi['final_cycle_avg']}**")
        lines.append("")

    lines.append("## Per-Dimension Breakdown\n")
    lines.append("| Dimension | Avg | Std Dev |")
    lines.append("|---|---|---|")
    for d in DIMENSIONS:
        s = r["per_dimension"][d]
        label = DIMENSION_LABELS.get(d, d)
        lines.append(f"| {label} | {s['avg']} | {s['stdev']} |")
    lines.append("")

    lines.append("## Pass Rate by Segment\n")
    lines.append("| Segment | Pass Rate |")
    lines.append("|---|---|")
    for seg, rate in r["per_segment_pass_rate"].items():
        label = SEGMENT_LABELS.get(seg, seg)
        lines.append(f"| {label} | {rate:.0%} |")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. v2 — Multimodal visual quality trends (2x2 dashboard)
# ---------------------------------------------------------------------------


def plot_visual_quality_trends(
    library_path: str = "data/multimodal_ad_library.json",
) -> Path:
    """Create a 2x2 multimodal dashboard and save to output/visual_quality_trends.png."""
    records = load_multimodal_library(library_path)

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("Ad Engine — Multimodal Quality Dashboard", fontsize=16, fontweight="bold")

    _plot_text_vs_visual_scatter(axes[0, 0], records)
    _plot_visual_dimension_averages(axes[0, 1], records)
    _plot_winning_style_distribution(axes[1, 0], records)
    _plot_cost_breakdown(axes[1, 1], records)

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out = _OUT / "visual_quality_trends.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def _plot_text_vs_visual_scatter(
    ax: plt.Axes, records: list[MultiModalAdRecord]
) -> None:
    """Top-left: text aggregate vs visual aggregate scatter, colored by segment."""
    for r in records:
        seg = r.brief.audience_segment
        color = SEGMENT_COLORS.get(seg, "#999999")
        ax.scatter(
            r.text_record.evaluation.aggregate_score,
            r.winning_variant.visual_evaluation.visual_aggregate_score,
            c=color,
            s=80,
            edgecolors="white",
            linewidth=0.5,
            zorder=3,
        )

    ax.axvline(THRESHOLD, color="#C44E52", linestyle="--", linewidth=1, alpha=0.7, label=f"Text thresh ({THRESHOLD})")
    ax.axhline(VISUAL_THRESHOLD, color="#8172B2", linestyle="--", linewidth=1, alpha=0.7, label=f"Visual thresh ({VISUAL_THRESHOLD})")

    segments_seen = sorted({r.brief.audience_segment for r in records})
    for seg in segments_seen:
        label = SEGMENT_LABELS.get(seg, seg)
        ax.scatter([], [], c=SEGMENT_COLORS.get(seg, "#999"), label=label, s=50)

    ax.set_xlabel("Text Aggregate Score")
    ax.set_ylabel("Visual Aggregate Score")
    ax.set_title("Text vs Visual Score")
    ax.set_xlim(4, 10)
    ax.set_ylim(4, 10)
    ax.legend(fontsize=7, loc="lower right")


def _plot_visual_dimension_averages(
    ax: plt.Axes, records: list[MultiModalAdRecord]
) -> None:
    """Top-right: average score per visual dimension (bar chart)."""
    avgs = []
    labels = []
    for d in VISUAL_DIMENSIONS:
        scores = [
            getattr(r.winning_variant.visual_evaluation, d).score
            for r in records
        ]
        avgs.append(mean(scores))
        labels.append(VISUAL_DIMENSION_LABELS.get(d, d))

    x = np.arange(len(VISUAL_DIMENSIONS))
    bars = ax.bar(x, avgs, color=PALETTE[: len(VISUAL_DIMENSIONS)], width=0.6)

    for bar, val in zip(bars, avgs):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.1,
            f"{val:.1f}",
            ha="center",
            fontsize=9,
        )

    ax.axhline(VISUAL_THRESHOLD, color="#C44E52", linestyle="--", linewidth=1.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=9)
    ax.set_ylabel("Avg Score")
    ax.set_title("Avg Visual Dimension Score")
    ax.set_ylim(0, 10)


def _plot_winning_style_distribution(
    ax: plt.Axes, records: list[MultiModalAdRecord]
) -> None:
    """Bottom-left: winning style distribution (pie chart)."""
    style_counts = Counter(r.winning_variant.style for r in records)
    labels = list(style_counts.keys())
    sizes = list(style_counts.values())
    colors = PALETTE[: len(labels)]

    wedges, texts, autotexts = ax.pie(
        sizes,
        labels=labels,
        autopct="%1.0f%%",
        colors=colors,
        startangle=90,
        textprops={"fontsize": 9},
    )
    for t in autotexts:
        t.set_fontweight("bold")
    ax.set_title("Winning Style Distribution")


def _plot_cost_breakdown(
    ax: plt.Axes, records: list[MultiModalAdRecord]
) -> None:
    """Bottom-right: average per-ad cost breakdown (stacked bar)."""
    n = len(records)
    avg_text_gen = sum(r.text_record.generation_cost_usd for r in records) / n
    avg_text_eval = sum(r.text_record.evaluation_cost_usd for r in records) / n
    avg_img_gen = sum(
        sum(v.generation_cost_usd for v in r.all_variants) for r in records
    ) / n
    avg_img_eval = sum(
        sum(v.evaluation_cost_usd for v in r.all_variants) for r in records
    ) / n

    components = [avg_text_gen, avg_text_eval, avg_img_gen, avg_img_eval]
    labels = ["Text Gen", "Text Eval", "Image Gen", "Image Eval"]
    colors = PALETTE[:4]

    bottom = 0.0
    for val, label, color in zip(components, labels, colors):
        ax.bar("Avg Cost / Ad", val, bottom=bottom, color=color, label=label, width=0.4)
        if val > 0.001:
            ax.text(
                0,
                bottom + val / 2,
                f"${val:.4f}",
                ha="center",
                va="center",
                fontsize=8,
                fontweight="bold",
                color="white",
            )
        bottom += val

    ax.set_ylabel("Cost (USD)")
    ax.set_title("Avg Cost Breakdown per Ad")
    ax.legend(fontsize=8, loc="upper right")
    ax.set_xlim(-0.5, 0.5)


# ---------------------------------------------------------------------------
# 5. v2 — Ad showcase (top-N composite image)
# ---------------------------------------------------------------------------


def create_ad_showcase(
    library_path: str = "data/multimodal_ad_library.json",
    top_n: int = 5,
) -> Path:
    """Create a PIL composite showing the top N ads by combined_score."""
    records = load_multimodal_library(library_path)
    records.sort(key=lambda r: r.combined_score, reverse=True)

    thumb_size = 256
    row_height = thumb_size + 20
    text_col_width = 500
    canvas_width = thumb_size + text_col_width + 40
    padding = 10

    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16
        )
        font_sm = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13
        )
    except (OSError, IOError):
        font = ImageFont.load_default()
        font_sm = font

    rows: list[tuple[MultiModalAdRecord, Image.Image | None]] = []
    for r in records[:top_n]:
        img_path = _ROOT / r.winning_variant.image_path
        try:
            img = Image.open(img_path).convert("RGB")
            img.thumbnail((thumb_size, thumb_size), Image.LANCZOS)
        except (FileNotFoundError, OSError):
            img = None
        rows.append((r, img))

    if not rows:
        blank = Image.new("RGB", (canvas_width, 100), "white")
        out = _OUT / "ad_showcase.png"
        blank.save(out)
        return out

    canvas_height = len(rows) * row_height + padding * 2
    canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
    draw = ImageDraw.Draw(canvas)

    y = padding
    for idx, (record, thumb) in enumerate(rows):
        if thumb is not None:
            canvas.paste(thumb, (padding, y + (row_height - thumb.size[1]) // 2))

        tx = thumb_size + padding * 3
        ty = y + 10

        headline = record.text_record.generated_ad.headline
        draw.text((tx, ty), f"#{idx + 1}  {headline}", fill="black", font=font)
        ty += 24

        text_score = record.text_record.evaluation.aggregate_score
        vis_score = record.winning_variant.visual_evaluation.visual_aggregate_score
        lines = [
            f"Combined: {record.combined_score:.2f}  |  Text: {text_score:.2f}  |  Visual: {vis_score:.2f}",
            f"Style: {record.winning_variant.style}  |  Segment: {SEGMENT_LABELS.get(record.brief.audience_segment, record.brief.audience_segment)}",
            f"Cost: ${record.total_cost_usd:.4f}  |  Time: {record.pipeline_time_s:.1f}s",
        ]
        for line in lines:
            draw.text((tx, ty), line, fill="#444444", font=font_sm)
            ty += 20

        if idx < len(rows) - 1:
            line_y = y + row_height - 2
            draw.line([(padding, line_y), (canvas_width - padding, line_y)], fill="#DDDDDD", width=1)

        y += row_height

    out = _OUT / "ad_showcase.png"
    canvas.save(out, dpi=(150, 150))
    return out


# ---------------------------------------------------------------------------
# 6. v2 — Multimodal evaluation report (JSON + Markdown)
# ---------------------------------------------------------------------------


def generate_multimodal_report(
    library_path: str = "data/multimodal_ad_library.json",
) -> tuple[Path, Path]:
    """Produce multimodal evaluation report (JSON + Markdown)."""
    records = load_multimodal_library(library_path)
    n = len(records)

    text_scores = [r.text_record.evaluation.aggregate_score for r in records]
    visual_scores = [
        r.winning_variant.visual_evaluation.visual_aggregate_score
        for r in records
    ]
    combined_scores = [r.combined_score for r in records]

    text_passed = sum(1 for r in records if r.text_record.evaluation.passes_threshold)
    visual_passed = sum(
        1
        for r in records
        if r.winning_variant.visual_evaluation.passes_visual_threshold
    )
    combined_passed = sum(1 for r in records if r.combined_score >= 7.0)

    # Visual dimension stats
    vis_dim_stats: dict[str, dict] = {}
    for d in VISUAL_DIMENSIONS:
        vals = [
            getattr(r.winning_variant.visual_evaluation, d).score
            for r in records
        ]
        vis_dim_stats[d] = {
            "avg": round(mean(vals), 2),
            "stdev": round(stdev(vals), 2) if len(vals) > 1 else 0.0,
        }

    # Text-visual correlation (Pearson r via numpy)
    if n > 1:
        corr_matrix = np.corrcoef(text_scores, visual_scores)
        text_visual_corr = round(float(corr_matrix[0, 1]), 4)
    else:
        text_visual_corr = None

    # Best style per segment
    seg_style_counts: dict[str, Counter] = defaultdict(Counter)
    for r in records:
        seg_style_counts[r.brief.audience_segment][r.winning_variant.style] += 1
    best_style_per_segment = {
        seg: counts.most_common(1)[0][0]
        for seg, counts in sorted(seg_style_counts.items())
    }

    # Cost breakdown
    avg_text_gen = sum(r.text_record.generation_cost_usd for r in records) / n
    avg_text_eval = sum(r.text_record.evaluation_cost_usd for r in records) / n
    avg_img_gen = sum(
        sum(v.generation_cost_usd for v in r.all_variants) for r in records
    ) / n
    avg_img_eval = sum(
        sum(v.evaluation_cost_usd for v in r.all_variants) for r in records
    ) / n
    total_cost = sum(r.total_cost_usd for r in records)

    # Time breakdown
    avg_pipeline_time = mean([r.pipeline_time_s for r in records])
    avg_image_time = mean(
        [sum(v.generation_time_s for v in r.all_variants) for r in records]
    )
    avg_text_time = avg_pipeline_time - avg_image_time

    # Style distribution
    style_counts = Counter(r.winning_variant.style for r in records)

    report = {
        "total_ads": n,
        "pass_rates": {
            "text": round(text_passed / n, 4) if n else 0,
            "visual": round(visual_passed / n, 4) if n else 0,
            "combined": round(combined_passed / n, 4) if n else 0,
        },
        "scores": {
            "text_avg": round(mean(text_scores), 2),
            "visual_avg": round(mean(visual_scores), 2),
            "combined_avg": round(mean(combined_scores), 2),
            "combined_min": round(min(combined_scores), 2),
            "combined_max": round(max(combined_scores), 2),
        },
        "visual_dimensions": vis_dim_stats,
        "text_visual_correlation": text_visual_corr,
        "best_style_per_segment": best_style_per_segment,
        "style_distribution": dict(style_counts.most_common()),
        "cost": {
            "total_usd": round(total_cost, 4),
            "per_ad_usd": round(total_cost / n, 4) if n else 0,
            "avg_text_gen": round(avg_text_gen, 6),
            "avg_text_eval": round(avg_text_eval, 6),
            "avg_image_gen": round(avg_img_gen, 6),
            "avg_image_eval": round(avg_img_eval, 6),
        },
        "time": {
            "avg_pipeline_s": round(avg_pipeline_time, 2),
            "avg_text_s": round(avg_text_time, 2),
            "avg_image_s": round(avg_image_time, 2),
        },
    }

    _DATA.mkdir(parents=True, exist_ok=True)

    json_path = _DATA / "multimodal_evaluation_report.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)

    md_path = _DATA / "multimodal_evaluation_report.md"
    md_path.write_text(_build_multimodal_report_md(report))

    return json_path, md_path


def _build_multimodal_report_md(r: dict) -> str:
    lines: list[str] = []
    lines.append("# Multimodal Evaluation Report\n")

    lines.append("## Overview\n")
    lines.append(f"- **Total ads:** {r['total_ads']}")
    pr = r["pass_rates"]
    lines.append(f"- **Text pass rate:** {pr['text']:.0%}")
    lines.append(f"- **Visual pass rate:** {pr['visual']:.0%}")
    lines.append(f"- **Combined pass rate:** {pr['combined']:.0%}")
    sc = r["scores"]
    lines.append(f"- **Avg text score:** {sc['text_avg']}")
    lines.append(f"- **Avg visual score:** {sc['visual_avg']}")
    lines.append(f"- **Avg combined score:** {sc['combined_avg']}")
    lines.append(f"- **Combined range:** {sc['combined_min']} -- {sc['combined_max']}")
    lines.append("")

    if r["text_visual_correlation"] is not None:
        lines.append("## Text–Visual Correlation\n")
        corr = r["text_visual_correlation"]
        strength = "strong" if abs(corr) > 0.6 else "moderate" if abs(corr) > 0.3 else "weak"
        lines.append(f"- Pearson r = **{corr:.4f}** ({strength})")
        lines.append(f"- {'Higher text scores tend to correspond to higher visual scores.' if corr > 0 else 'No clear positive relationship between text and visual quality.'}")
        lines.append("")

    lines.append("## Visual Dimension Breakdown\n")
    lines.append("| Dimension | Avg | Std Dev |")
    lines.append("|---|---|---|")
    for d in VISUAL_DIMENSIONS:
        s = r["visual_dimensions"][d]
        label = VISUAL_DIMENSION_LABELS.get(d, d)
        lines.append(f"| {label} | {s['avg']} | {s['stdev']} |")
    lines.append("")

    lines.append("## Style Analysis\n")
    lines.append("### Winning Style Distribution\n")
    lines.append("| Style | Count | Share |")
    lines.append("|---|---|---|")
    total = r["total_ads"]
    for style, count in r["style_distribution"].items():
        lines.append(f"| {style} | {count} | {count / total:.0%} |")
    lines.append("")

    lines.append("### Best Style per Segment\n")
    lines.append("| Segment | Preferred Style |")
    lines.append("|---|---|")
    for seg, style in r["best_style_per_segment"].items():
        label = SEGMENT_LABELS.get(seg, seg)
        lines.append(f"| {label} | {style} |")
    lines.append("")

    lines.append("## Cost Breakdown\n")
    c = r["cost"]
    lines.append(f"- **Total cost:** ${c['total_usd']:.2f}")
    lines.append(f"- **Cost per ad:** ${c['per_ad_usd']:.4f}")
    lines.append("")
    lines.append("| Component | Avg per Ad |")
    lines.append("|---|---|")
    lines.append(f"| Text Generation | ${c['avg_text_gen']:.6f} |")
    lines.append(f"| Text Evaluation | ${c['avg_text_eval']:.6f} |")
    lines.append(f"| Image Generation | ${c['avg_image_gen']:.6f} |")
    lines.append(f"| Image Evaluation | ${c['avg_image_eval']:.6f} |")
    pct_image = (c["avg_image_gen"] + c["avg_image_eval"]) / c["per_ad_usd"] * 100 if c["per_ad_usd"] else 0
    lines.append(f"\nImage costs account for **{pct_image:.0f}%** of per-ad spend.")
    lines.append("")

    lines.append("## Pipeline Time\n")
    t = r["time"]
    lines.append(f"- **Avg total:** {t['avg_pipeline_s']:.1f}s")
    lines.append(f"- **Avg text stages:** {t['avg_text_s']:.1f}s")
    lines.append(f"- **Avg image stages:** {t['avg_image_s']:.1f}s")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate visualization artifacts for ad engine results",
    )
    parser.add_argument(
        "--v2",
        action="store_true",
        help="Include v2 multimodal visualizations",
    )
    args = parser.parse_args()

    # ── v1 visualizations ──────────────────────────────────────────────
    records = load_ad_library()

    print("Generating quality trends dashboard…")
    trends_path = plot_quality_trends()
    print(f"  -> {trends_path}")

    best = max(records, key=lambda r: r.evaluation.aggregate_score)
    worst = min(records, key=lambda r: r.evaluation.aggregate_score)
    print(f"Generating radar charts for best ({best.ad_id[:8]}) and worst ({worst.ad_id[:8]})…")
    for rec in (best, worst):
        radar_path = plot_dimension_radar(rec)
        print(f"  -> {radar_path}")

    print("Generating evaluation report…")
    json_path, md_path = generate_evaluation_report()
    print(f"  -> {json_path}")
    print(f"  -> {md_path}")

    # ── v2 multimodal visualizations ───────────────────────────────────
    if args.v2:
        print("\nGenerating v2 multimodal visualizations…")

        print("  Visual quality trends dashboard…")
        vt_path = plot_visual_quality_trends()
        print(f"  -> {vt_path}")

        print("  Ad showcase composite…")
        showcase_path = create_ad_showcase()
        print(f"  -> {showcase_path}")

        print("  Multimodal evaluation report…")
        mj_path, mm_path = generate_multimodal_report()
        print(f"  -> {mj_path}")
        print(f"  -> {mm_path}")

    print("\nDone — all visualization artifacts written.")


if __name__ == "__main__":
    main()

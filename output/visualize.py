"""Quality trend visualizations and evaluation report generation.

Produces:
  - output/quality_trends.png   (2x2 subplot dashboard)
  - output/radar_{ad_id}.png    (per-ad spider chart)
  - data/evaluation_report.json (machine-readable stats)
  - data/evaluation_report.md   (human-readable summary)

Usage:
    python -m output.visualize
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, stdev

import matplotlib.pyplot as plt
import numpy as np

from generate.models import AdRecord
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
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
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

    print("\nDone — all visualization artifacts written.")


if __name__ == "__main__":
    main()

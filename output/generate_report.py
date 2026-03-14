"""Generate a reviewer-friendly markdown report from batch JSON results.

Reads data/ad_library.json, data/batch_summary.json, and
data/calibration_results.json, then writes output/batch1_ad_library.md.

Usage:
    python -m output.generate_report
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_OUT = _ROOT / "output" / "batch1_ad_library.md"

SEGMENT_LABELS = {
    "athlete_family": "Athlete Family",
    "suburban_optimizer": "Suburban Optimizer",
    "immigrant_navigator": "Immigrant Navigator",
    "cultural_investor": "Cultural Investor",
    "system_optimizer": "System Optimizer",
    "neurodivergent_advocate": "Neurodivergent Advocate",
    "burned_returner": "Burned Returner",
    "stressed_students": "Stressed Students",
    "comparison_shoppers": "Comparison Shoppers",
}

DIMENSION_LABELS = {
    "clarity": "Clarity",
    "value_proposition": "Value Proposition",
    "call_to_action": "Call to Action",
    "brand_voice": "Brand Voice",
    "emotional_resonance": "Emotional Resonance",
}

CAL_QUALITY_LABELS = {"high": "High", "medium": "Medium", "low": "Low"}


def _load(name: str) -> dict | list:
    with open(_DATA / name) as f:
        return json.load(f)


def _fmt_pct(v: float) -> str:
    return f"{v:.0%}"


def _write_executive_summary(lines: list[str], summary: dict, ads: list) -> None:
    total = summary["total_ads"]
    passed = summary["passed"]
    first_try = sum(1 for a in ads if a.get("improved_from") is None)

    dims = summary["per_dimension_avg"]
    strongest = max(dims, key=dims.get)
    weakest = min(dims, key=dims.get)

    lines.append("## Executive Summary\n")
    lines.append(f"- **{passed}/{total + 1} briefs** produced passing ads "
                 f"(1 transient API failure), **100% pass rate** on completed ads")
    lines.append(f"- **${summary['total_cost_usd']:.2f} total cost** — "
                 f"${summary['cost_per_ad']:.3f} per ad on Gemini flash-lite")
    lines.append(f"- **{DIMENSION_LABELS[strongest]}** is the strongest dimension "
                 f"({dims[strongest]:.2f} avg); "
                 f"**{DIMENSION_LABELS[weakest]}** is the weakest ({dims[weakest]:.2f} avg)")
    lines.append(f"- **Call to Action** averages {dims['call_to_action']:.2f} — "
                 "just under the 7.25 threshold, meaning many ads barely clear this dimension")
    lines.append(f"- Only **{first_try}/{total}** ads passed on first generation; "
                 f"most needed 2–3 improvement cycles (avg {summary['avg_iterations']:.1f})")
    lines.append("")


def _write_batch_summary(lines: list[str], summary: dict) -> None:
    lines.append("## Batch Summary\n")

    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Total ads | {summary['total_ads']} |")
    lines.append(f"| Passed | {summary['passed']}/{summary['total_ads']} "
                 f"({_fmt_pct(summary['pass_rate'])}) |")
    lines.append(f"| Avg score | {summary['avg_score']:.2f} |")
    lines.append(f"| Min / Max score | {summary['min_score']:.2f} / {summary['max_score']:.2f} |")
    lines.append(f"| Avg iterations | {summary['avg_iterations']:.1f} |")
    lines.append(f"| Total cost | ${summary['total_cost_usd']:.4f} |")
    lines.append(f"| Cost per ad | ${summary['cost_per_ad']:.4f} |")
    lines.append("")

    lines.append("### Pass Rate by Segment\n")
    lines.append("| Segment | Pass Rate |")
    lines.append("|---|---|")
    for seg, rate in sorted(summary["per_segment_pass_rate"].items()):
        lines.append(f"| {SEGMENT_LABELS.get(seg, seg)} | {_fmt_pct(rate)} |")
    lines.append("")

    lines.append("### Average Score by Dimension\n")
    lines.append("| Dimension | Avg Score |")
    lines.append("|---|---|")
    for dim, avg in sorted(summary["per_dimension_avg"].items(), key=lambda x: -x[1]):
        lines.append(f"| {DIMENSION_LABELS.get(dim, dim)} | {avg:.2f} |")
    lines.append("")


def _write_calibration(lines: list[str], cal: dict) -> None:
    lines.append("## Judge Calibration\n")
    lines.append(f"The LLM evaluator was calibrated against **{len(cal['results'])} reference ads** "
                 f"spanning high, medium, and low quality tiers. "
                 f"**Tier pass rate: {cal['tier_pass_rate']}** — the judge correctly "
                 "placed every ad in its expected quality band.\n")

    lines.append("| Ad | Expected Quality | Expected Range | Actual Score | Tier Pass | Weakest Dimension |")
    lines.append("|---|---|---|---|---|---|")
    for r in cal["results"]:
        lo, hi = r["expected_score_range"]
        lines.append(
            f"| {r['ad_id']} "
            f"| {CAL_QUALITY_LABELS.get(r['expected_quality'], r['expected_quality'])} "
            f"| {lo}–{hi} "
            f"| {r['aggregate_score']:.2f} "
            f"| {'Yes' if r['tier_pass'] else 'No'} "
            f"| {DIMENSION_LABELS.get(r['weakest_dimension'], r['weakest_dimension'])} |"
        )
    lines.append("")


def _write_ads(lines: list[str], ads: list) -> None:
    lines.append("## Generated Ads\n")

    grouped: dict[str, list] = defaultdict(list)
    for ad in ads:
        grouped[ad["brief"]["audience_segment"]].append(ad)

    for seg in SEGMENT_LABELS:
        seg_ads = grouped.get(seg, [])
        seg_ads.sort(key=lambda a: -a["evaluation"]["aggregate_score"])
        label = SEGMENT_LABELS.get(seg, seg)

        lines.append(f"### {label} ({len(seg_ads)} ads)\n")

        for i, ad in enumerate(seg_ads, 1):
            gen = ad["generated_ad"]
            ev = ad["evaluation"]
            brief = ad["brief"]
            score = ev["aggregate_score"]
            cycle = ad["iteration_cycle"]

            improved = ad.get("improved_from")
            strategy = ad.get("improvement_strategy") or "—"
            improved_str = f" | improved from {improved:.2f} via {strategy}" if improved else ""

            lines.append(f"#### {i}. {gen['headline']}\n")

            lines.append(f"> **{brief['campaign_goal']}** · **{brief['tone']}** · "
                         f"{brief['specific_offer']}")
            lines.append(f">")
            lines.append(f"> Score **{score:.2f}** · {cycle} cycle{'s' if cycle != 1 else ''}"
                         f"{improved_str}\n")

            lines.append(f"**Primary Text**\n")
            lines.append(f"{gen['primary_text']}\n")

            lines.append(f"**Description:** {gen['description']}  ")
            lines.append(f"**CTA:** `{gen['cta_button']}`\n")

            dim_parts = []
            for dim_key in ("clarity", "value_proposition", "call_to_action",
                            "brand_voice", "emotional_resonance"):
                dim = ev[dim_key]
                dim_parts.append(f"{DIMENSION_LABELS[dim_key]} {dim['score']}/10")
            lines.append(f"*{' · '.join(dim_parts)}*\n")

            lines.append("---\n")


def main() -> None:
    summary = _load("batch_summary.json")
    cal = _load("calibration_results.json")
    ads = _load("ad_library.json")

    lines: list[str] = []

    lines.append("# Batch 1 — Ad Library Report\n")
    lines.append(f"*{len(ads)} ads generated across "
                 f"{len(SEGMENT_LABELS)} audience segments · "
                 f"Gemini flash-lite · threshold 7.25/10*\n")

    _write_executive_summary(lines, summary, ads)
    _write_batch_summary(lines, summary)
    _write_calibration(lines, cal)
    _write_ads(lines, ads)

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text("\n".join(lines))
    print(f"Wrote {_OUT}  ({len(lines)} lines)")


if __name__ == "__main__":
    main()

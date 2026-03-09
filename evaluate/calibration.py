"""Calibration script for the LLM judge.

Runs all 8 calibration ads through the evaluator and checks whether the
judge can reliably distinguish high / medium / low quality ads.

Usage:
    python -m evaluate.calibration
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from evaluate.judge import evaluate_ad

console = Console()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CALIBRATION_PATH = _PROJECT_ROOT / "compete" / "references" / "calibration_ads.json"
_RESULTS_PATH = _PROJECT_ROOT / "data" / "calibration_results.json"

# Aggregate score thresholds per quality tier
_TIER_RANGES: dict[str, tuple[float, float]] = {
    "high": (7.5, 10.0),
    "medium": (4.5, 7.5),
    "low": (1.0, 5.0),
}


def _load_calibration_ads() -> list[dict[str, Any]]:
    with open(_CALIBRATION_PATH) as f:
        return json.load(f)


def _check_tier(expected_quality: str, aggregate_score: float) -> bool:
    lo, hi = _TIER_RANGES[expected_quality]
    return lo <= aggregate_score <= hi


def _suggest_fixes(results: list[dict[str, Any]]) -> list[str]:
    """Generate actionable fix suggestions for miscalibrated dimensions."""
    suggestions: list[str] = []

    for r in results:
        if r["tier_pass"]:
            continue
        ad_id = r["ad_id"]
        expected = r["expected_quality"]
        agg = r["aggregate_score"]
        lo, hi = _TIER_RANGES[expected]

        if expected == "low" and agg > hi:
            over_dims = [
                dim
                for dim, info in r["dimension_details"].items()
                if info["actual"] > info["expected"] + 2
            ]
            if over_dims:
                dims_str = ", ".join(d.replace("_", " ") for d in over_dims)
                suggestions.append(
                    f"{ad_id}: evaluator scores this LOW-quality ad too high on "
                    f"{dims_str}. Add more negative examples to those rubrics."
                )
            else:
                suggestions.append(
                    f"{ad_id}: evaluator gives {agg:.2f} (expected <{hi}). "
                    f"Rubrics may need sharper score-1 anchors."
                )

        elif expected == "high" and agg < lo:
            under_dims = [
                dim
                for dim, info in r["dimension_details"].items()
                if info["actual"] < info["expected"] - 2
            ]
            if under_dims:
                dims_str = ", ".join(d.replace("_", " ") for d in under_dims)
                suggestions.append(
                    f"{ad_id}: evaluator is too harsh on {dims_str} for this "
                    f"HIGH-quality ad. Check rubric score-10 examples."
                )
            else:
                suggestions.append(
                    f"{ad_id}: evaluator gives {agg:.2f} (expected ≥{lo}). "
                    f"Consider adding stronger positive examples."
                )

        elif expected == "medium":
            direction = "high" if agg > hi else "low"
            suggestions.append(
                f"{ad_id}: MEDIUM-quality ad scored {agg:.2f} (expected "
                f"{lo}-{hi}). Score is too {direction} — review rubric "
                f"score-5 anchors."
            )

    return suggestions


def run_calibration() -> dict[str, Any]:
    """Run the full calibration suite and return the results dict."""
    calibration_ads = _load_calibration_ads()
    results: list[dict[str, Any]] = []
    total_cost = 0.0

    console.rule("[bold blue]Judge Calibration Run[/bold blue]")
    console.print(f"Evaluating {len(calibration_ads)} calibration ads…\n")

    for ad_data in calibration_ads:
        ad_id = ad_data["id"]
        expected_quality = ad_data["expected_quality"]
        expected_range = ad_data["expected_score_range"]
        dim_expectations = ad_data.get("dimension_expectations", {})

        console.rule(f"[cyan]{ad_id}[/cyan] (expected: {expected_quality})")

        ad_fields = {
            "primary_text": ad_data["primary_text"],
            "headline": ad_data["headline"],
            "description": ad_data["description"],
            "cta_button": ad_data["cta_button"],
        }

        evaluation, usage = evaluate_ad(ad_fields)
        total_cost += usage["cost_usd"]

        dimension_details: dict[str, dict[str, Any]] = {}
        for dim_name in ["clarity", "value_proposition", "call_to_action", "brand_voice", "emotional_resonance"]:
            actual = getattr(evaluation, dim_name).score
            expected_dim = dim_expectations.get(dim_name)
            dimension_details[dim_name] = {
                "actual": actual,
                "expected": expected_dim,
                "delta": actual - expected_dim if expected_dim else None,
            }

        tier_pass = _check_tier(expected_quality, evaluation.aggregate_score)

        results.append({
            "ad_id": ad_id,
            "expected_quality": expected_quality,
            "expected_score_range": expected_range,
            "aggregate_score": evaluation.aggregate_score,
            "tier_pass": tier_pass,
            "passes_threshold": evaluation.passes_threshold,
            "weakest_dimension": evaluation.weakest_dimension,
            "dimension_details": dimension_details,
        })

    # --- Summary report ---
    console.print()
    console.rule("[bold blue]Calibration Report[/bold blue]")

    summary_table = Table(title="Per-Ad Results", show_lines=True)
    summary_table.add_column("ID", style="cyan")
    summary_table.add_column("Expected", justify="center")
    summary_table.add_column("Aggregate", justify="center")
    summary_table.add_column("Expected Range", justify="center")
    summary_table.add_column("Tier", justify="center")
    summary_table.add_column("Weakest")

    for r in results:
        tier_style = "green" if r["tier_pass"] else "red"
        agg_style = "green" if r["tier_pass"] else "red"
        summary_table.add_row(
            r["ad_id"],
            r["expected_quality"].upper(),
            f"[{agg_style}]{r['aggregate_score']:.2f}[/{agg_style}]",
            f"{r['expected_score_range'][0]}-{r['expected_score_range'][1]}",
            f"[{tier_style}]{'PASS' if r['tier_pass'] else 'FAIL'}[/{tier_style}]",
            r["weakest_dimension"].replace("_", " "),
        )
    console.print(summary_table)

    # Per-dimension delta table
    dim_table = Table(title="Dimension Deltas (actual - expected)", show_lines=True)
    dim_table.add_column("ID", style="cyan")
    for dim in ["clarity", "value_proposition", "call_to_action", "brand_voice", "emotional_resonance"]:
        dim_table.add_column(dim.replace("_", " ").title(), justify="center")

    for r in results:
        row = [r["ad_id"]]
        for dim in ["clarity", "value_proposition", "call_to_action", "brand_voice", "emotional_resonance"]:
            delta = r["dimension_details"][dim]["delta"]
            if delta is None:
                row.append("—")
            else:
                style = "green" if abs(delta) <= 1 else ("yellow" if abs(delta) <= 2 else "red")
                row.append(f"[{style}]{delta:+d}[/{style}]")
        dim_table.add_row(*row)
    console.print(dim_table)

    # Overall pass/fail
    tier_passes = sum(1 for r in results if r["tier_pass"])
    total_ads = len(results)
    overall_pass = tier_passes == total_ads

    if overall_pass:
        console.print(
            f"\n[bold green]CALIBRATION PASSED[/bold green] — "
            f"all {total_ads} ads scored within expected tiers."
        )
    else:
        console.print(
            f"\n[bold red]CALIBRATION FAILED[/bold red] — "
            f"{tier_passes}/{total_ads} ads within expected tiers."
        )
        suggestions = _suggest_fixes(results)
        if suggestions:
            console.print("\n[bold yellow]Suggested fixes:[/bold yellow]")
            for s in suggestions:
                console.print(f"  • {s}")

    console.print(f"\nTotal estimated cost: ${total_cost:.4f}")

    # Save results
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_pass": overall_pass,
        "tier_pass_rate": f"{tier_passes}/{total_ads}",
        "total_cost_usd": round(total_cost, 6),
        "results": results,
    }
    _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_RESULTS_PATH, "w") as f:
        json.dump(output, f, indent=2)
    console.print(f"Results saved to {_RESULTS_PATH}")

    return output


if __name__ == "__main__":
    run_calibration()

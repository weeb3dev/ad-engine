"""Batch orchestrator for large-scale ad generation runs.

Loads (or generates) a brief matrix, runs each brief through the
pipeline with rate-limit retry and a live progress bar, then persists
the full ad library and a summary report.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from config.loader import get_config
from config.observability import get_langfuse
from generate.briefs import generate_brief_matrix, load_briefs, save_briefs
from generate.models import AdBrief, AdRecord
from iterate.feedback import run_pipeline

console = Console()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_MAX_RETRIES = 3
_RETRY_WAIT_SECS = 60


def _is_rate_limit_error(exc: Exception) -> bool:
    """Check whether *exc* looks like a 429 / resource-exhausted error."""
    name = type(exc).__name__
    if name in ("ResourceExhausted", "TooManyRequests"):
        return True
    msg = str(exc).lower()
    return "429" in msg or "resource exhausted" in msg or "rate limit" in msg


def _build_summary(records: list[AdRecord]) -> dict[str, Any]:
    if not records:
        return {"total_ads": 0}

    scores = [r.evaluation.aggregate_score for r in records]
    passed = sum(1 for r in records if r.evaluation.passes_threshold)
    total_cost = sum(r.generation_cost_usd + r.evaluation_cost_usd for r in records)

    seg_total: dict[str, int] = defaultdict(int)
    seg_passed: dict[str, int] = defaultdict(int)
    dim_scores: dict[str, list[float]] = defaultdict(list)

    for r in records:
        seg = r.brief.audience_segment
        seg_total[seg] += 1
        if r.evaluation.passes_threshold:
            seg_passed[seg] += 1
        for dim in ("clarity", "value_proposition", "call_to_action", "brand_voice", "emotional_resonance"):
            dim_scores[dim].append(getattr(r.evaluation, dim).score)

    return {
        "total_ads": len(records),
        "passed": passed,
        "pass_rate": round(passed / len(records), 4),
        "avg_score": round(sum(scores) / len(scores), 2),
        "min_score": round(min(scores), 2),
        "max_score": round(max(scores), 2),
        "avg_iterations": round(sum(r.iteration_cycle for r in records) / len(records), 2),
        "total_cost_usd": round(total_cost, 4),
        "cost_per_ad": round(total_cost / len(records), 4),
        "per_segment_pass_rate": {
            seg: round(seg_passed[seg] / seg_total[seg], 4) for seg in sorted(seg_total)
        },
        "per_dimension_avg": {
            dim: round(sum(vals) / len(vals), 2) for dim, vals in sorted(dim_scores.items())
        },
    }


def run_full_batch(num_ads: int = 54) -> dict[str, Any]:
    """Generate *num_ads* ads through the full pipeline.

    Loads saved briefs from data/briefs.json if available, otherwise
    generates and saves a new brief matrix.  Returns a summary dict.
    """
    config = get_config()

    briefs_path = _PROJECT_ROOT / "data" / "briefs.json"
    if briefs_path.exists():
        briefs = load_briefs()
        console.print(f"[dim]Loaded {len(briefs)} briefs from {briefs_path}[/dim]")
    else:
        briefs = generate_brief_matrix(config)
        save_briefs(briefs)
        console.print(f"[dim]Generated and saved {len(briefs)} briefs[/dim]")

    briefs = briefs[:num_ads]
    records: list[AdRecord] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("pass rate: {task.fields[pass_rate]}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Batch", total=len(briefs), pass_rate="—")

        for i, brief in enumerate(briefs):
            label = f"{brief.audience_segment}/{brief.campaign_goal}"
            progress.update(task, description=f"[{i + 1}/{len(briefs)}] {label}")

            record = _run_with_retry(brief, config)
            if record is not None:
                records.append(record)

            passed = sum(1 for r in records if r.evaluation.passes_threshold)
            rate = f"{100 * passed / len(records):.0f}%" if records else "—"
            progress.update(task, advance=1, pass_rate=rate)

    summary = _build_summary(records)

    _save_ad_library(records)
    _save_summary(summary)
    _print_summary_table(summary)

    try:
        get_langfuse().flush()
    except Exception:
        pass

    return summary


def _run_with_retry(brief: AdBrief, config: Any) -> AdRecord | None:
    """Run a single brief through the pipeline with rate-limit retries."""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return run_pipeline(brief, config)
        except Exception as exc:
            if _is_rate_limit_error(exc) and attempt < _MAX_RETRIES:
                console.print(
                    f"  [yellow]Rate limited — waiting {_RETRY_WAIT_SECS}s "
                    f"(attempt {attempt}/{_MAX_RETRIES})…[/yellow]"
                )
                time.sleep(_RETRY_WAIT_SECS)
                continue
            console.print(f"  [red]Pipeline failed: {exc}[/red]")
            return None
    return None


def _save_ad_library(records: list[AdRecord]) -> None:
    out = _PROJECT_ROOT / "data" / "ad_library.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump([r.model_dump(mode="json") for r in records], f, indent=2, default=str)
    console.print(f"\n[dim]Saved {len(records)} records to {out}[/dim]")


def _save_summary(summary: dict[str, Any]) -> None:
    out = _PROJECT_ROOT / "data" / "batch_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(summary, f, indent=2)
    console.print(f"[dim]Saved summary to {out}[/dim]")


def load_ad_library(path: str | Path = "data/ad_library.json") -> list[AdRecord]:
    """Reload saved ad records for downstream analysis / visualization."""
    full = _PROJECT_ROOT / path
    with open(full) as f:
        raw = json.load(f)
    return [AdRecord.model_validate(item) for item in raw]


def _print_summary_table(summary: dict[str, Any]) -> None:
    if not summary.get("total_ads"):
        console.print("[red]No ads produced.[/red]")
        return

    table = Table(title="Batch Summary", show_lines=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Total ads", str(summary["total_ads"]))
    table.add_row("Passed", f"{summary['passed']}/{summary['total_ads']} ({summary['pass_rate']:.0%})")
    table.add_row("Avg score", f"{summary['avg_score']:.2f}")
    table.add_row("Min / Max", f"{summary['min_score']:.2f} / {summary['max_score']:.2f}")
    table.add_row("Avg iterations", f"{summary['avg_iterations']:.1f}")
    table.add_row("Total cost", f"${summary['total_cost_usd']:.4f}")
    table.add_row("Cost per ad", f"${summary['cost_per_ad']:.4f}")

    seg_rates = summary.get("per_segment_pass_rate", {})
    for seg, rate in seg_rates.items():
        table.add_row(f"  {seg}", f"{rate:.0%}")

    dim_avgs = summary.get("per_dimension_avg", {})
    for dim, avg in dim_avgs.items():
        table.add_row(f"  {dim}", f"{avg:.2f}")

    console.print(table)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run batch ad generation pipeline")
    parser.add_argument(
        "--num-ads",
        type=int,
        default=54,
        help="Number of ads to generate (default: 54)",
    )
    args = parser.parse_args()
    run_full_batch(args.num_ads)

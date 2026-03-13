"""Multi-modal ad generation pipeline.

Orchestrates the v1 text pipeline (generate -> evaluate -> improve) with
the v2 image pipeline (generate variants -> evaluate -> select winner)
into a single 3-stage flow.  Includes a batch runner with rate-limit
retry and a CLI entry point.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
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
from config.observability import get_langfuse, observe, propagate_attributes
from generate.ab_variants import generate_ab_variants, select_best_variant
from generate.briefs import generate_brief_matrix, load_briefs, save_briefs
from generate.models import AdBrief, Config, MultiModalAdRecord
from iterate.feedback import run_pipeline

console = Console()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_MAX_RETRIES = 3
_RETRY_WAIT_SECS = 90  # longer than text-only (60s) — image gen has stricter limits

_TEXT_WEIGHT = 0.6
_VISUAL_WEIGHT = 0.4


# ---------------------------------------------------------------------------
# Rate-limit detection (mirrors output/batch_runner.py with longer waits)
# ---------------------------------------------------------------------------

def _is_rate_limit_error(exc: Exception) -> bool:
    """Check whether *exc* looks like a 429 / resource-exhausted error."""
    name = type(exc).__name__
    if name in ("ResourceExhausted", "TooManyRequests"):
        return True
    msg = str(exc).lower()
    return "429" in msg or "resource exhausted" in msg or "rate limit" in msg


# ---------------------------------------------------------------------------
# Single-ad multimodal pipeline
# ---------------------------------------------------------------------------

@observe(name="run-multimodal-pipeline")
def run_multimodal_pipeline(
    brief: AdBrief,
    config: Config,
) -> MultiModalAdRecord:
    """Run the full text + image pipeline for a single brief.

    Stage 1 — TEXT:  reuse the v1 ``run_pipeline`` to produce an AdRecord.
    Stage 2 — IMAGES: generate A/B image variants and pick the winner.
    Stage 3 — COMBINE: assemble a MultiModalAdRecord with a blended score.
    """
    pipeline_start = time.time()

    with propagate_attributes(
        tags=["multimodal-pipeline"],
        metadata={
            "audience_segment": brief.audience_segment,
            "campaign_goal": brief.campaign_goal,
        },
    ):
        # ── Stage 1: Text (v1) ──────────────────────────────────────────
        console.rule("[bold blue]Multimodal Pipeline — Stage 1: Text")
        text_record = run_pipeline(brief, config)

        text_status = (
            "[green]PASS[/green]"
            if text_record.evaluation.passes_threshold
            else "[red]FAIL (proceeding anyway)[/red]"
        )
        console.print(
            f"  Text score: [bold]{text_record.evaluation.aggregate_score:.2f}[/bold]  "
            f"{text_status}"
        )

        # ── Stage 2: Images (v2) ────────────────────────────────────────
        console.rule("[bold blue]Multimodal Pipeline — Stage 2: Images")
        variants = generate_ab_variants(
            text_record.generated_ad,
            brief,
            text_record.ad_id,
            config,
        )

        if not variants:
            raise RuntimeError(
                f"No image variants produced for ad {text_record.ad_id}"
            )

        winner = select_best_variant(variants, brief.campaign_goal)
        console.print(
            f"  Winner: [bold cyan]{winner.style}[/bold cyan]  "
            f"visual score: [bold]{winner.visual_evaluation.visual_aggregate_score:.2f}[/bold]  "
            f"path: {winner.image_path}"
        )

        # ── Stage 3: Combine ────────────────────────────────────────────
        console.rule("[bold blue]Multimodal Pipeline — Stage 3: Combine")

        text_score = text_record.evaluation.aggregate_score
        visual_score = winner.visual_evaluation.visual_aggregate_score
        combined = round(
            _TEXT_WEIGHT * text_score + _VISUAL_WEIGHT * visual_score, 2
        )

        image_gen_cost = sum(v.generation_cost_usd for v in variants)
        image_eval_cost = sum(v.evaluation_cost_usd for v in variants)
        total_cost = (
            text_record.generation_cost_usd
            + text_record.evaluation_cost_usd
            + image_gen_cost
            + image_eval_cost
        )

        pipeline_time = round(time.time() - pipeline_start, 2)

        record = MultiModalAdRecord(
            ad_id=text_record.ad_id,
            brief=brief,
            text_record=text_record,
            winning_variant=winner,
            all_variants=variants,
            combined_score=combined,
            total_cost_usd=round(total_cost, 6),
            pipeline_time_s=pipeline_time,
            timestamp=datetime.now(UTC),
        )

        console.print(Panel(
            f"[bold]{text_record.generated_ad.headline}[/bold]\n"
            f"Text: {text_score:.2f}  |  Visual: {visual_score:.2f}  |  "
            f"[bold]Combined: {combined:.2f}[/bold]\n"
            f"Winning style: [cyan]{winner.style}[/cyan]  |  "
            f"Variants: {len(variants)}  |  "
            f"Cost: ${total_cost:.4f}  |  Time: {pipeline_time:.1f}s",
            title="Multimodal Result",
            border_style="green" if combined >= 7.0 else "yellow",
        ))

        return record


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def _run_multimodal_with_retry(
    brief: AdBrief,
    config: Config,
) -> MultiModalAdRecord | None:
    """Run a single brief through the multimodal pipeline with retries."""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return run_multimodal_pipeline(brief, config)
        except Exception as exc:
            if _is_rate_limit_error(exc) and attempt < _MAX_RETRIES:
                wait = _RETRY_WAIT_SECS * attempt
                console.print(
                    f"  [yellow]Rate limited — waiting {wait}s "
                    f"(attempt {attempt}/{_MAX_RETRIES})…[/yellow]"
                )
                time.sleep(wait)
                continue
            console.print(f"  [red]Multimodal pipeline failed: {exc}[/red]")
            return None
    return None


@observe(name="run-multimodal-batch")
def run_multimodal_batch(
    briefs: list[AdBrief],
    config: Config,
    num_ads: int = 20,
) -> list[MultiModalAdRecord]:
    """Run the multimodal pipeline for a list of briefs.

    Saves results to ``data/multimodal_ad_library.json`` and prints a
    summary table.
    """
    briefs = briefs[:num_ads]
    batch_id = uuid.uuid4().hex[:12]
    records: list[MultiModalAdRecord] = []

    with propagate_attributes(session_id=batch_id, tags=["multimodal-batch"]):
        console.print(
            f"\n[bold]Starting multimodal batch: {len(briefs)} brief(s)  "
            f"session={batch_id}[/bold]\n"
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("pass rate: {task.fields[pass_rate]}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                "Multimodal Batch", total=len(briefs), pass_rate="—",
            )

            for i, brief in enumerate(briefs):
                label = f"{brief.audience_segment}/{brief.campaign_goal}"
                progress.update(
                    task,
                    description=f"[{i + 1}/{len(briefs)}] {label}",
                )

                record = _run_multimodal_with_retry(brief, config)
                if record is not None:
                    records.append(record)

                passed = sum(1 for r in records if r.combined_score >= 7.0)
                rate = f"{100 * passed / len(records):.0f}%" if records else "—"
                progress.update(task, advance=1, pass_rate=rate)

    _save_multimodal_library(records)
    _print_batch_summary(records)

    try:
        get_langfuse().flush()
    except Exception:
        pass

    return records


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _save_multimodal_library(records: list[MultiModalAdRecord]) -> None:
    out = _PROJECT_ROOT / "data" / "multimodal_ad_library.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(
            [r.model_dump(mode="json") for r in records],
            f,
            indent=2,
            default=str,
        )
    console.print(f"\n[dim]Saved {len(records)} multimodal record(s) to {out}[/dim]")


def load_multimodal_library(
    path: str | Path = "data/multimodal_ad_library.json",
) -> list[MultiModalAdRecord]:
    """Reload saved multimodal records for analysis / visualization."""
    full = _PROJECT_ROOT / path
    with open(full) as f:
        raw = json.load(f)
    return [MultiModalAdRecord.model_validate(item) for item in raw]


# ---------------------------------------------------------------------------
# Batch summary
# ---------------------------------------------------------------------------

def _print_batch_summary(records: list[MultiModalAdRecord]) -> None:
    if not records:
        console.print("[red]No multimodal records produced.[/red]")
        return

    text_passed = sum(
        1 for r in records if r.text_record.evaluation.passes_threshold
    )
    visual_passed = sum(
        1 for r in records
        if r.winning_variant.visual_evaluation.passes_visual_threshold
    )
    combined_passed = sum(1 for r in records if r.combined_score >= 7.0)
    n = len(records)

    combined_scores = [r.combined_score for r in records]
    total_cost = sum(r.total_cost_usd for r in records)
    total_time = sum(r.pipeline_time_s for r in records)

    style_counts: Counter[str] = Counter(
        r.winning_variant.style for r in records
    )
    most_popular = style_counts.most_common(1)[0][0]

    table = Table(title="Multimodal Batch Summary", show_lines=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Total ads", str(n))
    table.add_row("Text pass rate", f"{text_passed}/{n} ({100 * text_passed / n:.0f}%)")
    table.add_row("Visual pass rate", f"{visual_passed}/{n} ({100 * visual_passed / n:.0f}%)")
    table.add_row("Combined pass rate", f"{combined_passed}/{n} ({100 * combined_passed / n:.0f}%)")
    table.add_row("Avg combined score", f"{sum(combined_scores) / n:.2f}")
    table.add_row(
        "Min / Max combined",
        f"{min(combined_scores):.2f} / {max(combined_scores):.2f}",
    )
    table.add_row("Most popular style", most_popular)

    for style, count in style_counts.most_common():
        table.add_row(f"  {style}", f"{count} ({100 * count / n:.0f}%)")

    table.add_row("Total cost", f"${total_cost:.4f}")
    table.add_row("Cost per ad", f"${total_cost / n:.4f}")
    table.add_row("Total time", f"{total_time:.1f}s")
    table.add_row("Avg time per ad", f"{total_time / n:.1f}s")

    console.print(table)


# ---------------------------------------------------------------------------
# CLI entry point: python -m iterate.multimodal_pipeline --num-ads 5
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the multimodal ad generation pipeline",
    )
    parser.add_argument(
        "--num-ads",
        type=int,
        default=20,
        help="Number of ads to generate (default: 20)",
    )
    args = parser.parse_args()

    config = get_config()

    briefs_path = _PROJECT_ROOT / "data" / "briefs.json"
    if briefs_path.exists():
        briefs = load_briefs()
        console.print(f"[dim]Loaded {len(briefs)} briefs from {briefs_path}[/dim]")
    else:
        briefs = generate_brief_matrix(config)
        save_briefs(briefs)
        console.print(f"[dim]Generated and saved {len(briefs)} briefs[/dim]")

    run_multimodal_batch(briefs, config, num_ads=args.num_ads)

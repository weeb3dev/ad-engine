"""Core feedback loop: generate -> evaluate -> improve -> re-evaluate.

Ties together the generator (Phase 4), evaluator (Phase 3), and
improvement strategies into an iterative self-improvement pipeline.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from config.loader import get_config, get_gemini_client
from config.observability import get_langfuse, observe, propagate_attributes
from evaluate.judge import evaluate_ad
from generate.generator import generate_ad
from generate.models import AdBrief, AdEvaluation, AdRecord, Config, GeneratedAd
from iterate.strategies import build_targeted_prompt, get_strategy_name

console = Console()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_INPUT_COST_PER_M = 1.25
_OUTPUT_COST_PER_M = 10.00


def _extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from model response, handling markdown fences."""
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1)
    else:
        brace_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if brace_match:
            cleaned = brace_match.group(0)
    return json.loads(cleaned)


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * _INPUT_COST_PER_M + output_tokens * _OUTPUT_COST_PER_M) / 1_000_000


@observe(name="improve-ad")
def improve_ad(
    ad: GeneratedAd,
    evaluation: AdEvaluation,
    brief: AdBrief,
    config: Config,
    attempt: int = 1,
) -> tuple[GeneratedAd, dict[str, Any]]:
    """Regenerate an ad targeting its weakest dimension.

    Returns (improved_GeneratedAd, usage_dict).
    """
    client = get_gemini_client()
    weak_dim = evaluation.weakest_dimension
    dim_score = getattr(evaluation, weak_dim)
    strategy = get_strategy_name(attempt)

    try:
        get_langfuse().update_current_span(
            metadata={"strategy": strategy, "weak_dimension": weak_dim, "attempt": attempt},
        )
    except Exception:
        pass

    display_dim = weak_dim.replace("_", " ").title()
    console.print(
        f"\n[bold yellow]Improving ad[/bold yellow]  "
        f"strategy={strategy}  weak_dim={display_dim} ({dim_score.score}/10)"
    )

    system_instruction, user_prompt = build_targeted_prompt(
        original_ad=ad,
        weak_dimension=weak_dim,
        score=dim_score.score,
        rationale=dim_score.rationale,
        strategy=strategy,
        config=config,
    )

    temperatures = [0.9, 0.5]

    for retry_idx, temp in enumerate(temperatures):
        try:
            response = client.models.generate_content(
                model=config.models.generator,
                contents=user_prompt,
                config={
                    "system_instruction": system_instruction,
                    "temperature": temp,
                },
            )

            input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
            usage: dict[str, Any] = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": _estimate_cost(input_tokens, output_tokens),
            }

            parsed = _extract_json(response.text)
            improved = GeneratedAd(**parsed)

            console.print(Panel(
                f"[bold]{improved.headline}[/bold]\n"
                f"{improved.primary_text[:200]}{'…' if len(improved.primary_text) > 200 else ''}\n"
                f"[dim]{improved.description}[/dim]\n"
                f"[[ {improved.cta_button} ]]",
                title=f"Improved Ad (strategy={strategy})",
                border_style="yellow",
            ))

            return improved, usage

        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            if retry_idx == 0:
                console.print(
                    f"  [yellow]⟳[/yellow] Parse error (temp={temp}), "
                    f"retrying with temp=0.5… ({exc})"
                )
                continue
            raise ValueError(
                f"Improvement failed after 2 parse attempts: {exc}"
            ) from exc

    raise ValueError("Unreachable — improve loop exited without return")


@observe(name="run-pipeline")
def run_pipeline(brief: AdBrief, config: Config) -> AdRecord:
    """Run the full generate -> evaluate -> improve loop for a single brief.

    Returns the best AdRecord produced within max_regeneration_attempts.
    """
    with propagate_attributes(
        tags=["pipeline"],
        metadata={
            "audience_segment": brief.audience_segment,
            "campaign_goal": brief.campaign_goal,
        },
    ):
        max_attempts = config.quality.max_regeneration_attempts
        total_gen_cost = 0.0
        total_eval_cost = 0.0

        # Step 1: initial generation
        console.rule("[bold blue]Pipeline — Initial Generation")
        ad, gen_usage = generate_ad(brief, config)
        total_gen_cost += gen_usage["cost_usd"]

        # Step 2: initial evaluation
        evaluation, eval_usage = evaluate_ad(ad)
        total_eval_cost += eval_usage["cost_usd"]

        initial_score = evaluation.aggregate_score

        # Track the best version seen
        best_ad = ad
        best_eval = evaluation
        best_strategy: str | None = None
        cycle = 1

        _print_cycle_summary(cycle, evaluation, strategy=None)

        # Step 3: improvement loop
        for attempt in range(1, max_attempts + 1):
            if best_eval.passes_threshold:
                console.print(
                    f"\n[bold green]Passed threshold ({best_eval.aggregate_score:.2f} >= 7.0) "
                    f"after {cycle} cycle(s)[/bold green]"
                )
                break

            console.rule(f"[bold yellow]Pipeline — Improvement Cycle {attempt}")

            try:
                improved_ad, imp_usage = improve_ad(
                    ad=best_ad,
                    evaluation=best_eval,
                    brief=brief,
                    config=config,
                    attempt=attempt,
                )
            except ValueError as exc:
                console.print(f"  [red]✗[/red] Improvement attempt {attempt} failed: {exc}")
                break

            total_gen_cost += imp_usage["cost_usd"]

            re_eval, re_eval_usage = evaluate_ad(improved_ad)
            total_eval_cost += re_eval_usage["cost_usd"]

            cycle += 1
            strategy_name = get_strategy_name(attempt)
            _print_cycle_summary(cycle, re_eval, strategy=strategy_name)

            if re_eval.aggregate_score > best_eval.aggregate_score:
                best_ad = improved_ad
                best_eval = re_eval
                best_strategy = strategy_name

        else:
            if not best_eval.passes_threshold:
                console.print(
                    f"\n[bold red]Max attempts reached. Best score: "
                    f"{best_eval.aggregate_score:.2f} (below threshold)[/bold red]"
                )

        record = AdRecord(
            ad_id=uuid.uuid4().hex[:12],
            brief=brief,
            generated_ad=best_ad,
            evaluation=best_eval,
            iteration_cycle=cycle,
            improved_from=initial_score if cycle > 1 else None,
            improvement_strategy=best_strategy,
            generation_cost_usd=total_gen_cost,
            evaluation_cost_usd=total_eval_cost,
            timestamp=datetime.utcnow(),
        )

        console.rule("[bold blue]Pipeline — Result")
        console.print(
            f"  Final score: [bold]{record.evaluation.aggregate_score:.2f}[/bold]  "
            f"Passed: {'[green]Yes' if record.evaluation.passes_threshold else '[red]No'}[/]  "
            f"Cycles: {record.iteration_cycle}  "
            f"Cost: ${record.generation_cost_usd + record.evaluation_cost_usd:.4f}"
        )

        return record


@observe(name="run-batch")
def run_batch(briefs: list[AdBrief], config: Config) -> list[AdRecord]:
    """Run the full pipeline for a list of briefs and save results."""
    batch_id = uuid.uuid4().hex[:12]
    records: list[AdRecord] = []

    with propagate_attributes(session_id=batch_id, tags=["batch"]):
        console.print(f"\n[bold]Starting batch run: {len(briefs)} brief(s)  session={batch_id}[/bold]\n")

        for i, brief in enumerate(briefs, 1):
            console.rule(
                f"[bold magenta]Brief {i}/{len(briefs)} — "
                f"{brief.audience_segment} / {brief.campaign_goal}"
            )
            try:
                record = run_pipeline(brief, config)
                records.append(record)
            except Exception as exc:
                console.print(f"  [red]✗ Pipeline failed for brief {i}: {exc}[/red]")

    # Batch summary
    _print_batch_summary(records)

    # Save to disk
    output_path = _PROJECT_ROOT / "data" / "ad_library.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialised = [r.model_dump(mode="json") for r in records]
    with open(output_path, "w") as f:
        json.dump(serialised, f, indent=2, default=str)
    console.print(f"\n[dim]Saved {len(records)} record(s) to {output_path}[/dim]")

    # Flush traces to Langfuse before returning
    try:
        get_langfuse().flush()
    except Exception:
        pass

    return records


# ---------------------------------------------------------------------------
# Pretty-printing helpers
# ---------------------------------------------------------------------------

def _print_cycle_summary(
    cycle: int,
    evaluation: AdEvaluation,
    strategy: str | None,
) -> None:
    style = "green" if evaluation.passes_threshold else "yellow"
    strat_label = f"  strategy={strategy}" if strategy else ""
    console.print(
        f"\n  Cycle {cycle}: "
        f"[{style}]{evaluation.aggregate_score:.2f}[/{style}]  "
        f"weakest={evaluation.weakest_dimension}"
        f"{strat_label}"
    )


def _print_batch_summary(records: list[AdRecord]) -> None:
    if not records:
        console.print("[red]No records produced.[/red]")
        return

    passed = sum(1 for r in records if r.evaluation.passes_threshold)
    scores = [r.evaluation.aggregate_score for r in records]
    total_cost = sum(r.generation_cost_usd + r.evaluation_cost_usd for r in records)
    avg_cycles = sum(r.iteration_cycle for r in records) / len(records)

    table = Table(title="Batch Summary", show_lines=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Total ads", str(len(records)))
    table.add_row("Pass rate", f"{passed}/{len(records)} ({100 * passed / len(records):.0f}%)")
    table.add_row("Avg score", f"{sum(scores) / len(scores):.2f}")
    table.add_row("Min / Max score", f"{min(scores):.2f} / {max(scores):.2f}")
    table.add_row("Avg cycles", f"{avg_cycles:.1f}")
    table.add_row("Total cost", f"${total_cost:.4f}")
    table.add_row("Cost per ad", f"${total_cost / len(records):.4f}")

    console.print(table)

"""LLM-as-judge evaluation module.

Evaluates generated ad copy across five quality dimensions using Gemini
as a structured judge. Each dimension is scored independently with its
own rubric and calibration references.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.table import Table

from config.loader import get_config, get_gemini_client
from config.observability import get_langfuse, observe
from evaluate.dimensions import get_all_rubrics
from generate.models import AdEvaluation, DimensionScore, GeneratedAd

console = Console()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PROMPT_PATH = _PROJECT_ROOT / "evaluate" / "prompts" / "judge_prompt.yaml"
_CALIBRATION_PATH = _PROJECT_ROOT / "compete" / "references" / "calibration_ads.json"

# Approximate Gemini 3.1 Pro pricing (USD per 1M tokens)
_INPUT_COST_PER_M = 1.25
_OUTPUT_COST_PER_M = 10.00


def _load_prompt_template() -> dict[str, str]:
    with open(_PROMPT_PATH) as f:
        return yaml.safe_load(f)


def _load_calibration_ads() -> list[dict[str, Any]]:
    with open(_CALIBRATION_PATH) as f:
        return json.load(f)


def _format_reference_ad(ad: dict[str, Any]) -> str:
    """Format a calibration ad as a readable string for prompt injection."""
    return (
        f"Primary Text: {ad['primary_text']}\n"
        f"Headline: {ad['headline']}\n"
        f"Description: {ad['description']}\n"
        f"CTA Button: {ad['cta_button']}"
    )


def _pick_references(
    calibration_ads: list[dict[str, Any]],
) -> tuple[str, str]:
    """Pick one high-scoring and one low-scoring reference ad."""
    high_ads = [a for a in calibration_ads if a["expected_quality"] == "high"]
    low_ads = [a for a in calibration_ads if a["expected_quality"] == "low"]
    high_ref = _format_reference_ad(high_ads[0]) if high_ads else "N/A"
    low_ref = _format_reference_ad(low_ads[0]) if low_ads else "N/A"
    return high_ref, low_ref


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


def get_evaluation_context() -> tuple[dict[str, str], str, str, list[str]]:
    """Return shared evaluation context for per-dimension streaming loops.

    Returns (rubrics, high_ref, low_ref, dimension_names).
    """
    cfg = get_config()
    rubrics = get_all_rubrics()
    calibration_ads = _load_calibration_ads()
    high_ref, low_ref = _pick_references(calibration_ads)
    dimension_names = list(cfg.dimensions.keys())
    return rubrics, high_ref, low_ref, dimension_names


@observe(name="evaluate-dimension")
def evaluate_dimension(
    ad_fields: dict[str, str],
    dimension_name: str,
    rubric: str,
    high_ref: str,
    low_ref: str,
) -> tuple[DimensionScore, dict[str, Any]]:
    """Score a single ad on one quality dimension via Gemini.

    Accepts ad_fields as a plain dict so it works with both GeneratedAd
    instances and raw calibration ad dicts.

    Returns (DimensionScore, token_usage_dict).
    """
    config = get_config()
    client = get_gemini_client()
    template = _load_prompt_template()

    display_name = dimension_name.replace("_", " ").title()

    user_prompt = template["user"].format(
        primary_text=ad_fields["primary_text"],
        headline=ad_fields["headline"],
        description=ad_fields["description"],
        cta_button=ad_fields["cta_button"],
        dimension_name=display_name,
        dimension_rubric=rubric,
        high_reference=high_ref,
        low_reference=low_ref,
    )

    usage_info: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model=config.models.evaluator,
                contents=user_prompt,
                config={
                    "system_instruction": template["system"],
                    "temperature": 0,
                },
            )

            input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
            usage_info = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": _estimate_cost(input_tokens, output_tokens),
            }

            parsed = _extract_json(response.text)
            score = DimensionScore(
                score=int(parsed["score"]),
                rationale=parsed["rationale"],
                confidence=parsed["confidence"],
            )
            console.print(
                f"  [green]✓[/green] {display_name}: "
                f"[bold]{score.score}[/bold]/10 "
                f"({score.confidence} confidence)"
            )
            try:
                get_langfuse().update_current_span(
                    metadata={"dimension": dimension_name, "score": score.score, "confidence": score.confidence},
                )
            except Exception:
                pass
            return score, usage_info

        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            if attempt == 0:
                console.print(
                    f"  [yellow]⟳[/yellow] {display_name}: parse error, retrying… ({exc})"
                )
                continue

            console.print(
                f"  [red]✗[/red] {display_name}: parse failed after retry — defaulting to 5"
            )
            fallback = DimensionScore(
                score=5,
                rationale="Evaluation failed — parse error",
                confidence="low",
            )
            return fallback, usage_info

    # Unreachable, but satisfies the type checker
    fallback = DimensionScore(score=5, rationale="Evaluation failed", confidence="low")
    return fallback, usage_info


@observe(name="evaluate-ad")
def evaluate_ad(
    ad: GeneratedAd | dict[str, str],
    config: None = None,
) -> tuple[AdEvaluation, dict[str, Any]]:
    """Evaluate an ad across all five quality dimensions.

    Accepts either a GeneratedAd or a plain dict (for calibration ads
    with free-form CTAs that don't fit the GeneratedAd Literal).

    Returns (AdEvaluation, aggregated_usage_dict).
    """
    cfg = get_config()

    if isinstance(ad, GeneratedAd):
        ad_fields = {
            "primary_text": ad.primary_text,
            "headline": ad.headline,
            "description": ad.description,
            "cta_button": ad.cta_button,
        }
    else:
        ad_fields = ad

    rubrics = get_all_rubrics()
    calibration_ads = _load_calibration_ads()
    high_ref, low_ref = _pick_references(calibration_ads)

    dimension_names = list(cfg.dimensions.keys())
    scores: dict[str, DimensionScore] = {}
    total_usage: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    console.print(f"\n[bold]Evaluating ad across {len(dimension_names)} dimensions…[/bold]")

    for dim_name in dimension_names:
        score, usage = evaluate_dimension(
            ad_fields=ad_fields,
            dimension_name=dim_name,
            rubric=rubrics[dim_name],
            high_ref=high_ref,
            low_ref=low_ref,
        )
        scores[dim_name] = score
        total_usage["input_tokens"] += usage["input_tokens"]
        total_usage["output_tokens"] += usage["output_tokens"]
        total_usage["cost_usd"] += usage["cost_usd"]

    evaluation = AdEvaluation(**scores)

    # Print summary table
    table = Table(title="Evaluation Summary", show_lines=True)
    table.add_column("Dimension", style="cyan")
    table.add_column("Score", justify="center")
    table.add_column("Conf.", justify="center")
    table.add_column("Rationale")

    for dim_name in dimension_names:
        s = scores[dim_name]
        score_style = "green" if s.score >= 7 else ("yellow" if s.score >= 5 else "red")
        table.add_row(
            dim_name.replace("_", " ").title(),
            f"[{score_style}]{s.score}[/{score_style}]",
            s.confidence,
            s.rationale[:80] + ("…" if len(s.rationale) > 80 else ""),
        )

    table.add_section()
    agg = evaluation.aggregate_score
    agg_style = "green bold" if evaluation.passes_threshold else "red bold"
    table.add_row(
        "AGGREGATE",
        f"[{agg_style}]{agg:.2f}[/{agg_style}]",
        "—",
        f"{'PASS' if evaluation.passes_threshold else 'FAIL'} "
        f"(threshold 7.25) | weakest: {evaluation.weakest_dimension}",
    )
    console.print(table)

    total_usage["total_tokens"] = total_usage["input_tokens"] + total_usage["output_tokens"]
    console.print(
        f"  Tokens: {total_usage['input_tokens']:,} in / "
        f"{total_usage['output_tokens']:,} out | "
        f"Est. cost: ${total_usage['cost_usd']:.4f}"
    )

    try:
        get_langfuse().update_current_span(
            metadata={
                "aggregate_score": agg,
                "passes_threshold": evaluation.passes_threshold,
                "weakest_dimension": evaluation.weakest_dimension,
            },
        )
    except Exception:
        pass

    return evaluation, total_usage

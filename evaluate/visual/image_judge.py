"""Multimodal image judge for ad creatives.

Evaluates generated ad images across four visual quality dimensions using
Gemini 2.5 Flash as a multimodal judge. Mirrors the text evaluation pattern
in evaluate/judge.py but sends [prompt_text, PIL Image] for vision analysis.
"""

from __future__ import annotations

import json
import re
from typing import Any

from PIL import Image
from rich.console import Console
from rich.table import Table

from config.loader import get_config, get_gemini_client
from config.observability import get_langfuse, observe
from evaluate.visual.rubrics import get_all_visual_rubrics
from generate.models import Config, DimensionScore, GeneratedAd, VisualEvaluation

console = Console()

# gemini-2.5-flash pricing (USD per 1M tokens)
_INPUT_COST_PER_M = 0.30
_OUTPUT_COST_PER_M = 2.50


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


def get_visual_evaluation_context() -> tuple[dict[str, str], list[str]]:
    """Return shared visual evaluation context.

    Returns (rubrics, dimension_names) for use by streaming endpoints.
    """
    rubrics = get_all_visual_rubrics()
    dimension_names = list(rubrics.keys())
    return rubrics, dimension_names


@observe(name="evaluate-image-dimension")
def evaluate_image_dimension(
    image: Image.Image,
    ad: GeneratedAd,
    dimension_name: str,
    rubric: str,
) -> tuple[DimensionScore, dict[str, Any]]:
    """Score a single ad image on one visual quality dimension via Gemini.

    Sends multimodal content [prompt_text, image] to the visual evaluation
    model. Returns (DimensionScore, token_usage_dict).
    """
    config = get_config()
    client = get_gemini_client()

    model_name = (
        config.visual_evaluation_config.model
        if config.visual_evaluation_config
        else "gemini-2.5-flash"
    )
    display_name = dimension_name.replace("_", " ").title()

    prompt_text = (
        "You are evaluating a Facebook/Instagram ad IMAGE for Varsity Tutors SAT prep.\n"
        "The ad copy this image accompanies:\n"
        f"Primary Text: {ad.primary_text}\n"
        f"Headline: {ad.headline}\n"
        f"Description: {ad.description}\n\n"
        "Evaluate the IMAGE (not the text copy) on this dimension:\n\n"
        f"{rubric}\n\n"
        "SCORING RULES:\n"
        "- Use the full 1-10 scale. Do not cluster around 6-8.\n"
        "- A score of 5 means 'mediocre — not terrible, not good.'\n"
        "- A score of 7 means 'publishable quality — meets the bar.'\n"
        "- A score of 9-10 means 'exceptional — top 5% of ad creatives you've seen.'\n"
        "- A score of 1-3 means 'significant problems — would not publish.'\n\n"
        "Think step-by-step about the image, then respond with ONLY a JSON object:\n"
        '{"thinking": "your step-by-step reasoning", '
        '"score": <integer 1-10>, '
        '"rationale": "2-3 sentence explanation", '
        '"confidence": "low" | "medium" | "high"}'
    )

    usage_info: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[prompt_text, image],
                config={"temperature": 0},
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
                    metadata={
                        "dimension": dimension_name,
                        "score": score.score,
                        "confidence": score.confidence,
                    },
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
                rationale="Visual evaluation failed — parse error",
                confidence="low",
            )
            return fallback, usage_info

    fallback = DimensionScore(score=5, rationale="Visual evaluation failed", confidence="low")
    return fallback, usage_info


@observe(name="evaluate-ad-image")
def evaluate_ad_image(
    image: Image.Image,
    ad: GeneratedAd,
    config: Config | None = None,
) -> tuple[VisualEvaluation, dict[str, Any]]:
    """Evaluate an ad image across all four visual quality dimensions.

    Returns (VisualEvaluation, aggregated_usage_dict).
    """
    if config is None:
        config = get_config()

    rubrics = get_all_visual_rubrics()
    dimension_names = list(rubrics.keys())

    scores: dict[str, DimensionScore] = {}
    total_usage: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    console.print(f"\n[bold]Evaluating image across {len(dimension_names)} visual dimensions…[/bold]")

    for dim_name in dimension_names:
        score, usage = evaluate_image_dimension(
            image=image,
            ad=ad,
            dimension_name=dim_name,
            rubric=rubrics[dim_name],
        )
        scores[dim_name] = score
        total_usage["input_tokens"] += usage["input_tokens"]
        total_usage["output_tokens"] += usage["output_tokens"]
        total_usage["cost_usd"] += usage["cost_usd"]

    evaluation = VisualEvaluation(**scores)

    table = Table(title="Visual Evaluation Summary", show_lines=True)
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
    agg = evaluation.visual_aggregate_score
    threshold = (
        config.visual_evaluation_config.threshold
        if config.visual_evaluation_config
        else 7.0
    )
    agg_style = "green bold" if evaluation.passes_visual_threshold else "red bold"
    table.add_row(
        "AGGREGATE",
        f"[{agg_style}]{agg:.2f}[/{agg_style}]",
        "—",
        f"{'PASS' if evaluation.passes_visual_threshold else 'FAIL'} "
        f"(threshold {threshold}) | weakest: {evaluation.weakest_visual_dimension}",
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
                "visual_aggregate_score": agg,
                "passes_visual_threshold": evaluation.passes_visual_threshold,
                "weakest_visual_dimension": evaluation.weakest_visual_dimension,
            },
        )
    except Exception:
        pass

    return evaluation, total_usage

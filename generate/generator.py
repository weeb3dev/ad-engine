"""Ad copy generation module.

Generates Facebook/Instagram ad copy for Varsity Tutors SAT prep using
Gemini, with support for multiple hook styles and few-shot examples.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.panel import Panel

from config.loader import get_config, get_gemini_client
from generate.models import AdBrief, Config, GeneratedAd

console = Console()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PROMPT_PATH = _PROJECT_ROOT / "generate" / "prompts" / "generator_prompt.yaml"
_CALIBRATION_PATH = _PROJECT_ROOT / "compete" / "references" / "calibration_ads.json"

_INPUT_COST_PER_M = 1.25
_OUTPUT_COST_PER_M = 10.00

HOOK_STYLES = ["question", "stat", "story", "fear"]

_prompt_cache: dict[str, str] | None = None


def _load_prompt_template() -> dict[str, str]:
    global _prompt_cache
    if _prompt_cache is None:
        with open(_PROMPT_PATH) as f:
            _prompt_cache = yaml.safe_load(f)
    return _prompt_cache  # type: ignore[return-value]


def _load_calibration_ads() -> list[dict[str, Any]]:
    with open(_CALIBRATION_PATH) as f:
        return json.load(f)


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


def _resolve_audience(brief: AdBrief, config: Config) -> str:
    """Map audience_segment ID to its human-readable label."""
    for seg in config.brand.audience_segments:
        if seg.id == brief.audience_segment:
            return seg.label
    return brief.audience_segment


def load_few_shot_examples(dimension: str | None = None) -> str:
    """Load high-quality calibration ads formatted as few-shot examples.

    If *dimension* is provided, examples are sorted by that dimension's
    expected score (descending) so the best exemplars for that dimension
    appear first.
    """
    ads = _load_calibration_ads()
    high_ads = [a for a in ads if a["expected_quality"] == "high"]

    if dimension and high_ads:
        high_ads.sort(
            key=lambda a: a.get("dimension_expectations", {}).get(dimension, 0),
            reverse=True,
        )

    examples = high_ads[:3]
    if not examples:
        return ""

    lines = ["HIGH-SCORING REFERENCE ADS (study what makes them effective):\n"]
    for i, ad in enumerate(examples, 1):
        lines.append(
            f"EXAMPLE {i}:\n"
            f"Primary Text: {ad['primary_text']}\n"
            f"Headline: {ad['headline']}\n"
            f"Description: {ad['description']}\n"
            f"CTA Button: {ad['cta_button']}\n"
        )
    return "\n".join(lines)


def generate_ad(
    brief: AdBrief,
    config: Config,
    hook_style: str = "question",
    few_shot_examples: str = "",
) -> tuple[GeneratedAd, dict[str, Any]]:
    """Generate a single ad from a brief.

    Returns (GeneratedAd, usage_dict) where usage_dict contains
    input_tokens, output_tokens, and cost_usd.
    """
    client = get_gemini_client()
    template = _load_prompt_template()

    audience_description = _resolve_audience(brief, config)

    user_prompt = template["user"].format(
        audience_description=audience_description,
        campaign_goal=brief.campaign_goal,
        tone=brief.tone or config.brand.voice,
        specific_offer=brief.specific_offer or "None specified",
        hook_style=hook_style,
        few_shot_examples=few_shot_examples,
    )

    console.print(f"\n[bold cyan]Generating ad[/bold cyan]  hook={hook_style}  audience={audience_description}")

    temperatures = [1.0, 0.7]

    for attempt, temp in enumerate(temperatures):
        try:
            response = client.models.generate_content(
                model=config.models.generator,
                contents=user_prompt,
                config={
                    "system_instruction": template["system"],
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
            ad = GeneratedAd(**parsed)

            console.print(Panel(
                f"[bold]{ad.headline}[/bold]\n"
                f"{ad.primary_text[:120]}{'…' if len(ad.primary_text) > 120 else ''}\n"
                f"[dim]{ad.description}[/dim]\n"
                f"[[ {ad.cta_button} ]]",
                title=f"Generated Ad (hook={hook_style})",
                border_style="green",
            ))
            console.print(
                f"  Tokens: {input_tokens:,} in / {output_tokens:,} out | "
                f"Est. cost: ${usage['cost_usd']:.4f}"
            )

            return ad, usage

        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            if attempt == 0:
                console.print(f"  [yellow]⟳[/yellow] Parse error (temp={temp}), retrying with temp=0.7… ({exc})")
                continue
            raise ValueError(
                f"Failed to generate valid ad after 2 attempts: {exc}"
            ) from exc

    raise ValueError("Unreachable — generation loop exited without return")


def generate_ad_variants(
    brief: AdBrief,
    config: Config,
    num_variants: int = 4,
) -> list[tuple[GeneratedAd, dict[str, Any]]]:
    """Generate multiple ad variants, one per hook style.

    Returns up to *num_variants* (GeneratedAd, usage_dict) tuples.
    """
    examples = load_few_shot_examples()
    styles = HOOK_STYLES[:num_variants]
    results: list[tuple[GeneratedAd, dict[str, Any]]] = []

    console.print(f"\n[bold]Generating {len(styles)} ad variants…[/bold]")

    for style in styles:
        try:
            ad, usage = generate_ad(brief, config, hook_style=style, few_shot_examples=examples)
            results.append((ad, usage))
        except ValueError as exc:
            console.print(f"  [red]✗[/red] hook={style} failed: {exc}")

    console.print(f"\n[bold]Generated {len(results)}/{len(styles)} variants successfully.[/bold]")
    return results

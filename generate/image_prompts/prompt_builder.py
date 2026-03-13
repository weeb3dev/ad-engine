"""Image prompt assembly from YAML templates.

Loads structured templates and combines audience scene, style modifier,
campaign goal, headline instruction, placement, and base instructions
into a single natural-language paragraph for Nano Banana 2.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from generate.models import AdBrief, Config, GeneratedAd

_TEMPLATES_PATH = Path(__file__).resolve().parent / "templates.yaml"

_template_cache: dict[str, Any] | None = None


def _load_templates() -> dict[str, Any]:
    global _template_cache
    if _template_cache is None:
        with open(_TEMPLATES_PATH) as f:
            _template_cache = yaml.safe_load(f)
    return _template_cache


def build_full_image_prompt(
    ad: GeneratedAd,
    brief: AdBrief,
    style: str,
    placement: str = "feed_square",
    config: Config | None = None,
) -> str:
    """Assemble a complete image generation prompt from YAML templates.

    Returns a single coherent paragraph (Nano Banana responds best to
    natural language, not bullet points).
    """
    t = _load_templates()

    audience_scene = t["audience_scenes"].get(
        brief.audience_segment,
        "A clean, well-lit, modern setting with warm natural light.",
    )

    style_modifier = t["style_modifiers"].get(
        style,
        t["style_modifiers"].get("photorealistic", ""),
    )

    goal_modifier = t["campaign_goal_modifiers"].get(
        brief.campaign_goal,
        "",
    )

    overlay_mode = "programmatic"
    if config and config.image_generation:
        overlay_mode = config.image_generation.text_overlay_mode

    if overlay_mode == "ai":
        headline_instruction = t["headline_instruction_ai"].format(
            headline=ad.headline,
        )
    else:
        headline_instruction = t["headline_instruction_programmatic"]

    placement_instruction = t["placement_instructions"].get(
        placement,
        t["placement_instructions"].get("feed_square", ""),
    )

    base = t["base_instructions"]

    parts = [
        audience_scene.strip(),
        style_modifier.strip(),
        goal_modifier.strip(),
        headline_instruction.strip(),
        placement_instruction.strip(),
        base.strip(),
    ]

    return " ".join(p for p in parts if p)

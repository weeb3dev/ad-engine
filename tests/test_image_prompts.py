"""Tests for generate/image_prompts/prompt_builder.py.

Verifies that prompt assembly correctly maps audience segments, style
modifiers, and overlay branches into coherent image generation prompts.
"""

from __future__ import annotations

import pytest

from generate.image_prompts.prompt_builder import build_full_image_prompt
from generate.models import AdBrief, Config, GeneratedAd


@pytest.fixture
def _ad() -> GeneratedAd:
    return GeneratedAd(
        primary_text="Is your child ready for the digital SAT?",
        headline="Expert SAT Prep",
        description="Join 40,000+ students who raised their scores.",
        cta_button="Try Free",
    )


@pytest.fixture
def _config() -> Config:
    return Config.from_yaml("config/config.yaml")


_SEGMENT_KEYWORDS: dict[str, list[str]] = {
    "athlete_family": ["athlete", "sports"],
    "suburban_optimizer": ["kitchen", "home"],
    "immigrant_navigator": ["diverse", "family"],
    "cultural_investor": ["prep materials", "focused"],
    "system_optimizer": ["data", "professional"],
    "neurodivergent_advocate": ["calm", "focus"],
    "burned_returner": ["fresh", "hopeful"],
    "stressed_students": ["bright", "focused"],
    "comparison_shoppers": ["aspirational", "confident"],
}


@pytest.mark.parametrize("segment,keywords", list(_SEGMENT_KEYWORDS.items()))
def test_prompt_contains_audience_scene(segment, keywords, _ad, _config):
    brief = AdBrief(audience_segment=segment, campaign_goal="awareness")
    prompt = build_full_image_prompt(_ad, brief, style="photorealistic", config=_config)
    prompt_lower = prompt.lower()
    assert any(
        kw.lower() in prompt_lower for kw in keywords
    ), f"Prompt for segment '{segment}' missing expected keywords {keywords}. Got: {prompt[:200]}"


def test_prompt_photorealistic_style(_ad, _config):
    brief = AdBrief(audience_segment="suburban_optimizer", campaign_goal="conversion")
    prompt = build_full_image_prompt(_ad, brief, style="photorealistic", config=_config)
    prompt_lower = prompt.lower()
    assert any(
        term in prompt_lower for term in ["dslr", "depth of field", "natural"]
    )


def test_prompt_ugc_no_text_instruction(_ad, _config):
    brief = AdBrief(audience_segment="stressed_students", campaign_goal="awareness")
    prompt = build_full_image_prompt(_ad, brief, style="ugc_style", config=_config)
    assert "Do NOT render any text" in prompt or "Do NOT include any text" in prompt


def test_prompt_hero_style_leave_top_clear(_ad, _config):
    brief = AdBrief(audience_segment="suburban_optimizer", campaign_goal="conversion")
    prompt = build_full_image_prompt(_ad, brief, style="hero_photo", config=_config)
    prompt_lower = prompt.lower()
    assert "top" in prompt_lower
    assert "clean" in prompt_lower or "bright" in prompt_lower


def test_prompt_ai_text_styles_include_headline(_ad, _config):
    brief = AdBrief(audience_segment="suburban_optimizer", campaign_goal="conversion")
    prompt = build_full_image_prompt(_ad, brief, style="infographic", config=_config)
    assert "Expert SAT Prep" in prompt


def test_prompt_programmatic_no_text(_ad, _config):
    brief = AdBrief(audience_segment="stressed_students", campaign_goal="awareness")
    prompt = build_full_image_prompt(_ad, brief, style="photorealistic", config=_config)
    assert "Do NOT render any text" in prompt

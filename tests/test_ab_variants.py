"""Tests for generate/ab_variants.py variant selection logic."""

from __future__ import annotations

import pytest

from generate.ab_variants import select_best_variant
from generate.models import DimensionScore, ImageVariant, VisualEvaluation


def _make_variant(style: str, score: int) -> ImageVariant:
    """Build an ImageVariant with a uniform visual score."""
    dim = DimensionScore(score=score, rationale="Test.", confidence="high")
    return ImageVariant(
        variant_id=f"test_{style}",
        style=style,
        placement="feed_square",
        image_path=f"data/images/test_{style}.png",
        visual_evaluation=VisualEvaluation(
            brand_consistency=dim,
            engagement_potential=dim,
            text_image_coherence=dim,
            technical_quality=dim,
        ),
        generation_cost_usd=0.067,
        evaluation_cost_usd=0.008,
        generation_time_s=5.0,
    )


def test_select_best_variant_highest_score():
    variants = [
        _make_variant("illustration", 6),
        _make_variant("photorealistic", 8),
        _make_variant("ugc_style", 7),
    ]
    winner = select_best_variant(variants)
    assert winner.style == "photorealistic"
    assert winner.visual_evaluation.visual_aggregate_score == 8.0


def test_select_best_variant_tiebreaker_conversion():
    # hero_photo at 7, ugc_style at 7 (delta = 0, within 0.5)
    variants = [
        _make_variant("hero_photo", 7),
        _make_variant("ugc_style", 7),
    ]
    winner = select_best_variant(variants, campaign_goal="conversion")
    assert winner.style == "hero_photo"

    winner_awareness = select_best_variant(variants, campaign_goal="awareness")
    assert winner_awareness.style == "ugc_style"


def test_select_best_variant_empty_raises():
    with pytest.raises(ValueError, match="No variants"):
        select_best_variant([])

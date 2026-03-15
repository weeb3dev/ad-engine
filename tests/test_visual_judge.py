"""Tests for visual evaluation rubrics and model computed fields."""

from __future__ import annotations

from evaluate.visual.rubrics import get_visual_rubric
from generate.models import DimensionScore, VisualEvaluation


def test_get_visual_rubric_returns_string():
    rubric = get_visual_rubric("brand_consistency")
    assert isinstance(rubric, str)
    assert len(rubric) > 0
    assert "Brand Consistency" in rubric


def test_visual_evaluation_aggregate():
    dim = lambda s: DimensionScore(score=s, rationale="Test.", confidence="high")
    ve = VisualEvaluation(
        brand_consistency=dim(8),
        engagement_potential=dim(7),
        text_image_coherence=dim(6),
        technical_quality=dim(9),
    )
    # 0.30*8 + 0.30*7 + 0.25*6 + 0.15*9 = 2.4 + 2.1 + 1.5 + 1.35 = 7.35
    assert ve.visual_aggregate_score == 7.35
    assert ve.weakest_visual_dimension == "text_image_coherence"


def test_visual_threshold_pass_fail():
    dim = lambda s: DimensionScore(score=s, rationale="Test.", confidence="high")

    # All 5s -> aggregate = 5.0 (well below 7.0)
    low = VisualEvaluation(
        brand_consistency=dim(5),
        engagement_potential=dim(5),
        text_image_coherence=dim(5),
        technical_quality=dim(5),
    )
    assert low.passes_visual_threshold is False

    # All 7s -> aggregate = 7.0 (exactly at 7.0 threshold)
    high = VisualEvaluation(
        brand_consistency=dim(7),
        engagement_potential=dim(7),
        text_image_coherence=dim(7),
        technical_quality=dim(7),
    )
    assert high.passes_visual_threshold is True

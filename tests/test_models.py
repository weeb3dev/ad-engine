"""Tests for Pydantic data models in generate/models.py."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from generate.models import (
    AdBrief,
    AdEvaluation,
    DimensionScore,
    GeneratedAd,
)


def test_ad_brief_creation(sample_brief):
    assert sample_brief.audience_segment == "suburban_optimizer"
    assert sample_brief.campaign_goal == "conversion"
    assert sample_brief.product == "sat_prep"


def test_ad_brief_invalid_goal():
    with pytest.raises(ValidationError):
        AdBrief(audience_segment="suburban_optimizer", campaign_goal="invalid_goal")


def test_generated_ad_headline_max_length():
    with pytest.raises(ValidationError):
        GeneratedAd(
            primary_text="Valid text.",
            headline="x" * 81,
            description="Valid description.",
            cta_button="Try Free",
        )


def test_dimension_score_range():
    with pytest.raises(ValidationError):
        DimensionScore(score=0, rationale="Too low.", confidence="high")

    with pytest.raises(ValidationError):
        DimensionScore(score=11, rationale="Too high.", confidence="high")

    valid = DimensionScore(score=1, rationale="Edge.", confidence="low")
    assert valid.score == 1

    valid_top = DimensionScore(score=10, rationale="Edge.", confidence="high")
    assert valid_top.score == 10


def test_ad_evaluation_aggregate_score(sample_evaluation):
    # All scores are 8; weights sum to 1.0 -> aggregate = 8.0
    assert sample_evaluation.aggregate_score == 8.0
    assert sample_evaluation.passes_threshold is True
    # All equal -> weakest is whichever min() picks first (alphabetical key order
    # in dict insertion order: "clarity" comes first)
    assert sample_evaluation.weakest_dimension in {
        "clarity",
        "value_proposition",
        "call_to_action",
        "brand_voice",
        "emotional_resonance",
    }

"""Shared pytest fixtures for the ad-engine test suite."""

from __future__ import annotations

import pytest

from generate.models import (
    AdBrief,
    AdEvaluation,
    Config,
    DimensionScore,
    GeneratedAd,
)


@pytest.fixture
def sample_brief() -> AdBrief:
    return AdBrief(
        audience_segment="anxious_parents",
        campaign_goal="conversion",
        tone="empathetic",
        specific_offer="Free SAT practice test",
    )


@pytest.fixture
def sample_ad() -> GeneratedAd:
    return GeneratedAd(
        primary_text="Is your child's SAT score holding them back? Our expert tutors help students improve 200+ points.",
        headline="Raise Their SAT Score",
        description="Join 40,000+ students who improved with Varsity Tutors.",
        cta_button="Try Free",
    )


@pytest.fixture
def sample_dimension_score() -> DimensionScore:
    return DimensionScore(
        score=8,
        rationale="Clear single message with a strong hook.",
        confidence="high",
    )


@pytest.fixture
def sample_evaluation() -> AdEvaluation:
    """Evaluation where every dimension scores 8."""
    dim = lambda: DimensionScore(score=8, rationale="Solid.", confidence="high")
    return AdEvaluation(
        clarity=dim(),
        value_proposition=dim(),
        call_to_action=dim(),
        brand_voice=dim(),
        emotional_resonance=dim(),
    )


@pytest.fixture
def config() -> Config:
    return Config.from_yaml("config/config.yaml")

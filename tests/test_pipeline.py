"""Tests for the LLM pipeline with mocked Gemini responses."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from generate.models import AdBrief, Config, DimensionScore, GeneratedAd


def _mock_response(text: str, input_tokens: int = 100, output_tokens: int = 50):
    """Build a fake Gemini response object."""
    resp = MagicMock()
    resp.text = text
    resp.usage_metadata = SimpleNamespace(
        prompt_token_count=input_tokens,
        candidates_token_count=output_tokens,
    )
    return resp


def _dimension_json(score: int = 8) -> str:
    return json.dumps({
        "thinking": "Looks good.",
        "score": score,
        "rationale": "Well-crafted copy.",
        "confidence": "high",
    })


def _ad_json() -> str:
    return json.dumps({
        "primary_text": "Improved ad text here.",
        "headline": "Better Headline",
        "description": "Better description for the ad.",
        "cta_button": "Try Free",
    })


# ---- helpers to build a mock client ----

def _make_mock_client(side_effect=None, return_value=None):
    client = MagicMock()
    if side_effect is not None:
        client.models.generate_content.side_effect = side_effect
    elif return_value is not None:
        client.models.generate_content.return_value = return_value
    return client


# -----------------------------------------------------------------------
# Test 1: evaluate_dimension with a mocked Gemini response
# -----------------------------------------------------------------------

@patch("evaluate.judge.get_gemini_client")
@patch("evaluate.judge.get_config")
def test_evaluate_dimension_mock(mock_get_config, mock_get_client):
    mock_get_config.return_value = Config.from_yaml("config/config.yaml")
    mock_get_client.return_value = _make_mock_client(
        return_value=_mock_response(_dimension_json(9))
    )

    from evaluate.judge import evaluate_dimension

    score, usage = evaluate_dimension(
        ad_fields={
            "primary_text": "Great ad text.",
            "headline": "Strong Headline",
            "description": "Compelling description.",
            "cta_button": "Try Free",
        },
        dimension_name="clarity",
        rubric="Test rubric content.",
        high_ref="High ref ad.",
        low_ref="Low ref ad.",
    )

    assert isinstance(score, DimensionScore)
    assert score.score == 9
    assert score.confidence == "high"
    assert usage["input_tokens"] == 100


# -----------------------------------------------------------------------
# Test 2: run_pipeline passes on first try with high scores
# -----------------------------------------------------------------------

@patch("iterate.feedback.evaluate_ad")
@patch("iterate.feedback.generate_ad")
def test_run_pipeline_passes_first_try(mock_generate, mock_evaluate, config, sample_ad, sample_evaluation):
    mock_generate.return_value = (sample_ad, {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001})
    mock_evaluate.return_value = (sample_evaluation, {"input_tokens": 500, "output_tokens": 250, "cost_usd": 0.005})

    from iterate.feedback import run_pipeline

    brief = AdBrief(
        audience_segment="anxious_parents",
        campaign_goal="conversion",
        specific_offer="Free SAT practice test",
    )

    record = run_pipeline(brief, config)

    assert record.evaluation.passes_threshold is True
    assert record.iteration_cycle == 1
    assert record.improvement_strategy is None
    mock_generate.assert_called_once()


# -----------------------------------------------------------------------
# Test 3: run_pipeline retries when first evaluation fails threshold
# -----------------------------------------------------------------------

@patch("iterate.feedback.evaluate_ad")
@patch("iterate.feedback.improve_ad")
@patch("iterate.feedback.generate_ad")
def test_run_pipeline_retries_on_low_score(
    mock_generate, mock_improve, mock_evaluate, config, sample_ad, sample_evaluation
):
    from generate.models import AdEvaluation, DimensionScore

    low_dim = lambda: DimensionScore(score=4, rationale="Weak.", confidence="medium")
    low_eval = AdEvaluation(
        clarity=low_dim(),
        value_proposition=low_dim(),
        call_to_action=low_dim(),
        brand_voice=low_dim(),
        emotional_resonance=low_dim(),
    )

    improved_ad = GeneratedAd(
        primary_text="Much better ad text after improvement.",
        headline="Improved Headline",
        description="Improved description.",
        cta_button="Get Started",
    )

    usage = {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001}

    mock_generate.return_value = (sample_ad, usage)
    mock_evaluate.side_effect = [
        (low_eval, usage),       # first eval: fails
        (sample_evaluation, usage),  # re-eval after improvement: passes
    ]
    mock_improve.return_value = (improved_ad, usage)

    from iterate.feedback import run_pipeline

    brief = AdBrief(
        audience_segment="stressed_students",
        campaign_goal="awareness",
    )

    record = run_pipeline(brief, config)

    assert record.iteration_cycle == 2
    assert record.evaluation.passes_threshold is True
    mock_improve.assert_called_once()

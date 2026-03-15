"""Tests for iterate/multimodal_pipeline.py helpers."""

from __future__ import annotations

from iterate.multimodal_pipeline import (
    _TEXT_WEIGHT,
    _VISUAL_WEIGHT,
    _is_rate_limit_error,
)


def test_combined_score_formula():
    assert _TEXT_WEIGHT == 0.6
    assert _VISUAL_WEIGHT == 0.4
    combined = round(_TEXT_WEIGHT * 8.0 + _VISUAL_WEIGHT * 7.0, 2)
    assert combined == 7.6


def test_is_rate_limit_error():
    assert _is_rate_limit_error(Exception("429 Too Many Requests"))
    assert _is_rate_limit_error(Exception("resource exhausted"))
    assert _is_rate_limit_error(Exception("rate limit exceeded"))

    class ResourceExhausted(Exception):
        pass

    assert _is_rate_limit_error(ResourceExhausted("quota"))

    assert not _is_rate_limit_error(Exception("connection timeout"))
    assert not _is_rate_limit_error(ValueError("invalid input"))

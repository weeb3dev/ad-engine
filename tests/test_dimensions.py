"""Tests for evaluate/dimensions.py rubric generation."""

from __future__ import annotations

from evaluate.dimensions import get_all_rubrics, get_rubric


def test_get_rubric_returns_string():
    rubric = get_rubric("clarity")
    assert isinstance(rubric, str)
    assert len(rubric) > 0
    assert "Clarity" in rubric


def test_get_all_rubrics_has_five():
    rubrics = get_all_rubrics()
    assert len(rubrics) == 5
    expected_keys = {
        "clarity",
        "value_proposition",
        "call_to_action",
        "brand_voice",
        "emotional_resonance",
    }
    assert set(rubrics.keys()) == expected_keys

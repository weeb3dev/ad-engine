"""Tests for generate/briefs.py brief matrix generation."""

from __future__ import annotations

from generate.briefs import DEFAULT_SEGMENTS, generate_brief_matrix


def test_generate_brief_matrix_count():
    briefs = generate_brief_matrix()
    assert len(briefs) == 162  # 9 segments x 2 goals x 3 offers x 3 tones


def test_brief_matrix_coverage():
    briefs = generate_brief_matrix()
    segments = {b.audience_segment for b in briefs}
    assert segments == set(DEFAULT_SEGMENTS)

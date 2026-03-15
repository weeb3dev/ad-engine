"""Tests for generate/image_generator.py utility functions.

No API calls — tests only cover local helpers: save, cost estimation,
placement mapping, and overlay style sets.
"""

from __future__ import annotations

from PIL import Image

from generate.image_generator import (
    _HERO_STYLES,
    _IMAGE_COST_PER_UNIT,
    _PLACEMENT_ASPECT_RATIOS,
    _SKIP_PIL_OVERLAY,
    _estimate_image_cost,
    save_ad_image,
)


def test_save_ad_image(tmp_path):
    img = Image.new("RGB", (10, 10), color="blue")
    path = save_ad_image(img, "ad_001", 0, "photorealistic", output_dir=str(tmp_path))
    assert path == str(tmp_path / "ad_001_v0_photorealistic.png")
    assert (tmp_path / "ad_001_v0_photorealistic.png").exists()


def test_estimate_image_cost():
    cost = _estimate_image_cost("1K", 1000, 500)
    text_cost = (1000 * 0.50 + 500 * 3.00) / 1_000_000
    image_cost = _IMAGE_COST_PER_UNIT["1K"]
    assert abs(cost - (text_cost + image_cost)) < 1e-9


def test_placement_aspect_ratio_mapping():
    assert _PLACEMENT_ASPECT_RATIOS == {
        "feed_square": "1:1",
        "stories_vertical": "9:16",
        "feed_landscape": "16:9",
    }


def test_skip_overlay_sets():
    assert "ugc_style" in _SKIP_PIL_OVERLAY
    assert "infographic" in _SKIP_PIL_OVERLAY
    assert "typography_checklist" in _SKIP_PIL_OVERLAY
    assert "comic_panel" in _SKIP_PIL_OVERLAY
    assert "hero_photo" in _HERO_STYLES
    assert "photorealistic" not in _SKIP_PIL_OVERLAY

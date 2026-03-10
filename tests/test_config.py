"""Tests for config loading and validation."""

from __future__ import annotations

from generate.models import Config


def test_config_loads(config):
    assert config is not None
    assert config.models.generator
    assert config.models.evaluator


def test_config_dimensions_sum_to_one(config):
    total = sum(d.weight for d in config.dimensions.values())
    assert abs(total - 1.0) < 0.01


def test_config_threshold(config):
    assert config.quality.threshold == 7.0

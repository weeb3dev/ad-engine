"""Pydantic v2 data models for the Autonomous Ad Engine.

Defines the core data structures used across generation, evaluation,
iteration, and output stages of the pipeline.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


# ---------------------------------------------------------------------------
# Dimension weight defaults — must stay in sync with config/config.yaml
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS: dict[str, float] = {
    "clarity": 0.25,
    "value_proposition": 0.25,
    "call_to_action": 0.20,
    "brand_voice": 0.15,
    "emotional_resonance": 0.15,
}

VISUAL_DEFAULT_WEIGHTS: dict[str, float] = {
    "brand_consistency": 0.30,
    "engagement_potential": 0.30,
    "text_image_coherence": 0.25,
    "technical_quality": 0.15,
}


# ---------------------------------------------------------------------------
# 1. AdBrief — input to the generator
# ---------------------------------------------------------------------------

class AdBrief(BaseModel):
    """Brief that drives ad copy generation."""

    audience_segment: str
    product: str = "sat_prep"
    campaign_goal: Literal["awareness", "conversion"]
    tone: Optional[str] = None
    specific_offer: Optional[str] = None
    style_approaches: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# 2. GeneratedAd — output of the generator
# ---------------------------------------------------------------------------

class GeneratedAd(BaseModel):
    """A single generated Meta (Facebook/Instagram) ad."""

    primary_text: str = Field(..., max_length=1000)
    headline: str = Field(..., max_length=80)
    description: str = Field(..., max_length=200)
    cta_button: Literal[
        "Learn More", "Sign Up", "Get Started", "Book Now", "Try Free"
    ]


# ---------------------------------------------------------------------------
# 3. DimensionScore — single-dimension evaluation result
# ---------------------------------------------------------------------------

class DimensionScore(BaseModel):
    """Score for one quality dimension of an ad."""

    score: int = Field(..., ge=1, le=10)
    rationale: str
    confidence: Literal["low", "medium", "high"]


# ---------------------------------------------------------------------------
# 4. AdEvaluation — full five-dimension evaluation with computed aggregates
# ---------------------------------------------------------------------------

class AdEvaluation(BaseModel):
    """Complete evaluation across all five quality dimensions."""

    clarity: DimensionScore
    value_proposition: DimensionScore
    call_to_action: DimensionScore
    brand_voice: DimensionScore
    emotional_resonance: DimensionScore

    @computed_field
    @property
    def aggregate_score(self) -> float:
        scores = {
            "clarity": self.clarity.score,
            "value_proposition": self.value_proposition.score,
            "call_to_action": self.call_to_action.score,
            "brand_voice": self.brand_voice.score,
            "emotional_resonance": self.emotional_resonance.score,
        }
        return round(
            sum(scores[d] * DEFAULT_WEIGHTS[d] for d in scores), 2
        )

    @computed_field
    @property
    def passes_threshold(self) -> bool:
        return self.aggregate_score >= 7.25  # keep in sync with config.yaml quality.threshold

    @computed_field
    @property
    def weakest_dimension(self) -> str:
        scores = {
            "clarity": self.clarity.score,
            "value_proposition": self.value_proposition.score,
            "call_to_action": self.call_to_action.score,
            "brand_voice": self.brand_voice.score,
            "emotional_resonance": self.emotional_resonance.score,
        }
        return min(scores, key=scores.get)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 4b. VisualEvaluation — four-dimension visual quality with computed aggregates
# ---------------------------------------------------------------------------

class VisualEvaluation(BaseModel):
    """Visual evaluation across four image quality dimensions."""

    brand_consistency: DimensionScore
    engagement_potential: DimensionScore
    text_image_coherence: DimensionScore
    technical_quality: DimensionScore

    @computed_field
    @property
    def visual_aggregate_score(self) -> float:
        scores = {
            "brand_consistency": self.brand_consistency.score,
            "engagement_potential": self.engagement_potential.score,
            "text_image_coherence": self.text_image_coherence.score,
            "technical_quality": self.technical_quality.score,
        }
        return round(
            sum(scores[d] * VISUAL_DEFAULT_WEIGHTS[d] for d in scores), 2
        )

    @computed_field
    @property
    def passes_visual_threshold(self) -> bool:
        return self.visual_aggregate_score >= 6.5

    @computed_field
    @property
    def weakest_visual_dimension(self) -> str:
        scores = {
            "brand_consistency": self.brand_consistency.score,
            "engagement_potential": self.engagement_potential.score,
            "text_image_coherence": self.text_image_coherence.score,
            "technical_quality": self.technical_quality.score,
        }
        return min(scores, key=scores.get)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 5. AdRecord — complete ad record for the library
# ---------------------------------------------------------------------------

class AdRecord(BaseModel):
    """Full lifecycle record: brief -> generated ad -> evaluation."""

    ad_id: str
    brief: AdBrief
    generated_ad: GeneratedAd
    evaluation: AdEvaluation
    iteration_cycle: int
    improved_from: Optional[float] = None
    improvement_strategy: Optional[str] = None
    generation_cost_usd: float
    evaluation_cost_usd: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# 5b. ImageVariant — a single image variant with its evaluation
# ---------------------------------------------------------------------------

class ImageVariant(BaseModel):
    """One image variant for an ad, including its visual evaluation."""

    variant_id: str
    style: str
    placement: str = "feed_square"
    image_path: str
    visual_evaluation: VisualEvaluation
    generation_cost_usd: float
    evaluation_cost_usd: float
    generation_time_s: float


# ---------------------------------------------------------------------------
# 5c. MultiModalAdRecord — text + image combined record
# ---------------------------------------------------------------------------

class MultiModalAdRecord(BaseModel):
    """Full multimodal ad record: text pipeline output + image variants."""

    ad_id: str
    brief: AdBrief
    text_record: AdRecord
    winning_variant: ImageVariant
    all_variants: list[ImageVariant]
    combined_score: float
    total_cost_usd: float
    pipeline_time_s: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# 6. Config — loaded from config/config.yaml
# ---------------------------------------------------------------------------

class ModelConfig(BaseModel):
    generator: str
    evaluator: str
    escalation: str = "gemini-2.5-flash"


class QualityConfig(BaseModel):
    threshold: float
    max_regeneration_attempts: int


class DimensionConfig(BaseModel):
    weight: float
    description: str
    score_1: str
    score_10: str


class AudienceSegment(BaseModel):
    id: str
    label: str


class BrandConfig(BaseModel):
    name: str
    parent_company: str
    voice: str
    guidelines: list[str]
    audience_segments: list[AudienceSegment]


class VisualDimensionConfig(BaseModel):
    weight: float
    description: str
    score_1: str
    score_10: str


class ImageGenerationConfig(BaseModel):
    model: str
    default_aspect_ratio: str = "1:1"
    default_resolution: str = "1K"
    thinking_level: str = "minimal"
    variants_per_ad: int = 2
    text_overlay_mode: str = "programmatic"
    style_approaches: list[str]


class VisualEvaluationConfig(BaseModel):
    model: str
    threshold: float = 6.5
    dimensions: dict[str, VisualDimensionConfig]


class Config(BaseModel):
    """Top-level configuration loaded from config.yaml."""

    model_config = ConfigDict(populate_by_name=True)

    models: ModelConfig
    quality: QualityConfig
    dimensions: dict[str, DimensionConfig]
    brand: BrandConfig
    seed: int
    image_generation: Optional[ImageGenerationConfig] = None
    visual_evaluation_config: Optional[VisualEvaluationConfig] = Field(
        default=None, alias="visual_evaluation"
    )

    @field_validator("dimensions")
    @classmethod
    def weights_must_sum_to_one(
        cls, v: dict[str, DimensionConfig]
    ) -> dict[str, DimensionConfig]:
        total = sum(d.weight for d in v.values())
        if not (0.99 <= total <= 1.01):
            raise ValueError(
                f"Dimension weights must sum to 1.0, got {total}"
            )
        return v

    @classmethod
    def from_yaml(cls, path: str | Path = "config/config.yaml") -> Config:
        """Load and validate config from a YAML file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"Config file not found at {path.resolve()}. "
                "Make sure you're running from the project root and "
                "config/config.yaml exists."
            )
        with open(path) as f:
            raw = yaml.safe_load(f)
        return cls.model_validate(raw)

"""Targeted improvement strategies for the feedback loop.

Pure prompt-construction functions — no LLM calls. Given an ad and its
evaluation, these build regeneration prompts that focus on the weakest
dimension while preserving strengths.
"""

from __future__ import annotations

from generate.generator import load_few_shot_examples
from generate.models import AdEvaluation, Config, GeneratedAd

_STRATEGIES = {
    1: "targeted_reprompt",
    2: "few_shot_injection",
    3: "model_escalation",
}

_SYSTEM_INSTRUCTION = (
    "You are an expert direct-response copywriter specializing in Facebook "
    "and Instagram ads for Varsity Tutors, a personalized SAT test prep "
    "platform.\n\n"
    "BRAND VOICE: Empowering, knowledgeable, approachable, results-focused.\n"
    "- Lead with outcomes, not features\n"
    "- Confident but not arrogant. Expert but not elitist.\n"
    "- Meet people where they are\n\n"
    "You are revising an existing ad to improve a specific weak dimension "
    "while keeping everything else strong."
)

_ESCALATION_SYSTEM = (
    "You are the most senior creative director at a top-tier performance "
    "marketing agency. You specialize in Meta ads for EdTech brands.\n\n"
    "BRAND VOICE for Varsity Tutors: Empowering, knowledgeable, approachable, "
    "results-focused.\n"
    "- Lead with outcomes, not features\n"
    "- Confident but not arrogant. Expert but not elitist.\n"
    "- Meet people where they are\n\n"
    "A junior copywriter produced the ad below. It has a specific weakness. "
    "Rewrite it to award-winning quality. Be ruthless about the weak "
    "dimension while preserving what already works."
)


def get_strategy_name(attempt: int) -> str:
    """Map an attempt number (1-based) to a strategy name."""
    return _STRATEGIES.get(attempt, "few_shot_injection")


def get_improvement_prompt(
    ad: GeneratedAd,
    evaluation: AdEvaluation,
    dimension_name: str,
) -> str:
    """Build a basic targeted-reprompt improvement prompt."""
    dim_score = getattr(evaluation, dimension_name)
    display = dimension_name.replace("_", " ").title()

    return (
        f"## Original Ad\n\n"
        f"Primary Text: {ad.primary_text}\n"
        f"Headline: {ad.headline}\n"
        f"Description: {ad.description}\n"
        f"CTA Button: {ad.cta_button}\n\n"
        f"## Evaluation Feedback\n\n"
        f"This ad scored **{dim_score.score}/10** on **{display}**.\n"
        f"Rationale: {dim_score.rationale}\n\n"
        f"## Task\n\n"
        f"Rewrite this ad to significantly improve its {display} score "
        f"while maintaining the strengths in other dimensions.\n"
        f"Focus specifically on: {display}.\n\n"
        f"Respond with ONLY a JSON object:\n"
        f'{{\n'
        f'  "primary_text": "your improved primary text",\n'
        f'  "headline": "your improved headline",\n'
        f'  "description": "your improved description",\n'
        f'  "cta_button": "one of: Learn More, Sign Up, Get Started, Book Now, Try Free"\n'
        f'}}'
    )


def build_targeted_prompt(
    original_ad: GeneratedAd,
    weak_dimension: str,
    score: int,
    rationale: str,
    strategy: str,
    config: Config,
) -> tuple[str, str]:
    """Build the full regeneration prompt for a given strategy.

    Returns (system_instruction, user_prompt) so the caller can pass them
    directly to the Gemini client.
    """
    display = weak_dimension.replace("_", " ").title()

    base_prompt = (
        f"## Original Ad\n\n"
        f"Primary Text: {original_ad.primary_text}\n"
        f"Headline: {original_ad.headline}\n"
        f"Description: {original_ad.description}\n"
        f"CTA Button: {original_ad.cta_button}\n\n"
        f"## Evaluation Feedback\n\n"
        f"This ad scored **{score}/10** on **{display}**.\n"
        f"Rationale: {rationale}\n\n"
    )

    json_format = (
        "Respond with ONLY a JSON object:\n"
        '{\n'
        '  "primary_text": "your improved primary text",\n'
        '  "headline": "your improved headline",\n'
        '  "description": "your improved description",\n'
        '  "cta_button": "one of: Learn More, Sign Up, Get Started, Book Now, Try Free"\n'
        '}'
    )

    if strategy == "targeted_reprompt":
        user_prompt = (
            base_prompt
            + f"## Task\n\n"
            f"Rewrite this ad to significantly improve its {display} score "
            f"while maintaining the strengths in other dimensions.\n"
            f"Focus specifically on: {display}.\n\n"
            + json_format
        )
        return _SYSTEM_INSTRUCTION, user_prompt

    if strategy == "few_shot_injection":
        examples = load_few_shot_examples(dimension=weak_dimension)
        user_prompt = (
            base_prompt
            + f"## High-Scoring Examples for {display}\n\n"
            f"Study these ads that score well on {display}:\n\n"
            f"{examples}\n\n"
            f"## Task\n\n"
            f"Rewrite the original ad to match the quality of the examples "
            f"above, specifically on {display}. Preserve what already works "
            f"in the original.\n\n"
            + json_format
        )
        return _SYSTEM_INSTRUCTION, user_prompt

    # model_escalation: stronger system prompt + few-shot
    examples = load_few_shot_examples(dimension=weak_dimension)
    user_prompt = (
        base_prompt
        + f"## High-Scoring Examples for {display}\n\n"
        f"Study these ads that score well on {display}:\n\n"
        f"{examples}\n\n"
        f"## Task\n\n"
        f"Produce a top-5% rewrite. The {display} score MUST reach 8+. "
        f"Don't just tweak — reimagine the angle if needed. Preserve brand "
        f"voice and the original offer.\n\n"
        + json_format
    )
    return _ESCALATION_SYSTEM, user_prompt

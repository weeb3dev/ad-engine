"""Detailed scoring rubrics for visual quality dimensions.

Reads dimension definitions from config (visual_evaluation_config.dimensions)
and expands them into rich rubric strings for prompt injection into the
multimodal image judge. Rubrics are specific to Varsity Tutors SAT prep
ad creatives on Meta (Facebook/Instagram).
"""

from __future__ import annotations

from config.loader import get_config

# ---------------------------------------------------------------------------
# Per-dimension rubric expansions
# ---------------------------------------------------------------------------
# Each entry adds a score-5 anchor, concrete visual examples, and common
# mistakes on top of the score_1 / score_10 anchors already in config.yaml.

_VISUAL_RUBRIC_EXTRAS: dict[str, dict[str, str]] = {
    "brand_consistency": {
        "score_5": (
            "The image is professional and inoffensive but has no distinctly "
            "Varsity Tutors qualities. It could belong to any tutoring company "
            "— neutral colors, generic setting, no warmth or personality."
        ),
        "example_high": (
            "A warm, naturally-lit kitchen table scene with a parent and teen "
            "studying together. Soft blue accent tones, genuine smiles, modern "
            "but approachable decor. Immediately feels like Varsity Tutors: "
            "supportive, knowledgeable, real."
        ),
        "example_low": (
            "A sterile stock photo of a suited adult pointing at a whiteboard "
            "in a corporate conference room. Cold fluorescent lighting, no "
            "warmth, no education context. Could be a consulting firm ad."
        ),
        "common_mistakes": (
            "- Generic office or classroom stock-photo aesthetic that could "
            "belong to any company\n"
            "- Cold corporate color palette (grays, dark blues) instead of "
            "VT's warm, approachable tones\n"
            "- Adults in business attire instead of casual, relatable settings\n"
            "- Missing the education/tutoring context entirely — image shows "
            "no study materials, no learning environment\n"
            "- Overly polished studio portraits that feel posed and inauthentic"
        ),
    },
    "engagement_potential": {
        "score_5": (
            "The image is competent but forgettable. Adequate composition, "
            "nothing technically wrong, but no visual hook — a user scrolling "
            "their feed would pass right over it without slowing down."
        ),
        "example_high": (
            "A close-up of a teenager's face lighting up while looking at a "
            "laptop screen, warm golden-hour light from a window, shallow depth "
            "of field blurring the background. The expression is genuine and "
            "draws you in — you want to know what made them smile."
        ),
        "example_low": (
            "A wide shot of an empty desk with a textbook and pencil centered "
            "in frame. Flat lighting, no human element, no emotion. It's a "
            "prop photo, not a story."
        ),
        "common_mistakes": (
            "- No clear focal point — the eye wanders without landing\n"
            "- Flat, even lighting with no contrast or visual drama\n"
            "- Missing the human element — objects alone rarely stop a scroll\n"
            "- Cluttered composition with too many competing elements\n"
            "- Relying on text overlay for engagement instead of the image "
            "itself doing the work"
        ),
    },
    "text_image_coherence": {
        "score_5": (
            "The image is loosely related to the ad copy's topic (education, "
            "tutoring) but doesn't reinforce the specific message. The copy "
            "talks about a concrete benefit and the image is generically "
            "on-theme rather than amplifying that benefit."
        ),
        "example_high": (
            "Copy says 'Your child isn't struggling with the material — "
            "they're struggling with the test.' Image shows a bright teen "
            "looking confident with study materials, subtly conveying 'I know "
            "this stuff.' The image and copy tell the same story of untapped "
            "potential."
        ),
        "example_low": (
            "Copy references a specific SAT score improvement ('1180 to 1410') "
            "but the image is a generic smiling family at a park with no "
            "educational context. The image and copy could have been randomly "
            "paired."
        ),
        "common_mistakes": (
            "- Copy about a specific student story paired with a generic "
            "stock-style image\n"
            "- Copy emphasizes urgency or deadlines but image is calm and "
            "relaxed with no tension\n"
            "- Copy targets anxious parents but image shows only happy "
            "students with no parent presence\n"
            "- Audience mismatch: copy for comparison shoppers (rational) but "
            "image is purely emotional with no informational cues\n"
            "- Image tells a completely different story than the headline"
        ),
    },
    "technical_quality": {
        "score_5": (
            "The image is usable but has noticeable issues: slight blurriness, "
            "minor composition problems, or subtle AI artifacts that a careful "
            "viewer would spot. Passable for a draft but not production-ready."
        ),
        "example_high": (
            "Sharp, high-resolution image with professional composition. "
            "Clean rule-of-thirds framing, no artifacts, all hands and faces "
            "rendered correctly. Text overlay (if present) is crisp and "
            "readable. Could be published as-is."
        ),
        "example_low": (
            "Obvious AI generation artifacts: six fingers on a hand, melted "
            "text that's illegible, warped furniture in the background, "
            "inconsistent lighting between foreground and background. Would "
            "damage brand credibility if published."
        ),
        "common_mistakes": (
            "- Distorted or extra fingers/hands (classic AI artifact)\n"
            "- Melted, warped, or misspelled text baked into the image\n"
            "- Blurry or low-resolution output that looks pixelated at feed "
            "display size\n"
            "- Inconsistent lighting — foreground and background lit from "
            "different directions\n"
            "- Uncanny valley faces: almost realistic but something is off "
            "(asymmetric eyes, waxy skin, floating hair)\n"
            "- Poor composition: subject cut off at edges, too much dead "
            "space, or focal point pushed to the corner"
        ),
    },
}


def get_visual_rubric(dimension_name: str) -> str:
    """Build the full scoring rubric for a single visual dimension.

    Combines config-level anchors (score_1, score_10) with hardcoded
    score-5 examples, concrete visual examples, and common mistakes.
    """
    config = get_config()
    dims = (
        config.visual_evaluation_config.dimensions
        if config.visual_evaluation_config
        else {}
    )
    if dimension_name not in dims:
        raise ValueError(
            f"Unknown visual dimension '{dimension_name}'. "
            f"Valid: {list(dims.keys())}"
        )

    dim = dims[dimension_name]
    extras = _VISUAL_RUBRIC_EXTRAS[dimension_name]
    display_name = dimension_name.replace("_", " ").title()

    return (
        f"### {display_name} (weight: {dim.weight})\n\n"
        f"**What this measures:** {dim.description}\n\n"
        f"**Score 1 — Failing:** {dim.score_1}\n"
        f"Example: {extras['example_low']}\n\n"
        f"**Score 5 — Mediocre:** {extras['score_5']}\n\n"
        f"**Score 10 — Exceptional:** {dim.score_10}\n"
        f"Example: {extras['example_high']}\n\n"
        f"**Common mistakes that lower the score:**\n{extras['common_mistakes']}"
    )


def get_all_visual_rubrics() -> dict[str, str]:
    """Return rubrics for all four visual dimensions."""
    config = get_config()
    dims = (
        config.visual_evaluation_config.dimensions
        if config.visual_evaluation_config
        else {}
    )
    return {name: get_visual_rubric(name) for name in dims}

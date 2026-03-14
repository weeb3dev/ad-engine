"""Detailed scoring rubrics for each quality dimension.

Reads dimension definitions from config and expands them into rich rubric
strings that get injected into the LLM judge prompt. Rubrics are specific
to Varsity Tutors SAT prep ads on Meta (Facebook/Instagram).
"""

from __future__ import annotations

from config.loader import get_config

# ---------------------------------------------------------------------------
# Per-dimension rubric expansions
# ---------------------------------------------------------------------------
# Each rubric adds a score-5 anchor, concrete examples, and common mistakes
# on top of the score_1 / score_10 anchors already in config.yaml.

_RUBRIC_EXTRAS: dict[str, dict[str, str]] = {
    "clarity": {
        "score_5": (
            "The ad has a recognizable message but requires re-reading or "
            "buries the lead. The reader can figure out what's being offered "
            "but it takes more than 3 seconds."
        ),
        "example_high": (
            "\"Your child is smarter than their SAT score.\" — one clear "
            "takeaway in the first line. The rest of the ad supports that "
            "single message without competing ideas."
        ),
        "example_low": (
            "An ad that opens with a nostalgia hook, pivots to digital SAT "
            "features, name-drops three competitors, lists pricing, and ends "
            "with urgency — five messages fighting for attention."
        ),
        "common_mistakes": (
            "- Repeating the same sentence in primary text, headline, AND "
            "description (zero information density)\n"
            "- Primary text over 125 characters without a strong first-line "
            "hook (the rest hides behind 'See more' on mobile)\n"
            "- Leaving copywriting framework labels visible ('BEFORE:', "
            "'AFTER:', 'THE BRIDGE:') in the final copy\n"
            "- Bold markdown (**text**) that renders as literal asterisks on "
            "Meta placements\n"
            "- Stacking too many value claims (pricing + score improvement + "
            "competitor comparisons + feature lists) — when an ad tries to "
            "communicate 5 propositions at once, none of them land"
        ),
    },
    "value_proposition": {
        "score_5": (
            "The ad mentions a benefit but it's generic ('improve your SAT "
            "score') with no specifics, no proof, and no differentiation "
            "from competitors."
        ),
        "example_high": (
            "\"Jessica went from 1180 to 1410 in 16 sessions\" — a named "
            "student, specific score jump, specific timeframe. The claim is "
            "credible because it's concrete. Or: '16 sessions → 200 points' "
            "— conditioned claim with a clear input/output."
        ),
        "example_low": (
            "\"We have expert tutors who can help your child do better on "
            "the SAT\" — pure feature claim with no numbers, no proof, no "
            "differentiation. Could be any tutoring company."
        ),
        "common_mistakes": (
            "- Vague score claims with no conditions: 'gain 200 points' is "
            "not credible without specifying starting range and timeline. "
            "Good: '16 sessions → 200 points' or '100pts/month at 2x/week'. "
            "Bad: 'gain 200 points' (impossible above 1400, dubious above 1350)\n"
            "- Unsourced statistics ('2.6x better results') that trigger "
            "skepticism — add the comparison: '2.6x the improvement of "
            "Princeton Review group classes'\n"
            "- Leading with features ('digital SAT interface training') "
            "instead of outcomes ('scored 1390')\n"
            "- Missing the digital SAT reframe angle: 60%+ of math can be "
            "solved with built-in tools, students trained on the interface "
            "gain 100+ points from tool mastery alone\n"
            "- Missing competitor comparison with real numbers: Princeton "
            "Review charges $252/hr for 1:1 vs VT at $349/mth\n"
            "- Missing the scholarship angle: every 100 SAT points = "
            "$10,000-$40,000 in merit aid\n"
            "- Stacking too many value claims in one ad — when an ad tries "
            "to communicate 5 propositions at once, none of them land"
        ),
    },
    "call_to_action": {
        "score_5": (
            "The ad has a CTA button but no embedded action step in the copy "
            "itself. The button says something reasonable but the primary "
            "text never tells the reader what to do next."
        ),
        "example_high": (
            "Primary text ends with 'Start this week.' and the CTA button "
            "is 'Book Now' — specific, urgent, and low-friction. Or: "
            "'Talk to an SAT specialist today. We'll call you in 60 seconds.' "
            "with a 'Book Now' button — micro-commitment, immediate action."
        ),
        "example_low": (
            "A bare 'Learn More' button with no action prompt in the copy. "
            "The reader finishes the ad and has no clear next step."
        ),
        "common_mistakes": (
            "- Using 'Learn More' as the CTA button — it's the weakest "
            "option on Meta and signals lazy copywriting. Prefer 'Book Now', "
            "'Try Free', or 'Get Started'\n"
            "- No urgency element — but urgency must be REAL (test date, "
            "college app deadline, weeks remaining), never fake ('spots "
            "filling fast', 'limited enrollment')\n"
            "- Asking for high-commitment action ('Sign Up') to cold "
            "audiences who haven't been warmed up\n"
            "- CTA that doesn't match the offer in the primary text\n"
            "- Generic CTAs like 'Start your journey' — prefer specific "
            "actions: 'Book Diagnostic', 'See what score is realistic in "
            "8-10 weeks', 'Talk to an SAT specialist today'"
        ),
    },
    "brand_voice": {
        "score_5": (
            "The ad is professional and inoffensive but reads like it could "
            "be from any tutoring company. No distinctly Varsity Tutors "
            "qualities — not empowering, not particularly knowledgeable, "
            "just… competent."
        ),
        "example_high": (
            "\"Your child isn't struggling with the material — they're "
            "struggling with the test.\" — empowering (validates the "
            "student's intelligence), knowledgeable (reframes the real "
            "problem), approachable (speaks directly to the parent in "
            "their language), results-focused (implies a solvable problem)."
        ),
        "example_low": (
            "\"Stop Wasting Time on Khan Academy\" as a headline — "
            "condescending, talks down to parents who chose Khan, violates "
            "'confident but not arrogant' and 'meet people where they are'. "
            "Or generic motivational ad-speak like 'unblock their dreams' "
            "that could be any education brand."
        ),
        "common_mistakes": (
            "- Using 'your student' instead of 'your child' — parents NEVER "
            "call their child 'my student'. This is a dead giveaway of "
            "brand-disconnected copy. Automatic 2-point deduction.\n"
            "- Using 'SAT Prep' instead of 'SAT Tutoring' — VT positions "
            "as tutoring, not generic prep\n"
            "- Corporate/marketing language that parents don't use: 'unlock "
            "potential', 'maximize score potential', 'tailored support', "
            "'custom strategies', 'growth areas', 'concrete score gains', "
            "'dream college within reach'. Replace with plain speech: 'raise "
            "your child's score', 'tutoring'\n"
            "- Aggressive competitor attacks that violate 'confident but "
            "not arrogant'\n"
            "- Generic motivational copy ('achieve greatness', 'empower "
            "their future') that any brand could use\n"
            "- Fear-based messaging that contradicts the empowering tone\n"
            "- Overpromising in a way that sounds arrogant rather than "
            "confident\n"
            "- POSITIVE SIGNALS: speaks in parent language, uses 'your child', "
            "shows specific mechanism rather than telling, names competitors "
            "with real price/result comparisons"
        ),
    },
    "emotional_resonance": {
        "score_5": (
            "The ad is purely rational — it presents facts and features but "
            "doesn't connect with any real emotion. The reader thinks 'okay' "
            "but doesn't feel anything."
        ),
        "example_high": (
            "\"You're not imagining it. The score doesn't match your child.\" "
            "— validates a parent's gut feeling that their child is capable, "
            "tapping into the worry that the test is unfair and the hope "
            "that it's fixable. Or: '3.8 GPA. 1260 SAT. Something's off.' "
            "— instantly resonates with the parent who knows their child "
            "is smarter than the score suggests."
        ),
        "example_low": (
            "\"The SAT is fully digital now. Your child takes it on a "
            "laptop, not paper. That changes how they should prepare.\" — "
            "purely informational, no emotion. A parent reads this and "
            "thinks 'interesting' but doesn't feel urgency or hope."
        ),
        "common_mistakes": (
            "- Fake urgency ('spots filling fast!', 'limited enrollment!', "
            "'don't miss out!') instead of REAL calendar urgency (test date "
            "in 6 weeks, college app deadline, number of sessions possible "
            "before the exam). Fake scarcity is an automatic deduction.\n"
            "- Relying on abstract urgency ('don't wait!') instead of "
            "concrete emotional triggers tied to the persona\n"
            "- Athlete/scholarship angle with no real story — abstract "
            "potential without specifics feels hollow\n"
            "- Fear-mongering without offering hope (emotional resonance "
            "requires both tension AND resolution)\n"
            "- Parent quotes that are clearly brand-written rather than "
            "authentic testimonial voice\n"
            "- Emotional content that is BURIED under formatting noise, "
            "template artifacts, or competing messages never reaches the "
            "reader — score the emotion the reader actually EXPERIENCES in "
            "a real feed scroll, not the emotion theoretically present in "
            "the raw text\n"
            "- POSITIVE SIGNALS: persona-specific emotional triggers "
            "(athlete mom worried about scholarship, suburban parent seeing "
            "GPA-SAT mismatch, burned returner's trust deficit), real "
            "calendar urgency, validation of the parent's instinct"
        ),
    },
}


def get_rubric(dimension_name: str) -> str:
    """Build the full scoring rubric for a single dimension.

    Combines config-level anchors (score_1, score_10) with hardcoded
    score-5 examples, concrete ad examples, and common mistakes.
    """
    config = get_config()
    if dimension_name not in config.dimensions:
        raise ValueError(
            f"Unknown dimension '{dimension_name}'. "
            f"Valid: {list(config.dimensions.keys())}"
        )

    dim = config.dimensions[dimension_name]
    extras = _RUBRIC_EXTRAS[dimension_name]
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


def get_all_rubrics() -> dict[str, str]:
    """Return rubrics for all five dimensions."""
    config = get_config()
    return {name: get_rubric(name) for name in config.dimensions}

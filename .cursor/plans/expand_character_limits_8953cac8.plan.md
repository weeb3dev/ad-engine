---
name: Expand character limits
overview: Widen Pydantic validation limits, align the generator prompt to encourage length diversity, and update console display truncation to show more text.
todos:
  - id: widen-pydantic
    content: "Update max_length in GeneratedAd: primary_text=1000, headline=80, description=200"
    status: completed
  - id: update-gen-prompt
    content: Revise generator_prompt.yaml with wider char limits and LENGTH GUIDANCE section for short/medium/long variety
    status: completed
  - id: widen-display
    content: Change primary_text[:120] to [:200] in generator.py and feedback.py console panels
    status: completed
isProject: false
---

# Expand Character Limits and Add Length Diversity

## Problem

- Pydantic `max_length` constraints are too tight, causing validation errors that waste API calls on retries
- Generator prompt pushes toward a single length range ("aim for 100-300") instead of varying
- Console display truncates at 120 chars, making it look like the evaluator is seeing cut-off text (it isn't, but it's confusing)

## Changes

### 1. Widen Pydantic limits in [generate/models.py](generate/models.py)

These are the "never exceed" safety rails -- make them generous:

```python
primary_text: str = Field(..., max_length=1000)
headline: str = Field(..., max_length=80)
description: str = Field(..., max_length=200)
```

### 2. Update generator prompt in [generate/prompts/generator_prompt.yaml](generate/prompts/generator_prompt.yaml)

Replace the fixed "HARD CHARACTER LIMITS" block with guidance that encourages length variety:

```yaml
HARD CHARACTER LIMITS:
- primary_text: max 800 characters
- headline: max 70 characters (5-10 words)
- description: max 150 characters
- cta_button: exactly one of "Learn More", "Sign Up", "Get Started", "Book Now", "Try Free"

LENGTH GUIDANCE — vary ad length based on the hook style and audience:
- Short (50-150 chars primary): Best for punchy question hooks and mobile-first impressions. The entire message should be visible without "See more."
- Medium (150-350 chars primary): Good for stat hooks and single-benefit stories. First line hooks, supporting proof follows.
- Long (350-800 chars primary): Use for detailed story hooks with testimonials or before/after narratives. Put the strongest hook in the first line since mobile truncates after ~125 chars.
```

### 3. Widen console display truncation in [generate/generator.py](generate/generator.py) and [iterate/feedback.py](iterate/feedback.py)

Both files truncate `primary_text[:120]` in the rich panel. Bump to `[:200]` so the display shows more of the ad without cluttering the terminal.

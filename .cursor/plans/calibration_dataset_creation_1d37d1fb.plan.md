---
name: Calibration Dataset Creation
overview: Create `compete/references/calibration_ads.json` — a JSON array of 8 manually-scored SAT prep ads for Varsity Tutors across 3 quality tiers, sourced from patterns in the real VT ad library and the generated 9/10 and 10/10 reference ads.
todos:
  - id: create-calibration-json
    content: Create `compete/references/calibration_ads.json` with 8 ads (3 high, 3 medium, 2 low) using patterns from the VT ad catalog and generated reference ads
    status: completed
  - id: validate-json
    content: Validate the JSON is parseable and all fields are present on every ad object
    status: completed
isProject: false
---

# Step 1.3: Create Calibration Dataset

Per [adenginebuildguide.md](.cursor/plans/adenginebuildguide.md) lines 191-216, create a file at `compete/references/calibration_ads.json` containing 8 example SAT test prep ads with a mix of quality levels. This file becomes ground truth for calibrating the LLM evaluator in Phase 3.

## File Structure

Each ad object in the JSON array:

```json
{
  "id": "cal_01",
  "primary_text": "...",
  "headline": "...",
  "description": "...",
  "cta_button": "...",
  "expected_quality": "high" | "medium" | "low",
  "expected_score_range": [8, 10],
  "notes": "Why this ad scores at this level, dimension-by-dimension."
}
```

## Quality Tier Sourcing

### 3 High-Quality Ads (expected scores 8-10)

Modeled directly on the patterns that scored highest in the research:

- **Ad cal_01 (target ~9.5)**: Modeled on the generated 10/10 ad from [vt_ad_catalog.md](compete/references/vt_ad_catalog.md) lines 730-770. Short (under 60 words), "You're not imagining it" validation hook, specific score jump (Jessica 1180 to 1410), strong CTA button ("Book a Tutor"), zero unsourced claims. Exercises: Clarity 10, CTA 9, Emotional Resonance 10.
- **Ad cal_02 (target ~9.0)**: Modeled on the generated 9/10 ad from [vt_ad_catalog.md](compete/references/vt_ad_catalog.md) lines 693-727. Story-driven (Jessica narrative), "not struggling with the material — struggling with the test" reframe, strong CTA ("Match With a Top 5% Tutor"). Exercises: Value Proposition 10, Brand Voice 9.
- **Ad cal_03 (target ~8.0)**: Modeled on real Ad #12 (the highest-scoring real ad at 8.0, lines 326-348). Warm validation opener, Sarah case study with price comparison, embedded urgency ("Start this week"), but uses a proper CTA button instead of "Learn more". Exercises: all dimensions 8+.

### 3 Medium-Quality Ads (expected scores 5-7)

Based on mid-tier patterns that are decent but have identifiable weaknesses:

- **Ad cal_04 (target ~6.5)**: Generic digital SAT angle — "the SAT is digital now, paper prep doesn't work." Correct information but no named student, no specific score jump, no emotional hook. CTA "Learn More." Exercises: weak emotional resonance, weak CTA, decent clarity/value prop.
- **Ad cal_05 (target ~6.0)**: Nostalgia angle modeled on real Ads #9/#10 (lines 248-296). "Class of '93" hook that burns scroll-stopping seconds on emotion before delivering value. Long-form, value prop buried. CTA "Learn More." Exercises: strong emotional resonance but weak clarity, buried value prop.
- **Ad cal_06 (target ~5.5)**: Comparison-shopper ad that names competitors aggressively. "Stop Wasting Time on Khan Academy" style, violating "confident but not arrogant" brand guideline. Feature-heavy checklist. CTA "Learn More." Exercises: strong value prop but failed brand voice (score 4-5), weak CTA.

### 2 Low-Quality Ads (expected scores 2-4)

Based on the anti-patterns identified in the worst real ads:

- **Ad cal_07 (target ~3.5)**: Production-error style ad modeled on real Ads #20/#21 (lines 534-583). Headline, description, and primary text are near-identical generic text. No specific numbers, no case studies, no digital SAT angle. CTA "Learn More" with no embedded action. Exercises: all dimensions scoring 2-4.
- **Ad cal_08 (target ~4.5)**: BEFORE/AFTER/BRIDGE framework labels left visible in live copy, modeled on real Ads #13/#18 (lines 352-504). Markdown formatting in ad text, 6 competing messages, off-brand headline. CTA "Learn More." Exercises: brand voice failure (3), clarity failure (5), production error.

## Key Design Decisions

- **CTA variety matters**: High-quality ads use strong CTAs ("Book a Tutor", "Match With a Top 5% Tutor", "Start Your Free Assessment"). Medium and low ads use "Learn More" — matching the systemic weakness found in the real library.
- **Length correlates with quality inversely**: The 10/10 ad is 52 words. The worst ads are 150-200+ words. The calibration set reflects this pattern.
- **Notes are dimension-aware**: Each ad's `notes` field references all 5 dimensions (clarity, value_proposition, call_to_action, brand_voice, emotional_resonance) so the evaluator can be calibrated per-dimension, not just on aggregate.
- **No unsourced claims in high-quality ads**: The "2.6x improvement" stat that appears without citation in the real library is deliberately excluded from high-quality calibration ads.

## Validation Criteria

When the file is created, verify:

- 8 ads total: 3 high, 3 medium, 2 low
- All required fields present on every ad
- Score ranges don't overlap between tiers (high 8-10, medium 5-7, low 2-4)
- High-quality ads use varied hook types (question, stat, story)
- At least one ad per tier exercises each of the 5 dimensions as its strongest or weakest
- Valid JSON (parseable by Python's `json.load`)


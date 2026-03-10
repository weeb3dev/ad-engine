# Known Limitations

## Evaluation

- **Score clustering:** Per-dimension averages across the 53-ad batch range from 6.51 to 8.42. The judge rarely uses the extremes of the 1-10 scale — truly low (1-3) and truly high (9-10) scores are uncommon. This compresses the effective scoring range.
- **100% pass rate is suspicious.** Every ad in the batch passed the 7.0 threshold. This likely means the threshold is too lenient, the judge is too generous, or both. A stricter threshold (e.g., 7.5) or a harsher rubric would produce a more realistic distribution.
- **Self-evaluation bias.** Both generator and evaluator use `gemini-3.1-flash-lite-preview`. Same model family grading its own output creates inherent bias. Calibration against hand-scored reference ads mitigates this, but doesn't eliminate it. A different model family for evaluation (e.g., Claude, GPT-4) would be a stronger check.
- **Weak dimensions stay weak.** `emotional_resonance` (6.51 avg) and `call_to_action` (6.98 avg) consistently score lowest. The improvement loop raises them above threshold but doesn't make them strong. The targeted reprompt strategy may not be sufficient for these dimensions — they might need fundamentally different prompt engineering.
- **LLM judge drift.** Model weights get updated by Google without notice. Scores that calibrate today may drift over weeks. There's no automated recalibration mechanism.
- **Small calibration set.** Calibration is based on 8 reference ads. This is enough to catch gross miscalibration but not enough to validate fine-grained scoring accuracy.

## Generation

- **Unsubstantiated claims.** The model sometimes generates specific but unverifiable claims like "guaranteed 200+ point improvement" or "97% satisfaction rate." These would need legal review before publishing.
- **Hook diversity degrades in long batches.** Over 53 ads, the model gravitates toward its favorite patterns. Question hooks and stat hooks dominate; story hooks are underrepresented.
- **Character limits are soft.** Field limits were relaxed (headline max 80, primary_text max 1000) to reduce validation failures. The evaluator's clarity score handles length organically, but some generated ads are longer than ideal for mobile feeds.

## Cost

- **Evaluation is the biggest cost driver.** Five LLM calls per evaluation (one per dimension), and evaluation runs on every iteration cycle. A 53-ad batch with 2.23 avg iterations = ~590 evaluation calls.
- **No caching.** Re-evaluating the same ad text costs the same every time. Caching evaluation results by content hash would cut costs on retry-heavy runs.
- **Rate limiting.** Gemini API rate limits can slow large batches. The batch runner handles 429s with 60-second backoff, but this extends wall-clock time significantly.
- **Hardcoded pricing.** Cost constants ($1.25/1M input, $10/1M output) are hardcoded in two files. If Gemini pricing changes, these need manual updates.

## Competitive Intelligence

- Meta Ad Library API doesn't support US non-political ads. Competitor analysis is entirely manual.
- Reference ads may become stale as competitors update their campaigns.
- No automated pattern extraction from competitor ads.

## Missing Features

- **No visualization pipeline.** Quality trend charts (Phase 10) are not yet implemented.
- **No A/B test integration.** Generated ads can't be pushed to a Meta Ads account for real-world performance testing.
- **No human-in-the-loop.** The pipeline is fully autonomous — there's no approval step before an ad is marked as "passing."
- **Model escalation is a placeholder.** Tier 3 of the improvement strategy (switch to a more expensive model) is defined but not implemented.

## What I'd Do Differently

- **Use a different model family for evaluation.** The single biggest improvement would be breaking the self-evaluation loop. Even a cheap model from a different provider would add genuine diversity to the scoring.
- **Start with a stricter threshold.** 7.0 is too easy. Starting at 7.5 or 8.0 would force the generator and improvement loop to work harder and produce genuinely better copy.
- **Centralize cost constants.** Having pricing in two files is a maintenance hazard. Should live in `config.yaml`.
- **Add content hash caching for evaluations.** Identical ad text should return cached scores instead of burning 5 API calls.
- **Invest more in the emotional_resonance rubric.** It's the weakest dimension by a wide margin (6.51 avg). The rubric likely needs more specific anchoring examples and clearer scoring criteria.

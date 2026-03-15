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

## Web Application

- **Single-process architecture.** The FastAPI server runs as one `uvicorn` process with no worker pool. Only one pipeline run executes at a time — concurrent requests will queue behind `asyncio.to_thread`.
- **No authentication or rate limiting.** Anyone with the Railway URL can generate ads and burn API credits. There's no auth layer, no API key requirement, and no request throttling.
- **No persistent storage.** The ad library is a JSON file on disk (`data/ad_library.json`). Railway's ephemeral filesystem means data resets on every redeploy unless a volume is configured.
- **No SSE retry/reconnect on the client.** If the connection drops mid-stream, the in-flight result is lost. The client doesn't attempt reconnection or resume from the last event.
- **Legacy Gradio code.** `app.py` (the original Gradio GUI) still exists in the repo alongside `server.py`. It's dead code — the Procfile runs FastAPI.

## Missing Features

- **Visualizations are basic.** `output/visualize.py` produces static matplotlib charts (quality_trends.png, per-ad radar PNGs) and the web UI has interactive Chart.js radar charts, but there's no trend-over-time tracking across batches or historical comparison.
- **No A/B test integration.** Generated ads can't be pushed to a Meta Ads account for real-world performance testing.
- **No human-in-the-loop.** The pipeline is fully autonomous — there's no approval step before an ad is marked as "passing."
- **Model escalation adds cost on tier 3.** Tier 3 of the improvement strategy now switches from `gemini-3.1-flash-lite-preview` to `gemini-2.5-flash` ($0.30/$2.50 per 1M tokens vs $1.25/$10.00). This is a genuine model upgrade but only triggers on attempt 3 — most ads resolve by tier 1-2, so the cost impact across a batch is small.
- **Self-evaluation bias spans two model tiers.** With escalation, the improvement loop can use either flash-lite or 2.5-flash, but both are in the Gemini family. The evaluator (also flash-lite) may still be lenient toward output from a sibling model. Cross-family evaluation (e.g., Claude or GPT-4 as judge) remains the strongest mitigation.

## v2: Multi-Modal

- **Image quality variance.** Nano Banana 2 output is inconsistent across runs. Some images are polished and ad-ready; others have AI artifacts — distorted hands, extra fingers, melted text, or uncanny facial expressions. There's no way to predict which calls will produce artifacts.
- **Text rendering in images.** AI-generated text overlay is unreliable (misspellings, warped letters, illegible fonts), which is why programmatic PIL overlay is the default. But PIL overlays look "pasted on" — they lack the visual integration that a skilled designer would achieve. The `_AI_TEXT_STYLES` (infographic, typography_checklist, comic_panel) accept this unreliability because their visual concepts require integrated text.
- **Visual evaluation is noisier than text.** The same image scored by the same model can vary by ±1 point across runs. The lower visual threshold (7.0 vs 7.25 for text) reflects this, but it means the visual pass/fail signal is weaker. Visual judges disagree with human judgment more often than text judges do, especially on brand_consistency and engagement_potential which are inherently subjective.
- **No real-world A/B testing.** The "best variant" is selected by LLM judgment (visual aggregate score), not by actual click-through rates or conversion data. The winning style for a given campaign goal may not be what performs best on Meta. The style tiebreaker (hero_photo for conversion, ugc_style for awareness) is based on advertising best practices, not validated by data from this system.
- **Image generation is the cost bottleneck.** At ~$0.067/image (1K resolution), 4 variants per ad costs ~$0.268 for image generation alone — about 84% of the per-ad cost. Text gen+eval is ~$0.02 by comparison. The Batch API (50% cost reduction) and draft-then-upscale (generate at 512, upscale winner to 1K) are obvious optimizations not yet implemented.
- **Self-evaluation bias compounds.** The Gemini model family generates images (Nano Banana 2) and evaluates them (2.5 Flash). While using a different model tier (2.5 Flash vs flash-lite) for visual eval helps, it's still Gemini judging Gemini output. A cross-provider visual judge (e.g., Claude's vision, GPT-4o) would provide a genuinely independent evaluation.

## What I'd Do Differently

- **Use a different model family for evaluation.** The single biggest improvement would be breaking the self-evaluation loop. Even a cheap model from a different provider would add genuine diversity to the scoring.
- **Start with a stricter threshold.** 7.0 is too easy. Starting at 7.5 or 8.0 would force the generator and improvement loop to work harder and produce genuinely better copy.
- **Centralize cost constants.** Having pricing in two files is a maintenance hazard. Should live in `config.yaml`.
- **Add content hash caching for evaluations.** Identical ad text should return cached scores instead of burning 5 API calls.
- **Invest more in the emotional_resonance rubric.** It's the weakest dimension by a wide margin (6.51 avg). The rubric likely needs more specific anchoring examples and clearer scoring criteria.
- **Use a persistent database.** Replace `data/ad_library.json` with SQLite or Postgres so the ad library survives redeploys and supports querying.
- **Add authentication.** Even basic API key auth would prevent the public URL from being an open credit-burning endpoint.
- **Use an external image generation model.** Flux via Replicate or fal.ai would break the single-provider dependency and let us compare Gemini image quality against alternatives. This also eliminates the self-evaluation compounding problem if paired with a non-Gemini visual judge.
- **Implement draft-then-upscale.** Generate all variants at 512 resolution ($0.045/image) for evaluation, then only upscale the winning variant to 1K/2K. This would cut image generation cost by ~33% for a 4-variant batch while producing the same final output quality.
- **Add human-in-the-loop for image selection.** Visual quality is too subjective for fully autonomous selection. A lightweight approval step — show the top 2 variants, let a human pick — would catch the cases where the LLM judge picks a technically clean but creatively boring image over a more engaging one with minor imperfections.

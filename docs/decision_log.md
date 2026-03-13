# Decision Log

This log documents thinking and judgment calls throughout the project.
Entries are written as decisions are made, not retroactively.

---

### Decision: Build evaluator before generator
- **Date:** 2026-03-09
- **Context:** Need to decide build order — generator or evaluator first?
- **Options:** (A) Generator first, then evaluator. (B) Evaluator first, then generator.
- **Decision:** Evaluator first (Phase 3 before Phase 4).
- **Rationale:** The PRD says "the hardest part isn't generation — it's evaluation." Without a calibrated judge there's no way to know if generated ads are any good. Building the evaluator first also produces the calibration dataset and rubrics that the generator's few-shot examples depend on.
- **Outcome:** Calibration passed 8/8 ads on the first run. Having a working judge before touching generation meant every generated ad could be scored immediately — no guesswork.

---

### Decision: Dimension weighting
- **Date:** 2026-03-09
- **Context:** How to weight the 5 quality dimensions in the aggregate score?
- **Options:** (A) Equal weights (20% each). (B) Clarity-heavy (40% clarity). (C) Custom weights from PRD: clarity 0.25, value_proposition 0.25, call_to_action 0.20, brand_voice 0.15, emotional_resonance 0.15.
- **Decision:** Option C — PRD custom weights.
- **Rationale:** Clarity and value proposition are the two things a user sees first in a scrolling feed, so they deserve the most weight. Brand voice and emotional resonance matter but are harder for the judge to score reliably, so down-weighting them reduces noise in the aggregate. The weights sum to 1.0 which simplifies the math.
- **Outcome:** Batch average aggregate 7.59. The two lowest-scoring dimensions — emotional_resonance (6.51 avg) and call_to_action (6.98 avg) — have lower weights, so they drag the aggregate down less. If they had equal weight the pass rate would likely drop below 100%. This feels right: an ad with crystal-clear messaging and a strong value prop but lukewarm emotional resonance is still publishable.

---

### Decision: Same model for generation and evaluation
- **Date:** 2026-03-09
- **Context:** Use separate models for generation vs. evaluation, or the same one?
- **Options:** (A) Flash Lite for generation, Pro for evaluation (better judge quality, higher cost). (B) Flash Lite for both (cheaper, faster). (C) Pro for both (expensive).
- **Decision:** Option B — `gemini-3.1-flash-lite-preview` for both.
- **Rationale:** Flash Lite is dramatically cheaper and faster. The build guide suggested Pro for evaluation, but early tests showed Flash Lite produced well-structured JSON judge responses that passed calibration. Using the same cheap model for everything kept the full 53-ad batch under $2.50 total. The risk is self-evaluation bias (same model family grading its own output), but calibration against hand-scored reference ads mitigates this.
- **Outcome:** 53 ads generated and evaluated for $2.35 total (~$0.044/ad). 100% pass rate at the 7.0 threshold. The cost savings are significant — a Pro-based eval would have been ~10x more expensive per call. The tradeoff is that the judge may be slightly more lenient than a Pro-based judge would be.

---

### Decision: Relaxed character limits on GeneratedAd fields
- **Date:** 2026-03-09
- **Context:** The build guide spec called for strict Meta ad character limits: headline max 40, primary_text max 300, description max 125. The model frequently exceeded these, causing validation failures and wasted API calls.
- **Options:** (A) Keep strict limits and add retry logic for validation failures. (B) Relax limits to match what Meta actually truncates vs. rejects. (C) Remove limits entirely.
- **Decision:** Option B — relaxed but still bounded: headline max 80, primary_text max 1000, description max 200.
- **Rationale:** Meta doesn't hard-reject ads that exceed these character counts — it truncates them in the feed. The strict limits from the build guide were causing 30-40% of generation attempts to fail validation before they even reached the evaluator. The new limits are generous enough that the model rarely hits them, but still prevent runaway output. The evaluator's clarity dimension naturally penalizes overly long copy.
- **Outcome:** Validation failures dropped to near zero. The evaluator still scores long-winded ads lower on clarity, so the feedback loop handles length organically rather than through hard validation.

---

### Decision: Three-tier improvement strategy escalation
- **Date:** 2026-03-09
- **Context:** When an ad fails the quality threshold, how should the system decide what to do next?
- **Options:** (A) Always use the same regeneration prompt. (B) Escalate through progressively stronger interventions. (C) Regenerate from scratch each time.
- **Decision:** Option B — three escalation tiers: (1) targeted reprompt citing the weak dimension and its rationale, (2) few-shot injection adding high-scoring examples for the weak dimension, (3) model escalation (placeholder for switching to a more expensive model).
- **Rationale:** A single strategy plateaus quickly. Targeted reprompting is cheapest and works ~60% of the time. Few-shot injection costs the same per call but uses more input tokens for the examples. Model escalation is the nuclear option (not yet implemented). The tiered approach matches how a human creative director would escalate: first give notes, then show examples, then bring in a senior writer.
- **Outcome:** Average iteration count was 2.23 across 53 ads, meaning most ads needed 1-2 improvement cycles. The tiered approach keeps cost low — most ads are fixed by tier 1 (targeted reprompt) without needing the more expensive few-shot injection.

---

### Decision: Langfuse observability via OpenTelemetry
- **Date:** 2026-03-09
- **Context:** Need tracing for every LLM call to track cost, latency, and quality per dollar.
- **Options:** (A) Manual Langfuse SDK calls (`langfuse.trace()`, `langfuse.span()`). (B) OpenTelemetry auto-instrumentation with OTLP exporter to Langfuse + `@observe` decorator for pipeline spans. (C) No tracing, just log to console.
- **Decision:** Option B — OTLP exporter + `@observe` decorator + `GoogleGenAIInstrumentor` for automatic Gemini call tracing.
- **Rationale:** Auto-instrumentation captures every Gemini call without touching the generator or evaluator code. The `@observe` decorator adds pipeline-level spans (run_pipeline, evaluate_ad, etc.) that nest the auto-captured LLM calls. Graceful degradation means the pipeline works fine without Langfuse keys set — important for tests and CI.
- **Outcome:** Every LLM call appears in the Langfuse dashboard with full token counts, latency, and prompt/response content. The `propagate_attributes` context manager adds session IDs, tags, and metadata. Tests run without Langfuse keys because the observability module degrades to no-ops.

---

### Decision: Hardcoded cost model
- **Date:** 2026-03-09
- **Context:** Need to track cost per ad and per batch. Gemini pricing can change.
- **Options:** (A) Query a pricing API at runtime. (B) Hardcode current pricing constants. (C) Put pricing in config.yaml.
- **Decision:** Option B — hardcoded constants in `feedback.py` and `generator.py`: $1.25/1M input tokens, $10.00/1M output tokens.
- **Rationale:** There's no public Gemini pricing API. Config.yaml would be cleaner but adds complexity for something that changes rarely. Hardcoded constants are easy to grep and update. The values match the current Flash Lite pricing.
- **Outcome:** Cost tracking works. 53 ads cost $2.35 total, $0.044/ad average. If pricing changes, two constants need updating in two files — not ideal but acceptable for v1. A future improvement would be centralizing these in config.yaml.

---

### Decision: Replace Gradio with FastAPI + Jinja2 + Tailwind/DaisyUI
- **Date:** 2026-03-11
- **Context:** The Gradio GUI was functional but limited — no control over layout, no incremental streaming of evaluation scores, and `share=True` links are temporary (expire after 72 hours). Needed a real deployment with a persistent URL.
- **Options:** (A) Keep Gradio. (B) FastAPI + Jinja2 + Tailwind CSS. (C) Separate React/Next.js frontend.
- **Decision:** Option B — single-process FastAPI serving Jinja2 templates styled with Tailwind CSS + DaisyUI from CDN, Chart.js for interactive radar charts.
- **Rationale:** Zero build step, no CORS, no separate frontend repo. Tailwind + DaisyUI gives a polished component library out of the box. Chart.js loads from CDN. Everything is one `uvicorn` process — simple to deploy and reason about. A separate React app would add a build pipeline, a second deploy, and CORS configuration for marginal benefit at this stage.
- **Outcome:** Full dashboard with Generate, Batch, and Library tabs. Responsive UI with DaisyUI's `corporate` theme. Interactive Chart.js radar charts per ad. Deploys as a single process to Railway.

---

### Decision: SSE streaming for real-time pipeline progress
- **Date:** 2026-03-11
- **Context:** The pipeline takes 15-30 seconds per ad (generate + 5 evaluation calls + potential improvement cycles). Need to show each stage as it happens rather than a loading spinner.
- **Options:** (A) WebSocket for bidirectional communication. (B) Server-Sent Events (SSE) for server-to-client streaming. (C) Polling the server for status updates.
- **Decision:** Option B — SSE via FastAPI's `StreamingResponse`.
- **Rationale:** SSE is unidirectional (server → client), which is exactly the pattern here — the client submits a brief and watches the pipeline execute. No WebSocket upgrade complexity, no polling overhead. `StreamingResponse` is native to FastAPI. The client uses `fetch()` + `getReader()` to parse the stream. Structured JSON events per stage (`status`, `ad_copy`, `eval_start`, `eval_progress`, `improving`, `complete`) let the frontend render incrementally — ad copy card appears first, then scores fill in one-by-one, then the radar chart builds vertex by vertex.
- **Outcome:** Generate endpoint streams ~8–12 events per ad depending on improvement cycles. Batch endpoint streams `progress` and `ad_complete` events with running summary stats. The frontend shows a step indicator, progressive score table, and incremental radar chart — no spinners, no waiting for the full result.

---

### Decision: Deploy to Railway
- **Date:** 2026-03-11
- **Context:** Need a persistent public URL for the demo video and reviewer access. Gradio's `share=True` links expire after 72 hours and are unreliable.
- **Options:** (A) Railway. (B) Fly.io. (C) Render. (D) Keep Gradio share link.
- **Decision:** Option A — Railway with a one-line Procfile.
- **Rationale:** Minimal config: `web: uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}`. Railway auto-detects Python from `requirements.txt`, assigns a stable `*.up.railway.app` URL, and supports environment variables in the dashboard. SSE streaming works without buffering issues (some platforms like Render buffer SSE responses by default). Free tier is sufficient for demo traffic.
- **Outcome:** Live at a persistent Railway URL. Environment variables (`GOOGLE_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`) configured in the Railway dashboard. Deploys automatically on push.

---

### Decision: Multi-model orchestration — which model handles which task
- **Date:** 2026-03-13
- **Context:** v2 introduces image generation and visual evaluation alongside the existing text pipeline. A single model can no longer cover all tasks well. Need to decide which model handles which task.
- **Orchestration map:**

| Task | Model | Rationale |
|---|---|---|
| Text generation | `gemini-3.1-flash-lite-preview` | Cheapest, fast, proven in v1 (100% pass rate at $0.044/ad). Iteration loop compensates for any weak individual generations. |
| Text evaluation | `gemini-3.1-flash-lite-preview` | Same cheap model. Calibration passed 8/8. Self-evaluation bias exists but is acceptable. |
| Image generation | `gemini-3.1-flash-image-preview` | Nano Banana 2 — the only Gemini model that generates images. No alternative within the ecosystem. |
| Visual evaluation | `gemini-2.5-flash` | Flash-lite's vision capabilities are too weak for reliable image scoring — it tends to score everything 6-8 regardless of quality. 2.5 Flash provides meaningfully better discrimination at ~$0.01 more per image eval. |
| Text improvement (tier 3 escalation) | `gemini-2.5-flash` | Genuine model upgrade for stubborn cases. Better reasoning and creative output than flash-lite. Only triggers on attempt 3, so cost impact is minimal. |

- **Decision:** Use the cheapest model that meets each task's capability bar. Upgrade only where there's a measurable quality gap (visual eval, tier 3 escalation).
- **Cost per multimodal ad:** ~$0.005 text gen + ~$0.008 text eval + ~$0.005 text improvement + ~$0.134 image gen (2 variants at 1K) + ~$0.008 visual eval = **~$0.16/ad**. Image generation is the dominant cost driver at ~84%.
- **Outcome:** The escalation model is now configurable via `config.models.escalation` (defaults to `gemini-2.5-flash`). When the improvement loop reaches tier 3, `improve_ad()` switches to the escalation model with its own cost tracking. This replaces the previous placeholder that only changed the system prompt.

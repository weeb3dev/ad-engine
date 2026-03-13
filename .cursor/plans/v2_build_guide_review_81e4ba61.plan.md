---
name: v2 Build Guide Review
overview: Comprehensive review of the v2 multimodal build guide covering model name accuracy, API usage errors, architectural gaps, and design tradeoffs.
todos:
  - id: fix-response-modalities
    content: Add response_modalities and image_config to all image generation code examples and Cursor prompts
    status: completed
  - id: fix-api-claims
    content: Remove false claim about no aspect_ratio/resolution params; update to use ImageConfig API
    status: completed
  - id: fix-pricing
    content: "Fix all pricing: flash-lite is $0.25/$1.50 (not $1.25/$10.00), 2.5-flash is $0.30/$2.50 (not $0.15/$0.60). Fix v1 README too."
    status: completed
  - id: add-nano-banana-pro
    content: Add discussion of gemini-3-pro-image-preview as alternative for text-heavy creatives
    status: completed
  - id: add-thinking-mode
    content: Document thinking mode config (minimal vs high) and expose in config.yaml
    status: completed
  - id: add-text-overlay-fallback
    content: Add PIL-based programmatic text overlay as default approach
    status: completed
  - id: fix-init-py
    content: Add missing generate/image_prompts/__init__.py
    status: completed
  - id: consolidate-image-dirs
    content: Consolidate output/images/ and data/images/ to single directory
    status: completed
isProject: false
---

# v2 Build Guide Review: Gaps, Errors, and Tradeoffs

## 1. Model Names -- Corrections Needed

### Correct

- `gemini-3.1-flash-image-preview` (Nano Banana 2) -- used throughout for image generation. Matches [the Gemini docs](https://ai.google.dev/gemini-api/docs/image-generation) exactly.
- `gemini-2.5-flash` -- used for visual evaluation. Valid model with strong multimodal understanding.
- `gemini-3.1-flash-lite-preview` -- inherited from v1 for text gen/eval. In production, works fine.

### Missing from Discussion

- `**gemini-3-pro-image-preview` (Nano Banana Pro)** -- The docs describe this as "designed for professional asset production, utilizing advanced reasoning ('Thinking') to follow complex instructions and render high-fidelity text." For ad creatives that need legible text overlays (headlines on images), this could be significantly better than Nano Banana 2. The guide should at least discuss it as an option, especially since text rendering in images is called out as a known limitation.
- `**gemini-2.5-flash-image`** (original Nano Banana) -- Cheaper/faster option for lower-fidelity use cases. Worth mentioning as a cost-saving fallback for draft variants.

---

## 2. API Usage -- Critical Errors

### Error 1: Missing `response_modalities` (HIGH PRIORITY)

The guide never sets `response_modalities` in the `GenerateContentConfig`. The Gemini docs show this is needed to get image output:

```python
config=types.GenerateContentConfig(
    response_modalities=['TEXT', 'IMAGE'],  # REQUIRED for image output
)
```

Without this, the model may return text-only responses. The guide's Phase V2-2 code example (lines 306-323) just calls `generate_content()` with a text prompt and hopes for an image. This works sometimes but is unreliable.

**Fix:** Every image generation call needs `response_modalities=['TEXT', 'IMAGE']` (or `['IMAGE']` for image-only). Add this to the `GenerateContentConfig`.

### Error 2: Wrong Claim About Aspect Ratio / Resolution API (HIGH PRIORITY)

Line 327-328 states:

> "No separate aspect_ratio or resolution parameters -- control output through prompt text"

This is **false**. The Gemini API has explicit `image_config` parameters:

```python
config=types.GenerateContentConfig(
    response_modalities=['TEXT', 'IMAGE'],
    image_config=types.ImageConfig(
        aspect_ratio="1:1",    # API parameter, not prompt text
        image_size="1K",       # 512, 1K, 2K, 4K
    ),
)
```

The guide's approach of putting "Create a square 1:1 aspect ratio image" in the prompt text is less reliable than using the API parameter. The `image_config.aspect_ratio` supports: `1:1`, `1:4`, `1:8`, `2:3`, `3:2`, `3:4`, `4:1`, `4:3`, `4:5`, `5:4`, `8:1`, `9:16`, `16:9`, `21:9`. The `image_config.image_size` supports: `512`, `1K`, `2K`, `4K`.

**Fix:** Update the image generator to use `types.ImageConfig(aspect_ratio=..., image_size=...)` instead of prompt-based control. Update the YAML config to include `default_resolution: "1K"`. Update the Cursor prompts accordingly.

### Error 3: ALL Cost Numbers Are Wrong (HIGH PRIORITY)

Cross-referencing with the [actual Gemini API pricing page](https://ai.google.dev/gemini-api/docs/pricing):

**Actual pricing (standard tier):**

- `gemini-3.1-flash-lite-preview`: **$0.25/1M input, $1.50/1M output**
- `gemini-2.5-flash`: **$0.30/1M input, $2.50/1M output**
- `gemini-3.1-flash-image-preview`: $0.50/1M input, $3.00/1M output (text/thinking), **$60.00/1M output (images)**
- `gemini-3-pro-image-preview`: $2.00/1M input, $12.00/1M output (text/thinking), **$120.00/1M output (images)**

**What the v2 guide says (line 854):**

> "$0.15/1M input, $0.60/1M output for 2.5-flash vs $1.25/1M input, $10.00/1M output for flash-lite"

Both numbers are wrong:

- The 2.5-flash numbers ($0.15/$0.60) are **batch tier** pricing, not standard. Standard is $0.30/$2.50.
- The flash-lite numbers ($1.25/$10.00) are actually **gemini-2.5-pro** pricing. Flash-lite is $0.25/$1.50.

**What the v1 README says (line 141):**

> "Using `gemini-3.1-flash-lite-preview` at $1.25/1M input tokens and $10.00/1M output tokens"

This is also wrong -- same gemini-2.5-pro confusion. The actual flash-lite rate is 5x cheaper on input and 6.7x cheaper on output.

**Impact on the guide's model orchestration rationale:**

The escalation direction is actually correct -- flash-lite ($0.25/$1.50) IS cheaper than 2.5-flash ($0.30/$2.50) -- but the magnitude is much smaller than the guide implies. Flash-lite is only ~20% cheaper on input and ~40% cheaper on output, not the 8x difference the wrong numbers suggest. This actually strengthens the case for using flash-lite for high-volume text tasks.

**Corrected cost table for the guide:**

- `gemini-3.1-flash-lite-preview`: $0.25 input / $1.50 output per 1M tokens
- `gemini-2.5-flash`: $0.30 input / $2.50 output per 1M tokens
- `gemini-3.1-flash-image-preview` (text): $0.50 input / $3.00 output per 1M tokens
- `gemini-3.1-flash-image-preview` (images): $0.045/image at 512, $0.067/image at 1K, $0.101/image at 2K, $0.151/image at 4K
- `gemini-3-pro-image-preview` (images): $0.134/image at 1K-2K, $0.24/image at 4K

The guide's per-image costs (line 13: "$0.045/image at 512px, $0.067 at 1K, $0.101 at 2K") are correct for Nano Banana 2.

**Fix:** Correct all per-token pricing throughout the guide and the v1 README. Recalculate the cost summary table in Phase V2-7.

---

## 3. Architectural Gaps

### Gap 1: No Thinking Mode Configuration

The Gemini docs state that Gemini 3 image models use "Thinking" by default and it **cannot be disabled**. For `gemini-3.1-flash-image-preview`, you can control the level:

- `minimal` (default) -- faster, cheaper
- `high` -- better quality, slower, more expensive

The guide never mentions this. For ad creatives where quality matters, `high` thinking might be worth the latency/cost tradeoff. At minimum, the config should expose `thinking_level` as a parameter.

### Gap 2: No Content Safety / Policy Rejection Handling

Image generation can be rejected by Google's content safety filters (e.g., if the prompt is interpreted as generating misleading advertising, or if it involves certain sensitive topics). The guide handles "no image in response" with a retry, but doesn't distinguish between:

- Rate limit (429) -- retry with backoff
- Content policy rejection -- retry won't help, need to modify prompt
- Transient failure -- retry might help

### Gap 3: No Programmatic Text Overlay Fallback

The guide instructs image prompts to include headline text as overlay (line 374-375). AI-generated text in images is notoriously unreliable -- misspellings, warped letters, illegible fonts. The guide even acknowledges this in limitations (line 1042). But there's no fallback:

A better approach: Generate the image WITHOUT text overlay, then use PIL `ImageDraw` to composite the headline programmatically. This gives pixel-perfect text every time. The guide should offer this as the default, with AI text overlay as an experimental option.

### Gap 4: No Reference Image Usage for Brand Consistency

The Gemini docs show you can pass up to 14 reference images. The guide could leverage this by passing:

- 2-3 reference brand images (existing VT ad creatives, brand colors)
- Logo as a reference image for consistent branding

This would dramatically improve brand_consistency scores without relying solely on text prompts.

### Gap 5: No Image Format Optimization

All images saved as PNG. For web dashboard serving, WebP or JPEG would be 3-5x smaller. The `save_ad_image()` function should support format selection.

### Gap 6: No Parallel Variant Generation

The A/B variant engine (Phase V2-5) generates variants sequentially. With 2-4 variants per ad and ~5-10s per image, this adds 10-40s per ad. At batch scale (50 ads), that's 8-33 extra minutes. The guide should at least discuss `asyncio` or `concurrent.futures` for parallel generation, with rate limit awareness.

### Gap 7: Missing `__init__.py` for `generate/image_prompts/`

The guide creates `evaluate/visual/__init__.py` but not `generate/image_prompts/__init__.py`. If `prompt_builder.py` is imported as a module, this will fail.

### Gap 8: No Image Deduplication / Caching

If you re-run the pipeline with the same brief, you'll regenerate identical images and pay again. A simple hash-based cache (hash the prompt, check if image exists) would save significant cost during development and iteration.

---

## 4. Design Tradeoffs Worth Questioning

### Tradeoff 1: 60/40 Text/Visual Weighting

Line 775: `combined_score = 0.6 * text_aggregate + 0.4 * visual_aggregate`

For Meta feed ads, the image is typically the primary scroll-stopper. Facebook's own research shows images drive 75-90% of ad engagement. A 50/50 or even 40/60 (image-heavy) weighting might better reflect real-world performance. The 60/40 text-heavy bias is a safe default but potentially undervalues the visual component.

**Recommendation:** Make the weighting configurable in `config.yaml` and document the rationale.

### Tradeoff 2: Self-Evaluation Bias Compounding

v1 already has same-family-evaluates-same-family bias (flash-lite judges flash-lite). v2 adds another layer: Gemini evaluates Gemini-generated images. The guide acknowledges this (line 1046) but doesn't propose mitigation.

**Speculative mitigation:** Use the visual evaluation as a "soft gate" rather than a hard threshold. Flag images below threshold for manual review rather than auto-rejecting. Or add a simple heuristic check (resolution, color histogram diversity, SSIM against a blank image) as a non-LLM sanity check.

### Tradeoff 3: Visual Threshold at 6.5 vs Text at 7.0

The guide justifies the lower visual threshold (line 161) as "image eval is noisier." This is reasonable, but it means the system will accept visually mediocre images more readily. An alternative: keep the threshold at 7.0 but allow 1 more retry cycle for images (since generation is cheaper than evaluation at the per-unit level).

### Tradeoff 4: Nano Banana 2 vs Nano Banana Pro for Ad Creatives

The guide locks in `gemini-3.1-flash-image-preview` without discussing the Pro alternative. With actual pricing from [the pricing page](https://ai.google.dev/gemini-api/docs/pricing):

- **Nano Banana 2** (`gemini-3.1-flash-image-preview`): $0.067/image at 1K, $0.101 at 2K
- **Nano Banana Pro** (`gemini-3-pro-image-preview`): $0.134/image at 1K-2K, $0.24 at 4K

Nano Banana Pro is exactly **2x the cost** at 1K/2K resolution. For ad creatives specifically:

- **Text rendering**: Pro has "high-fidelity text" -- critical for headline overlays in ads
- **Complex instructions**: Pro uses "advanced reasoning (Thinking)" -- better for multi-element compositions
- **Reference images**: Flash supports 10 objects + 4 characters; Pro supports 6 objects + 5 characters
- **Resolution**: Both support up to 4K. Flash also supports 512 (0.5K) for drafts.

At 2 variants per ad, Nano Banana Pro adds ~$0.134 more per ad ($0.268 vs $0.134). Over a 50-ad batch, that's ~$6.70 extra. For production ad creatives where text rendering matters, this could be worth it. The guide should discuss this tradeoff and make the image model configurable in `config.yaml`.

### Tradeoff 5: UGC Style Tiebreaker for Awareness

Line 697-698: ugc_style wins tiebreakers for awareness campaigns. This is a reasonable heuristic, but it's an assumption without data. In practice, illustration or minimal_graphic styles might perform better for awareness (they're more distinctive in a feed). The guide should flag this as an assumption to validate.

### Tradeoff 6: Cost Increase at Scale

With corrected pricing, the per-ad cost breakdown:

- Text pipeline (flash-lite at $0.25/$1.50): ~$0.01-0.02/ad (much cheaper than guide's $0.04 estimate based on wrong rates)
- Image generation (Nano Banana 2 at $0.067/1K image x 2 variants): ~$0.134/ad
- Visual evaluation (2.5-flash at $0.30/$2.50, 4 dims x 2 variants): ~$0.008/ad
- **Total: ~$0.16/multimodal ad** (image gen dominates at ~84% of cost)

The guide's estimate of ~$0.19 is in the right ballpark but derived from wrong per-token rates. At 50 ads: ~$8.00 total. The v1 text-only batch would actually be closer to ~$0.75-1.00 with correct flash-lite pricing (not $2.35 -- that figure was calculated with 5x inflated rates).

**Key insight:** Image generation is the overwhelming cost driver. Optimizations should focus there: use 512 resolution for draft/evaluation, only upscale the winning variant to 1K/2K. Consider Batch API for image gen (50% cost reduction: $0.034/image at 1K). The guide mentions neither of these.

---

## 5. Minor Issues

- **Line 13 cost note** mentions "512px" but should say "512 resolution" (it's not pixels, it's a tier)
- **Line 327** says `part.as_image()` returns a PIL Image -- this is correct but worth noting it requires Pillow installed
- **Line 854** model escalation comment says "better reasoning, better creative output" for 2.5-flash but the escalation is for text improvement, not image generation -- the model choice here is fine but the rationale should be clearer
- `**output/images/` vs `data/images/`** -- the guide uses both directories inconsistently. `save_ad_image` defaults to `data/images/` but comparison images go to `output/images/`. Should be consolidated.
- **v1 guide inconsistency** -- the v1 guide config section (line 232) uses `gemini-3.1-pro-preview` but the actual running config uses `gemini-3.1-flash-lite-preview`. The v2 guide correctly references the actual running model, but this v1 discrepancy could confuse someone reading both guides.

---

## 6. Summary of Required Changes

**Must fix (will cause failures or incorrect behavior):**

1. Add `response_modalities=['TEXT', 'IMAGE']` to all image generation calls
2. Use `image_config=types.ImageConfig(aspect_ratio=..., image_size=...)` instead of prompt-based control
3. Remove the false claim about "no separate aspect_ratio or resolution parameters"
4. Add `generate/image_prompts/__init__.py`
5. Fix ALL pricing numbers -- flash-lite is $0.25/$1.50, not $1.25/$10.00; 2.5-flash is $0.30/$2.50, not $0.15/$0.60. Also fix the v1 README which has the same error.

**Should fix (will cause confusion or suboptimal results):**

1. Discuss Nano Banana Pro (`gemini-3-pro-image-preview`) as alternative -- 2x cost but "high-fidelity text" rendering for headlines
2. Add thinking mode configuration (`minimal` vs `high` for image gen)
3. Add programmatic text overlay via PIL as default, AI text overlay as option
4. Consolidate `output/images/` vs `data/images/`
5. Recalculate the cost summary table in Phase V2-7 with correct pricing

**Nice to have (quality/cost improvements):**

1. Reference image passing for brand consistency (up to 14 images supported)
2. Image caching (hash-based) for development iteration
3. Parallel variant generation via `concurrent.futures`
4. Configurable text/visual weighting in `config.yaml`
5. Content policy rejection handling (distinct from rate limits)
6. Use 512 resolution for draft variants, only upscale winner to 1K/2K
7. Mention Batch API for image gen (50% cost reduction: $0.034/image at 1K vs $0.067 standard)


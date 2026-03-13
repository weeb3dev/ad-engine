# v2 Build Guide: Multi-Modal Ads

**Extending the Ad Engine with AI-generated creative, visual evaluation, A/B variant testing, and multi-model orchestration.**

This guide picks up where the v1 Build Guide left off. You should have a working text-only ad copy pipeline (generate → evaluate → iterate) before starting v2. If you don't, complete the v1 guide first.

> **What v2 adds:** Image generation for ad creatives, visual evaluation (brand consistency, engagement potential), A/B variant generation from the same brief with different creative approaches, and multi-model orchestration with clear rationale for which model does what.

> **Time estimate:** 3–5 days on top of a working v1.

> **Prerequisites:** Working v1 pipeline (all phases 0–10 complete), a **paid** Gemini API key (image generation has no free tier), Pillow installed, and Cursor IDE.

> **Cost note:** Image generation via Nano Banana 2 costs approximately $0.045/image at 512 resolution, $0.067 at 1K, $0.101 at 2K. A full batch of 20 multimodal ads with 2 image variants each at 1K would cost roughly $2.70 in image generation alone, on top of ~$0.50–0.75 for text generation/evaluation (flash-lite at $0.25/$1.50 per 1M tokens). Nano Banana Pro (`gemini-3-pro-image-preview`) is 2x the cost but has better text rendering — see Phase V2-2 for the tradeoff.

---

## Table of Contents

1. [v1 Codebase Inventory — What We're Building On](#v1-codebase-inventory--what-were-building-on)
2. [Phase V2-0: Environment & Config Update](#phase-v2-0-environment--config-update)
3. [Phase V2-1: Data Models for Multi-Modal](#phase-v2-1-data-models-for-multi-modal)
4. [Phase V2-2: Image Generation Module](#phase-v2-2-image-generation-module)
5. [Phase V2-3: Image Prompt Engineering](#phase-v2-3-image-prompt-engineering)
6. [Phase V2-4: Visual Evaluation (Image Judge)](#phase-v2-4-visual-evaluation-image-judge)
7. [Phase V2-5: A/B Variant Generation](#phase-v2-5-ab-variant-generation)
8. [Phase V2-6: Multi-Modal Pipeline Integration](#phase-v2-6-multi-modal-pipeline-integration)
9. [Phase V2-7: Multi-Model Orchestration](#phase-v2-7-multi-model-orchestration)
10. [Phase V2-8: Batch Runner & Reporting](#phase-v2-8-batch-runner--reporting)
11. [Phase V2-9: Web Dashboard Update](#phase-v2-9-web-dashboard-update)
12. [Phase V2-10: Tests for v2](#phase-v2-10-tests-for-v2)
13. [Phase V2-11: Documentation & Decision Log](#phase-v2-11-documentation--decision-log)
14. [Multi-Model Orchestration Rationale](#multi-model-orchestration-rationale)
15. [Cursor Troubleshooting: Image Generation](#cursor-troubleshooting-image-generation)

---

## v1 Codebase Inventory — What We're Building On

Before writing any v2 code, know exactly what already exists. Every v2 module imports from these.

### Files You'll Import From (DO NOT REWRITE)

| File | What it provides | v2 usage |
|---|---|---|
| `generate/models.py` | `AdBrief`, `GeneratedAd`, `DimensionScore`, `AdEvaluation`, `AdRecord`, `Config`, `DEFAULT_WEIGHTS` | Import all. Add new models (`VisualEvaluation`, `MultiModalAdRecord`) here. |
| `config/loader.py` | `get_config()`, `get_gemini_client()` | Reuse for all API calls. |
| `config/observability.py` | `@observe`, `propagate_attributes`, `get_langfuse()` | Decorate all new pipeline functions. |
| `generate/generator.py` | `generate_ad()`, `generate_ad_variants()`, `load_few_shot_examples()` | Reuse for text generation stage. |
| `evaluate/judge.py` | `evaluate_ad()`, `evaluate_dimension()`, `get_evaluation_context()` | Reuse for text evaluation stage. |
| `evaluate/dimensions.py` | `get_rubric()`, `get_all_rubrics()` | Pattern to follow for visual rubrics. |
| `iterate/feedback.py` | `run_pipeline()`, `improve_ad()`, `run_batch()` | Reuse `run_pipeline()` as Stage 1 of the multimodal pipeline. |
| `iterate/strategies.py` | `get_strategy_name()`, `build_targeted_prompt()` | Reuse for text improvement. |
| `output/batch_runner.py` | `run_full_batch()`, `load_ad_library()`, `_build_summary()` | Pattern to follow for multimodal batch runner. |
| `output/visualize.py` | `plot_quality_trends()`, `plot_dimension_radar()`, `generate_evaluation_report()` | Extend with visual metrics. |

### Current Config (`config/config.yaml`)

The v1 config uses `gemini-3.1-flash-lite-preview` for both generator and evaluator. v2 will add new model entries for image generation and visual evaluation — the existing text models stay unchanged.

### Current Pipeline Flow (v1)

```
AdBrief → generate_ad() → GeneratedAd → evaluate_ad() → AdEvaluation
    ↓ (if fails threshold)
    improve_ad() → re-evaluate → ... (up to 3 cycles)
    ↓ (passes or max attempts)
    AdRecord → data/ad_library.json
```

### v2 Pipeline Flow (what we're building)

```
AdBrief → [STAGE 1: TEXT — reuse v1 run_pipeline()] → AdRecord
    ↓ (text passes threshold)
    [STAGE 2: IMAGES]
    → generate_ad_image() × N styles → PIL Images
    → evaluate_ad_image() per image → VisualEvaluation
    → select_best_variant()
    ↓
    [STAGE 3: COMBINE]
    → MultiModalAdRecord → data/multimodal_ad_library.json
```

---

## Phase V2-0: Environment & Config Update

**Goal:** Add image-related dependencies, extend project structure, and verify image generation API access.

### Terminal Commands

```bash
# Make sure you're in the ad-engine directory with venv active
cd ad-engine
source .venv/bin/activate

# Add v2 dependency (only Pillow — google-genai already installed)
echo "Pillow>=10.0" >> requirements.txt
pip install -r requirements.txt

# Create v2 directory structure
mkdir -p generate/image_prompts
mkdir -p evaluate/visual
mkdir -p data/images

# Create __init__.py for new packages
touch generate/image_prompts/__init__.py
touch evaluate/visual/__init__.py
```

### Verify Nano Banana 2 Access

This is the most important check — if this fails, you cannot proceed with v2.

```bash
python3 -c "
from google import genai
from google.genai import types
import os
from dotenv import load_dotenv
load_dotenv()

client = genai.Client(api_key=os.getenv('GOOGLE_API_KEY'))
response = client.models.generate_content(
    model='gemini-3.1-flash-image-preview',
    contents=['Generate a simple blue square with the text HELLO on it.'],
    config=types.GenerateContentConfig(
        response_modalities=['TEXT', 'IMAGE'],
        image_config=types.ImageConfig(
            aspect_ratio='1:1',
            image_size='1K',
        ),
    ),
)

for part in response.parts:
    if part.inline_data is not None:
        image = part.as_image()
        image.save('data/images/test_image.png')
        print('Image saved to data/images/test_image.png')
        print('Nano Banana 2 access verified!')
    elif part.text is not None:
        print(f'Text response: {part.text}')
"
```

> **If you get an error:** Nano Banana 2 requires a **paid** Gemini API key. Free-tier keys cannot generate images. Go to [ai.google.dev](https://ai.google.dev), enable billing on your project, and generate a new key. Update your `.env` file.

### Update `config/config.yaml`

Add these sections **below** the existing `seed: 42` line. Do NOT modify any existing config — v1 modules depend on it.

```yaml
# ── v2: Image Generation ──────────────────────────────────────────────

image_generation:
  model: "gemini-3.1-flash-image-preview"     # Nano Banana 2 (default)
  # Alt: "gemini-3-pro-image-preview"         # Nano Banana Pro — 2x cost, better text rendering
  default_aspect_ratio: "1:1"                  # feed ads; "9:16" for Stories
  default_resolution: "1K"                     # 512 for drafts, 1K for production, 2K/4K for high-res
  thinking_level: "minimal"                    # "minimal" (faster/cheaper) or "high" (better quality)
  variants_per_ad: 2                           # image variants per text ad
  text_overlay_mode: "programmatic"            # "programmatic" (PIL, pixel-perfect) or "ai" (in-image, experimental)
  style_approaches:
    - "photorealistic"
    - "ugc_style"
    - "illustration"
    - "minimal_graphic"

visual_evaluation:
  model: "gemini-2.5-flash"                    # multimodal judge (see orchestration rationale)
  threshold: 6.5                               # lower than text — image eval is noisier
  dimensions:
    brand_consistency:
      weight: 0.30
      description: "Does the image match Varsity Tutors' visual identity?"
      score_1: "Generic stock photo, could be any brand"
      score_10: "Distinctly VT: warm, approachable, education-focused, trustworthy"
    engagement_potential:
      weight: 0.30
      description: "Would this stop a thumb-scroll in a Facebook/Instagram feed?"
      score_1: "Boring, forgettable, blends into the feed"
      score_10: "Arresting visual that demands attention without being clickbait"
    text_image_coherence:
      weight: 0.25
      description: "Does the image reinforce and complement the ad copy?"
      score_1: "Disconnected — image has nothing to do with the copy"
      score_10: "Image and copy tell one unified story"
    technical_quality:
      weight: 0.15
      description: "Resolution, composition, no AI artifacts?"
      score_1: "Distorted faces, melted text, blurry, bad composition"
      score_10: "Clean, high-resolution, professional composition"
```

### Update Config Model

The existing `Config` model in `generate/models.py` doesn't know about these new sections. We'll add them in Phase V2-1.

---

## Phase V2-1: Data Models for Multi-Modal

**Goal:** Extend `generate/models.py` with new Pydantic models for visual evaluation and multimodal records. The existing models stay unchanged — we only add.

### Cursor Prompt

> **Paste this into Cursor chat:**
>
> ```
> Read the existing generate/models.py. Do NOT modify any existing models (AdBrief,
> GeneratedAd, DimensionScore, AdEvaluation, AdRecord, Config, etc.).
>
> ADD the following new models at the bottom of the file:
>
> 1. `VisualDimensionConfig(BaseModel)`:
>    - weight: float
>    - description: str
>    - score_1: str
>    - score_10: str
>
> 2. `ImageGenerationConfig(BaseModel)`:
>    - model: str
>    - default_aspect_ratio: str = "1:1"
>    - default_resolution: str = "1K"
>    - thinking_level: str = "minimal"  # "minimal" or "high"
>    - variants_per_ad: int = 2
>    - text_overlay_mode: str = "programmatic"  # "programmatic" or "ai"
>    - style_approaches: list[str]
>
> 3. `VisualEvaluationConfig(BaseModel)`:
>    - model: str
>    - threshold: float = 6.5
>    - dimensions: dict[str, VisualDimensionConfig]
>
> 4. `VisualEvaluation(BaseModel)`:
>    - brand_consistency: DimensionScore
>    - engagement_potential: DimensionScore
>    - text_image_coherence: DimensionScore
>    - technical_quality: DimensionScore
>    - Computed fields (same pattern as AdEvaluation):
>      - visual_aggregate_score: float (weighted average using VISUAL_DEFAULT_WEIGHTS)
>      - passes_visual_threshold: bool (aggregate >= 6.5)
>      - weakest_visual_dimension: str
>
>    Add VISUAL_DEFAULT_WEIGHTS at module level:
>    {"brand_consistency": 0.30, "engagement_potential": 0.30,
>     "text_image_coherence": 0.25, "technical_quality": 0.15}
>
> 5. `ImageVariant(BaseModel)`:
>    - variant_id: str
>    - style: str
>    - placement: str = "feed_square"
>    - image_path: str
>    - visual_evaluation: VisualEvaluation
>    - generation_cost_usd: float
>    - evaluation_cost_usd: float
>    - generation_time_s: float
>
> 6. `MultiModalAdRecord(BaseModel)`:
>    - ad_id: str
>    - brief: AdBrief
>    - text_record: AdRecord          # the full v1 text record
>    - winning_variant: ImageVariant   # best-scoring image variant
>    - all_variants: list[ImageVariant]
>    - combined_score: float           # e.g. 0.6 * text + 0.4 * visual
>    - total_cost_usd: float           # text + image gen + all evaluation
>    - pipeline_time_s: float
>    - timestamp: datetime
>
> Also update the Config model to OPTIONALLY load the new config sections.
> Add these optional fields to Config:
>    - image_generation: Optional[ImageGenerationConfig] = None
>    - visual_evaluation_config: Optional[VisualEvaluationConfig] = None
>
> Use Optional so that v1 code that loads Config without the new YAML sections
> doesn't break. The from_yaml classmethod already uses model_validate which
> will ignore unknown fields — but adding Optional typed fields is cleaner.
>
> Important: all existing models, DEFAULT_WEIGHTS, and the from_yaml classmethod
> must remain unchanged. Only ADD new code.
> ```

### Verify Models

```bash
python3 -c "
from generate.models import VisualEvaluation, DimensionScore, MultiModalAdRecord, Config

# Test VisualEvaluation computed fields
dim = lambda s: DimensionScore(score=s, rationale='Test.', confidence='high')
ve = VisualEvaluation(
    brand_consistency=dim(8),
    engagement_potential=dim(7),
    text_image_coherence=dim(6),
    technical_quality=dim(9),
)
print(f'Visual aggregate: {ve.visual_aggregate_score}')
print(f'Passes threshold: {ve.passes_visual_threshold}')
print(f'Weakest: {ve.weakest_visual_dimension}')

# Test Config loads new sections
config = Config.from_yaml('config/config.yaml')
print(f'Image model: {config.image_generation.model}')
print(f'Visual eval model: {config.visual_evaluation_config.model}')
print('v2 models verified!')
"
```

---

## Phase V2-2: Image Generation Module

**Goal:** Build the core image generation module. This wraps the Nano Banana 2 API into a clean function that takes ad copy and returns a PIL Image.

### Understanding the API

This is the core pattern — every image generation call in your codebase will follow it:

```python
from google import genai
from google.genai import types
from PIL import Image
import os

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

response = client.models.generate_content(
    model="gemini-3.1-flash-image-preview",
    contents=["A warm photo of a teenager studying with a tutor at a kitchen table, natural lighting"],
    config=types.GenerateContentConfig(
        response_modalities=['TEXT', 'IMAGE'],
        image_config=types.ImageConfig(
            aspect_ratio="1:1",
            image_size="1K",
        ),
    ),
)

# Response contains mixed text + image parts — always loop
for part in response.parts:
    if part.inline_data is not None:
        image = part.as_image()   # Returns a PIL Image
        image.save("my_ad.png")
    elif part.text is not None:
        print(part.text)          # Model sometimes adds commentary
```

Key constraints:
- **`response_modalities=['TEXT', 'IMAGE']` is REQUIRED** in the `GenerateContentConfig` to get image output. Without this, the model may return text-only responses.
- **Use `image_config` for aspect ratio and resolution** — `types.ImageConfig(aspect_ratio="1:1", image_size="1K")`. Supported aspect ratios: `1:1`, `2:3`, `3:2`, `3:4`, `4:3`, `4:5`, `5:4`, `9:16`, `16:9`, `21:9`. Supported sizes: `512`, `1K`, `2K`, `4K`. This is more reliable than prompt-based control.
- **`part.as_image()`** returns a PIL `Image` object (requires Pillow installed). Save, resize, or process normally.
- **Mixed response** — always loop through `response.parts` and check type. Never assume `parts[0]` is the image.
- **SynthID watermarks** are automatically embedded. No action needed.
- **Thinking mode** — Gemini 3 image models use "Thinking" by default and it cannot be disabled. You can set `thinking_level` to `"minimal"` (default, faster/cheaper) or `"high"` (better quality, slower). Expose this in config.
- **Rate limits** — image generation has stricter rate limits than text. Plan for 429 retries. Distinguish rate limits (429, retry with backoff) from content policy rejections (retry won't help, modify prompt) and transient failures.

### Cursor Prompt — Image Generator

> **Paste this into Cursor chat:**
>
> ```
> Create a file at `generate/image_generator.py` that handles image generation for ad creatives.
>
> CRITICAL API CONTEXT:
> - We use the google.genai SDK (package: google-genai), NOT google.generativeai.
> - Import: `from google import genai` and `from google.genai import types`
> - Client: `genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))`
> - Model ID: "gemini-3.1-flash-image-preview" (Nano Banana 2)
> - Image generation uses the SAME client.models.generate_content() as text.
> - **REQUIRED**: Pass `config=types.GenerateContentConfig(response_modalities=['TEXT', 'IMAGE'], image_config=types.ImageConfig(aspect_ratio=..., image_size=...))` — without `response_modalities`, the model may return text-only responses.
> - Use `image_config` for aspect ratio and resolution control, NOT prompt text.
> - Images come back in response.parts as part.inline_data, call part.as_image() for PIL Image.
> - There is NO response.images or separate image API.
>
> Import from existing codebase:
> - GeneratedAd, AdBrief, Config from generate/models.py
> - get_config, get_gemini_client from config/loader.py
> - @observe from config/observability.py
>
> Create these functions:
>
> 1. `class ImageGenerationError(Exception): pass`
>
> 2. `build_image_prompt(ad: GeneratedAd, brief: AdBrief, style: str, placement: str = "feed_square") -> str`
>    - This is the prompt engineering function — the most important part.
>    - Load templates from generate/image_prompts/templates.yaml (created in V2-3,
>      but for now hardcode the mappings so the module is self-contained).
>    - Map audience_segment to scene descriptions:
>      - anxious_parents → warm home setting, parent helping teen, kitchen table
>      - stressed_students → bright study space, focused teen, laptop, natural light
>      - comparison_shoppers → clean modern setting, before/after or achievement visual
>    - Map style to visual instructions:
>      - photorealistic → "Professional photography, natural lighting, shallow DOF, 85mm lens"
>      - ugc_style → "Casual smartphone photo, slightly imperfect, authentic, warm light"
>      - illustration → "Modern flat illustration, clean lines, warm colors, friendly"
>      - minimal_graphic → "Bold typography focal point, gradient background, minimal imagery"
>    - Map placement to aspect ratio (used in image_config, NOT prompt text):
>      - feed_square → "1:1"
>      - stories_vertical → "9:16"
>      - feed_landscape → "16:9"
>    - NOTE: Aspect ratio is enforced via types.ImageConfig(aspect_ratio=...) in the
>      API call, not through prompt text. The prompt should describe the scene/style only.
>    - Include the headline as text overlay instruction (optional — see text overlay fallback)
>    - Include brand guidelines: warm blues, approachable, not stock-photo, no watermarks
>    - Combine into a single coherent paragraph (Nano Banana responds best to natural language)
>    - Return the prompt string
>
> 3. `@observe(name="generate-ad-image")
>    generate_ad_image(ad: GeneratedAd, brief: AdBrief, style: str = "photorealistic",
>                      placement: str = "feed_square", config: Config | None = None)
>                      -> tuple[Image.Image, dict]`
>    - Builds the prompt using build_image_prompt()
>    - Maps placement to aspect_ratio: feed_square→"1:1", stories_vertical→"9:16", feed_landscape→"16:9"
>    - Calls Gemini via get_gemini_client() with model from config.image_generation.model
>    - MUST pass config=types.GenerateContentConfig(
>        response_modalities=['TEXT', 'IMAGE'],
>        image_config=types.ImageConfig(
>            aspect_ratio=mapped_ratio,
>            image_size=config.image_generation.default_resolution,
>        ),
>      )
>    - Loops through response.parts to find the image
>    - Tracks generation time with time.time()
>    - Returns (PIL Image, metadata dict) where metadata includes:
>      {"model": str, "prompt": str, "style": str, "placement": str,
>       "generation_time_s": float, "input_tokens": int, "output_tokens": int,
>       "cost_usd": float}
>    - On failure (no image in response): retry once, then raise ImageGenerationError
>    - Log progress with rich console
>
> 4. `generate_image_variants(ad: GeneratedAd, brief: AdBrief, config: Config | None = None)
>                             -> list[tuple[Image.Image, dict]]`
>    - Reads style_approaches from config.image_generation.style_approaches
>    - Generates one image per style (up to config.image_generation.variants_per_ad)
>    - Returns list of (image, metadata) tuples
>    - Handles individual style failures gracefully (skip and continue)
>
> 5. `save_ad_image(image: Image.Image, ad_id: str, variant_index: int, style: str,
>                   output_dir: str = "data/images") -> str`
>    - Saves to: {output_dir}/{ad_id}_v{variant_index}_{style}.png
>    - Creates output_dir if needed
>    - Returns the file path
>
> Cost estimation: use the same _estimate_cost pattern from generate/generator.py.
> Image generation pricing for Nano Banana 2 (standard tier):
>   Text input/output: $0.50/1M input, $3.00/1M output
>   Image output: $0.045/image at 512, $0.067 at 1K, $0.101 at 2K, $0.151 at 4K
> Map config.image_generation.default_resolution to the per-image cost for tracking.
> ```

### Quick Test

```bash
python3 -c "
from generate.image_generator import generate_ad_image, save_ad_image
from generate.models import GeneratedAd, AdBrief
from config.loader import get_config

config = get_config()
brief = AdBrief(audience_segment='anxious_parents', campaign_goal='conversion')
ad = GeneratedAd(
    primary_text='Is your child ready for the digital SAT?',
    headline='Expert SAT Prep',
    description='Join 40,000+ students who raised their scores.',
    cta_button='Try Free'
)

image, metadata = generate_ad_image(ad, brief, style='photorealistic', config=config)
path = save_ad_image(image, 'test_001', 0, 'photorealistic')
print(f'Image saved to: {path}')
print(f'Generation time: {metadata[\"generation_time_s\"]:.1f}s')
print(f'Prompt: {metadata[\"prompt\"][:100]}...')
"
```

Open `data/images/test_001_v0_photorealistic.png` and check: Does it look like a plausible Facebook ad image? Is the mood appropriate?

### Programmatic Text Overlay (Recommended Default)

AI-generated text in images is notoriously unreliable — misspellings, warped letters, illegible fonts. The recommended approach: generate the image WITHOUT text overlay, then composite the headline programmatically with PIL `ImageDraw`. This gives pixel-perfect text every time.

The `text_overlay_mode` config controls this:
- `"programmatic"` (default): Image prompt omits headline text. After generation, PIL composites the headline.
- `"ai"` (experimental): Image prompt includes headline text overlay instruction. Relies on the model rendering text correctly.

Add this to `generate/image_generator.py`:

```python
from PIL import ImageDraw, ImageFont

def apply_text_overlay(image: Image.Image, headline: str,
                       position: str = "bottom", font_size: int = 36) -> Image.Image:
    """Composite headline text onto image with PIL. Pixel-perfect, no AI artifacts."""
    img = image.copy()
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except (OSError, IOError):
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), headline, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    img_w, img_h = img.size

    if position == "bottom":
        x = (img_w - text_w) // 2
        y = img_h - text_h - 40
    else:  # "top"
        x = (img_w - text_w) // 2
        y = 30

    # Semi-transparent background for readability
    padding = 12
    draw.rectangle(
        [x - padding, y - padding, x + text_w + padding, y + text_h + padding],
        fill=(0, 0, 0, 140),
    )
    draw.text((x, y), headline, fill="white", font=font)
    return img
```

In `generate_ad_image()`, after getting the image back from the API:

```python
if config.image_generation.text_overlay_mode == "programmatic":
    image = apply_text_overlay(image, ad.headline)
```

---

## Phase V2-3: Image Prompt Engineering

**Goal:** Build a YAML-based prompt template system for image generation, mirroring the text prompt template pattern from `generate/prompts/generator_prompt.yaml`.

### Cursor Prompt — Prompt Templates

> **Paste this into Cursor chat:**
>
> ```
> Create a file at `generate/image_prompts/templates.yaml` with structured prompt
> templates for Nano Banana 2 image generation.
>
> Structure:
>
> base_instructions: |
>   A shared paragraph appended to every image prompt:
>   - "This is a creative for a Facebook/Instagram paid social ad"
>   - "High quality, well-lit, professional but warm and approachable"
>   - "Brand tone: Varsity Tutors — warm blues and whites, education-focused, trustworthy"
>   - "No watermarks, logos, or UI chrome in the image"
>   - "Do NOT include the Facebook ad interface or phone mockup — just the creative"
>
> audience_scenes:
>   anxious_parents: "A warm, well-lit family home. A supportive parent and their teenager
>     at a kitchen table or cozy home office with study materials. Modern decor, natural light."
>   stressed_students: "A bright, organized study space. A focused teenager with a laptop,
>     determined but not stressed. Study materials visible. Natural window light."
>   comparison_shoppers: "A clean, aspirational setting. A confident student or parent-student
>     pair in a modern environment that communicates 'smart choice.' Achievement-oriented."
>
> style_modifiers:
>   photorealistic: "Professional photography style. Shallow depth of field, natural warm
>     lighting, real people with genuine expressions. DSLR quality, 85mm lens feel. Authentic,
>     not posed stock photography."
>   ugc_style: "Casual smartphone photo aesthetic. Slightly imperfect framing, warm ambient
>     light, real-life feel. Like a parent or student took this photo naturally. No studio setup."
>   illustration: "Modern flat illustration. Clean geometric shapes, warm color palette
>     (blues, warm whites, soft oranges), friendly simplified characters. Think Headspace or
>     Duolingo ad visual language."
>   minimal_graphic: "Bold graphic design. Large sans-serif typography as the focal point,
>     solid or soft gradient background in warm blue tones, minimal imagery. Clean and modern.
>     Think Apple or Nike simplicity applied to education."
>
> placement_instructions:
>   feed_square: "Compose for a square Facebook/Instagram feed placement. Center the focal point."
>   feed_landscape: "Compose for a wide landscape Facebook feed placement. Use horizontal visual flow."
>   stories_vertical: "Compose for a vertical Instagram Stories placement. Stack elements top-to-bottom."
>
> NOTE: Actual aspect ratio is enforced via types.ImageConfig(aspect_ratio=...) in the API
> call, NOT through prompt text. These placement instructions guide composition only.
>
> campaign_goal_modifiers:
>   awareness: "Emotional and aspirational. Focus on possibility, relief, and connection."
>   conversion: "Action-oriented. Clear visual hierarchy, emphasis on the offer."
>
> # Only used when text_overlay_mode == "ai" in config
> headline_instruction_ai: "Include the text '{headline}' as visible overlay text in the image,
>   using a clean, readable sans-serif font in white or dark blue with sufficient contrast
>   against the background."
>
> # Used when text_overlay_mode == "programmatic" (default) — headline added via PIL after generation
> headline_instruction_programmatic: "Leave clear space at the bottom of the image for a text
>   overlay that will be added separately. Do NOT render any text in the image."
>
> Also create `generate/image_prompts/prompt_builder.py` with:
>
> `build_full_image_prompt(ad: GeneratedAd, brief: AdBrief, style: str,
>                          placement: str = "feed_square") -> str`
>   - Loads templates.yaml
>   - Assembles: audience_scene + style_modifier + campaign_goal_modifier
>     + headline_instruction (with {headline} filled) + placement_instruction
>     + base_instructions
>   - Returns a single coherent paragraph (not bullet points)
>   - Caches the loaded YAML at module level (same pattern as generator.py)
>
> Then update generate/image_generator.py to import build_full_image_prompt
> and use it instead of the hardcoded mappings from V2-2. The hardcoded
> version was scaffolding; this YAML-driven version is the real system.
> ```

---

## Phase V2-4: Visual Evaluation (Image Judge)

**Goal:** Build an image evaluation module that scores generated images across 4 visual dimensions, mirroring the text evaluation pattern in `evaluate/judge.py`.

### Understanding Multimodal Evaluation

Gemini accepts PIL Images directly in the `contents` list. The official pattern is text first, then image:

```python
from google import genai
from PIL import Image

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
image = Image.open("my_ad.png")

response = client.models.generate_content(
    model="gemini-2.5-flash",            # multimodal judge
    contents=[
        "Evaluate this ad image for brand consistency. Score 1-10 with rationale.",
        image,                            # PIL Image — SDK handles encoding
    ],
)
print(response.text)
```

### Why a Different Model for Visual Evaluation

See the [Multi-Model Orchestration Rationale](#multi-model-orchestration-rationale) section for the full reasoning. Short version: we use `gemini-2.5-flash` for visual evaluation because it has stronger vision capabilities than flash-lite, while remaining cost-effective. This is the first place in the system where we deliberately split models by task.

### Cursor Prompt — Visual Rubrics

> **Paste this into Cursor chat:**
>
> ```
> Create a file at `evaluate/visual/rubrics.py` that defines scoring rubrics for
> the 4 visual quality dimensions.
>
> Follow the exact same pattern as evaluate/dimensions.py — read dimension definitions
> from config (config.visual_evaluation_config.dimensions) and expand them into detailed
> rubric strings for prompt injection.
>
> Functions:
> 1. `get_visual_rubric(dimension_name: str) -> str`
>    - Returns a rubric string with score 1/5/10 anchors and common mistakes
>    - brand_consistency: reference VT's warm blues, approachable feel,
>      NOT stock-photo generic, NOT corporate cold. Common mistake: generic office
>      photo that could be any company.
>    - engagement_potential: would you stop scrolling? Contrast, visual hierarchy,
>      emotional impact. Common mistake: flat, forgettable image with no focal point.
>    - text_image_coherence: does the image reinforce the copy's message?
>      Common mistake: copy talks about a specific student story but image is generic.
>    - technical_quality: resolution, no AI artifacts (distorted hands, melted text,
>      extra fingers), clean composition. Common mistake: text overlay is unreadable.
>
> 2. `get_all_visual_rubrics() -> dict[str, str]`
> ```

### Cursor Prompt — Image Judge Module

> **Paste this into Cursor chat:**
>
> ```
> Create a file at `evaluate/visual/image_judge.py` that evaluates ad images.
>
> CRITICAL API CONTEXT:
> - We use google.genai SDK. Client from config/loader.py via get_gemini_client().
> - For visual evaluation, use the model from config.visual_evaluation_config.model
>   (currently "gemini-2.5-flash" — NOT the image generation model).
> - Pass contents as [prompt_text, pil_image] — text FIRST, then image.
> - The SDK handles PIL Image encoding automatically.
>
> Follow the pattern of evaluate/judge.py closely. Reuse DimensionScore from
> generate/models.py. Reuse the _extract_json helper pattern.
>
> Functions:
>
> 1. `@observe(name="evaluate-image-dimension")
>    evaluate_image_dimension(image: Image.Image, ad: GeneratedAd,
>        dimension_name: str, rubric: str) -> tuple[DimensionScore, dict]`
>    - Builds a prompt with: the dimension rubric, the ad copy text for context
>      (primary_text, headline, description), and scoring instructions
>    - Sends [prompt_text, image] to the visual evaluation model
>    - Uses temperature=0 for consistent scoring
>    - Parses JSON response into DimensionScore
>    - Handles parse errors: retry once, then fallback to score=5
>    - Returns (DimensionScore, usage_dict)
>
>    The prompt should include:
>    "You are evaluating a Facebook/Instagram ad IMAGE for Varsity Tutors SAT prep.
>     The ad copy this image accompanies:
>     Primary Text: {primary_text}
>     Headline: {headline}
>     Description: {description}
>
>     Evaluate the IMAGE (not the text) on this dimension:
>     {rubric}
>
>     Respond with ONLY JSON: {\"score\": int 1-10, \"rationale\": str, \"confidence\": str}"
>
> 2. `@observe(name="evaluate-ad-image")
>    evaluate_ad_image(image: Image.Image, ad: GeneratedAd,
>        config: Config | None = None) -> tuple[VisualEvaluation, dict]`
>    - Evaluates the image across all 4 visual dimensions
>    - Loads rubrics from evaluate/visual/rubrics.py
>    - Assembles VisualEvaluation (computed fields handle aggregation)
>    - Prints a rich summary table (same style as evaluate/judge.py)
>    - Returns (VisualEvaluation, aggregated_usage_dict)
>
> Import @observe from config/observability.py.
> Import VisualEvaluation, DimensionScore from generate/models.py.
> Add rich console logging matching the style in evaluate/judge.py.
> ```

### Visual Calibration Test

```bash
python3 -c "
from PIL import Image
from generate.models import GeneratedAd
from evaluate.visual.image_judge import evaluate_ad_image

# Use the test image from V2-0, or generate a fresh one
image = Image.open('data/images/test_image.png')
ad = GeneratedAd(
    primary_text='Is your child ready for the digital SAT?',
    headline='Expert SAT Prep',
    description='Join 40,000+ students',
    cta_button='Try Free'
)

evaluation, usage = evaluate_ad_image(image, ad)
print(f'Visual aggregate: {evaluation.visual_aggregate_score}')
print(f'Passes threshold: {evaluation.passes_visual_threshold}')
print(f'Weakest: {evaluation.weakest_visual_dimension}')
print(f'Cost: \${usage[\"cost_usd\"]:.4f}')
"
```

> **Decision Log Entry:** After running visual calibration, document: How do the visual scores compare to your own judgment? Which dimensions does the evaluator get right vs. wrong? Visual eval is significantly harder than text eval — honest documentation here is valuable.

---

## Phase V2-5: A/B Variant Generation

**Goal:** For a single text ad, generate multiple image variants across different styles, evaluate each, and automatically select the winner.

### Cursor Prompt — A/B Variant Engine

> **Paste this into Cursor chat:**
>
> ```
> Create a file at `generate/ab_variants.py` that generates and evaluates A/B
> creative variants for a single text ad.
>
> Import from existing code:
> - GeneratedAd, AdBrief, Config, ImageVariant, VisualEvaluation from generate/models.py
> - generate_ad_image, save_ad_image from generate/image_generator.py
> - evaluate_ad_image from evaluate/visual/image_judge.py
> - get_config from config/loader.py
> - @observe from config/observability.py
>
> Functions:
>
> 1. `@observe(name="generate-ab-variants")
>    generate_ab_variants(ad: GeneratedAd, brief: AdBrief, ad_id: str,
>        config: Config | None = None) -> list[ImageVariant]`
>    - Reads style_approaches and variants_per_ad from config.image_generation
>    - For each style (up to variants_per_ad):
>      a) generate_ad_image(ad, brief, style=style)
>      b) save_ad_image(image, ad_id, variant_index, style)
>      c) evaluate_ad_image(image, ad)
>      d) Assemble an ImageVariant with all the data
>    - Sort variants by visual_aggregate_score descending (best first)
>    - Return the sorted list
>    - Handle individual variant failures gracefully (log error, skip, continue)
>    - Print a summary table showing all variants and their scores
>
> 2. `select_best_variant(variants: list[ImageVariant],
>        campaign_goal: str = "awareness") -> ImageVariant`
>    - Returns the variant with the highest visual_aggregate_score
>    - Tiebreaker (scores within 0.5 of each other):
>      - conversion campaigns → prefer "photorealistic" (feels more credible)
>      - awareness campaigns → prefer "ugc_style" (feels more authentic)
>    - If no variants exist, raise ValueError
>
> 3. `save_variant_comparison(variants: list[ImageVariant],
>        ad_id: str, output_dir: str = "data/images") -> str`
>    - Uses PIL to create a side-by-side comparison image
>    - Each variant image shown at reduced size with its style name and score overlaid
>    - Green border on the winning variant
>    - Saves to data/images/comparison_{ad_id}.png
>    - Returns the file path
> ```

### Test A/B Generation

```bash
python3 -c "
from generate.ab_variants import generate_ab_variants, select_best_variant
from generate.models import GeneratedAd, AdBrief
from config.loader import get_config

config = get_config()
brief = AdBrief(audience_segment='anxious_parents', campaign_goal='conversion',
                specific_offer='Free SAT practice test')
ad = GeneratedAd(
    primary_text='Your child is smart. The SAT just doesn\'t show it yet.',
    headline='Close the SAT Gap',
    description='1:1 diagnostic-driven tutoring.',
    cta_button='Try Free',
)

variants = generate_ab_variants(ad, brief, ad_id='test_ab', config=config)
winner = select_best_variant(variants, campaign_goal='conversion')
print(f'Winner: {winner.style} (score: {winner.visual_evaluation.visual_aggregate_score})')
print(f'Image: {winner.image_path}')
"
```

---

## Phase V2-6: Multi-Modal Pipeline Integration

**Goal:** Wire the text pipeline (v1) and image pipeline (v2) into a single end-to-end flow.

### Cursor Prompt — Multimodal Pipeline

> **Paste this into Cursor chat:**
>
> ```
> Create a file at `iterate/multimodal_pipeline.py` that orchestrates the full
> multimodal ad generation pipeline.
>
> Import from existing code:
> - run_pipeline from iterate/feedback.py (the v1 text pipeline)
> - generate_ab_variants, select_best_variant from generate/ab_variants.py
> - AdBrief, Config, AdRecord, MultiModalAdRecord, ImageVariant from generate/models.py
> - get_config from config/loader.py
> - @observe, propagate_attributes, get_langfuse from config/observability.py
>
> Functions:
>
> 1. `@observe(name="run-multimodal-pipeline")
>    run_multimodal_pipeline(brief: AdBrief, config: Config) -> MultiModalAdRecord`
>
>    STAGE 1 — TEXT (reuse v1):
>    - Call run_pipeline(brief, config) from iterate/feedback.py
>    - This returns an AdRecord with the best text ad (already iterated)
>    - If text doesn't pass threshold after max attempts, still proceed to images
>      (the text is the best we have)
>
>    STAGE 2 — IMAGES (new for v2):
>    - Call generate_ab_variants(text_record.generated_ad, brief, text_record.ad_id, config)
>    - This generates multiple image variants and evaluates each
>    - Call select_best_variant(variants, brief.campaign_goal)
>
>    STAGE 3 — COMBINE:
>    - Compute combined_score = 0.6 * text_aggregate + 0.4 * visual_aggregate
>      (text is still more important than the image for Meta ads)
>    - Compute total_cost = text costs + all image gen costs + all image eval costs
>    - Assemble MultiModalAdRecord
>    - Print a rich summary showing:
>      - Text score, visual score, combined score
>      - Winning style, image path
>      - Total cost, pipeline time
>
>    Return the MultiModalAdRecord.
>
> 2. `@observe(name="run-multimodal-batch")
>    run_multimodal_batch(briefs: list[AdBrief], config: Config,
>                         num_ads: int = 20) -> list[MultiModalAdRecord]`
>    - Runs run_multimodal_pipeline for each brief (up to num_ads)
>    - Rate-limit handling (same pattern as output/batch_runner.py _run_with_retry)
>    - Saves results to data/multimodal_ad_library.json
>    - Prints batch summary:
>      total ads, text pass rate, visual pass rate, combined pass rate,
>      most popular winning style, total cost, cost per multimodal ad
>    - Flushes Langfuse traces
>
> Make it runnable: `python -m iterate.multimodal_pipeline --num-ads 5`
>
> Add argparse with --num-ads (default 20).
> Use rich Progress bar for batch progress (same pattern as output/batch_runner.py).
> ```

### Test End-to-End

```bash
# Small test (2 ads = ~$1-2 API spend including images)
python -m iterate.multimodal_pipeline --num-ads 2

# Check results
ls data/images/
cat data/multimodal_ad_library.json | python -m json.tool | head -30
```

---

## Phase V2-7: Multi-Model Orchestration

**Goal:** Explicitly document and implement which model handles which task, and why.

### The Orchestration Map

| Task | Model | Why |
|---|---|---|
| **Text generation** | `gemini-3.1-flash-lite-preview` | Cheapest, fast, good enough for creative writing with iteration. V1 proved it works. |
| **Text evaluation** | `gemini-3.1-flash-lite-preview` | Same cheap model. Calibration passed 8/8. Self-evaluation bias exists but is acceptable for v1/v2. |
| **Image generation** | `gemini-3.1-flash-image-preview` | Nano Banana 2. Default image gen model. See note below on Nano Banana Pro alternative. |
| **Visual evaluation** | `gemini-2.5-flash` | Needs stronger vision capabilities than flash-lite for reliable image scoring. 2.5 Flash is the best cost/quality tradeoff for multimodal understanding. |
| **Text improvement** | `gemini-3.1-flash-lite-preview` | Same as generation. Tier 3 strategy ("model_escalation") could upgrade this to 2.5 Flash for stubborn cases. |

### Nano Banana Pro Alternative for Ad Creatives

`gemini-3-pro-image-preview` (Nano Banana Pro) is worth considering for ad creatives, especially those with headline text overlays:

| | Nano Banana 2 (`flash-image-preview`) | Nano Banana Pro (`3-pro-image-preview`) |
|---|---|---|
| **Cost (1K)** | $0.067/image | $0.134/image (2x) |
| **Cost (2K)** | $0.101/image | $0.134/image |
| **Cost (4K)** | $0.151/image | $0.24/image |
| **Text rendering** | Decent, can misspell/warp | "High-fidelity text" — critical for headline overlays |
| **Complex instructions** | Good | Better — uses "advanced reasoning (Thinking)" |
| **Reference images** | 10 objects + 4 characters | 6 objects + 5 characters |
| **512 draft tier** | Yes ($0.045) | No |

**Recommendation:** Use Nano Banana 2 as default. Make the image model configurable in `config.yaml` so you can switch to Pro for campaigns where text rendering quality matters. At 2 variants per ad, Pro adds ~$0.134/ad ($6.70 over a 50-ad batch) — worth it for production creatives with headlines.

### Why Not One Model for Everything?

1. **Image generation is locked** — only Nano Banana 2 (`gemini-3.1-flash-image-preview`) generates images in the Gemini family. No flexibility here.
2. **Text gen/eval on flash-lite is proven** — v1 batch data shows 100% pass rate at $0.044/ad. No reason to spend more.
3. **Visual eval needs better vision** — flash-lite's vision capabilities are weaker. In testing, it struggles to detect subtle AI artifacts and brand consistency issues. `gemini-2.5-flash` provides meaningfully better image understanding at a modest cost increase ($0.30/1M input, $2.50/1M output vs flash-lite's $0.25/$1.50).
4. **The cost math works** — per multimodal ad: ~$0.02 text (flash-lite at $0.25/$1.50) + ~$0.134 images (2 variants × $0.067 at 1K) + ~$0.008 visual eval (2.5 flash) = ~$0.16/ad total. Affordable at batch scale.

### Implementing Model Escalation (Tier 3)

v1's tier 3 improvement strategy ("model_escalation") was a placeholder. Now we can actually implement it.

#### Cursor Prompt — Model Escalation

> **Paste this into Cursor chat:**
>
> ```
> Read iterate/strategies.py. The "model_escalation" strategy (tier 3) currently uses
> the same model as tier 2 with a stronger system prompt. Now that we have multi-model
> orchestration, implement real model escalation:
>
> In iterate/feedback.py, modify improve_ad():
> - When strategy == "model_escalation":
>   - Use "gemini-2.5-flash" instead of config.models.generator
>   - This is a genuine model upgrade: better reasoning, better creative output
>   - Log the model switch clearly: "Escalating to gemini-2.5-flash for improvement"
>   - Track the different cost rate ($0.30/1M input, $2.50/1M output for 2.5-flash
>     vs $0.25/1M input, $1.50/1M output for flash-lite)
>
> This is a targeted change. Only modify the model selection inside improve_ad()
> when strategy == "model_escalation". All other code stays the same.
> ```

> **Decision Log Entry:** Document your model orchestration decisions. Which models did you test? What were the tradeoffs? If you tried different models for visual evaluation, what differences did you observe in scoring quality?

---

## Phase V2-8: Batch Runner & Reporting

**Goal:** Create v2-specific batch running and reporting that includes visual metrics.

### Cursor Prompt — Multimodal Visualizations

> **Paste this into Cursor chat:**
>
> ```
> Read the existing output/visualize.py (v1 visualization module).
>
> Add these v2 functions. Do NOT modify existing v1 functions — they must keep working.
>
> 1. `plot_visual_quality_trends(library_path: str = "data/multimodal_ad_library.json")`
>    - Create a matplotlib 2x2 figure, saved to output/visual_quality_trends.png:
>      a) Top-left: Text score vs Visual score scatter plot. Each dot is one ad.
>         X-axis: text aggregate score. Y-axis: visual aggregate score.
>         Color by audience_segment. Draw threshold lines at 7.0 (text) and 6.5 (visual).
>      b) Top-right: Visual dimension averages (grouped bar chart).
>         4 bars: brand_consistency, engagement_potential, text_image_coherence, technical_quality.
>      c) Bottom-left: Winning style distribution (pie chart).
>         What % of winning variants were photorealistic vs ugc_style vs illustration vs minimal_graphic?
>      d) Bottom-right: Cost breakdown (stacked bar chart).
>         Average per-ad cost split: text generation, text evaluation, image generation, image evaluation.
>
> 2. `create_ad_showcase(library_path: str = "data/multimodal_ad_library.json", top_n: int = 5)`
>    - Creates a PIL composite image showing the top N ads by combined_score
>    - For each ad: the generated image, headline, text score, visual score, combined score
>    - Layout: 1 ad per row, image on left, text info on right
>    - Save to output/ad_showcase.png
>
> 3. `generate_multimodal_report(library_path: str = "data/multimodal_ad_library.json")`
>    - Extends the v1 report format with:
>      - Visual dimension averages and stdevs
>      - Correlation between text and visual scores (do good text ads get good images?)
>      - Most successful style per audience segment
>      - Image generation cost breakdown
>      - Pipeline time breakdown (text stages vs image stages)
>    - Save to data/multimodal_evaluation_report.json and data/multimodal_evaluation_report.md
>
> Make it runnable: `python -m output.visualize --v2`
> Use argparse: no flag = v1 only, --v2 = run v2 visualizations too.
> ```

---

## Phase V2-9: Web Dashboard Update

**Goal:** Extend the FastAPI dashboard (`server.py` + `templates/index.html` + `static/app.js`) to display generated images alongside ad copy.

### Cursor Prompt — Dashboard v2

> **Paste this into Cursor chat:**
>
> ```
> Read server.py, templates/index.html, and static/app.js.
>
> Extend the web dashboard for v2 multimodal ads. Changes needed:
>
> 1. In server.py:
>    - Add a new SSE endpoint POST /api/generate-multimodal that:
>      a) Runs the text pipeline (same as /api/generate)
>      b) After text completes, streams "image_generating" events
>      c) Generates image variants, streams each variant as "image_variant" event
>         with the image path (served from /data/images/)
>      d) Streams visual evaluation scores per variant
>      e) Streams "image_selected" event with the winning variant
>      f) Final "complete" event with the full MultiModalAdRecord
>    - Mount data/images as a static files directory so images are servable
>    - Add GET /api/multimodal-library endpoint
>
> 2. In templates/index.html:
>    - Add a toggle on the Generate tab: "Text Only" vs "Multi-Modal"
>    - When Multi-Modal is selected, the generate button calls /api/generate-multimodal
>    - After the ad card, show an "Image Variants" section:
>      - Display each variant image with its style name and visual score
>      - Highlight the winning variant with a green border
>      - Show a second radar chart for visual dimensions alongside the text radar
>    - On the Library tab, show the generated image thumbnail next to each ad row
>    - On the Library detail panel, show the full-size image with visual scores
>
> 3. In static/app.js:
>    - Handle the new SSE event types (image_generating, image_variant,
>      image_selected) in the generate flow
>    - Render variant images as they arrive (progressive loading)
>    - Add a second Chart.js radar for visual dimensions
>    - Update the library detail view to show images
>
> Keep all existing v1 functionality working. The "Text Only" toggle should
> behave exactly like the current generate flow.
> ```

---

## Phase V2-10: Tests for v2

**Goal:** Add 8+ new tests covering image generation, visual evaluation, and A/B variants.

### Cursor Prompt — v2 Tests

> **Paste this into Cursor chat:**
>
> ```
> Add v2 tests to the tests/ directory. We need at least 8 new tests.
> None of these should call the real Gemini API — mock everything.
>
> tests/test_image_generator.py (3 tests):
> - test_build_image_prompt_contains_headline:
>   Call build_image_prompt (or build_full_image_prompt) with a GeneratedAd
>   that has headline "Expert SAT Prep". Assert the prompt string contains
>   "Expert SAT Prep".
> - test_build_image_prompt_audience_mapping:
>   Call with audience_segment "anxious_parents". Assert the prompt contains
>   parent/family/home-related terms.
> - test_build_image_prompt_style_mapping:
>   Call with style "photorealistic". Assert the prompt contains photography
>   terms like "natural lighting" or "DSLR" or "depth of field".
>
> tests/test_visual_judge.py (3 tests):
> - test_get_visual_rubric_returns_string:
>   Call get_visual_rubric("brand_consistency"). Assert non-empty string.
> - test_visual_evaluation_aggregate:
>   Create a VisualEvaluation with known scores:
>   brand_consistency=8, engagement=7, coherence=6, technical=9.
>   Expected: 0.30*8 + 0.30*7 + 0.25*6 + 0.15*9 = 2.4+2.1+1.5+1.35 = 7.35.
>   Verify visual_aggregate_score == 7.35.
> - test_visual_threshold:
>   Create VisualEvaluation with aggregate 6.0 → passes_visual_threshold is False.
>   Create one with 7.0 → passes_visual_threshold is True.
>
> tests/test_ab_variants.py (2 tests):
> - test_select_best_variant:
>   Create 3 mock ImageVariant objects with visual_aggregate_scores 6.0, 7.5, 7.0.
>   Verify select_best_variant returns the one scoring 7.5.
> - test_select_best_variant_tiebreaker:
>   Create 2 mock ImageVariant objects scoring 7.5 and 7.3 (within 0.5).
>   One is "photorealistic", one is "ugc_style".
>   For campaign_goal="conversion", verify "photorealistic" wins.
>   For campaign_goal="awareness", verify "ugc_style" wins.
>
> Use pytest fixtures in tests/conftest.py — add new fixtures for:
> - sample_visual_evaluation: VisualEvaluation with all scores at 7
> - sample_image_variant: ImageVariant with known values
>
> Mock the Gemini client using unittest.mock.patch on config.loader.get_gemini_client.
> ```

### Run All Tests

```bash
# Run v1 + v2 tests together
pytest tests/ -v

# Expected: 23+ tests (15 from v1 + 8 from v2), all passing
```

---

## Phase V2-11: Documentation & Decision Log

**Goal:** Update project documentation with v2-specific content.

### Decision Log Entries to Add

Open `docs/decision_log.md` and add entries for:

1. **Image generation model choice** — Why Nano Banana 2? What alternatives did you consider? (Flux, DALL-E, Stable Diffusion via API)
2. **Visual evaluation model choice** — Why `gemini-2.5-flash` instead of flash-lite? What differences did you observe in scoring quality? Include specific examples if possible.
3. **Visual dimension weighting** — Why 0.30/0.30/0.25/0.15? Why is the visual threshold (6.5) lower than text (7.0)?
4. **Combined score formula** — Why 0.6 text + 0.4 visual? What happens if you weight them equally?
5. **Style selection tiebreaker** — Why photorealistic for conversion, ugc_style for awareness? Is this validated by the data or an assumption?
6. **Image prompt engineering** — What prompts worked vs. didn't? What did you learn about Nano Banana 2's strengths and weaknesses?

### Update `docs/limitations.md`

Add a "v2: Multi-Modal" section covering:

- Image quality variance (Nano Banana 2 is inconsistent — some images are great, some have artifacts)
- Text rendering in images (AI models struggle with readable text overlay)
- Visual evaluation is noisier than text evaluation (scores have higher variance)
- No real-world A/B testing — "best variant" is based on LLM judgment, not click-through rates
- Image generation is the new cost bottleneck (~$0.07/image vs ~$0.004/text generation)
- Self-evaluation bias now compounds — same model family for both text and visual scoring

### Update `README.md`

Add v2 sections:
- Updated architecture diagram showing the multimodal pipeline
- New entry points (`python -m iterate.multimodal_pipeline`)
- Updated cost estimates (per-ad cost with images)
- Multi-model orchestration table

---

## Multi-Model Orchestration Rationale

This section documents the reasoning behind which model does what. Include a version of this in your decision log.

### The Problem

v1 used a single model (`gemini-3.1-flash-lite-preview`) for everything. This was a deliberate cost-optimization choice that worked because text generation and text evaluation are both tasks flash-lite handles well. v2 introduces two new task types — image generation and image understanding — that have fundamentally different model requirements.

### The Decision Framework

For each task, evaluate on three axes:

1. **Capability** — Can the model do this task at all? At what quality level?
2. **Cost** — What's the per-unit cost? What's the batch cost at 50+ ads?
3. **Self-evaluation bias** — Does using the same model for generation and evaluation create blind spots?

### Per-Task Analysis

**Text Generation (keep flash-lite):**
Flash-lite produces good creative copy. The v1 batch proved it: 100% pass rate, 7.59 avg score. The improvement loop compensates for any individual weak generations. Upgrading to a stronger model would 4-10x the cost for marginal quality gains. Verdict: keep flash-lite.

**Text Evaluation (keep flash-lite, flag as tech debt):**
Flash-lite's text evaluation passed calibration 8/8. But the 100% pass rate and compressed score range (7.0–8.85) suggest it may be too lenient. Using a different model family (Claude, GPT-4) would provide a genuine external check on quality. This is documented tech debt — worth revisiting in v3 but not blocking v2.

**Image Generation (Nano Banana 2 — no choice):**
`gemini-3.1-flash-image-preview` is the only Gemini model that generates images. External alternatives (DALL-E 3, Flux, Stable Diffusion via API) are viable but would add a second API key, a second SDK, and cross-provider orchestration complexity. For v2, staying within the Gemini ecosystem is the pragmatic choice. If image quality is insufficient, Flux via Replicate or fal.ai is the recommended fallback — add this to your decision log.

**Visual Evaluation (upgrade to gemini-2.5-flash):**
This is the one place where flash-lite genuinely struggles. Image understanding requires stronger vision capabilities — detecting brand consistency, evaluating composition, spotting AI artifacts. In testing, flash-lite tends to give everything 6-8 on visual dimensions regardless of actual quality. `gemini-2.5-flash` provides meaningfully better discrimination at modest additional cost. The per-image evaluation cost increase is ~$0.01 — negligible at batch scale.

### Cost Summary

**Model pricing (standard tier):**
- `gemini-3.1-flash-lite-preview`: $0.25/1M input, $1.50/1M output
- `gemini-2.5-flash`: $0.30/1M input, $2.50/1M output
- `gemini-3.1-flash-image-preview` (text/thinking): $0.50/1M input, $3.00/1M output
- `gemini-3.1-flash-image-preview` (images): $0.045/image at 512, $0.067 at 1K, $0.101 at 2K, $0.151 at 4K
- `gemini-3-pro-image-preview` (images): $0.134/image at 1K-2K, $0.24 at 4K

| Component | Model | Cost per unit | Units per ad | Cost per ad |
|---|---|---|---|---|
| Text generation | flash-lite ($0.25/$1.50) | ~$0.002 | 1-3 (with retries) | ~$0.005 |
| Text evaluation | flash-lite ($0.25/$1.50) | ~$0.004 | 1-3 (5 dims × 1-3 evals) | ~$0.008 |
| Text improvement | flash-lite / 2.5-flash (tier 3) | ~$0.002-0.005 | 0-2 | ~$0.005 |
| Image generation | Nano Banana 2 ($0.067/1K) | ~$0.067 | 2 variants | ~$0.134 |
| Visual evaluation | 2.5-flash ($0.30/$2.50) | ~$0.001 | 2 variants × 4 dims | ~$0.008 |
| **Total** | | | | **~$0.16** |

At 50 ads: approximately **$8.00** for a full multimodal batch (vs. ~$0.75–1.00 for text-only v1 at correct flash-lite rates).

**Key insight:** Image generation is the overwhelming cost driver (~84% of per-ad cost). Optimize there first: use 512 resolution for draft/evaluation, only upscale the winning variant to 1K/2K. Consider the Batch API for image gen (50% cost reduction: $0.034/image at 1K).

---

## Cursor Troubleshooting: Image Generation

### Problem: Cursor uses the wrong SDK

> ```
> CORRECTION: We use the `google.genai` SDK (package: google-genai), NOT `google.generativeai`.
>
> Correct:
>   from google import genai
>   client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
>
> NOT:
>   import google.generativeai as genai
>   genai.configure(api_key=...)
>
> Please rewrite using the correct SDK.
> ```

### Problem: Cursor tries to use a separate image generation API

> ```
> CORRECTION: Nano Banana 2 does NOT have a separate image generation endpoint.
> It uses the SAME client.models.generate_content() as text generation.
> Images come back in response.parts:
>
>   for part in response.parts:
>       if part.inline_data is not None:
>           image = part.as_image()  # Returns PIL Image
>
> There is no response.images, no separate image API. Please rewrite.
> ```

### Problem: Cursor doesn't handle mixed text+image response

> ```
> CORRECTION: Nano Banana 2 returns BOTH text and image parts in a single response.
> You MUST loop through all parts:
>
>   image_result = None
>   for part in response.parts:
>       if part.inline_data is not None:
>           image_result = part.as_image()
>       elif part.text is not None:
>           pass  # model commentary, can log or ignore
>
>   if image_result is None:
>       raise ImageGenerationError("No image in response")
>
> Do NOT assume parts[0] is the image. The order varies. Always loop.
> ```

### Problem: Cursor sends images to the wrong model for evaluation

> ```
> CORRECTION: For visual EVALUATION, use gemini-2.5-flash (the vision model from config),
> NOT the image generation model. Send text first, then image:
>
>   response = client.models.generate_content(
>       model="gemini-2.5-flash",
>       contents=[prompt_text, pil_image],  # text FIRST, then image
>   )
>
> The image generation model (gemini-3.1-flash-image-preview) is for CREATING images.
> The evaluation model (gemini-2.5-flash) is for ANALYZING images.
> ```

### Problem: Rate limiting on image generation

> ```
> Image generation has stricter rate limits than text. If you're getting 429 errors:
>
> 1. Add exponential backoff: 30s, then 60s, then 120s
> 2. Reduce batch parallelism — generate images sequentially, not in parallel
> 3. Check your Gemini dashboard for current rate limit quotas
> 4. Consider caching: if the same prompt produces the same image, save and reuse
>
> The batch runner should use the same _is_rate_limit_error() + retry pattern
> from output/batch_runner.py but with longer wait times for image calls.
> ```

---

## v2 Final Checklist

Before considering v2 complete:

- [ ] Image generation works with Nano Banana 2 (`gemini-3.1-flash-image-preview`)
- [ ] Generated images saved to `data/images/` with descriptive filenames
- [ ] Image prompt templates in `generate/image_prompts/templates.yaml`
- [ ] Visual evaluation across 4 dimensions using `gemini-2.5-flash`
- [ ] A/B variants generated (at least 2 styles per ad)
- [ ] Best variant auto-selected based on visual scores
- [ ] Variant comparison images saved to `data/images/`
- [ ] Full multimodal pipeline runs: text → eval → images → eval → select
- [ ] Multimodal batch runner generates 20+ complete ads
- [ ] Multi-model orchestration documented with clear rationale
- [ ] Model escalation (tier 3) actually uses a different model
- [ ] Cost tracking covers image generation and visual evaluation
- [ ] Visual quality trends chart generated
- [ ] Ad showcase image generated
- [ ] Web dashboard shows generated images (if time permits)
- [ ] 8+ new v2 tests, all passing (23+ total)
- [ ] Decision log updated with v2-specific entries
- [ ] Limitations doc updated with visual eval and image generation observations
- [ ] README updated with v2 architecture, entry points, and cost estimates

### Files Created or Modified in v2

| Action | File |
|---|---|
| **Modified** | `generate/models.py` (added 6 new models + Config fields) |
| **Modified** | `config/config.yaml` (added image_generation + visual_evaluation) |
| **Modified** | `iterate/feedback.py` (model escalation in improve_ad) |
| **Modified** | `output/visualize.py` (added v2 visualization functions) |
| **Modified** | `server.py` (added multimodal endpoint) |
| **Modified** | `templates/index.html` (image display) |
| **Modified** | `static/app.js` (image SSE handling) |
| **Modified** | `docs/decision_log.md` (v2 entries) |
| **Modified** | `docs/limitations.md` (v2 section) |
| **Modified** | `README.md` (v2 docs) |
| **Created** | `generate/image_generator.py` |
| **Created** | `generate/image_prompts/__init__.py` |
| **Created** | `generate/image_prompts/templates.yaml` |
| **Created** | `generate/image_prompts/prompt_builder.py` |
| **Created** | `generate/ab_variants.py` |
| **Created** | `evaluate/visual/__init__.py` |
| **Created** | `evaluate/visual/rubrics.py` |
| **Created** | `evaluate/visual/image_judge.py` |
| **Created** | `iterate/multimodal_pipeline.py` |
| **Created** | `tests/test_image_generator.py` |
| **Created** | `tests/test_visual_judge.py` |
| **Created** | `tests/test_ab_variants.py` |
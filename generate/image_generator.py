"""Ad image generation module.

Wraps the Nano Banana 2 (gemini-3.1-flash-image-preview) API into clean
functions that take ad copy + brief and return PIL Images. Prompts are
assembled from YAML templates via generate/image_prompts/prompt_builder.py.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from google.genai import types
from PIL import Image, ImageDraw, ImageFont
from rich.console import Console

from config.loader import get_config, get_gemini_client
from config.observability import observe
from generate.image_prompts.prompt_builder import build_full_image_prompt
from generate.models import AdBrief, Config, GeneratedAd

console = Console()

_PLACEMENT_ASPECT_RATIOS: dict[str, str] = {
    "feed_square": "1:1",
    "stories_vertical": "9:16",
    "feed_landscape": "16:9",
}

_IMAGE_COST_PER_UNIT: dict[str, float] = {
    "512": 0.045,
    "1K": 0.067,
    "2K": 0.101,
    "4K": 0.151,
}

_TEXT_INPUT_COST_PER_M = 0.50
_TEXT_OUTPUT_COST_PER_M = 3.00


class ImageGenerationError(Exception):
    pass


def _estimate_image_cost(
    resolution: str, input_tokens: int, output_tokens: int,
) -> float:
    text_cost = (
        input_tokens * _TEXT_INPUT_COST_PER_M
        + output_tokens * _TEXT_OUTPUT_COST_PER_M
    ) / 1_000_000
    image_cost = _IMAGE_COST_PER_UNIT.get(resolution, 0.067)
    return text_cost + image_cost


def apply_text_overlay(
    image: Image.Image,
    headline: str,
    position: str = "bottom",
    font_size: int = 36,
) -> Image.Image:
    """Composite headline text onto image with PIL. Pixel-perfect, no AI artifacts."""
    img = image.copy().convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size,
        )
    except (OSError, IOError):
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), headline, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    img_w, img_h = img.size

    if position == "bottom":
        x = (img_w - text_w) // 2
        y = img_h - text_h - 40
    else:
        x = (img_w - text_w) // 2
        y = 30

    padding = 12
    draw.rectangle(
        [x - padding, y - padding, x + text_w + padding, y + text_h + padding],
        fill=(0, 0, 0, 140),
    )
    draw.text((x, y), headline, fill="white", font=font)

    return Image.alpha_composite(img, overlay).convert("RGB")


@observe(name="generate-ad-image")
def generate_ad_image(
    ad: GeneratedAd,
    brief: AdBrief,
    style: str = "photorealistic",
    placement: str = "feed_square",
    config: Config | None = None,
) -> tuple[Image.Image, dict[str, Any]]:
    """Generate a single ad image via Nano Banana 2.

    Returns (PIL Image, metadata_dict).
    """
    if config is None:
        config = get_config()

    client = get_gemini_client()
    prompt = build_full_image_prompt(ad, brief, style, placement, config)
    aspect_ratio = _PLACEMENT_ASPECT_RATIOS.get(placement, "1:1")
    resolution = config.image_generation.default_resolution if config.image_generation else "1K"
    model_name = config.image_generation.model if config.image_generation else "gemini-3.1-flash-image-preview"

    console.print(
        f"\n[bold cyan]Generating image[/bold cyan]  "
        f"style={style}  placement={placement}  ratio={aspect_ratio}"
    )

    max_attempts = 2
    for attempt in range(max_attempts):
        try:
            start = time.time()
            response = client.models.generate_content(
                model=model_name,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    image_config=types.ImageConfig(
                        aspect_ratio=aspect_ratio,
                        image_size=resolution,
                    ),
                ),
            )
            elapsed = time.time() - start

            input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
            cost = _estimate_image_cost(resolution, input_tokens, output_tokens)

            image_result: Image.Image | None = None
            for part in response.parts:
                if part.inline_data is not None:
                    genai_img = part.as_image()
                    image_result = genai_img._pil_image if hasattr(genai_img, "_pil_image") else genai_img
                    break

            if image_result is None:
                if attempt < max_attempts - 1:
                    console.print("  [yellow]No image in response, retrying...[/yellow]")
                    continue
                raise ImageGenerationError(
                    f"No image returned after {max_attempts} attempts"
                )

            NO_TEXT_STYLES = {"ugc_style"}

            overlay_mode = "programmatic"
            if config.image_generation:
                overlay_mode = config.image_generation.text_overlay_mode

            if overlay_mode == "programmatic" and style not in NO_TEXT_STYLES:
                image_result = apply_text_overlay(image_result, ad.headline)

            metadata: dict[str, Any] = {
                "model": model_name,
                "prompt": prompt,
                "style": style,
                "placement": placement,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "generation_time_s": round(elapsed, 2),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": round(cost, 6),
            }

            console.print(
                f"  [green]Image generated[/green] in {elapsed:.1f}s | "
                f"Tokens: {input_tokens:,} in / {output_tokens:,} out | "
                f"Est. cost: ${cost:.4f}"
            )

            return image_result, metadata

        except ImageGenerationError:
            raise
        except Exception as exc:
            if attempt < max_attempts - 1:
                console.print(f"  [yellow]Error ({exc}), retrying...[/yellow]")
                continue
            raise ImageGenerationError(
                f"Image generation failed after {max_attempts} attempts: {exc}"
            ) from exc

    raise ImageGenerationError("Unreachable — generation loop exited without return")


def generate_image_variants(
    ad: GeneratedAd,
    brief: AdBrief,
    config: Config | None = None,
) -> list[tuple[Image.Image, dict[str, Any]]]:
    """Generate one image per style, up to variants_per_ad.

    Returns list of (image, metadata) tuples. Individual failures are
    logged and skipped.
    """
    if config is None:
        config = get_config()

    styles = (
        config.image_generation.style_approaches
        if config.image_generation
        else ["photorealistic", "ugc_style"]
    )
    max_variants = (
        config.image_generation.variants_per_ad
        if config.image_generation
        else 2
    )
    styles = styles[:max_variants]

    console.print(f"\n[bold]Generating {len(styles)} image variant(s)...[/bold]")

    results: list[tuple[Image.Image, dict[str, Any]]] = []
    for style in styles:
        try:
            image, metadata = generate_ad_image(ad, brief, style=style, config=config)
            results.append((image, metadata))
        except ImageGenerationError as exc:
            console.print(f"  [red]style={style} failed:[/red] {exc}")

    console.print(
        f"[bold]Generated {len(results)}/{len(styles)} variant(s) successfully.[/bold]"
    )
    return results


def save_ad_image(
    image: Image.Image,
    ad_id: str,
    variant_index: int,
    style: str,
    output_dir: str = "data/images",
) -> str:
    """Save a generated image to disk.

    Returns the file path.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    filename = f"{ad_id}_v{variant_index}_{style}.png"
    path = out / filename
    image.save(path)
    console.print(f"  Saved: {path}")
    return str(path)

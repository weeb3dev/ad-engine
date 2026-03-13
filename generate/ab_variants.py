"""A/B creative variant engine.

Generates multiple image variants for a single text ad across different
visual styles, evaluates each via the image judge, selects a winner,
and produces a side-by-side comparison image.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from rich.console import Console
from rich.table import Table

from config.loader import get_config
from config.observability import observe
from evaluate.visual.image_judge import evaluate_ad_image
from generate.image_generator import (
    ImageGenerationError,
    generate_ad_image,
    save_ad_image,
)
from generate.models import AdBrief, Config, GeneratedAd, ImageVariant

console = Console()

_TIEBREAK_PREFERENCE: dict[str, str] = {
    "conversion": "photorealistic",
    "awareness": "ugc_style",
}

_TIEBREAK_DELTA = 0.5


@observe(name="generate-ab-variants")
def generate_ab_variants(
    ad: GeneratedAd,
    brief: AdBrief,
    ad_id: str,
    config: Config | None = None,
) -> list[ImageVariant]:
    """Generate, save, and evaluate image variants for a single text ad.

    Returns a list of ``ImageVariant`` sorted by visual aggregate score
    (best first).  Individual style failures are logged and skipped.
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

    console.print(
        f"\n[bold]Generating {len(styles)} A/B variant(s) for [cyan]{ad_id}[/cyan]…[/bold]"
    )

    variants: list[ImageVariant] = []
    for idx, style in enumerate(styles):
        try:
            image, gen_meta = generate_ad_image(
                ad, brief, style=style, config=config,
            )
            image_path = save_ad_image(image, ad_id, idx, style)
            vis_eval, eval_usage = evaluate_ad_image(image, ad, config=config)

            variant = ImageVariant(
                variant_id=f"{ad_id}_v{idx}",
                style=style,
                placement=gen_meta.get("placement", "feed_square"),
                image_path=image_path,
                visual_evaluation=vis_eval,
                generation_cost_usd=gen_meta.get("cost_usd", 0.0),
                evaluation_cost_usd=eval_usage.get("cost_usd", 0.0),
                generation_time_s=gen_meta.get("generation_time_s", 0.0),
            )
            variants.append(variant)

        except (ImageGenerationError, Exception) as exc:
            console.print(
                f"  [red]Variant {idx} ({style}) failed:[/red] {exc}"
            )

    variants.sort(
        key=lambda v: v.visual_evaluation.visual_aggregate_score,
        reverse=True,
    )

    _print_variants_table(variants)
    return variants


def select_best_variant(
    variants: list[ImageVariant],
    campaign_goal: str = "awareness",
) -> ImageVariant:
    """Pick the winning variant by visual aggregate score with tiebreaker.

    Tiebreaker (scores within 0.5 of each other):
      - conversion campaigns prefer ``photorealistic``
      - awareness campaigns prefer ``ugc_style``

    Raises ``ValueError`` if *variants* is empty.
    """
    if not variants:
        raise ValueError("No variants to select from")

    best = max(
        variants,
        key=lambda v: v.visual_evaluation.visual_aggregate_score,
    )
    best_score = best.visual_evaluation.visual_aggregate_score

    preferred_style = _TIEBREAK_PREFERENCE.get(campaign_goal)
    if preferred_style and best.style != preferred_style:
        for v in variants:
            if (
                v.style == preferred_style
                and abs(v.visual_evaluation.visual_aggregate_score - best_score)
                <= _TIEBREAK_DELTA
            ):
                console.print(
                    f"  [yellow]Tiebreaker:[/yellow] preferring "
                    f"[bold]{preferred_style}[/bold] for {campaign_goal} "
                    f"(score delta {abs(v.visual_evaluation.visual_aggregate_score - best_score):.2f})"
                )
                return v

    return best


def save_variant_comparison(
    variants: list[ImageVariant],
    ad_id: str,
    output_dir: str = "data/images",
) -> str:
    """Create a side-by-side comparison image of all variants.

    The winning variant (highest score) gets a green border.
    Returns the saved file path.
    """
    if not variants:
        raise ValueError("No variants to compare")

    thumb_w = 400
    padding = 8
    label_h = 40

    best_score = max(
        v.visual_evaluation.visual_aggregate_score for v in variants
    )

    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18,
        )
    except (OSError, IOError):
        font = ImageFont.load_default()

    thumbnails: list[Image.Image] = []
    for v in variants:
        img = Image.open(v.image_path).convert("RGB")
        ratio = thumb_w / img.width
        thumb_h = int(img.height * ratio)
        img = img.resize((thumb_w, thumb_h), Image.LANCZOS)

        cell_h = thumb_h + label_h + padding * 2
        cell = Image.new("RGB", (thumb_w + padding * 2, cell_h), "white")

        is_winner = (
            v.visual_evaluation.visual_aggregate_score == best_score
        )
        if is_winner:
            border = Image.new(
                "RGB",
                (thumb_w + padding * 2, cell_h),
                (34, 197, 94),
            )
            inner = Image.new(
                "RGB",
                (thumb_w + padding * 2 - 8, cell_h - 8),
                "white",
            )
            border.paste(inner, (4, 4))
            cell = border

        cell.paste(img, (padding, padding))

        draw = ImageDraw.Draw(cell)
        score_str = f"{v.visual_evaluation.visual_aggregate_score:.2f}"
        label = f"{v.style}  |  {score_str}"
        if is_winner:
            label += "  ★ WINNER"

        draw.text(
            (padding, thumb_h + padding + 4),
            label,
            fill="black",
            font=font,
        )
        thumbnails.append(cell)

    max_cell_h = max(t.height for t in thumbnails)
    total_w = sum(t.width for t in thumbnails) + padding * (len(thumbnails) - 1)
    canvas = Image.new("RGB", (total_w, max_cell_h), "white")

    x_offset = 0
    for t in thumbnails:
        canvas.paste(t, (x_offset, 0))
        x_offset += t.width + padding

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"comparison_{ad_id}.png"
    canvas.save(path)
    console.print(f"  [bold green]Comparison saved:[/bold green] {path}")
    return str(path)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _print_variants_table(variants: list[ImageVariant]) -> None:
    """Rich summary table of generated variants."""
    if not variants:
        console.print("  [yellow]No variants generated.[/yellow]")
        return

    table = Table(title="A/B Variant Summary", show_lines=True)
    table.add_column("#", justify="center", style="dim")
    table.add_column("Style", style="cyan")
    table.add_column("Score", justify="center")
    table.add_column("Pass?", justify="center")
    table.add_column("Gen $", justify="right")
    table.add_column("Eval $", justify="right")
    table.add_column("Time", justify="right")
    table.add_column("Path")

    for i, v in enumerate(variants):
        agg = v.visual_evaluation.visual_aggregate_score
        passed = v.visual_evaluation.passes_visual_threshold
        score_style = "green" if passed else "red"
        table.add_row(
            str(i),
            v.style,
            f"[{score_style}]{agg:.2f}[/{score_style}]",
            "[green]PASS[/green]" if passed else "[red]FAIL[/red]",
            f"${v.generation_cost_usd:.4f}",
            f"${v.evaluation_cost_usd:.4f}",
            f"{v.generation_time_s:.1f}s",
            v.image_path,
        )

    console.print(table)

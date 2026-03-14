"""FastAPI web application for the Autonomous Ad Engine.

Single-process server: serves the HTML frontend, static assets,
and JSON API endpoints that wrap the existing pipeline.

Usage:
    uvicorn server:app --reload              # dev
    uvicorn server:app --host 0.0.0.0        # production
"""

import asyncio
import csv
import io
import itertools
import json
import time
import uuid
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import matplotlib

matplotlib.use("Agg")

from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from config.loader import get_config
from evaluate.judge import evaluate_dimension, get_evaluation_context
from evaluate.visual.image_judge import evaluate_ad_image
from generate.ab_variants import select_best_variant
from generate.briefs import CAMPAIGN_GOALS, OFFERS, TONES, generate_brief_matrix, load_briefs
from generate.generator import generate_ad
from generate.image_generator import generate_ad_image, save_ad_image
from generate.models import (
    AdBrief,
    AdEvaluation,
    AdRecord,
    GeneratedAd,
    ImageVariant,
    MultiModalAdRecord,
)
from iterate.feedback import improve_ad, run_pipeline
from iterate.multimodal_pipeline import load_multimodal_library
from iterate.strategies import get_strategy_name
from output.batch_runner import load_ad_library
from output.generate_report import DIMENSION_LABELS, SEGMENT_LABELS

_ROOT = Path(__file__).resolve().parent
_APP_JS_VERSION = str(int((_ROOT / "static" / "app.js").stat().st_mtime))

DIMENSIONS = [
    "clarity",
    "value_proposition",
    "call_to_action",
    "brand_voice",
    "emotional_resonance",
]

VISUAL_DIMENSIONS = [
    "brand_consistency",
    "engagement_potential",
    "text_image_coherence",
    "technical_quality",
]

VISUAL_DIMENSION_LABELS = {
    "brand_consistency": "Brand Consistency",
    "engagement_potential": "Engagement Potential",
    "text_image_coherence": "Text-Image Coherence",
    "technical_quality": "Technical Quality",
}

_TEXT_WEIGHT = 0.6
_VISUAL_WEIGHT = 0.4

for _d in ("data", "data/images", "output", "static", "templates"):
    (_ROOT / _d).mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Autonomous Ad Engine")
app.mount("/static", StaticFiles(directory=str(_ROOT / "static")), name="static")
app.mount("/output", StaticFiles(directory=str(_ROOT / "output")), name="output")
app.mount("/images", StaticFiles(directory=str(_ROOT / "data" / "images")), name="images")
templates = Jinja2Templates(directory=str(_ROOT / "templates"))


# ── Pages ─────────────────────────────────────────────────────────────────


@app.get("/")
async def index(request: Request):
    cfg = get_config()
    segments = [{"id": s.id, "label": s.label} for s in cfg.brand.audience_segments]
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "segments": segments,
            "tones": TONES,
            "offers": OFFERS,
            "goals": CAMPAIGN_GOALS,
            "js_version": _APP_JS_VERSION,
            "config_json": json.dumps(
                {
                    "segments": segments,
                    "tones": TONES,
                    "offers": OFFERS,
                    "goals": CAMPAIGN_GOALS,
                    "dimensions": DIMENSIONS,
                    "dimension_labels": DIMENSION_LABELS,
                    "segment_labels": SEGMENT_LABELS,
                    "visual_dimensions": VISUAL_DIMENSIONS,
                    "visual_dimension_labels": VISUAL_DIMENSION_LABELS,
                }
            ),
        },
    )


# ── API ───────────────────────────────────────────────────────────────────


def _ad_fields(ad: GeneratedAd) -> dict[str, str]:
    return {
        "primary_text": ad.primary_text,
        "headline": ad.headline,
        "description": ad.description,
        "cta_button": ad.cta_button,
    }


def _append_text_ad(record: AdRecord) -> None:
    lib_path = _ROOT / "data" / "ad_library.json"
    existing = json.loads(lib_path.read_text()) if lib_path.exists() else []
    existing.append(record.model_dump(mode="json"))
    lib_path.write_text(json.dumps(existing, indent=2, default=str))


def _append_multimodal_ad(record: MultiModalAdRecord) -> None:
    lib_path = _ROOT / "data" / "multimodal_ad_library.json"
    existing = json.loads(lib_path.read_text()) if lib_path.exists() else []
    existing.append(record.model_dump(mode="json"))
    lib_path.write_text(json.dumps(existing, indent=2, default=str))


@app.post("/api/generate")
async def generate_endpoint(brief: AdBrief):
    """SSE streaming endpoint: emits per-stage events as the pipeline runs."""

    async def stream():
        try:
            cfg = get_config()
            max_attempts = cfg.quality.max_regeneration_attempts
            total_gen_cost = 0.0
            total_eval_cost = 0.0

            # Stage 1: Generate
            yield _sse({"type": "status", "message": "Generating initial ad copy..."})
            ad, gen_usage = await asyncio.to_thread(generate_ad, brief, cfg)
            total_gen_cost += gen_usage["cost_usd"]

            ad_data = _ad_fields(ad)
            yield _sse({"type": "ad_copy", "ad": ad_data})

            # Stage 2: Evaluate per dimension
            rubrics, high_ref, low_ref, dimension_names = await asyncio.to_thread(
                get_evaluation_context
            )
            fields = _ad_fields(ad)
            scores: dict[str, Any] = {}
            eval_cost = 0.0

            for i, dim_name in enumerate(dimension_names):
                label = DIMENSION_LABELS.get(dim_name, dim_name.replace("_", " ").title())
                yield _sse({
                    "type": "eval_start",
                    "dimension": dim_name,
                    "label": label,
                    "index": i + 1,
                    "total": len(dimension_names),
                })

                score, usage = await asyncio.to_thread(
                    evaluate_dimension,
                    ad_fields=fields,
                    dimension_name=dim_name,
                    rubric=rubrics[dim_name],
                    high_ref=high_ref,
                    low_ref=low_ref,
                )
                scores[dim_name] = score
                eval_cost += usage["cost_usd"]

                yield _sse({
                    "type": "eval_progress",
                    "dimension": dim_name,
                    "label": label,
                    "index": i + 1,
                    "total": len(dimension_names),
                    "score": {
                        "score": score.score,
                        "confidence": score.confidence,
                        "rationale": score.rationale,
                    },
                })

            total_eval_cost += eval_cost
            evaluation = AdEvaluation(**scores)
            initial_score = evaluation.aggregate_score

            best_ad = ad
            best_eval = evaluation
            best_strategy: str | None = None
            cycle = 1

            # Stage 3: Improvement loop
            for attempt in range(1, max_attempts + 1):
                if best_eval.passes_threshold:
                    break

                strategy = get_strategy_name(attempt)
                weak_dim = best_eval.weakest_dimension
                display_weak = DIMENSION_LABELS.get(weak_dim, weak_dim.replace("_", " ").title())

                yield _sse({
                    "type": "improving",
                    "cycle": attempt + 1,
                    "strategy": strategy,
                    "weakest": display_weak,
                })

                try:
                    improved_ad, imp_usage = await asyncio.to_thread(
                        improve_ad,
                        ad=best_ad,
                        evaluation=best_eval,
                        brief=brief,
                        config=cfg,
                        attempt=attempt,
                    )
                except ValueError:
                    break

                total_gen_cost += imp_usage["cost_usd"]
                improved_data = _ad_fields(improved_ad)
                yield _sse({"type": "ad_copy", "ad": improved_data, "cycle": attempt + 1})

                # Re-evaluate improved ad
                improved_fields = _ad_fields(improved_ad)
                re_scores: dict[str, Any] = {}
                re_eval_cost = 0.0

                for i, dim_name in enumerate(dimension_names):
                    label = DIMENSION_LABELS.get(dim_name, dim_name.replace("_", " ").title())
                    yield _sse({
                        "type": "eval_start",
                        "dimension": dim_name,
                        "label": label,
                        "index": i + 1,
                        "total": len(dimension_names),
                        "cycle": attempt + 1,
                    })

                    score, usage = await asyncio.to_thread(
                        evaluate_dimension,
                        ad_fields=improved_fields,
                        dimension_name=dim_name,
                        rubric=rubrics[dim_name],
                        high_ref=high_ref,
                        low_ref=low_ref,
                    )
                    re_scores[dim_name] = score
                    re_eval_cost += usage["cost_usd"]

                    yield _sse({
                        "type": "eval_progress",
                        "dimension": dim_name,
                        "label": label,
                        "index": i + 1,
                        "total": len(dimension_names),
                        "score": {
                            "score": score.score,
                            "confidence": score.confidence,
                            "rationale": score.rationale,
                        },
                        "cycle": attempt + 1,
                    })

                total_eval_cost += re_eval_cost
                re_eval = AdEvaluation(**re_scores)
                cycle += 1

                if re_eval.aggregate_score > best_eval.aggregate_score:
                    best_ad = improved_ad
                    best_eval = re_eval
                    best_strategy = strategy

            # Final result
            record = AdRecord(
                ad_id=uuid.uuid4().hex[:12],
                brief=brief,
                generated_ad=best_ad,
                evaluation=best_eval,
                iteration_cycle=cycle,
                improved_from=initial_score if cycle > 1 else None,
                improvement_strategy=best_strategy,
                generation_cost_usd=total_gen_cost,
                evaluation_cost_usd=total_eval_cost,
                timestamp=datetime.utcnow(),
            )

            _append_text_ad(record)
            yield _sse({"type": "complete", "record": record.model_dump(mode="json")})

        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            print(f"[generate_endpoint] ERROR:\n{tb}")
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(stream(), media_type="text/event-stream")


class BatchRequest(BaseModel):
    num_ads: int = 5
    segments: Optional[list[str]] = None
    goals: Optional[list[str]] = None
    tones: Optional[list[str]] = None
    offers: Optional[list[str]] = None
    multimodal: bool = False
    style_approaches: Optional[list[str]] = None


def _build_batch_briefs(req: BatchRequest, cfg) -> list[AdBrief]:
    segs = req.segments or [s.id for s in cfg.brand.audience_segments]
    goals = req.goals or CAMPAIGN_GOALS
    tones = req.tones or TONES
    offers = req.offers or OFFERS

    briefs = [
        AdBrief(
            audience_segment=seg,
            campaign_goal=goal,
            tone=tone,
            specific_offer=offer,
            style_approaches=req.style_approaches if req.multimodal else None,
        )
        for seg, goal, offer, tone in itertools.product(segs, goals, offers, tones)
    ]
    briefs.sort(key=lambda b: (b.audience_segment, b.campaign_goal))
    return briefs[: req.num_ads]


@app.post("/api/batch")
async def batch_endpoint(req: BatchRequest):
    async def stream():
        cfg = get_config()
        briefs = _build_batch_briefs(req, cfg)

        records: list[AdRecord] = []
        mm_records: list[MultiModalAdRecord] = []
        errors: list[str] = []

        for i, brief in enumerate(briefs):
            label = f"{brief.audience_segment}/{brief.campaign_goal}"
            yield _sse({"type": "progress", "current": i, "total": len(briefs), "label": label})

            try:
                text_record = await asyncio.to_thread(run_pipeline, brief, cfg)
                records.append(text_record)

                if req.multimodal:
                    mm_rec = await _run_batch_multimodal(text_record, brief, cfg)
                    if mm_rec:
                        mm_records.append(mm_rec)

                yield _sse({
                    "type": "ad_complete",
                    "index": i,
                    "total": len(briefs),
                    "summary": _batch_summary(records, errors),
                })
            except Exception as exc:
                errors.append(f"Brief {i + 1}: {exc}")

        if records:
            lib_path = _ROOT / "data" / "ad_library.json"
            existing = json.loads(lib_path.read_text()) if lib_path.exists() else []
            existing.extend([r.model_dump(mode="json") for r in records])
            lib_path.write_text(json.dumps(existing, indent=2, default=str))

        if mm_records:
            mm_lib = _ROOT / "data" / "multimodal_ad_library.json"
            existing_mm = json.loads(mm_lib.read_text()) if mm_lib.exists() else []
            existing_mm.extend([r.model_dump(mode="json") for r in mm_records])
            mm_lib.write_text(json.dumps(existing_mm, indent=2, default=str))

        yield _sse({"type": "complete", "summary": _batch_summary(records, errors)})

    return StreamingResponse(stream(), media_type="text/event-stream")


async def _run_batch_multimodal(
    text_record: AdRecord, brief: AdBrief, cfg
) -> MultiModalAdRecord | None:
    pipeline_start = time.time()
    style_approaches = brief.style_approaches or (
        cfg.image_generation.style_approaches if cfg.image_generation else ["photorealistic", "ugc_style"]
    )
    variants_per_ad = cfg.image_generation.variants_per_ad if cfg.image_generation else 2
    styles = style_approaches[:variants_per_ad]

    image_variants: list[ImageVariant] = []
    image_gen_cost = 0.0
    image_eval_cost = 0.0

    for vi, style in enumerate(styles):
        try:
            gen_start = time.time()
            image, meta = await asyncio.to_thread(
                generate_ad_image, text_record.generated_ad, brief, style, "feed_square", cfg,
            )
            gen_time = round(time.time() - gen_start, 2)

            image_path = await asyncio.to_thread(
                save_ad_image, image, text_record.ad_id, vi, style,
            )
            gen_cost = meta.get("cost_usd", 0.0)
            image_gen_cost += gen_cost

            vis_eval, vis_usage = await asyncio.to_thread(
                evaluate_ad_image, image, text_record.generated_ad, cfg,
            )
            ev_cost = vis_usage.get("cost_usd", 0.0)
            image_eval_cost += ev_cost

            variant = ImageVariant(
                variant_id=f"{text_record.ad_id}_v{vi}_{style}",
                style=style,
                placement="feed_square",
                image_path=image_path,
                visual_evaluation=vis_eval,
                generation_cost_usd=round(gen_cost, 6),
                evaluation_cost_usd=round(ev_cost, 6),
                generation_time_s=gen_time,
            )
            image_variants.append(variant)
        except Exception as exc:
            print(f"[batch-multimodal] Image variant {style} failed: {exc}")

    if not image_variants:
        return None

    winner = select_best_variant(image_variants, brief.campaign_goal)
    text_score = text_record.evaluation.aggregate_score
    visual_score = winner.visual_evaluation.visual_aggregate_score
    combined = round(_TEXT_WEIGHT * text_score + _VISUAL_WEIGHT * visual_score, 2)
    total_cost = round(
        text_record.generation_cost_usd + text_record.evaluation_cost_usd + image_gen_cost + image_eval_cost, 6
    )

    return MultiModalAdRecord(
        ad_id=text_record.ad_id,
        brief=brief,
        text_record=text_record,
        winning_variant=winner,
        all_variants=image_variants,
        combined_score=combined,
        total_cost_usd=total_cost,
        pipeline_time_s=round(time.time() - pipeline_start, 2),
        timestamp=datetime.utcnow(),
    )


@app.post("/api/generate-multimodal")
async def generate_multimodal_endpoint(brief: AdBrief):
    """SSE streaming endpoint for multimodal ad generation (text + images)."""

    async def stream():
        try:
            pipeline_start = time.time()
            cfg = get_config()
            max_attempts = cfg.quality.max_regeneration_attempts
            total_gen_cost = 0.0
            total_eval_cost = 0.0

            # ── Stage 1: Text (same as /api/generate) ─────────────────
            yield _sse({"type": "status", "message": "Generating initial ad copy..."})
            ad, gen_usage = await asyncio.to_thread(generate_ad, brief, cfg)
            total_gen_cost += gen_usage["cost_usd"]

            ad_data = _ad_fields(ad)
            yield _sse({"type": "ad_copy", "ad": ad_data})

            rubrics, high_ref, low_ref, dimension_names = await asyncio.to_thread(
                get_evaluation_context
            )
            fields = _ad_fields(ad)
            scores: dict[str, Any] = {}
            eval_cost = 0.0

            for i, dim_name in enumerate(dimension_names):
                label = DIMENSION_LABELS.get(dim_name, dim_name.replace("_", " ").title())
                yield _sse({
                    "type": "eval_start",
                    "dimension": dim_name,
                    "label": label,
                    "index": i + 1,
                    "total": len(dimension_names),
                })

                score, usage = await asyncio.to_thread(
                    evaluate_dimension,
                    ad_fields=fields,
                    dimension_name=dim_name,
                    rubric=rubrics[dim_name],
                    high_ref=high_ref,
                    low_ref=low_ref,
                )
                scores[dim_name] = score
                eval_cost += usage["cost_usd"]

                yield _sse({
                    "type": "eval_progress",
                    "dimension": dim_name,
                    "label": label,
                    "index": i + 1,
                    "total": len(dimension_names),
                    "score": {
                        "score": score.score,
                        "confidence": score.confidence,
                        "rationale": score.rationale,
                    },
                })

            total_eval_cost += eval_cost
            evaluation = AdEvaluation(**scores)
            initial_score = evaluation.aggregate_score

            best_ad = ad
            best_eval = evaluation
            best_strategy: str | None = None
            cycle = 1

            for attempt in range(1, max_attempts + 1):
                if best_eval.passes_threshold:
                    break

                strategy = get_strategy_name(attempt)
                weak_dim = best_eval.weakest_dimension
                display_weak = DIMENSION_LABELS.get(weak_dim, weak_dim.replace("_", " ").title())

                yield _sse({
                    "type": "improving",
                    "cycle": attempt + 1,
                    "strategy": strategy,
                    "weakest": display_weak,
                })

                try:
                    improved_ad, imp_usage = await asyncio.to_thread(
                        improve_ad,
                        ad=best_ad,
                        evaluation=best_eval,
                        brief=brief,
                        config=cfg,
                        attempt=attempt,
                    )
                except ValueError:
                    break

                total_gen_cost += imp_usage["cost_usd"]
                improved_data = _ad_fields(improved_ad)
                yield _sse({"type": "ad_copy", "ad": improved_data, "cycle": attempt + 1})

                improved_fields = _ad_fields(improved_ad)
                re_scores: dict[str, Any] = {}
                re_eval_cost = 0.0

                for i, dim_name in enumerate(dimension_names):
                    label = DIMENSION_LABELS.get(dim_name, dim_name.replace("_", " ").title())
                    yield _sse({
                        "type": "eval_start",
                        "dimension": dim_name,
                        "label": label,
                        "index": i + 1,
                        "total": len(dimension_names),
                        "cycle": attempt + 1,
                    })

                    score, usage = await asyncio.to_thread(
                        evaluate_dimension,
                        ad_fields=improved_fields,
                        dimension_name=dim_name,
                        rubric=rubrics[dim_name],
                        high_ref=high_ref,
                        low_ref=low_ref,
                    )
                    re_scores[dim_name] = score
                    re_eval_cost += usage["cost_usd"]

                    yield _sse({
                        "type": "eval_progress",
                        "dimension": dim_name,
                        "label": label,
                        "index": i + 1,
                        "total": len(dimension_names),
                        "score": {
                            "score": score.score,
                            "confidence": score.confidence,
                            "rationale": score.rationale,
                        },
                        "cycle": attempt + 1,
                    })

                total_eval_cost += re_eval_cost
                re_eval = AdEvaluation(**re_scores)
                cycle += 1

                if re_eval.aggregate_score > best_eval.aggregate_score:
                    best_ad = improved_ad
                    best_eval = re_eval
                    best_strategy = strategy

            text_record = AdRecord(
                ad_id=uuid.uuid4().hex[:12],
                brief=brief,
                generated_ad=best_ad,
                evaluation=best_eval,
                iteration_cycle=cycle,
                improved_from=initial_score if cycle > 1 else None,
                improvement_strategy=best_strategy,
                generation_cost_usd=total_gen_cost,
                evaluation_cost_usd=total_eval_cost,
                timestamp=datetime.utcnow(),
            )

            # ── Stage 2: Images ────────────────────────────────────────
            style_approaches = brief.style_approaches or (
                cfg.image_generation.style_approaches if cfg.image_generation else ["photorealistic", "ugc_style"]
            )
            variants_per_ad = cfg.image_generation.variants_per_ad if cfg.image_generation else 2
            styles = style_approaches[:variants_per_ad]
            total_styles = len(styles)

            yield _sse({"type": "image_generating", "message": f"Generating {total_styles} image variant(s)..."})

            image_variants: list[ImageVariant] = []
            image_gen_cost = 0.0
            image_eval_cost = 0.0

            for vi, style in enumerate(styles):
                yield _sse({
                    "type": "image_generating",
                    "message": f"Generating image variant {vi + 1}/{total_styles} ({style})...",
                })

                try:
                    gen_start = time.time()
                    image, meta = await asyncio.to_thread(
                        generate_ad_image, best_ad, brief, style, "feed_square", cfg,
                    )
                    gen_time = round(time.time() - gen_start, 2)

                    image_path = await asyncio.to_thread(
                        save_ad_image, image, text_record.ad_id, vi, style,
                    )
                    gen_cost = meta.get("cost_usd", 0.0)
                    image_gen_cost += gen_cost

                    vis_eval, vis_usage = await asyncio.to_thread(
                        evaluate_ad_image, image, best_ad, cfg,
                    )
                    ev_cost = vis_usage.get("cost_usd", 0.0)
                    image_eval_cost += ev_cost

                    variant = ImageVariant(
                        variant_id=f"{text_record.ad_id}_v{vi}_{style}",
                        style=style,
                        placement="feed_square",
                        image_path=image_path,
                        visual_evaluation=vis_eval,
                        generation_cost_usd=round(gen_cost, 6),
                        evaluation_cost_usd=round(ev_cost, 6),
                        generation_time_s=gen_time,
                    )
                    image_variants.append(variant)

                    image_url = f"/images/{Path(image_path).name}"

                    yield _sse({
                        "type": "image_variant",
                        "index": vi,
                        "total": total_styles,
                        "style": style,
                        "image_url": image_url,
                        "visual_evaluation": vis_eval.model_dump(mode="json"),
                    })
                except Exception as img_exc:
                    print(f"[generate-multimodal] Image variant {style} failed: {img_exc}")
                    yield _sse({
                        "type": "image_variant_error",
                        "index": vi,
                        "style": style,
                        "message": str(img_exc),
                    })

            if not image_variants:
                yield _sse({"type": "error", "message": "All image variants failed to generate."})
                return

            # ── Stage 3: Select winner & combine ───────────────────────
            winner = select_best_variant(image_variants, brief.campaign_goal)
            winner_idx = next(
                (i for i, v in enumerate(image_variants) if v.variant_id == winner.variant_id), 0
            )

            yield _sse({
                "type": "image_selected",
                "winning_index": winner_idx,
                "style": winner.style,
                "image_url": f"/images/{Path(winner.image_path).name}",
                "visual_aggregate_score": winner.visual_evaluation.visual_aggregate_score,
            })

            text_score = best_eval.aggregate_score
            visual_score = winner.visual_evaluation.visual_aggregate_score
            combined = round(_TEXT_WEIGHT * text_score + _VISUAL_WEIGHT * visual_score, 2)
            total_cost = round(
                total_gen_cost + total_eval_cost + image_gen_cost + image_eval_cost, 6
            )

            pipeline_time = round(time.time() - pipeline_start, 2)

            mm_record = MultiModalAdRecord(
                ad_id=text_record.ad_id,
                brief=brief,
                text_record=text_record,
                winning_variant=winner,
                all_variants=image_variants,
                combined_score=combined,
                total_cost_usd=total_cost,
                pipeline_time_s=pipeline_time,
                timestamp=datetime.utcnow(),
            )

            _append_multimodal_ad(mm_record)
            yield _sse({"type": "complete", "record": mm_record.model_dump(mode="json")})

        except Exception as exc:
            import traceback

            tb = traceback.format_exc()
            print(f"[generate_multimodal_endpoint] ERROR:\n{tb}")
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/multimodal-library")
def multimodal_library_endpoint(segment: str = "all", min_score: float = 0):
    try:
        records = load_multimodal_library()
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    if segment != "all":
        records = [r for r in records if r.brief.audience_segment == segment]
    records = [r for r in records if r.combined_score >= min_score]
    records.sort(key=lambda r: -r.combined_score)
    return [r.model_dump(mode="json") for r in records]


@app.get("/api/library")
def library_endpoint(segment: str = "all", min_score: float = 0):
    try:
        records = load_ad_library()
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    if segment != "all":
        records = [r for r in records if r.brief.audience_segment == segment]
    records = [r for r in records if r.evaluation.aggregate_score >= min_score]
    records.sort(key=lambda r: -r.evaluation.aggregate_score)
    return [r.model_dump(mode="json") for r in records]


_CSV_COLUMNS = [
    "ad_id", "segment", "goal", "tone", "offer", "headline",
    "primary_text", "description", "cta", "aggregate_score",
    "clarity", "value_proposition", "call_to_action",
    "brand_voice", "emotional_resonance", "cycle", "cost", "timestamp",
]
_CSV_COLUMNS_MM = _CSV_COLUMNS + [
    "combined_score", "visual_score", "winning_style", "image_filename",
]


def _ad_record_to_csv_row(r: dict) -> dict:
    brief = r.get("brief", {})
    ad = r.get("generated_ad", {})
    ev = r.get("evaluation", {})
    return {
        "ad_id": r.get("ad_id", ""),
        "segment": brief.get("audience_segment", ""),
        "goal": brief.get("campaign_goal", ""),
        "tone": brief.get("tone", ""),
        "offer": brief.get("specific_offer", ""),
        "headline": ad.get("headline", ""),
        "primary_text": ad.get("primary_text", ""),
        "description": ad.get("description", ""),
        "cta": ad.get("cta_button", ""),
        "aggregate_score": ev.get("aggregate_score", ""),
        "clarity": ev.get("clarity", {}).get("score", ""),
        "value_proposition": ev.get("value_proposition", {}).get("score", ""),
        "call_to_action": ev.get("call_to_action", {}).get("score", ""),
        "brand_voice": ev.get("brand_voice", {}).get("score", ""),
        "emotional_resonance": ev.get("emotional_resonance", {}).get("score", ""),
        "cycle": r.get("iteration_cycle", ""),
        "cost": round(r.get("generation_cost_usd", 0) + r.get("evaluation_cost_usd", 0), 4),
        "timestamp": r.get("timestamp", ""),
    }


def _mm_record_to_csv_row(r: dict) -> dict:
    tr = r.get("text_record", {})
    row = _ad_record_to_csv_row(tr)
    row["ad_id"] = r.get("ad_id", row["ad_id"])
    row["combined_score"] = r.get("combined_score", "")
    wv = r.get("winning_variant", {})
    vis_eval = wv.get("visual_evaluation", {})
    row["visual_score"] = vis_eval.get("visual_aggregate_score", "")
    row["winning_style"] = wv.get("style", "")
    img_path = wv.get("image_path", "")
    row["image_filename"] = Path(img_path).name if img_path else ""
    row["cost"] = round(r.get("total_cost_usd", 0), 4)
    return row


def _find_ad_in_libraries(ad_id: str) -> tuple[dict | None, bool]:
    for lib_name, is_mm in [("multimodal_ad_library.json", True), ("ad_library.json", False)]:
        lib_path = _ROOT / "data" / lib_name
        if not lib_path.exists():
            continue
        records = json.loads(lib_path.read_text())
        for rec in records:
            if rec.get("ad_id") == ad_id:
                return rec, is_mm
    return None, False


def _build_csv_bytes(records: list[dict], is_mm: bool) -> bytes:
    cols = _CSV_COLUMNS_MM if is_mm else _CSV_COLUMNS
    row_fn = _mm_record_to_csv_row if is_mm else _ad_record_to_csv_row
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for r in records:
        writer.writerow(row_fn(r))
    return buf.getvalue().encode()


def _build_zip(records: list[dict], is_mm: bool) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ads.json", json.dumps(records, indent=2, default=str))
        zf.writestr("ads.csv", _build_csv_bytes(records, is_mm).decode())
        if is_mm:
            added = set()
            for r in records:
                for v in r.get("all_variants", []):
                    img_path = v.get("image_path", "")
                    if not img_path:
                        continue
                    fname = Path(img_path).name
                    full = _ROOT / "data" / "images" / fname
                    if full.exists() and fname not in added:
                        zf.write(full, f"images/{fname}")
                        added.add(fname)
    return buf.getvalue()


@app.get("/api/download/ad/{ad_id}")
def download_ad(ad_id: str, format: str = "zip"):
    record, is_mm = _find_ad_in_libraries(ad_id)
    if record is None:
        return Response(content="Ad not found", status_code=404)

    if format == "json":
        return Response(
            content=json.dumps(record, indent=2, default=str),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="ad_{ad_id}.json"'},
        )
    elif format == "csv":
        return Response(
            content=_build_csv_bytes([record], is_mm),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="ad_{ad_id}.csv"'},
        )
    else:
        return Response(
            content=_build_zip([record], is_mm),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="ad_{ad_id}.zip"'},
        )


@app.get("/api/download/library")
def download_library(
    multimodal: bool = False,
    segment: str = "all",
    min_score: float = 0,
    format: str = "zip",
):
    if multimodal:
        lib_path = _ROOT / "data" / "multimodal_ad_library.json"
    else:
        lib_path = _ROOT / "data" / "ad_library.json"

    if not lib_path.exists():
        return Response(content="Library empty", status_code=404)

    records = json.loads(lib_path.read_text())

    if segment != "all":
        records = [r for r in records if r.get("brief", {}).get("audience_segment") == segment]

    if min_score > 0:
        if multimodal:
            records = [r for r in records if r.get("combined_score", 0) >= min_score]
        else:
            records = [r for r in records if r.get("evaluation", {}).get("aggregate_score", 0) >= min_score]

    if not records:
        return Response(content="No ads match filters", status_code=404)

    if format == "json":
        return Response(
            content=json.dumps(records, indent=2, default=str),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="ad_library.json"'},
        )
    elif format == "csv":
        return Response(
            content=_build_csv_bytes(records, multimodal),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="ad_library.csv"'},
        )
    else:
        return Response(
            content=_build_zip(records, multimodal),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="ad_library.zip"'},
        )


@app.get("/health")
def health():
    return {"status": "ok"}


# ── Helpers ───────────────────────────────────────────────────────────────


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, default=str)}\n\n"


def _batch_summary(records: list[AdRecord], errors: list[str]) -> dict:
    if not records:
        return {"total": 0, "errors": errors}

    n = len(records)
    scores = [r.evaluation.aggregate_score for r in records]
    passed = sum(1 for r in records if r.evaluation.passes_threshold)
    cost = sum(r.generation_cost_usd + r.evaluation_cost_usd for r in records)

    seg: dict[str, dict] = defaultdict(lambda: {"t": 0, "p": 0})
    for r in records:
        s = r.brief.audience_segment
        seg[s]["t"] += 1
        if r.evaluation.passes_threshold:
            seg[s]["p"] += 1

    dim = {
        d: round(sum(getattr(r.evaluation, d).score for r in records) / n, 2)
        for d in DIMENSIONS
    }

    return {
        "total": n,
        "passed": passed,
        "pass_rate": round(100 * passed / n),
        "avg_score": round(sum(scores) / n, 2),
        "min_score": round(min(scores), 2),
        "max_score": round(max(scores), 2),
        "total_cost": round(cost, 4),
        "cost_per_ad": round(cost / n, 4),
        "segments": {
            s: {"pass_rate": round(100 * v["p"] / v["t"]), "count": v["t"]}
            for s, v in sorted(seg.items())
        },
        "dimensions": dim,
        "errors": errors,
    }

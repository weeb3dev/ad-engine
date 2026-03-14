"""FastAPI web application for the Autonomous Ad Engine.

Single-process server: serves the HTML frontend, static assets,
and JSON API endpoints that wrap the existing pipeline.

Usage:
    uvicorn server:app --reload              # dev
    uvicorn server:app --host 0.0.0.0        # production
"""

import asyncio
import json
import time
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from config.loader import get_config
from evaluate.judge import evaluate_dimension, get_evaluation_context
from evaluate.visual.image_judge import evaluate_ad_image
from generate.ab_variants import select_best_variant
from generate.briefs import TONES, generate_brief_matrix, load_briefs
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
            "js_version": _APP_JS_VERSION,
            "config_json": json.dumps(
                {
                    "segments": segments,
                    "tones": TONES,
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

            yield _sse({"type": "complete", "record": record.model_dump(mode="json")})

        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            print(f"[generate_endpoint] ERROR:\n{tb}")
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(stream(), media_type="text/event-stream")


class BatchRequest(BaseModel):
    num_ads: int = 5


@app.post("/api/batch")
async def batch_endpoint(req: BatchRequest):
    async def stream():
        cfg = get_config()
        briefs_path = _ROOT / "data" / "briefs.json"
        briefs = load_briefs() if briefs_path.exists() else generate_brief_matrix(cfg)
        briefs = briefs[: req.num_ads]

        records: list[AdRecord] = []
        errors: list[str] = []

        for i, brief in enumerate(briefs):
            label = f"{brief.audience_segment}/{brief.campaign_goal}"
            yield _sse({"type": "progress", "current": i, "total": len(briefs), "label": label})

            try:
                record = await asyncio.to_thread(run_pipeline, brief, cfg)
                records.append(record)
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
            with open(lib_path, "w") as f:
                json.dump(
                    [r.model_dump(mode="json") for r in records],
                    f,
                    indent=2,
                    default=str,
                )

        yield _sse({"type": "complete", "summary": _batch_summary(records, errors)})

    return StreamingResponse(stream(), media_type="text/event-stream")


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

"""FastAPI web application for the Autonomous Ad Engine.

Single-process server: serves the HTML frontend, static assets,
and JSON API endpoints that wrap the existing pipeline.

Usage:
    uvicorn server:app --reload              # dev
    uvicorn server:app --host 0.0.0.0        # production
"""

import asyncio
import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from config.loader import get_config
from generate.briefs import TONES, generate_brief_matrix, load_briefs
from generate.models import AdBrief, AdRecord
from iterate.feedback import run_pipeline
from output.batch_runner import load_ad_library
from output.generate_report import DIMENSION_LABELS, SEGMENT_LABELS

_ROOT = Path(__file__).resolve().parent

DIMENSIONS = [
    "clarity",
    "value_proposition",
    "call_to_action",
    "brand_voice",
    "emotional_resonance",
]

for _d in ("data", "output", "static", "templates"):
    (_ROOT / _d).mkdir(exist_ok=True)

app = FastAPI(title="Autonomous Ad Engine")
app.mount("/static", StaticFiles(directory=str(_ROOT / "static")), name="static")
app.mount("/output", StaticFiles(directory=str(_ROOT / "output")), name="output")
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
            "config_json": json.dumps(
                {
                    "segments": segments,
                    "tones": TONES,
                    "dimensions": DIMENSIONS,
                    "dimension_labels": DIMENSION_LABELS,
                    "segment_labels": SEGMENT_LABELS,
                }
            ),
        },
    )


# ── API ───────────────────────────────────────────────────────────────────


@app.post("/api/generate")
def generate_endpoint(brief: AdBrief):
    record = run_pipeline(brief, get_config())
    return record.model_dump(mode="json")


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
    return f"data: {json.dumps(data)}\n\n"


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

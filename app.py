"""Gradio GUI for the Autonomous Ad Engine.

Three-tab interface: Generate | Batch | Library

Usage:
    python app.py              # local only
    python app.py --share      # public *.gradio.live URL (72 hrs)
"""

import argparse
import json
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import gradio as gr

from config.loader import get_config
from evaluate.judge import evaluate_dimension, get_evaluation_context
from generate.briefs import TONES, generate_brief_matrix, load_briefs
from generate.generator import generate_ad
from generate.models import AdBrief, AdEvaluation, AdRecord, GeneratedAd
from iterate.feedback import improve_ad, run_pipeline
from iterate.strategies import get_strategy_name
from output.batch_runner import load_ad_library
from output.generate_report import DIMENSION_LABELS, SEGMENT_LABELS
from output.visualize import DIMENSIONS, plot_dimension_radar, plot_quality_trends

_ROOT = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_ad_markdown(record: AdRecord) -> str:
    ad = record.generated_ad
    return (
        f"### {ad.headline}\n\n"
        f"{ad.primary_text}\n\n"
        f"**Description:** {ad.description}\n\n"
        f"**CTA:** `[ {ad.cta_button} ]`"
    )


def _scores_rows(record: AdRecord) -> list[list]:
    return [
        [
            DIMENSION_LABELS.get(d, d),
            getattr(record.evaluation, d).score,
            getattr(record.evaluation, d).confidence,
            getattr(record.evaluation, d).rationale,
        ]
        for d in DIMENSIONS
    ]


def _pipeline_info(record: AdRecord) -> str:
    cost = record.generation_cost_usd + record.evaluation_cost_usd
    parts = [f"**Cycles:** {record.iteration_cycle}"]
    if record.improved_from is not None:
        parts.append(f"**Improved from:** {record.improved_from:.2f}")
    if record.improvement_strategy:
        parts.append(f"**Strategy:** {record.improvement_strategy}")
    parts.append(f"**Cost:** ${cost:.4f}")
    return " | ".join(parts)


def _load_library() -> list[AdRecord]:
    try:
        return load_ad_library()
    except (FileNotFoundError, json.JSONDecodeError):
        return []


# ---------------------------------------------------------------------------
# Tab 1 — Generate single ad
# ---------------------------------------------------------------------------


def _ad_fields(ad: GeneratedAd) -> dict[str, str]:
    return {
        "primary_text": ad.primary_text,
        "headline": ad.headline,
        "description": ad.description,
        "cta_button": ad.cta_button,
    }


def _format_gen_ad_markdown(ad: GeneratedAd) -> str:
    return (
        f"### {ad.headline}\n\n"
        f"{ad.primary_text}\n\n"
        f"**Description:** {ad.description}\n\n"
        f"**CTA:** `[ {ad.cta_button} ]`"
    )


def _run_eval_streaming(
    ad: GeneratedAd,
    ad_md_text: str,
    rubrics: dict,
    high_ref: str,
    low_ref: str,
    dimension_names: list[str],
    status_prefix: str,
):
    """Evaluate an ad dimension-by-dimension, yielding UI updates after each.

    Yields (ad_md, score_num, scores_rows, radar_img, iter_md) tuples.
    Returns (scores_dict, total_usage) via the final state.
    """
    fields = _ad_fields(ad)
    scores: dict[str, Any] = {}
    total_usage: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    rows: list[list] = []

    for i, dim_name in enumerate(dimension_names):
        display = DIMENSION_LABELS.get(dim_name, dim_name.replace("_", " ").title())
        status = f"{status_prefix}Evaluating **{display}** ({i + 1}/{len(dimension_names)})..."
        yield (
            ad_md_text + f"\n\n---\n*{status}*",
            None,
            rows[:],
            None,
            f"*{status}*",
        ), None, None

        score, usage = evaluate_dimension(
            ad_fields=fields,
            dimension_name=dim_name,
            rubric=rubrics[dim_name],
            high_ref=high_ref,
            low_ref=low_ref,
        )
        scores[dim_name] = score
        total_usage["input_tokens"] += usage["input_tokens"]
        total_usage["output_tokens"] += usage["output_tokens"]
        total_usage["cost_usd"] += usage["cost_usd"]

        rows.append([display, score.score, score.confidence, score.rationale])

    evaluation = AdEvaluation(**scores)
    yield (
        ad_md_text,
        evaluation.aggregate_score,
        rows[:],
        None,
        f"*{status_prefix}Evaluation complete — **{evaluation.aggregate_score:.2f}***",
    ), evaluation, total_usage


def generate_single(segment, goal, tone, offer):
    """Streaming generator — yields (ad_md, score, scores_df, radar, info) at each stage."""
    try:
        brief = AdBrief(
            audience_segment=segment,
            campaign_goal=goal,
            tone=tone or None,
            specific_offer=offer or None,
        )
        config = get_config()
        max_attempts = config.quality.max_regeneration_attempts
        total_gen_cost = 0.0
        total_eval_cost = 0.0

        # --- Stage 1: Generate ---
        yield (
            "*Generating initial ad copy...*",
            None,
            [],
            None,
            "*Generating...*",
        )

        ad, gen_usage = generate_ad(brief, config)
        total_gen_cost += gen_usage["cost_usd"]
        ad_md_text = _format_gen_ad_markdown(ad)

        # --- Stage 2: Evaluate (per dimension) ---
        rubrics, high_ref, low_ref, dimension_names = get_evaluation_context()

        evaluation = None
        eval_usage: dict[str, Any] = {}
        for ui_tuple, eval_result, usage_result in _run_eval_streaming(
            ad, ad_md_text, rubrics, high_ref, low_ref, dimension_names, ""
        ):
            yield ui_tuple
            if eval_result is not None:
                evaluation = eval_result
                eval_usage = usage_result

        total_eval_cost += eval_usage["cost_usd"]
        initial_score = evaluation.aggregate_score

        best_ad = ad
        best_eval = evaluation
        best_strategy: str | None = None
        cycle = 1

        # --- Stage 3: Improvement loop ---
        for attempt in range(1, max_attempts + 1):
            if best_eval.passes_threshold:
                break

            strategy = get_strategy_name(attempt)
            display_weak = best_eval.weakest_dimension.replace("_", " ").title()
            yield (
                _format_gen_ad_markdown(best_ad),
                best_eval.aggregate_score,
                [
                    [DIMENSION_LABELS.get(d, d), getattr(best_eval, d).score,
                     getattr(best_eval, d).confidence, getattr(best_eval, d).rationale]
                    for d in DIMENSIONS
                ],
                None,
                f"*Improving — targeting **{display_weak}** (cycle {attempt + 1}, strategy: {strategy})...*",
            )

            try:
                improved_ad, imp_usage = improve_ad(
                    ad=best_ad,
                    evaluation=best_eval,
                    brief=brief,
                    config=config,
                    attempt=attempt,
                )
            except ValueError:
                break

            total_gen_cost += imp_usage["cost_usd"]
            improved_md = _format_gen_ad_markdown(improved_ad)

            re_eval = None
            re_usage: dict[str, Any] = {}
            for ui_tuple, eval_result, usage_result in _run_eval_streaming(
                improved_ad, improved_md, rubrics, high_ref, low_ref, dimension_names,
                f"Re-eval cycle {attempt + 1}: ",
            ):
                yield ui_tuple
                if eval_result is not None:
                    re_eval = eval_result
                    re_usage = usage_result

            total_eval_cost += re_usage["cost_usd"]
            cycle += 1

            if re_eval.aggregate_score > best_eval.aggregate_score:
                best_ad = improved_ad
                best_eval = re_eval
                best_strategy = strategy

        # --- Final result ---
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
        radar_path = plot_dimension_radar(record)
        yield (
            _format_ad_markdown(record),
            record.evaluation.aggregate_score,
            _scores_rows(record),
            str(radar_path),
            _pipeline_info(record),
        )

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        print(f"[generate_single] ERROR:\n{tb}")
        error_md = (
            f"## Pipeline Error\n\n```\n{exc}\n```\n\n"
            f"<details><summary>Full traceback</summary>\n\n```\n{tb}\n```\n</details>"
        )
        yield error_md, 0, [], None, f"**Error:** {exc}"


# ---------------------------------------------------------------------------
# Tab 2 — Batch generation with progress
# ---------------------------------------------------------------------------


def _batch_tables(records: list[AdRecord], errors: list[str]):
    """Build (summary_rows, seg_rows, dim_rows) from accumulated records."""
    n = len(records)
    if n == 0:
        return [], [], []

    scores = [r.evaluation.aggregate_score for r in records]
    passed = sum(1 for r in records if r.evaluation.passes_threshold)
    total_cost = sum(r.generation_cost_usd + r.evaluation_cost_usd for r in records)

    summary_rows = [
        ["Total Ads", str(n)],
        ["Pass Rate", f"{100 * passed / n:.0f}% ({passed}/{n})"],
        ["Avg Score", f"{sum(scores) / n:.2f}"],
        ["Score Range", f"{min(scores):.2f} – {max(scores):.2f}"],
        ["Total Cost", f"${total_cost:.4f}"],
        ["Cost / Ad", f"${total_cost / n:.4f}"],
    ]
    if errors:
        summary_rows.append(["Failed", f"{len(errors)} brief(s)"])

    seg_total: dict[str, int] = defaultdict(int)
    seg_passed: dict[str, int] = defaultdict(int)
    for r in records:
        seg = r.brief.audience_segment
        seg_total[seg] += 1
        if r.evaluation.passes_threshold:
            seg_passed[seg] += 1
    seg_rows = [
        [SEGMENT_LABELS.get(s, s), f"{seg_passed[s] / seg_total[s]:.0%}", str(seg_total[s])]
        for s in sorted(seg_total)
    ]

    dim_rows = [
        [
            DIMENSION_LABELS.get(d, d),
            f"{sum(getattr(r.evaluation, d).score for r in records) / n:.2f}",
        ]
        for d in DIMENSIONS
    ]
    return summary_rows, seg_rows, dim_rows


def run_batch_gui(num_ads):
    """Streaming generator — yields (status, summary, seg, dim, trends) after each ad."""
    try:
        cfg = get_config()

        briefs_path = _ROOT / "data" / "briefs.json"
        briefs = load_briefs() if briefs_path.exists() else generate_brief_matrix(cfg)
        briefs = briefs[: int(num_ads)]

        records: list[AdRecord] = []
        errors: list[str] = []

        for i, brief in enumerate(briefs):
            seg_label = SEGMENT_LABELS.get(brief.audience_segment, brief.audience_segment)
            status = (
                f"**Generating ad {i + 1}/{len(briefs)}** — "
                f"{seg_label} / {brief.campaign_goal}..."
            )
            summary, seg, dim = _batch_tables(records, errors)
            yield status, summary, seg, dim, None

            try:
                records.append(run_pipeline(brief, cfg))
            except Exception as exc:
                errors.append(f"Brief {i + 1}: {exc}")
                print(f"Pipeline failed for brief {i + 1}: {exc}")

        if not records:
            err_msg = errors[0] if errors else "unknown"
            yield (
                "**Batch failed** — no ads generated.",
                [["Status", "All ads failed"], ["Error", str(err_msg)]],
                [],
                [],
                None,
            )
            return

        # Persist results
        lib_path = _ROOT / "data" / "ad_library.json"
        lib_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lib_path, "w") as f:
            json.dump([r.model_dump(mode="json") for r in records], f, indent=2, default=str)

        try:
            trends_img = str(plot_quality_trends())
        except Exception:
            trends_img = None

        summary, seg, dim = _batch_tables(records, errors)
        n = len(records)
        passed = sum(1 for r in records if r.evaluation.passes_threshold)
        yield (
            f"**Done!** {n} ads generated — {passed}/{n} passed threshold.",
            summary,
            seg,
            dim,
            trends_img,
        )

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        print(f"[run_batch_gui] ERROR:\n{tb}")
        yield (
            f"**Error:** {exc}",
            [["Status", "Batch failed"], ["Error", str(exc)]],
            [],
            [],
            None,
        )


# ---------------------------------------------------------------------------
# Tab 3 — Library browser
# ---------------------------------------------------------------------------


def refresh_library(segment_filter, min_score):
    records = _load_library()
    if not records:
        return [], gr.Dropdown(choices=[], value=None)

    cfg = get_config()

    if segment_filter != "All":
        seg_id = next(
            (s.id for s in cfg.brand.audience_segments if s.label == segment_filter),
            segment_filter,
        )
        records = [r for r in records if r.brief.audience_segment == seg_id]

    records = [r for r in records if r.evaluation.aggregate_score >= min_score]
    records.sort(key=lambda r: -r.evaluation.aggregate_score)

    rows = [
        [
            r.ad_id[:8],
            SEGMENT_LABELS.get(r.brief.audience_segment, r.brief.audience_segment),
            r.brief.campaign_goal,
            r.generated_ad.headline[:50],
            f"{r.evaluation.aggregate_score:.2f}",
            str(r.iteration_cycle),
        ]
        for r in records
    ]

    ad_choices = [f"{r.ad_id[:8]} — {r.generated_ad.headline[:40]}" for r in records]
    return rows, gr.Dropdown(choices=ad_choices, value=ad_choices[0] if ad_choices else None)


def show_ad_detail(selection):
    if not selection:
        return "*Select an ad above to view details.*", None

    ad_prefix = selection.split(" — ")[0]
    records = _load_library()
    record = next((r for r in records if r.ad_id[:8] == ad_prefix), None)

    if not record:
        return "*Ad not found.*", None

    detail = _format_ad_markdown(record)
    detail += f"\n\n---\n\n**Aggregate Score: {record.evaluation.aggregate_score:.2f}**\n\n"

    detail += "| Dimension | Score | Confidence | Rationale |\n|---|---|---|---|\n"
    for d in DIMENSIONS:
        ds = getattr(record.evaluation, d)
        detail += f"| {DIMENSION_LABELS.get(d, d)} | {ds.score}/10 | {ds.confidence} | {ds.rationale} |\n"

    detail += f"\n{_pipeline_info(record)}"

    try:
        radar = str(plot_dimension_radar(record))
    except Exception:
        radar = None

    return detail, radar


# ---------------------------------------------------------------------------
# Build the Gradio app
# ---------------------------------------------------------------------------


def build_app() -> gr.Blocks:
    cfg = get_config()
    segment_choices = [(s.label, s.id) for s in cfg.brand.audience_segments]
    segment_labels = [s.label for s in cfg.brand.audience_segments]

    with gr.Blocks(title="Autonomous Ad Engine") as demo:
        gr.Markdown(
            "# Autonomous Ad Engine\n"
            "*Self-improving ad copy generation for Varsity Tutors SAT Prep*"
        )

        # ---- Tab 1: Generate ----
        with gr.Tab("Generate"):
            with gr.Row():
                with gr.Column(scale=1):
                    segment_dd = gr.Dropdown(
                        choices=segment_choices,
                        label="Audience Segment",
                        value=cfg.brand.audience_segments[0].id,
                        elem_id="gen-segment",
                    )
                    goal_radio = gr.Radio(
                        choices=["awareness", "conversion"],
                        label="Campaign Goal",
                        value="awareness",
                        elem_id="gen-goal",
                    )
                    tone_dd = gr.Dropdown(
                        choices=TONES,
                        label="Tone",
                        value=TONES[0],
                        allow_custom_value=True,
                        elem_id="gen-tone",
                    )
                    offer_txt = gr.Textbox(
                        label="Specific Offer",
                        placeholder="e.g., Free SAT practice test",
                        value="Free SAT practice test",
                        elem_id="gen-offer",
                    )
                    gen_btn = gr.Button("Generate Ad", variant="primary", size="lg")

                with gr.Column(scale=2):
                    ad_md = gr.Markdown(value="*Click 'Generate Ad' to create an ad.*")
                    with gr.Row():
                        score_num = gr.Number(label="Aggregate Score", precision=2, elem_id="gen-score")
                        iter_md = gr.Markdown()
                    scores_df = gr.Dataframe(
                        headers=["Dimension", "Score", "Confidence", "Rationale"],
                        label="Dimension Scores",
                    )
                    radar_img = gr.Image(label="Radar Chart", type="filepath")

            gen_btn.click(
                fn=generate_single,
                inputs=[segment_dd, goal_radio, tone_dd, offer_txt],
                outputs=[ad_md, score_num, scores_df, radar_img, iter_md],
            )

        # ---- Tab 2: Batch ----
        with gr.Tab("Batch"):
            with gr.Row():
                num_slider = gr.Slider(
                    minimum=1,
                    maximum=54,
                    step=1,
                    value=5,
                    label="Number of Ads",
                    elem_id="batch-num",
                )
                batch_btn = gr.Button("Run Batch", variant="primary", size="lg")

            batch_status = gr.Markdown(value="*Configure and click 'Run Batch' to start.*")
            batch_summary = gr.Dataframe(headers=["Metric", "Value"], label="Batch Summary")
            with gr.Row():
                batch_seg = gr.Dataframe(
                    headers=["Segment", "Pass Rate", "Count"],
                    label="Per-Segment Breakdown",
                )
                batch_dim = gr.Dataframe(
                    headers=["Dimension", "Avg Score"],
                    label="Per-Dimension Averages",
                )
            batch_trends = gr.Image(label="Quality Trends Dashboard", type="filepath")

            batch_btn.click(
                fn=run_batch_gui,
                inputs=[num_slider],
                outputs=[batch_status, batch_summary, batch_seg, batch_dim, batch_trends],
            )

        # ---- Tab 3: Library ----
        with gr.Tab("Library"):
            with gr.Row():
                lib_seg = gr.Dropdown(
                    choices=["All"] + segment_labels,
                    label="Segment Filter",
                    value="All",
                    elem_id="lib-segment",
                )
                lib_min = gr.Slider(
                    minimum=1.0,
                    maximum=10.0,
                    step=0.5,
                    value=1.0,
                    label="Minimum Score",
                    elem_id="lib-min-score",
                )
                lib_btn = gr.Button("Load / Filter", variant="secondary")

            lib_table = gr.Dataframe(
                headers=["ID", "Segment", "Goal", "Headline", "Score", "Cycles"],
                label="Ad Library",
                interactive=False,
            )

            ad_select = gr.Dropdown(label="Select Ad for Details", choices=[], interactive=True, elem_id="lib-ad-select")

            with gr.Row():
                detail_md = gr.Markdown(value="*Load the library, then select an ad.*")
                detail_radar = gr.Image(label="Radar Chart", type="filepath")

            lib_btn.click(
                fn=refresh_library,
                inputs=[lib_seg, lib_min],
                outputs=[lib_table, ad_select],
            )
            ad_select.change(
                fn=show_ad_detail,
                inputs=[ad_select],
                outputs=[detail_md, detail_radar],
            )

    return demo


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autonomous Ad Engine GUI")
    parser.add_argument("--share", action="store_true", help="Create a public gradio.live URL")
    args = parser.parse_args()

    demo = build_app()
    demo.launch(share=args.share, theme=gr.themes.Soft())

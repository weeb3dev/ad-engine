"""Gradio GUI for the Autonomous Ad Engine.

Three-tab interface: Generate | Batch | Library

Usage:
    python app.py              # local only
    python app.py --share      # public *.gradio.live URL (72 hrs)
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import gradio as gr

from config.loader import get_config
from generate.briefs import TONES, generate_brief_matrix, load_briefs
from generate.models import AdBrief, AdRecord
from iterate.feedback import run_pipeline
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


def generate_single(segment, goal, tone, offer):
    try:
        brief = AdBrief(
            audience_segment=segment,
            campaign_goal=goal,
            tone=tone or None,
            specific_offer=offer or None,
        )
        record = run_pipeline(brief, get_config())
        radar_path = plot_dimension_radar(record)
        return (
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
        error_md = f"## Pipeline Error\n\n```\n{exc}\n```\n\n<details><summary>Full traceback</summary>\n\n```\n{tb}\n```\n</details>"
        return error_md, 0, [], None, f"**Error:** {exc}"


# ---------------------------------------------------------------------------
# Tab 2 — Batch generation with progress
# ---------------------------------------------------------------------------


def run_batch_gui(num_ads, progress=gr.Progress()):
    try:
        cfg = get_config()

        briefs_path = _ROOT / "data" / "briefs.json"
        briefs = load_briefs() if briefs_path.exists() else generate_brief_matrix(cfg)
        briefs = briefs[: int(num_ads)]

        records: list[AdRecord] = []
        errors: list[str] = []
        for i, brief in enumerate(briefs):
            label = f"{brief.audience_segment}/{brief.campaign_goal}"
            progress((i, len(briefs)), desc=f"[{i + 1}/{len(briefs)}] {label}")
            try:
                records.append(run_pipeline(brief, cfg))
            except Exception as exc:
                errors.append(f"Brief {i + 1}: {exc}")
                print(f"Pipeline failed for brief {i + 1}: {exc}")

        if not records:
            err_msg = errors[0] if errors else "unknown"
            return (
                [["Status", "All ads failed"], ["Error", str(err_msg)]],
                [],
                [],
                None,
            )

        scores = [r.evaluation.aggregate_score for r in records]
        passed = sum(1 for r in records if r.evaluation.passes_threshold)
        total_cost = sum(r.generation_cost_usd + r.evaluation_cost_usd for r in records)
        n = len(records)

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

        # Persist results
        lib_path = _ROOT / "data" / "ad_library.json"
        lib_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lib_path, "w") as f:
            json.dump([r.model_dump(mode="json") for r in records], f, indent=2, default=str)

        try:
            trends_img = str(plot_quality_trends())
        except Exception:
            trends_img = None

        progress(1.0, desc="Done!")
        return summary_rows, seg_rows, dim_rows, trends_img

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        print(f"[run_batch_gui] ERROR:\n{tb}")
        return (
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
                outputs=[batch_summary, batch_seg, batch_dim, batch_trends],
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

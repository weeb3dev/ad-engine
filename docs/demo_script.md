# Demo Video Script — Autonomous Ad Engine

**Target runtime:** 3:30–4:30  
**Pace:** ~150 words/min (conversational, not rushed)

---

## 1. INTRO & HOOK (~20s)

> [SCREEN: Title card — "Autonomous Ad Engine" / your face or webcam]

For Varsity Tutors, I built an Autonomous Ad Engine. It's a self-improving ad copy pipeline that generates, evaluates, and iterates on Meta ads completely autonomously.

The idea is simple: you give it a brief, it writes an ad, scores it against five quality dimensions, identifies weaknesses, and fixes them — all without human intervention. And it does the whole thing for about four cents per ad.

---

## 2. WHO IT'S FOR & THE PROBLEM (~25s)

> [SCREEN: Stay on title card or cut to a slide: "The Problem"]

This is built for marketing and advertising teams — the people producing Facebook and Instagram ad copy at scale. Writing one good ad isn't hard. Writing fifty good ads across different audience segments and campaign goals, and knowing which ones are actually good? That's the hard part. Manual quality review doesn't scale, and without a calibrated judge, you're just vibes-checking your own work.

---

## 3. WHAT WE BUILT — ARCHITECTURE (~40s)

> [SCREEN: Show the README mermaid diagram or a slide of the pipeline flow]

The pipeline has four stages.

**Generate** — users feed a structured brief into Gemini and get back structured ad copy: headline, primary text, description, and a CTA button.

**Evaluate** — an LLM judge scores the ad independently on five dimensions: clarity, value proposition, call to action, brand voice, and emotional resonance. Each dimension has its own rubric, its own weight, and produces a 1-to-10 score with a written rationale.

**Improve** — if the aggregate score is below 7.0, the system identifies the weakest dimension and kicks off a targeted fix. It escalates through three tiers: first a focused reprompt citing the weak dimension, then few-shot injection with high-scoring examples, and finally a model escalation prompt. Most ads pass after one or two cycles.

**Observe** — every single LLM call is traced to Langfuse via OpenTelemetry, so we get full visibility into token counts, latency, and cost per call — with graceful degradation if Langfuse isn't configured.

---

## 4. LIVE DEMO — GENERATING ADS IN GRADIO (~60s)

> [SCREEN: Switch to the running Gradio app — Generate tab]

Here's the dashboard. We're on the Generate tab. I'll pick an audience segment — let's start with "Parents anxious about college admissions," set the campaign goal to awareness, tone to empathetic, and the offer is a free SAT practice test.

> [SCREEN: Click "Generate Ad" — wait for results to populate]

There's the generated ad — headline, primary text, description, CTA. Below that we get the aggregate score and a full breakdown table showing each dimension's score, confidence level, and the judge's written rationale for that score. And here's the radar chart visualizing the five dimensions.

You can see it took [X] improvement cycles and cost [X] cents total. Let me generate another one — this time for stressed students, conversion goal, urgent tone.

> [SCREEN: Change inputs, click Generate again, show new results]

Different segment, completely different copy, different score profile. The system adapts the messaging to the audience and the goal.

---

## 5. BATCH GENERATION & REPORTING (~30s)

> [SCREEN: Switch to the Batch tab in Gradio]

For production runs, there's the Batch tab — you set the number of ads with a slider and hit Run Batch. There's also a CLI command for headless runs: `python -m output.batch_runner`. We ran a full 53-ad batch across all three audience segments, both campaign goals, multiple tones and offers. The batch report script generates a full markdown report with an executive summary, per-segment pass rates, per-dimension averages, and every individual ad with its scores.

> [SCREEN: Flash the batch report markdown — output/batch1_ad_library.md — scroll through briefly]

53 ads, 100% pass rate, $2.35 total cost. That's four cents per ad including all evaluation and improvement cycles.

---

## 6. VISUALIZATIONS (~20s)

> [SCREEN: Show output/quality_trends.png — the 2x2 dashboard]

The visualization module produces this quality trends dashboard — score by iteration cycle, average score per dimension, pass rate by audience segment, and cost by iteration count. Each individual ad also gets its own radar chart showing its dimension profile at a glance.

---

## 7. TECH STACK & WHY GRADIO (~30s)

> [SCREEN: Slide or stay on dashboard — bullet list of stack]

Quick note on the stack. I went with **Gemini 3.1 Flash Lite** for both generation and evaluation. It's dramatically cheaper than Pro — I ran the whole 53-ad batch for $2.35 — and it passed judge calibration against hand-scored reference ads.

The entire pipeline is **Python** — Pydantic models, YAML config, clean module boundaries.

For the UI we chose **Gradio**. It wraps Python natively, zero frontend code, and the `--share` flag gives you a temporary public URL instantly. The whole three-tab dashboard is about 150 lines. It's the right tool when you want data and ML people to build something that marketing people can actually use.

Observability is **Langfuse plus OpenTelemetry** — auto-instrumentation captures every Gemini call without touching pipeline code.

---

## 8. KEY DECISIONS & HONEST LIMITATIONS (~25s)

> [SCREEN: Show docs/decision_log.md or a summary slide]

A few decisions worth calling out. I built the evaluator before the generator — you can't improve what you can't measure. I relaxed Meta's character limits and let the evaluator's clarity score handle length organically instead of hard validation. And I use the same cheap model for both generation and evaluation, which saved 10x on cost but introduces self-evaluation bias.

I documented the limitations honestly. The 100% pass rate is suspiciously high — the threshold or the judge is probably too lenient. Emotional resonance is consistently the weakest dimension at 6.51 average and doesn't improve much through iteration. These are real tradeoffs I made for v1.

---

## 9. NEXT STEPS — V2 (~20s)

> [SCREEN: Slide — "What's Next"]

For v2, three big things.

**Image generation** — pairing the ad copy with AI-generated creative so you get a complete ad unit, not just text.

**Model fallback and load balancing** — if Gemini rate-limits or goes down, automatic failover to a different provider. Claude Sonnet 4 from Anthropic is the top candidate here — it's a strong writer, and using a different model family for evaluation would also solve the self-evaluation bias problem we flagged in limitations.

And **stricter quality thresholds**, evaluation caching, and eventually A/B test integration to close the loop with real-world performance data.

---

## 10. OUTRO (~10s)

> [SCREEN: Return to title card or dashboard]

That's the Autonomous Ad Engine — generates, scores, and self-improves ad copy, all for under five cents per ad. Thanks for watching.

---

**Total word count:** ~780 words (~5:10 at 150 wpm — trim the live demo section based on how long the actual generation takes on screen, or speed up pace slightly to land at ~4:00)

**Trim notes if running long:**
- Section 8 (decisions/limitations) can be shortened to just self-evaluation bias + 100% pass rate
- Section 5 (batch) can skip the CLI mention
- Section 7 (tech stack) can drop the Langfuse detail

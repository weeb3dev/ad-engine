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

The whole thing streams to the browser over Server-Sent Events — the frontend sees each stage as it happens, not just the final result.

---

## 4. LIVE DEMO — GENERATING ADS (~60s)

> [SCREEN: Open the web app in the browser — Generate tab]

Here's the dashboard, deployed on Railway with a persistent URL. We're on the Generate tab. I'll pick an audience segment — let's start with "Parents anxious about college admissions," set the campaign goal to awareness, tone to empathetic, and the offer is a free SAT practice test.

> [SCREEN: Click "Generate Ad" — watch the streaming pipeline]

Notice the step indicator at the top — it tracks where we are in the pipeline: Generate, Evaluate, Improve, Done. The ad copy card appears immediately after generation, before any scores exist. Now watch the scores table — each dimension fills in one by one as the judge evaluates it. Clarity first, then value proposition, call to action, brand voice, emotional resonance. The radar chart builds incrementally too, adding a vertex with each score.

If the aggregate score lands below 7.0, the system kicks into an improvement cycle — you'll see the status update with the strategy name and cycle number, new ad copy streams in, and the scores re-evaluate live. No spinner, no waiting — you see every pipeline stage as it happens.

> [SCREEN: Change inputs, click Generate again, show new results]

Let me run another one — stressed students, conversion goal, urgent tone. Different segment, completely different copy, different score profile. The system adapts the messaging to the audience and the goal.

---

## 5. BATCH GENERATION & REPORTING (~30s)

> [SCREEN: Switch to the Batch tab]

For production runs, there's the Batch tab — you set the number of ads with a slider and hit Run Batch. The progress bar advances with each ad, but the real thing to watch is the live stat cards — pass count, average score, per-segment pass rates, and per-dimension averages all update progressively after each ad completes. You don't wait until the end to see how the batch is shaping up.

We ran a full 53-ad batch across all three audience segments, both campaign goals, multiple tones and offers.

> [SCREEN: Flash the batch report markdown — output/batch1_ad_library.md — scroll through briefly]

53 ads, 100% pass rate, $2.35 total cost. That's four cents per ad including all evaluation and improvement cycles.

---

## 6. VISUALIZATIONS (~20s)

> [SCREEN: Show output/quality_trends.png — the 2x2 dashboard]

The visualization module produces this quality trends dashboard — score by iteration cycle, average score per dimension, pass rate by audience segment, and cost by iteration count. Each individual ad also gets an interactive Chart.js radar chart showing its dimension profile at a glance — you can hover over points to see exact scores.

---

## 7. TECH STACK & DEPLOYMENT (~30s)

> [SCREEN: Slide or stay on dashboard — bullet list of stack]

Quick note on the stack. I went with **Gemini 3.1 Flash Lite** for both generation and evaluation. It's dramatically cheaper than Pro — I ran the whole 53-ad batch for $2.35 — and it passed judge calibration against hand-scored reference ads.

The entire pipeline is **Python** — Pydantic models, YAML config, clean module boundaries.

The frontend is **FastAPI** serving Jinja2 templates styled with **Tailwind CSS and DaisyUI**, with **Chart.js** for interactive radar charts — all loaded from CDN, zero build step. Both the generate and batch endpoints use **Server-Sent Events** — FastAPI's `StreamingResponse` pushes structured JSON events per pipeline stage, and a shared JS helper on the client parses and renders them incrementally. It's a single Python process, no separate frontend, no CORS. The app is deployed to **Railway**, so it has a persistent public URL — no tunneling, no temporary share links.

Observability is **Langfuse plus OpenTelemetry** — auto-instrumentation captures every Gemini call without touching pipeline code.

---

## 8. KEY DECISIONS & HONEST LIMITATIONS (~25s)

> [SCREEN: Show docs/decision_log.md or a summary slide]

A few decisions worth calling out. I built the evaluator before the generator — you can't improve what you can't measure. I relaxed Meta's character limits and let the evaluator's clarity score handle length organically instead of hard validation. And I use the same cheap model for both generation and evaluation, which saved 10x on cost but introduces self-evaluation bias.

I documented the limitations honestly. The 100% pass rate is suspiciously high — the threshold or the judge is probably too lenient. Emotional resonance is consistently the weakest dimension at 6.51 average and doesn't improve much through iteration. These are real tradeoffs I made for v1.

---

## 9. NEXT STEPS — V2 (~20s)

> [SCREEN: Slide — "What's Next"]

For v2, two big things.

**Image generation** — pairing the ad copy with AI-generated creative so you get a complete ad unit, not just text.

**Model fallback and load balancing** — if Gemini rate-limits or goes down, automatic failover to a different provider. Claude Sonnet 4 from Anthropic is the top candidate here — it's a strong writer, and using a different model family for evaluation would also solve the self-evaluation bias problem we flagged in limitations.

Beyond that — stricter quality thresholds, evaluation caching, and eventually A/B test integration to close the loop with real-world performance data.

---

## 10. OUTRO (~10s)

> [SCREEN: Return to title card or dashboard]

That's the Autonomous Ad Engine — generates, scores, and self-improves ad copy, all for under five cents per ad. Thanks for watching.

---

**Total word count:** ~830 words (~5:30 at 150 wpm — the streaming demo section runs longer on screen because you're narrating what's happening in real time; trim architecture or tech stack if you need to land at ~4:00)

**Trim notes if running long:**
- Section 8 (decisions/limitations) can be shortened to just self-evaluation bias + 100% pass rate
- Section 7 (tech stack) can drop the SSE implementation detail and Railway mention
- Section 3 (architecture) can cut the SSE streaming sentence at the end

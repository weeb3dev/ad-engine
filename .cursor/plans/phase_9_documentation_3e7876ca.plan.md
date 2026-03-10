---
name: Phase 9 Documentation
overview: "Create the three documentation deliverables for Phase 9: a decision log (docs/decision_log.md), a limitations doc (docs/limitations.md), and a project README.md -- all grounded in actual project data and implementation details."
todos:
  - id: decision-log
    content: Create docs/decision_log.md with 7+ filled-in entries based on actual project data and implementation decisions
    status: completed
  - id: limitations
    content: Create docs/limitations.md customized with real batch data observations (score clustering, pass rate, weakest dimensions)
    status: completed
  - id: readme
    content: Create README.md with quick start, architecture diagram, project structure, entry points, batch results, and cost estimate
    status: completed
isProject: false
---

# Phase 9: Document -- Decision Log & README

## What We're Creating

Three files, none of which exist yet. The `docs/` directory is empty and there is no `README.md` at the project root.

## 1. Decision Log (`docs/decision_log.md`)

The build guide provides a skeleton with three starter entries. We'll flesh those out with **real data** from the project, then add additional entries reflecting actual decisions visible in the code:

**Entries to include (with real context):**

- **Build evaluator before generator** -- per PRD philosophy. Outcome: calibration passed 8/8 on first run.
- **Dimension weighting** -- chose the PRD's custom weights (clarity 0.25, value_prop 0.25, CTA 0.20, brand 0.15, emotional 0.15) over equal 20%. Outcome: batch avg 7.59, weakest dim is emotional_resonance (6.51 avg) -- the lowest-weighted dimensions pull the aggregate less.
- **Single model for gen + eval** -- the config shows `gemini-3.1-flash-lite-preview` for both generator and evaluator (deviates from the build guide's suggestion of Pro for eval). This was a cost/speed decision. Outcome: 53 ads for ~$2.35 total, 100% pass rate.
- **Relaxed character limits** -- `headline` max was raised from 40 to 80, `primary_text` from 300 to 1000, `description` from 125 to 200 (per Phase 8 plan notes). Rationale: the model frequently exceeded strict limits; relaxing them avoided constant validation failures while still staying within Meta's truncation thresholds.
- **Improvement strategy escalation** -- three tiers: targeted reprompt, few-shot injection, model escalation (placeholder). Avg iterations was 2.23, meaning most ads needed 1-2 improvement cycles.
- **Langfuse observability via OpenTelemetry** -- chose OTLP exporter + `@observe` decorator pattern over manual Langfuse SDK calls. Graceful degradation if keys aren't set.
- **Cost model** -- hardcoded $1.25/1M input, $10/1M output in `feedback.py` and `generator.py`. Simple but effective for tracking ($0.044/ad).

Each entry follows the template: Date, Context, Options, Decision, Rationale, Outcome.

## 2. Limitations Doc (`docs/limitations.md`)

The build guide provides a solid skeleton. We'll customize it with project-specific observations from actual batch data:

- Evaluation clustering: per-dimension averages range 6.51-8.42 (not full 1-10 range)
- 100% pass rate suggests threshold may be too lenient or the judge too generous
- emotional_resonance (6.51) and call_to_action (6.98) consistently score lowest
- No caching of evaluations
- No visualization pipeline yet (Phase 10)
- Single model family (Gemini) for both gen and eval = potential self-evaluation bias
- Fill in the "What I'd Do Differently" section

## 3. README.md (project root)

Per the build guide spec -- concise, developer-oriented:

- **Title + one-liner**
- **Quick Start** -- 5 commands: clone, venv, pip install, cp .env.example, run batch
- **Architecture** -- 4-stage pipeline diagram (generate -> evaluate -> improve -> observe) using a mermaid flowchart
- **How It Works** -- brief explanation of the feedback loop
- **Project Structure** -- directory tree matching actual files
- **Configuration** -- pointer to `config/config.yaml`, brief on dimensions/weights/threshold
- **Entry Points** -- the 4 runnable modules: `batch_runner`, `generate_report`, `briefs`, `calibration`
- **Running Tests** -- `pytest tests/ -v` (15+ tests)
- **Key Design Decisions** -- link to `docs/decision_log.md`
- **Batch Results** -- actual numbers from `data/batch_summary.json` (53 ads, 100% pass, $2.35 total)
- **Limitations** -- link to `docs/limitations.md`
- **Cost Estimate** -- ~$0.044/ad, ~$2.35 for a 53-ad batch

## Files Changed


| File                                         | Action |
| -------------------------------------------- | ------ |
| [docs/decision_log.md](docs/decision_log.md) | Create |
| [docs/limitations.md](docs/limitations.md)   | Create |
| [README.md](README.md)                       | Create |


No code changes. No dependencies. Pure documentation.
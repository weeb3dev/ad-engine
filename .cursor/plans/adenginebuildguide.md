# Autonomous Ad Engine — Step-by-Step Build Guide

**A junior-developer-friendly walkthrough for building the entire system end to end.**

This guide walks you through building the Autonomous Ad Copy Generation System from scratch. Each phase has terminal commands to run, files to create, and **Cursor AI prompts** you can paste directly into Cursor's chat or composer to generate code. The phases are designed to be completed in order — each one builds on the last.

> **Prerequisites:** Python 3.11+, a Google AI Studio account (ai.google.dev), a Langfuse account (langfuse.com — free cloud tier works), and Cursor IDE installed.

> **Time estimate:** v1 can be built in 1–2 days. Don't skip the study and calibration steps — they're the foundation everything else depends on.

---

## Table of Contents

1. [Phase 0: Project Setup & Environment](#phase-0-project-setup--environment)
2. [Phase 1: Study — Research & Competitive Intelligence](#phase-1-study--research--competitive-intelligence)
3. [Phase 2: Define — Data Models & Configuration](#phase-2-define--data-models--configuration)
4. [Phase 3: Evaluate — Build the Judge First](#phase-3-evaluate--build-the-judge-first)
5. [Phase 4: Generate — Ad Copy Pipeline](#phase-4-generate--ad-copy-pipeline)
6. [Phase 5: Iterate — The Feedback Loop](#phase-5-iterate--the-feedback-loop)
7. [Phase 6: Observe — Langfuse Integration](#phase-6-observe--langfuse-integration)
8. [Phase 7: Scale — Batch Generation & Quality Trends](#phase-7-scale--batch-generation--quality-trends)
9. [Phase 8: Test — Unit & Integration Tests](#phase-8-test--unit--integration-tests)
10. [Phase 9: Document — Decision Log & README](#phase-9-document--decision-log--readme)
11. [Phase 10: Visualize — Quality Trends & Dashboards](#phase-10-visualize--quality-trends--dashboards)
12. [Tips for Working with Cursor](#tips-for-working-with-cursor)

---

## Phase 0: Project Setup & Environment

**Goal:** Get a clean project structure, virtual environment, and all dependencies installed before writing any application code.

### Terminal Commands

```bash
# Create project directory and enter it
mkdir ad-engine && cd ad-engine

# Initialize git
git init

# Create the full directory structure
mkdir -p generate/prompts evaluate iterate compete/references output config tests docs data

# Create empty __init__.py files so Python treats folders as packages
touch generate/__init__.py evaluate/__init__.py iterate/__init__.py output/__init__.py

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Create requirements.txt
cat > requirements.txt << 'EOF'
google-genai>=1.0.0
pydantic>=2.0
pyyaml>=6.0
langfuse>=3.0.0
openinference-instrumentation-google-genai>=0.1.0
matplotlib>=3.8
plotly>=5.18
pytest>=8.0
pytest-asyncio>=0.23
python-dotenv>=1.0
rich>=13.0
EOF

# Install dependencies
pip install -r requirements.txt

# Create .env file for API keys (NEVER commit this)
cat > .env << 'EOF'
GOOGLE_API_KEY=your-gemini-api-key-here
LANGFUSE_PUBLIC_KEY=your-langfuse-public-key
LANGFUSE_SECRET_KEY=your-langfuse-secret-key
LANGFUSE_BASE_URL=https://cloud.langfuse.com
EOF

# Create .gitignore
cat > .gitignore << 'EOF'
.venv/
.env
__pycache__/
*.pyc
data/*.db
data/*.json
.DS_Store
EOF
```

### How to Get Your API Keys

1. **Gemini API Key:** Go to [ai.google.dev](https://ai.google.dev), sign in, click "Get API Key", create a key in a new project. Copy it into your `.env` file.
2. **Langfuse Keys:** Go to [langfuse.com](https://langfuse.com), sign up for free cloud, create a new project, go to Settings → API Keys, and copy the public key, secret key, and host URL into `.env`.

### Verify Setup

```bash
# Quick test that your Gemini key works
python3 -c "
from google import genai
import os
from dotenv import load_dotenv
load_dotenv()
client = genai.Client(api_key=os.getenv('GOOGLE_API_KEY'))
response = client.models.generate_content(
    model='gemini-3-flash-preview',
    contents='Say hello in exactly 5 words.'
)
print(response.text)
print('Setup verified!')
"
```

If you see a response and "Setup verified!", you're good to go.

---

## Phase 1: Study — Research & Competitive Intelligence

**Goal:** Before writing any generation or evaluation code, understand what "good" looks like. This phase is manual and critical.

### Step 1.1: Collect Reference Ads from Slack

Go to the Gauntlet/Nerdy Slack channel and download all reference ads and performance data provided. Save them to `compete/references/`.

```bash
# Create a file to catalog what you find
cat > compete/references/README.md << 'EOF'
# Reference Ad Catalog

## Instructions
Save reference ads from the Gauntlet/Nerdy Slack channel here.
For each ad, note:
- Primary text, headline, description, CTA
- Performance context (if provided)
- Your personal score (1-10) on each of the 5 dimensions
- What makes it good or bad

## Ads Cataloged
(Add entries as you review them)
EOF
```

### Step 1.2: Manual Competitor Research

Open [facebook.com/ads/library](https://facebook.com/ads/library) in your browser and search for each competitor. You cannot automate this for US ads (the API only covers EU/political ads), so do it manually.

```bash
# Create a spreadsheet-style markdown file to track your findings
cat > compete/references/competitor_patterns.md << 'EOF'
# Competitor Ad Patterns

## How to Use This File
Search each competitor on facebook.com/ads/library.
Focus on ads that have been running 60+ days (likely winners).
Document the patterns you see below.

## Princeton Review
- Hooks used:
- CTAs used:
- Emotional angles:
- Specific numbers/claims:

## Kaplan
- Hooks used:
- CTAs used:
- Emotional angles:
- Specific numbers/claims:

## Khan Academy
- Hooks used:
- CTAs used:
- Emotional angles:
- Specific numbers/claims:

## Chegg
- Hooks used:
- CTAs used:
- Emotional angles:
- Specific numbers/claims:

## Cross-Competitor Patterns
- Most common hook type:
- Most common CTA:
- Recurring emotional angle:
- What's MISSING (opportunity for VT):
EOF
```

### Step 1.3: Create Your Calibration Dataset

After reviewing reference ads, create a JSON file with 5–10 ads you've manually scored. This becomes the ground truth for calibrating your evaluator in Phase 3.

#### Cursor Prompt

> **Paste this into Cursor chat:**
>
> ```
> Create a file at `compete/references/calibration_ads.json` containing a JSON array of 8 example SAT test prep ads for Varsity Tutors. Include a mix of quality levels:
>
> - 3 high-quality ads (you'd expect scores of 8-10) with strong hooks, specific numbers, clear CTAs
> - 3 medium-quality ads (scores of 5-7) that are decent but generic or missing emotional resonance
> - 2 low-quality ads (scores of 2-4) that are vague, off-brand, or have weak/missing CTAs
>
> Each ad object should have: primary_text, headline, description, cta_button, expected_quality (high/medium/low), and notes explaining why it's that quality level.
>
> Base the high-quality ones on these patterns from real Meta ads:
> - Question hooks: "Is your child's SAT score holding them back?"
> - Stat hooks: "Students who prep score 200+ points higher"
> - Story hooks: "My daughter went from 1050 to 1400 in 8 weeks"
> - Specific numbers > vague promises
> - Free trial CTAs > paid commitment CTAs
>
> Brand voice for Varsity Tutors: Empowering, knowledgeable, approachable, results-focused. Lead with outcomes, not features.
> ```

---

## Phase 2: Define — Data Models & Configuration

**Goal:** Define all data structures, configuration files, and the quality dimension rubrics before writing any pipeline logic.

### Step 2.1: Configuration File

```bash
# Create the main config
cat > config/config.yaml << 'EOF'
# Autonomous Ad Engine Configuration

models:
  generator: "gemini-3.1-pro-preview"
  evaluator: "gemini-3.1-pro-preview"

quality:
  threshold: 7.0
  max_regeneration_attempts: 3

dimensions:
  clarity:
    weight: 0.25
    description: "Is the message immediately understandable in under 3 seconds?"
    score_1: "Confusing, multiple messages competing for attention"
    score_10: "Crystal clear single takeaway"
  value_proposition:
    weight: 0.25
    description: "Does it communicate a compelling, specific benefit?"
    score_1: "Generic, feature-focused (e.g., 'we have tutors')"
    score_10: "Specific, differentiated benefit (e.g., 'raise your SAT score 200+ points')"
  call_to_action:
    weight: 0.20
    description: "Is the next step clear, compelling, and low-friction?"
    score_1: "No CTA or vague ('learn more')"
    score_10: "Specific, urgent, low-friction ('Start your free practice test')"
  brand_voice:
    weight: 0.15
    description: "Does it sound like Varsity Tutors?"
    score_1: "Generic, could be any brand"
    score_10: "Distinctly empowering, knowledgeable, approachable"
  emotional_resonance:
    weight: 0.15
    description: "Does it connect with real emotional motivation?"
    score_1: "Flat, purely rational"
    score_10: "Taps into parent worry, student ambition, or test anxiety"

brand:
  name: "Varsity Tutors"
  parent_company: "Nerdy"
  voice: "Empowering, knowledgeable, approachable, results-focused"
  guidelines:
    - "Lead with outcomes, not features"
    - "Confident but not arrogant"
    - "Expert but not elitist"
    - "Meet people where they are"
  audience_segments:
    - id: "anxious_parents"
      label: "Parents anxious about college admissions"
    - id: "stressed_students"
      label: "High school students stressed about SAT scores"
    - id: "comparison_shoppers"
      label: "Families comparing prep options (Princeton Review, Kaplan, Khan Academy)"

seed: 42  # For reproducibility
EOF
```

### Step 2.2: Pydantic Data Models

#### Cursor Prompt

> **Paste this into Cursor chat:**
>
> ```
> Read the config file at config/config.yaml and the PRD at Autonomous_Ad_Engine_PRD.md (if available in context, otherwise use the information I describe below).
>
> Create a file at `generate/models.py` with Pydantic v2 models for the entire system:
>
> 1. `AdBrief` — input to the generator. Fields: audience_segment (str), product (str, default "sat_prep"), campaign_goal (Literal["awareness", "conversion"]), tone (optional str), specific_offer (optional str)
>
> 2. `GeneratedAd` — output of generator. Fields: primary_text (str, max 300 chars), headline (str, max 40 chars), description (str, max 125 chars), cta_button (Literal["Learn More", "Sign Up", "Get Started", "Book Now", "Try Free"])
>
> 3. `DimensionScore` — single dimension evaluation. Fields: score (int, 1-10), rationale (str), confidence (Literal["low", "medium", "high"])
>
> 4. `AdEvaluation` — full evaluation. Fields: clarity (DimensionScore), value_proposition (DimensionScore), call_to_action (DimensionScore), brand_voice (DimensionScore), emotional_resonance (DimensionScore), aggregate_score (float, computed), passes_threshold (bool, computed), weakest_dimension (str, computed)
>
> 5. `AdRecord` — complete ad record for the library. Fields: ad_id (str), brief (AdBrief), generated_ad (GeneratedAd), evaluation (AdEvaluation), iteration_cycle (int), improved_from (optional float), improvement_strategy (optional str), generation_cost_usd (float), evaluation_cost_usd (float), timestamp (datetime)
>
> 6. `Config` — loaded from YAML. Fields match the config.yaml structure above.
>
> Use Pydantic computed fields for aggregate_score (weighted average using dimension weights from config), passes_threshold, and weakest_dimension. Add a classmethod `from_yaml` on Config that loads from a YAML file path.
>
> Include docstrings explaining each model. Add input validation (e.g., headline max 40 chars, scores 1-10).
> ```

### Step 2.3: Config Loader

#### Cursor Prompt

> **Paste this into Cursor chat:**
>
> ```
> Create a file at `config/loader.py` that:
>
> 1. Loads config/config.yaml using PyYAML
> 2. Validates it against the Config Pydantic model from generate/models.py
> 3. Loads environment variables from .env using python-dotenv
> 4. Exposes a singleton `get_config()` function that caches the loaded config
> 5. Exposes a `get_gemini_client()` function that returns a configured google.genai.Client
>
> Handle errors gracefully — if config.yaml is missing or malformed, print a helpful error message telling the developer what went wrong and how to fix it.
> ```

---

## Phase 3: Evaluate — Build the Judge First

**Goal:** Build the evaluator BEFORE the generator. This is counterintuitive but critical — if you can't measure quality, you can't improve it.

### Step 3.1: Dimension Definitions

#### Cursor Prompt

> **Paste this into Cursor chat:**
>
> ```
> Create a file at `evaluate/dimensions.py` that:
>
> 1. Reads the 5 dimension definitions from config.yaml (clarity, value_proposition, call_to_action, brand_voice, emotional_resonance)
> 2. For each dimension, builds a detailed scoring rubric string that will be injected into the LLM judge prompt. The rubric should include:
>    - What the dimension measures
>    - What a score of 1 looks like (with an example)
>    - What a score of 5 looks like (with an example)
>    - What a score of 10 looks like (with an example)
>    - Common mistakes that lead to low scores
> 3. Exports a function `get_rubric(dimension_name: str) -> str` that returns the full rubric text
> 4. Exports a function `get_all_rubrics() -> dict[str, str]` that returns all rubrics
>
> The rubrics should be specific to Varsity Tutors SAT prep ads. For example, the brand_voice rubric should reference the specific brand voice guidelines: empowering, knowledgeable, approachable, results-focused.
> ```

### Step 3.2: Evaluation Prompt Template

```bash
# Create the evaluation prompt template
cat > evaluate/prompts/judge_prompt.yaml << 'EOF'
system: |
  You are an expert advertising copywriter and creative director specializing in
  Facebook and Instagram paid social ads for the EdTech industry. You are evaluating
  ad copy for Varsity Tutors, a tutoring platform that offers personalized SAT test prep.

  Brand voice: Empowering, knowledgeable, approachable, results-focused.
  - Lead with outcomes, not features
  - Confident but not arrogant
  - Expert but not elitist
  - Meet people where they are

  You will evaluate a single ad on ONE specific quality dimension.
  Think step-by-step before assigning your score.

  SCORING RULES:
  - Use the full 1-10 scale. Do not cluster around 6-8.
  - A score of 5 means "mediocre — not terrible, not good."
  - A score of 7 means "publishable quality — meets the bar."
  - A score of 9-10 means "exceptional — top 5% of ads you've seen."
  - Provide 2-3 sentences of rationale explaining your score.
  - State your confidence: low (you could see this going +/- 2 points),
    medium (+/- 1 point), high (confident in this score).

user: |
  ## Ad Copy to Evaluate

  **Primary Text:** {primary_text}
  **Headline:** {headline}
  **Description:** {description}
  **CTA Button:** {cta_button}

  ## Dimension: {dimension_name}

  {dimension_rubric}

  ## Reference Ads for Calibration

  HIGH-SCORING EXAMPLE (8-10 range):
  {high_reference}

  LOW-SCORING EXAMPLE (2-4 range):
  {low_reference}

  ## Your Evaluation

  Think step-by-step about this ad's {dimension_name}, then provide your evaluation.

  Respond with ONLY a JSON object in this exact format:
  {{
    "thinking": "your step-by-step reasoning here",
    "score": <integer 1-10>,
    "rationale": "2-3 sentence explanation",
    "confidence": "low" | "medium" | "high"
  }}
EOF
```

### Step 3.3: The Judge Module

#### Cursor Prompt

> **Paste this into Cursor chat:**
>
> ```
> Read the evaluation prompt template at evaluate/prompts/judge_prompt.yaml and the models at generate/models.py.
>
> Create a file at `evaluate/judge.py` that implements the LLM-as-judge evaluation:
>
> 1. A function `evaluate_dimension(ad: GeneratedAd, dimension_name: str, rubric: str, high_ref: str, low_ref: str) -> DimensionScore` that:
>    - Loads the prompt template from YAML
>    - Fills in the template variables (primary_text, headline, etc.)
>    - Calls Gemini 3.1 Pro (gemini-3.1-pro-preview) with temperature=0 for deterministic scoring
>    - Parses the JSON response into a DimensionScore
>    - Handles errors: if the model returns invalid JSON, retry once, then return a DimensionScore with score=5, rationale="Evaluation failed — parse error", confidence="low"
>    - Returns token usage (input_tokens, output_tokens) alongside the score for cost tracking
>
> 2. A function `evaluate_ad(ad: GeneratedAd, config: Config) -> AdEvaluation` that:
>    - Calls evaluate_dimension for each of the 5 dimensions
>    - Loads rubrics from dimensions.py
>    - Loads high/low reference ads from compete/references/calibration_ads.json
>    - Assembles the full AdEvaluation with computed aggregate_score, passes_threshold, and weakest_dimension
>    - Prints a formatted summary using the `rich` library showing each dimension score
>
> Use the google.genai Client. Import the config loader from config/loader.py.
> Add detailed logging (print statements are fine for v1) showing which dimension is being evaluated and the score received.
> ```

### Step 3.4: Calibration Script

#### Cursor Prompt

> **Paste this into Cursor chat:**
>
> ```
> Create a file at `evaluate/calibration.py` that:
>
> 1. Loads all ads from compete/references/calibration_ads.json
> 2. Runs each ad through evaluate_ad() from judge.py
> 3. Compares the evaluator's aggregate scores against the expected quality levels:
>    - "high" quality ads should score 7.5+ (ideally 8-10)
>    - "medium" quality ads should score 4.5-7.5
>    - "low" quality ads should score below 5.0
> 4. Prints a calibration report showing:
>    - Each ad's expected vs actual scores
>    - Whether calibration PASSED or FAILED
>    - Which dimensions seem miscalibrated
> 5. Saves the calibration results to data/calibration_results.json
>
> Make it runnable as a script: `python -m evaluate.calibration`
>
> If calibration fails, print specific suggestions for how to fix it (e.g., "The evaluator is scoring low-quality ads too high on brand_voice — consider adding more negative examples to the rubric").
> ```

### Run Calibration

```bash
# Run calibration — this is the most important step in the entire project
python -m evaluate.calibration

# Expected output: a report showing whether your evaluator can distinguish
# good ads from bad ads. If it can't, fix your prompts before proceeding.
```

> **Decision Log Entry:** After running calibration, open `docs/decision_log.md` and write down: what scores did your evaluator give? Did it pass calibration? If not, what did you change in the prompts to fix it? This is the kind of honest documentation the evaluators want to see.

---

## Phase 4: Generate — Ad Copy Pipeline

**Goal:** Build the ad copy generator. This is simpler than the evaluator because the evaluator already tells us what "good" looks like.

### Step 4.1: Generation Prompt Templates

```bash
cat > generate/prompts/generator_prompt.yaml << 'EOF'
system: |
  You are an expert direct-response copywriter specializing in Facebook and Instagram
  ads for Varsity Tutors, a personalized SAT test prep platform.

  BRAND VOICE:
  - Empowering, knowledgeable, approachable, results-focused
  - Lead with outcomes, not features
  - Confident but not arrogant. Expert but not elitist.
  - Meet people where they are

  AD FORMAT (Facebook/Instagram):
  - Primary Text: The main copy above the image. First line must hook the reader.
    Keep under 125 characters for full visibility (can go longer but it gets truncated).
  - Headline: Bold text below the image. 5-8 words max. Benefit-driven.
  - Description: Secondary text below headline. Social proof or urgency. Often truncated on mobile.
  - CTA Button: One of: "Learn More", "Sign Up", "Get Started", "Book Now", "Try Free"

  WHAT WORKS ON META:
  - Specific numbers > vague promises ("200+ point improvement" beats "better scores")
  - Social proof (reviews, ratings, student counts) > brand claims
  - Free trial CTAs > paid commitment CTAs for cold audiences
  - Authentic, UGC-style copy > polished corporate messaging
  - Story-driven > feature-list

user: |
  Generate a Facebook/Instagram ad for Varsity Tutors SAT prep.

  BRIEF:
  - Audience: {audience_description}
  - Campaign Goal: {campaign_goal}
  - Tone: {tone}
  - Specific Offer: {specific_offer}

  HOOK STYLE TO USE: {hook_style}

  {few_shot_examples}

  Respond with ONLY a JSON object:
  {{
    "primary_text": "your primary text here",
    "headline": "your headline here",
    "description": "your description here",
    "cta_button": "one of the allowed CTA options"
  }}
EOF
```

### Step 4.2: Generator Module

#### Cursor Prompt

> **Paste this into Cursor chat:**
>
> ```
> Read the generation prompt at generate/prompts/generator_prompt.yaml and models at generate/models.py.
>
> Create a file at `generate/generator.py` that implements ad copy generation:
>
> 1. A function `generate_ad(brief: AdBrief, config: Config, hook_style: str = "question", few_shot_examples: str = "") -> tuple[GeneratedAd, dict]` that:
>    - Loads the prompt template from YAML
>    - Maps the brief's audience_segment to a human-readable description using config
>    - Fills in all template variables
>    - Calls Gemini 3.1 Pro (gemini-3.1-pro-preview) with temperature=1.0 (Gemini 3 default; recommended by Google for best reasoning)
>    - Parses the JSON response into a GeneratedAd
>    - Returns the ad AND a dict with token usage info (input_tokens, output_tokens)
>    - On parse error, retries once with temperature=0.7, then raises an exception
>
> 2. A function `generate_ad_variants(brief: AdBrief, config: Config, num_variants: int = 4) -> list[tuple[GeneratedAd, dict]]` that:
>    - Generates one ad per hook style: "question", "stat", "story", "fear"
>    - Returns up to num_variants ads
>    - Each variant uses a different hook style so we get diversity
>
> 3. A helper `load_few_shot_examples(dimension: str = None) -> str` that:
>    - Loads high-quality reference ads from compete/references/calibration_ads.json
>    - Formats 2-3 of them as few-shot examples in the prompt
>    - If dimension is specified, picks examples that score high on that dimension
>
> Use the google.genai Client from config/loader.py. Add print statements showing the hook style and a preview of the generated ad.
> ```

### Step 4.3: Quick Test

```bash
# Test generating a single ad
python3 -c "
from generate.generator import generate_ad
from generate.models import AdBrief
from config.loader import get_config

config = get_config()
brief = AdBrief(
    audience_segment='anxious_parents',
    campaign_goal='conversion',
    specific_offer='Free SAT practice test'
)
ad, usage = generate_ad(brief, config, hook_style='question')
print(f'Primary: {ad.primary_text}')
print(f'Headline: {ad.headline}')
print(f'Description: {ad.description}')
print(f'CTA: {ad.cta_button}')
print(f'Tokens used: {usage}')
"
```

---

## Phase 5: Iterate — The Feedback Loop

**Goal:** Wire generation and evaluation together into the core feedback loop: generate → evaluate → identify weakness → targeted regeneration → re-evaluate.

### Step 5.1: Improvement Strategies

#### Cursor Prompt

> **Paste this into Cursor chat:**
>
> ```
> Create a file at `iterate/strategies.py` that implements targeted improvement strategies:
>
> 1. `get_improvement_prompt(ad: GeneratedAd, evaluation: AdEvaluation, dimension_name: str) -> str`
>    - Takes an ad that scored below threshold and returns a targeted regeneration prompt
>    - The prompt should reference the specific weak dimension, its score, and the rationale
>    - Include the original ad as context so the model can improve on it rather than starting fresh
>    - Strategy: tell the model "This ad scored {score}/10 on {dimension} because {rationale}. Rewrite ONLY to improve {dimension} while maintaining the strengths in other dimensions."
>
> 2. `get_strategy_name(attempt: int) -> str`
>    - Attempt 1: "targeted_reprompt" — just tell the model what's weak
>    - Attempt 2: "few_shot_injection" — add 2-3 high-scoring examples for the weak dimension
>    - Attempt 3: "model_escalation" — (future: switch to a more expensive model)
>    - Returns the strategy name for logging
>
> 3. `build_targeted_prompt(original_ad: GeneratedAd, weak_dimension: str, score: int, rationale: str, strategy: str, config: Config) -> str`
>    - Builds the full regeneration prompt based on the strategy
>    - For "targeted_reprompt": includes the weakness feedback
>    - For "few_shot_injection": loads high-scoring examples from calibration data
> ```

### Step 5.2: The Feedback Loop

#### Cursor Prompt

> **Paste this into Cursor chat:**
>
> ```
> Create a file at `iterate/feedback.py` that implements the core feedback loop:
>
> 1. `improve_ad(ad: GeneratedAd, evaluation: AdEvaluation, brief: AdBrief, config: Config, attempt: int = 1) -> tuple[GeneratedAd, dict]`
>    - Gets the weakest dimension from the evaluation
>    - Picks an improvement strategy based on the attempt number
>    - Builds a targeted regeneration prompt
>    - Calls Gemini 3 Flash with the improvement prompt
>    - Returns the improved ad and token usage
>
> 2. `run_pipeline(brief: AdBrief, config: Config) -> AdRecord`
>    - This is the MAIN function that ties everything together
>    - Step 1: Generate an ad using generate_ad()
>    - Step 2: Evaluate it using evaluate_ad()
>    - Step 3: If it passes threshold (7.0+), create an AdRecord and return it
>    - Step 4: If it fails, call improve_ad() with the weak dimension
>    - Step 5: Re-evaluate the improved ad
>    - Step 6: Repeat up to max_regeneration_attempts (default 3)
>    - Step 7: After max attempts, return the best version (highest aggregate_score) even if below threshold, flagged as below_threshold
>    - Track total cost across all generation + evaluation calls
>    - Print a progress summary after each cycle showing: cycle number, aggregate score, weakest dimension, strategy used
>
> 3. `run_batch(briefs: list[AdBrief], config: Config) -> list[AdRecord]`
>    - Runs run_pipeline for each brief
>    - Prints a batch summary: total ads, pass rate, average score, total cost
>    - Saves all AdRecords to data/ad_library.json
>
> This is the heart of the system. Add clear logging at every step so you can trace what's happening.
> ```

### Step 5.3: Test the Full Loop

```bash
# Test the full pipeline with a single brief
python3 -c "
from iterate.feedback import run_pipeline
from generate.models import AdBrief
from config.loader import get_config

config = get_config()
brief = AdBrief(
    audience_segment='anxious_parents',
    campaign_goal='conversion',
    specific_offer='Free SAT practice test'
)
record = run_pipeline(brief, config)
print(f'\nFinal score: {record.evaluation.aggregate_score}')
print(f'Passed threshold: {record.evaluation.passes_threshold}')
print(f'Iterations: {record.iteration_cycle}')
print(f'Total cost: ${record.generation_cost_usd + record.evaluation_cost_usd:.4f}')
"
```

---

## Phase 6: Observe — Langfuse Integration

**Goal:** Add observability to every LLM call so you can track cost per ad, quality per dollar, and latency.

#### Cursor Prompt

> **Paste this into Cursor chat:**
>
> ```
> Read the existing files: evaluate/judge.py, generate/generator.py, iterate/feedback.py, and config/loader.py.
>
> Create a file at `config/observability.py` that sets up Langfuse tracing:
>
> 1. Initialize the Langfuse client using environment variables
> 2. Set up the OpenInference GoogleGenAI instrumentor for automatic tracing
> 3. Provide a helper decorator or context manager that wraps pipeline functions
>
> Then modify the existing files to add Langfuse tracing:
>
> - In evaluate/judge.py: wrap evaluate_dimension and evaluate_ad with @observe()
>   so every evaluation call is traced with its dimension name, score, and token usage
> - In generate/generator.py: wrap generate_ad with @observe() so every generation
>   call is traced with the brief info and token usage
> - In iterate/feedback.py: wrap run_pipeline with @observe() as the parent trace,
>   so each pipeline run shows the full generate→evaluate→improve cycle as nested spans
>
> Use Langfuse's propagate_attributes to add metadata like:
> - session_id: the batch run ID
> - tags: ["generation", "evaluation", "iteration"] as appropriate
> - metadata: {audience_segment, campaign_goal, hook_style, dimension_name}
>
> After adding tracing, every LLM call should appear in the Langfuse dashboard with
> full token counts, latency, cost, and the prompt/response content.
>
> Use the openinference-instrumentation-google-genai library for automatic instrumentation
> of the google.genai client, plus Langfuse's @observe() decorator for pipeline-level spans.
> ```

### Verify Langfuse

```bash
# Run a single pipeline and check Langfuse
python3 -c "
from iterate.feedback import run_pipeline
from generate.models import AdBrief
from config.loader import get_config

config = get_config()
brief = AdBrief(audience_segment='anxious_parents', campaign_goal='conversion')
record = run_pipeline(brief, config)

# Flush traces to Langfuse
from langfuse import get_client
get_client().flush()
print('Check your Langfuse dashboard for the trace!')
"
```

Then go to your Langfuse dashboard — you should see a trace with nested spans for generation, each evaluation dimension, and any improvement cycles.

---

## Phase 7: Scale — Batch Generation & Quality Trends

**Goal:** Generate 50+ ads across multiple audience segments and brief types. Track quality improvement across iteration cycles.

### Step 7.1: Brief Generator

#### Cursor Prompt

> **Paste this into Cursor chat:**
>
> ```
> Create a file at `generate/briefs.py` that generates a diverse set of ad briefs:
>
> 1. `generate_brief_matrix() -> list[AdBrief]`
>    - Creates briefs for every combination of:
>      - 3 audience segments: anxious_parents, stressed_students, comparison_shoppers
>      - 2 campaign goals: awareness, conversion
>      - 3 specific offers: "Free SAT practice test", "1-on-1 expert tutoring", "Score improvement guarantee"
>    - That's 18 unique briefs
>    - For each brief, also vary the tone slightly: "urgent", "empathetic", "confident"
>    - Returns 50+ briefs total (some combinations with different tones)
>
> 2. `save_briefs(briefs: list[AdBrief], path: str = "data/briefs.json")`
>    - Saves the brief list to JSON for reproducibility
>
> 3. `load_briefs(path: str = "data/briefs.json") -> list[AdBrief]`
>    - Loads briefs from JSON
>
> Make it runnable: `python -m generate.briefs` should generate and save 50+ briefs,
> printing a summary of the distribution.
> ```

### Step 7.2: Batch Runner

#### Cursor Prompt

> **Paste this into Cursor chat:**
>
> ```
> Create a file at `output/batch_runner.py` that orchestrates large batch runs:
>
> 1. `run_full_batch(num_ads: int = 54) -> dict`
>    - Loads or generates briefs from generate/briefs.py
>    - Runs each brief through the full pipeline (iterate/feedback.py run_pipeline)
>    - Tracks: total ads generated, pass rate, average score per dimension,
>      total cost, cost per ad, average iterations per ad
>    - Saves all AdRecords to data/ad_library.json
>    - Saves a batch summary to data/batch_summary.json
>    - Uses rich library to show a live progress bar
>    - Handles rate limiting gracefully: if a Gemini API call fails with 429,
>      wait 60 seconds and retry (up to 3 retries)
>
> 2. `load_ad_library(path: str = "data/ad_library.json") -> list[AdRecord]`
>    - Loads the generated ad library from disk
>
> Make it runnable: `python -m output.batch_runner`
>
> Add a --num-ads CLI argument using argparse so you can run:
>   python -m output.batch_runner --num-ads 10  (for testing)
>   python -m output.batch_runner --num-ads 54  (for the full run)
> ```

### Run the Full Batch

```bash
# First, do a small test run
python -m output.batch_runner --num-ads 5

# If that works, run the full batch (this will take a while and cost some API credits)
python -m output.batch_runner --num-ads 54

# Check your Langfuse dashboard for all the traces!
```

---

## Phase 8: Test — Unit & Integration Tests

**Goal:** Write 15+ tests to meet the code quality requirement.

#### Cursor Prompt

> **Paste this into Cursor chat:**
>
> ```
> Create test files in the tests/ directory. We need 15+ tests total. Read the existing code in generate/, evaluate/, iterate/, and config/ to understand what to test.
>
> tests/test_models.py (5 tests):
> - test_ad_brief_creation: valid AdBrief creates successfully
> - test_ad_brief_validation: invalid audience_segment raises ValidationError
> - test_generated_ad_headline_max_length: headline > 40 chars raises error
> - test_dimension_score_range: score outside 1-10 raises error
> - test_ad_evaluation_aggregate_score: verify weighted average calculation is correct
>   (e.g., if clarity=8, value_prop=8, cta=8, brand=8, emotional=8, with weights
>   0.25+0.25+0.20+0.15+0.15=1.0, aggregate should be 8.0)
>
> tests/test_config.py (3 tests):
> - test_config_loads: config.yaml loads without errors
> - test_config_dimensions_sum_to_one: dimension weights sum to 1.0
> - test_config_threshold: quality threshold is 7.0
>
> tests/test_dimensions.py (2 tests):
> - test_get_rubric_returns_string: get_rubric("clarity") returns non-empty string
> - test_get_all_rubrics_has_five: get_all_rubrics() returns exactly 5 rubrics
>
> tests/test_briefs.py (2 tests):
> - test_generate_brief_matrix_count: generates at least 50 briefs
> - test_brief_matrix_coverage: all 3 audience segments are represented
>
> tests/test_pipeline.py (3 tests — these use mocked LLM responses):
> - test_evaluate_dimension_mock: mock the Gemini call, verify DimensionScore is parsed
> - test_run_pipeline_passes_on_first_try: mock a high-scoring evaluation, verify no retries
> - test_run_pipeline_retries_on_low_score: mock a low score then a high score, verify 2 cycles
>
> Use pytest fixtures for common setup (config, sample briefs, sample ads).
> For tests that would call the real API, use unittest.mock.patch to mock the Gemini client.
> Mock responses should return realistic JSON that matches the expected format.
> ```

### Run Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pip install pytest-cov
pytest tests/ -v --cov=generate --cov=evaluate --cov=iterate --cov=config

# Expected: 15+ tests, all passing
```

---

## Phase 9: Document — Decision Log & README

**Goal:** Write the decision log and README. The decision log matters as much as the code.

### Step 9.1: Decision Log

```bash
cat > docs/decision_log.md << 'EOF'
# Decision Log

This log documents my thinking and judgment calls throughout the project.
Entries are written as decisions are made, not retroactively.

## Template for Each Entry

### Decision: [Short title]
- **Date:** YYYY-MM-DD
- **Context:** What problem was I trying to solve?
- **Options considered:** What were the alternatives?
- **Decision:** What did I choose?
- **Rationale:** Why? What tradeoffs did I accept?
- **Outcome:** Did it work? What would I do differently?

---

## Entries

### Decision: Build evaluator before generator
- **Date:**
- **Context:** Need to decide build order — generator or evaluator first?
- **Options:** (A) Generator first, then evaluator. (B) Evaluator first, then generator.
- **Decision:** Evaluator first.
- **Rationale:** The PRD says "the hardest part isn't generation—it's evaluation." If I can't measure quality, I can't improve it. Building the evaluator first also gives me calibrated reference points before I start generating.
- **Outcome:** (Fill in after building)

### Decision: Dimension weighting
- **Date:**
- **Context:** How to weight the 5 quality dimensions?
- **Options:** (A) Equal weights (20% each). (B) Clarity-heavy. (C) Custom weights from PRD.
- **Decision:** (Fill in)
- **Rationale:** (Fill in)
- **Outcome:** (Fill in after calibration)

### Decision: Separate models for generation vs evaluation
- **Date:**
- **Context:** Use one model for everything or split generation/evaluation?
- **Options:** (A) Single model (cheaper). (B) Flash for gen, Pro for eval (better judge quality).
- **Decision:** (Fill in)
- **Rationale:** (Fill in)
- **Outcome:** (Fill in)

(Add more entries as you build. Be honest about what didn't work.)
EOF
```

### Step 9.2: README

#### Cursor Prompt

> **Paste this into Cursor chat:**
>
> ```
> Create a README.md for the ad-engine project. It should include:
>
> 1. **Project title and one-line description**
> 2. **Quick start** — 5 commands max to clone, install, configure, and run
>    - git clone, cd, pip install, copy .env.example, python -m output.batch_runner
> 3. **Architecture overview** — brief description of the 4-stage pipeline
> 4. **How it works** — the generate → evaluate → improve loop, explained simply
> 5. **Project structure** — the directory tree from the PRD
> 6. **Configuration** — how to edit config.yaml (dimensions, weights, threshold)
> 7. **Running tests** — `pytest tests/ -v`
> 8. **Key design decisions** — link to docs/decision_log.md
> 9. **Limitations** — be honest. What doesn't work well? What's missing?
> 10. **Cost estimate** — approximate API cost per batch of 50 ads
>
> Keep it concise. No marketing fluff. A developer should be able to understand
> the project and run it within 5 minutes of reading the README.
> ```

### Step 9.3: Limitations Doc

```bash
cat > docs/limitations.md << 'EOF'
# Known Limitations

## Evaluation
- LLM-as-judge scores can drift over time as model weights are updated
- Self-evaluation bias exists even with separate models (both are Gemini family)
- The 1-10 scale tends to cluster around 5-8; truly low (1-3) and truly high (9-10) scores are rare
- Calibration is based on a small set of reference ads — may not generalize

## Generation
- Generated ads sometimes include unsubstantiated claims ("guaranteed 200+ point improvement")
- The model occasionally breaks character count limits despite explicit instructions
- Hook diversity decreases over long batch runs (model tends toward favorite patterns)

## Cost
- Evaluation is the biggest cost driver (5 LLM calls per ad, using the expensive Pro model)
- No caching implemented — re-evaluating the same ad costs the same each time
- Rate limiting from Gemini API can slow large batches significantly

## Competitive Intelligence
- Meta Ad Library API doesn't work for US non-political ads
- Competitor analysis is entirely manual — no automated pattern extraction
- Reference ads may become stale as competitors update their campaigns

## What I'd Do Differently
(Fill in as you build — this section is the most valuable part of the doc)
EOF
```

---

## Phase 10: Visualize — Quality Trends & Dashboards

**Goal:** Create visualizations showing quality improvement over iteration cycles.

#### Cursor Prompt

> **Paste this into Cursor chat:**
>
> ```
> Create a file at `output/visualize.py` that generates quality trend visualizations:
>
> 1. `plot_quality_trends(ad_library_path: str = "data/ad_library.json")`
>    - Load all AdRecords from the ad library
>    - Create a matplotlib figure with 2x2 subplots:
>      a) Top-left: Average aggregate score per iteration cycle (line chart)
>         X-axis: cycle 1, 2, 3. Y-axis: average score. Show the 7.0 threshold as a red dashed line.
>      b) Top-right: Score distribution per dimension (grouped bar chart)
>         5 groups (one per dimension), bars showing average score. Color-code by dimension.
>      c) Bottom-left: Pass rate by audience segment (bar chart)
>         What % of ads for each audience segment passed the 7.0 threshold?
>      d) Bottom-right: Cost per ad by iteration count (bar chart)
>         Ads that passed on first try vs after 1 retry vs after 2 retries — average cost each.
>    - Save to output/quality_trends.png
>    - Use a clean, professional style (not the default matplotlib style)
>
> 2. `plot_dimension_radar(ad_record: AdRecord)`
>    - Create a radar/spider chart showing the 5 dimension scores for a single ad
>    - Save to output/radar_{ad_id}.png
>
> 3. `generate_evaluation_report(ad_library_path: str = "data/ad_library.json")`
>    - Create a JSON report at data/evaluation_report.json with:
>      - Total ads generated, pass rate, average score
>      - Per-dimension averages and standard deviations
>      - Per-audience-segment pass rates
>      - Total cost, cost per ad, cost per passing ad
>      - Quality improvement: average score in cycle 1 vs final cycle
>    - Also create a human-readable summary at data/evaluation_report.md
>
> Make it runnable: `python -m output.visualize`
> Use seaborn style for prettier charts: plt.style.use('seaborn-v0_8-whitegrid')
> ```

### Generate Visualizations

```bash
# After running a batch, generate the visualizations
python -m output.visualize

# Check the output/ directory for the charts
ls output/*.png
```

---

## Tips for Working with Cursor

### General Workflow

1. **Always provide context.** Before asking Cursor to write code, make sure the relevant files are open or referenced. Cursor works best when it can see the files it needs to import from.

2. **Use phased prompts.** Don't ask Cursor to build the whole project at once. Feed it one file at a time, in the order this guide specifies. Each phase builds on the last.

3. **Fix before moving on.** If Cursor generates code with an error, fix it before starting the next phase. Run the code after each step. Don't accumulate technical debt.

4. **Use Cursor's inline edit (Cmd+K) for small changes.** If a function has a bug or needs a tweak, highlight the function and use Cmd+K to describe the change instead of regenerating the whole file.

### Debugging Prompts

If something isn't working, paste this pattern into Cursor:

> ```
> I'm getting this error when running [command]:
>
> [paste the full error traceback]
>
> The relevant files are:
> - [file1.py] (open in editor)
> - [file2.py] (open in editor)
>
> What's wrong and how do I fix it?
> ```

### When the LLM Judge Scores Seem Wrong

> ```
> My evaluator is giving [describe the problem, e.g., "all ads a 7 regardless of quality"].
>
> Here's the current evaluation prompt:
> [paste from evaluate/prompts/judge_prompt.yaml]
>
> Here are two ads that should score very differently but got similar scores:
> [paste the two ads and their scores]
>
> How should I adjust the prompt to fix this? Focus on making the scoring rubric
> more specific and adding clearer anchoring examples.
> ```

### How to Add to the Decision Log

Every time you make a non-obvious choice, add an entry. Good triggers for a decision log entry:

- You chose between two approaches
- Something didn't work and you changed course
- You were surprised by a result
- You disagreed with the PRD and went a different direction

---

## Final Checklist

Before submitting, verify you have:

- [ ] 50+ generated ads with full evaluation scores in `data/ad_library.json`
- [ ] Quality improvement demonstrated over 3+ iteration cycles (visible in charts)
- [ ] All 5 dimensions scored independently on every ad
- [ ] Evaluation report with quality trends at `data/evaluation_report.json`
- [ ] 15+ passing tests (`pytest tests/ -v`)
- [ ] Decision log at `docs/decision_log.md` with honest entries
- [ ] Limitations documented at `docs/limitations.md`
- [ ] README with one-command setup
- [ ] Quality trend visualization at `output/quality_trends.png`
- [ ] Code runs with `python -m output.batch_runner` from a clean setup
- [ ] `.env.example` file (with placeholder keys, never real keys)
- [ ] All API keys in `.env`, never in source code
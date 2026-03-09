---
name: Phase 0 Project Setup
overview: "Set up the ad-engine project from scratch: git, directory structure, Python venv, dependencies, env config, and gitignore."
todos:
  - id: git-init
    content: Initialize git repo
    status: completed
  - id: dir-structure
    content: Create full directory structure (generate, evaluate, iterate, compete/references, output, config, tests, docs, data) and __init__.py files
    status: completed
  - id: venv-deps
    content: Create venv, write requirements.txt, install dependencies
    status: completed
  - id: env-files
    content: Create .env (placeholder), .env.example, and .gitignore
    status: completed
  - id: verify
    content: Run Gemini API smoke test after user pastes real keys
    status: completed
isProject: false
---

# Phase 0: Project Setup and Environment

Based on the [build guide](.cursor/plans/adenginebuildguide.md) (lines 30-115).

## What we're doing

Standing up the full project skeleton so all subsequent phases have a clean foundation to build on.

## Steps

### 1. Initialize Git

```bash
git init
```

### 2. Create directory structure

```bash
mkdir -p generate/prompts evaluate iterate compete/references output config tests docs data
```

Directories map to pipeline stages:

- `generate/` -- ad copy generation (Phase 4)
- `evaluate/` -- LLM-as-judge scoring (Phase 3)
- `iterate/` -- feedback loop (Phase 5)
- `compete/references/` -- competitor research and calibration ads (Phase 1)
- `output/` -- batch runner and visualizations (Phase 7/10)
- `config/` -- YAML config and loader (Phase 2)
- `tests/` -- pytest suite (Phase 8)
- `docs/` -- decision log and limitations (Phase 9)
- `data/` -- generated artifacts (ad library, calibration results, etc.)

### 3. Create Python package markers

```bash
touch generate/__init__.py evaluate/__init__.py iterate/__init__.py output/__init__.py
```

### 4. Create virtual environment and install dependencies

Create `.venv`, activate, then install from `requirements.txt`:

```
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
```

### 5. Create `.env` file

Placeholder `.env` -- you'll paste your real keys when prompted:

```
GOOGLE_API_KEY=your-gemini-api-key-here
LANGFUSE_PUBLIC_KEY=your-langfuse-public-key
LANGFUSE_SECRET_KEY=your-langfuse-secret-key
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

Also create `.env.example` with the same placeholder content (this one gets committed).

### 6. Create `.gitignore`

```
.venv/
.env
__pycache__/
*.pyc
data/*.db
data/*.json
.DS_Store
```

### 7. Verify setup

Run the quick Gemini API smoke test from the guide (after you paste your real API key into `.env`):

```python
from google import genai
import os
from dotenv import load_dotenv
load_dotenv()
client = genai.Client(api_key=os.getenv('GOOGLE_API_KEY'))
response = client.models.generate_content(
    model='gemini-3-flash',
    contents='Say hello in exactly 5 words.'
)
print(response.text)
print('Setup verified!')
```

If this prints a response, Phase 0 is done.
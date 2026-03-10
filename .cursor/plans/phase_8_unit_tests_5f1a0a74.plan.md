---
name: Phase 8 Unit Tests
overview: Create 15+ pytest tests covering models, config, dimensions, briefs, and pipeline (with mocked LLM calls) in the `tests/` directory.
todos:
  - id: conftest
    content: Create tests/conftest.py with shared fixtures (sample_brief, sample_ad, sample_evaluation, config)
    status: completed
  - id: test-models
    content: Create tests/test_models.py with 5 Pydantic validation tests
    status: completed
  - id: test-config
    content: Create tests/test_config.py with 3 config loading tests
    status: completed
  - id: test-dimensions
    content: Create tests/test_dimensions.py with 2 rubric tests
    status: completed
  - id: test-briefs
    content: Create tests/test_briefs.py with 2 brief matrix tests
    status: completed
  - id: test-pipeline
    content: Create tests/test_pipeline.py with 3 mocked LLM pipeline tests
    status: completed
  - id: run-verify
    content: Run pytest -v and verify all 15+ tests pass
    status: completed
isProject: false
---

# Phase 8: Unit & Integration Tests

## Context

The `tests/` directory is currently empty. We need 15+ tests across 5 test files. The main challenge is that several modules (`config/loader.py`, `evaluate/judge.py`, `generate/generator.py`) trigger `init_observability()` and `get_gemini_client()` at import time or call time -- tests that don't hit the real API will need careful mocking.

## Key Considerations

- `config/loader.py` calls `init_observability()` at **module level** (line 21-22). Tests importing anything from `config.loader` will trigger this. Since Langfuse keys won't be set in CI, the observability module already degrades to no-ops, so this is fine.
- `get_config()` uses `lru_cache` -- tests that need different configs should call `get_config.cache_clear()` in teardown.
- `GeneratedAd` field limits were relaxed from the build guide spec: `headline` max is 80 (not 40), `primary_text` max is 1000. Tests should reflect the **actual** code, not the guide.
- `AdEvaluation.aggregate_score` uses hardcoded `DEFAULT_WEIGHTS` from [generate/models.py](generate/models.py), not config -- tests can verify the math directly.

## Test Files

### 1. `tests/conftest.py` -- Shared Fixtures

Provide reusable fixtures:

- `sample_brief` -- a valid `AdBrief`
- `sample_ad` -- a valid `GeneratedAd`
- `sample_dimension_score` -- a valid `DimensionScore`
- `sample_evaluation` -- a full `AdEvaluation` with known scores
- `config` -- loaded from `config/config.yaml`

### 2. `tests/test_models.py` (5 tests)

All pure Pydantic validation, no API calls needed.


| Test                                    | What it verifies                                                              |
| --------------------------------------- | ----------------------------------------------------------------------------- |
| `test_ad_brief_creation`                | Valid `AdBrief` constructs without error                                      |
| `test_ad_brief_invalid_goal`            | `campaign_goal` not in `["awareness", "conversion"]` raises `ValidationError` |
| `test_generated_ad_headline_max_length` | `headline` > 80 chars raises `ValidationError`                                |
| `test_dimension_score_range`            | `score=0` and `score=11` both raise `ValidationError`                         |
| `test_ad_evaluation_aggregate_score`    | All dimensions at 8 with weights 0.25+0.25+0.20+0.15+0.15 = aggregate 8.0     |


### 3. `tests/test_config.py` (3 tests)

Loads the real `config/config.yaml`.


| Test                                | What it verifies                                                |
| ----------------------------------- | --------------------------------------------------------------- |
| `test_config_loads`                 | `Config.from_yaml()` succeeds without error                     |
| `test_config_dimensions_sum_to_one` | Sum of dimension weights is 1.0 (validator on the model itself) |
| `test_config_threshold`             | `config.quality.threshold == 7.0`                               |


### 4. `tests/test_dimensions.py` (2 tests)

Calls `evaluate/dimensions.py` functions (these load config internally).


| Test                             | What it verifies                                   |
| -------------------------------- | -------------------------------------------------- |
| `test_get_rubric_returns_string` | `get_rubric("clarity")` returns a non-empty string |
| `test_get_all_rubrics_has_five`  | `get_all_rubrics()` returns exactly 5 rubrics      |


### 5. `tests/test_briefs.py` (2 tests)

Calls `generate/briefs.py` functions.


| Test                               | What it verifies                             |
| ---------------------------------- | -------------------------------------------- |
| `test_generate_brief_matrix_count` | Matrix produces exactly 54 briefs (3x2x3x3)  |
| `test_brief_matrix_coverage`       | All 3 audience segments appear in the matrix |


### 6. `tests/test_pipeline.py` (3 tests)

These mock the Gemini client to avoid real API calls. We'll use `unittest.mock.patch` on `config.loader.get_gemini_client` and set up a mock response object with `.text` returning valid JSON and `.usage_metadata` with token counts.


| Test                                     | What it verifies                                                                         |
| ---------------------------------------- | ---------------------------------------------------------------------------------------- |
| `test_evaluate_dimension_mock`           | Mock Gemini returns valid JSON -> `DimensionScore` is correctly parsed                   |
| `test_run_pipeline_passes_first_try`     | Mock high scores (all 8s) -> pipeline returns after 1 cycle with `passes_threshold=True` |
| `test_run_pipeline_retries_on_low_score` | Mock low scores then high scores -> pipeline runs 2 cycles                               |


**Mocking strategy**: Patch `config.loader.get_gemini_client` to return a mock client whose `models.generate_content()` returns a mock response with:

- `.text` = JSON string matching the expected format
- `.usage_metadata.prompt_token_count` = 100
- `.usage_metadata.candidates_token_count` = 50

For the pipeline retry test, use `side_effect` to return different JSON on successive calls (low scores first, then high scores, then a valid ad JSON for the improvement step).

## Running

```bash
pytest tests/ -v
pytest tests/ -v --cov=generate --cov=evaluate --cov=iterate --cov=config
```


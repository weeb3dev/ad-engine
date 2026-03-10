---
name: Run Full 54 Batch
overview: Run the full 54-ad batch generation pipeline and monitor the results.
todos:
  - id: run-batch
    content: Run `python -m output.batch_runner` and monitor progress
    status: completed
  - id: review-results
    content: Review batch_summary.json and ad_library.json output
    status: completed
isProject: false
---

# Run Full 54-Ad Batch

## Command

```bash
python -m output.batch_runner
```

This runs `run_full_batch(54)` in [output/batch_runner.py](output/batch_runner.py), which will:

1. Load existing `data/briefs.json` (54 briefs already generated)
2. Run each brief through the generate -> evaluate -> improve pipeline
3. Retry on rate limits (up to 3 retries with 60s backoff)
4. Show a live progress bar with running pass rate
5. Save `data/ad_library.json` and `data/batch_summary.json`

## Estimates

- **Cost**: ~$3 total (previous run was ~$0.057/ad, x54 = ~$3.07)
- **Time**: ~30-60 min (each ad takes generate + evaluate + up to 3 improvement cycles)
- **API calls**: ~200-400 Gemini flash-lite calls total (depends on how many ads need improvement iterations)

## What to Watch For

- **Rate limiting**: The runner handles 429s automatically (60s sleep + retry). If flash-lite's RPM is low, this could add time but won't lose progress.
- **Pass rate**: Previous 2-ad run hit 100% pass rate at 7.9 avg score. The full 54 will give a more realistic picture across all segments/tones.
- **Failed ads**: Any pipeline failures are logged in red and skipped (the ad is omitted from results, not retried endlessly).

## After Completion

The runner prints a summary table with:

- Overall pass rate, avg/min/max scores
- Per-segment pass rates (anxious_parents, stressed_students, comparison_shoppers)
- Per-dimension averages (clarity, value_proposition, call_to_action, brand_voice, emotional_resonance)
- Total cost and cost-per-ad

Results saved to `data/ad_library.json` (all ad records) and `data/batch_summary.json` (stats).
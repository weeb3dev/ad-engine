---
name: Batch Markdown Report
overview: Generate a reviewer-friendly markdown report from the batch results, including key takeaways, summary stats, calibration data, and all 53 ads in readable format.
todos:
  - id: write-report-script
    content: Create output/generate_report.py that reads the 3 JSON files and writes the markdown report
    status: completed
  - id: run-script
    content: Run the script to generate output/batch1_ad_library.md
    status: completed
  - id: verify-output
    content: Spot-check the markdown output for correctness and readability
    status: completed
  - id: commit-push
    content: Commit both the script and the generated report, push to GitHub
    status: completed
isProject: false
---

# Batch 1 Markdown Report

## File Location

Create `output/batch1_ad_library.md`. The `output/` directory already houses the batch orchestration code, so it's the natural home for output artifacts. Keeps `data/` clean as raw JSON.

## Structure

The markdown file will have these sections:

### 1. Executive Summary

Key takeaways from the run:

- 53/54 ads produced, 100% pass rate, $2.35 total cost
- Clarity is the strongest dimension (8.42 avg), emotional resonance is the weakest (6.51)
- Call to action at 6.98 avg is just under threshold -- many ads barely pass on this dimension
- Most ads need 2-3 improvement cycles (only 11/53 passed on first generation)
- Flash-lite at $0.044/ad is extremely cost-efficient

### 2. Batch Summary

Table from [data/batch_summary.json](data/batch_summary.json): pass rate, avg/min/max scores, cost, iterations, per-segment rates, per-dimension averages.

### 3. Judge Calibration

Table from [data/calibration_results.json](data/calibration_results.json) showing 8/8 tier pass rate -- the evaluator correctly ranks high/medium/low quality ads. Include expected vs actual scores per calibration ad.

### 4. All 53 Ads (grouped by audience segment)

Three sections: **Anxious Parents** (17 ads), **Comparison Shoppers** (18 ads), **Stressed Students** (18 ads).

Each ad rendered as:

- Headline, primary text, description, CTA button
- Brief metadata (goal, tone, offer) in a compact line
- Score, iteration count, improvement strategy
- Per-dimension scores in a compact line

## Generation Approach

Write a small Python script (`output/generate_report.py`) that reads the three JSON files and produces the markdown programmatically. This is better than hand-writing 53 ad entries, and the script can be re-run on future batches. The script:

1. Reads `data/batch_summary.json`, `data/calibration_results.json`, `data/ad_library.json`
2. Writes `output/batch1_ad_library.md`
3. Groups ads by `audience_segment`, sorts within group by `aggregate_score` descending (best ads first)
4. Embeds the key takeaways as static text at the top

Then run it once and commit both the script and the generated `.md`.
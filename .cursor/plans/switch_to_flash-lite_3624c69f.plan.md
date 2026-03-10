---
name: Switch to Flash-Lite
overview: Update the two model references in config/config.yaml from the now-deprecated gemini-3.1-pro-preview to gemini-3.1-flash-lite-preview, then verify the pipeline still runs.
todos:
  - id: update-config
    content: Change both model references in config/config.yaml to gemini-3.1-flash-lite-preview
    status: completed
  - id: verify-pipeline
    content: Run python -m output.batch_runner --num-ads 2 to confirm end-to-end pipeline works with new model
    status: completed
isProject: false
---

# Switch Models to gemini-3.1-flash-lite-preview

## Why

`gemini-3.1-pro-preview` was shut down on March 9, 2026. The pipeline is currently broken. Additionally, Flash-Lite has generous free-tier rate limits and costs $0.25/$1.50 per 1M tokens (8x cheaper than Pro was), which should eliminate the 250 RPD bottleneck.

## Change

Single file: [config/config.yaml](config/config.yaml)

```yaml
models:
  generator: "gemini-3.1-flash-lite-preview"
  evaluator: "gemini-3.1-flash-lite-preview"
```

No code changes needed -- every module reads the model ID from this config via `config.models.generator` / `config.models.evaluator`.

## Verification

Run `python -m output.batch_runner --num-ads 2` to confirm the pipeline works end-to-end with the new model.

## Note on evaluation quality

Flash-Lite is optimized for throughput over deep reasoning. If evaluation scores drift or become less discriminating (e.g., clustering around 6-8 for everything), we can revisit and bump the evaluator to `gemini-3-flash-preview` while keeping the generator on Flash-Lite. Worth a decision log entry after the full batch run.

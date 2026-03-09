---
name: Update Model References
overview: "Update all Gemini model references in the build guide to use current model IDs: `gemini-3.1-pro-preview` for both generator and evaluator, `gemini-3-flash-preview` for the smoke test."
todos:
  - id: smoke-test
    content: "Line 107: change gemini-3-flash to gemini-3-flash-preview"
    status: completed
  - id: config-generator
    content: "Line 232: change generator model from gemini-3-flash to gemini-3.1-pro-preview"
    status: completed
  - id: generator-prompt
    content: "Line 563: change Gemini 3 Flash reference to Gemini 3.1 Pro (gemini-3.1-pro-preview) and update temperature recommendation"
    status: completed
isProject: false
---

# Update Gemini Model References in Build Guide

5 model references in [adenginebuildguide.md](.cursor/plans/adenginebuildguide.md) need updating. The old model IDs (`gemini-3-flash`) are not valid -- they need the `-preview` suffix, and the user wants `gemini-3.1-pro-preview` for both generation and evaluation.

## Changes

### 1. Smoke test (line 107)

Change `gemini-3-flash` to `gemini-3-flash-preview`. Using Flash here (not Pro) since the smoke test just verifies the API key works -- no reason to burn Pro tokens on "Say hello in 5 words." Flash also has a free tier.

### 2. Config YAML generator model (line 232)

Change `generator: "gemini-3-flash"` to `generator: "gemini-3.1-pro-preview"`. User wants Pro for both roles.

### 3. Config YAML evaluator model (line 233)

Already `evaluator: "gemini-3.1-pro-preview"` -- no change needed.

### 4. Evaluator Cursor prompt (line 437)

Already references `gemini-3.1-pro-preview` -- no change needed.

### 5. Generator Cursor prompt (line 563)

Change `Gemini 3 Flash (gemini-3-flash)` to `Gemini 3.1 Pro (gemini-3.1-pro-preview)`. Also note: temperature=0.8 is fine for Pro, but the Gemini 3 docs recommend keeping temperature at default 1.0 for Gemini 3 models. We should update to `temperature=1.0` (or just remove the explicit temperature setting).

## Cost implication note

Using Pro for generation instead of Flash roughly 4x the generation cost ($2/$12 vs $0.50/$3 per 1M tokens). Worth noting in the guide or decision log, but the user is aware and wants the quality.

# Phase 1.6 — Multimodal Processor (Visual Analysis / Art Director's Notes)

> [← Root README](../../../../README.md) · [← Pipeline Index](../../README.md)

> **Section 8 · Visual Asset Pre-bake**

---

## 1. Purpose

Phase 1.6 is the pipeline's **Art Director**. It pre-bakes visual analysis for every illustration in the volume *before* translation begins. A Gemini multimodal vision model examines each image and generates structured Art Director's Notes covering composition, emotional delta, subtext, EPS band assignments, and POV character identification.

These notes are stored in `visual_cache.json` and injected into Phase 2 translation prompts, giving the translator grounded visual context without requiring real-time image processing during translation. This decoupled "CPU + GPU" architecture means the visual analysis cost is paid once per volume, not once per chapter.

Key design constraint (**Canon Event Fidelity**): visual guidance *enhances vocabulary and register choices* in translation — it does not alter plot content. The translator uses Art Director's Notes to match emotional tone, not to invent or change events.

---

## 2. Entry Points

| Layer | Identifier |
|-------|-----------|
| Main processor class | `modules.multimodal.asset_processor.VisualAssetProcessor` |
| Invoked via | Direct class instantiation from `MTLController.run_phase1_6()` |
| Controller method | `MTLController.run_phase1_6(volume_id, standalone, full_ln_cache_mode, force_override)` in `scripts/mtl.py` |
| Integrity checker | `modules.multimodal.integrity_checker.check_illustration_integrity` |
| Cache manager | `modules.multimodal.cache_manager.VisualCacheManager` |
| Thought logger | `modules.multimodal.thought_logger.ThoughtLogger` |

The controller calls `VisualAssetProcessor` directly (not as a subprocess):
```python
from modules.multimodal.asset_processor import VisualAssetProcessor
processor = VisualAssetProcessor(volume_path, force_override=force_override)
stats = processor.process_volume()
```

---

## 3. Inputs

| Input | Source | Notes |
|-------|--------|-------|
| `volume_id` | CLI arg | Resolved to `data/<vol>/` directory |
| `manifest.json` | `data/<vol>/manifest.json` | `assets[]` list with `epub_id_to_cache_id` mapping |
| Illustration files | `data/<vol>/illustrations/` | JPEG/PNG extracted by Phase 1 |
| Full-LN cache | From Phase 1.55 | Required (interactive gate for standalone runs) |
| `--full-ln-cache off` | CLI flag | Skips full-LN cache prep for this run |
| `force_override` | Internal flag | Re-analyzes already-cached illustrations |

**Pre-flight check:** An illustration integrity check (`check_illustration_integrity`) runs before any analysis. It validates that all `epub_id` references in the manifest have corresponding asset files. Failures are **fatal** — the phase aborts with actionable error messages.

---

## 4. Outputs

| Output | Location | Description |
|--------|----------|-------------|
| Visual cache | `data/<vol>/visual_cache.json` | Per-illustration analysis dict, keyed by `cache_id` |
| Thought logs | `data/<vol>/THINKING/` | Raw Gemini thinking traces for editorial review |
| `pipeline_state.multimodal_processor` | `manifest.json` | Status, timestamp, counts |

Each `visual_cache.json` entry contains nine structured fields:

| Field | Description |
|-------|-------------|
| `composition` | Panel layout, framing, focal point |
| `emotional_delta` | Gap between surface appearance and underlying emotion |
| `key_details` | `expressions`, `actions`, `environment`, `costume_significance` |
| `pov_character` | Canonical EN name of the foregrounded character |
| `subtext_inference` | Per-character unspoken emotional state |
| `translation_vocab` | Vocabulary register and tone recommendations |
| `visual_eps_band` | EPS band assignment from visual evidence (`HOT`/`WARM`/`NEUTRAL`/`COOL`/`COLD`) |
| `arc_tracking` | Character arc signals visible in illustration |
| `prompt_injection` | Pre-formatted `<Visual_Cache>` XML block for Phase 2 prompt assembly |

**Run stats returned by `process_volume()`:**
- `total` — total illustrations
- `cached` — already in cache (skipped)
- `generated` — newly analyzed this run
- `blocked` — safety-blocked by Gemini (fallback text used)

---

## 5. LLM Routing

| Parameter | Value |
|-----------|-------|
| Model | `gemini-3-flash-preview` _(config.yaml `translation.phase_models.'1_6'`)_ |
| Temperature | `0.3` |
| Top-P | `0.95` |
| Top-K | `40` |
| Max output tokens | `65536` |
| Thinking budget | `-1` (adaptive) |
| Provider | Gemini (Google) — multimodal vision |
| Config key | `translation.phase_models.'1_6'` in `config.yaml` |
| API client | `pipeline.common.genai_factory.create_genai_client` |

> **Note:** The module docstring (`asset_processor.py`) references "Gemini 3 Pro Vision" and "Gemini 3 Multimodal Vision". The current `config.yaml` maps phase `1_6` to `gemini-3-flash-preview`. Verify which model name resolves in your Gemini backend configuration.

**Safety config** (from `config.yaml`):
- All safety categories: `BLOCK_NONE`
- Fallback enabled with `max_retries: 3`; triggers on `SAFETY`, `RECITATION`, `BLOCKED`
- On safety block: logs warning and stores a meaningful fallback text rather than crashing

---

## 6. Prompt / Tool Dependencies

The visual analysis prompt is defined inline at the top of `modules/multimodal/asset_processor.py` as `VISUAL_ANALYSIS_PROMPT`. It includes:
- EPS band definition table
- Nine required output fields with field-level instructions
- KF spec references: §2.1 (Visual_Cache), §2.2 (Subtext/Intent), §3.1 (Voice Archetype), §5.1 (POV)
- `<Visual_Cache>` XML schema for downstream prompt injection

Supporting modules:
- `modules/multimodal/segment_classifier.py` — classifies image segments
- `modules/multimodal/analysis_detector.py` — detects existing analysis hits
- `modules/multimodal/prompt_injector.py` — assembles `<Visual_Cache>` XML blocks
- `modules/multimodal/kuchie_visualizer.py` — Extracts character names from kuchie (口絵) color-plate illustrations using Gemini Vision; cross-references with Phase 1 ruby annotations to enforce canonical names in `visual_cache.json`

---

## 7. Failure Modes & Guardrails

| Failure | Symptom | Recovery |
|---------|---------|---------|
| Illustration integrity check fails | Fatal; lists specific missing/malformed assets | Fix manifest `epub_id_to_cache_id` mapping or missing image files |
| Gemini 429 (rate limit) | Exponential backoff retry (up to `retry_attempts: 10`) | Reduce throughput; check `rate_limit.requests_per_minute: 2` |
| Gemini 503 (transient) | Retry with backoff | Automatic; no action needed |
| Safety block on illustration | Warning logged; fallback text stored in cache | Manual: run `./mtl cache-inspect <vol> --detail` to review |
| `ImportError` for multimodal module | Fatal; check install | Ensure `modules/multimodal/` is in `PYTHONPATH` |
| `manifest.json` missing | Early exit with error | Run Phase 1 first |
| Full-LN cache gate declined | Phase aborts if standalone and user selects skip | Re-run after Phase 1.55 completes |
| `force_override=False` | Already-cached illustrations skipped | Normal behavior; use `force_override` to re-analyze |

**Cache invalidation:** Each illustration's cache entry is keyed by a hash of `prompt + image_bytes + model`. Changing the prompt or upgrading the model automatically invalidates stale entries.

---

## 8. How to Run

### Standard Phase 1.6
```bash
./mtl phase1.6 20260305_17a8
```

### Skip full-LN cache prep
```bash
./mtl phase1.6 20260305_17a8 --full-ln-cache off
```

### Phase 1.6 + Phase 2 with multimodal context (combined)
```bash
./mtl multimodal 20260305_17a8
```

### Inspect cached visual analysis after run
```bash
./mtl cache-inspect 20260305_17a8
./mtl cache-inspect 20260305_17a8 --detail   # Full per-illustration details
```

### Convert visual thought logs to Markdown (editorial review)
```bash
./mtl visual-thinking 20260305_17a8
./mtl visual-thinking 20260305_17a8 --split          # One file per illustration
./mtl visual-thinking 20260305_17a8 --with-cache     # Include Art Director's Notes
```

---

## 9. Validation Checklist

After a successful Phase 1.6 run, verify:

- [ ] `data/<volume_id>/visual_cache.json` exists and is valid JSON
- [ ] Cache entry count matches illustration count in `manifest.json → assets[]`
- [ ] `manifest.json → pipeline_state.multimodal_processor.status` indicates completion
- [ ] `stats.blocked == 0` or review blocked entries manually with `cache-inspect --detail`
- [ ] Each cache entry has all nine required fields (spot-check 2–3 entries)
- [ ] `pov_character` fields use canonical EN names from `metadata_en.character_names`
- [ ] `visual_eps_band` values are valid (`HOT` / `WARM` / `NEUTRAL` / `COOL` / `COLD`)
- [ ] Thought logs in `data/<volume_id>/THINKING/` are present (if thinking budget > 0)
- [ ] Run `./mtl cache-inspect <volume_id>` — section output shows correct counts

---

*Last verified: 2026-03-05*

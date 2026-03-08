# Phase 1.55 — Full-LN Cache Rich Metadata Enrichment

> **Section 6 · Rich Metadata Cache**  
> Also covers: **Phase 1.56** — Translator's Guidance Brief (Section 7)

---

## 1. Purpose

Phase 1.55 solves the **continuity gap** that exists when translating a long-form novel volume-by-volume: the translator's context window can only hold a fraction of the total text, causing drift in character voice, relationship dynamics, and cultural references across chapters.

The phase:
1. Caches the **full JP volume text** as a structured resource (full-LN cache)
2. Calls Gemini Flash to perform a **whole-volume metadata enrichment** pass that adds rich continuity fields (`character_registry`, `cultural_glossary`, `timeline_map`, etc.) to `metadata_en`
3. Optionally links a **series bible** to inject cross-volume continuity context

This enriched metadata is injected into every Phase 2 translation prompt, giving the translator a deep, consistent reference without per-chapter re-analysis.

---

## 2. Entry Points

| Layer | Identifier |
|-------|-----------|
| Python module | `pipeline.metadata_processor.rich_metadata_cache` |
| Invoked via | `python -m pipeline.metadata_processor.rich_metadata_cache` |
| Controller method | `MTLController.run_phase1_55(volume_id)` in `scripts/mtl.py` |
| Cache-only variant | `MTLController.run_phase1_55_cache_only(volume_id)` |
| Cache-only flag | `--cache-only` on the module CLI |

Controller command:
```python
[sys.executable, "-m", "pipeline.metadata_processor.rich_metadata_cache",
 "--volume", volume_id]
# Cache-only (no metadata overwrite):
[..., "--cache-only"]
```

---

## 3. Inputs

| Input | Source | Notes |
|-------|--------|-------|
| `--volume <volume_id>` | CLI arg | Must have Phase 1 + 1.5 completed |
| `manifest.json` | `data/<vol>/manifest.json` | Chapter list, existing `metadata_en` |
| Chapter Markdown files | `data/<vol>/chapters/` | Full JP text assembled for cache |
| Series bible | `bibles/<series_id>.json` (when linked) | Cross-volume continuity context |
| `--cache-only` | Optional flag | Build/verify cache path without overwriting metadata |

---

## 4. Outputs

| Output | Location | Description |
|--------|----------|-------------|
| Rich metadata patch | `data/<vol>/rich_metadata_cache_patch.json` | Delta of new/updated fields |
| `metadata_en` enriched fields | `manifest.json → metadata_en` | Merged after successful enrichment |
| Co-processor artifacts | `data/<vol>/` | `character_registry.json`, `cultural_glossary.json`, `timeline_map.json`, `idiom_transcreation_cache.json` |
| Pronoun-shift artifact | `WORK/<vol>/.context/pronoun_shift_events_<lang>.json` | Chapter-level `PRONOUN_SHIFT_EVENT` detection payload + `active_directives` |
| `pipeline_state.rich_metadata_cache` | `manifest.json` | Status, timestamp, cache readiness |

**Rich fields added to `metadata_en`:**
- `character_registry` — structured character database with relationships, arcs, pronouns
- `cultural_glossary` — JP-specific terms with localization guidance
- `timeline_map` — chapter-level event chronology
- `idiom_transcreation_cache` — volume-specific idiom mappings

**Ops note (Pronoun Shift Framework):**
- Phase 1.55 now writes `pronoun_shift_events_<lang>.json` to `.context` and mirrors detected chapter events into `metadata_<lang>.emotional_pronoun_shifts.events_by_chapter`.
- Each event includes `shift_from`, `shift_to`, `shift_archetype`, `detected_at_line`, and `active_directives` for downstream prompt control.

---

## 5. LLM Routing

| Parameter | Value |
|-----------|-------|
| Model | `gemini-3-flash-preview` |
| Temperature | `0.7` |
| Top-P | `0.95` |
| Top-K | `40` |
| Max output tokens | `65536` |
| Thinking budget | `-1` (adaptive) |
| Provider | Gemini (Google) |
| Config key | `translation.phase_models.'1_55'` in `config.yaml` |

> **Note:** The module docstring and `scripts/mtl.py` header reference "Gemini 2.5 Flash" as the intended model for this phase. The current `config.yaml` maps it to `gemini-3-flash-preview`. Verify which model name is active in your environment.

---

## 6. Prompt / Tool Dependencies

- Prompt construction: assembled inline by `RichMetadataCacheAgent._build_prompt()` in `pipeline/metadata_processor/rich_metadata_cache.py` (no external prompt file)
- Bible integration: `./mtl bible sync <volume_id>` must be run separately to link a series bible
- Co-processor output files are consumed by Phase 1.7-cp

**Ops note (Translator trigger behavior):**
- During Phase 2 prompt assembly, translator injects `<pronoun_shift_handling>` only when current chapter has events in `.context/pronoun_shift_events_<lang>.json` (or mirrored metadata state).
- Trigger is chapter-scoped and scene-aware: no event for chapter ⇒ no override block injected.

---

## 7. Failure Modes & Guardrails

| Failure | Symptom | Recovery |
|---------|---------|---------|
| Phase 1 or 1.5 not completed | Hard error; agent exits | Run prerequisite phases first |
| Gemini cache resource creation fails | Warning logged; continues with direct call | Check quota; retry |
| Series bible not linked | Skips bible context; logs info | Run `./mtl bible sync <volume_id>` to add cross-volume context |
| Partial enrichment (some fields missing) | `pipeline_state.rich_metadata_cache.status` warns | Re-run; use `--cache-only` to verify cache integrity |
| Phase 2 `--phase1-55-mode` conflict | Controlled by `skip|overwrite|auto|ask` CLI modes | See Phase 2 docs for mode descriptions |
| User manually purges cache state | Cache state cleared from manifest | Re-run phase 1.55 before Phase 2 |

**Full-LN Cache Gate:** When Phase 1.6 or Phase 2 run as standalone commands, an interactive gate (`Full-LN Cache Gate`) prompts whether to build/verify the cache before proceeding. In non-interactive shells, it auto-proceeds with cache mode `on`.

---

## 8. How to Run

### Standard run (enrich metadata + build cache)
```bash
./mtl phase1.55 20260305_17a8
```

### Cache-only (build cache without overwriting metadata_en)
```bash
# This is used internally by Phase 2 when --phase1-55-mode skip is set
./mtl phase1.55 20260305_17a8  # no direct cache-only CLI flag in wrapper
# Use python directly:
python -m pipeline.metadata_processor.rich_metadata_cache --volume 20260305_17a8 --cache-only
```

### Inspect cache state after run
```bash
./mtl status 20260305_17a8
```

---

## 9. Validation Checklist

After a successful Phase 1.55 run, verify:

- [ ] `manifest.json → pipeline_state.rich_metadata_cache.status` is present and not `failed`
- [ ] `data/<volume_id>/rich_metadata_cache_patch.json` exists with non-empty content
- [ ] `manifest.json → metadata_en` contains `character_registry` and/or `cultural_glossary`
- [ ] If a bible was linked: `manifest.json` references the bible and cross-volume fields are populated
- [ ] `data/<volume_id>/character_registry.json` exists if co-processor artifacts were generated
- [ ] Run `./mtl status <volume_id>` — Section 6 badge should be ✓

---

---

# Phase 1.56 — Translator's Guidance Brief (Batch Pre-Analysis)

> **Section 7 · Translation Brief Agent**

---

## 1. Purpose

Phase 1.56 produces a **single reference document** (the "Guidance Brief") by running a full-corpus pre-analysis pass over the entire JP volume using a fast Gemini Flash model. This brief is then injected into **every Anthropic batch translation prompt** in Phase 2, providing:

- Volume-wide tone and genre signature
- Recurring stylistic patterns the translator must maintain
- Character-specific dialect/register notes not captured in `character_profiles`
- Localization decisions that apply across all chapters

The brief is generated once and cached. Phase 2 batch mode checks for its presence and skips re-generation on subsequent runs unless `--force-brief` is passed.

---

## 2. Entry Points

| Layer | Identifier |
|-------|-----------|
| Python module | `pipeline.post_processor.translation_brief_agent` |
| Invoked via | `python -m pipeline.post_processor.translation_brief_agent` |
| Controller method | `PipelineController.run_phase1_56(volume_id, force, enable_prequel_brief_injection)` in `scripts/mtl.py` |

Controller command:
```python
[sys.executable, "-m", "pipeline.post_processor.translation_brief_agent",
 "--volume", volume_id]
# Force re-generation:
[..., "--force"]
# Enable sequel-aware prequel brief injection:
[..., "--enable-prequel-brief-injection"]
```

---

## 3. Inputs

| Input | Source | Notes |
|-------|--------|-------|
| `--volume <volume_id>` | CLI arg | Phase 1 + 1.5 + 1.55 prerequisite |
| `manifest.json` | `WORK/<vol>/manifest.json` | Chapter list, metadata, sequel context |
| Full chapter text | `WORK/<vol>/JP/*.md` | Assembled for full-corpus analysis |
| `--force` | Optional flag | Re-generate even if brief is cached |
| `--enable-prequel-brief-injection` | Optional CLI flag | Force-enable sequel prequel brief injection for this run |
| `translation.phase1_56_prequel_brief_injection.enabled` | `config.yaml` | Default gate for sequel prequel brief injection (default: `false`) |
| `translation.phase1_56_prequel_brief_injection.max_chars` | `config.yaml` | Max chars loaded from prequel brief into prompt continuity block |

---

## 4. Outputs

| Output | Location | Description |
|--------|----------|-------------|
| Guidance brief document | `WORK/<vol>/.context/TRANSLATION_BRIEF.md` | Markdown reference doc injected into Phase 2 prompts |
| Brief cache metadata | `WORK/<vol>/.context/TRANSLATION_BRIEF.meta.json` | Chapter file signature + prequel-injection signature for cache invalidation |
| Runtime audit line | process logs | `[P1.56][PREQUEL] ... reason_code=...` diagnostics |

---

## 5. LLM Routing

| Parameter | Value |
|-----------|-------|
| Model | Gemini Flash (fast pass) — _(exact model name: not found in codebase — verify `translation_brief_agent.py`)_ |
| Provider | Gemini (Google) for analysis; output is injected into Anthropic batch prompts |
| Temperature | _(not found in codebase — verify)_ |
| Config key | _(not found in codebase — verify)_ |

> The brief is generated by Gemini but **consumed by the Anthropic translator** (Phase 2 batch path). It bridges the two provider stacks.

---

## 6. Prompt / Tool Dependencies

- Prompt construction: inline in `pipeline.post_processor.translation_brief_agent` _(verify)_
- Output injected into Phase 2 via `config.yaml → anthropic.batch.cache_shared_brief: true`

---

## 7. Failure Modes & Guardrails

| Failure | Symptom | Recovery |
|---------|---------|---------|
| Missing Phase 1 / 1.5 | Error; agent exits | Run prerequisites |
| Brief already exists | Skipped (cached); re-run with `--force-brief` in batch mode | Use `--force-brief` or `--force` flag |
| Prequel injection disabled | `[P1.56][PREQUEL] ... reason_code=P156_PREQUEL_BRIEF_DISABLED` | Enable via config or `--enable-prequel-brief-injection` |
| Not a sequel volume | `reason_code=P156_PREQUEL_NOT_SEQUEL` | Ensure `metadata.series_index > 1` when sequel behavior is expected |
| Bible unavailable | `reason_code=P156_PREQUEL_BIBLE_UNAVAILABLE` | Verify bible resolve/link and `volumes_registered` integrity |
| Prequel volume unresolved | `reason_code=P156_PREQUEL_VOLUME_NOT_FOUND` | Ensure prequel `volume_id` exists in bible registry |
| Prequel brief missing/empty | `reason_code=P156_PREQUEL_BRIEF_MISSING` / `P156_PREQUEL_BRIEF_EMPTY` | Run Phase 1.56 for prequel volume first |
| Prequel injected | `reason_code=P156_PREQUEL_BRIEF_READY`, `injected=true` | Expected success path; no action needed |
| Gemini analysis failure | Warning in batch pipeline; continues | `run_phase1_56` failure is non-fatal in `run_batch()` — Phase 2 proceeds without brief |
| `translator_provider != "anthropic"` | Brief still generated; not injected if not using Anthropic | Verify `config.yaml → translator_provider` |

Prequel reason-code reference:

| Reason code | Meaning |
|------------|---------|
| `P156_PREQUEL_BRIEF_DISABLED` | Feature gate off (config and CLI override absent) |
| `P156_PREQUEL_NOT_SEQUEL` | Current volume not recognized as sequel (`series_index <= 1`) |
| `P156_PREQUEL_BIBLE_UNAVAILABLE` | Could not resolve series bible / predecessor registry |
| `P156_PREQUEL_VOLUME_NOT_FOUND` | No valid predecessor `volume_id` found from bible registry |
| `P156_PREQUEL_BRIEF_MISSING` | Prequel `.context/TRANSLATION_BRIEF.md` missing |
| `P156_PREQUEL_BRIEF_EMPTY` | Prequel brief file exists but has no usable content |
| `P156_PREQUEL_BRIEF_READY` | Prequel brief loaded and injected into prompt |

---

## 8. How to Run

### Standalone
```bash
./mtl phase1.56 20260305_17a8
```

### Standalone with sequel-aware prequel brief injection
```bash
./mtl phase1.56 20260305_17a8 --enable-prequel-brief-injection
```

### Force re-generation
```bash
./mtl batch 20260305_17a8 --force-brief
```

### As part of full batch pipeline
```bash
./mtl batch 20260305_17a8
# Automatically runs: phase1.5 → phase1.55 → phase1.56 → phase1.6 → phase1.7 → phase2 (batch)
```

### Batch pipeline with sequel-aware prequel brief injection
```bash
./mtl batch 20260305_17a8 --enable-prequel-brief-injection
```

---

## 9. Validation Checklist

After a successful Phase 1.56 run, verify:

- [ ] `WORK/<vol>/.context/TRANSLATION_BRIEF.md` exists and is non-empty
- [ ] `WORK/<vol>/.context/TRANSLATION_BRIEF.meta.json` exists and has chapter signature metadata
- [ ] If prequel injection enabled: metadata sidecar includes `prequel_brief_injection` signature block
- [ ] Brief content is non-empty and covers all chapters
- [ ] If using Anthropic batch mode: `config.yaml → anthropic.batch.cache_shared_brief: true`
- [ ] Re-run is skipped on second invocation (caching works) — confirm by checking timestamp
- [ ] Logs contain `[P1.56][PREQUEL] ... reason_code=...` for audit traceability

---

*Last verified: 2026-03-06*

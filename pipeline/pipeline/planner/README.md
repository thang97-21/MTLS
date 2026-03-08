# Phase 1.7 — Stage 1 Scene Planner (Narrative Beat + Rhythm Scaffold)

> **Section 9 · Scene Planning Agent**  
> Also covers: **Phase 1.7-cp** — Co-Processor Pack (Section 9 Co-Processor)

---

## 1. Purpose

Phase 1.7 implements the **v1.6 Stage 1 architecture**: before any chapter is translated, a dedicated planning pass reads the raw JP text and constructs a structured `ScenePlan` that the translator (Phase 2, Stage 2) treats as a binding scaffold.

The planner answers three questions per chapter:
1. **What are the narrative beats?** — Each chapter is decomposed into `SceneBeat` objects with `beat_type`, `emotional_arc`, `dialogue_register`, and `target_rhythm`.
2. **Who owns the POV?** — `pov_tracking` segments identify which character's cognitive/emotional frame controls the prose across contiguous spans.
3. **What do characters sound like here?** — `character_profiles` capture per-chapter speech bias, emotional state, and denial/victory speech patterns.

Additional annotations the planner produces:
- **Culture Bleed Risk** — flags JP phrases that LLMs commonly mistranslate by emotional-tone substitution, along with forbidden EN substitutions
- **EPS Band per scene** — `HOT` / `WARM` / `NEUTRAL` / `COOL` / `COLD` grounding for the translator's register choices

The planner **does not translate**. Its output is pure structural analysis in JSON.

---

## 2. Entry Points

| Layer | Identifier |
|-------|-----------|
| Planning agent class | `pipeline.planner.scene_planner.ScenePlanningAgent` |
| Planner agent module | `pipeline.planner.agent` |
| Invoked via | `python -m pipeline.planner.agent` |
| Controller method | `MTLController.run_phase1_7(volume_id, chapters, force, temperature, max_output_tokens)` |
| Co-Processor controller method | `MTLController.run_phase1_7_coprocessor(volume_id)` |

Controller command:
```python
[sys.executable, "-m", "pipeline.planner.agent",
 "--volume", volume_id,
 "--temperature", "0.3",       # default from config '1_7' override
 "--max-output-tokens", "65535"]
# Optional:
[..., "--chapters", "chapter_01", "chapter_03"]   # subset
[..., "--force"]                                    # overwrite existing plans
```

---

## 3. Inputs

| Input | Source | Notes |
|-------|--------|-------|
| `--volume <volume_id>` | CLI arg | Phase 1 prerequisite |
| `manifest.json` | `data/<vol>/manifest.json` | Chapter list; `scene_plan_file` field checked for existing plans |
| Chapter JP text | `data/<vol>/chapters/chapter_NN.md` | Raw JP source text per chapter |
| `metadata_en.character_names` | `manifest.json` | **Canonical character name reference block** — injected into prompt header |
| `config/planning_config.json` | `pipeline/config/planning_config.json` | Beat types, dialogue registers, rhythm targets |
| `--chapters` | Optional list | Limit to specific chapter IDs |
| `--force` | Optional flag | Overwrite existing `*_scene_plan.json` files |

**Canonical Name Injection:** The prompt explicitly instructs the planner to use EXACT canonical names from the character name reference block in all `pov_tracking.character` fields. Generic labels like "Narrator" or "Protagonist" are prohibited.

---

## 4. Outputs

All outputs written to `data/<volume_id>/scene_plans/`:

| Output | Path | Description |
|--------|------|-------------|
| Per-chapter scene plan | `scene_plans/<chapter_id>_scene_plan.json` | Structured `ScenePlan` JSON |
| Manifest backlink | `manifest.json → chapters[].scene_plan_file` | Relative path to plan file |
| Pipeline state | `manifest.json → pipeline_state.scene_planner` | `status`, `generated_plans`, `skipped_plans`, `failed_plans`, `model` |

**`ScenePlan` JSON structure:**

```jsonc
{
  "chapter_id": "chapter_03",
  "overall_tone": "...",
  "pacing_strategy": "...",
  "pov_tracking": [
    { "character": "Yuki Shirogane", "start_line": 1, "end_line": 45, "description": "..." }
  ],
  "character_profiles": {
    "Yuki Shirogane": {
      "emotional_state": "...", "sentence_bias": "...",
      "victory_patterns": [...], "denial_patterns": [...], "relationship_dynamic": "..."
    }
  },
  "scenes": [
    {
      "id": "scene_01",
      "beat_type": "escalation",
      "emotional_arc": "...",
      "dialogue_register": "flustered_defense",
      "target_rhythm": "short_fragments",
      "illustration_anchor": false,
      "eps_band": "WARM",
      "culture_bleed_risk": "high",
      "culture_bleed_category": "...",
      "culture_bleed_source_phrase": "...",
      "culture_bleed_warning": "...",
      "culture_bleed_forbidden": ["..."]
    }
  ]
}
```

---

## 5. LLM Routing

| Parameter | Value |
|-----------|-------|
| Model | `gemini-3-flash-preview` |
| Temperature | `0.5` _(config.yaml `translation.phase_models.'1_7'.temperature`)_ |
| Top-P | `0.95` |
| Top-K | `40` |
| Max output tokens | `65535` |
| Thinking budget | `-1` (adaptive) |
| Provider | Gemini (Google) |
| Config key | `translation.phase_models.'1_7'` in `config.yaml` |
| Runtime override | `--temperature` and `--max-output-tokens` CLI flags |
| Router | `pipeline.common.phase_llm_router.PhaseLLMRouter` |
| Client | `pipeline.common.gemini_client.GeminiClient` |

The controller defaults to `temperature=0.3` when calling `run_phase1_7()` directly, while `config.yaml` specifies `0.5`. The CLI flag on `pipeline.planner.agent` takes precedence.

Caching is **disabled** for Phase 1.7 (`enable_caching=False` in `PhaseLLMRouter.get_client()`).

---

## 6. Prompt / Tool Dependencies

The planning prompt is built dynamically by `ScenePlanningAgent._build_planning_prompt()` using values loaded from `planning_config.json`:

- `beat_types` — enumeration of valid `beat_type` values injected into prompt
- `dialogue_registers` — suggested register vocabulary
- `rhythm_targets` — mapping of rhythm labels to word-count ranges

Planning config location: `pipeline/config/planning_config.json`

**Koji Fox Method Alignment:** Phase 1.7 implements the "Method Acting & Drafting Phase" from the Koji Fox localization method. The planner's two-stage output (structure analysis → character voice snapshot) mirrors the `<thinking>` block Stage 1 (ANALYSIS) and Stage 2 (RHYTHM DRAFTING) flow that the translator must follow. Scene plans produced here become the binding scaffold that ensures production-stage prose meets the rhythm, EPS, and register targets the planner identified.

**POV inference rules** (embedded in prompt):
1. Interior monologue, knowledge asymmetry, private reactions > JP pronouns as evidence
2. Canonical names from character reference block — no generic labels
3. Single-narrator chapters must still emit one `pov_tracking` entry

**Culture bleed detection:** Phase 1.7 specifically flags JP phrases that LLMs commonly mistranslate by emotional-tone substitution, specifying forbidden EN substitutions. This prevents the most common localization failure mode: replacing JP understatement with EN directness or vice versa.

---

## 7. Failure Modes & Guardrails

| Failure | Symptom | Recovery |
|---------|---------|---------|
| `manifest.json` missing | Hard error, agent exits | Run Phase 1 first |
| Chapter JP text file missing | Chapter skipped; counted as `failed_plans` | Re-run Phase 1 to restore chapter files |
| Gemini returns empty response | Up to `empty_response_retries` retries (default 2) with `empty_retry_backoff_seconds` delay | Automatic |
| Gemini safety block | `enable_safety_sanitized_retry: true` — sanitized retry attempt | Automatic |
| Invalid `beat_type` in output | Planner validates against allowed list from config | Warning logged; plan still saved |
| POV character not in canonical list | Warning logged | Review `pov_tracking` entries manually |
| Partial failure (some chapters fail) | `pipeline_state.scene_planner.status == "partial"` | Controller logs warning; pipeline continues |
| `planning_config.json` not found | Defaults used: `beat_types`, `dialogue_registers`, `rhythm_targets` fall back to hardcoded lists | Provide config file for production runs |

---

## 8. How to Run

### Standard Phase 1.7 (all chapters)
```bash
./mtl phase1.7 20260305_17a8
```

### Specific chapters only
```bash
# Not directly exposed in ./mtl wrapper — use python directly:
python -m pipeline.planner.agent --volume 20260305_17a8 --chapters chapter_01 chapter_05
```

### Force re-plan (overwrite existing plans)
```bash
python -m pipeline.planner.agent --volume 20260305_17a8 --force
```

### Co-Processor Pack (context-offload refresh only)
```bash
./mtl phase1.7-cp 20260305_17a8
```

### As part of full batch pipeline
```bash
./mtl batch 20260305_17a8
# Phase 1.7 runs automatically as Step 5/6
```

---

## 9. Validation Checklist

After a successful Phase 1.7 run, verify:

- [ ] `data/<volume_id>/scene_plans/` directory exists and contains one `*_scene_plan.json` per chapter
- [ ] `manifest.json → pipeline_state.scene_planner.status` is `completed` (not `partial`)
- [ ] `generated_plans` count equals chapter count (or expected subset)
- [ ] `failed_plans` == `0`; if > 0, re-run for missing chapters with `--force`
- [ ] Spot-check one plan file: `pov_tracking[].character` uses canonical names from `metadata_en.character_names`
- [ ] Spot-check one plan file: `scenes[].beat_type` values are from `planning_config.json` beat list
- [ ] Spot-check one plan file: `scenes[].eps_band` values are valid (`HOT`/`WARM`/`NEUTRAL`/`COOL`/`COLD`)
- [ ] `manifest.json → chapters[].scene_plan_file` is populated for all chapters

---

---

## Sub-Phase: 1.7-cp — Co-Processor Pack (Standalone Context Offload)

### Purpose

Phase 1.7-cp is an on-demand maintenance command that refreshes the four **context-offload co-processor artifacts** without running the full scene planning pass or overwriting `metadata_en`. It rebuilds:

- `character_registry.json`
- `cultural_glossary.json`
- `timeline_map.json`
- `idiom_transcreation_cache.json`

These files are consumed by Phase 2 to offload recurring lookup context outside the main prompt, reducing token costs for large volumes.

### Entry Point

Controller method: `MTLController.run_phase1_7_coprocessor(volume_id)` in `scripts/mtl.py`

Delegates to: `pipeline.metadata_processor.rich_metadata_cache --volume <vol> --cache-only`

```python
[sys.executable, "-m", "pipeline.metadata_processor.rich_metadata_cache",
 "--volume", volume_id,
 "--cache-only"]
```

### Inputs

- Phase 1 + Phase 1.5 completed (manifest + `metadata_en`)
- Existing `rich_metadata_cache_patch.json` preferred but not required

### Outputs

Refreshed co-processor files in `data/<volume_id>/`:
- `character_registry.json`
- `cultural_glossary.json`
- `timeline_map.json`
- `idiom_transcreation_cache.json`

### When to Use

- After updating `metadata_en` character profiles: refresh the registry
- Before Phase 2 when the cultural glossary may be stale (new chapters added)
- As a lightweight alternative to re-running full Phase 1.55

### How to Run

```bash
./mtl phase1.7-cp 20260305_17a8
```

### Validation

- [ ] All four co-processor JSON files exist and are up to date in `data/<volume_id>/`
- [ ] Timestamps are newer than last Phase 1.5 or 1.55 run

---

*Last verified: 2026-03-05*

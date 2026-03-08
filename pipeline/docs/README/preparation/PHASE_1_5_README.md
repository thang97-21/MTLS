# Phase 1.5 — Schema Autoupdate + Metadata Translation

> [← Root README](../../../../README.md) · [← Pipeline Index](../../README.md)

> **Section 3 · Metadata Processor Agent**  
> Also covers: **Phase 1.51** (Koji Fox Voice RAG Expansion) and **Phase 1.52** (EPS Band Backfill)

---

## 1. Purpose

Phase 1.5 takes the raw JP volume metadata produced by the Librarian and generates a fully translated `metadata_en` block that the translator, scene planner, and quality auditors consume. It performs two tasks in sequence:

1. **Schema Autoupdate** — Upgrades legacy V2/V4 metadata schemas to the v3 enhanced schema without losing existing translated fields.
2. **Metadata Translation** — Calls Gemini to translate title, author, chapter titles, and character names into the target language.

A critical design constraint: the agent **preserves** any existing v3 enhanced schema fields (`character_profiles`, `localization_notes`, `keigo_switch`, `character_voice_fingerprints`, `scene_intent_map`, `signature_phrases`, `schema_version`) and only updates the translation fields. This makes Phase 1.5 safe to re-run.

---

## 2. Entry Points

| Layer | Identifier |
|-------|-----------|
| Python module | `pipeline.metadata_processor.agent` |
| Invoked via | `python -m pipeline.metadata_processor.agent` |
| Controller method | `MTLController.run_phase1_5(volume_id)` in `scripts/mtl.py` |
| Phase 1.51 flag | `--voice-rag-only` on the same module |
| Phase 1.52 flag | `--eps-only` on the same module |

Controller command:
```python
[sys.executable, "-m", "pipeline.metadata_processor.agent",
 "--volume", volume_id,
 "--sequel-mode"]   # added when a prequel volume is detected
```

---

## 3. Inputs

| Input | Source | Notes |
|-------|--------|-------|
| `--volume <volume_id>` | CLI arg | Resolved volume directory under `data/` |
| `manifest.json` | `data/<vol>/manifest.json` | Must exist (Phase 1 prerequisite) |
| `metadata_en` scaffold | `manifest.json → metadata_en` | Updated in-place |
| `target_language` | `config.yaml → project.target_language` | `en` or `vn` |
| Language config | `config.yaml → project.languages.<lang>` | Prompt templates, grammar RAG config |
| Sequel detection | Sibling volume manifests | Auto-detected by title prefix matching (first 10 chars) |
| `--sequel-mode` | Auto-injected flag | Inherits metadata from detected prequel |
| `--ignore-sequel` | `--verbose` interactive choice | Forces fresh metadata generation |

---

## 4. Outputs

All changes are written back to `data/<volume_id>/manifest.json` and a separate `metadata_en.json`:

| Output | Location | Description |
|--------|----------|-------------|
| `metadata_en.title_en` | `manifest.json` | Translated title |
| `metadata_en.author_en` | `manifest.json` | Translated author name |
| `metadata_en.chapters[].title_en` | `manifest.json` | Per-chapter translated titles |
| `metadata_en.character_names` | `manifest.json` | JP → EN/VN character name mapping |
| `metadata_en.glossary` | `manifest.json` | Terms glossary |
| `metadata_en.translation_timestamp` | `manifest.json` | ISO timestamp of last run |
| `pipeline_state.metadata_processor` | `manifest.json` | `status`, `target_language`, `schema_preserved` |
| Side-effect | `data/<vol>/metadata_en.json` | _(not found in codebase — verify standalone file)_ |

**Preserved fields (never overwritten):**
`character_profiles`, `localization_notes`, `keigo_switch`, `schema_version`, `character_voice_fingerprints`, `signature_phrases`, `scene_intent_map`

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
| Config key | `translation.phase_models.'1_5'` in `config.yaml` |
| Router | `pipeline.common.phase_llm_router.PhaseLLMRouter` |
| Client | `pipeline.common.gemini_client.GeminiClient` |

---

## 6. Prompt / Tool Dependencies

- **Prompt files:**
  - `prompts/metadata_processor_prompt.xml` — English-target metadata translation prompt
  - `prompts/metadata_processor_prompt_vn.xml` — Vietnamese-target metadata translation prompt
  - Selected at runtime based on `config.yaml → project.target_language`
  - Contains Section 5B: KOJI FOX CHARACTER VOICE ANALYSIS for `character_voice_fingerprints` generation
- Schema autoupdate logic: `pipeline.metadata_processor.schema_autoupdate.SchemaAutoUpdater`
- Name order normalization: `pipeline.common.name_order_normalizer.normalize_payload_names`
- Afterword detection: `pipeline.common.chapter_kind.is_afterword_chapter`
- Placeholder stripping: `strip_json_placeholders()` (inline in `agent.py`)

---

## 7. Failure Modes & Guardrails

| Failure | Symptom | Recovery |
|---------|---------|---------|
| `manifest.json` missing | Hard error, agent exits | Run Phase 1 first |
| Gemini returns unescaped JSON quotes | `sanitize_json_strings()` auto-corrects | Logged; transparent to user |
| Volume number extraction fails | `None` returned; title uses raw JP | Check JP title format; manual override in manifest |
| Sequel detected in non-verbose mode | Auto-inherits; logs warning | Check `metadata_en.json` character list before Phase 2 |
| Placeholder tokens in LLM response | `strip_json_placeholders()` removes them | Re-run if fields are empty |
| Schema upgrade breaks custom fields | Preserved by design; logs preserved set | Check `schema_preserved` flag in pipeline state |

The agent is **idempotent**: re-running updates translation fields while preserving v3 schema elements.

---

## 8. How to Run

### Standard Phase 1.5
```bash
./mtl phase1.5 20260305_17a8
```

### Force fresh metadata (ignore sequel detection)
```bash
# Run with --verbose to get the interactive sequel prompt
./mtl phase1.5 20260305_17a8 --verbose
# Select [N] when prompted about sequel mode
```

### Phase 1.51 — Koji Fox Voice RAG backfill only
```bash
./mtl phase1.51 20260305_17a8
```

### Phase 1.52 — EPS Band backfill only
```bash
./mtl phase1.52 20260305_17a8
```

---

## 9. Validation Checklist

After a successful Phase 1.5 run, verify:

- [ ] `manifest.json → pipeline_state.metadata_processor.status == "completed"`
- [ ] `manifest.json → metadata_en.title_en` is non-empty
- [ ] `manifest.json → metadata_en.author_en` is non-empty
- [ ] `manifest.json → metadata_en.chapters` contains translated titles for all chapters
- [ ] `manifest.json → metadata_en.character_names` has expected character count
- [ ] `manifest.json → metadata_en.schema_preserved == true` (if upgrading from existing v3)
- [ ] Run `./mtl metadata <volume_id>` to inspect schema version and field completeness
- [ ] Run `./mtl metadata <volume_id> --validate` if schema compatibility is in question

---

## Sub-Phase: 1.51 — Koji Fox Voice RAG Expansion

### Purpose

Adds or refreshes the `character_voice_fingerprints` and `scene_intent_map` fields in `metadata_en` without regenerating the full metadata translation. These fields drive the voice-accuracy RAG layer during translation.

### Entry Point

Same module (`pipeline.metadata_processor.agent`) with `--voice-rag-only` flag.

### Inputs

- Requires Phase 1 + Phase 1.5 completed (manifest + existing `metadata_en`)
- Full chapter text is built into an in-memory cache for voice analysis

### Outputs

- `metadata_en.character_voice_fingerprints[]` — per-character speech pattern fingerprints
- `metadata_en.scene_intent_map` — scene-level intent annotations

### How to Run

```bash
./mtl phase1.51 20260305_17a8
```

### When to Use

- After Phase 1.5, when `character_voice_fingerprints` is empty or missing
- When adding new characters discovered in later volumes
- Re-run if voice fingerprints appear generic or incorrect in Phase 2 output

---

## Sub-Phase: 1.52 — EPS Band Backfill

### Purpose

Backfills `emotional_proximity_signals` (EPS band annotations) at the chapter level without regenerating any other metadata. EPS bands encode the emotional distance between characters per scene, guiding tone selection in Phase 2.

The **EPS (Emotional Proximity Signal)** system replaced the legacy RTAS (Relationship-Trust-Arc-State) model. It derives a quantitative emotional proximity score from six Japanese corpus signals:

| Signal | Weight | Description |
|--------|--------|-------------|
| `keigo_shift` | 0.30 | Honorific form changes between characters |
| `sentence_length_delta` | 0.20 | Sentence length deviation from character baseline |
| `particle_signature` | 0.15 | Intimacy-marker particles (ね、よ vs です、ます) |
| `pronoun_shift` | 0.15 | First-person pronoun intimacy level |
| `dialogue_volume` | 0.10 | Ratio of dialogue lines to total lines |
| `direct_address` | 0.10 | Frequency of protagonist's name in dialogue |

The score maps to 5 voice bands:

| Band | Score Range | Voice Effect |
|------|------------|-------------|
| `COLD` | ≤ −0.5 | Maximum formality, guarded brevity |
| `COOL` | −0.5 to −0.1 | Polite distance, controlled warmth |
| `NEUTRAL` | −0.1 to +0.1 | Character baseline register |
| `WARM` | +0.1 to +0.5 | Casual intimacy, relaxed formality |
| `HOT` | ≥ +0.5 | Vulnerable openness, direct emotional statements |

### Entry Point

Same module (`pipeline.metadata_processor.agent`) with `--eps-only` flag.

### Inputs

- Requires Phase 1 + Phase 1.5 completed
- Full text cache is built in-memory for EPS analysis

### Outputs

- `metadata_en.chapters[].emotional_proximity_signals` — per-chapter EPS band values
- `metadata_en.chapters[].scene_intents` — scene-intent annotations

### LLM Routing

> Uses same model/temperature as Phase 1.5 (`gemini-3-flash-preview`, temp 0.7).  
> Prompt identifies it as: `"EPS-only metadata backfill agent for Japanese light novels"`

### How to Run

```bash
./mtl phase1.52 20260305_17a8
```

### When to Use

- When Phase 1.7 scene plans contain EPS bands but `metadata_en` chapters lack them
- When auditors report EPS inconsistencies between chapters

---

*Last verified: 2026-03-05*

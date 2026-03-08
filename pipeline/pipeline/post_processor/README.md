# Phase 2.5 — Volume Bible Update Agent (Post-Translation Bible Writeback)

> **Section 11 · Series Bible Synthesis**  
> Also covers: **BibleSyncAgent** (Pull/Push), **BibleController** (bible CRUD)

---

## 1. Purpose

Phase 2.5 is the pipeline's **continuity writeback layer**. After Phase 2 has translated an entire volume and quality control has cleared all chapters, Phase 2.5 synthesizes the full translated text with a Gemini LLM call and pushes enriched data back to the series bible so every future volume inherits:

1. **Character voice profiles** — updated speech patterns, dialect, formality levels derived from the final EN translation
2. **Arc resolution** — how the volume's character arcs resolved, stored as cross-volume continuity context
3. **Translation decisions** — localization choices (name rendering, cultural adaptations, recurring idioms) from this volume
4. **Continuity pack** — a JSON artifact the next volume's Phase 2 pre-loads into its `<Continuity_Pack>` context block

The design principle: **the bible is advisory during translation, authoritative only for carry-forward.** Phase 2 reads the bible as a context hint; Phase 2.5 writes back confirmed decisions. The local volume manifest always wins during translation.

---

## 2. Entry Points

| Layer | Identifier |
|-------|-----------|
| Agent class | `VolumeBibleUpdateAgent` in `pipeline/post_processor/volume_bible_update_agent.py` |
| Invocation | Called internally by `TranslatorAgent._run_phase25_bible_update()` at end of `translate_volume()` |
| BibleSyncAgent (pull/push) | `pipeline.metadata_processor.bible_sync.BibleSyncAgent` |
| BibleController | `pipeline.translator.series_bible.BibleController` |
| Config key | `translation.phase25.run_bible_update: true` in `config.yaml` |

Phase 2.5 is **not** a standalone CLI command in `./mtl`. It runs automatically as the final step of `translate_volume()` when `run_bible_update` is configured and QC clearance passes.

The `BibleSyncAgent` pull/push operations are separate:
- **Pull** runs during Phase 1.5 (metadata translation) to inject canonical terms
- **Push** runs after Phase 1.5 final manifest write to export new discoveries

---

## 3. Inputs

| Input | Source | Notes |
|-------|--------|-------|
| `en_dir` | `WORK/<vol>/EN/` | Fully translated EN chapter files from Phase 2 |
| `manifest` | `manifest.json` loaded by `TranslatorAgent` | Character profiles, bible ID, name-order policy |
| `qc_cleared` | Internal Phase 2 flag | If False, Phase 2.5 is skipped entirely |
| `target_language` | `config.yaml → project.target_language` | `en` or `vn` |
| `series bible` | `bibles/<series_id>.json` | Loaded by `BibleController`; written back after update |
| `config.yaml → translation.phase25` | `run_bible_update`, model, `max_output_tokens` | Phase 2.5 behavior switches |

**QC Gate:** Phase 2.5 will abort with `error: "qc_not_cleared"` if the QC gate has not been satisfied. This prevents bible corruption from unreviewed translations.

---

## 4. Outputs

| Output | Location | Description |
|--------|----------|-------------|
| Updated series bible | `bibles/<series_id>.json` | Voice profiles, arc resolution, and translation decisions appended/merged |
| Continuity pack | `WORK/<vol>/.context/continuity_pack_phase25.json` _(verify exact path)_ | Pre-formatted context pack for next volume's Phase 2 |
| Local translation decisions | `WORK/<vol>/translation_decisions.json` _(verify)_ | Volume-scoped localization decisions for auditor reference |
| Bible index updated | `bibles/_index.json` | Volume linked to series under `series_id → volumes[]` |
| Phase 2.5 log | `manifest.json → pipeline_state.phase25` _(verify)_ | Status, `voice_profiles_added`, `decisions_written` |

**`VolumeBibleUpdateResult` summary fields:**
- `success` — `True` if run completed without exception
- `voice_profiles_added` — number of character voice profiles enriched in bible
- `decisions_written` — number of translation decisions written locally
- `continuity_pack_path` — path to generated continuity pack

---

## 5. LLM Routing

| Parameter | Value |
|-----------|-------|
| Model | `gemini-2.5-pro` (default, set in `VolumeBibleUpdateAgent.__init__`) |
| Max output tokens | `65535` |
| Temperature | _(defaults to Gemini client default; verify in `volume_bible_update_agent.py`)_ |
| Provider | Gemini (Google) |
| Config key | `translation.phase25.model` in `config.yaml` (when overriding default) |
| Client | Same `GeminiClient` instance passed from `TranslatorAgent` |

The synthesis prompt (`_build_synthesis_prompt`) instructs the LLM to act as a "long-running translation bible updater" with:
- Full translated volume text (assembled from `en_dir`)
- Existing manifest metadata for context
- Target language specification
- Output: JSON with `character_voices`, `arc_resolution`, `translation_decisions` keys

---

## 6. Bible Sync: Pull & Push (Phase 1.5 Operations)

The `BibleSyncAgent` performs bidirectional sync at Phase 1.5 time, independent of Phase 2.5:

### Pull (Bible → Manifest)

Runs **before** `batch_translate_ruby` in Phase 1.5's metadata translation step.

**Purpose:** Inject known canonical terms from the series bible into the metadata translation prompt so the LLM skips already-translated names and inherits canonical glossary terms.

**Output:** `BiblePullResult` with:
- `known_terms` — JP → EN flat glossary from bible
- `known_characters` — JP → EN character name mapping
- `context_block` — formatted `<Series_Bible>` block for injection into translation prompt
- `characters_inherited`, `geography_inherited`, `weapons_inherited`, `eps_states_inherited` — stats

### Push (Manifest → Bible)

Runs **after** Phase 1.5 final manifest write.

**Purpose:** Export newly translated terms (characters, glossary, geography, weapons) from the manifest back to the bible for use in subsequent volumes.

**Output:** `BiblePushResult` with:
- `characters_enriched` — new character records added
- `terms_added` — total new glossary entries

### Extended Push (`push_extended`) — Phase 2.5 Path

Runs from `VolumeBibleUpdateAgent.run()` after full-volume synthesis.

**Purpose:** Push enriched voice profiles and arc resolution (not available at Phase 1.5 time) along with any additional terms discovered in the final translation.

---

## 7. BibleController — Bible CRUD

`pipeline.translator.series_bible.BibleController` manages the physical bible files:

| Operation | Method | Description |
|-----------|--------|-------------|
| Load bible | `get_bible(series_id)` | Load `bibles/<series_id>.json` |
| Create bible | `create_bible(series_id, ...)` | New empty bible with bootstrapped metadata |
| Import from manifest | `import_from_manifest(manifest, series_id)` | Seed bible from manifest character/glossary data |
| Link volume | `link_volume(volume_id, series_id)` | Register volume in `_index.json` |
| Save | `bible.save()` | Write updated bible JSON to disk |

**Series ID derivation:** `BibleSyncAgent._build_series_id()` constructs a deterministic `series_id` from the cleaned series name (e.g., `わたしが恋人になれるわけない` → `watashiga_koibito`). This is stable across all volumes in the same series.

---

## 8. Failure Modes & Guardrails

| Failure | Symptom | Recovery |
|---------|---------|---------|
| `qc_not_cleared` | Phase 2.5 skipped; logged as `error: qc_not_cleared` | Fix failed chapters in Phase 2; QC must pass before writeback |
| Empty translated volume | `error: empty_en_volume` | Verify EN chapter files exist and are non-empty |
| LLM synthesis failure | Exception caught; `success=False` logged | Re-trigger by re-setting `qc_cleared` and re-running Phase 2 with `run_bible_update: true` |
| Bible file not found | `resolve()` returns False; bible bootstrapped from scratch | Non-fatal; new bible created |
| Name-order policy mismatch | `_normalize_bible_name_order()` runs auto-correction | Logged; bible saved with normalized names |
| Bible update disabled | No-op; Phase 2.5 agent is `None` | Set `translation.phase25.run_bible_update: true` in `config.yaml` |
| Bible push failure | Warning logged; `voice_profiles_added = 0` | Check bible file permissions and JSON validity |

---

## 9. How to Trigger Phase 2.5

Phase 2.5 runs automatically when enabled. To trigger it:

### Enable in config
```yaml
# config.yaml
translation:
  phase25:
    run_bible_update: true
```

### Run Phase 2 (Phase 2.5 fires at end)
```bash
./mtl phase2 20260305_17a8
# Translator completes → QC gate passes → Phase 2.5 bible update runs
```

### Force a bible sync pull/push (Phase 1.5 level)
```bash
./mtl phase1.5 20260305_17a8
# BibleSyncAgent.pull() + push() run automatically during metadata translation
```

### Manual bible management CLI commands
```bash
./mtl bible sync 20260305_17a8        # Trigger bible sync (pull + push)
./mtl bible list                       # List all series bibles
./mtl bible show <series_id>           # Show a specific bible content
```

---

## 10. Validation Checklist

After Phase 2 + Phase 2.5 complete, verify:

- [ ] `bibles/<series_id>.json` updated — `last_modified` timestamp is newer than Phase 2 run
- [ ] `bibles/<series_id>.json → voice_profiles` has ≥ 1 new entry per translated character
- [ ] `bibles/_index.json → series.<series_id>.volumes` includes this volume's ID
- [ ] `VolumeBibleUpdateResult.success == True` in Phase 2 completion log
- [ ] `voice_profiles_added > 0` in Phase 2 completion log
- [ ] Continuity pack file exists in `WORK/<vol>/.context/`
- [ ] Next volume: re-run `./mtl phase1.5 <next_vol>` to confirm bible pull inherits this volume's data
- [ ] `BiblePullResult.characters_inherited > 0` on next-volume pull (cross-volume inheritance working)

---

*Last verified: 2026-03-05*

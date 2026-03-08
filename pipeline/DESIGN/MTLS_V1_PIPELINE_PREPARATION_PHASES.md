# MTLS v1 — Pipeline Direction: Preparation Phases 1–9 and Translator (Section 10)

**Document type:** Formal operational direction and technical specification  
**Abbreviation:** MTLS (MTL Studio)  
**Version:** 1.0  
**Status:** Canonical  
**Scope:** All preparation phases (Sections 1, 3, 4, 5, 6, 7, 8, 9) and the production translation phase (Section 10). Phase numbering, purpose, inputs, outputs, LLM routing, failure modes, and operating procedures.  
**Primary sources:** Per-phase README files, `scripts/mtl.py` controller documentation, `config.yaml` configuration, pipeline module docstrings  
**Last updated:** 2026-03-06

---

## Table of Contents

1. [Domain Overview](#1-domain-overview)
2. [Standard Run Order and CLI Reference](#2-standard-run-order-and-cli-reference)
3. [Phase 1 — Librarian (Section 1)](#3-phase-1--librarian-section-1)
4. [Phase 1.5 — Schema Autoupdate + Metadata Translation (Section 3)](#4-phase-15--schema-autoupdate--metadata-translation-section-3)
5. [Phase 1.51 — Voice RAG Expansion (Section 4)](#5-phase-151--voice-rag-expansion-section-4)
6. [Phase 1.52 — EPS Band Backfill (Section 5)](#6-phase-152--eps-band-backfill-section-5)
7. [Phase 1.55 — Rich Metadata Cache Enrichment (Section 6)](#7-phase-155--rich-metadata-cache-enrichment-section-6)
8. [Phase 1.56 — Translator's Guidance Brief (Section 7)](#8-phase-156--translators-guidance-brief-section-7)
9. [Phase 1.6 — Multimodal Processor (Section 8)](#9-phase-16--multimodal-processor-section-8)
10. [Phase 1.7 — Stage 1 Scene Planner (Section 9)](#10-phase-17--stage-1-scene-planner-section-9)
11. [Phase 1.7-cp — Co-Processor Pack Refresh](#11-phase-17-cp--co-processor-pack-refresh)
12. [Phase 2 — Translator, Koji Fox Engine (Section 10)](#12-phase-2--translator-koji-fox-engine-section-10)
13. [Cross-Phase Data Flow](#13-cross-phase-data-flow)
14. [Manifest State Machine](#14-manifest-state-machine)
15. [Full Batch Pipeline](#15-full-batch-pipeline)

---

## 1. Domain Overview

The Preparation domain encompasses every phase executed before the production translator. Its collective mission: take a raw Japanese EPUB and produce a rich, fully annotated context package — extracted text, metadata, voice fingerprints, EPS bands, full-corpus enrichment, visual analysis, and structural scene plans — so the translator can operate with maximum fidelity.

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MTLS v1 · PREPARATION + TRANSLATION DOMAIN MAP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  §1  Phase 1          Librarian              JP EPUB → Markdown + manifest
  §3  Phase 1.5        Metadata Translation   title, author, chapters, characters → EN
  §4  Phase 1.51       Voice RAG Expansion    character_voice_fingerprints backfill
  §5  Phase 1.52       EPS Band Backfill      emotional_proximity_signals backfill
  §6  Phase 1.55       Rich Metadata Cache    full-LN cache + Gemini metadata enrichment
  §7  Phase 1.56       Translation Brief      full-corpus batch pre-analysis → guidance brief
  §8  Phase 1.6        Multimodal Processor   Gemini Vision → Art Director's Notes
  §9  Phase 1.7        Scene Planner          narrative beats + rhythm scaffold per chapter
  §9c Phase 1.7-cp     Co-Processor Pack      co-processor artifact refresh (maintenance)
  §10 Phase 2          Translator             Koji Fox Engine → EN/VN chapter prose
                                                                        
  ──────────────────────────────────────────────────────────────────
  STANDARD FULL-PIPELINE SEQUENCE:
  1  →  1.5  →  1.55  →  1.56  →  1.6  →  1.7  →  2
  ──────────────────────────────────────────────────────────────────
  ON-DEMAND (backfill, not in sequence):
  1.51  (voice fingerprints)       1.52  (EPS bands)
  1.7-cp (co-processor artifacts)
```

### Phase-Level Summary Table

| Phase | Section | Name | Model Family | Role | CLI |
|-------|---------|------|-------------|------|-----|
| 1 | §1 | Librarian | None (deterministic) | Extract EPUB → Markdown + manifest | `./mtl phase1 <epub>` |
| 1.5 | §3 | Metadata Translation | Gemini Flash | Translate metadata fields to EN/VN | `./mtl phase1.5 <vol>` |
| 1.51 | §4 | Voice RAG Expansion | Gemini Flash | Backfill voice fingerprints | `./mtl phase1.51 <vol>` |
| 1.52 | §5 | EPS Band Backfill | Gemini Flash | Backfill EPS bands per chapter | `./mtl phase1.52 <vol>` |
| 1.55 | §6 | Rich Metadata Cache | Gemini Flash | Full-LN cache + metadata enrichment | `./mtl phase1.55 <vol>` |
| 1.56 | §7 | Translation Brief | Gemini Flash → Anthropic | Generate guidance brief for batch | `./mtl phase1.56 <vol>` |
| 1.6 | §8 | Multimodal Processor | Gemini Flash Vision | Illustration → Art Director's Notes | `./mtl phase1.6 <vol>` |
| 1.7 | §9 | Scene Planner | Gemini Flash | Narrative beats + character rhythm scaffold | `./mtl phase1.7 <vol>` |
| 1.7-cp | §9c | Co-Processor Pack | Gemini Flash | Refresh co-processor artifacts (cache-only) | `./mtl phase1.7-cp <vol>` |
| 2 | §10 | Translator | Claude Opus 4.6 | Literary translation (batch) | `./mtl batch <vol>` |

---

## 2. Standard Run Order and CLI Reference

### 2.1 Standard Full-Volume Pipeline

```bash
./mtl run INPUT/novel_vol3.epub
# Auto-generates volume ID and runs phases 1 → 2 in sequence
```

### 2.2 Batch Pipeline (Recommended for Production)

```bash
./mtl batch <volume_id>
# Runs: phase1.5 → phase1.55 → phase1.56 → phase1.6 → phase1.7 → phase2 (batch mode)
```

### 2.3 Manual Phase-by-Phase

```bash
./mtl phase1    INPUT/novel_vol3.epub
./mtl phase1.5  <volume_id>
./mtl phase1.55 <volume_id>
./mtl phase1.56 <volume_id>
./mtl phase1.6  <volume_id>
./mtl phase1.7  <volume_id>
./mtl phase2    <volume_id>
```

### 2.4 Skip Phase 1.6 (No Illustrations)

```bash
./mtl phase1    INPUT/novel_vol3.epub
./mtl phase1.5  <volume_id>
./mtl phase1.55 <volume_id>
./mtl phase1.56 <volume_id>
./mtl phase1.7  <volume_id>
./mtl phase2    <volume_id>
```

### 2.5 On-Demand Backfill Phases

```bash
./mtl phase1.51   <volume_id>   # Backfill voice fingerprints
./mtl phase1.52   <volume_id>   # Backfill EPS bands
./mtl phase1.7-cp <volume_id>   # Refresh co-processor pack
```

### 2.6 Status Check

```bash
./mtl status <volume_id>        # Shows all phase completion badges
./mtl list                      # List all volumes + status summary
./mtl metadata <volume_id>      # Inspect metadata fields
```

---

## 3. Phase 1 — Librarian (Section 1)

### 3.1 Purpose

The Librarian is the pipeline's ingestion gate. It unpacks a Japanese EPUB, extracts every chapter as structured Markdown, harvests illustration asset references, and writes the canonical `manifest.json` that every downstream phase depends on. **No other phase can run until Phase 1 completes successfully.**

Key outcomes:
- One `.md` file per chapter under `WORK/<vol>/chapters/`
- `manifest.json` with chapter list, asset index, and pipeline state flags
- Initial `metadata_en` scaffold populated from EPUB OPF metadata
- Volume-ID assignment (timestamp-based if not supplied: `YYYYMMDD_<hash4>`)

### 3.2 Architecture

Phase 1 is **entirely deterministic** — no LLM calls are made. The processing pipeline:

```text
  Raw EPUB (.epub)
       │
       ▼
  [1] EPUB extraction          EPUBExtractor — unzip, locate OPF/NCX
       │
       ▼
  [2] OPF metadata parsing     MetadataParser — title, author, language, publication date
       │
       ▼
  [3] TOC parsing              TOCParser — EPUB3 Navigation Document or EPUB2 NCX
       │
       ▼
  [4] Spine parsing            SpineParser — reading order, illustration page detection
       │
       ▼
  [5] Pre-TOC detection        config.pre_toc_detection — unlisted color plates before TOC
       │
       ▼
  [6] Volume act detection     _detect_volume_acts() — multi-act chapters, Kodansha groups
       │
       ▼
  [7] Hybrid TOC/spine fallback _validate_toc_completeness() — spine fallback when TOC < threshold
       │
       ▼
  [8] XHTML → Markdown         XHTMLToMarkdownConverter — clean JP markdown per chapter
       │
       ▼
  [9] Ruby extraction          extract_ruby_from_directory() — furigana → character scaffold
       │
       ▼
  [10] Image extraction        ImageExtractor + catalog_images() — illustration catalog
       │
       ▼
  [11] Content splitting       ContentSplitter / KodanshaSplitter — publisher-specific splits
       │
       ▼
  manifest.json + chapter/*.md + illustrations/
```

**Initial character profile scaffold:** Built deterministically from `ruby_names[]` extracted from furigana. Character profiles at Phase 1 contain `speech_pattern: "[TO BE FILLED]"` placeholders — populated in Phase 1.5/1.51.

### 3.3 LLM Routing

| Parameter | Value |
|-----------|-------|
| Model | None — fully deterministic |
| LLM calls | Zero at Phase 1 |
| LLM config key | `translation.phase_models.'1'` in `config.yaml` (gemini-3-flash-preview; unused) |

### 3.4 Inputs and Outputs

| Input | Description |
|-------|-------------|
| `epub_path` | Path to `.epub` file (CLI positional arg) |
| `--volume-id` | Optional. Auto-generates as `YYYYMMDD_<hash4>` if omitted |
| `--target-lang` | `en` or `vn` (from `config.yaml`) |
| `--ref-validate` | Optional: triggers reference cross-validation |

| Output | Path | Description |
|--------|------|-------------|
| `manifest.json` | `WORK/<vol>/manifest.json` | Master state document |
| Chapter Markdown | `WORK/<vol>/chapters/chapter_NN.md` | JP text, one per chapter |
| Illustrations | `WORK/<vol>/illustrations/` | Extracted image files |
| Initial metadata scaffold | `manifest.json → metadata_en` | OPF-derived, untranslated |

### 3.5 Failure Modes

| Failure | Recovery |
|---------|---------|
| EPUB file not found | Verify path; re-run |
| Malformed EPUB structure | Verify EPUB validity; check `META-INF/container.xml` |
| Duplicate volume ID | Supply new `--volume-id` or delete existing dir |
| Illustration extraction failure | Non-fatal; Phase 1.6 will report missing files |

Phase 1 is **idempotent** — re-runs safely. Existing translated fields in `metadata_en` are not preserved; re-run Phase 1.5 after any re-extraction.

### 3.6 Validation Checklist

- [ ] `WORK/<volume_id>/manifest.json` exists and is valid JSON
- [ ] `manifest.json → pipeline_state.librarian.status == "completed"`
- [ ] `manifest.json → chapters[]` has expected chapter count
- [ ] Chapter Markdown files present under `WORK/<vol>/chapters/`
- [ ] Illustration files (if any) under `WORK/<vol>/illustrations/`
- [ ] `manifest.json → metadata.title` populated with JP title
- [ ] `./mtl status <volume_id>` — §1 badge shows ✓

---

## 4. Phase 1.5 — Schema Autoupdate + Metadata Translation (Section 3)

### 4.1 Purpose

Phase 1.5 takes the raw JP volume metadata produced by the Librarian and generates a fully translated `metadata_en` block covering: volume title, author, all chapter titles, all character names, and a terms glossary. It also performs **Schema Autoupdate** — upgrading legacy V2/V4 metadata schemas to the current v3 enhanced schema without losing existing translated fields.

A critical design constraint: Phase 1.5 **preserves** existing v3 schema fields and only updates translation fields. This makes it safe to re-run.

For sequel volumes, Phase 1.5 automatically detects a prequel (by title prefix matching) and inherits metadata, avoiding re-translation of known character names.

### 4.2 Entry Point

| Layer | Module |
|-------|--------|
| Python module | `pipeline.metadata_processor.agent` |
| Controller method | `MTLController.run_phase1_5(volume_id)` |
| Phase 1.51 flag | `--voice-rag-only` |
| Phase 1.52 flag | `--eps-only` |

### 4.3 LLM Routing

| Parameter | Value |
|-----------|-------|
| Model | `gemini-3-flash-preview` |
| Temperature | `0.7` |
| Top-P | `0.95` |
| Top-K | `40` |
| Max output tokens | `65,536` |
| Thinking budget | `-1` (adaptive) |
| Config key | `translation.phase_models.'1_5'` in `config.yaml` |

### 4.4 Inputs and Outputs

**Key inputs:**
- `manifest.json` from Phase 1 (prerequisite)
- `metadata_en` scaffold — updated in-place
- `config.yaml → project.target_language` (`en` or `vn`)
- Sibling volume manifests — for sequel auto-detection

**Outputs to `manifest.json`:**

| Field | Description |
|-------|-------------|
| `metadata_en.title_en` | Translated title |
| `metadata_en.author_en` | Translated author name |
| `metadata_en.chapters[].title_en` | Per-chapter translated titles |
| `metadata_en.character_names` | JP → EN/VN character name mapping |
| `metadata_en.glossary` | Terms glossary |
| `pipeline_state.metadata_processor` | Status, target_language, schema_preserved |

**Fields never overwritten (preserved):**
`character_profiles`, `localization_notes`, `keigo_switch`, `character_voice_fingerprints`, `signature_phrases`, `scene_intent_map`, `schema_version`

### 4.5 Prompts

- `prompts/metadata_processor_prompt.xml` — English target
- `prompts/metadata_processor_prompt_vn.xml` — Vietnamese target
- Selected at runtime from `config.yaml → project.target_language`
- Contains **Section 5B: KOJI FOX CHARACTER VOICE ANALYSIS** for `character_voice_fingerprints` generation

### 4.6 Failure Modes

| Failure | Recovery |
|---------|---------|
| `manifest.json` missing | Run Phase 1 first |
| Gemini returns unescaped JSON quotes | `sanitize_json_strings()` auto-corrects |
| Volume number extraction fails | Check JP title format; manual override in manifest |
| Sequel auto-detected incorrectly | Re-run with `--verbose` and select `[N]` at sequel prompt |

### 4.7 Validation Checklist

- [ ] `manifest.json → pipeline_state.metadata_processor.status == "completed"`
- [ ] `metadata_en.title_en` is non-empty
- [ ] `metadata_en.author_en` is non-empty
- [ ] `metadata_en.chapters` has translated titles for all chapters
- [ ] `metadata_en.character_names` has expected character count
- [ ] `./mtl metadata <volume_id>` — schema version and field completeness visible

---

## 5. Phase 1.51 — Voice RAG Expansion (Section 4)

### 5.1 Purpose

Adds or refreshes `character_voice_fingerprints` and `scene_intent_map` in `metadata_en` without regenerating the full metadata translation. These fields drive the **Voice Accuracy RAG layer** during Phase 2 translation — ensuring each character speaks in a consistent, distinctive register throughout the volume.

### 5.2 Entry Point

Same module as Phase 1.5: `pipeline.metadata_processor.agent --voice-rag-only`

### 5.3 Operation

The agent:
1. Loads all existing character profiles from `metadata_en`
2. Builds a full chapter text in-memory from `WORK/<vol>/chapters/`
3. Calls Gemini to analyze each character's speech patterns across all chapters
4. Writes per-character `character_voice_fingerprints[]` entries with `speech_pattern`, `register`, `key_phrases`, `relationship_dynamics`
5. Writes `scene_intent_map` annotations for recurring scene types

### 5.4 Outputs

| Field | Description |
|-------|-------------|
| `metadata_en.character_voice_fingerprints[]` | Per-character speech pattern fingerprints |
| `metadata_en.scene_intent_map` | Scene-level intent annotations |

### 5.5 When to Run

- After Phase 1.5 when `character_voice_fingerprints` is empty or missing
- When adding new characters discovered in later volumes
- When Phase 2 voice fingerprint startup log shows `✓ Koji Fox: 0 voice fingerprint(s) indexed`

### 5.6 CLI

```bash
./mtl phase1.51 <volume_id>
```

---

## 6. Phase 1.52 — EPS Band Backfill (Section 5)

### 6.1 Purpose

Backfills `emotional_proximity_signals` (EPS band annotations) at the chapter level without regenerating any other metadata.

### 6.2 The EPS System

The **Emotional Proximity Signal (EPS)** system is the emotional-register backbone of the MTLS voice system. It replaced the legacy RTAS (Relationship-Trust-Arc-State) model. EPS derives a quantitative emotional proximity score from six JP corpus signals:

| Signal | Weight | Description |
|--------|--------|-------------|
| `keigo_shift` | 30% | Honorific form changes between characters |
| `sentence_length_delta` | 20% | Sentence length deviation from character baseline |
| `particle_signature` | 15% | Intimacy-marker particles (ね、よ vs です、ます) |
| `pronoun_shift` | 15% | First-person pronoun intimacy level (俺/boku/watashi) |
| `dialogue_volume` | 10% | Ratio of dialogue lines to total lines |
| `direct_address` | 10% | Frequency of protagonist's name in dialogue |

The weighted score maps to five voice bands:

```text
  ────────────────────────────────────────────────────────────
       COLD          COOL         NEUTRAL        WARM          HOT
  ≤ −0.5      −0.5 to −0.1   −0.1 to +0.1   +0.1 to +0.5   ≥ +0.5
  ────────────────────────────────────────────────────────────
  Max          Polite         Character       Casual          Vulnerable
  formality    distance       baseline        intimacy        openness
  guarded      controlled     archetype-      relaxed         direct
  brevity      warmth         consistent      formality       emotion
  ────────────────────────────────────────────────────────────
```

### 6.3 Entry Point

Same module as Phase 1.5: `pipeline.metadata_processor.agent --eps-only`

### 6.4 LLM Routing

Same configuration as Phase 1.5 (`gemini-3-flash-preview`, temp 0.7).
Prompt identifies itself as: `"EPS-only metadata backfill agent for Japanese light novels"`

### 6.5 Outputs

| Field | Description |
|-------|-------------|
| `metadata_en.chapters[].emotional_proximity_signals` | Per-chapter EPS band values |
| `metadata_en.chapters[].scene_intents` | Scene-intent annotations |

### 6.6 When to Run

- When Phase 1.7 scene plans contain EPS bands but `metadata_en` chapters lack them
- When auditors report EPS inconsistencies between chapters
- When starting translation of a new volume with a long EPS arc

### 6.7 CLI

```bash
./mtl phase1.52 <volume_id>
```

---

## 7. Phase 1.55 — Rich Metadata Cache Enrichment (Section 6)

### 7.1 Purpose

Phase 1.55 solves the **continuity gap** inherent in long-form volume-by-volume translation: the translator's context window holds only a fraction of the total text, causing drift in character voice, relationship dynamics, and cultural references across chapters.

The phase:
1. Assembles the **full JP volume text** as a structured in-memory cache
2. Calls Gemini Flash to perform a **whole-volume metadata enrichment pass** — adding rich continuity fields to `metadata_en`
3. Produces four **co-processor artifact files** consumable by Phase 2 to offload recurring lookup context
4. Optionally integrates a **Series Bible** for cross-volume continuity

The enriched metadata is injected into every Phase 2 translation prompt, guaranteeing deep, consistent reference without per-chapter re-analysis overhead.

### 7.2 Entry Points

| Command | Operation |
|---------|-----------|
| `./mtl phase1.55 <vol>` | Full enrich: build cache + overwrite metadata_en enriched fields |
| `python -m pipeline.metadata_processor.rich_metadata_cache --volume <vol> --cache-only` | Build/verify cache only — no `metadata_en` overwrite |

### 7.3 LLM Routing

| Parameter | Value |
|-----------|-------|
| Model | `gemini-3-flash-preview` |
| Temperature | `0.7` |
| Top-P / Top-K | `0.95 / 40` |
| Max output tokens | `65,536` |
| Config key | `translation.phase_models.'1_55'` |
| Prompt construction | Inline `RichMetadataCacheAgent._build_prompt()` (no external prompt file) |

### 7.4 Outputs

| Artifact | Location | Description |
|----------|----------|-------------|
| Rich metadata patch | `WORK/<vol>/rich_metadata_cache_patch.json` | Delta of new/updated fields |
| `metadata_en` enriched fields | `manifest.json → metadata_en` | Merged after enrichment |
| `character_registry.json` | `WORK/<vol>/` | Structured character database with relationships, arcs, pronouns |
| `cultural_glossary.json` | `WORK/<vol>/` | JP-specific terms with localization guidance |
| `timeline_map.json` | `WORK/<vol>/` | Chapter-level event chronology |
| `idiom_transcreation_cache.json` | `WORK/<vol>/` | Volume-specific idiom mappings |

**Rich fields added to `metadata_en`:**
- `character_registry` — character database with relationships and arc positions
- `cultural_glossary` — JP-specific terms with localization guidance
- `timeline_map` — chapter-level event chronology
- `idiom_transcreation_cache` — volume-specific idiomatic phrase mappings

### 7.5 Series Bible Integration

```bash
./mtl bible sync <volume_id>   # Link a series bible before Phase 1.55
./mtl phase1.55 <volume_id>    # Bible context injected into enrichment call
```

When a series bible is linked, cross-volume character continuity and canonical name decisions from prior volumes are embedded in the enrichment context.

### 7.6 Full-LN Cache Gate

When Phase 1.6 or Phase 2 run as standalone commands without Phase 1.55 having completed, an interactive **Full-LN Cache Gate** prompts whether to build/verify the cache before proceeding. In non-interactive shells, it auto-proceeds with cache mode `on`.

### 7.7 Failure Modes

| Failure | Recovery |
|---------|---------|
| Phase 1 or 1.5 not completed | Hard error; run prerequisites |
| Gemini cache resource creation fails | Retries with direct call; check quota |
| Series bible not linked | Skips bible context; run `./mtl bible sync <vol>` |
| Partial enrichment | Re-run; use `--cache-only` to verify cache integrity |

### 7.8 Validation Checklist

- [ ] `manifest.json → pipeline_state.rich_metadata_cache.status` present and not `failed`
- [ ] `WORK/<vol>/rich_metadata_cache_patch.json` exists with non-empty content
- [ ] `metadata_en` contains `character_registry` and/or `cultural_glossary`
- [ ] `WORK/<vol>/character_registry.json` exists
- [ ] `./mtl status <volume_id>` — §6 badge shows ✓

---

## 8. Phase 1.56 — Translator's Guidance Brief (Section 7)

### 8.1 Purpose

Phase 1.56 produces a single reference document — the **Guidance Brief** — by running a full-corpus pre-analysis pass over the entire JP volume. This brief is injected into **every Anthropic batch translation prompt** in Phase 2, providing:

- Volume-wide tone and genre signature
- Recurring stylistic patterns the translator must maintain
- Character-specific dialect/register notes not captured in `character_profiles`
- Localization decisions that apply globally across all chapters

The brief is generated **once and cached**. Phase 2 batch mode checks for its presence and skips re-generation unless `--force-brief` is passed.

The brief bridges the two provider stacks: generated by Gemini (fast full-corpus pass), consumed by Anthropic (batch translation). This pattern achieves high analytical coverage at Gemini Flash pricing while reserving Opus 4.6's tokens exclusively for literary output.

### 8.2 Entry Points

| Command | Operation |
|---------|-----------|
| `./mtl phase1.56 <vol>` | Generate guidance brief |
| `./mtl batch <vol> --force-brief` | Regenerate brief in batch pipeline |
| `./mtl batch <vol>` | Generate only if not cached |

### 8.3 LLM Routing

| Parameter | Value |
|-----------|-------|
| Model | Gemini Flash (fast full-corpus analysis pass) |
| Analysis provider | Gemini (Google) |
| Output consumer | Anthropic batch path (Phase 2) |
| Config key | Verify `translation_brief_agent.py` for current model name |
| Cache behavior | Brief cached after first generation; reused in subsequent batch runs |

### 8.4 Outputs

| Artifact | Location | Description |
|----------|----------|-------------|
| Guidance brief | `WORK/<vol>/translation_brief.md` | Markdown reference doc |
| Pipeline state | `manifest.json → pipeline_state.translation_brief` | Status, timestamp, model |

### 8.5 Batch Integration

Phase 1.56 output is injected into Phase 2 batch prompts via:
```yaml
# config.yaml
anthropic:
  batch:
    cache_shared_brief: true
```

When `cache_shared_brief: true`, the guidance brief is included in the shared system prompt cache block, meaning it is created once and re-used across all 12 chapter requests in the batch at cache-read pricing ($0.25/MTok).

### 8.6 Failure Modes

| Failure | Recovery |
|---------|---------|
| Phase 1/1.5 incomplete | Hard error; run prerequisites |
| Brief already cached | Skipped (normal behavior); use `--force-brief` to regenerate |
| Gemini analysis failure | Non-fatal in `run_batch()` — Phase 2 proceeds without brief |

### 8.7 Validation Checklist

- [ ] `WORK/<vol>/translation_brief.md` exists and is non-empty
- [ ] `manifest.json → pipeline_state.translation_brief.status` indicates completion
- [ ] Brief covers all chapters
- [ ] Second invocation is skipped (cache working) — verify by timestamp

---

## 9. Phase 1.6 — Multimodal Processor (Section 8)

### 9.1 Purpose

Phase 1.6 is the pipeline's **Art Director**. It pre-bakes visual analysis for every illustration in the volume before translation begins. A Gemini multimodal vision model examines each illustration and generates structured **Art Director's Notes (ADN)** covering:

- Composition and visual framing
- Emotional delta (surface appearance vs. underlying emotion)
- `pov_character` identification using canonical EN names
- EPS band assignment from visual evidence
- Subtext inference per character
- Translation vocabulary register recommendations

ADN are stored in `WORK/<vol>/visual_cache.json` and injected into Phase 2 prompts at translation time. This **CPU+GPU architecture** decouples illustration analysis from translation: vision cost is paid once per volume, not per chapter.

**Invariant:** ADN enhance vocabulary and register choices in translation — they do not alter plot content. Art Director's Notes are style guidance, never canon.

### 9.2 Entry Point

Phase 1.6 calls `VisualAssetProcessor` directly (not as a subprocess):

```python
from modules.multimodal.asset_processor import VisualAssetProcessor
processor = VisualAssetProcessor(volume_path, force_override=force_override)
stats = processor.process_volume()
```

Related modules:
- `modules.multimodal.integrity_checker` — pre-flight illustration validation
- `modules.multimodal.cache_manager.VisualCacheManager` — cache read/write
- `modules.multimodal.thought_logger.ThoughtLogger` — Gemini thinking trace storage
- `modules.multimodal.kuchie_visualizer` — kuchie color-plate character name extraction
- `modules.multimodal.prompt_injector` — assembles `<Visual_Cache>` XML blocks

### 9.3 LLM Routing

| Parameter | Value |
|-----------|-------|
| Model | `gemini-3-flash-preview` (vision) |
| Temperature | `0.3` |
| Top-P / Top-K | `0.95 / 40` |
| Max output tokens | `65,536` |
| Thinking budget | `-1` (adaptive) |
| Media resolution | `media_resolution_high` (1,120 tokens/image) |
| Safety config | All categories: `BLOCK_NONE` |
| Rate limit | `2 req/min` default |
| Max retries | `10` with exponential backoff |
| Config key | `translation.phase_models.'1_6'` |

### 9.4 Visual Cache Structure

Each `visual_cache.json` entry (9 fields per illustration):

| Field | Description |
|-------|-------------|
| `composition` | Panel layout, framing, focal point |
| `emotional_delta` | Gap between surface appearance and underlying emotion |
| `key_details` | `expressions`, `actions`, `environment`, `costume_significance` |
| `pov_character` | Canonical EN name of the foregrounded character |
| `subtext_inference` | Per-character unspoken emotional state |
| `translation_vocab` | Vocabulary register and tone recommendations |
| `visual_eps_band` | EPS band from visual evidence (`HOT`/`WARM`/`NEUTRAL`/`COOL`/`COLD`) |
| `arc_tracking` | Character arc signals visible in illustration |
| `prompt_injection` | Pre-formatted `<Visual_Cache>` XML block for Phase 2 injection |

### 9.5 Cache Invalidation

Each cache entry is keyed by a hash of `prompt + image_bytes + model`. Changing the analysis prompt or upgrading the Gemini model automatically invalidates stale entries.

### 9.6 Pre-Flight Illustration Integrity Check

Before any analysis, `check_illustration_integrity()` validates that all `epub_id` references in `manifest.json → assets[]` have corresponding image files. **Failures are fatal** — the phase aborts with actionable error messages listing the specific missing/malformed assets.

### 9.7 Failure Modes

| Failure | Recovery |
|---------|---------|
| Integrity check fails | Fix manifest `epub_id_to_cache_id` mapping or missing files |
| Gemini 429 (rate limit) | Exponential backoff; check `rate_limit.requests_per_minute: 2` |
| Safety block on illustration | Fallback text stored in cache; inspect with `cache-inspect --detail` |
| Full-LN cache gate declined | Re-run after Phase 1.55 completes |
| `force_override=False` | Already-cached illustrations skipped (normal behavior) |

### 9.8 CLI Reference

```bash
# Standard Phase 1.6
./mtl phase1.6 <volume_id>

# Skip full-LN cache prep
./mtl phase1.6 <volume_id> --full-ln-cache off

# Inspect visual analysis output
./mtl cache-inspect <volume_id>
./mtl cache-inspect <volume_id> --detail

# Export Gemini thinking traces to Markdown
./mtl visual-thinking <volume_id>
./mtl visual-thinking <volume_id> --split          # one file per illustration
./mtl visual-thinking <volume_id> --with-cache     # include Art Director's Notes
```

### 9.9 Validation Checklist

- [ ] `WORK/<vol>/visual_cache.json` exists and is valid JSON
- [ ] Cache entry count matches `manifest.json → assets[]` count
- [ ] `manifest.json → pipeline_state.multimodal_processor.status` completed
- [ ] `stats.blocked == 0` or blocked entries reviewed with `cache-inspect --detail`
- [ ] Each entry has all 9 required fields (spot-check 2–3)
- [ ] `pov_character` fields use canonical EN names from `metadata_en.character_names`
- [ ] `visual_eps_band` values are valid (`HOT`/`WARM`/`NEUTRAL`/`COOL`/`COLD`)
- [ ] `WORK/<vol>/THINKING/` contains thought logs (if thinking budget > 0)

---

## 10. Phase 1.7 — Stage 1 Scene Planner (Section 9)

### 10.1 Purpose

Phase 1.7 implements the **v1.6 Stage 1 architecture** of the Koji Fox method: before any chapter is translated, a dedicated planning pass reads the raw JP text and constructs a structured `ScenePlan` that the Phase 2 translator (Stage 2) treats as a binding scaffold.

The planner answers three questions per chapter:

1. **What are the narrative beats?** — Each chapter is decomposed into `SceneBeat` objects with `beat_type`, `emotional_arc`, `dialogue_register`, and `target_rhythm`.
2. **Who owns the POV?** — `pov_tracking` segments identify which character's cognitive/emotional frame controls the prose across contiguous spans.
3. **What do characters sound like here?** — `character_profiles` per-chapter capture speech bias, emotional state, and denial/victory speech patterns.

Additional outputs:
- **Culture Bleed Risk flags** — JP phrases that LLMs commonly mistranslate by emotional-tone substitution, with explicitly forbidden EN substitutions
- **EPS Band per scene** — grounding for register choice at the scene level

The planner **does not translate** — its output is pure structural analysis in JSON.

### 10.2 Entry Point

| Layer | Module |
|-------|--------|
| Planning agent class | `pipeline.planner.scene_planner.ScenePlanningAgent` |
| Controller method | `MTLController.run_phase1_7(volume_id, chapters, force, temperature, max_output_tokens)` |

### 10.3 Stage 1 / Stage 2 Alignment

Phase 1.7 implements the "Method Acting & Drafting Phase" from the Koji Fox localization method:

```text
  ┌────────────────────────────────────────────────────────┐
  │ STAGE 1 (Phase 1.7 — Scene Planner)                   │
  │                                                        │
  │  ANALYSIS: narrative beat decomposition                │
  │  · beat_type, emotional_arc, dialogue_register         │
  │  · pov_tracking per span                               │
  │  · culture_bleed_risk detection                        │
  │  · eps_band per scene                                  │
  │                                                        │
  │  CHARACTER SNAPSHOT: per-chapter voice state           │
  │  · emotional_state, sentence_bias                      │
  │  · victory_patterns, denial_patterns                   │
  │  · relationship_dynamic                                │
  └────────────────────────────────────────────────────────┘
              │
              │  scene_plan.json (binding scaffold)
              ▼
  ┌────────────────────────────────────────────────────────┐
  │ STAGE 2 (Phase 2 — Translator / Koji Fox Engine)      │
  │                                                        │
  │  · Receives ScenePlan as binding scaffold              │
  │  · Prose must meet beat_type + target_rhythm           │
  │  · Register must match dialogue_register + eps_band    │
  │  · POV must match pov_tracking spans                   │
  │  · Culture bleed warnings enforced (forbidden EN list) │
  └────────────────────────────────────────────────────────┘
```

### 10.4 LLM Routing

| Parameter | Value |
|-----------|-------|
| Model | `gemini-3-flash-preview` |
| Temperature | `0.5` (config.yaml) / `0.3` (controller default) |
| Top-P / Top-K | `0.95 / 40` |
| Max output tokens | `65,535` |
| Caching | **Disabled** (`enable_caching=False`) |
| Config key | `translation.phase_models.'1_7'` |
| Prompt construction | Dynamic: `ScenePlanningAgent._build_planning_prompt()` |
| Planning config | `pipeline/config/planning_config.json` |

### 10.5 ScenePlan JSON Schema

```jsonc
{
  "chapter_id": "chapter_03",
  "overall_tone": "...",
  "pacing_strategy": "...",
  "pov_tracking": [
    {
      "character": "Yuki Shirogane",   // MUST be canonical EN name
      "start_line": 1,
      "end_line": 45,
      "description": "..."
    }
  ],
  "character_profiles": {
    "Yuki Shirogane": {
      "emotional_state": "...",
      "sentence_bias": "...",
      "victory_patterns": ["..."],
      "denial_patterns": ["..."],
      "relationship_dynamic": "..."
    }
  },
  "scenes": [
    {
      "id": "scene_01",
      "beat_type": "escalation",           // from planning_config.json beat list
      "emotional_arc": "...",
      "dialogue_register": "flustered_defense",
      "target_rhythm": "short_fragments",
      "eps_band": "WARM",
      "culture_bleed_risk": "high",
      "culture_bleed_category": "...",
      "culture_bleed_source_phrase": "...",
      "culture_bleed_warning": "...",
      "culture_bleed_forbidden": ["..."]   // DO NOT use these EN substitutions
    }
  ]
}
```

**POV inference rules (embedded in planner prompt):**
1. Interior monologue, knowledge asymmetry, and private reactions take precedence over JP pronoun evidence
2. All `pov_tracking[].character` fields must use exact canonical names from the character reference block — no generic labels (`"Narrator"`, `"Protagonist"`)
3. Single-narrator chapters must emit exactly one `pov_tracking` entry

### 10.6 Failure Modes

| Failure | Recovery |
|---------|---------|
| Chapter JP text file missing | Chapter skipped (`failed_plans`); re-run Phase 1 to restore |
| Gemini returns empty response | Up to `empty_response_retries` retries (default 2) |
| Partial failure (some chapters fail) | `pipeline_state.scene_planner.status == "partial"` |
| POV character not in canonical list | Warning logged; review `pov_tracking` manually |
| Invalid `beat_type` in output | Warning logged; plan saved with non-validation-blocked fields |

### 10.7 CLI Reference

```bash
# Standard (all chapters)
./mtl phase1.7 <volume_id>

# Subset of chapters (via python module)
python -m pipeline.planner.agent --volume <vol> --chapters chapter_01 chapter_05

# Force re-plan (overwrite existing)
python -m pipeline.planner.agent --volume <vol> --force
```

### 10.8 Validation Checklist

- [ ] `WORK/<vol>/scene_plans/` exists with one `*_scene_plan.json` per chapter
- [ ] `manifest.json → pipeline_state.scene_planner.status == "completed"` (not `partial`)
- [ ] `generated_plans` count equals chapter count
- [ ] `failed_plans == 0`
- [ ] Spot-check: `pov_tracking[].character` uses canonical EN names
- [ ] Spot-check: `scenes[].beat_type` values from `planning_config.json`
- [ ] Spot-check: `scenes[].eps_band` valid (`HOT`/`WARM`/`NEUTRAL`/`COOL`/`COLD`)
- [ ] `manifest.json → chapters[].scene_plan_file` populated for all chapters

---

## 11. Phase 1.7-cp — Co-Processor Pack Refresh

### 11.1 Purpose

Phase 1.7-cp is an on-demand maintenance command that refreshes the four co-processor artifact files without running the full scene planning pass or overwriting `metadata_en`. It rebuilds the context-offload artifacts that Phase 2 uses to reduce token costs for large volumes.

### 11.2 Artifacts Refreshed

| File | Purpose |
|------|---------|
| `character_registry.json` | Structured character database with relationships, arcs, pronouns |
| `cultural_glossary.json` | JP-specific terms with localization guidance |
| `timeline_map.json` | Chapter-level event chronology |
| `idiom_transcreation_cache.json` | Volume-specific idiom mappings |

### 11.3 Implementation

Delegates to Phase 1.55 cache-only mode:
```python
[sys.executable, "-m", "pipeline.metadata_processor.rich_metadata_cache",
 "--volume", volume_id,
 "--cache-only"]
```

### 11.4 When to Run

- After updating character profiles in `metadata_en`: refresh the registry
- Before Phase 2 when the cultural glossary may be stale
- As a lightweight alternative to re-running full Phase 1.55

### 11.5 CLI

```bash
./mtl phase1.7-cp <volume_id>
```

---

## 12. Phase 2 — Translator, Koji Fox Engine (Section 10)

### 12.1 Purpose

Phase 2 is the Koji Fox literary translation engine. It consumes every artifact produced by the Preparation family (Phases 1–1.7) and generates a fully translated, Yen Press–grade English (or Vietnamese) chapter set.

The engine's design philosophy derives directly from Michael-Christopher Koji Fox's FFXVI localization method:

1. **English First** — prose rhythm, cadence, and naturalness take priority over literal JP syntax adherence
2. **Method Acting** — the translator maintains a distinct voice per character through the entire volume, modulated by EPS band
3. **Deep Involvement** — every available context artifact is injected before the first token of translation
4. **Canon Event Fidelity** — ADN and EPS bands guide *register and tone only* — no events are invented

### 12.2 Per-Chapter Execution Sequence

For each chapter, Phase 2:

```text
  [1] Pre-Phase-2 Invariant Gate
      → validate manifest completeness, scene plan, EPS coverage, voice fingerprint count, bible sync

  [2] Prompt context assembly
      → character voice directives (Voice RAG), arc directive (ArcTracker),
        scene plan scaffold, visual cache XML, EPS context,
        cultural glossary, series bible block, continuity pack,
        translation brief (batch shared block)

  [3] LLM call (Anthropic Batch / streaming / tool-mode)
      → Claude Opus 4.6, effort=max, adaptive thinking

  [4] Post-processing pipeline (14-pass deterministic validators)
      → CJK cleaner → grammar validator → tense validator →
        format normalizer → name-order normalizer → truncation validator →
        POV validator → reference validator → copyedit post-pass →
        AI-ism fixer → voice validator → Koji Fox naturalness test

  [5] Write EN/<chapter_id>.md
      + update manifest.json → translation_log
      + update .context/arc_tracker.json
      + update .context/continuity_pack.json
```

### 12.3 Entry Point

| Layer | Module |
|-------|--------|
| Python module | `pipeline.translator.agent` |
| Main class | `TranslatorAgent` |
| Volume translate | `TranslatorAgent.translate_volume()` |
| Batch translate | `TranslatorAgent.translate_volume_batch()` |
| Controller (batch) | `PipelineController.run_batch(volume_id, ...)` |

### 12.4 LLM Routing

**Anthropic — Production Path (Default)**

| Parameter | Value |
|-----------|-------|
| Model | `claude-opus-4-6` |
| Temperature | `1.0` |
| Max output tokens | `32,000` |
| Thinking mode | Adaptive (enabled via extended thinking) |
| Cache strategy | System prompt + metadata; TTL auto-promoted to 1h for batch |
| Context window | 200K standard; 1M beta (Usage Tier 4, `context-1m-2025-08-07`) |
| Config key | `translation.anthropic.model` |

**Batch Mode Parameters**

| Parameter | Value |
|-----------|-------|
| API | Anthropic Message Batches API |
| Cost saving | 50% vs. streaming |
| Latency | ~1h average; 24h hard expiry |
| Cache TTL | Auto-promoted 5m ephemeral → 1h for batch runs |
| Max per batch | 100,000 requests / 256 MB |
| Result retention | 29 days |

**Gemini Path (Optional)**

| Parameter | Value |
|-----------|-------|
| Primary model | `gemini-3-flash-preview` |
| Temperature | `0.7` |
| Tool mode | NOT SUPPORTED — auto-disabled |

**OpenRouter Path**

| Parameter | Value |
|-----------|-------|
| Routing | `openrouter/<model>` |
| 1M context | `translation.openrouter_opus_1m_confirmed: true` |
| Tool mode | NOT SUPPORTED — auto-disabled |

### 12.5 Pre-Phase-2 Invariant Gate

`_run_pre_phase2_invariant_gate` validates before any translation begins:

| Check | Severity |
|-------|---------|
| `manifest.json` exists | **Hard failure** |
| `metadata_en.title_en` populated | **Hard failure** |
| Character names populated | **Hard failure** |
| Visual cache (when multimodal enabled) | **Hard failure** |
| Scene plans present (≥ 1 chapter) | Warning |
| `character_voice_fingerprints` count | Warning if < 2 |
| EPS band coverage | Warning if partial |
| Bible sync status | Warning if failed |

### 12.6 Prompt Assembly

The 7 context layers assembled per chapter before Opus receives the prompt:

| Layer | Source | Format |
|-------|--------|--------|
| 1. Canon Event Fidelity v2 | Config / system prompt | CFv2 priority hierarchy |
| 2. Character voice directives | `VoiceRAGManager.query_for_chapter(chapter_id, eps_band)` | `<Character_Voice_Directive>` XML |
| 3. Arc directive | `ArcTracker.get_directive(chapter_id)` | EPS band + history |
| 4. Scene plan scaffold | `scene_plans/<chapter>_scene_plan.json` | `<Scene_Plan>` XML |
| 5. Art Director's Notes | `visual_cache.json → prompt_injection` | `<Visual_Cache>` XML |
| 6. Cultural glossary + continuity | `cultural_glossary.json`, `continuity_pack.json` | Structured blocks |
| 7. Translation brief | `translation_brief.md` | Shared cache block (batch) |

Opus does not receive: raw image data, instruction hierarchy ambiguities, tool planning prompts, or output format templates beyond basic Markdown headers.

### 12.7 The EPS Voice System (Phase 2 Operation)

**VoiceRAGManager** (`pipeline/translator/voice_rag_manager.py`):
- Indexed at startup from `metadata_en.character_voice_fingerprints`
- ChromaDB storage with JSON fallback
- Queried per chapter by `(character_name, eps_band)` — returns most-relevant speech pattern sample
- Inserted into prompt as `CHARACTER VOICE DIRECTIVE` block

**ArcTracker** (`pipeline/translator/arc_tracker.py`):
- Tracks EPS evolution from Phase 1.52 bands + real-time re-computation per chapter
- Computes from 6 JP corpus signals (same as Phase 1.52 weights)
- Maps score → 5 voice bands
- EPS state persisted to `.context/arc_tracker.json` after each chapter

### 12.8 Post-Processing Pipeline (14 Passes)

| Pass | Module | Purpose |
|------|--------|---------|
| 1 | `post_processor.cjk_cleaner_v2` | Remove stray JP characters |
| 2 | `post_processor.vn_cjk_cleaner` | VN-specific CJK and diacritic cleanup |
| 3 | `post_processor.format_normalizer` | Whitespace, header, list normalization |
| 4 | `common.name_order_normalizer` | JP/EN name-order policy enforcement |
| 5 | `post_processor.truncation_validator` | Detect mid-sentence truncation |
| 6 | `post_processor.pov_validator` | Verify POV consistency with scene plan |
| 7 | `post_processor.reference_validator` | Check cross-references |
| 8 | `post_processor.tense_validator` | Flag tense consistency issues |
| 9 | `post_processor.grammar_validator` | Light structural grammar checks |
| 10 | `post_processor.copyedit_post_pass` | Oxford comma, dialogue dash normalization |
| 11 | `post_processor.phase2_5_ai_ism_fixer` | Strip AI-characteristic phrasing |
| 12 | `post_processor.stage3_refinement_agent` | Optional LLM-assisted refinement |
| 13 | `translator.voice_validator` | EPS-band-adapted voice fingerprint checks |
| 14 | `translator.koji_fox_validator` | Anime dub detection, stilted formality, read-aloud score |

### 12.9 Outputs

| Artifact | Path | Description |
|----------|------|-------------|
| Translated chapters | `WORK/<vol>/EN/<chapter_id>.md` | Final translated prose |
| Translation log | `manifest.json → translation_log` | Per-chapter cost audit, quality score, status |
| Cost audit | `cost_audit_last_run.json` | Full tokenized breakdown |
| Arc tracker | `.context/arc_tracker.json` | Updated EPS state after each chapter |
| Continuity pack | `.context/continuity_pack.json` | Updated cross-chapter continuity context |

**`translation_log` per-chapter fields:**
`status`, `quality_score`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens`, `cost_usd`, `tool_calls`, `adn_flags`, `retries`

### 12.10 Failure Modes

| Failure | Recovery |
|---------|---------|
| Pre-flight gate failure | Fix violations (run missing prep phases); re-run |
| LLM returns truncated output | Auto retry with extended `max_tokens` |
| LLM 429 rate limit | Exponential backoff (configurable in `config.yaml`) |
| Anthropic batch timeout (24h) | Partial results returned; re-submit failed chapters individually |
| Visual cache miss for illustration | Warning; proceeds without ADN; run Phase 1.6 to populate |
| Voice fingerprint count < 2 | Run `./mtl phase1.51 <vol>` to backfill |
| Chapter already translated | Skipped unless `--force` |

### 12.11 CLI Reference

```bash
# Standard translation (all chapters)
./mtl phase2 <volume_id>

# With Art Director's Notes (multimodal)
./mtl phase2 <volume_id> --enable-multimodal

# Batch mode (50% cost, ~1h latency) — recommended
./mtl batch <volume_id>

# Full multimodal combined run
./mtl multimodal <volume_id>

# Control Phase 1.55 mode at translation time
./mtl phase2 <volume_id> --phase1-55-mode skip       # use existing cache
./mtl phase2 <volume_id> --phase1-55-mode overwrite  # force rebuild
./mtl phase2 <volume_id> --phase1-55-mode auto       # auto-decide

# Force re-translate specific chapters
python -m pipeline.translator.agent --dir WORK/<vol_dir> --chapters chapter_01 chapter_05 --force

# Skip full-LN cache prep gate
./mtl phase2 <volume_id> --full-ln-cache off
```

### 12.12 Validation Checklist

- [ ] `WORK/<vol>/EN/` exists with one `.md` per chapter
- [ ] `manifest.json → pipeline_state.translator.status == "completed"`
- [ ] `translation_log.chapters_completed` equals expected chapter count
- [ ] `translation_log.chapters_failed == 0`
- [ ] Spot-check 2–3 EN chapters: no CJK residue, correct dialogue dash style, no truncation
- [ ] `cost_audit_last_run.json` exists with plausible token counts
- [ ] `.context/arc_tracker.json` updated (timestamp newer than run)
- [ ] Startup log: `✓ Koji Fox: N voice fingerprint(s) indexed` (N = character count)
- [ ] If multimodal: `adn_flags` in translation log entries confirm ADN receipt
- [ ] `./mtl status <volume_id>` — §10 badge shows ✓

---

## 13. Cross-Phase Data Flow

The following diagram shows how each phase's outputs flow into downstream phases:

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MTLS v1 · CROSS-PHASE DATA FLOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Phase 1  ─────────────────────────────────────────────────────
  Outputs: manifest.json, chapters/*.md, illustrations/, metadata_en scaffold
           │        │              │
           ▼        ▼              ▼
  Phase   1.5    Phase 1.55    Phase 1.6
  (metadata)    (LN cache)   (visual ADN)
     │              │              │
     ▼              ▼              │
  Phase 1.51    character_registry.json ──► Phase 2
  Phase 1.52    cultural_glossary.json  ──► Phase 2
  (backfill)    timeline_map.json       ──► Phase 2
                idiom_trans_cache.json  ──► Phase 2
     │                                      ▲
     ▼                                      │
  Phase 1.56 ─────────────────────────────► │
  (translation_brief.md: Gemini→Anthropic)  │
                                            │
  Phase 1.7 ──────────────────────────────► │
  (scene_plans/*.json)                      │
                                            │
  visual_cache.json ────────────────────────┘
  (from Phase 1.6)

  ──────────────────────────────────────────────────────────────
  Phase 2 (Translator):
    Reads ALL of the above
    Writes: EN/*.md, translation_log, cost_audit, arc_tracker
    ──────────────────────────────────────────────────────────
    Phase 2.5 (Bible Sync — post-translation)
    Reads: EN/*.md, manifest.json
    Writes: bibles/<series_id>.json (diff + merge)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Artifact Dependency Table

| Artifact | Produced By | Consumed By |
|----------|------------|-------------|
| `manifest.json` | Phase 1 (init) | All subsequent phases (R/W) |
| `chapters/*.md` | Phase 1 | Phase 1.55, 1.56, 1.7, Phase 2 |
| `illustrations/` | Phase 1 | Phase 1.6 |
| `metadata_en` fields | Phase 1.5 | Phase 1.51, 1.52, 1.55, 1.7, Phase 2 |
| `character_voice_fingerprints` | Phase 1.51 (or 1.5) | Phase 2 (Voice RAG) |
| `EPS bands` | Phase 1.52 (or 1.5) | Phase 1.7, Phase 2 (ArcTracker) |
| `rich_metadata_cache_patch.json` | Phase 1.55 | Phase 1.56, Phase 2 |
| `character_registry.json` et al. | Phase 1.55 / 1.7-cp | Phase 2 (co-processor injection) |
| `translation_brief.md` | Phase 1.56 | Phase 2 (batch shared cache block) |
| `visual_cache.json` | Phase 1.6 | Phase 2 (multimodal path) |
| `scene_plans/*.json` | Phase 1.7 | Phase 2 (binding scaffold) |
| `EN/*.md` | Phase 2 | Phase 4 (EPUB builder), Auditors |
| `arc_tracker.json` | Phase 2 (updated) | Phase 2 (cross-chapter carry-forward) |

---

## 14. Manifest State Machine

`manifest.json → pipeline_state` is the authoritative pipeline state record. Each phase writes its own key:

```jsonc
{
  "pipeline_state": {
    "librarian":           { "status": "completed", "timestamp": "..." },
    "metadata_processor":  { "status": "completed", "target_language": "en", "schema_preserved": true },
    "rich_metadata_cache": { "status": "completed", "cache_readiness": true },
    "translation_brief":   { "status": "completed", "model": "gemini-3-flash-preview" },
    "multimodal_processor":{ "status": "completed", "total": 8, "generated": 8, "blocked": 0 },
    "scene_planner":       { "status": "completed", "generated_plans": 12, "failed_plans": 0 },
    "translator":          { "status": "completed", "chapters_completed": 12, "chapters_failed": 0 }
  }
}
```

`./mtl status <volume_id>` reads these fields and renders the section badge summary:

```text
  §1  Librarian              ✓   §8  Multimodal Processor    ✓
  §3  Metadata Translation   ✓   §9  Scene Planner           ✓
  §6  Rich Metadata Cache    ✓   §10 Translator (Opus 4.6)   ✓
  §7  Translation Brief      ✓
```

---

## 15. Full Batch Pipeline

The `./mtl batch` command automates the complete sequence from Phase 1.5 through Phase 2 in a single invocation:

```text
  ./mtl batch <volume_id>
        │
        ├── [1/6] phase1.5   — translate metadata
        ├── [2/6] phase1.55  — enrich full-LN cache
        ├── [3/6] phase1.56  — generate translation brief
        ├── [4/6] phase1.6   — analyze illustrations (ADN)
        ├── [5/6] phase1.7   — generate scene plans
        └── [6/6] phase2     — batch translate all chapters
                              (Anthropic Message Batches API)
                              (50% cost, ~1h latency)
```

**Phase 1 (EPUB extraction) is NOT included** — it must be run separately first:
```bash
./mtl phase1 INPUT/novel_vol3.epub   # extracts, returns volume_id
./mtl batch <volume_id>               # runs everything else
```

**Batch pipeline options:**
```bash
./mtl batch <vol> --force-brief        # regenerate translation brief
./mtl batch <vol> --full-ln-cache off  # skip full-LN cache gate
./mtl batch <vol> --enable-multimodal  # inject Art Director's Notes in Phase 2
```

---

*This document is the canonical pipeline phase direction reference for MTLS v1.*  
*Cross-reference:* [← Root README](../../README.md) · [MTLS_V1_SYSTEM_ARCHITECTURE.md](./MTLS_V1_SYSTEM_ARCHITECTURE.md) · [MTLS_V1_AI_TANDEM_ARCHITECTURE.md](./MTLS_V1_AI_TANDEM_ARCHITECTURE.md) · [MTLS_V1_OPUS_TOKEN_ALLOCATION.md](./MTLS_V1_OPUS_TOKEN_ALLOCATION.md)

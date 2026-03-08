# MTLS v1 — System Architecture: Unified Diagram and Module Interactions

**Document type:** Formal design reference  
**Abbreviation:** MTLS (MTL Studio)  
**Version:** 1.0  
**Status:** Canonical  
**Scope:** Full pipeline architecture, layer model, module inventory, data contracts, and inter-phase interaction patterns  
**Last updated:** 2026-03-06

---

## Table of Contents

- [MTLS v1 — System Architecture: Unified Diagram and Module Interactions](#mtls-v1--system-architecture-unified-diagram-and-module-interactions)
  - [Table of Contents](#table-of-contents)
  - [1. Executive Summary](#1-executive-summary)
  - [2. System Identity](#2-system-identity)
  - [3. Top-Level Layer Model](#3-top-level-layer-model)
  - [4. Full ASCII Pipeline Diagram](#4-full-ascii-pipeline-diagram)
    - [4.1 Production Flow — Standard Run](#41-production-flow--standard-run)
    - [4.2 Dual-Model "CPU + GPU" Multimodal Subsystem](#42-dual-model-cpu--gpu-multimodal-subsystem)
    - [4.3 Voice RAG and EPS Signal Architecture](#43-voice-rag-and-eps-signal-architecture)
    - [4.4 Canon Authority and Data Flow](#44-canon-authority-and-data-flow)
    - [4.5 Current vs Target Architecture](#45-current-vs-target-architecture)
  - [5. Phase Module Inventory](#5-phase-module-inventory)
    - [5.1 Preparation Domain (Phases 1–1.7)](#51-preparation-domain-phases-117)
    - [5.2 Translation Domain (Phase 2)](#52-translation-domain-phase-2)
    - [5.3 Series Bible Domain (Phase 2.5)](#53-series-bible-domain-phase-25)
    - [5.4 Post-Processing Stack](#54-post-processing-stack)
    - [5.5 Auditor Stack (Downstream QC)](#55-auditor-stack-downstream-qc)
    - [5.6 Support Modules (pipeline/modules/)](#56-support-modules-pipelinemodules)
    - [5.7 Vector Store Infrastructure](#57-vector-store-infrastructure)
  - [6. Data Contract Architecture](#6-data-contract-architecture)
    - [6.1 Volume Artifacts (per-volume working directory)](#61-volume-artifacts-per-volume-working-directory)
    - [6.2 Series Artifacts (cross-volume)](#62-series-artifacts-cross-volume)
    - [6.3 Proposed Target Data Contracts (v1 Canonical)](#63-proposed-target-data-contracts-v1-canonical)
  - [7. Inter-Module Interaction Matrix](#7-inter-module-interaction-matrix)
  - [8. Provider and Model Routing](#8-provider-and-model-routing)
  - [9. Derived Artifact Graph](#9-derived-artifact-graph)
  - [10. Canon Authority Hierarchy](#10-canon-authority-hierarchy)
  - [11. Post-Processing Module Stack](#11-post-processing-module-stack)
  - [12. Observability and Audit Layer](#12-observability-and-audit-layer)
  - [13. Target Architecture (v1 Canonical Form)](#13-target-architecture-v1-canonical-form)
  - [14. Failure Modes and Recovery Paths](#14-failure-modes-and-recovery-paths)
  - [15. Design Governance Principles](#15-design-governance-principles)
  - [Appendix A: CLI Reference](#appendix-a-cli-reference)
  - [Appendix B: Key File Paths Reference](#appendix-b-key-file-paths-reference)

---

## 1. Executive Summary

MTL Studio (MTLS) is a multi-phase literary translation pipeline purpose-built for Japanese light novel and web novel localization. Version 1 is the first formally named release following the internal codename period.

MTLS orchestrates two AI model families — Google Gemini 3 (multimodal reasoning, fast volume processing, embedding) and Anthropic Claude Opus 4.6 (literary translation, extended thinking) — across a structured nine-phase preparation pipeline and a dedicated translation execution stage.

The architecture is designed around a single governing principle:

> **Resolve all non-literary uncertainty before translation begins, so that the translator model spends its full reasoning budget on literary craft.**

This document is the canonical reference for system topology: layer definitions, phase modules, inter-module data flow, canon authority, and the full ASCII diagram inventory.

---

## 2. System Identity

| Property | Value |
|----------|-------|
| Full name | MTL Studio |
| Official abbreviation | MTLS |
| Version | 1 |
| Pipeline architecture | Multi-phase sequential with upstream canon pre-assembly |
| Primary translator model | `claude-opus-4-6` (Anthropic) |
| Primary preparation model | `gemini-3.1-pro-preview` / `gemini-3-flash-preview` (Google) |
| Embedding engine | Gemini embedding + ChromaDB vector stores |
| Execution mode (production) | Anthropic Message Batches API (50% cost, async) |
| Output format | Markdown chapters → EPUB via Phase 4 builder |
| Canon control | Canon Event Fidelity v2 (CFv2) hierarchy |
| Voice continuity | Koji Fox EPS (Emotional Proximity Signal) system |

---

## 3. Top-Level Layer Model

MTLS is organized into seven architectural layers. Each layer has a single authorized job. Layers below Layer 3 are read-only downstream consumers of canon assembled in Layers 1–2.

```text
╔══════════════════════════════════════════════════════════════════════╗
║  MTLS v1 — LAYER MODEL                                               ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  LAYER 0  ·  Source Ingest                                           ║
║    Responsibilities: EPUB unpack, XHTML→Markdown, asset catalog      ║
║    Boundary: writes raw JP source only; no translated content        ║
║                                                                      ║
║  LAYER 1  ·  Canon Construction                                      ║
║    Responsibilities: Volume Canon (names, glossary, EPS, voice),     ║
║                      Series Canon (Bible, cross-volume memory)       ║
║    Boundary: single authoritative write pass per volume              ║
║                                                                      ║
║  LAYER 2  ·  Derived Intelligence                                    ║
║    Responsibilities: Voice RAG index, EPS index, visual cache,       ║
║                      scene plans, translation brief                  ║
║    Boundary: read-only derived views; regenerable from Layer 1       ║
║                                                                      ║
║  LAYER 3  ·  Translation Runtime                                     ║
║    Responsibilities: Prompt assembly, provider execution,            ║
║                      adaptive thinking, batch/streaming              ║
║    Boundary: consumes Layer 1+2; emits EN markdown only              ║
║                                                                      ║
║  LAYER 4  ·  Deterministic Post-Pass                                 ║
║    Responsibilities: Typography normalization, name-order,           ║
║                      ellipsis/quote normalization, safe grammar fix  ║
║    Boundary: non-semantic mutations only; grammar audit = report     ║
║                                                                      ║
║  LAYER 5  ·  Continuity Export                                       ║
║    Responsibilities: Phase 2.5 Bible push, continuity pack,         ║
║                      EPS carry-forward                               ║
║    Boundary: only upstream writer after translation completes        ║
║                                                                      ║
║  LAYER 6  ·  Human / QC / Build                                      ║
║    Responsibilities: Critics (auditors), quality report,             ║
║                      EPUB builder (Phase 4)                          ║
║    Boundary: read-only except for QC annotations and EPUB output     ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## 4. Full ASCII Pipeline Diagram

### 4.1 Production Flow — Standard Run

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MTLS v1 · PRODUCTION PIPELINE · STANDARD RUN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌─────────────────────┐
  │  INPUT/novel.epub   │
  └──────────┬──────────┘
             │ (raw EPUB)
             ▼
  ┌─────────────────────────────────────────────────────┐
  │  PHASE 1 · LIBRARIAN                                │
  │  Model: deterministic (no LLM)                      │
  │  ▸ EPUB unpack → chapters/CHAPTER_NN.md             │
  │  ▸ OPF/NCX parse → chapter order + asset catalog    │
  │  ▸ Ruby extraction → initial character scaffold     │
  │  ▸ manifest.json written (orchestration state)      │
  └──────────────────┬──────────────────────────────────┘
                     │ manifest.json + JP/*.md
                     ▼
  ┌─────────────────────────────────────────────────────┐
  │  PHASE 1.5 · METADATA TRANSLATION                   │
  │  Model: gemini-3-flash-preview (Gemini Flash)       │
  │  ▸ Schema autoupdate (V2/V4 → v3 enhanced)          │
  │  ▸ Translate: title, author, chapter titles         │
  │  ▸ Translate: character names, glossary             │
  │  ▸ Sub-phase 1.51: Voice RAG fingerprint expansion  │
  │  ▸ Sub-phase 1.52: EPS band backfill                │
  └──────────────────┬──────────────────────────────────┘
                     │ metadata_en.json enriched
                     ▼
  ┌─────────────────────────────────────────────────────┐
  │  PHASE 1.55 · RICH METADATA CACHE ENRICHMENT        │
  │  Model: gemini-3-flash-preview (full JP corpus)     │
  │  ▸ Full light-novel corpus JP cache build           │
  │  ▸ Rich scene metadata extraction per chapter       │
  │  ▸ Emotional cue indexing + cultural notes          │
  │  ▸ Output: rich_metadata_cache_patch_en.json        │
  └──────────────────┬──────────────────────────────────┘
                     │ rich_metadata_cache_patch_en.json
                     ▼
  ┌─────────────────────────────────────────────────────┐
  │  PHASE 1.56 · TRANSLATOR'S GUIDANCE BRIEF           │
  │  Model: claude-opus-4-5 or claude-haiku-4-5         │
  │         (Anthropic Batch for full-corpus analysis)  │
  │  ▸ Full-chapter JP pre-analysis pass                │
  │  ▸ Identifies translation challenges in advance     │
  │  ▸ Generates TRANSLATION_BRIEF.md                   │
  │  ▸ Provides chapter-level risk flags to translator  │
  └──────────────────┬──────────────────────────────────┘
                     │ TRANSLATION_BRIEF.md
                     ▼
  ┌─────────────────────────────────────────────────────┐
  │  PHASE 1.6 · MULTIMODAL PROCESSOR                   │
  │  Model: gemini-3-flash-preview (vision)             │
  │  ▸ Gemini Vision analyzes all illustrations         │
  │  ▸ Generates Art Director's Notes (ADN)             │
  │  ▸ ADN schema: DID, priority, scope, word budget,   │
  │     canon_override flag, EPS signal, spoiler guard  │
  │  ▸ Output: visual_cache.json (structured ADN)       │
  │  ▸ Illustration thought logs: cache/thoughts/       │
  └──────────────────┬──────────────────────────────────┘
                     │ visual_cache.json (ADN)
                     ▼
  ┌─────────────────────────────────────────────────────┐
  │  PHASE 1.7 · STAGE 1 SCENE PLANNER                  │
  │  Model: gemini-3.1-pro-preview or                   │
  │         claude-opus-4-5 (configurable)              │
  │  ▸ Narrative beat mapping per chapter               │
  │  ▸ Character rhythm scaffold                        │
  │  ▸ POV assignment + scene intent annotation         │
  │  ▸ Co-Processor Pack (1.7-cp): cache-only refresh   │
  │  ▸ Output: PLANS/chapter_NN_scene_plan.json         │
  └──────────────────┬──────────────────────────────────┘
                     │ PLANS/*.json (scene plans)
                     ▼
  ┌─────────────────────────────────────────────────────┐
  │  PHASE 2 · TRANSLATOR AGENT (Koji Fox Engine)       │
  │  Model: claude-opus-4-6 (effort=max)                │
  │  Mode:  Anthropic Batch API (production)            │
  │  ▸ Reads: volume_canon, series_continuity,          │
  │           scene_plans, visual_cache (ADN),          │
  │           translation_brief, grammar RAG priors     │
  │  ▸ CFv2 hierarchy pre-resolved in prompt            │
  │  ▸ Extended adaptive thinking (no budget_tokens)    │
  │  ▸ Tool mode: auto-disabled in batch (tool_calls=0) │
  │  ▸ Cache hit ratio: ~91.7% (1-hour prompt cache)    │
  │  ▸ Emits: EN/CHAPTER_NN_EN.md per chapter           │
  │  ▸ Emits: THINKING/chapter_NN_THINKING.md           │
  │  ▸ Emits: translation_log.json                      │
  └──────────────────┬──────────────────────────────────┘
                     │ EN/*.md + thinking logs
                     ▼
  ┌─────────────────────────────────────────────────────┐
  │  COPYEDIT POST-PASS (Phase 2 inline)                │
  │  Model: deterministic                               │
  │  ▸ Typography normalization (……→…, quotes)          │
  │  ▸ Whitespace normalization                         │
  │  ▸ Grammar audit (report only; auto_fix=OFF)        │
  │  ▸ Name-order normalization                         │
  └──────────────────┬──────────────────────────────────┘
                     │ clean EN/*.md
                     ▼
  ┌─────────────────────────────────────────────────────┐
  │  PHASE 2.5 · VOLUME BIBLE UPDATE AGENT              │
  │  Model: gemini-3-flash-preview or claude-haiku-4-5  │
  │  ▸ Diffs local canon vs series Bible                │
  │  ▸ Pushes approved continuity carry-forward         │
  │  ▸ Updates: EPS latest state, voice evolution       │
  │  ▸ The ONLY authorized upstream writer post-Phase 2 │
  └──────────────────┬──────────────────────────────────┘
                     │ updated series Bible
                     ▼
  ┌─────────────────────────────────────────────────────┐
  │  AUDITORS (optional, downstream validation)         │
  │  Models: claude-haiku-4-5 (speed), claude-sonnet    │
  │  ▸ FidelityAuditor       — source fidelity check    │
  │  ▸ IntegrityAuditor      — structural integrity     │
  │  ▸ GapPreservationAuditor — narrative gap check     │
  │  ▸ NameConsistencyAuditor — EN name consistency     │
  │  ▸ ProseAuditor           — prose quality scoring   │
  │  ▸ VN-specific auditors   — VN grammar/prose        │
  │  ▸ FinalAuditor           — composite QC report     │
  └──────────────────┬──────────────────────────────────┘
                     │ audit reports + quality_report.md
                     ▼
  ┌─────────────────────────────────────────────────────┐
  │  PHASE 4 · EPUB BUILDER                             │
  │  Model: deterministic                               │
  │  ▸ Assembles EN markdown → EPUB structure           │
  │  ▸ Applies EPUB metadata from manifest              │
  │  ▸ Copies illustration assets                       │
  │  ▸ Validates EPUB output structure                  │
  └──────────────────┬──────────────────────────────────┘
                     │
                     ▼
  ┌─────────────────────────────┐
  │  OUTPUT/novel_vol_EN.epub   │
  └─────────────────────────────┘
```

### 4.2 Dual-Model "CPU + GPU" Multimodal Subsystem

This diagram isolates the visual processing pipeline that feeds Phase 2:

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MTLS v1 · DUAL-MODEL VISUAL PROCESSING SUBSYSTEM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  "GPU" (Vision Reasoning)       "CPU" (Translation Enforcement)
  ───────────────────────        ────────────────────────────────

  Illustration JPEGs             Art Director's Notes (ADN)
         │                              │
         ▼                              │
  ┌──────────────┐                      │
  │ Gemini 3     │                      │
  │ Flash Vision │                      │
  │              │                      │
  │ Analyzes:    │                      │
  │ · composition│  generates →   structured ADN JSON:
  │ · EPS signal │  ──────────>   · DID (directive ID)
  │ · character  │                · type (atmospheric/bridge_prose/
  │   identity   │                         register_constraint)
  │ · subtext    │                · priority (required/recommended)
  │ · spoiler    │                · scope (post_marker_narration/
  │   prevention │                         post_marker_dialogue)
  │ · POV detect │                · canon_override (TRUE/FALSE)
  └──────────────┘                · word_budget (tokens)
         │                        · placement_hint
         │                        · EPS interpretation signal
         ▼                        · spoiler gate (do_not_reveal_before)
  visual_cache.json               │
                                  ▼
                          Phase 2 prompt assembly
                                  │
                                  ▼
                          claude-opus-4-6
                          (receives structured ADN,
                           NOT raw image data)
```

**Key design insight:** Opus never sees raw images. It receives pre-interpreted structured directives. This converts a high-entropy multimodal reasoning problem into a bounded prose-guidance problem.

### 4.3 Voice RAG and EPS Signal Architecture

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MTLS v1 · VOICE RAG + EPS SIGNAL SYSTEM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌─────────────────────────┐    ┌──────────────────────────────┐
  │  VOICE RAG INDEX        │    │  EPS SIGNAL SYSTEM           │
  │  (ChromaDB)             │    │  (Emotional Proximity        │
  │                         │    │   Signals)                   │
  │  Per-character:         │    │                              │
  │  · speech pattern       │    │  6 signal bands:             │
  │  · vocabulary register  │    │  · COOL  (formal/distant)    │
  │  · sentence rhythm      │    │  · WARM  (approachable)      │
  │  · emotional vocabulary │    │  · CLOSE (comfortable)       │
  │  · fingerprint key      │    │  · HOT   (emotionally open)  │
  │  · cross-vol evolution  │    │  · PEAK  (raw/unguarded)     │
  │                         │    │  · MELT  (complete surrender)│
  │  Built in: Phase 1.51   │    │                              │
  │  Updated in: Phase 2.5  │    │  Per chapter + per char:     │
  │                         │    │  · current_band              │
  └──────────┬──────────────┘    │  · delta_from_prior          │
             │                   │  · trigger_event             │
             │ similarity        │  · carry-forward state       │
             │ retrieval         │                              │
             ▼                   │  Built in: Phase 1.52        │
  Translation prompt             │  Carried forward: Phase 2.5  │
  (voice guidance)               └──────────────┬───────────────┘
                                                │ EPS directives
                                                ▼
                                  Translation prompt
                                  (emotional register guidance)
                                                │
                                                ▼
                                       claude-opus-4-6
                                  (uses both for character-
                                   specific voice rendering)
```

### 4.4 Canon Authority and Data Flow

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MTLS v1 · CANON AUTHORITY ARCHITECTURE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  AUTHORITATIVE SOURCES                   DERIVED VIEWS
  ─────────────────────                   ──────────────

  ┌──────────────────────┐
  │  VOLUME CANON STORE  │ ◄── Phase 1.5 (writes)
  │                      │ ◄── Phase 1.51 (voice)
  │  · character_names   │ ◄── Phase 1.52 (EPS)
  │  · glossary          │
  │  · voice_fingerprints│ ──────────────────────────────────┐
  │  · EPS by chapter    │                                   │
  │  · scene_intents     │ ──read──►  visual_cache.json      │
  │  · translation_rules │           scene_plans/*.json      │
  │  · world_setting     │           continuity_pack.json    │
  │                      │           translation_log.json    │
  │  Source: manifest.json           voice_rag/              │
  │  + metadata_en.json  │                                   │
  └──────────┬───────────┘                                   │
             │ local-wins                          all read-only
             │ policy                         (never redefine canon)
             │                                               │
             ▼                                               │
  ┌──────────────────────┐                                   │
  │  SERIES CANON STORE  │                                   │
  │  (Series Bible JSON) │                                   │
  │                      │                                   ▼
  │  · cross-vol names   │             ┌────────────────────────────┐
  │  · series glossary   │ ──advisory──►  TRANSLATION RUNTIME       │
  │  · EPS carry-forward │             │                            │
  │  · voice evolution   │             │  Reads (in priority order):│
  │  · translation       │             │  1. Volume Canon           │
  │    decisions         │             │  2. Series Continuity      │
  │                      │             │  3. Derived Views          │
  │  Source: bibles/     │             │  4. Translation Brief      │
  │  Updated: Phase 2.5  │             │  5. Scene Plans            │
  └──────────────────────┘             │  6. Visual Cache (ADN)     │
                                       └────────────────────────────┘
```

### 4.5 Current vs Target Architecture

Based on the formal architecture maturity analysis, MTLS v1 is transitioning toward the following canonical target shape:

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━  CURRENT STATE  ━━━━━━━━━━━━━━━━━━━━━━━
EPUB
 │
 ▼
Librarian
 │
 +────────────────────► manifest.json
 │                      metadata_en.json
 │                      assets
 │
 ▼
Phase 1.15 / 1.5 / 1.51 / 1.52 / 1.55 / 1.6 / 1.7
 │
 ├── metadata_en.json ──────────────────────────────────────┐
 ├── rich_metadata_cache_patch_en.json ──────────────────── │
 ├── visual_cache.json ──────────────────────────────────── │
 ├── PLANS/*.json ─────────────────────────────────────── ──│
 ├── .context/*.json ──────────────────────────────────── ──│
 └── series bible ──────────────────────────────────────────┤
                                                            ▼
                                                   Phase 2 Translator
                                                            │
                                          ┌─────────────────┼──────────────────┐
                                          ▼                 ▼                  ▼
                                  prompt loader      tool/provider       validators
                                          │           runtime             /post-fixes
                                          └───── reads many overlapping stores ────┘
                                                            │
                                                            ▼
                                                         EN/*.md
                                                            │
                                                            ▼
                                                        Phase 2.5
                                                            │
                                                            ▼
                                                     series bible

━━━━━━━━━━━━━━━━━━━━━━━━━━━  TARGET STATE  ━━━━━━━━━━━━━━━━━━━━━━━━

EPUB
 │
 ▼
Librarian
 │
 ▼
┌────────────────────────┐
│  Volume Canon Builder  │
│  (all Phase 1 canon)   │
└────────────────────────┘
 │
 ├──► volume_canon.json  ◄──────────────────────────────────────┐
 │                                                              │
 └──► manifest.json (orchestration only)                        │
                                                               │
┌────────────────────────┐                                     │
│  Series Canon Store    │ ◄──── Phase 2.5 push ───────────────┘
│  (Bible)               │
└────────────────────────┘
 │
 │  advisory (never direct-write to runtime)
 │
 ▼
┌─────────────────────────────────────────────────────────────┐
│  Derived Artifacts (read-only views — regenerable)          │
│  voice_rag.json │ eps_index.json │ visual_cache.json        │
│  scene_plans/*.json │ continuity_pack.json │ brief.md       │
└─────────────────────────────────────────────────────────────┘
 │
 ▼
┌────────────────────────┐
│  Translation Runtime   │
│  reads:                │
│  · volume_canon        │
│  · series continuity   │
│  · derived views       │
└────────────────────────┘
 │
 ▼
EN/*.md
 │
 ▼
┌────────────────────────┐
│  Deterministic PostPass│
│  copyedit + validation │
└────────────────────────┘
 │
 ▼
clean EN/*.md
 │
 ▼
Phase 2.5 continuity export
```

---

## 5. Phase Module Inventory

### 5.1 Preparation Domain (Phases 1–1.7)

| Phase | Name | Python Module | Primary Model | Job |
|-------|------|---------------|---------------|-----|
| 1 | Librarian | `pipeline.librarian.agent` | Deterministic | EPUB → Markdown, manifest creation |
| 1.5 | Metadata Translation | `pipeline.metadata_processor.agent` | gemini-3-flash-preview | JP→EN metadata, name/glossary |
| 1.51 | Voice RAG Expansion | Same (--voice-rag-only) | gemini-3-flash-preview | Character voice fingerprint backfill |
| 1.52 | EPS Band Backfill | Same (--eps-only) | gemini-3-flash-preview | Emotional Proximity Signal per chapter |
| 1.55 | Rich Metadata Cache | `pipeline.metadata_processor.rich_cache` | gemini-3-flash-preview | Full JP corpus cache + rich scene metadata |
| 1.56 | Translator's Guidance Brief | `pipeline.metadata_processor.brief` | claude-opus-4-5 (batch) | Pre-analysis of full JP corpus, challenge flags |
| 1.6 | Multimodal Processor | `pipeline.multimodal.*` | gemini-3-flash-preview (vision) | Illustration analysis → ADN in visual_cache.json |
| 1.7 | Stage 1 Scene Planner | `pipeline.planner.*` | gemini-3.1-pro-preview | Narrative beats, POV, scene intents → PLANS/ |
| 1.7-cp | Co-Processor Pack | `pipeline.planner.*` (--cache-only) | — | Cache-only refresh for context offload |

### 5.2 Translation Domain (Phase 2)

| Phase | Name | Python Module | Primary Model | Job |
|-------|------|---------------|---------------|-----|
| 2 | Translator Agent | `pipeline.translator.*` | claude-opus-4-6 (effort=max) | Full literary translation, EN chapter output |
| 2 (batch) | Anthropic Batch Translation | Same + batch controller | claude-opus-4-6 (batch) | Async batch processing (50% cost, 1h) |

### 5.3 Series Bible Domain (Phase 2.5)

| Phase | Name | Python Module | Primary Model | Job |
|-------|------|---------------|---------------|-----|
| 2.5 | Volume Bible Update Agent | `pipeline.narrator.*` | gemini-3-flash-preview | Diff + push continuity pack to Series Bible |

### 5.4 Post-Processing Stack

| Module | Python Path | Type | Job |
|--------|-------------|------|-----|
| CopyeditPostPass | `pipeline.post_processor.copyedit_post_pass` | Deterministic | Typography, whitespace, quote/ellipsis normalization |
| GrammarValidator | `pipeline.post_processor.grammar_validator` | Deterministic (report only) | Grammar violation detection; auto_fix=OFF |
| NameOrderNormalizer | `pipeline.post_processor.*` | Deterministic | JP name-order enforcement in EN output |

### 5.5 Auditor Stack (Downstream QC)

| Auditor | File | Scope |
|---------|------|-------|
| FidelityAuditor | `auditors/fidelity_auditor.py` | Source fidelity to JP |
| IntegrityAuditor | `auditors/integrity_auditor.py` | Structural completeness |
| GapPreservationAuditor | `auditors/gap_preservation_auditor.py` | Narrative gap retention |
| NameConsistencyAuditor | `auditors/name_consistency_auditor.py` | EN-facing name consistency |
| ProseAuditor | `auditors/prose_auditor.py` | EN prose quality scoring |
| VNProseAuditor | `auditors/vn_prose_auditor.py` | VN-specific prose quality |
| VNNameConsistencyAuditor | `auditors/vn_name_consistency_auditor.py` | VN name consistency |
| FinalAuditor | `auditors/final_auditor.py` | Composite QC report generator |

### 5.6 Support Modules (pipeline/modules/)

| Module | File | Function |
|--------|------|----------|
| MEGA Core Translation Engine | `MEGA_CORE_TRANSLATION_ENGINE.md` | Master prompt module for Opus |
| MEGA Character Voice System | `MEGA_CHARACTER_VOICE_SYSTEM.md` | Per-character voice rendering spec |
| Anti-AI-ism Agent | `anti_ai_ism_agent.py` | AI-ism detection and filtering |
| English Grammar RAG | `english_grammar_rag.py` | ChromaDB grammar pattern retrieval |
| English Pattern Store | `english_pattern_store.py` | EN idiom/pattern vector store |
| Vietnamese Grammar RAG | `vietnamese_grammar_rag.py` | VN-specific grammar guidance |
| Vietnamese Pattern Store | `vietnamese_pattern_store.py` | VN pattern vector store |
| Sino-Vietnamese Store | `sino_vietnamese_store.py` | Sino-VN vocabulary support |
| GAP Semantic Analyzer | `gap_semantic_analyzer.py` | Narrative gap semantic analysis |
| Idiom Localization | `idiom_localization.py` | Cross-cultural idiom adaptation |
| RTAS Calculator | `rtas_calculator.py` | Reader Trust & Atmosphere Score |
| Atmosphere Analyzer | `atmosphere_analyzer.py` | Scene atmosphere profiling |
| Dialect Detector | `dialect_detector.py` | JP dialect identification |
| Dialogue Analyzer | `dialogue_analyzer.py` | Speech pattern analysis |
| Multimodal (directory) | `modules/multimodal/` | Illustration processing sub-modules |
| Manga RAG (directory) | `modules/manga_rag/` | Manga-specific RAG pipeline |

### 5.7 Vector Store Infrastructure

| Store | Path | Engine | Purpose |
|-------|------|--------|---------|
| Series Bible RAG | `chroma_series_bible/` | ChromaDB + Gemini embedding | Cross-volume canon memory |
| English Patterns | `chroma_english_patterns/` | ChromaDB + Gemini embedding | EN grammar/idiom retrieval |
| Vietnamese Patterns | `chroma_vietnamese_patterns/` | ChromaDB + Gemini embedding | VN grammar/idiom retrieval |
| Sino-VN Vocabulary | `chroma_sino_vn/` | ChromaDB + Gemini embedding | Sino-Vietnamese reference |

---

## 6. Data Contract Architecture

### 6.1 Volume Artifacts (per-volume working directory)

| Artifact | Path | Authority | Phase Written | Consumers |
|----------|------|-----------|---------------|-----------|
| `manifest.json` | `WORK/<vol>/` | Volume Canon | Phase 1 creates; 1.5 updates | All phases |
| `metadata_en.json` | `WORK/<vol>/` | Volume Canon | Phase 1.5 | Phase 2, 1.7, auditors |
| `rich_metadata_cache_patch_en.json` | `WORK/<vol>/` | Derived | Phase 1.55 | Phase 2 prompt |
| `TRANSLATION_BRIEF.md` | `WORK/<vol>/.context/` | Derived | Phase 1.56 | Phase 2 prompt |
| `visual_cache.json` | `WORK/<vol>/` | Derived | Phase 1.6 | Phase 2 prompt (ADN) |
| `PLANS/*.json` | `WORK/<vol>/PLANS/` | Derived | Phase 1.7 | Phase 2 prompt |
| `.context/*.json` | `WORK/<vol>/.context/` | Derived | Phase 2 | Phase 2 (lookback) |
| `translation_log.json` | `WORK/<vol>/` | Derived | Phase 2 | Auditors, cost tracking |
| `cost_audit_last_run.json` | `WORK/<vol>/` | Derived | Phase 2 | Human review |
| `EN/CHAPTER_NN_EN.md` | `WORK/<vol>/EN/` | Output | Phase 2 | Phase 2.5, auditors, Phase 4 |
| `THINKING/chapter_NN_THINKING.md` | `WORK/<vol>/THINKING/` | Derived | Phase 2 | Design analysis, debugging |
| `continuity_diff_report.json` | `WORK/<vol>/` | Derived | Phase 2.5 | Human review |

### 6.2 Series Artifacts (cross-volume)

| Artifact | Path | Authority | Phase Written | Consumers |
|----------|------|-----------|---------------|-----------|
| Series Bible JSON | `bibles/` | Series Canon | Phase 2.5 | Phase 1.5, Phase 2 (advisory) |
| Grammar RAG indexes | `chroma_english_patterns/` | Infrastructure | Build scripts | Phase 2 |
| Embedding indexes | `chroma_series_bible/` | Infrastructure | Phase 2.5 | Phase 2 |

### 6.3 Proposed Target Data Contracts (v1 Canonical)

**Contract A: `volume_canon.json`**
```
volume_identity       → title, author, series_id, volume_number, target_language
world_setting         → genre, setting, name_order_policy, cultural_notes
character_registry    → [JP_key, canonical_EN, short_name, aliases, fingerprint_key]
glossary              → [JP_term, EN_term, locked=bool, context_notes]
voice_rag             → [char_key → fingerprint_hash, voiceIndex_path]
eps                   → [chapter_id → {char_key → {band, delta, trigger_event}}]
scene_intents         → [chapter_id → {act, pov, tone, narrative_beat}]
translation_rules     → [rule_id, scope, priority, text]
multimodal_identity   → [char_key → visual_anchor, color_id, non_color_id]
quality_flags         → {fingerprint_coverage, eps_coverage, scene_plan_quality}
```

**Contract B: `series_bible.json`**
```
series_identity       → series_title, publisher, language_pair
series_glossary       → [term_id, JP, EN, locked, precedent_volume]
character_registry    → [char_key → {latest_EN_name, voice_evolution, eps_history}]
voice_memory          → [char_key → {fingerprint_versions[], continuity_notes}]
continuity_memory     → [event_id → {chapter_ref, canon_fact, carry_forward=bool}]
latest_eps_state      → [char_key → {band, last_volume, last_chapter}]
translation_decisions → [decision_id → {JP, EN, rationale, date}]
```

---

## 7. Inter-Module Interaction Matrix

```text
                    ┌─────────────────────────────────────────────────────────────────┐
                    │                     CONSUMER PHASES                            │
                    │  1.5  1.51  1.52  1.55  1.56  1.6  1.7  2   2.5  QC  Phase4  │
  PRODUCER          ├─────────────────────────────────────────────────────────────────┤
  ──────────        │                                                                 │
  Phase 1           │   R    R     R     R     R     R    R    R    R              │
  (manifest.json)   │                                                                 │
  ──────────        │                                                                 │
  Phase 1.5         │              R           R          R    R    R    R          │
  (metadata_en)     │                                                                 │
  ──────────        │                                                                 │
  Phase 1.51        │                                          R    R    R    R      │
  (voice fingerpr.) │                                                                 │
  ──────────        │                                                                 │
  Phase 1.52        │                                          R    R    R    R      │
  (EPS bands)       │                                                                 │
  ──────────        │                                                                 │
  Phase 1.55        │                                R         R    R    R          │
  (rich cache)      │                                                                 │
  ──────────        │                                                                 │
  Phase 1.56        │                                               R    R          │
  (brief)           │                                                                 │
  ──────────        │                                                                 │
  Phase 1.6         │                                               R    R          │
  (visual_cache)    │                                                                 │
  ──────────        │                                                                 │
  Phase 1.7         │                                               R    R          │
  (scene plans)     │                                                                 │
  ──────────        │                                                                 │
  Phase 2           │                                          W    R    R     R     │
  (EN/*.md)         │                                                                 │
  ──────────        │                                                                 │
  Phase 2.5         │   R    R     R                           R         R           │
  (Bible update)    │                                                                 │
                    └─────────────────────────────────────────────────────────────────┘

  R = reads from this producer's output
  W = writes to this artifact
```

**Critical interaction rules:**
1. Phase 2 does **not** write back to canon (it only reads)
2. Phase 2.5 is the **only** authorized Bible writer after translation
3. Derived artifacts (visual_cache, scene_plans, rich_cache) are **never** canon
4. Bible is **advisory** at runtime — local Volume Canon wins all conflicts

---

## 8. Provider and Model Routing

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MTLS v1 · PROVIDER ROUTING MAP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  GOOGLE / GEMINI PATH
  ────────────────────
  Phase 1.5   → gemini-3-flash-preview     (metadata translation)
  Phase 1.51  → gemini-3-flash-preview     (voice fingerprint)
  Phase 1.52  → gemini-3-flash-preview     (EPS bands)
  Phase 1.55  → gemini-3-flash-preview     (rich cache)
  Phase 1.6   → gemini-3-flash-preview     (vision, ADN generation)
  Phase 1.7   → gemini-3.1-pro-preview     (scene planning)
                  [configurable → claude-opus-4-5 alt]
  Phase 2.5   → gemini-3-flash-preview     (Bible update diff)
  Embedding   → Gemini embedding model     (all ChromaDB indexes)

  ANTHROPIC PATH
  ──────────────
  Phase 1.56  → claude-opus-4-5 (batch)   (translation brief pre-analysis)
  Phase 2     → claude-opus-4-6 (batch)   (PRODUCTION translation)
                effort=max, adaptive thinking=ON
                tool_mode=auto-disabled (batch constraint)
  Phase 2 alt → claude-opus-4-6 (stream)  (small volumes, dev runs)

  ROUTING ENGINE: pipeline.common.phase_llm_router.PhaseLLMRouter
  CONFIG KEY:     config.yaml → translation.phase_models
  PROVIDER KEY:   config.yaml → translation.provider

  OPENROUTER PATH (optional, full prequel cache mode)
  ─────────────────────────────────────────────────────
  Full prequel bundle:  Available via OpenRouter with
                        context window > 850k tokens
                        (FULL_PREQUEL_ROUTE_NOT_OPENROUTER
                         fallback activates for non-OR routes)
```

---

## 9. Derived Artifact Graph

```text
  manifest.json (Phase 1)
       │
       ├──► metadata_en.json (Phase 1.5)
       │         │
       │         ├──► voice_rag/*.json (Phase 1.51)
       │         │         │
       │         │         └──[voice guidance]──► Phase 2 prompt
       │         │
       │         ├──► EPS.chapter_data (Phase 1.52)
       │         │         │
       │         │         └──[EPS directives]──► Phase 2 prompt
       │         │
       │         └──[name/glossary]────────────► Phase 2 prompt
       │
       ├──► rich_metadata_cache_patch_en.json (Phase 1.55)
       │         │
       │         └──[scene context]────────────► Phase 2 prompt
       │
       ├──► TRANSLATION_BRIEF.md (Phase 1.56)
       │         │
       │         └──[challenge flags]──────────► Phase 2 prompt
       │
       ├──► visual_cache.json / ADN (Phase 1.6)
       │         │
       │         └──[ADN directives]───────────► Phase 2 prompt
       │
       └──► PLANS/*.json (Phase 1.7)
                 │
                 └──[scene plans]─────────────► Phase 2 prompt
```

All arrows converge into the Translation Runtime as **read-only derived views**. None may redefine canon during translation.

---

## 10. Canon Authority Hierarchy

The Canon Event Fidelity v2 (CFv2) system defines the authority chain that governs every translation decision:

```text
  ═══════════════════════════════════════════════
  CANON EVENT FIDELITY v2 · AUTHORITY HIERARCHY
  ═══════════════════════════════════════════════

  RANK 1  JP Source Text
          ─────────────
          Canonical truth for ALL events, dialogue, plot.
          Translation renders it — never invents.

  RANK 2  Volume Canon (manifest, metadata_en)
          ────────────────────────────────────
          Character names, glossary, name-order policy.
          Wins all conflicts with derivative sources.

  RANK 3  Series Bible (advisory)
          ────────────────────────
          Cross-volume continuity memory.
          Informs — never overrides local volume canon.

  RANK 4  EPS Bands
          ─────────
          Emotional register guidance per character.
          Advisory (dialogue register follows JP source first).

  RANK 5  Art Director's Notes (ADN / visual_cache)
          ────────────────────────────────────────────
          Style guidance from illustrations.
          Descriptive context, NOT additional canon.
          canon_override=TRUE only on explicit scene items.

  RANK 6  Scene Plans
          ───────────
          Narrative beat scaffolding.
          Generates from canon; never re-defines it.

  RANK 7  Translation Brief
          ──────────────────
          Pre-analysis challenge flags.
          Heuristic guidance; JP source overrides all specific claims.

  ═══════════════════════════════════════════════
  BLOCKED CODES (CFv2):
   BLOCKED:POV_MISMATCH
   BLOCKED:CHARACTER_ABSENT
   BLOCKED:SOURCE_CONTRADICTION
   BLOCKED:CANON_FIDELITY
   BLOCKED:WORD_BUDGET_EXCEEDED
  ═══════════════════════════════════════════════
```

---

## 11. Post-Processing Module Stack

```text
  ═══════════════════════════════════════════════════
  COPYEDIT POST-PASS · ORDERED EXECUTION STACK
  ═══════════════════════════════════════════════════

  Input: raw EN/*.md from Phase 2

  Step 1 · TYPOGRAPHY NORMALIZATION
    ───────────────────────────────
    · Multi-ellipsis collapse (……→…, …………→…)
    · Opening/closing quote standardization
    · Em-dash normalization
    · CJK punctuation strip
    [deterministic, regex-based]

  Step 2 · WHITESPACE NORMALIZATION
    ────────────────────────────────
    · Trailing whitespace removal
    · Double-blank line collapse
    · Line-ending normalization
    [deterministic]

  Step 3 · NAME-ORDER NORMALIZATION
    ─────────────────────────────────
    · Applies name_order_policy from Volume Canon
    · Japanese-pattern names → canonical EN order
    [deterministic, canon-driven]

  Step 4 · GRAMMAR AUDIT (REPORT ONLY)
    ─────────────────────────────────────
    · GrammarValidator scans for violations
    · auto_fix = OFF (policy-hardened)
    · Writes grammar_validation_report.json
    · Never mutates prose content
    [reporting only as of MTLS v1]

  Step 5 · CJK VALIDATION
    ───────────────────────
    · Scans for residual CJK characters in EN output
    · Logs violations; blocks EPUB build if critical
    [deterministic]

  Output: clean EN/*.md ready for Phase 2.5 and Phase 4
  ═══════════════════════════════════════════════════
```

---

## 12. Observability and Audit Layer

Every MTLS v1 run produces the following machine-readable artifacts:

| Artifact | Path | Content |
|----------|------|---------|
| `translation_log.json` | `WORK/<vol>/` | Per-chapter token counts, cost, model, batch IDs |
| `cost_audit_last_run.json` | `WORK/<vol>/` | Full cost breakdown with cache hit ratio |
| `cost_audit_last_run.md` | `WORK/<vol>/` | Human-readable cost summary |
| `THINKING/chapter_NN_THINKING.md` | `WORK/<vol>/THINKING/` | Opus extended thinking log per chapter |
| `cache/thoughts/i-NNN.json` | `WORK/<vol>/cache/thoughts/` | Gemini visual reasoning log per illustration |
| `DEBUG/LATEST_TRANSLATOR_DEBUG_LOG.txt` | `WORK/<vol>/DEBUG/` | Runtime debug log |
| `QC/quality_report.md` | `WORK/<vol>/QC/` | Composite quality report from auditors |
| `QC/gemini_comparison.json` | `WORK/<vol>/QC/` | Gemini pre-KF vs final output diff |
| `audits/grammar_validation_report.json` | `WORK/<vol>/audits/` | Grammar audit findings |
| `continuity_diff_report.json` | `WORK/<vol>/` | Phase 2.5 Bible delta report |
| `PIPELINE_INTEGRATION_AUDIT.md` | `WORK/<vol>/` | Per-volume pipeline audit summary |

---

## 13. Target Architecture (v1 Canonical Form)

The target architecture for MTLS v1 consolidates the current multi-surface state into a two-canon, read-only-derived-artifacts model:

**Principle A: Two canonical stores only**  
- `volume_canon.json` — authoritative for current volume during Phases 1–2  
- `series_bible.json` — authoritative for cross-volume carry-forward only; advisory at runtime

**Principle B: Derived artifacts are rebuildable views**  
- If an artifact can be regenerated from canon, it is not canon.  
- Manual patching of derived artifacts is forbidden.

**Principle C: One canonical identity resolver**  
- `CanonResolver` module resolves JP key → canonical EN name, aliases, fingerprint key, EPS state  
- All phases, including planner, multimodal, translator, and Bible sync, call the same resolver

**Principle D: Phase write scopes are narrow and explicit**  
- Librarian: raw source only  
- Phase 1.5 family: `volume_canon.json` only  
- Phase 1.6: `visual_cache.json` only  
- Phase 1.7: scene plans only  
- Phase 2: EN output, logs — no canon mutation  
- Phase 2.5: only authorized upstream continuity writer

**Principle E: Deterministic cleanup after generation, not before**  
- All mechanical normalization belongs in the post-pass  
- Not in Librarian, not as ad hoc repair in later phases

---

## 14. Failure Modes and Recovery Paths

| Phase | Failure Mode | Symptom | Recovery |
|-------|-------------|---------|---------|
| 1 | Malformed EPUB | RuntimeError at extraction | Validate EPUB; re-run |
| 1.5 | Schema version mismatch | Fields overwritten | Schema autoupdate preserves v3+ fields; re-run safe |
| 1.6 | No illustrations | visual_cache empty/None | Phase 2 gracefully skips ADN injection |
| 1.6 | Vision model failure | Missing thought cache | Non-fatal warning; translation proceeds without ADN |
| 1.7 | Scene plan schema error | Invalid PLANS/*.json | Re-run Phase 1.7; Phase 2 has fallback scene-plan defaults |
| 2 | Batch timeout (>24h) | Chapters expired | Re-submit failed chapters via streaming fallback |
| 2 | CFv2 BLOCKED code returned | Chapter flagged | Human review of flagged passage; re-run with override if correct |
| 2.5 | Bible conflict | Continuity diff > threshold | Human review continuity_diff_report.json; approve push |
| All | Cache bleed (context contamination) | Unexpected character names | Isolate affected chapters; restart with fresh cache slot |

---

## 15. Design Governance Principles

These principles are invariants for MTLS v1. Any change to the pipeline must preserve all of them.

1. **One canon authority per scope.** Volume Canon for local facts. Series Canon for cross-volume facts. They do not peer-write.

2. **Derived artifacts are views, not truth.** `visual_cache.json`, `PLANS/*.json`, `.context/*.json`, `translation_log.json`, `continuity_pack.json` are never authoritative. They enrich prompts; they do not redefine canon.

3. **Translation is rendering, not authoring.** Phase 2 renders JP source into EN. It does not invent, extend, or modify plot, character, or canon.

4. **Post-processing is deterministic.** The copyedit post-pass applies only mechanical normalization. Grammar auto-fix is OFF. No in-band prose mutation after Phase 2.

5. **Role separation is preserved.** Every phase has one job. The translator is not a validator, formatter, or tool orchestrator during chapter generation.

6. **Bible is advisory at runtime.** Local volume canon wins every conflict. Bible import mode should be explicit: `canon-safe`, `continuity-only`, or `bypassed`.

7. **Phase 2.5 is the only authorized upstream writer.** After translation completes, only Phase 2.5 may push continuity changes to the series Bible.

8. **Opus reasoning budget is spent on literary craft.** Every architectural decision is evaluated against this constraint: does it reduce or protect Opus's ability to spend reasoning tokens on translation?

---

## Appendix A: CLI Reference

```bash
# Full pipeline (auto-generate volume ID)
./mtl run INPUT/my_novel.epub

# Full pipeline with fixed ID
./mtl run INPUT/my_novel.epub --id 20260305_17a8

# Individual phases
./mtl phase1 INPUT/my_novel.epub         # Librarian
./mtl phase1.5 <volume_id>               # Metadata translation
./mtl phase1.51 <volume_id>              # Voice RAG backfill
./mtl phase1.52 <volume_id>              # EPS band backfill
./mtl phase1.55 <volume_id>              # Rich metadata cache
./mtl phase1.56 <volume_id>              # Translation brief
./mtl phase1.6 <volume_id>               # Multimodal processor
./mtl phase1.7 <volume_id>               # Scene planner
./mtl phase1.7-cp <volume_id>            # Co-Processor cache refresh

# Translation
./mtl phase2 <volume_id>                 # Streaming translation
./mtl batch <volume_id>                  # Anthropic Batch (production)

# Bible + Build
./mtl phase2.5 <volume_id>              # Bible update (auto post-phase2)
./mtl phase4 <volume_id>                # EPUB build

# Utilities
./mtl list                               # List all volumes
./mtl status <volume_id>                 # Phase completion status
./mtl config --show                      # Show active configuration
```

---

## Appendix B: Key File Paths Reference

```text
pipeline/
├── config.yaml                          ← Master configuration
├── modules/                             ← Prompt modules + AI support code
│   ├── MEGA_CORE_TRANSLATION_ENGINE.md  ← Core translator prompt module
│   ├── MEGA_CHARACTER_VOICE_SYSTEM.md   ← Voice rendering module
│   └── *.py                             ← Support modules (RAG, idiom, etc.)
├── pipeline/                            ← Phase implementation code
│   ├── librarian/                       ← Phase 1
│   ├── metadata_processor/              ← Phases 1.5, 1.51, 1.52, 1.55, 1.56
│   ├── planner/                         ← Phases 1.7, 1.7-cp
│   ├── translator/                      ← Phase 2
│   ├── narrator/                        ← Phase 2.5
│   ├── post_processor/                  ← Copyedit post-pass
│   ├── audit/                           ← Auditor dispatch
│   └── builder/                         ← Phase 4
├── auditors/                            ← QC auditor implementations
├── chroma_*/                            ← Vector store indexes (ChromaDB)
├── bibles/                              ← Series Bible JSON files
├── WORK/<volume_id>/                    ← Per-volume working directory
│   ├── JP/                              ← JP source markdown
│   ├── EN/                              ← EN output markdown
│   ├── assets/                          ← Extracted illustrations
│   ├── PLANS/                           ← Scene plans
│   ├── THINKING/                        ← Opus thinking logs
│   ├── QC/                              ← Quality reports
│   └── manifest.json                    ← Volume state
└── OUTPUT/                              ← Final EPUB output
```

---

*This document is the canonical system architecture reference for MTLS v1.*  
*Cross-reference:* [← Root README](../../README.md) · [MTLS_V1_AI_TANDEM_ARCHITECTURE.md](./MTLS_V1_AI_TANDEM_ARCHITECTURE.md) · [MTLS_V1_PIPELINE_PREPARATION_PHASES.md](./MTLS_V1_PIPELINE_PREPARATION_PHASES.md) · [MTLS_V1_OPUS_TOKEN_ALLOCATION.md](./MTLS_V1_OPUS_TOKEN_ALLOCATION.md)

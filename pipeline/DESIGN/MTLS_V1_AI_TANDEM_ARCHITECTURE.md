# MTLS v1 — AI Tandem Architecture: Gemini 3, Claude Opus 4.6, and the 1M-Token Roadmap

**Document type:** Formal technical specification and design analysis  
**Abbreviation:** MTLS (MTL Studio)  
**Version:** 1.0  
**Status:** Canonical  
**Scope:** Official model specifications, MTLS applied configuration, dual-model interaction patterns, embedding architecture, and the 1M input token future roadmap  
**Primary sources:** Gemini 3 API documentation, Claude Opus 4.6 release notes, Anthropic context window documentation, batch processing API documentation, MTLS migration report (Gemini 2.5 Pro → Opus 4.6)  
**Last updated:** 2026-03-06

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Why Two AI Families?](#2-why-two-ai-families)
3. [Google Gemini 3 — Official Specification](#3-google-gemini-3--official-specification)
4. [Anthropic Claude Opus 4.6 — Official Specification](#4-anthropic-claude-opus-46--official-specification)
5. [MTLS Applied Configuration: Gemini 3](#5-mtls-applied-configuration-gemini-3)
6. [MTLS Applied Configuration: Claude Opus 4.6](#6-mtls-applied-configuration-claude-opus-46)
7. [Tandem Interaction Architecture](#7-tandem-interaction-architecture)
8. [Embedding Architecture: Gemini + ChromaDB](#8-embedding-architecture-gemini--chromadb)
9. [Migration Evidence: Why Opus Replaced Gemini for Translation](#9-migration-evidence-why-opus-replaced-gemini-for-translation)
10. [The 1M Input Token Roadmap for Opus](#10-the-1m-input-token-roadmap-for-opus)
11. [Cost Architecture](#11-cost-architecture)
12. [Configuration Reference](#12-configuration-reference)

---

## 1. Executive Summary

MTLS v1 employs two AI model families in complementary roles. Neither family is used for everything. Each is applied only where its specific capabilities create a decisive advantage.

**Google Gemini 3 (Pro / Flash)** handles:
- All preparation-phase work (metadata translation, illustration analysis, scene planning)
- Embedding generation for all ChromaDB vector stores
- Fast, high-volume multi-modal processing
- Bible update diffs and continuity packaging

**Anthropic Claude Opus 4.6** handles:
- All production literary translation
- Extended adaptive thinking for scene interpretation
- Character voice rendering with sub-chapter register precision
- **Zero-Censorship Resolve**: Reliable rendering of adult-themed/explicit content (AV-themed romcoms) where other models (Gemini) would trigger safety blocks.

**Anthropic Claude Sonnet 4** handles:
- **Phase 1.56 Translation's Brief Agent**: Pre-analyzing chapter challenges and surfacing nuanced register/literary flags before the primary Opus pass.
- **High-speed validation passes** where technical baseline checks require more intelligence than Haiku but less cost than Opus.

The tandem design is not incidental. It is a deliberate cognitive labor division: Gemini 3 resolves structure and imagery upstream; Sonnet 4 surfaces the literary brief; Opus 4.6 receives a pre-resolved, high-context environment and spends its reasoning budget entirely on literary craft and genre-authentic (including uncensored) rendering.

The current production architecture uses standard 200K context. A formal 1M input token roadmap is defined in Section 10, enabling whole-volume single-pass translation as the next significant capability threshold.

---

## 2. Why Two AI Families?

The core translation challenge in literary Japanese LN localization requires two fundamentally different cognitive operations:

**Operation A: High-recall structured interpretation**  
Analyzing illustrations for scene-relevant details, translating metadata fields, building cross-referential knowledge graphs, deciding which narrative facts are canon. This requires fast, broad-world knowledge and efficient multimodal vision handling. It does not require deep sustained reasoning on any single output.

→ **Gemini 3 is optimal for Operation A.**

**Operation B: Sustained literary judgment under multiple soft constraints**  
Rendering one chapter of Japanese prose into English while simultaneously maintaining character voice fingerprints, emotional register calibration, cultural localization of humor and subtext, and pacing decisions. Every paragraph requires literary judgment. None of it can be cached or pre-decided.

→ **Opus 4.6 is optimal for Operation B.**

The critical insight that defines the tandem architecture: **these two operations should never happen at the same time in the same model.** Forcing Opus to do Operation A wastes its premium reasoning budget. Forcing Gemini to do Operation B produces structurally inferior prose. The architecture separates them cleanly.

---

## 3. Google Gemini 3 — Official Specification

### 3.1 Model Family Overview

Gemini 3 is Google's most intelligent model family as of 2026, built on a foundation of state-of-the-art reasoning, designed for agentic workflows, autonomous coding, and complex multimodal tasks.

| Model ID | Context Window (In / Out) | Knowledge Cutoff | Pricing (Input / Output) |
|----------|--------------------------|-----------------|--------------------------|
| **gemini-3.1-flash-lite-preview** | 1M / 64k | Jan 2025 | $0.25 / $1.50 |
| **gemini-3.1-flash-image-preview** | 128k / 32k | Jan 2025 | $0.25 text / $0.067 image output |
| **gemini-3.1-pro-preview** | 1M / 64k | Jan 2025 | $2 / $12 (<200k tokens); $4 / $18 (>200k) |
| **gemini-3-flash-preview** | 1M / 64k | Jan 2025 | $0.50 / $3 |
| **gemini-3-pro-image-preview** | 65k / 32k | Jan 2025 | $2 text / $0.134 image output |

> **Note for MTLS operators:** As of 2026-03-09, `gemini-3-pro-preview` is deprecated. MTLS uses `gemini-3.1-pro-preview` for high-capability tasks and `gemini-3-flash-preview` for volume operations.

### 3.2 Thinking Level Control

Gemini 3 introduces the `thinking_level` parameter, which controls the maximum depth of internal reasoning before producing a response. Unlike hard token budgets, Gemini 3 treats thinking levels as relative allowances.

| Thinking Level | gemini-3.1 Pro | gemini-3 Flash | Description |
|---------------|----------------|----------------|-------------|
| `minimal` | Not supported | Supported | Near-zero thinking; maximizes latency efficiency for chat |
| `low` | Supported | Supported | Minimizes latency; best for simple instruction following |
| `medium` | Supported | Supported | Balanced thinking for most tasks |
| `high` | Supported (Default) | Supported (Default) | Maximizes reasoning depth; slower first token |

**MTLS setting (Phase 1.6 illustration analysis):** `thinking_level: "medium"` — provides sufficient scene subtext and EPS inference without the latency cost of `high`. Illustration analysis processing time: 18.9s per image average in the 16e6 run.

### 3.3 Media Resolution Control

Gemini 3 provides granular control over multimodal processing via `media_resolution`.

| Setting | Max Tokens (Image) | Max Tokens (Video) | MTLS Usage |
|---------|-------------------|--------------------|-----------|
| `media_resolution_low` | 280 | 70 | Not primary |
| `media_resolution_medium` | 560 | 70 | — |
| `media_resolution_high` | 1120 | 280 | **Phase 1.6 illustrations** |

**MTLS setting:** `media_resolution_high` for all illustration analysis in Phase 1.6. This maximizes the model's ability to read fine text on illustration title pages and identify small character identity details (hairpin style, uniform variation, emotional micro-expression).

### 3.4 Thought Signatures

Gemini 3 introduces thought signatures — encrypted representations of the model's internal reasoning — that must be returned in subsequent API calls to preserve chain-of-thought continuity across multi-step workflows.

**MTLS relevance:** Phase 1.7 (Scene Planner) uses multi-step Gemini calls where thought signatures are managed automatically by the Google GenAI SDK. The MTLS pipeline does not need to manually manage thought signature fields when using the official SDK.

### 3.5 Temperature Recommendation

For all Gemini 3 models, Google strongly recommends keeping `temperature = 1.0` (default). Lowering temperature can cause looping or degraded performance in reasoning tasks.

**MTLS configuration:** Temperature is not explicitly set, preserving the default of 1.0 across all Gemini 3 phases.

---

## 4. Anthropic Claude Opus 4.6 — Official Specification

### 4.1 Model Overview

| Claude Opus 4.6 | `claude-opus-4-6` | 200K (1M beta) | 128K tokens | Adaptive thinking, effort=max, fast mode, zero censorship |
| Claude Sonnet 4 | `claude-sonnet-4` | 200K | 64K tokens | Adaptive thinking, Brief Agent (Ph 1.56) |
| Claude Sonnet 4.6 | `claude-sonnet-4-6` | 200K (1M beta) | 64K tokens | Adaptive thinking, effort param, web tools |

### 4.2 Adaptive Thinking (Recommended Mode)

`thinking: {type: "adaptive"}` is the recommended thinking mode for Opus 4.6. In adaptive mode:

- Claude dynamically decides when and how much to think
- At `effort=high` (default), Claude almost always activates thinking
- At `effort=max`, thinking is maximized with no token constraints
- At lower effort levels, Claude may skip thinking for simpler segments
- Adaptive thinking automatically enables interleaved thinking

**Deprecation note:** `thinking: {type: "enabled", budget_tokens: N}` is deprecated on Opus 4.6. It remains functional but will be removed in a future release.

### 4.3 Effort Parameter (Generally Available)

The `effort` parameter (GA as of Claude 4.6) controls how many tokens Claude allocates across the full response, including thinking, prose, and any tool calls.

| Level | Description | Availability |
|-------|-------------|-------------|
| `max` | Absolute maximum capability; no token constraints | Opus 4.6 only |
| `high` | High capability; default behavior | All supported models |
| `medium` | Balanced; moderate token savings | All supported models |
| `low` | Most efficient; significant token savings | All supported models |

**Key property:** Effort controls all token spend — text, thinking, and tool calls. At `low` effort, Claude makes fewer tool calls and produces more concise text. At `max` effort, Claude activates maximum reasoning depth.

**MTLS configuration:** `effort=max` for all Phase 2 production translation runs.

### 4.4 128K Output Tokens

Opus 4.6 supports up to 128K output tokens — double the previous 64K limit. This enables:
- Longer thinking budgets for complex chapters
- More comprehensive chapter output without truncation
- Full single-pass translation of longer chapters

**MTLS implication:** The 16e6 run's most expensive chapter (Chapter 1) produced 35,591 output tokens. At 128K max, Opus 4.6 has full headroom for the longest chapters in the corpus.

### 4.5 Fast Mode (Research Preview)

`speed: "fast"` delivers up to 2.5x faster output token generation for Opus models. Fast mode uses the same model intelligence with faster inference.

| Parameter | Value |
|-----------|-------|
| Speed increase | Up to 2.5x |
| Pricing | $30 / $150 per MTok (premium) |
| Intelligence change | None |

**MTLS roadmap applicability:** Fast mode is not used in current MTLS production (batch mode is preferred for cost). Fast mode becomes relevant for streaming translation when latency matters more than cost (e.g., live demo runs, single-chapter re-runs).

### 4.6 Compaction API (Beta)

Compaction provides automatic server-side context summarization for Opus 4.6, enabling effectively infinite conversation windows. When context approaches the 200K limit, the API automatically summarizes earlier parts.

**MTLS relevance:** Currently not used in production pipeline (batch mode processes chapters independently, not as a continuous conversation). Compaction becomes architecturally significant in two scenarios: (a) the full-prequel-bundle route, where prior volume chapters need to remain in context across a long translation session; (b) future agentic translation workflows.

### 4.7 Context Awareness (Sonnet 4.6 / Haiku 4.5)

Claude Sonnet 4.6 and Haiku 4.5 receive explicit context budget information:

```xml
<budget:token_budget>200000</budget:token_budget>
```

After each tool call:
```xml
<system_warning>Token usage: 35000/200000; 165000 remaining</system_warning>
```

**MTLS implication:** Haiku-class models used in the QC auditor pass receive context budget signals, enabling the auditor to allocate its analysis proportionally to available context.

---

## 5. MTLS Applied Configuration: Gemini 3

### 5.1 Phase-Level Gemini Configuration Table

| Phase | Model | Thinking Level | Key Function in MTLS |
|-------|-------|---------------|---------------------|
| 1.5 | gemini-3-flash-preview | Default (high) | Translate title, author, chapter titles, character names |
| 1.51 | gemini-3-flash-preview | Default | Generate character voice fingerprints from JP source |
| 1.52 | gemini-3-flash-preview | Default | Assign EPS bands per chapter per character |
| 1.55 | gemini-3-flash-preview | Default | Full JP corpus cache + rich scene metadata extraction |
| 1.6 | gemini-3-flash-preview (vision) | medium | Vision analysis: illustrations → Art Director's Notes |
| 1.7 | gemini-3.1-pro-preview | high | Scene planning: narrative beats, POV, rhythm scaffold |
| 2.5 | gemini-3-flash-preview | Default | Bible update: diff local canon vs series Bible |
| Embedding | Gemini embedding API | — | Build ChromaDB indexes for Voice RAG, pattern stores |

### 5.2 Phase 1.6: Art Director's Notes Generation — Full Flow

The most sophisticated Gemini operation in MTLS. For each illustration:

**Input to Gemini:**
```
- Raw illustration JPEG (media_resolution_high = 1120 tokens/image)
- Chapter context (which chapter this appears in)
- Character registry (who appears in this volume)
- Scene type hints
- EPS system definitions (COOL/WARM/CLOSE/HOT/PEAK/MELT bands)
- ADN schema specification
```

**Gemini reasoning process** (visible in `cache/thoughts/i-NNN.json`):
1. Composition analysis — panel layout, visual narrative flow
2. Emotional delta inference — surface vs underlying state
3. Identity resolution — confirm character via non-color identifiers (hairstyle, posture, accessories)
4. EPS signal detection — which band is the character in based on visual cues
5. Spoiler detection — are visual facts that haven't been revealed in the text yet visible?
6. ADN generation — structured JSON with DID, type, priority, scope, canon_override, word_budget

**Sample Gemini reasoning excerpt** (i-011, Chapter 1, 弓道部 volume):
> *"The Emotional Delta is where things get interesting. On the surface, it's the 'Cool Beauty' persona. She's stoic, composed. But the underlying emotion, I infer, is exhaustion or a heavy burden. The weight of the equipment, and the downward tilt of her gaze in the close-up, strongly suggest this."*

**Output ADN structure** (used directly by Phase 2 translator):
```json
{
  "DID": "i-011-d2",
  "type": "atmospheric_frame",
  "priority": "required",
  "scope": "post_marker_narration",
  "canon_override": false,
  "word_budget": null,
  "summary": "Translate Rino's internal state with a 'heavy' or 'stiff' lexical cluster"
}
```

### 5.3 Gemini Role Boundary in MTLS

Gemini is explicitly **not allowed** to:
- Define canonical character names (Phase 2 Opus may override via CFv2)
- Create new plot events (ADN directives are stylistic, not canonical)
- Produce EN prose that enters the final output (visual_cache.json is never output, only guidance)
- Modify the Series Bible directly (only Phase 2.5 may do this, and it goes via diff review)

---

## 6. MTLS Applied Configuration: Claude Opus 4.6

### 6.1 Phase 2 Production Translation Configuration

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Model | `claude-opus-4-6` | Maximum literary capability |
| Effort | `max` | No constraint on reasoning depth |
| Thinking mode | `adaptive` | Dynamic; almost always activates at max effort |
| Execution mode | Anthropic Batch API | 50% cost reduction, async, 1h avg |
| Max output tokens | 128K per chapter | Full headroom for longest chapters |
| Tool mode | Auto-disabled (batch constraint) | Removes tool-branch reasoning overhead |
| Prompt cache | 1-hour cache duration | 91.7% cache hit rate in 16e6 run |
| Provider | Anthropic direct | Not via OpenRouter (full-prequel bundle not available) |

### 6.2 Prompt Architecture Supplied to Opus

Every Phase 2 prompt contains seven information layers, all pre-assembled before Opus receives the request:

1. **Canon Event Fidelity v2 block** — pre-resolves instruction hierarchy  
2. **Character registry with voice fingerprints** — from Volume Canon + Voice RAG  
3. **EPS directives per character** — current band, delta, trigger  
4. **Art Director's Notes (ADN)** — structured, not raw images  
5. **Scene plan context** — narrative beat, POV, act position  
6. **Translation Brief notes** — chapter-level challenge flags from Phase 1.56  
7. **JP source chapter text** — the canonical input  

Opus does not receive:
- Raw image data
- Instruction hierarchy ambiguities
- Tool planning prompts
- Output format templates beyond basic Markdown headers

### 6.3 Thinking Log Evidence

The 12 `THINKING/chapter_NN_THINKING.md` logs from the 16e6 full-volume run confirm that Opus reasoning content is entirely literary in nature. Representative reasoning topics observed:

- How to localize a cultural pun tied to kyudo (archery) terminology
- Whether Rino's internal monologue should use clipped or full sentence structures given her COOL→HOT EPS transition in Chapter 5
- How to render the narrator's gamer metaphors at consistent frequency across chapters
- The appropriate lexical distance for Touya's third-person perspective on Rino's composure
- Whether a specific cultural reference should be rendered directly or with a parenthetical gloss

**Reasoning topics not observed (confirmed zero):**
- Instruction conflict resolution
- Tool-use planning
- Schema shape verification
- Provider routing decisions
- Output format compliance checking

---

## 7. Tandem Interaction Architecture

The handoff between Gemini and Opus is not a direct API call. It is a structured data transformation: Gemini produces structured artifacts; Opus consumes structured artifacts, never raw Gemini output.

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MTLS v1 · GEMINI → OPUS HANDOFF DIAGRAM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Gemini 3 Layer (Phases 1.5 → 1.7)           Opus 4.6 Layer (Phase 2)
  ──────────────────────────────────           ──────────────────────────

  Raw JP text                                  (never sees raw JP directly
  Raw illustrations                             without context pre-pack)
  Raw OPF metadata
       │                                              │
       ▼                                              │
  ┌────────────────────────────────┐                 │
  │ Gemini 3 Flash (metadata)      │                 │
  │ Gemini 3 Flash Vision (images) │                 │
  │ Gemini 3.1 Pro (scene plans)   │                 │
  └────────────────────────────────┘                 │
       │                                              │
       │ produces structured artifacts:               │
       │                                              │
       ├──► metadata_en.json ──────────────────────► │
       ├──► voice_fingerprints ─────────────────────►│
       ├──► EPS.chapter_data ───────────────────────►│
       ├──► rich_metadata_cache_patch_en.json ──────►│
       ├──► TRANSLATION_BRIEF.md ──────────────────► │
       ├──► visual_cache.json (ADN) ───────────────► │
       └──► PLANS/*.json (scene plans) ────────────► │
                                                     │
                             ┌───────────────────────┘
                             │ receives pre-assembled context:
                             │  · canonical character registry
                             │  · voice fingerprints
                             │  · EPS directives (not raw signals)
                             │  · structured ADN (not raw images)
                             │  · scene plans (not raw narrative)
                             │  · challenge flags (not raw analysis)
                             │  · CFv2 hierarchy (pre-resolved)
                             │
                             ▼
                   ┌──────────────────────┐
                   │  Claude Opus 4.6     │
                   │  effort=max          │
                   │  adaptive thinking   │
                   │                      │
                   │  Spends 100% of      │
                   │  reasoning on:       │
                   │  · scene rendering   │
                   │  · voice control     │
                   │  · cultural adapt.   │
                   │  · pacing/rhythm     │
                   │  · prose decisions   │
                   └──────────────────────┘
                             │
                             ▼
                   EN/CHAPTER_NN_EN.md
                   THINKING/chapter_NN_THINKING.md
```

### 7.1 Information Transformation Rules

| Input Type | Gemini Sees | Opus Receives | Transformation |
|-----------|------------|---------------|----------------|
| Illustrations | Raw JPEG (1120 tokens/img) | ADN JSON (structured directives) | Vision reasoning → prose guidance |
| Character names | JP kanji + OPF metadata | Canonical EN names + fingerprint keys | Metadata translation → canon registry |
| Scene context | Full JP chapter + narrative | Scene plan JSON (beat/POV/tone) | Narrative analysis → planning scaffold |
| EPS state | Character behavior cues | Band label + delta + trigger | Signal inference → register guidance |
| Translation challenges | Full-volume JP corpora | TRANSLATION_BRIEF.md flags | Pre-analysis → challenge registry |

**The transformation invariant:** Every Gemini output that enters Phase 2 is a structured artifact, not free-form prose. Opus never directly extends Gemini text.

---

## 8. Embedding Architecture: Gemini + ChromaDB

### 8.1 Role of Embeddings in MTLS

Vector embeddings power the retrieval systems that make MTLS's contextual guidance consistent across chapters and volumes:

| System | What It Retrieves | Where Used |
|--------|------------------|-----------|
| Voice RAG | Character speech pattern examples | Phase 2: per-character voice fingerprint injection |
| Series Bible RAG | Cross-volume character memory + decisions | Phase 1.5 / Phase 2 (advisory) |
| English Pattern Store | EN idiom and grammar patterns | Phase 2: anti-AI-ism guidance |
| Vietnamese Pattern Store | VN grammar patterns | Phase 2 (VN target): VN guidance |
| Sino-VN Store | Sino-Vietnamese vocabulary | Phase 2 (VN target): term lookup |

### 8.2 Gemini Embedding Model

All ChromaDB indexes in MTLS are built using the Gemini embedding API, providing semantic similarity search compatible with the preparation-phase context.

**Key properties for MTLS use:**
- Text embeddings are multilingual — JP and EN texts embed in compatible semantic space
- Enables cross-language similarity: a JP phrase in the source can retrieve relevant EN pattern examples
- Index update happens in Phase 2.5: new canonical decisions from a translated volume are embedded and added to the Bible index for future sequel use

### 8.3 ChromaDB Store Architecture

```text
  ┌─────────────────────────────────────────────────────────────┐
  │  MTLS v1 · CHROMA VECTOR STORE INVENTORY                   │
  ├─────────────────────────────────────────────────────────────┤
  │                                                             │
  │  chroma_series_bible/                                       │
  │  ├── Series-level character registry                        │
  │  ├── Cross-volume glossary entries                          │
  │  ├── Historical translation decisions                       │
  │  └── EPS evolution records                                  │
  │      [Updated: Phase 2.5]                                   │
  │      [Read: Phase 1.5 sequel detection, Phase 2 advisory]   │
  │                                                             │
  │  chroma_english_patterns/                                   │
  │  ├── EN idiom examples by register                          │
  │  ├── Anti-AI-ism pattern library                            │
  │  ├── Character-voice exemplars (EN output)                  │
  │  └── Prose quality reference samples                        │
  │      [Updated: manually curated + Phase 2.5 approved adds]  │
  │      [Read: Phase 2 grammar/voice RAG queries]              │
  │                                                             │
  │  chroma_vietnamese_patterns/                                │
  │  ├── VN grammar pattern library                             │
  │  ├── Honorific system examples                              │
  │  └── VN prose rhythm references                             │
  │      [Used for VN target language routes only]              │
  │                                                             │
  │  chroma_sino_vn/                                            │
  │  ├── Sino-Vietnamese vocabulary                             │
  │  ├── Classical + modern usage distinction                   │
  │  └── Register mapping examples                             │
  │      [Used for VN target language routes only]              │
  │                                                             │
  │  voice_rag/ (per-volume)                                    │
  │  └── WORK/<vol>/.context/voice_rag/voice_index.json         │
  │      Per-character voice fingerprint index                  │
  │      [Built: Phase 1.51]                                    │
  │      [Read: Phase 2 — per-character voice retrieval]        │
  │                                                             │
  └─────────────────────────────────────────────────────────────┘
```

### 8.4 Retrieval at Translation Time

During Phase 2, for each chapter:

1. The translator agent queries the Voice RAG index with the current character's key
2. Gemini embedding similarity search returns the k-nearest voice pattern examples
3. These examples are injected into the character's section of the translation prompt
4. The English Pattern Store is queried with scene-type signals to retrieve anti-AI-ism guidance
5. The Series Bible RAG is consulted for any cross-volume continuity signals (advisory only)

The retrieval cost is minimal (<0.1s per query) because ChromaDB is a local in-process vector database.

---

## 9. Migration Evidence: Why Opus Replaced Gemini for Translation

The MTLS pipeline used Gemini 2.5 Pro as the primary translation engine before Claude Opus 4.6. The documented migration report (compiled from EN output and THINKING logs across seven volumes: Otonari Asobi Vols. 2–5 with Gemini; 19ed/1e80/116c/2131 with Opus) identified five systematic Gemini failures:

### 9.1 Contraction Rate Underperformance

Gemini-translated dialogue consistently produced formal English register even when the JP source used casual/intimate forms. Characters that should have spoken in natural EN contractions (`isn't`, `wouldn't've`) were rendered with full formal forms (`is not`, `would not have`). Opus 4.6 with EPS band awareness and voice fingerprints resolved this systematically.

### 9.2 AI-ism Structural Patterns

Gemini output showed higher rates of structural AI-isms: explanatory transitions, summary-style paragraph openings, topic-sentence-heavy prose. These are recognizable as machine-generated phrasing patterns that reduce reader trust. Opus with the MEGA_CORE_TRANSLATION_ENGINE prompt module and Anti-AI-ism agent showed measurable reduction.

### 9.3 Context Architecture Inefficiency

Gemini's token architecture at translation time was less cache-stable. The Anthropic 1-hour prompt cache mechanism (available to Opus) allowed MTLS to achieve 91.7% cache hit rates in the 16e6 run, reducing effective cost dramatically. The equivalent Gemini path showed lower cache hit rates due to architectural differences in prompt assembly.

### 9.4 Procedural vs. Internalized Voice

Gemini's thinking logs (when available) showed visible rule-compliance reasoning: "This character is marked COOL; therefore I should use formal sentence structures." Opus's thinking logs show internalized voice: reasoning about how this specific line by this specific character sounds, not about which rule applies. The quality difference in output aligns with this reasoning difference.

### 9.5 QC Integration Gap

The Gemini pipeline had no formal downstream auditor pass. The Opus 4.6 pipeline introduced the full Auditor stack (FidelityAuditor, IntegrityAuditor, ProseAuditor, NameConsistencyAuditor, GapPreservationAuditor, FinalAuditor), producing machine-readable quality reports that enable systematic tracking across volumes.

### 9.6 Post-Migration Evidence (16e6 Run)

| Metric | Gemini 2.5 Pro Era | Claude Opus 4.6 (16e6) |
|--------|--------------------|------------------------|
| Tool calls in translation | Variable | 0 (batch mode) |
| Cache hit ratio | ~40% | 91.7% |
| Retry attempts | Present | 0 |
| Grammar auto-fix applied | Not tracked | 8 (pre-hardening) → 0 |
| Auditor pass | Not present | Full stack (6 auditors) |
| Thinking log literary focus | Procedural | Internalized craft |
| Total volume cost | Higher | $4.96 / 12 chapters |

### 9.7 Zero Censorship Resolve (The Adult Content/AV Threshold)

A critical factor in the migration from Gemini to Opus 4.6 was the "Content Safety" bottleneck. Project `0b39` (an AV-themed explicit romcom) served as the stress test.

**Discovery:** Gemini 3 Pro/Flash APIs triggered safety refusals on approximately 85% of adult-themed content in Phase 1 corpora scanning, effectively blocking the pipeline for the entire genre.

**Resolution:** Claude Opus 4.6 operates under a **Professional Translation Protocol**. When explicit content is presented within the context of translating a literary work:
- Opus maintains zero output refusal in the primary translation stream.
- It treats sexual terminology, anatomical descriptions, and explicit plot beats with clinical/literary professionalism rather than moralizing or safety-tripping.
- Results from `0b39`: Across 12 chapters of highly explicit material, Opus achieved a **100% completion rate** in its primary output. (Note: Refusal artifacts were observed only in secondary log-compression passes, which the pipeline has since disabled for adult titles).

This makes Opus 4.6 the only viable lead translator for the adult/ecchi light novel market.

---

## 10. The 1M Input Token Roadmap for Opus

### 10.1 Current State: 200K Context

The MTLS v1 production configuration runs on the standard 200K Opus 4.6 context window. Per-chapter processing in batch mode uses approximately 20K–31K input tokens (excluding cache reads) plus a 89,976-token cache creation block.

In the 16e6 run, the system prompt was estimated at 131,274 tokens (from the full_prequel_cache_gate audit). The full-prequel bundle (prior volume complete chapters) was estimated at 120,000 tokens — together these would have required 275,274 tokens, exceeding the 200K standard window. The system fell back to the Series Bible RAG mode (reason code: `FULL_PREQUEL_ROUTE_NOT_OPENROUTER`).

### 10.2 The 1M Token Beta: Official Specification

Claude Opus 4.6 supports a 1-million-token context window in beta for eligible organizations (Usage Tier 4 or custom rate limits).

**Activation:**
```python
response = client.beta.messages.create(
    model="claude-opus-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "..."}],
    betas=["context-1m-2025-08-07"],
)
```

**Pricing above 200K tokens:** 2x input, 1.5x output (automatically applied at standard pricing).

**Platform availability:** Claude API, Microsoft Foundry, Amazon Bedrock, Google Vertex AI.

**Important beta constraints:**
- Beta status: subject to change
- Rate limits: long context requests have dedicated rate limits
- Multimodal: large image/PDF batches may hit request size limits separately

### 10.3 MTLS 1M Token Capability Matrix

At 1M input tokens, MTLS can unlock four new operational modes:

#### Mode A: Full Prequel Bundle (Currently Blocked)

| Parameter | Current (200K) | With 1M |
|-----------|---------------|---------|
| System prompt | 131K tokens | 131K tokens |
| Prequel bundle | BLOCKED | 120K tokens |
| Current chapter | 24K tokens | 24K tokens |
| Total estimated | 275K (>200K limit) | 275K (within 1M) |
| Route | series_bible_rag fallback | full_prequel_cache_gate |

The full prequel bundle route provides Opus with the complete prior volume translation in context, not just Bible RAG summaries. This is expected to improve:
- Long-arc character relationship continuity
- Cross-chapter callback accuracy
- Sequel-read-through consistency for readers

#### Mode B: Whole-Volume Single Pass

All 12 chapters of a volume loaded into a single Opus context:

| Component | Estimated Tokens |
|-----------|-----------------|
| System prompt | 131K |
| 12 JP source chapters (avg 2.5K chars each) | ~36K |
| Visual cache (ADN for all illustrations) | ~20K |
| Scene plans (all 12 chapters) | ~36K |
| Voice RAG + EPS data | ~30K |
| Translation Brief | ~5K |
| Prior 11 chapters (lookback) | 0 (all in context) |
| **Total** | **~258K tokens** |

Single-pass whole-volume translation eliminates the lookback context problem entirely: Opus has the complete volume as simultaneous context.

#### Mode C: Cross-Volume Literary Analysis

Pre-loading Volumes 1–3 of a series simultaneously for Volume 4 translation:

| Scenario | Token Estimate |
|---------|----------------|
| Vol 1 EN complete (12 chapters) | ~290K |
| Vol 2 EN complete (12 chapters) | ~290K |
| Vol 3 EN complete (12 chapters) | ~290K |
| Vol 4 system prompt + current chapter | ~155K |
| **Total** | **~1.025M** |

This approaches the 1M limit but becomes feasible with the beta header. It would give Opus full literary awareness of the entire prior series, enabling sequel-series-level voice and continuity consistency that RAG retrieval cannot match.

#### Mode D: Enhanced Guidance Brief

Currently, the Translation Brief (Phase 1.56, produced by Haiku/Sonnet) is a compressed challenge-flag document. At 1M context, Opus itself could consume the full JP chapter corpus as its pre-analysis context, producing a guidance brief orders of magnitude richer than what a lighter model produces.

### 10.4 1M Roadmap: Priority Sequence

| Priority | Mode | Expected Benefit | Complexity |
|----------|------|-----------------|------------|
| 1 | Full Prequel Bundle (Mode A) | Immediate continuity improvement | Low — route already coded, blocked by window |
| 2 | Whole-Volume Single Pass (Mode B) | Eliminates lookback problem | Medium — requires batch architecture adjustment |
| 3 | Cross-Volume Literary Context (Mode C) | Series-level voice consistency | High — requires multi-volume context assembly |
| 4 | Full-Corpus Guidance Brief (Mode D) | Richer challenge pre-analysis | Medium — replaces Phase 1.56 model |

### 10.5 Activation Prerequisites

To unlock 1M context in MTLS production:

1. **Usage Tier 4 eligibility** — required by Anthropic for beta access
2. **Code change** — add `betas=["context-1m-2025-08-07"]` to the batch request builder
3. **OpenRouter route** — for full-prequel-bundle mode, the `FULL_PREQUEL_ROUTE_NOT_OPENROUTER` constraint must be resolved (either by using OpenRouter or by confirming direct API support)
4. **Cost model update** — requests exceeding 200K tokens incur 2x input pricing; cost audit must account for this
5. **Rate limit management** — long context requests have separate rate limits; batch parallelism may need adjustment

### 10.6 Extended Thinking Behavior at 1M Context

When using 1M context with adaptive thinking at `effort=max`, the extended thinking token management remains cache-efficient:

- Previous thinking blocks are automatically stripped from context on subsequent turns
- The effective context window calculation: `context_window = (input_tokens - previous_thinking_tokens) + current_turn_tokens`
- For batch mode (single-turn per chapter), thinking tokens are paid once and never carry forward

This means that even at 1M input, the extended thinking overhead remains bounded by `max_tokens`, not by context size.

---

## 11. Cost Architecture

### 11.1 Batch Processing Economics (Anthropic)

All production translation in MTLS uses the Anthropic Message Batches API, which provides **50% cost reduction** vs standard API pricing.

| Model | Standard Input | Batch Input | Standard Output | Batch Output |
|-------|---------------|-------------|----------------|-------------|
| Claude Opus 4.6 | $5.00 / MTok | **$2.50 / MTok** | $25.00 / MTok | **$12.50 / MTok** |
| Claude Opus 4.5 | $5.00 / MTok | $2.50 / MTok | $25.00 / MTok | $12.50 / MTok |
| Claude Haiku 4.5 | $1.00 / MTok | $0.50 / MTok | $5.00 / MTok | $2.50 / MTok |

**Batch constraints:**
- Maximum 100,000 requests or 256 MB per batch
- Results available for 29 days after creation
- Most batches complete within 1 hour
- 24-hour hard expiry

### 11.2 Prompt Caching savings

In addition to batch pricing, MTLS uses 1-hour prompt caching (supported in Batch API). The 16e6 run demonstrated:

| Token Type | 16e6 Volume Total | Cost Rate | Total Cost |
|-----------|------------------|-----------|-----------|
| Input tokens (uncached) | 251,223 | $2.50/MTok | $0.63 |
| Cache creation (1h) | 89,976 | $5.00/MTok | $0.45 |
| Cache read hits | 989,736 | $0.25/MTok | $0.25 |
| Output tokens | 290,724 | $12.50/MTok | $3.63 |
| **Total** | — | — | **$4.96** |

Without caching, the cache_read_tokens at standard input price would have added ~$2.47 to the bill. Prompt caching saved approximately 50% on repeated context delivery.

### 11.3 Gemini Production Economics

| Phase | Model | Context Volume | Approximate Cost |
|-------|-------|---------------|-----------------|
| 1.5–1.52 | gemini-3-flash-preview | Per volume, ~30K tokens | ~$0.02–0.05 |
| 1.55 | gemini-3-flash-preview | Full corpus, ~200K tokens | ~$0.10–0.25 |
| 1.6 | gemini-3-flash-preview (vision) | 1–8 illustrations | ~$0.05–0.20 |
| 1.7 | gemini-3.1-pro-preview | 12 chapter packages | ~$0.30–0.60 |
| Embedding | Gemini embedding | Full corpus | ~$0.01–0.05 |
| **Gemini total per volume** | | | **~$0.50–1.10** |

**Total MTLS run cost per volume (estimate):** $5.50–7.00 for a 12-chapter light novel at current pricing.

---

## 12. Configuration Reference

### 12.1 Relevant `config.yaml` Keys

```yaml
translation:
  provider: anthropic           # or gemini / openrouter
  phase_models:
    '1':     gemini-3-flash-preview
    '1_5':   gemini-3-flash-preview
    '1_55':  gemini-3-flash-preview
    '1_56':  claude-sonnet-4      # Translation Brief Agent
    '1_6':   gemini-3-flash-preview
    '1_7':   gemini-3.1-pro-preview
    '2':     claude-opus-4-6
    '2_5':   gemini-3-flash-preview
  batch_mode: true
  effort: max
  thinking_mode: adaptive
  prompt_cache: true
  cache_duration: 1h
```

### 12.2 Batch API Prompt Cache Configuration

To maximize cache hit rates for parallel chapter batches:

```python
# Every request in the batch must include the same cache_control block
params = {
    "model": "claude-opus-4-6",
    "system": [
        {
            "type": "text",
            "text": "<canonical system prompt>",
            "cache_control": {"type": "ephemeral"}  # 1-hour cache
        }
    ],
    "messages": [
        {"role": "user", "content": "<chapter-specific prompt>"}
    ]
}
```

The canonical system prompt (canon registry, CFv2 hierarchy, voice fingerprints, EPS data, ADN, scene plans) is identical across all chapter requests in the volume → high cache hit rate.

### 12.3 1M Context Activation Code Change

When Usage Tier 4 is reached:

```python
# Add to batch request creation
response = client.beta.messages.create(
    model="claude-opus-4-6",
    max_tokens=128000,
    thinking={"type": "adaptive"},
    betas=["context-1m-2025-08-07"],  # ← add this
    messages=[...],
)
```

**Estimated impact on 16e6 run:** Full prequel bundle inclusion would have changed route from `series_bible_rag` to `full_prequel_cache_gate`, adding ~120K additional context tokens at 2x input pricing (~$0.30 per chapter), total additional cost ~$3.60 for the volume — a reasonable premium for series-level continuity accuracy.

---

## Appendix: Official Model Comparison Full Table

| Property | Gemini 3.1 Pro | Gemini 3 Flash | Claude Opus 4.6 | Claude Haiku 4.5 |
|----------|---------------|----------------|----------------|-----------------|
| Context window | 1M / 64k out | 1M / 64k out | 200K (1M beta) | 200K |
| Max output | 64K | 64K | 128K | — |
| Thinking | `thinking_level` param | `thinking_level` param | Adaptive (`effort=max`) | Limited |
| Multimodal | Yes (images, video) | Yes (images, video) | Text + images | Text |
| Batch API | No equivalent | No equivalent | Yes (50% discount) | Yes |
| Prompt cache | Context-based | Context-based | 1-hour cache | 5-min cache |
| MTLS phase | 1.7, scene planning | 1.5–1.6, metadata, vision | 2, translation | Auditors, pre-analysis |
| Role in MTLS | Structured intelligence | Fast volume processing | Literary craft | QC validation |

---

*This document is the canonical AI tandem architecture reference for MTLS v1.*  
*Cross-reference:* [← Root README](../../README.md) · [MTLS_V1_SYSTEM_ARCHITECTURE.md](./MTLS_V1_SYSTEM_ARCHITECTURE.md) · [MTLS_V1_PIPELINE_PREPARATION_PHASES.md](./MTLS_V1_PIPELINE_PREPARATION_PHASES.md) · [MTLS_V1_OPUS_TOKEN_ALLOCATION.md](./MTLS_V1_OPUS_TOKEN_ALLOCATION.md)

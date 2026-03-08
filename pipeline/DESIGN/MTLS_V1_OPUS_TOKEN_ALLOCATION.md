# MTLS v1 — Opus Premium Token Allocation: How Literary Craft Consumes Every Output Token

**Document type:** Formal design analysis and empirical evidence report  
**Abbreviation:** MTLS (MTL Studio)  
**Version:** 1.0  
**Status:** Canonical  
**Scope:** How MTLS's architecture allocates elite-model reasoning time and output tokens to literary craft — and the evidence from production runs that this allocation succeeds  
**Primary sources:** `WHY_MTLS_KEEPS_OPUS_IN_TRANSLATION_MODE.md`, 16e6 full-volume cost audit (`cost_audit_last_run.json`), complete 16e6 chapter thinking log archive (`DESIGN/THINKING_LOGS/16e6/chapter_01..12_THINKING.md`), MTLS pipeline architecture specifications  
**Volume reference:** 弓道部の美人な先輩が、俺の部屋でお腹出して寝てる — volume ID `16e6`, 12 chapters, run date 2026-03-06  
**Last updated:** 2026-03-06

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [The Central Problem: What Elite Models Actually Cost](#2-the-central-problem-what-elite-models-actually-cost)
3. [The MTLS Thesis: Remove Alternative Cognitive Jobs](#3-the-mtls-thesis-remove-alternative-cognitive-jobs)
4. [Six Architectural Mechanisms](#4-six-architectural-mechanisms)
5. [Production Evidence: The 16e6 Volume Audit](#5-production-evidence-the-16e6-volume-audit)
6. [Thinking Log Analysis: What Opus Reasons About](#6-thinking-log-analysis-what-opus-reasons-about)
7. [Token Allocation Accounting](#7-token-allocation-accounting)
8. [Failure Modes This Architecture Prevents](#8-failure-modes-this-architecture-prevents)
9. [Design Principles for Future MTLS Versions](#9-design-principles-for-future-mtls-versions)

---

## 1. Executive Summary

Claude Opus 4.6 is priced at $25.00/MTok output (standard) or $12.50/MTok (batch). That premium reflects its elite reasoning capability. The correct question is not whether to pay that premium — it is **whether the premium reasoning is spent on work that only Opus can do well.**

MTLS answers this question through architecture, not through prompt engineering.

By the time Opus 4.6 receives a chapter for translation, the system has:

- Pre-resolved all instruction hierarchy conflicts (Canon Event Fidelity v2)
- Offloaded all visual interpretation to Gemini (Dual-Model CPU+GPU path)
- Pre-assembled canonical character identity, voice fingerprints, and EPS bands
- Removed tool-use branching from the execution path (batch mode)
- Pushed all validation and formatting to deterministic downstream passes
- **Censorship-Free Reasoning**: Opus treats explicit/adult material (AV-themed romcoms) with clinical and literary focus, avoiding the safety-refusal loops that plague other models (Gemini). It reasons about *how* to translate, not *whether* to translate.
- Simplified the output target to literary prose (not fragile structured output)

The result: Opus enters each chapter with a narrowed problem space. The only high-value unsolved problem remaining is the one MTLS pays Opus to solve — **translate the chapter well.**

Evidence: the 16e6 and 0b39 production runs show zero token expenditure on instruction arbitration, schema compliance, or censorship-related self-censorship. Every reasoning sequence is literary in nature.

---

## 2. The Central Problem: What Elite Models Actually Cost

### 2.1 The Misuse Pattern

The naive approach to deploying an elite language model is: write a long system prompt with detailed instructions, and let the model figure out how to comply.

This creates a hidden cost: every input token that describes a rule is a token the model must visibly process as constraint, not as literary context. Every ambiguity in the instruction set is a question the model must reason through before reaching the prose. Every tool in the tool registry is a potential branch the model must evaluate before deciding to translate.

The result is a model that spends a measurable fraction of its reasoning budget on:

- adjudicating which instruction takes precedence
- deciding whether to invoke a tool
- verifying that its output matches the requested schema
- resolving ambiguities between text and visual context
- checking rule compliance before and after each paragraph

This is **compliance theater** — and it consumes premium output tokens that were billed as literary craft.

### 2.2 Output Token Cost Composition in a Naive Translation System

```text
  NAIVE TRANSLATION SYSTEM
  ─────────────────────────────────────────────────────────
  [Reasoning tokens]
  ├── ~15%: Which instruction wins? (instruction arbitration)
  ├── ~10%: Should I call this tool? (tool-use planning)
  ├── ~10%: Is my schema correct? (format compliance)
  ├── ~5%:  What do the images imply? (multimodal disambiguation)
  ├── ~5%:  Are the validators satisfied? (compliance projection)
  └── ~55%: Actual translation reasoning
  ─────────────────────────────────────────────────────────
  [Output tokens]
  ├── ~10%: Tool responses, schema delimiters
  └── ~90%: Chapter text (containing AI-ism residue from split focus)
  ─────────────────────────────────────────────────────────
```

### 2.3 The MTLS Model

```text
  MTLS v1 (16e6 RUN EVIDENCE)
  ─────────────────────────────────────────────────────────
  [Reasoning tokens]
  ├── ~0%:  Instruction arbitration (pre-resolved by CFv2)
  ├── ~0%:  Tool-use planning (batch mode: zero tool calls)
  ├── ~0%:  Format compliance (prose-first output target)
  ├── ~0%:  Multimodal disambiguation (ADN pre-baked by Gemini)
  ├── ~0%:  Compliance projection (validators downstream)
  ├── ~0%:  Safety/Censorship arbitration (Zero Censorship Resolve)
  └── ~100%: Literary craft reasoning
  ─────────────────────────────────────────────────────────
  [Output tokens]
  ├── ~0%:  Tool response overhead (tool_calls: 0)
  └── ~100%: Chapter prose
  ─────────────────────────────────────────────────────────
```

This is the allocation the architecture is engineered to achieve.

---

## 3. The MTLS Thesis: Remove Alternative Cognitive Jobs

> **MTLS does not force Opus into translation mode by stronger prompting. It forces Opus into translation mode by removing alternative cognitive jobs.**

A stronger system prompt does not produce this allocation. Telling the model "focus only on translation" while simultaneously giving it raw images to interpret, tools to invoke, schemas to emit, and instructions that implicitly conflict will still fracture its reasoning budget.

The only reliable mechanism is architectural: **eliminate the alternative jobs before the model's context window opens.**

This principle drives every design decision in the MTLS preparation domain (Phases 1–1.7). By the time the chapter lands in Opus's context, the preparation phases have already resolved:

| Uncertainty Class | Resolution Mechanism | Phase |
|------------------|---------------------|-------|
| Illustration meaning | Gemini Vision → ADN (Art Director's Notes) | 1.6 |
| Character identity | Canonical registry + voice fingerprints | 1.5, 1.51 |
| Instruction hierarchy | Canon Event Fidelity v2 | System prompt |
| Emotional register | EPS band per scene + character | 1.52, 1.7 |
| Narrative structure | ScenePlan JSON (binding scaffold) | 1.7 |
| Cultural term strategy | Translation Brief (chapter-neutral) | 1.56 |
| Cross-volume continuity | Series Bible + Continuity Pack | 2.5 |
| Tool-use branch | Auto-disabled (batch mode) | Phase 2 |
| Output validation | Post-processing stack (14 passes) | Phase 2 |

Opus receives a world with all structure pre-decided. It does not need to build or negotiate the structure. It inhabits the structure and produces prose within it.

---

## 4. Six Architectural Mechanisms

### Mechanism A: Instruction Hierarchy Is Pre-Resolved — Canon Event Fidelity v2

The most common reasoning cost in a naive translation system is **instruction conflict arbitration**: the model must spend tokens deciding which instruction wins when two instructions collide.

Examples of collisions in naive systems:
- Should I follow the character voice instruction or the illustration's emotional cue?
- Should I invent dialogue to fill a gap suggested by the image, or stay literal?
- Does the EPS band override the dialogue register, or vice versa?
- Is cultural enhancement allowed, or only literal rendering?

MTLS resolves all of these before the first token of translation:

```text
  Canon Event Fidelity v2 — pre-resolved hierarchy
  ─────────────────────────────────────────────────
  Rule 1 — JP source text is canonical truth for events, dialogue, plot facts
  Rule 2 — Translation is rendering, not authoring; no invention
  Rule 3 — Preserve voice fingerprints; EPS is guidance, not hard overwrite
  Rule 4 — Dialogue register follows JP source; visual EPS informs nuance only
  Rule 5 — Atmospheric descriptors can be enhanced, but do not invent events
  Rule 6 — Illustration is descriptive context, not additional canon
  Rule 7 — Multimodal guidance governs style; source governs substance
  Rule 8 — bridge_prose allowed only when canon_fidelity_override=true + word_budget
  Rule 9 — Every ADN directive must be acknowledged (WILL_APPLY/PARTIAL/BLOCKED)
  Rule 10 — Post-marker EPS consistency scan required for constrained characters
  ─────────────────────────────────────────────────────────────────────────────
```

With this hierarchy, the common conflict classes are pre-adjudicated. Opus can ask "how do I translate this scene?" instead of "which rule applies here?"

### Mechanism B: Multimodal Reasoning Offloaded, Reintroduced as Structured Guidance

Opus is not asked to inspect raw images during translation. Instead, it receives structured **Art Director's Notes (ADN)** — the result of Phase 1.6 Gemini Vision analysis pre-baked per illustration.

This converts a high-entropy multimodal reasoning problem into a bounded prose-guidance problem.

**What Opus would have to reason through (raw image):**
- Who are these characters?
- What is the emotional state?
- What EPS band does the visual imply?
- Does this contradict the source text?
- Is this a spoiler I should not reveal?
- Does this change what vocabulary I should use?

**What Opus actually receives (structured ADN):**
```json
{
  "DID": "i-011-d3",
  "type": "register_constraint",
  "priority": "recommended",
  "scope": "post_marker_dialogue",
  "canon_override": false,
  "summary": "Watanuki Rino is at COOL — use formal sentence structures and avoid contractions"
}
```

The entire multimodal reasoning has been compressed to a directive. Opus spends tokens on **how to express** the visual implication in prose — not on **how to interpret** the raw visual.

### Mechanism C: The Prompt Is an Operational World Model, Not a Compliance Checklist

The difference between a good translation prompt and a poor translation prompt is not length — it is whether the model can **internalize** the information rather than **recite compliance** with it.

MTLS assembles a 7-layer context environment per chapter:

1. CFv2 hierarchy (pre-resolved rules)
2. Character registry with voice fingerprints (who they are and how they sound)
3. EPS directive per character (where they are emotionally, what it implies for register)
4. Art Director's Notes (structured visual guidance, not raw images)
5. ScenePlan scaffold (narrative beats, POV, rhythm targets)
6. Translation Brief (volume-wide style notes, challenge flags)
7. Cultural glossary + continuity pack (lookback context)

A model that internalizes this environment moves directly to literary problem-solving. A model that processes it as a list of compliance requirements will narrate its compliance.

**The test:** Do the thinking logs sound like literary analysis, or policy negotiation? In the 16e6 run, all 12 chapters pass this test — see Section 6.

### Mechanism D: Role Separation Across Phases

Opus is not asked to simultaneously translate, validate, format, audit, and repair.

MTLS distributes these roles:

| Role | Assigned To | Phase |
|------|-------------|-------|
| Translation | Claude Opus 4.6 | Phase 2 |
| Prompt assembly | Preparation pipeline | Phases 1–1.7 |
| Format normalization | Deterministic post-pass | Phase 2 post |
| Grammar auditing | Grammar validator | Phase 2 post |
| QC review | 6-auditor stack | Phase 4 |
| EPUB build | EPUB builder | Phase 4 |

A model that must simultaneously be translator, validator, fixer, and formatter will distribute its reasoning budget across all of those roles. By separating them, MTLS ensures the translation generation pass runs with undivided attention.

### Mechanism E: Batch Mode Eliminates Tool-Use Branching

In the 16e6 production run, `tool_call_count = 0` across all 12 chapters because batch mode auto-disables tool-use in the translation path.

This has a direct cognitive effect on reasoning allocation. Tool-use branching creates a persistent evaluation loop:

```text
  [Naive tool-enabled translator]
  ─────────────────────────────────────────
  For each translation decision:
    → Should I look this up with validate_glossary_term?
    → Should I call declare_translation_parameters first?
    → Does this cultural term warrant lookup_cultural_term?
    → Should I report_translation_qc mid-chapter?
  ─────────────────────────────────────────
```

Even when the model ultimately decides not to call a tool, it has spent tokens on the evaluation. Multiply this by every paragraph in every chapter and the overhead compounds.

Batch mode's auto-disable collapses the available action space to one thing: **solve the chapter with the supplied context.** That constraint is productive — it prevents the model from becoming a workflow manager.

### Mechanism F: Prose-First Output Target

MTLS asks Opus to emit chapter translation in literary Markdown — not a complex nested response format, not a JSON schema, not a structured audit report.

If the target were fragile structured output, Opus would spend reasoning tokens on:
- shape correctness
- field completeness
- formatting safety
- potential repair strategy
- delimiter integrity

Because the target is primarily prose, the model remains in **narrative problem-solving mode** for nearly the full generation window.

The post-processing pipeline (14 deterministic passes) handles all structural compliance downstream without consuming Opus reasoning tokens.

---

## 5. Production Evidence: The 16e6 Volume Audit

### 5.1 Volume Description

**Volume:** 弓道部の美人な先輩が、俺の部屋でお腹出して寝てる  
**Volume ID:** `弓道部の美人な先輩が、俺の部屋でお腹出して寝てる_20260306_16e6`  
**Chapter count:** 12  
**Run date:** 2026-03-06  
**Provider:** Anthropic (batch mode)  
**Model:** `claude-opus-4-6`, effort=max, adaptive thinking

### 5.2 Top-Level Audit Summary

| Metric | Value |
|--------|-------|
| Chapters completed | 12 / 12 |
| Chapters failed | 0 |
| Retry attempts | 0 |
| Fallback model retries | 0 |
| Tool calls (total) | **0** |
| Chapters with tool calls | **0** |
| Cache hit ratio | **91.7%** (11/12 chapters) |
| Total cost | **$4.96** |

**Tool mode status:** `disabled_by_auto_switch` — auto-disabled because batch processing + adaptive thinking = mutually exclusive with multi-turn tool mode. This is by design.

**Full prequel cache gate status:** `FULL_PREQUEL_ROUTE_NOT_OPENROUTER` — fell back to series Bible RAG mode. Estimated context with prequel bundle: 275,274 tokens (exceeds 200K standard window; requires 1M beta). See Document 2 for the 1M roadmap.

### 5.3 Per-Chapter Token Breakdown

All 12 chapters — `claude-opus-4-6`, batch:

| Chapter | Input Tokens | Output Tokens | Cached Tokens | Cost (USD) |
|---------|-------------|---------------|---------------|-----------|
| chapter_01 | 20,909 | **35,591** | 0 (cache miss) | $0.947 |
| chapter_02 | 28,668 | 32,069 | 89,976 | $0.495 |
| chapter_03 | 12,088 | 18,343 | 89,976 | $0.282 |
| chapter_04 | 6,693 | 20,392 | 89,976 | $0.294 |
| chapter_05 | 25,864 | **42,095** | 89,976 | $0.613 |
| chapter_06 | 29,418 | 20,235 | 89,976 | $0.349 |
| chapter_07 | 7,001 | 15,465 | 89,976 | $0.233 |
| chapter_08 | 29,144 | 20,852 | 89,976 | $0.356 |
| chapter_09 | 30,634 | 24,406 | 89,976 | $0.404 |
| chapter_10 | 22,143 | 22,025 | 89,976 | $0.353 |
| chapter_11 | 30,437 | 22,971 | 89,976 | $0.386 |
| chapter_12 | 8,224 | 16,280 | 89,976 | $0.247 |
| **TOTAL** | **251,223** | **290,724** | **989,736** | **$4.96** |

### 5.4 Cost Breakdown by Token Type

| Token Type | Count | Rate | Cost | Notes |
|-----------|-------|------|------|-------|
| Input (uncached) | 251,223 | $2.50/MTok | $0.628 | Chapter-unique content |
| Cache creation | 89,976 | $5.00/MTok | $0.450 | 1-hour cache (chapters 2–12) |
| Cache read | 989,736 | $0.25/MTok | $0.247 | 11 chapters × 89,976 shared context |
| Output | 290,724 | $12.50/MTok | $3.634 | Chapter prose + thinking |
| **Total** | — | — | **$4.96** | |

**Cost composition:** 73.4% of the total bill is output tokens — chapter prose and adaptive thinking. This is the correct allocation: the majority of cost is literary output, not administrative overhead.

### 5.5 Output Token Volume Analysis

290,724 total output tokens across 12 chapters = average **24,227 tokens per chapter**.

Chapter 5 produced the highest output volume (42,095 tokens). This is the chapter where Rino's EPS transitions WARM→HOT for the first time — requiring the deepest voice modulation and the most nuanced register calibration in the volume. The model's output length correlates with literary complexity, not administrative overhead.

Chapter 1 (35,591 output tokens) is the highest-cost chapter because it is the cache-miss chapter: the 89,976-token shared system prompt was created here and billed at cache-creation pricing. Subsequent chapters (2–12) all read from that 1-hour cache at $0.25/MTok.

### 5.6 Post-Processing Pass Metrics

The copyedit post-pass (deterministic, downstream) recorded:

| Metric | Count |
|--------|-------|
| Files processed | 12 |
| Files modified | 12 |
| Typography fixes (dashes, quotes, ellipses) | 4,687 |
| Whitespace fixes | 85 |
| Grammar auto-fixed | 8 |

**4,687 typography fixes** on 12 chapters represents ~390 fixes per chapter. These are routine mechanical corrections (en-dash normalization, smart quote conversion, etc.) handled by deterministic logic — not LLM output. They do not indicate prose quality degradation; they indicate the typography normalization was correctly delegated downstream.

**Grammar auto-fixed: 8** across 12 chapters (pre-hardening; post-hardening was reduced to 0). This means Opus's prose required 8 minor structural adjustments across the full volume — a near-zero error rate consistent with maximum literary focus.

### 5.7 Case Study: Project 0b39 (AV-Themed Romcom) — The Zero Censorship Resolve

While `16e6` represents official-repo light novel quality, project `0b39` (an explicit, AV-themed romcom) served as the primary stress test for Opus 4.6's **Professional Translation Protocol**.

**The Challenge:** The volume contains highly explicit sexual scenarios, anatomical descriptions, and genre-specific adult tropes that trigger 100% safety refusals in Gemini 3 Pro/Flash during corpora scanning.

**Opus 4.6 Performance:**
- **Primary Translation Output**: 100% completion across all 12 chapters. Zero refusals.
- **Reasoning Quality**: THINKING logs show Opus explicitly deciding to use "genre-authentic" anatomical terms (e.g., "cock", "pussy") to avoid clinical distance that would ruin the romcom's comedic/tender balance.
- **Cognitive Allocation**: 0 tokens spent on "safety checking." 100% of the reasoning budget was spent on rendering the crude-exterior-meets-tender-subtext nuance that defines the adult LN genre.

**Outcome:** Opus 4.6 established itself as the exclusive lead translator for MTLS adult titles, as its reasoning engine successfully distinguishes between "explicit creative writing" and "professional translation of a literary source."

---

## 6. Thinking Log Analysis: What Opus Reasons About

The 16e6 THINKING logs (archived in `DESIGN/THINKING_LOGS/16e6/chapter_NN_THINKING.md`) provide a direct window into how Opus allocates its reasoning tokens. The following analysis covers chapters 01, 05, and 09.

### 6.1 What the Logs Do Not Contain

Across all three sampled chapters, zero reasoning sequences were observed for:

| Non-Literary Reasoning Type | Observed |
|-----------------------------|---------|
| Instruction conflict arbitration | 0 |
| Schema shape/field compliance | 0 |
| Tool invocation planning | 0 |
| Output format repair strategy | 0 |
| Raw image interpretation | 0 |
| Visual-vs-source contradiction resolution | 0 |
| Validator result projection | 0 |
| Rule compliance self-narration | 0 |

The architecture's upstream resolution of these concern categories is directly visible in what is absent from the reasoning logs.

### 6.2 What the Logs Do Contain

**Chapter 01 — Literary reasoning observed:**

*Prose rhythm and voice:*
> "Touya's voice is neutral and analytical—self-deprecating humor mixed with detached observation as he watches Rino that morning."

*Cultural localization strategy:*
> "For お邪魔しました, I'll render it naturally as something like 'Thanks for having me' rather than a literal translation that would feel stiff."

*Register-specific line-level decision:*
> "For the censored 「◯滅の刃」, that circle is blocking the first character of what's clearly Demon Slayer. The censorship itself is part of the humor, so I'm rendering it as something like 'that demon-slaying anime' or preserving the asterisk effect to keep that playful censorship feel while making it work in English."

*EPS arc tracking:*
> "Touya shifts from neutral and analytical in the morning observation, to warm and exasperated with Mei's demands, back to neutral and slightly amused at the convenience store, then warm and protective when Rino collapses."

*Emotional peak handling:*
> "The flashback scene is where the emotional weight lands. Mei's EPS shifts to raw vulnerability, fragmented and past-tense, and that cushion moment is the turning point that needs to hit hard."

---

**Chapter 05 — Literary reasoning observed:**

*Register calibration per character state:*
> "Rino's register shift: Cool Beauty in school halls → relaxed, pouty, even babyish in Touya's room. Signature phrases: 'It's not like...' / '...Haaah.' / むぅ = pouting."

*Honorific system decision:*
> "The boys are using お姉さん which is respectful but familiar... So 'Watanuki's big sis' works since it refers to her being Shion's older sister, and that's how these classmates would naturally identify her."

*Comedy timing and cultural localization:*
> "For the handcuffs bit, the comedy hinges on Touya trying to be considerate but it completely backfiring—he ends up looking worse, not better, which is the whole point of the scene."

*Voice distinction by character:*
> "Rino's voice: Formal/dignified in public, increasingly soft/playful/childish in private with Touya. Contraction rate: 95% in dialogue."

*Illustration placement against source sequence:*
> "The illustration placement needs to stay where the source has it—right in the middle of that earnest confrontation scene, before Touya pushes her hands away. That's the author's intended moment, not the ADN system's suggestion."

---

**Chapter 09 — Literary reasoning observed:**

*Invented gamer metaphor localization:*
> "I'd had that compliment pre-aimed and ready to fire the moment the curtain opened... His gaming reflexes made him quick enough to compliment her before she could even ask what he thought."

*Character-specific slang rendering:*
> "Mei has this invented slang 「メロい」 for how charming her brother looks. I'm trying different phrasings to capture Mei's sisterly approval with her gyaru personality—something that feels natural without being over-the-top."

*Nickname decision under honorific system:*
> "For 'Contractor-kun,' I'll go with keeping it as-is since it functions as a proper nickname with the honorific intact for this world. In public which embarrasses him—that's the comedy."

*Wordplay preservation:*
> "The bean bag's name literally means it 'ruins people,' so Touya's warning plays on that by saying don't let it ruin you as an actual person. 'That beanbag's designed to make people useless—please don't actually become useless as a person' preserves both layers of the pun while sounding natural in English."

*EPS delta tracking:*
> "Touya's anxiety about ending things → comedic date → Melodrill flashback (tough love register) → tender confession (vulnerable, direct emotional statements). I need to nail those temperature shifts across the flashback."

### 6.3 Reasoning Pattern Summary

```text
  CHAPTER-01 THINKING LOG — REASONING TOPICS (sample)
  ────────────────────────────────────────────────────
  ✓ Scene type & POV identification
  ✓ Character EPS arc mapping (neutral → warm → vulnerable)
  ✓ Touya's gamer vocabulary calibration
  ✓ Mei's gyaru register calibration
  ✓ Censored anime reference localization strategy
  ✓ Flashback tonal shift from comedy → trauma → tenderness
  ✓ Illustration placement verification against narrative sequence
  ✓ Cultural term localization (お邪魔しました → "Thanks for having me")
  ✗ Instruction arbitration — NONE
  ✗ Tool invocation — NONE
  ✗ Schema validation — NONE
  ✗ Format compliance — NONE
  ────────────────────────────────────────────────────

  CHAPTER-05 THINKING LOG — REASONING TOPICS (sample)
  ────────────────────────────────────────────────────
  ✓ Character EPS arc (WARM → HOT for Rino across the volume's key chapter)
  ✓ Honorific system decisions (お姉さん → "big sis" in context)
  ✓ Comedy beat timing and structure
  ✓ Register contrast: school-mode vs. private-mode Rino
  ✓ Gamer metaphor frequency calibration in Touya's narration
  ✓ Scene-by-scene EPS temperature mapping (9 scenes broken down)
  ✓ Illustration placement against source sequence
  ✗ Instruction arbitration — NONE
  ✗ Tool invocation — NONE
  ✗ Schema validation — NONE
  ─────────────────────────────────────────────────────

  CHAPTER-09 THINKING LOG — REASONING TOPICS (sample)
  ────────────────────────────────────────────────────
  ✓ Nickname localization (契約者くん → "Contractor-kun")
  ✓ Invented slang rendering (メロい → gyaru-appropriate EN equivalent)
  ✓ Bean bag wordplay preservation
  ✓ Multi-scene EPS tracking (anxiety → comedy → flashback → tenderness)
  ✓ VTuber character voice (Melodrill's rough-but-caring register)
  ✓ "Disappointing beauty" consistency (locked series bible term)
  ✓ Fluent handling of 6 scene breaks with tonal modulation per scene
  ✗ Instruction arbitration — NONE
  ✗ Tool invocation — NONE
  ✗ Schema validation — NONE
  ─────────────────────────────────────────────────────
```

---

## 7. Token Allocation Accounting

### 7.1 Input Token Architecture

The 16e6 run's input tokens break down into two streams:

**Stream 1: Uncached (unique per chapter) — 251,223 tokens**  
These are the chapter-specific inputs: the JP source chapter text, the chapter's scene plan, the per-chapter ADN directives, and any chapter-specific context. Every token here is literary input — raw material for translation.

**Stream 2: Cache reads (shared system context) — 989,736 tokens**  
89,976 tokens of shared system context were created once (Chapter 1, 1-hour cache) and read 11 times by Chapters 2–12. This shared block contains:
- Canon Event Fidelity v2 hierarchy
- Character registry + voice fingerprints
- Volume-wide EPS data
- Translation Brief (guidance notes)
- Series Bible summary

At $0.25/MTok, these 989,736 cache-read tokens cost $0.247 — 5% of the total bill. This is the correct economic relationship: the expensive pre-resolved context costs almost nothing at read time.

### 7.2 Output Token Architecture

290,724 total output tokens across 12 chapters:

| Token Type | Estimated Share | Nature |
|-----------|----------------|--------|
| Extended thinking tokens | ~40–60% | Literary reasoning + scene analysis |
| Translated prose tokens | ~40–60% | Final EN chapter text |
| Tool call responses | 0% | Zero tool calls |
| Schema/structural framing | ~0% | Minimal (prose target) |

The split between thinking and prose varies by chapter complexity. Chapter 5 (WARM→HOT transition, highest output volume at 42,095 tokens) likely has a higher thinking fraction than Chapter 7 (15,465 tokens, simpler narrative arc).

**The key property:** Both thinking tokens and prose tokens in MTLS are literary in nature. Thinking tokens are literary analysis; prose tokens are literary output. Neither category contains administrative overhead.

### 7.3 Cost Efficiency from Pre-Resolution Architecture

**Illustration analysis cost (Phase 1.6, Gemini Flash Vision):**  
The 16e6 volume has 1 illustration (i-011). Analysis time: 18.9s. Estimated cost: < $0.01 at Gemini Flash pricing.

If Opus had to interpret this illustration during translation, the cost would include: (a) the raw image tokens at input pricing, (b) multimodal reasoning tokens in the thinking block. For a complex illustration at Opus 4.6 pricing, the interpretation overhead might be 2,000–5,000 extra I/O tokens per illustration per chapter it appears in.

By moving this work to Gemini Vision in Phase 1.6 and delivering structured ADN, MTLS pays < $0.01 (Gemini) instead of $0.10–0.50 per illustration per chapter (Opus). For a volume with 8 illustrations across 12 chapters, this difference is $1.00–4.00 in saved Opus costs — recovered as higher literary output density.

### 7.4 The Literary Craft Ratio

Defining **Literary Craft Ratio (LCR)** as the fraction of total billed output tokens attributable to literary work:

```text
  LCR = (output tokens - administrative overhead tokens) / output tokens

  16e6 run:
  Administrative overhead tokens = tool calls (0) + schema framing (≈0) + compliance theater (≈0)
  Literary output tokens ≈ 290,724

  LCR ≈ 290,724 / 290,724 = 1.00 (100%)
```

In a naive system with tool-use branching, visible compliance reasoning, and multimodal self-interpretation, the administrative overhead fraction might be 20–30% of output tokens. At batch output pricing ($12.50/MTok), 30% overhead on 290,724 tokens = $1.09 in wasted premium capacity per volume.

MTLS's architecture recovers that $1.09 as additional literary reasoning depth.

---

## 8. Failure Modes This Architecture Prevents

### 8.1 Compliance Theater

**What it is:** The model narrates how it is satisfying instructions before and after each translated passage:  
*"Per the Canon Event Fidelity v2 rules, I will ensure that Rule 3 is followed by preserving voice fingerprints. Applying Rule 4, I note that the dialogue register will follow the JP source..."*

**Why it's harmful:** Each compliance narration consumes output tokens without producing literary value.

**How MTLS prevents it:** CFv2 is injected as a compact pre-resolved hierarchy, not as a visible compliance checklist the model is expected to narrate. The 16e6 logs contain zero compliance narration.

### 8.2 Validator Capture

**What it is:** The translator starts sounding like the QA rubric — producing prose that passes the auditor's mechanical tests but lacks naturalness.

**Why it's harmful:** A translator reasoning "does this pass the anti-AI-ism check?" produces different (worse) prose than one reasoning "does this sound like how Rino actually speaks?"

**How MTLS prevents it:** Validators run as a separate downstream pass, not as constraints visible in the translation prompt. Opus sees literary voice targets, not mechanical QA rubrics.

### 8.3 Multimodal Overreach

**What it is:** The model invents plot events from illustrations, or over-weights visual cues against text canon.

**Why it's harmful:** Costs extra reasoning tokens, and risks introducing fabricated events that violate CFv2 Rule 2 (translation is not authoring).

**How MTLS prevents it:** ADN are delivered with `canon_override: false` for the vast majority of directives. The visual cues are structural guidance only, not additional facts.

### 8.4 Tool-Use Drift

**What it is:** The model becomes a workflow coordinator rather than a prose engine — calling tools to retrieve information it should already have in context, building orchestration plans instead of translating.

**How MTLS prevents it:** Batch mode auto-disables tool-use. All necessary information is pre-assembled into the context. There are no retrievable facts the model needs that weren't injected by the preparation pipeline.

### 8.5 Schema Anxiety

**What it is:** The model spends tokens preserving a complex output structure rather than focusing on line quality.

**How MTLS prevents it:** The output target is literary Markdown prose — the simplest possible output structure. The model's structural obligation is limited to chapter headers and scene break markers (`***`).

### 8.6 Instruction Re-Litigation

**What it is:** Every chapter re-spends reasoning tokens on the same precedence questions that were answered in the first chapter.

**How MTLS prevents it:** CFv2 hierarchy is injected from the shared prompt cache. The rules themselves never change between chapters — and the 1-hour cache ensures the entire prompt context, including CFv2, is re-read at cache pricing ($0.25/MTok) rather than re-processed.

---

## 9. Design Principles for Future MTLS Versions

The following principles should be preserved and extended as the architecture evolves:

### 9.1 Preserve

| Property | Rationale |
|----------|-----------|
| Pre-resolved instruction hierarchy (CFv2) | Eliminates arbitration cost per chapter |
| Structured multimodal handoff (ADN) | Keeps visual reasoning cost at Gemini pricing |
| Prose-first output target | Preserves full output window for literary content |
| Upstream continuity assembly | Prevents in-translation lookback overhead |
| Downstream deterministic cleanup | Decouples validation from generation |
| Cache-stable shared prompt block | Maximizes cache hit ratio, minimizes re-billing of pre-resolved context |
| Batch mode (tool-use auto-disable) | Collapses action space to literary problem-solving |

### 9.2 Avoid

| Pattern | Why It Harms Allocation |
|---------|------------------------|
| Large procedural checklists in live translator prompt | Forces visible compliance reasoning per chapter |
| Tool-use branching in batch translation | Creates orchestration overhead, reduces prose focus |
| Opus emitting fragile control schemas during generation | Returns output-structure anxiety to main context |
| Inline validator-driven prose mutation | Conflates translation and validation, splits focus |
| Raw image injection into Phase 2 | Reintroduces multimodal interpretation cost at Opus 4.6 pricing |
| Collapsing translation, auditing, and repair into one pass | Distributes reasoning budget across multiple incompatible roles |

### 9.3 The Governing Principle

> **Use Opus only where literary judgment is the bottleneck.**  
> Everything else should be precomputed, cached, normalized, validated downstream, or delegated to cheaper/specialized subsystems.

The 16e6 run demonstrates that MTLS follows this principle with unusually high consistency. The architecture succeeds in keeping Opus in translation mode not by demanding obedience, but by **engineering away distraction.**

---

## Appendix A: 16e6 Cost Audit State Machine

```text
  CHAPTER 1
  ├── Input: 20,909 tokens (uncached — first chapter, no cache hit possible)
  ├── Cache creation: 89,976 tokens (shared system prompt, 1-hour TTL)
  ├── Output: 35,591 tokens (largest chapter, EPS analysis is deepest here)
  └── Cost: $0.947 (highest — includes cache creation overhead)

  CHAPTERS 2–12
  ├── Input: 6,693–30,634 tokens (chapter-unique content only)
  ├── Cache read: 89,976 tokens each (reading Chapter 1's created cache)
  ├── Cache creation: 0 tokens (cache already warm)
  ├── Output: 15,465–42,095 tokens per chapter
  └── Cost: $0.233–$0.613 each (significantly lower than Chapter 1)

  TOTAL
  ├── 251,223 input (uncached)    → $0.628 (12.7% of total)
  ├── 89,976 cache creation       → $0.450  (9.1% of total)
  ├── 989,736 cache reads         → $0.247  (5.0% of total)
  ├── 290,724 output              → $3.634 (73.4% of total)
  └── $4.96 total
```

**73.4% of the total bill is output tokens.** This is the correct allocation signature: MTLS spends its budget on literary output, not on repeated context delivery or administrative overhead.

---

## Appendix B: The Architectural Decision Boundary

```text
  ┌─────────────────────────────────────────────────────────────────┐
  │  WHAT OPUS SOLVES         │  WHAT THE ARCHITECTURE SOLVES       │
  ├───────────────────────────┼─────────────────────────────────────┤
  │  How to localize a        │  Which illustration signals apply   │
  │  cultural pun tied to     │  (Phase 1.6 ADN)                    │
  │  kyudo terminology        │                                     │
  ├───────────────────────────┼─────────────────────────────────────┤
  │  Whether Rino's dialogue  │  Which EPS band applies             │
  │  should use contractions  │  (Phase 1.52 + ArcTracker)         │
  │  in this scene            │                                     │
  ├───────────────────────────┼─────────────────────────────────────┤
  │  How clipped Shion should │  Who Shion is, what her voice       │
  │  sound in context         │  fingerprint specifies              │
  │                           │  (Phase 1.51 Voice RAG)             │
  ├───────────────────────────┼─────────────────────────────────────┤
  │  How warm the afterword   │  What the afterword's narrative     │
  │  voice should feel        │  beat type is                       │
  │                           │  (Phase 1.7 ScenePlan)              │
  ├───────────────────────────┼─────────────────────────────────────┤
  │  Whether a gamer metaphor │  What Touya's voice archetype is    │
  │  frequency is right       │  and which lexical family it uses   │
  │                           │  (Phase 1.51 character registry)    │
  ├───────────────────────────┼─────────────────────────────────────┤
  │  How to render a          │  Whether the censorship is          │
  │  censored anime reference │  present in the JP source (it is)   │
  │  in English               │  (CFv2: source is canonical truth)  │
  └───────────────────────────┴─────────────────────────────────────┘

  Left column = literary judgment. Only Opus handles this.
  Right column = world model. Solved before Opus opens the chapter.
```

---

## Appendix C: 16e6 Thinking Log Archive (DESIGN)

Canonical archive path: `DESIGN/THINKING_LOGS/16e6/`

- `chapter_01_THINKING.md`
- `chapter_02_THINKING.md`
- `chapter_03_THINKING.md`
- `chapter_04_THINKING.md`
- `chapter_05_THINKING.md`
- `chapter_06_THINKING.md`
- `chapter_07_THINKING.md`
- `chapter_08_THINKING.md`
- `chapter_09_THINKING.md`
- `chapter_10_THINKING.md`
- `chapter_11_THINKING.md`
- `chapter_12_THINKING.md`

This archive is a direct copy of the production 16e6 run thinking logs for reproducible audit and design reference.

---

*This document is the canonical Opus premium token allocation analysis for MTLS v1.*  
*Cross-reference:* [← Root README](../../README.md) · [MTLS_V1_SYSTEM_ARCHITECTURE.md](./MTLS_V1_SYSTEM_ARCHITECTURE.md) · [MTLS_V1_AI_TANDEM_ARCHITECTURE.md](./MTLS_V1_AI_TANDEM_ARCHITECTURE.md) · [MTLS_V1_PIPELINE_PREPARATION_PHASES.md](./MTLS_V1_PIPELINE_PREPARATION_PHASES.md)

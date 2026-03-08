# MTL Studio — LLM-Engineered Japanese Light Novel Translation Pipeline

**Professional-grade machine translation pipeline for Japanese light novels, powered by Claude Opus 4.6 and a multi-phase preparation system.**

---

## Overview

MTL Studio (MTLS) is an LLM-engineered translation pipeline designed specifically for Japanese light novel (LN) and web novel (WN) localization. The system orchestrates two complementary AI model families—Anthropic Claude Opus 4.6 for literary translation and Google Gemini 3 for preparation-phase processing—across a structured multi-phase workflow that produces Yen Press-grade English (or Vietnamese: Beta — In Development) output.

The architecture is built on a single governing principle: **resolve all non-literary uncertainty before translation begins, so that the translator model spends its full reasoning budget on literary craft.** Every preparation phase exists to pre-resolve ambiguity that would otherwise consume premium model tokens on instruction arbitration, schema compliance, or context disambiguation. By the time Claude Opus 4.6 receives a chapter, the problem space has been narrowed to the one thing that justifies its cost—translating prose well.

The pipeline produces EPUB output from Japanese source files through a deterministic sequence of ingestion, enrichment, scene planning, translation, and post-processing phases. Cross-volume continuity is maintained through a Series Bible system that synthesizes character voice profiles, arc resolutions, and translation decisions from each completed volume.

---

## Pipeline Flow

```
┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐
│ Phase 1 │──>│Phase 1.5│──>│Phase 1.5│──>│Phase 1.5│──>│Phase 1.5│──>│Phase 1.5│──>│Phase 1.6│──>│Phase 1.7│──>│ Phase 2 │──>│Phase 2.5│──>│ Phase 4 │
│Librarian│   │Metadata │   │  Voice  │   │   EPS   │   │  Rich   │   │ Brief   │   │Multimodal│   │  Scene  │   │Translator│  │ Bible   │   │ EPUB    │
│         │   │Translat.│   │   RAG   │   │  Band   │   │Metadata │   │ Builder │   │Processor│   │ Planner │   │         │   │Update   │   │ Builder │
└─────────┘   └─────────┘   └─────────┘   └─────────┘   └─────────┘   └─────────┘   └─────────┘   └─────────┘   └─────────┘   └─────────┘   └─────────┘
  EPUB/HTML     Title/       Voice       Emotional    Full-corpus    Guidance     Art Director  Narrative    Koji Fox    Series Bible   Final
  -> Markdown   Author/      Finger-     Proximity    Enrichment    Brief for     Notes per    beats +     Engine      Synthesis    EPUB
                Chapter     prints      Signals      + Cache       Batch         illustration  rhythm       (Opus 4.6)   (writeback)   output
                Names/                                                         + EPS                        Batch mode
                Characters
```

---

## Phase Documentation

| Phase | Name | Description | README |
|-------|------|-------------|--------|
| 1 | Librarian | EPUB extraction: unpacks JP EPUB, converts XHTML to Markdown, generates manifest | [pipeline/docs/README/preparation/PHASE_1_README.md](pipeline/docs/README/preparation/PHASE_1_README.md) |
| 1.5 | Metadata Translation | Translates title, author, chapter titles, character names to target language | [pipeline/docs/README/preparation/PHASE_1_5_README.md](pipeline/docs/README/preparation/PHASE_1_5_README.md) |
| 1.51 | Voice RAG Expansion | Backfills character voice fingerprints into ChromaDB vector store | (included in Phase 1.5) |
| 1.52 | EPS Band Backfill | Backfills Emotional Proximity Signal bands per chapter | (included in Phase 1.5) |
| 1.55 | Rich Metadata Cache | Full-LN cache enrichment via Gemini metadata analysis | [pipeline/docs/README/preparation/PHASE_1_55_README.md](pipeline/docs/README/preparation/PHASE_1_55_README.md) |
| 1.56 | Translator's Guidance Brief | Full-corpus batch pre-analysis generates guidance brief for Phase 2 | (included in Phase 1.55) |
| 1.6 | Multimodal Processor | Gemini Vision analyzes illustrations, generates Art Director's Notes | [pipeline/docs/README/preparation/PHASE_1_6_README.md](pipeline/docs/README/preparation/PHASE_1_6_README.md) |
| 1.7 | Stage 1 Scene Planner | Narrative beats, rhythm scaffold, POV tracking, per-chapter character profiles | [pipeline/docs/README/preparation/PHASE_1_7_README.md](pipeline/docs/README/preparation/PHASE_1_7_README.md) |
| 1.7-cp | Co-Processor Pack | Refreshes co-processor artifacts (maintenance task) | (included in Phase 1.7) |
| 2 | Translator (Koji Fox Engine) | Claude Opus 4.6 literary translation with batch API support | [pipeline/docs/README/translator/PHASE_2_README.md](pipeline/docs/README/translator/PHASE_2_README.md) |
| 2.5 | Volume Bible Update | Synthesizes translated text, writes back to Series Bible for continuity | [pipeline/docs/README/series_bible/PHASE_2_5_README.md](pipeline/docs/README/series_bible/PHASE_2_5_README.md) |
| 4 | EPUB Builder | Converts translated Markdown chapters back to EPUB | (CLI: `./mtl phase4 <vol>`) |

---

## Architecture & Design

The following formal design documents define the system's architecture, layer model, and model interaction patterns:

| Document | Description |
|----------|-------------|
| [pipeline/DESIGN/MTLS_V1_SYSTEM_ARCHITECTURE.md](pipeline/DESIGN/MTLS_V1_SYSTEM_ARCHITECTURE.md) | Full system topology: layer model, module inventory, data contracts, inter-phase interactions |
| [pipeline/DESIGN/MTLS_V1_PIPELINE_PREPARATION_PHASES.md](pipeline/DESIGN/MTLS_V1_PIPELINE_PREPARATION_PHASES.md) | Detailed phase specifications: inputs, outputs, LLM routing, failure modes |
| [pipeline/DESIGN/MTLS_V1_AI_TANDEM_ARCHITECTURE.md](pipeline/DESIGN/MTLS_V1_AI_TANDEM_ARCHITECTURE.md) | Dual-model design: Gemini 3 (preparation) + Opus 4.6 (translation), embedding architecture |
| [pipeline/DESIGN/MTLS_V1_OPUS_TOKEN_ALLOCATION.md](pipeline/DESIGN/MTLS_V1_OPUS_TOKEN_ALLOCATION.md) | Token economics: how preparation phases optimize Opus reasoning budget allocation |

---

## Quick Start

### Prerequisites

- Python 3.11+
- API keys: Anthropic (for Opus translation), Google Gemini (for preparation phases)
- Configuration via `pipeline/config.yaml`

### Basic Commands

```bash
# Full pipeline: EPUB to published EPUB (auto-generates volume ID)
./mtl run INPUT/my_novel_vol1.epub

# Run individual phases
./mtl phase1 <epub_path>                    # Librarian (EPUB extraction)
./mtl phase1.5 <volume_id>                   # Metadata Translation
./mtl phase1.55 <volume_id>                  # Rich Metadata Cache
./mtl phase1.56 <volume_id>                  # Translator's Guidance Brief
./mtl phase1.6 <volume_id>                   # Multimodal Processor (Art Director's Notes)
./mtl phase1.7 <volume_id>                   # Stage 1 Scene Planner

# Translation
./mtl phase2 <volume_id>                     # Streaming translation
./mtl batch <volume_id>                     # Anthropic Batch API (50% cost, ~1h)
./mtl phase4 <volume_id>                     # EPUB Builder

# Series Bible operations
./mtl bible-pull <series_id>                # Pull series bible
./mtl bible-push <volume_id>                # Push volume to bible
./mtl pronoun-shift <volume_id>             # Deterministic JP pronoun-shift detector
```

### Environment Setup

```bash
# Activate virtual environment
source .venv/bin/activate

# Install dependencies
pip install -r pipeline/requirements.txt

# Run tests
pytest
```

---

## Repository Structure

```
MTL_STUDIO/
├── pipeline/                    # Core pipeline code
│   ├── DESIGN/                 # Formal architecture documents
│   │   ├── MTLS_V1_SYSTEM_ARCHITECTURE.md
│   │   ├── MTLS_V1_PIPELINE_PREPARATION_PHASES.md
│   │   ├── MTLS_V1_AI_TANDEM_ARCHITECTURE.md
│   │   └── MTLS_V1_OPUS_TOKEN_ALLOCATION.md
│   ├── docs/README/            # Phase-level documentation
│   │   ├── preparation/        # Phase 1–1.7 READMEs
│   │   ├── translator/         # Phase 2 READMEs
│   │   └── series_bible/      # Phase 2.5 READMEs
│   ├── modules/                # Pipeline modules
│   ├── scripts/                # Controller scripts
│   ├── auditors/               # QC and validation agents
│   └── config.yaml             # Pipeline configuration
├── docs/MTL_STUDIO_ENGINEERING/  # Engineering references
│   ├── MTL_STUDIO_DIAGRAM.md
│   ├── BATCH_PROCESSING_CLAUDE.md
│   ├── KOJI_FOX_EPS_PLAN.md
│   ├── 1M_CONTEXT_WINDOWS.md
│   └── ...
├── INPUT/                      # Source EPUB files
├── OUTPUT/                     # Translated output
├── WORK/                       # Volume working directories
├── mtl, mtl.py, mtl.bat       # CLI entry points
└── config.yaml                 # Root configuration
```

---

## Engineering References

All technical documentation is organized by domain:

- **Architecture & Design** — See [Architecture & Design](#architecture--design) section above for foundational system documents
- **Phase READMEs** — See [Phase Documentation](#phase-documentation) section above for operational details per phase
- **Style Guides** — See `pipeline/style_guides/` for translation and localization guidelines
- **Config Schema** — See `pipeline/config/` for configuration reference

---

## Design Philosophy

MTL Studio's architecture reflects a deliberate cognitive labor division:

1. **Separation of Operations** — High-recall structured interpretation (metadata translation, illustration analysis, scene planning) happens in Gemini 3. Sustained literary judgment happens in Opus 4.6. These operations never happen simultaneously in the same model.

2. **Pre-Resolution** — Every preparation phase exists to remove non-literary uncertainty from the translation context. The translator receives a narrowed problem space where the only high-value unsolved problem is the prose itself.

3. **Canon Authority Hierarchy** — The Series Bible is advisory during translation, authoritative only for carry-forward. The local volume manifest always wins during translation.

4. **Batch Economics** — Production translation uses Anthropic's Message Batches API at 50% cost with ~1 hour turnaround. Streaming mode is reserved for debugging and development.

---

## License

See `LICENSE` file for details.

---

*Last verified: 2026-03-08*

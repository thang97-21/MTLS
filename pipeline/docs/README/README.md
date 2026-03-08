# MTL Studio Pipeline — Documentation Index

> [← Root README](../../../../README.md) · [← Pipeline](../../../README.md)

> **Root navigation for all phase READMEs, domain indexes, and architecture references**

---

## Quick Start

```
phase1 → phase1.5 → phase1.55 → phase1.56 → phase1.6 → phase1.7 → phase2 → [auditors] → phase2.5 → phase4
```

For a new volume from EPUB to published EPUB:
```bash
./mtl run INPUT/my_novel_vol1.epub       # Full pipeline (auto-generates volume ID)
./mtl batch <volume_id>                  # Anthropic batch path (50% cost, ~1h)
./mtl pronoun-shift <volume_id>          # Standalone deterministic JP pronoun-shift detector (Section 5.5)
```

---

## Domain Map

```text
pipeline/docs/README/
  README.md                             ← You are here (global index)

  preparation/
    README.md                           ← Preparation domain index
    PHASE_1_README.md                   ← Librarian (EPUB extraction)
    PHASE_1_5_README.md                 ← Metadata Translation · Phase 1.51 · Phase 1.52
    PHASE_1_55_README.md                ← Rich Metadata Cache · Phase 1.56 (Translation Brief)
    PHASE_1_6_README.md                 ← Multimodal Processor (Art Director's Notes)
    PHASE_1_7_README.md                 ← Stage 1 Scene Planner · Co-Processor Pack (1.7-cp)

  translator/
    README.md                           ← Translator domain index
    PHASE_2_README.md                   ← Translator Agent · Batch Mode · Tool Mode

  series_bible/
    README.md                           ← Series Bible domain index
    PHASE_2_5_README.md                 ← Volume Bible Update Agent
    CONTINUITY_ARCHITECTURE_README.md  ← Cross-volume continuity system deep-dive
```

---

## All Phases at a Glance

| Phase | Name | Section | CLI |
|-------|------|---------|-----|
| 1 | Librarian | §1 | `./mtl phase1 <epub_path>` |
| 1.5 | Schema Autoupdate + Metadata Translation | §3 | `./mtl phase1.5 <vol>` |
| 1.51 | Koji Fox Voice RAG Expansion | §3 sub | `./mtl phase1.51 <vol>` |
| 1.52 | EPS Band Backfill | §3 sub | `./mtl phase1.52 <vol>` |
| 1.55 | Full-LN Cache Rich Metadata Enrichment | §6 | `./mtl phase1.55 <vol>` |
| 1.56 | Translator's Guidance Brief | §7 | `./mtl phase1.56 <vol>` |
| 1.6 | Multimodal Processor (Art Director's Notes) | §8 | `./mtl phase1.6 <vol>` |
| 1.7 | Stage 1 Scene Planner | §9 | `./mtl phase1.7 <vol>` |
| 1.7-cp | Co-Processor Pack (context-offload refresh) | §9 sub | `./mtl phase1.7-cp <vol>` |
| 2 | Translator (Koji Fox Engine) | §10 | `./mtl phase2 <vol>` |
| 2 batch | Anthropic Batch API Translation | §10 | `./mtl batch <vol>` |
| 2.5 | Volume Bible Update Agent | §11 | _(auto at end of Phase 2)_ |
| 4 | EPUB Builder | — | `./mtl phase4 <vol>` |

---

## Domain READMEs

- [Preparation →](./preparation/README.md)
- [Translator →](./translator/README.md)
- [Series Bible →](./series_bible/README.md)

---

## Key Engineering References

These documents in `docs/MTL_STUDIO_ENGINEERING/` explain the design decisions behind the pipeline:

| Document | Topic |
|----------|-------|
| `MTL_STUDIO_DIAGRAM.md` | Architecture complexity analysis, target layer model |
| `MTL_STUDIO_EXEC_VIEW_ONE_PAGE.md` | Executive one-page value flow diagram |
| `WHY_MTLS_KEEPS_OPUS_IN_TRANSLATION_MODE.md` | Why MTLS pre-resolves non-literary ambiguity so Opus spends its reasoning budget on translation |
| `koji_fox_mtl_expansion_plan.md` | Full Koji Fox localization method spec and implementation plan |
| `KOJI_FOX_EPS_PLAN.md` | EPS signal system design, 6-signal weighting, band definitions |
| `BATCH_PROCESSING_CLAUDE.md` | Anthropic Message Batches API spec and pricing |
| `1M_CONTEXT_WINDOWS.md` | Claude context window management, 1M token beta |
| `GEMINI_3_SPECS.md` | Gemini 3 model capabilities |
| `GENERATIVE_AI_EMBEDDING.md` | ChromaDB / embedding strategy for Voice RAG |

---

## Governance Notes

1. Per the modularization plan, every LLM-driven phase has exactly one README in this tree.
2. Domain indexes summarize only; phase files hold operational detail.
3. Any change to LLM routing, phase outputs, or new CLI flags must update the corresponding phase README.
4. Series Bible cross-volume behavior is documented in `series_bible/` only.

---

*Last verified: 2026-03-05*

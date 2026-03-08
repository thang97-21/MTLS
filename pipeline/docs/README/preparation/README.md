# Preparation Domain — Index

> [← Root README](../../../../../README.md) · [← Pipeline Index](../../../README.md) · [← Docs Index](../README.md)

The **Preparation** family encompasses every phase that runs *before* the translator (Phase 2). Its collective purpose is to take a raw Japanese EPUB and produce a rich, structured context package — manifest, metadata, scene plans, visual cache, and guidance briefs — that the translation engine can consume with maximum fidelity.

---

## Phase Table

| Phase    | Name                                    | One-line description                                          | CLI command                   |
|----------|-----------------------------------------|---------------------------------------------------------------|-------------------------------|
| 1        | Librarian                               | Extract Japanese EPUB → Markdown + manifest                   | `./mtl phase1 <epub_path>`    |
| 1.5      | Schema Autoupdate + Metadata Translation| Translate title, author, chapter titles, character names      | `./mtl phase1.5 <volume_id>`  |
| 1.51     | Koji Fox Voice RAG Expansion            | Backfill `character_voice_fingerprints` + `scene_intent_map`  | `./mtl phase1.51 <volume_id>` |
| 1.52     | EPS Band Backfill                       | Backfill chapter `emotional_proximity_signals` only           | `./mtl phase1.52 <volume_id>` |
| 1.55     | Rich Metadata Cache Enrichment          | Full-LN JP cache + Gemini Flash rich-metadata enrichment      | `./mtl phase1.55 <volume_id>` |
| 5.5 (standalone) | JP Pronoun-Shift Detector        | Deterministic chapter-level pronoun-shift event extraction     | `./mtl pronoun-shift <volume_id>` |
| 1.56     | Translator's Guidance Brief             | Full-corpus Anthropic batch pre-analysis → `guidance_brief`   | `./mtl phase1.56 <volume_id>` |
| 1.6      | Multimodal Processor                    | Gemini Vision → Art Director's Notes (`visual_cache.json`)    | `./mtl phase1.6 <volume_id>`  |
| 1.7      | Stage 1 Scene Planner                   | Narrative beat + character rhythm scaffold per chapter        | `./mtl phase1.7 <volume_id>`  |
| 1.7-cp   | Co-Processor Pack                       | Standalone context-offload pack refresh (cache-only)          | `./mtl phase1.7-cp <volume_id>` |

---

## Typical Run Order

```
phase1  →  phase1.5  →  phase1.55  →  phase1.56  →  phase1.6  →  phase1.7  →  phase2
```

For volumes with no illustrations, skip Phase 1.6:

```
phase1  →  phase1.5  →  phase1.55  →  phase1.56  →  phase1.7  →  phase2
```

The **full Anthropic Batch pipeline** (`./mtl batch <volume_id>`) automates the entire sequence:
`phase1.5 → phase1.55 → phase1.56 → phase1.6 → phase1.7 → phase2 (batch)`.

**Note:** `./mtl pronoun-shift <volume_id>` is a standalone Section 5.5 utility for targeted runs. It is optional/on-demand and not part of the default preparation sequence above.

Sub-phases 1.51 and 1.52 are **on-demand backfill** commands, not part of the standard run order. Run them after Phase 1.5 when specific metadata fields are missing.

---

## Per-Phase READMEs

- [PHASE_1_README.md](./PHASE_1_README.md) — Librarian
- [PHASE_1_5_README.md](./PHASE_1_5_README.md) — Schema Autoupdate · Metadata Translation · Phase 1.51 · Phase 1.52
- [PHASE_1_55_README.md](./PHASE_1_55_README.md) — Rich Metadata Cache (1.55) · Translator's Guidance Brief (1.56)
- [PHASE_1_6_README.md](./PHASE_1_6_README.md) — Multimodal Processor
- [PHASE_1_7_README.md](./PHASE_1_7_README.md) — Stage 1 Scene Planner · Co-Processor Pack (1.7-cp)

---

*Last verified: 2026-03-05*

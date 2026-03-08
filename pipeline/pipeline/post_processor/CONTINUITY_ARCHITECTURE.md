# Continuity Architecture — Cross-Volume Memory Design

> **Reference: Series Bible · Arc Tracker · EPS System · Continuity Pack**

---

## 1. Overview

MTL Studio's continuity architecture solves the fundamental context-window problem in serialized novel translation: each volume must produce prose that is tonally, terminologically, and characterologically consistent with every preceding volume, even though no LLM context window can hold an entire multi-volume series.

The solution is a **two-store, layered memory model**:

```
┌─────────────────────────────────────────────────────────────┐
│  SERIES CANON STORE (upstream, cross-volume)                │
│  bibles/<series_id>.json                                    │
│  — canonical names, glossary, voice profiles, arc history  │
│  — advisory during Phase 2 translation                     │
│  — authoritative for carry-forward only                    │
└─────────────────────────────────────────────────────────────┘
          ↑ Phase 2.5 writes         ↓ Phase 1.5 pulls

┌─────────────────────────────────────────────────────────────┐
│  VOLUME CANON STORE (local, current volume)                 │
│  manifest.json + metadata_en.json                           │
│  — source of truth during Phase 1 and Phase 2              │
│  — ALWAYS wins over bible during translation               │
└─────────────────────────────────────────────────────────────┘
```

**Governing principle:** Local volume manifest state wins at runtime. The series bible is a **continuity hint**, never a canon override.

---

## 2. Continuity Data Flow

```text
Vol N-1 Phase 2   →   Phase 2.5   →   Series Bible (updated)
                                              ↓
Vol N   Phase 1.5 →   BibleSync.pull()  →   Inherited canonical terms injected
                                              into metadata translation prompt
        Phase 2   →   TranslatorAgent   →   Series Bible context block loaded
                       + ArcTracker           + EPS states carried forward
                       + BibleController
```

Each phase's relationship to the continuity stores:

| Phase | Read from Bible | Write to Bible |
|-------|----------------|----------------|
| 1.5 | Pull: canonical names, terms | Push: newly translated terms |
| 2 | Advisory: `<Series_Bible>` context block | Carry-forward EPS arc state |
| 2.5 | Reference for merge | Push: voice profiles, arc resolution |

---

## 3. The Series Bible (`bibles/<series_id>.json`)

### Structure

```jsonc
{
  "series_id": "watashiga_koibito",
  "series_title_jp": "わたしが恋人になれるわけないじゃん、ムリムリ!",
  "series_title_en": "There's No Freaking Way I'll Be Your Lover!",
  "created_at": "2026-02-20T...",
  "last_modified": "2026-03-05T...",
  "volumes": ["20260220_17a7", "20260305_17a8"],

  "characters": [
    {
      "name_jp": "天織れな子",
      "canonical_name_en": "Amaori Renako",
      "short_name": "Renako",
      "aliases": ["Rena-chan"],
      "pronouns": "she/her",
      "name_order": "western",
      "voice_archetype": "...",
      "fingerprint_key": "amaori_renako"
    }
  ],

  "glossary": {
    "空座高校": "Soraza High School",
    "部活": "club activity"
  },

  "voice_profiles": {
    "Amaori Renako": {
      "speech_patterns": "...",
      "formality_baseline": "casual",
      "signature_phrases": ["..."],
      "contraction_rate": 0.7,
      "sentence_length_avg": 8.2
    }
  },

  "arc_resolutions": [
    {
      "volume_id": "20260305_17a8",
      "summary": "Renako acknowledges feelings; relationship status: WARM",
      "eps_state": { "Amaori Renako → Protagonist": "WARM" }
    }
  ],

  "translation_decisions": {
    "keigo_rendering": "soft formality preserved, not literalized",
    "honorific_policy": "embedded in natural English, no -kun/-chan suffixes"
  }
}
```

### Series ID Derivation

`BibleSyncAgent._build_series_id()` builds a deterministic slug from the cleaned JP series title:
- Strips volume-discriminating suffixes
- Unicode normalize → ASCII slug
- Stable across all volumes in the same series

Example: `わたしが恋人になれるわけないじゃん` → `watashiga_koibito_narenai`

---

## 4. Arc Tracker & EPS Carry-Forward

### What It Is

`pipeline.translator.arc_tracker.ArcTracker` maintains an **emotional proximity signal (EPS)** history for each character pair across all chapters and volumes. EPS quantifies how close or distant a character is to the protagonist in a given scene.

### 6 Corpus Signals → EPS Score

| Signal | Weight | JP Signal Source |
|--------|--------|-----------------|
| `keigo_shift` | 0.30 | Honorific form changes between characters |
| `sentence_length_delta` | 0.20 | Deviation from character's baseline sentence length |
| `particle_signature` | 0.15 | Intimacy-marker particles (ね、よ、わ vs. です、ます) |
| `pronoun_shift` | 0.15 | First-person pronoun intimacy level |
| `dialogue_volume` | 0.10 | Ratio of dialogue lines to total lines |
| `direct_address` | 0.10 | Frequency of protagonist's name use in dialogue |

### EPS Score → Voice Band

| Band | Score Range | Voice Characteristics |
|------|------------|----------------------|
| `COLD` | ≤ −0.5 | Minimal expression, maximum formality, guarded brevity |
| `COOL` | −0.5 to −0.1 | Polite distance, controlled warmth, short answers |
| `NEUTRAL` | −0.1 to +0.1 | Character baseline, archetype-consistent prose |
| `WARM` | +0.1 to +0.5 | Casual intimacy, relaxed formality, personal address |
| `HOT` | ≥ +0.5 | Vulnerable openness, direct emotional statements |

### Storage

Arc state is persisted to `WORK/<vol>/.context/arc_tracker.json`. At Phase 2 startup, the arc tracker loads the previous volume's arc state (via series Bible `arc_resolutions`) to initialize carry-forward EPS.

---

## 5. Koji Fox Voice RAG System

### What It Is

`pipeline.translator.voice_rag_manager.VoiceRAGManager` provides a retrieval-augmented generation layer for **character speech consistency**. It indexes character voice fingerprints at Phase 2 startup and retrieves the most-relevant speech sample for each character before each chapter's translation.

### Source Data

Voice fingerprints are indexed from `manifest.json → metadata_en.character_voice_fingerprints`. This list is:
- Generated by Phase 1.51 LLM analysis of the full JP chapter text
- Augmented by `_augment_voice_fingerprint_coverage()` to ensure all `character_profiles` entries have at least a fallback fingerprint
- Stored in ChromaDB (with JSON fallback for offline operation)

### Query Interface

```python
voice_rag.query_for_chapter(
    chapter_id="chapter_03",
    eps_band="WARM",
    character_name="Amaori Renako"
)
# Returns: CHARACTER VOICE DIRECTIVE block for prompt injection
```

The directive specifies:
- Voice archetype for this EPS band
- Signature phrases to preserve
- Contraction rate targets
- Sentence length preferences
- Forbidden patterns (over-formal, anime-dub patterns)

---

## 6. Continuity Pack

The continuity pack is a JSON artifact written by Phase 2.5 and consumed at the start of the next volume's Phase 2:

```jsonc
{
  "source_volume_id": "20260305_17a8",
  "generated_at": "2026-03-05T...",
  "character_state": {
    "Amaori Renako": {
      "last_eps_band": "WARM",
      "relationship_status": "aware but unconfirmed",
      "arc_note": "Accepted Protagonist's proposal terms; internal conflict resolved"
    }
  },
  "open_plot_threads": ["Sena Ajisai subplot unresolved"],
  "glossary_additions": { "水着大会": "swimsuit competition" },
  "translation_decisions_delta": { "new_idiom": "rendering in Vol 2" }
}
```

The `ContinuityPackManager` (`pipeline/translator/continuity_manager.py`) loads this pack and injects it as a `<Continuity_Pack>` XML block in the Phase 2 prompt.

---

## 7. Series Bible vs. Local Manifest — Resolution Policy

The canonical resolution order during Phase 2 translation:

```
1. Local manifest.json  (highest authority — always wins)
2. Continuity pack      (carry-forward from previous volume)
3. Series bible         (advisory context only)
4. LLM inference        (fallback — lowest authority)
```

The Phase 1.5 bible pull can propose canonical terms for new characters. If the current manifest already has a conflicting translation, the override is logged as a `BiblePullResult.override` and the local value is used.

**Bible name-order normalization:** When Phase 2.5 updates the bible, `_normalize_bible_name_order()` reads the volume manifest's `name_order_policy` and converts all names in the existing bible to match (e.g., Western-order `Amaori Renako` instead of JP-order `Renako Amaori`), preventing future volumes from inheriting mismatched name forms.

---

## 8. Architecture Roadmap (from Engineering Docs)

The MTL Studio engineering review (`MTL_STUDIO_DIAGRAM.md`) targets the following improvements to reduce cross-phase coupling:

| Current State | Target State |
|---------------|-------------|
| Multiple phases can write canon-adjacent state | Only Phase 2.5 writes to series bible at end of run |
| `manifest.json`, `metadata_en.json`, `rich_metadata_cache_patch.json`, `visual_cache.json`, `PLANS/*.json` all writable by multiple phases | Derived artifacts treated as read-only views |
| Bible pull/push + Phase 2.5 push = 3 bible write paths | One normalized bible write path at Phase 2.5 only |
| Character identity logic duplicated across planner, multimodal, translator, bible sync | Single normalized identity model loaded once, shared |

---

## 9. Key Files

| File | Purpose |
|------|---------|
| `pipeline/metadata_processor/bible_sync.py` | `BibleSyncAgent`, `BiblePullResult`, `BiblePushResult` |
| `pipeline/translator/series_bible.py` | `BibleController`, `SeriesBible` |
| `pipeline/translator/arc_tracker.py` | `ArcTracker`, EPS signal computation |
| `pipeline/translator/voice_rag_manager.py` | `VoiceRAGManager`, ChromaDB index |
| `pipeline/translator/continuity_manager.py` | `ContinuityPackManager` |
| `pipeline/post_processor/volume_bible_update_agent.py` | `VolumeBibleUpdateAgent` (Phase 2.5) |
| `bibles/_index.json` | Series registry |
| `bibles/<series_id>.json` | Per-series bible data |
| `WORK/<vol>/.context/arc_tracker.json` | Per-volume arc state |
| `WORK/<vol>/.context/continuity_pack.json` | Per-volume continuity pack |

---

*Last verified: 2026-03-05*

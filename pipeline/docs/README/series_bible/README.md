# Series Bible Domain — Index

> [← Root README](../../../../../README.md) · [← Pipeline Index](../../../README.md) · [← Docs Index](../README.md)

The **Series Bible** family governs cross-volume continuity. Its two components — the live Bible store maintained by `BibleSyncAgent` and the post-translation writeback performed by `VolumeBibleUpdateAgent` (Phase 2.5) — ensure that canonical character names, voice profiles, glossary terms, arc resolutions, and translation decisions discovered in one volume are automatically available to all future volumes in the same series.

---

## Component Table

| Component | Name | One-line description | When it runs |
|-----------|------|---------------------|-------------|
| Phase 2.5 | Bible Update Agent | Post-QC full-volume synthesis → push voice profiles + arc resolution to bible | Automatically at end of Phase 2 (when `run_bible_update: true`) |
| Bible Sync (Pull) | BibleSyncAgent.pull() | Pull canonical terms from bible → inject into metadata translation prompt | During Phase 1.5 (before `batch_translate_ruby`) |
| Bible Sync (Push) | BibleSyncAgent.push() | Export newly discovered terms from manifest → bible | After Phase 1.5 final manifest write |
| Bible Controller | BibleController | Manage bible CRUD, series index, volume linking | Loaded by Phase 2 at startup |

---

## Phase 2.5 Trigger

Phase 2.5 (`VolumeBibleUpdateAgent`) is **not a standalone CLI command**. It runs automatically at the end of `TranslatorAgent.translate_volume()` when:

```yaml
# config.yaml
translation:
  phase25:
    run_bible_update: true
```

The QC clearance gate (`qc_cleared`) must pass before the update runs. If any chapter translations are flagged as failed or QC is explicitly bypassed, the bible update is skipped.

---

## Bible Store Architecture

```text
bibles/
  _index.json             # Series registry: series_id → bible file path, volume links
  <series_id>.json        # Individual series bible

  Structure per series bible:
    characters[]          # Canonical character records (name, aliases, pronouns, archetype)
    glossary{}            # JP → EN/VN term mappings
    voice_profiles{}      # Post-Phase-2.5 character voice data
    arc_resolutions[]     # Per-volume arc resolution summaries
    translation_decisions # Localization choices persistent across volumes
    eps_states{}          # Cross-volume EPS band carry-forward
```

---

## Per-Component READMEs

- [PHASE_2_5_README.md](./PHASE_2_5_README.md) — Volume Bible Update Agent (Phase 2.5)
- [CONTINUITY_ARCHITECTURE_README.md](./CONTINUITY_ARCHITECTURE_README.md) — Cross-volume Continuity Architecture

---

*Last verified: 2026-03-05*

# Phase 2 — Translator (Koji Fox Engine)

> **Section 10 · Translation Runtime**  
> Also covers: **Batch Mode** (Anthropic Message Batches API) · **Tool Mode** (structured JSON tool-call schema) · **Multimodal Mode** (Art Director's Notes injection)

---

## 1. Purpose

Phase 2 is the Koji Fox literary translation engine. It consumes every artifact produced by the Preparation family and generates a fully translated, Yen Press–grade English (or Vietnamese) chapter set for the volume.

The engine's design philosophy comes directly from Michael-Christopher Koji Fox's FFXVI localization method:

1. **English First** — prose rhythm, cadence, and naturalness take priority over literal structural adherence to JP syntax.
2. **Method Acting** — the translator maintains a distinct voice per character through the entire volume, modulated by EPS (Emotional Proximity Signal) band.
3. **Deep Involvement** — every available context artifact (scene plans, visual cache, voice fingerprints, series bible, arc tracker) is injected before the first token of translation is generated.
4. **Canon Event Fidelity** — art director's notes and EPS bands guide *register and tone*, never plot. No events are invented.

**What Phase 2 does per chapter:**

1. Runs the **Pre-Phase-2 Invariant Gate** — validates manifest completeness, scene plan presence, EPS coverage, voice fingerprint count, and bible sync status.
2. Assembles **per-chapter prompt context** — character voice directives, arc directives, scene plan scaffold, visual cache XML, EPS band context, continuity pack, cultural glossary, series bible context block.
3. Calls the translation **LLM provider** (Anthropic / Gemini / OpenRouter) — in streaming, batch, or tool-mode.
4. Runs **post-processing validators** — CJK cleaner, grammar validator, tense validator, format normalizer, name-order normalization, truncation validator, POV validator, reference validator.
5. Runs the **Koji Fox Naturalness Test** — anime dub pattern detection, stilted formality detection, contraction rate check, sentence length variance.
6. Writes final translated chapter Markdown to `EN/<chapter_id>.md`.
7. Updates `manifest.json → translation_log` with per-chapter cost audit, quality score, and status.

---

## 2. Entry Points

| Layer | Identifier |
|-------|-----------|
| Python module | `pipeline.translator.agent` |
| Main class | `TranslatorAgent` in `pipeline/translator/agent.py` |
| Volume translate method | `TranslatorAgent.translate_volume()` |
| Batch translate method | `TranslatorAgent.translate_volume_batch()` |
| Invoked via | `python -m pipeline.translator.agent` |
| Controller method | `PipelineController.run_phase2(volume_id, chapters, force, enable_multimodal, ...)` in `scripts/mtl.py` |
| Batch controller method | `PipelineController.run_batch(volume_id, ...)` in `scripts/mtl.py` |

Controller command:
```python
[sys.executable, "-m", "pipeline.translator.agent",
 "--dir", str(volume_dir),
 "--target-lang", target_lang,
 "--phase1-55-mode", phase155_mode]
# Optional flags:
[..., "--enable-multimodal"]          # inject Art Director's Notes
[..., "--tool-mode"]                  # structured tool-call schema (Anthropic only)
[..., "--full-ln-cache", "off"]       # skip full-LN cache prep gate
[..., "--force"]                      # overwrite chapters already translated
[..., "--chapters", "chapter_01", "chapter_03"]  # subset
```

Batch API invocation uses a separate code path within `TranslatorAgent.translate_volume_batch()` — prompts are assembled as Message Batch request objects, submitted to `AnthropicClient.create_batch()`, and polled until completion or timeout (24h max).

---

## 3. Inputs

| Input | Source | Notes |
|-------|--------|-------|
| `--dir <volume_dir>` | CLI arg | Full path to `WORK/<volume_id>/` directory |
| `manifest.json` | `<vol>/manifest.json` | Must have Phases 1, 1.5, 1.55 completed |
| Chapter JP text | `<vol>/chapters/chapter_NN.md` | Raw source text per chapter |
| Scene plans | `<vol>/scene_plans/<chapter>_scene_plan.json` | Phase 1.7 output; bound to chapter entry in manifest |
| Visual cache | `<vol>/visual_cache.json` | Phase 1.6 output; optional (required only with `--enable-multimodal`) |
| Rich metadata cache patch | `<vol>/rich_metadata_cache_patch.json` | Phase 1.55 enriched metadata delta |
| Co-processor artifacts | `<vol>/character_registry.json`, `cultural_glossary.json`, etc. | Phase 1.7-cp / 1.55 output |
| Translation brief | `<vol>/translation_brief.md` (or `.json`) | Phase 1.56 output; injected into batch prompts |
| Series bible | `bibles/<series_id>.json` | BibleController loads and pulls; advisory during translation |
| Arc tracker state | `<vol>/.context/arc_tracker.json` | EPS carry-forward; initialized if absent |
| Continuity pack | `<vol>/.context/continuity_pack.json` | Cross-chapter continuity context |
| `config.yaml` | Root `config.yaml` | LLM config, provider routing, tool mode config |
| `--enable-multimodal` | CLI flag | Triggers visual cache injection |
| `--phase1-55-mode` | `skip` / `overwrite` / `auto` / `ask` | Controls rich metadata cache behavior |

**Pre-flight Invariant Gate** (`_run_pre_phase2_invariant_gate`) validates:

| Check | Hard Failure | Warning |
|-------|-------------|---------|
| `manifest.json` exists | ✕ | — |
| `metadata_en.title_en` populated | ✕ | — |
| Character names populated | ✕ | — |
| Scene plans present (≥ 1 chapter) | — | ✓ (if none) |
| `character_voice_fingerprints` count | — | ✓ if < 2 |
| EPS band coverage vs. chapter count | — | ✓ if partial |
| Bible sync status | — | ✓ if failed |
| Visual cache (when multimodal enabled) | ✕ | — |

---

## 4. Outputs

All outputs written to `WORK/<volume_id>/`:

| Output | Path | Description |
|--------|------|-------------|
| Translated chapters | `EN/<chapter_id>.md` | One file per chapter, final translated prose |
| Translation log | `manifest.json → translation_log` | Per-chapter cost audit, quality score, status flags |
| Cost audit | `cost_audit_last_run.json` | Full tokenized cost breakdown (input, output, cache read, cache creation) |
| Arc tracker state | `.context/arc_tracker.json` | Updated EPS state after each chapter |
| Continuity pack | `.context/continuity_pack.json` | Updated cross-chapter continuity context |
| Pipeline state | `manifest.json → pipeline_state.translator` | `status`, `chapters_completed`, `chapters_failed`, `model`, timestamps |

**`translation_log` per-chapter entry fields:**
- `status` — `completed` / `failed`
- `quality_score` — 0.0–1.0 score from post-processing validators
- `input_tokens`, `output_tokens` — LLM usage
- `cache_read_tokens`, `cache_creation_tokens` — Anthropic prompt cache metrics
- `cost_usd` — estimated USD cost
- `tool_calls` — number of tool-mode invocations (0 if tool mode disabled)
- `adn_flags` — Art Director's Notes receipt flags (when multimodal)
- `retries` — retry count if translation required re-attempts

---

## 5. LLM Routing

### Anthropic (Default Production Path)

| Parameter | Value |
|-----------|-------|
| Model | `claude-opus-4-6` (default) or `claude-sonnet-4-6` |
| Temperature | `1.0` (Anthropic default) |
| Max output tokens | `32000` |
| Thinking budget | Enabled via extended thinking; adaptive |
| Cache strategy | Prompt caching on system prompt + metadata block; TTL 5m (auto-promoted to 1h for batch) |
| Config key | `translation.anthropic.model` in `config.yaml` |
| Client | `pipeline.common.anthropic_client.AnthropicClient` |
| Context window | 200K standard; 1M token window available for Opus 4.6 and Sonnet 4.6 (beta, Tier 4) |
| Endpoint routing | `openrouter` (default) or `official` (via `config.yaml → translation.phase2_anthropic_endpoint`) |

### Anthropic Batch Mode

| Parameter | Value |
|-----------|-------|
| API | Anthropic Message Batches API |
| Cost saving | 50% vs. streaming (Batch input/output priced at half of standard) |
| Latency | Most batches complete within 1 hour; 24h max before expiry |
| Cache TTL | Auto-promoted from 5m ephemeral to 1h for better cache hit rates across batch |
| Batch limit | 100,000 requests or 256 MB, whichever first |
| Result retention | 29 days after batch creation |
| Config key | `translation.anthropic.batch` in `config.yaml` |
| Trigger | `./mtl batch <volume_id>` or `./mtl phase2 <volume_id> --batch` |

### Gemini

| Parameter | Value |
|-----------|-------|
| Primary model | `gemini-3-flash-preview` or as configured |
| Fallback model | `gemini-2.5-flash` |
| Temperature | `0.7` |
| Max output tokens | `65536` |
| Thinking budget | `-1` (adaptive) |
| Tool mode | **NOT SUPPORTED** — auto-disabled on Gemini provider |
| Config key | `translation.gemini.model` in `config.yaml` |
| Client | `pipeline.common.gemini_client.GeminiClient` |

### OpenRouter

| Parameter | Value |
|-----------|-------|
| Model routing | `openrouter/<model>` format; defaults to `anthropic/<model>` |
| Config key | `translation.phase2_anthropic_endpoint: openrouter` |
| 1M context flag | `translation.openrouter_opus_1m_confirmed: true` enables 1M token routing |
| Tool mode | **NOT SUPPORTED** — auto-disabled on OpenRouter |
| Client | `pipeline.common.openrouter_client.OpenRouterLLMClient` |

---

## 6. Prompt / Tool Dependencies

### Prompt Assembly

The translation prompt is built by `pipeline.translator.prompt_loader.PromptLoader`. Key injection components:

| Component | Source | Format |
|-----------|--------|--------|
| Master system prompt | `prompts/` directory (managed by `PromptLoader`) | XML-structured |
| Character Voice Directive | `VoiceRAGManager.query_for_chapter(chapter_id, eps_band)` | `<Character_Voice_Directive>` block |
| Arc Directive | `ArcTracker.get_directive(chapter_id)` | EPS band + arc history |
| Scene Plan scaffold | `scene_plans/<chapter>_scene_plan.json` | Beat-by-beat `<Scene_Plan>` XML |
| Art Director's Notes | `visual_cache.json → <cache_id>.prompt_injection` | `<Visual_Cache>` XML (multimodal only) |
| Character profiles | `metadata_en.character_profiles` via `_transform_character_profiles()` | Structured character block |
| Cultural glossary | `cultural_glossary.json` | `<Cultural_Glossary>` block |
| Series bible context | `BibleSyncAgent.pull()` result | `<Series_Bible>` block |
| Continuity pack | `ContinuityPackManager.load()` | `<Continuity_Pack>` block |
| Translation brief | `translation_brief.md` | Injected into batch system prompt as shared cache block |

### Tool Mode (Anthropic Only)

When `config.yaml → translation.tool_mode.enabled: true` and provider = Anthropic, the translator uses a structured tool-call schema. Tools are invoked in a fixed order managed by `_TOOL_MODE_ORDER`:

| Tool | Purpose |
|------|---------|
| `declare_translation_parameters` | Declare EPS band, voice archetype, pacing strategy before first token |
| `validate_glossary_term` | RAG lookup for cultural terms during translation |
| `lookup_cultural_term` | Synonym / register lookup for JP cultural terms |
| _(additional tools)_ | _(see `pipeline/translator/agent.py` for full `_TOOL_MODE_ORDER` list)_ |

Tool mode is auto-disabled when:
- Provider is Gemini or OpenRouter
- Provider is OpenRouter with Anthropic model routing
- `config.yaml → translation.tool_mode.auto_disabled` is set

---

## 7. Koji Fox Voice System

The voice system governs per-character prose consistency across the entire volume.

### VoiceRAGManager (`pipeline/translator/voice_rag_manager.py`)

- Indexed at startup from `manifest.json → metadata_en.character_voice_fingerprints`
- ChromaDB storage with JSON fallback
- Queried per chapter by `(character_name, eps_band)` — returns most-relevant speech pattern sample
- Stored as `CHARACTER VOICE DIRECTIVE` block in the prompt

### ArcTracker (`pipeline/translator/arc_tracker.py`)

- Tracks EPS evolution across all volumes and chapters
- Computes EPS from 6 JP corpus signals:

| Signal | Weight |
|--------|--------|
| `keigo_shift` | 0.30 |
| `sentence_length_delta` | 0.20 |
| `particle_signature` | 0.15 |
| `pronoun_shift` | 0.15 |
| `dialogue_volume` | 0.10 |
| `direct_address` | 0.10 |

- Maps running EPS score → 5 voice bands (`COLD` / `COOL` / `NEUTRAL` / `WARM` / `HOT`)
- EPS bands adapt vocabulary register, contraction rate, formality, and sentence density
- State persisted to `.context/arc_tracker.json` after each chapter

### EPS Band Voice Characteristics

| Band | Range | Voice Characteristics |
|------|-------|----------------------|
| `COLD` | ≤ −0.5 | Minimal expression, heavy formality, guarded brevity |
| `COOL` | −0.5 to −0.1 | Polite distance, controlled warmth, short answers |
| `NEUTRAL` | −0.1 to +0.1 | Character baseline, archetype-consistent prose |
| `WARM` | +0.1 to +0.5 | Casual intimacy, relaxed formality, personal address |
| `HOT` | ≥ +0.5 | Vulnerable openness, direct emotional statements |

---

## 8. Post-Processing Pipeline

After each translated chapter is generated, a deterministic post-processing pipeline runs:

| Validator / Pass | Module | Purpose |
|-----------------|--------|---------|
| CJK Cleaner | `post_processor.cjk_cleaner_v2` | Remove CJK residue (stray JP characters) |
| VN CJK Cleaner | `post_processor.vn_cjk_cleaner` | Vietnamese-specific CJK and diacritic cleanup |
| Format Normalizer | `post_processor.format_normalizer` | Whitespace, header, list normalization |
| Name-Order Normalizer | `common.name_order_normalizer` | Apply volume-level JP/EN name-order policy |
| Truncation Validator | `post_processor.truncation_validator` | Detect mid-sentence truncation from token limits |
| POV Validator | `post_processor.pov_validator` | Verify POV consistency with scene plan |
| Reference Validator | `post_processor.reference_validator` | Check cross-references, chapter links |
| Tense Validator | `post_processor.tense_validator` | Flag tense consistency issues |
| Grammar Validator | `post_processor.grammar_validator` | Light structural grammar checks |
| Copyedit Post-Pass | `post_processor.copyedit_post_pass` | Final stylistic polish (Oxford comma, dialogue dash normalization) |
| AI-ism Fixer | `post_processor.phase2_5_ai_ism_fixer` | Strip AI-characteristic phrasing patterns |
| Stage 3 Refinement | `post_processor.stage3_refinement_agent` | Optional LLM-assisted refinement pass |
| Voice Validator | `translator.voice_validator` | EPS-band-adapted tolerance checks on voice fingerprints |
| Koji Fox Validator | `translator.koji_fox_validator` | Anime dub detection, stilted formality, read-aloud scoring |

---

## 9. Failure Modes & Guardrails

| Failure | Symptom | Recovery |
|---------|---------|---------|
| Pre-flight invariant gate failure | Fatal exit; lists specific violations | Fix violations (run missing prep phases), then re-run |
| LLM returns truncated output | Truncation validator flags; retried with extended `max_tokens` | Automatic retry up to `max_retries` |
| LLM 429 rate limit | Exponential backoff (`retry_delay_base_seconds`) | Automatic; configurable in `config.yaml → translation.rate_limit` |
| Gemini safety block | Warning logged; chapter marked failed | Manual: adjust content or use Anthropic provider |
| Anthropic batch timeout (24h) | Partial results returned; expired requests logged | Re-submit failed chapters individually |
| Visual cache miss for illustration | Warning logged; proceeds without ADN for that illustration | Run Phase 1.6 to populate cache |
| Voice fingerprint count < 2 | Pre-flight warning | Run `./mtl phase1.51 <volume_id>` to backfill |
| Bible sync failure | Warning; translation proceeds without bible context | Check bible file integrity; run `./mtl bible sync <volume_id>` |
| Name-order policy conflict | Hard error if unresolvable | Check `config.yaml → translation.name_order_policy` |
| Chapter already translated | Skipped unless `--force` | Re-run with `--force` to overwrite |

---

## 10. How to Run

### Standard translation (all chapters)
```bash
./mtl phase2 20260305_17a8
```

### With multimodal context (Art Director's Notes)
```bash
./mtl phase2 20260305_17a8 --enable-multimodal
```

### Batch mode (50% cost, ~1h latency)
```bash
./mtl batch 20260305_17a8
# Full batch pipeline: phase1.5 → phase1.55 → phase1.56 → phase1.6 → phase1.7 → phase2 (batch)
```

### Force re-translate specific chapters
```bash
# Not directly exposed in ./mtl wrapper. Use python directly:
python -m pipeline.translator.agent --dir WORK/5-3_vol_20260305_17a8 --chapters chapter_01 chapter_05 --force
```

### Skip full-LN cache prep gate
```bash
./mtl phase2 20260305_17a8 --full-ln-cache off
```

### Control Phase 1.55 rich metadata mode
```bash
./mtl phase2 20260305_17a8 --phase1-55-mode skip       # use existing cache only
./mtl phase2 20260305_17a8 --phase1-55-mode overwrite  # force rebuild cache
./mtl phase2 20260305_17a8 --phase1-55-mode auto       # auto-decide per manifest state
```

### Full combined multimodal run
```bash
./mtl multimodal 20260305_17a8
# Runs: phase1.6 → phase2 --enable-multimodal
```

### Check Phase 2 status after run
```bash
./mtl status 20260305_17a8
```

---

## 11. Validation Checklist

After a successful Phase 2 run, verify:

- [ ] `WORK/<volume_id>/EN/` directory exists with one `.md` file per chapter
- [ ] `manifest.json → pipeline_state.translator.status == "completed"` (or `partial` — check failed count)
- [ ] `manifest.json → translation_log` — `chapters_completed` equals expected chapter count
- [ ] `translation_log.chapters_failed == 0`; if > 0, identify and re-run failed chapters with `--force`
- [ ] Spot-check 2–3 EN chapter files: no stray JP characters (CJK residue), correct dialogue dash style, no truncation mid-sentence
- [ ] `cost_audit_last_run.json` exists and has plausible token counts
- [ ] `.context/arc_tracker.json` updated (timestamp newer than run)
- [ ] Voice fingerprint log at startup: `✓ Koji Fox: N voice fingerprint(s) indexed` — N should equal character count in `metadata_en.character_profiles`
- [ ] If multimodal: `adn_flags` in translation log entries show ADN receipts
- [ ] Run `./mtl status <volume_id>` — Section 10 badge should be ✓

---

*Last verified: 2026-03-05*

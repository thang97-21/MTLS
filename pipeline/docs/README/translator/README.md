# Translator Domain — Index

> [← Root README](../../../../../README.md) · [← Pipeline Index](../../../README.md) · [← Docs Index](../README.md)

The **Translator** family is the pipeline's core literary engine. Phase 2 converts the structured context package produced by the Preparation family into fully translated, Yen Press–grade English (or Vietnamese) prose chapters. It orchestrates multiple subsystems simultaneously: voice RAG, arc tracking, scene plan injection, multimodal context, continuity management, tooling schemas, and post-processing validators.

---

## Phase Table

| Phase  | Name                          | One-line description                                                   | CLI command                              |
|--------|-------------------------------|------------------------------------------------------------------------|------------------------------------------|
| 2      | Translator (Koji Fox Engine)  | LLM-driven JP → EN/VN chapter-by-chapter translation with full context | `./mtl phase2 <volume_id>`               |
| 2      | Batch Mode                    | Anthropic Batch API path: 50% cost, ~1h latency                        | `./mtl phase2 <volume_id> --batch`       |
| 2      | Multimodal Mode               | Phase 2 with Art Director's Notes injected from visual cache           | `./mtl phase2 <volume_id> --enable-multimodal` |

---

## Typical Run Sequence

```
[Preparation complete]  →  phase2  →  [Auditor QC]  →  phase2.5  →  phase4 (EPUB build)
```

Phase 2 is the only phase that writes final translated output. All upstream phases (1 → 1.7) feed into it; all downstream phases (2.5, 4, auditors) consume its output.

---

## Provider Architecture

Phase 2 supports three provider paths, switchable via `config.yaml → translation.translator_provider`:

| Provider    | Mode        | Notes |
|-------------|-------------|-------|
| `anthropic` | Streaming   | Default production path; Claude Opus/Sonnet models |
| `anthropic` | Batch       | `--batch` flag; Anthropic Message Batches API, 50% cost |
| `gemini`    | Streaming   | Gemini 3 Flash/Pro models; no tool-mode support |
| `openrouter`| Streaming   | OpenRouter routing; supports `anthropic/` model identifiers |

Tool-mode (structured JSON tool invocations during translation) is **Anthropic-only** and auto-disabled when provider is Gemini or OpenRouter.

---

## Per-Phase READMEs

- [PHASE_2_README.md](./PHASE_2_README.md) — Translator Agent · Batch Mode · Tool Mode · Post-Processing

---

*Last verified: 2026-03-05*

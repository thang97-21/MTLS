# Phase 1 — Librarian

> **Section 1 · EPUB → Markdown Extraction**

---

## 1. Purpose

The Librarian is the pipeline's ingestion gate. It unpacks a Japanese EPUB, extracts every chapter as structured Markdown, harvests illustration asset references, and writes the canonical `manifest.json` that every downstream phase depends on. No other phase can run until Phase 1 has completed successfully.

Key outcomes:
- Reproducible text units (one `.md` file per chapter)
- Manifest with chapter list, asset index, and pipeline state flags
- Initial `metadata_en` scaffold populated from EPUB OPF metadata
- Volume-ID assignment (timestamp-based if not supplied)

---

## 2. Entry Points

| Layer | Identifier |
|-------|-----------|
| Python module | `pipeline.librarian.agent` |
| Invoked via | `python -m pipeline.librarian.agent` |
| Controller method | `MTLController.run_phase1(epub_path, volume_id)` in `scripts/mtl.py` |
| MCP server (optional) | `pipeline/mcp/servers/librarian_server.py` |

The controller assembles the subprocess command:
```python
[sys.executable, "-m", "pipeline.librarian.agent",
 str(epub_path),
 "--work-dir", str(self.work_dir),
 "--target-lang", target_lang,
 "--volume-id", volume_id]   # omitted when auto-generating
```

---

## 3. Inputs

| Input | Source | Notes |
|-------|--------|-------|
| `epub_path` | CLI positional arg | Path to `.epub` file |
| `--work-dir` | config / default `data/` | Destination root for volume directories |
| `--target-lang` | `config.yaml → project.target_language` | `en` or `vn` |
| `--volume-id` | Optional CLI arg | Auto-generated as `YYYYMMDD_<hash4>` if omitted |
| `--ref-validate` | Optional flag | Triggers reference cross-validation pass |

---

## 4. Outputs

All artifacts are written to `<work_dir>/<volume_id>/`:

| Artifact | Path | Description |
|----------|------|-------------|
| `manifest.json` | `<vol>/manifest.json` | Master state document for the volume |
| Chapter Markdown | `<vol>/chapters/chapter_NN.md` | One file per chapter, JP text |
| Illustration assets | `<vol>/illustrations/` | Extracted image files |
| Initial metadata scaffold | `manifest.json → metadata_en` | OPF-derived title, author, chapter list |
| Pipeline state | `manifest.json → pipeline_state.librarian` | `status: completed`, timestamp |

`manifest.json` top-level fields populated by Phase 1:
- `metadata` — raw JP metadata from OPF
- `metadata_en` — initial scaffold (not yet translated)
- `chapters[]` — array of chapter objects with `id`, `file`, `title_jp`
- `assets[]` — illustration catalog with `epub_id`, `file_path`
- `pipeline_state.librarian` — phase completion flags

---

## 5. LLM Routing

| Parameter | Value |
|-----------|-------|
| Model | `gemini-3-flash-preview` |
| Temperature | `0.7` |
| Top-P | `0.95` |
| Top-K | `40` |
| Max output tokens | `65536` |
| Provider | Gemini (Google) |
| Thinking budget | `-1` (adaptive) |
| Config key | `translation.phase_models.'1'` in `config.yaml` |

The Librarian uses the LLM only for initial schema scaffold generation (character name extraction from EPUB metadata, not full translation). Chapter extraction is deterministic (HTML → Markdown parsing).

---

## 6. Prompt / Tool Dependencies

 Phase 1 is **entirely deterministic** — no LLM calls are made. The processing pipeline is:

1. **EPUB extraction** — `pipeline.librarian.epub_extractor.EPUBExtractor` → unzips EPUB, locates OPF/NCX, validates structure
2. **OPF metadata parsing** — `pipeline.librarian.metadata_parser.MetadataParser.parse_opf()` → extracts title, author, language, publication date
3. **TOC parsing** — `pipeline.librarian.toc_parser.TOCParser` → parses EPUB3 Navigation Document or EPUB2 NCX for chapter order
4. **Spine parsing** — `pipeline.librarian.spine_parser.SpineParser` → parses OPF spine for reading order and illustration page detection
5. **Pre-TOC content detection** — `config.pre_toc_detection` config → detects and handles unlisted opening-hook pages (color plates before TOC)
6. **Volume act detection** — `_detect_volume_acts()` → identifies multi-act chapters and publisher-specific spine structures (e.g., Kodansha act groupings)
7. **Hybrid TOC/spine fallback** — `_validate_toc_completeness()` → if TOC covers < threshold of spine, falls back to spine-ordered chapter set
8. **XHTML → Markdown conversion** — `pipeline.librarian.xhtml_to_markdown.XHTMLToMarkdownConverter` → converts each XHTML source file to clean JP Markdown
9. **Ruby name extraction** — `pipeline.librarian.ruby_extractor.extract_ruby_from_directory()` → extracts furigana annotations as `ruby_names[]` for initial character profile scaffolding
10. **Image extraction** — `pipeline.librarian.image_extractor.ImageExtractor` + `catalog_images()` → extracts and catalogs all illustration assets
11. **Content splitting** — `pipeline.librarian.content_splitter.ContentSplitter` / `KodanshaSplitter` → splits oversized spine groups into canonical chapter boundaries

**Initial character profile scaffold** is built deterministically from `ruby_names[]` — no LLM involved. Character profiles at Phase 1 have `speech_pattern: "[TO BE FILLED]"` placeholders until Phase 1.5 or 1.51 runs.

- Schema autoupdate: handled by `pipeline.metadata_processor.schema_autoupdate.SchemaAutoUpdater` (called in Phase 1.5, not Phase 1)
- No external tool schemas required at Phase 1

---

## 7. Failure Modes & Guardrails

| Failure | Symptom | Recovery |
|---------|---------|---------|
| EPUB file not found | `FileNotFoundError` at startup | Verify path; re-run with correct path |
| Malformed EPUB structure | `RuntimeError: EPUB extraction failed` | EPUB unpacking error is fatal; verify EPUB validity with a viewer; check OPF locates correctly in `META-INF/container.xml` |
| Duplicate volume ID | Manifest already exists | Supply a new `--volume-id` or delete existing dir |
| Illustration extraction failure | Warning logged; missing from `assets[]` | Non-fatal; Phase 1.6 will report missing files |
| Target language not configured | Falls back to `en` default | Set `project.target_language` in `config.yaml` |

Phase 1 is designed to be **idempotent** for re-runs on the same volume ID, but existing translated fields in `metadata_en` are not preserved — re-run Phase 1.5 after any re-extraction.

---

## 8. How to Run

### Full pipeline (auto-generate volume ID)
```bash
./mtl run INPUT/my_novel_vol3.epub
```

### Phase 1 only (extract, then stop)
```bash
./mtl phase1 INPUT/my_novel_vol3.epub
```

### Phase 1 with a specific volume ID
```bash
./mtl run INPUT/my_novel_vol3.epub --id 20260305_17a8
```

### Phase 1 with reference validation
```bash
./mtl phase1 INPUT/my_novel_vol3.epub --ref-validate
```

### Check extraction output
```bash
./mtl status <volume_id>    # Section 1 badge shows ✓
ls WORK/<volume_id>/chapters/       # one .md per chapter
ls WORK/<volume_id>/illustrations/  # extracted images
```

After Phase 1, the new volume ID is printed. Copy it — every subsequent phase requires it.

---

## 9. Validation Checklist

After a successful Phase 1 run, verify:

- [ ] `data/<volume_id>/manifest.json` exists and is valid JSON
- [ ] `manifest.json → pipeline_state.librarian.status == "completed"`
- [ ] `manifest.json → chapters[]` contains the expected chapter count
- [ ] Chapter Markdown files exist under `data/<volume_id>/chapters/`
- [ ] Illustration files (if any) present under `data/<volume_id>/illustrations/`
- [ ] `manifest.json → metadata.title` is populated with the JP title
- [ ] `manifest.json → metadata_en` scaffold is present (even if untranslated)
- [ ] Run `./mtl status <volume_id>` — Section 1 badge should be ✓

---

*Last verified: 2026-03-05*

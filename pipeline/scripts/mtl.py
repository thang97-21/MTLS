#!/usr/bin/env python3
"""
MT Publishing Pipeline - Unified Controller
Multi-language Japanese EPUB translation pipeline (EN/VN supported)

Sections:
  1. Librarian      - Extract Japanese EPUB to markdown
  3. Metadata       - Schema autoupdate + title/author/chapter translation
  6. Rich Cache     - Full-LN JP cache + rich metadata enrichment (Gemini 2.5 Flash)
  8. Multimodal     - Pre-bake illustration analysis (Gemini 3 Pro Vision)
  9. Scene Planner  - Narrative beat + rhythm scaffold (v1.6 Stage 1)
  9. Co-Processor   - Standalone context offload pack refresh (cache-only)
  10. Translator    - Gemini-powered translation with RAG + visual context
  11. Review Gate   - Manual/Agentic quality review (Gemini CLI + IDE Agent)
  12. Builder       - Package final translated EPUB

Usage:
  mtl.py run <epub_path>                 # Full pipeline (auto-generates volume ID)
  mtl.py run <epub_path> --id <id>       # Full pipeline with custom ID
  mtl.py run <epub_path> --verbose       # Full pipeline with interactive prompts
  mtl.py run <epub_path> --skip-multimodal  # Skip Section 8 (faster, no visual context)
  mtl.py phase1 <epub_path>              # Run Section 1 only
  mtl.py phase1.5 [volume_id]            # Run Section 3 (metadata processing)
    mtl.py pronoun-shift [volume_id]       # Run standalone deterministic JP pronoun-shift detector
  mtl.py phase1.55 [volume_id]           # Run Section 6 (full-LN cache metadata enrichment)
  mtl.py phase1.6 [volume_id]            # Run Section 8 (multimodal pre-bake)
  mtl.py phase1.6 [volume_id] --full-ln-cache off  # Skip full-LN cache prep
  mtl.py phase1.7 [volume_id]            # Run Section 9 (scene planning scaffold)
  mtl.py phase1.7-cp [volume_id]         # Run Section 9 Co-Processor (standalone context pack)
  mtl.py phase2 [volume_id]              # Run Section 10 (interactive if no ID)
  mtl.py phase2 [volume_id] --enable-multimodal  # Section 10 with visual context
  mtl.py phase2 [volume_id] --full-ln-cache off  # Run without full-LN cache prep
  mtl.py phase2 [volume_id] --phase1-55-mode skip|overwrite|auto|ask
  mtl.py phase2 [volume_id] --batch     # Anthropic Batch API (50% cost, ~1h latency)
  mtl.py phase1.56 [volume_id]          # Section 7: Translator's Guidance Brief (Anthropic batch pre-analysis)
  mtl.py batch [volume_id]              # OPTION 1 (Anthropic): Full batch pipeline — 1.5→1.55→1.56→1.6→1.7→Section 10 batch
  mtl.py batch [volume_id] --skip-multimodal  # Skip Section 8 (no illustrations)
  mtl.py batch [volume_id] --force-brief      # Re-generate brief even if cached
  mtl.py multimodal [volume_id]          # Run Section 8 + Section 10 with multimodal (visual translation)
  mtl.py phase4 [volume_id]              # Run Section 12 (interactive if no ID)
  mtl.py status <volume_id>              # Check pipeline status
  mtl.py list                            # List all volumes
  mtl.py metadata <volume_id>            # Inspect metadata and schema
  mtl.py bible list                      # List all linked series bibles
  mtl.py bible sync <volume_id>          # Sync bible <-> manifest continuity data
  mtl.py cache-inspect [volume_id]       # Inspect visual analysis cache
  mtl.py visual-thinking [volume_id]     # Convert visual thought logs to markdown
  mtl.py visual-thinking [volume_id] --split        # One file per illustration
  mtl.py visual-thinking [volume_id] --with-cache   # Include Art Director's Notes

Interactive Mode:
    - Section 10, 12: Can be run without volume_id to see selection menu
  - Partial IDs: Use last 4 chars (e.g., "1b2e" instead of full name)
  - Ambiguous IDs: Automatically shows selection menu

Configuration:
  mtl.py config --show                   # Show current configuration
  mtl.py config --language en            # Switch to English translation
  mtl.py config --language vn            # Switch to Vietnamese translation
  mtl.py config --show-language          # Show current target language
  mtl.py config --model pro              # Switch to gemini-3-pro-preview
  mtl.py config --model flash            # Switch to gemini-3-flash-preview
  mtl.py config --model 2.5-pro          # Switch to gemini-2.5-pro
  mtl.py config --model 2.5-flash        # Switch to gemini-2.5-flash
  mtl.py config --temperature 0.7        # Adjust creativity (0.0-2.0)
  mtl.py config --top-p 0.9              # Adjust nucleus sampling (0.0-1.0)
  mtl.py config --top-k 50               # Adjust top-k sampling (1-100)
  mtl.py config --toggle-pre-toc         # Toggle pre-TOC content detection
  mtl.py config --toggle-smart-chunking  # Toggle smart chunking for massive chapters

Target Languages:
  en:  English - Natural dialogue, American English conventions
  vn:  Vietnamese - Character archetypes, context-aware pronouns, SFX transcreation

Metadata Schemas (Auto-Detected):
  Enhanced v2.1:  characters, dialogue_patterns, scene_contexts, translation_guidelines
  Legacy V2:      character_profiles, localization_notes, speech_pattern
  V4 Nested:      character_names with nested {relationships, traits, pronouns}
  
  The translator auto-transforms all schemas to a unified internal format.
  Use 'mtl.py metadata <volume_id> --validate' to check schema compatibility.

Section 3 (Metadata Processor):
  - Auto-updates metadata_en schema via Gemini (Schema Agent autoupdate)
  - Translates: title, author, chapter titles, character names
  - PRESERVES: v3 enhanced schema (character_profiles, localization_notes, keigo_switch)
  - Safe to re-run on volumes with existing schema configurations

Section 6 (Rich Metadata Cache):
  - Loads bible continuity context (when linked)
  - Caches full JP volume text and calls Gemini 2.5 Flash (temp 0.5)
  - Enriches rich metadata fields for stronger Section 10 continuity

Section 8 (Multimodal Processor):
  - Analyzes illustrations using Gemini 3 Pro Vision
  - Generates Art Director's Notes for translation context
  - Canon Event Fidelity: Visual guidance enhances vocabulary, not content
  - Runs automatically in full pipeline (use --skip-multimodal to bypass)
  
  Manual inspection:
    mtl.py cache-inspect <volume_id>              # View cached visual analysis
    mtl.py cache-inspect <volume_id> --detail     # Full analysis details

Modes:
  Default (Minimal):  Clean output, auto-proceed through sections, no interactive prompts
  --verbose:          Full details, interactive menus, metadata review options
                      - Sequel detection: Asks whether to inherit metadata
                      - Post-Section 3: Option to review metadata before translation
                      - Post-Section 10: Interactive menu before building EPUB
"""

import sys
import argparse
import json
import logging
import readline  # Enable delete key, arrow keys, and command history in CLI
from collections import deque
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
import subprocess
import re
import os
import hashlib
import time

# Import CJK validator for quality control
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.cjk_validator import CJKValidator
from pipeline.cli.ui import ModernCLIUI

# Setup logging
logging.basicConfig(
    level=logging.INFO,  # Default to INFO, use --verbose for DEBUG
    format="[%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Project paths
INPUT_DIR = PROJECT_ROOT / "INPUT"
WORK_DIR = PROJECT_ROOT / "WORK"
OUTPUT_DIR = PROJECT_ROOT / "OUTPUT"


class PipelineController:
    """Unified controller for the MT Publishing Pipeline."""
    
    def __init__(
        self,
        work_dir: Path = WORK_DIR,
        verbose: bool = False,
        ui_mode: str = "auto",
        no_color: bool = False,
    ):
        self.work_dir = work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.verbose = verbose
        self.ui = ModernCLIUI(mode=ui_mode, no_color=no_color)

    def _ui_header(self, title: str, subtitle: str = "") -> None:
        """Print a consistent v5.2 CLI header."""
        if self.ui.print_header(title, subtitle):
            return

        line = "=" * 78
        logger.info(line)
        logger.info(f"MTL Studio v5.2 | {title}")
        if subtitle:
            logger.info(subtitle)
        logger.info(line)

    def _phase2_runtime_profile_lines(self, enable_multimodal: bool) -> List[str]:
        """
        Build concise advanced runtime lines for Section 10.
        """
        try:
            from pipeline.config import (
                PIPELINE_ROOT as CONFIG_PIPELINE_ROOT,
                get_config_section,
                get_language_config,
                get_target_language,
            )
            from pipeline.translator.config import (
                get_fallback_model_name, get_model_name,
                get_translator_provider, get_anthropic_config,
            )

            target_lang = get_target_language()
            lang_config = get_language_config(target_lang)

            translation_cfg = get_config_section("translation")
            gemini_cfg = get_config_section("gemini")
            multimodal_cfg = get_config_section("multimodal")
            massive_cfg = translation_cfg.get("massive_chapter", {})

            # Active translator provider
            provider = get_translator_provider()

            # Tiered RAG signals
            modules_dir = CONFIG_PIPELINE_ROOT / lang_config.get("modules_dir", "modules/")
            core_module_count = len(list(modules_dir.glob("*.md"))) if modules_dir.exists() else 0
            grammar_rag_cfg = lang_config.get("grammar_rag", {})
            grammar_rag_enabled = bool(grammar_rag_cfg.get("enabled", False))
            reference_count = len(lang_config.get("reference_modules", []))
            lookback = translation_cfg.get("context", {}).get("lookback_chapters", 2)

            # Vector search signals (config-backed where available)
            vector_cfg = grammar_rag_cfg.get("vector_store", {})
            if vector_cfg:
                vector_hint = vector_cfg.get("collection_name") or vector_cfg.get("persist_directory") or "configured"
            else:
                vector_hint = "language pattern stores"

            # Caching signals — provider-aware
            if provider == "anthropic":
                anthropic_cfg = get_anthropic_config()
                caching_cfg = anthropic_cfg.get("caching", {})
                cache_enabled = bool(caching_cfg.get("enabled", True))
                _ttl_min = int(caching_cfg.get("ttl_minutes", 5))
                _ttl_label = "5m" if _ttl_min <= 5 else "1h"
                cache_ttl_str = f"{_ttl_label} ephemeral" if cache_enabled else "OFF"
                active_model = anthropic_cfg.get("model", "claude-sonnet-4-6")
                active_fallback = anthropic_cfg.get("fallback_model", "claude-haiku-4-5-20251001")

                # ── Opus 4.6 feature flags ──────────────────────────────
                is_opus = active_model.startswith("claude-opus-4-6")
                thinking_cfg = anthropic_cfg.get("thinking_mode", {})
                thinking_enabled = bool(thinking_cfg.get("enabled", False))
                thinking_type = thinking_cfg.get("thinking_type", "adaptive")
                # For Opus: adaptive thinking is active when enabled
                # For Sonnet: adaptive is rejected, falls back to "enabled"/budget
                thinking_active = thinking_enabled and (is_opus or thinking_type == "enabled")
                thinking_mode_label = (
                    f"{thinking_type}" if thinking_active
                    else "OFF"
                )
                effort_label = "max" if is_opus else "N/A"
                max_out_label = "128K" if is_opus else "64K"
            else:
                caching_cfg = gemini_cfg.get("caching", {})
                cache_enabled = bool(caching_cfg.get("enabled", True))
                cache_ttl_str = f"{int(caching_cfg.get('ttl_minutes', 120))}m"
                active_model = get_model_name()
                active_fallback = get_fallback_model_name()
                is_opus = False
                thinking_active = False
                thinking_mode_label = "N/A"
                effort_label = "N/A"
                max_out_label = "N/A"

            cache_ttl = cache_ttl_str  # used in the cache line below

            # Multimodal signals
            multimodal_allowed = bool(multimodal_cfg.get("enabled", False))
            multimodal_default = bool(translation_cfg.get("enable_multimodal", False))
            multimodal_active = multimodal_allowed and (enable_multimodal or multimodal_default)
            vision_model = multimodal_cfg.get("models", {}).get("vision", "n/a")

            rag_status = "RUN" if core_module_count > 0 else "FAIL"
            vector_status = "RUN" if grammar_rag_enabled else "TODO"
            cache_status = "RUN" if cache_enabled else "TODO"
            smart_chunking_enabled = bool(massive_cfg.get("enable_smart_chunking", True))
            chunk_status = "RUN" if smart_chunking_enabled else "TODO"
            chunk_threshold_chars = int(massive_cfg.get("chunk_threshold_chars", 60000))
            chunk_threshold_bytes = int(massive_cfg.get("chunk_threshold_bytes", 120000))
            if multimodal_active:
                multimodal_status = "RUN"
            elif multimodal_allowed:
                multimodal_status = "TODO"
            else:
                multimodal_status = "FAIL"

            lines = [
                (
                    f"Runtime Profile: DONE | {target_lang.upper()} ({lang_config.get('language_name', target_lang.upper())}) "
                    f"| Provider={provider.upper()} | Model={active_model} | Fallback={active_fallback}"
                ),
                (
                    f"Tiered RAG: {rag_status} | T1 Core={core_module_count} | T1 Grammar={'ON' if grammar_rag_enabled else 'OFF'} "
                    f"| T2 Reference={reference_count} | T3 Lookback={lookback}"
                ),
                (
                    f"Vector Search: {vector_status} | {'ON' if grammar_rag_enabled else 'AUTO'} | Source={vector_hint}"
                ),
                (
                    f"Context Cache: {cache_status} | {'ON' if cache_enabled else 'OFF'} | TTL={cache_ttl}"
                ),
                (
                    f"Smart Chunking: {chunk_status} | {'ON' if smart_chunking_enabled else 'OFF'} "
                    f"| Threshold={chunk_threshold_chars}c/{chunk_threshold_bytes}b"
                ),
                (
                    f"Multimodal: {multimodal_status} | {'ON' if multimodal_active else 'OFF'} "
                    f"| {'Vision=' + vision_model if multimodal_active else 'Hint=--enable-multimodal'}"
                ),
            ]
            # Append Anthropic-specific Opus 4.6 features line when provider is Anthropic
            if provider == "anthropic":
                batch_hint = "ON (--batch)" if is_opus else "HINT=--batch"
                lines.append(
                    f"Claude Features: {'RUN' if thinking_active else 'TODO'} "
                    f"| Thinking={thinking_mode_label}"
                    f" | Effort={effort_label}"
                    f" | MaxOut={max_out_label}"
                    f" | Batch={batch_hint}"
                )
            return lines
        except Exception as e:
            if self.verbose:
                logger.debug(f"[S10 Profile] Fallback profile due to config read issue: {e}")
            return [
                "Runtime profile: Tiered RAG + Vector Search + Context Cache + Multimodal",
            ]

    def _status_badge(self, status: str) -> str:
        """Convert manifest status to compact badge."""
        value = (status or "").lower()
        if value == "completed":
            return "DONE"
        if value in {"in_progress", "running"}:
            return "RUN"
        if value in {"failed", "error"}:
            return "FAIL"
        if value in {"pending", "not started", ""}:
            return "TODO"
        return value[:4].upper()

    def _visual_phase_badge(self, volume_id: str) -> str:
        """Return Section 8 visual cache badge."""
        cache_path = self.work_dir / volume_id / "visual_cache.json"
        if not cache_path.exists():
            return "TODO"
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            return f"DONE({len(cache)})"
        except Exception:
            return "WARN"

    def _short_volume_id(self, volume_id: str) -> str:
        """Return a compact, stable ASCII key for table displays."""
        match = re.search(r"(\d{8}_[0-9a-fA-F]{4,8})$", volume_id)
        if match:
            return match.group(1)

        compact = re.sub(r"[^A-Za-z0-9_-]+", "", volume_id)
        if compact:
            return compact[-14:]

        digest = hashlib.sha1(volume_id.encode("utf-8")).hexdigest()[:8]
        return f"id_{digest}"
        
    # ── Verbose Section Confirmation Logs ───────────────────────────────

    def _log_phase1_confirmation(self, volume_id: str) -> None:
        """Log verbose confirmation for Section 1 (Librarian) results."""
        manifest = self.load_manifest(volume_id)
        if not manifest:
            return

        vol_path = self.work_dir / volume_id

        # Chapters
        jp_dir = vol_path / "JP"
        jp_chapters = sorted(jp_dir.glob("CHAPTER_*.md")) if jp_dir.is_dir() else []

        # Metadata
        metadata = manifest.get("metadata", {})
        title = metadata.get("title", "N/A")
        author = metadata.get("author", "N/A")

        # Ruby extraction
        ruby_names = manifest.get("ruby_names", {})
        ruby_terms = manifest.get("ruby_terms", [])

        # Character names (raw JP extraction)
        meta_en = manifest.get("metadata_en", {})
        char_names = meta_en.get("character_names", {})
        char_profiles = meta_en.get("character_profiles", {})

        # Assets
        assets_dir = vol_path / "assets" if (vol_path / "assets").is_dir() else vol_path / "_assets"
        illust_count = len(list((assets_dir / "illustrations").glob("*.*"))) if (assets_dir / "illustrations").is_dir() else 0
        kuchie_count = len(list((assets_dir / "kuchie").glob("*.*"))) if (assets_dir / "kuchie").is_dir() else 0

        # Bible linkage (explicit or resolvable from index patterns)
        bible_id = manifest.get("bible_id", None)
        bible_display = bible_id or "NOT SET"
        if not bible_id:
            try:
                from pipeline.translator.series_bible import BibleController
                bc = BibleController(PROJECT_ROOT)
                resolved = bc.detect_series(manifest)
                if resolved:
                    bible_display = f"AUTO-DETECT: {resolved[:27]}..."
            except Exception:
                # Keep default display if bible detection is unavailable.
                pass

        # Multimodal
        mm = manifest.get("multimodal", {})
        mm_enabled = mm.get("enabled", False)

        logger.info("")
        logger.info("┌─────────────────────────────────────────────────────────────┐")
        logger.info("│  SECTION 1 CONFIRMATION — Librarian Output                   │")
        logger.info("├─────────────────────────────────────────────────────────────┤")
        logger.info(f"│  Title:     {title[:50]:<50}│")
        logger.info(f"│  Author:    {author[:50]:<50}│")
        logger.info(f"│  Volume ID: {volume_id[-40:]:<50}│")
        logger.info("├─────────────────────────────────────────────────────────────┤")
        logger.info(f"│  JP Chapters:       {len(jp_chapters):<5}                                    │")
        logger.info(f"│  Ruby Names:        {len(ruby_names):<5}                                    │")
        logger.info(f"│  Ruby Terms:        {len(ruby_terms):<5}                                    │")
        logger.info(f"│  Character Names:   {len(char_names):<5}  (Gemini extraction)               │")
        logger.info(f"│  Character Profiles:{len(char_profiles):<5}  (rich profiles)                  │")
        logger.info("├─────────────────────────────────────────────────────────────┤")
        logger.info(f"│  Illustrations:     {illust_count:<5}                                    │")
        logger.info(f"│  Color Plates:      {kuchie_count:<5}  (kuchie)                          │")
        logger.info(f"│  Multimodal:        {'ENABLED' if mm_enabled else 'DISABLED':<10}                               │")
        logger.info("├─────────────────────────────────────────────────────────────┤")
        logger.info(f"│  Bible ID:          {bible_display:<40}│")
        logger.info("└─────────────────────────────────────────────────────────────┘")

    def _log_phase1_5_confirmation(self, volume_id: str) -> None:
        """Log verbose confirmation for Section 3 (Metadata Processor) results."""
        manifest = self.load_manifest(volume_id)
        if not manifest:
            return

        from pipeline.config import get_target_language
        target_lang = get_target_language()

        metadata = manifest.get("metadata", {})
        meta_key = f"metadata_{target_lang}"
        meta_translated = manifest.get(meta_key, {})
        if not meta_translated and target_lang == "en":
            meta_translated = manifest.get("metadata_en", {})

        title_key = f"title_{target_lang}"
        author_key = f"author_{target_lang}"
        series_key = f"series_title_{target_lang}"
        title_en = meta_translated.get(title_key, "N/A")
        author_en = meta_translated.get(author_key, "N/A")
        series_en = meta_translated.get(series_key, "—")

        char_names = meta_translated.get("character_names", {})
        char_profiles = meta_translated.get("character_profiles", {})
        glossary = meta_translated.get("glossary", {})

        # Chapters
        chapters = manifest.get("chapters", [])
        translated_titles = sum(1 for c in chapters if c.get(f"title_{target_lang}") or c.get("title_en"))

        # Bible integration
        bible_id = manifest.get("bible_id", None)
        bible_status = "NOT LINKED"
        bible_entries = 0
        bible_categories = ""
        if bible_id:
            try:
                from pipeline.translator.series_bible import BibleController
                bc = BibleController(PROJECT_ROOT)
                bible = bc.load(manifest)
                if bible:
                    bible_entries = bible.entry_count()
                    stats = bible.stats()
                    cats = []
                    # Use short labels to fit in the panel width
                    stat_map = [
                        ("chars", "characters"),
                        ("weapons", "weapons_artifacts"),
                        ("orgs", "organizations"),
                        ("cultural", "cultural_terms"),
                        ("myth", "mythology"),
                    ]
                    for short_name, stat_key in stat_map:
                        count = stats.get(stat_key, 0)
                        if isinstance(count, int) and count > 0:
                            cats.append(f"{short_name}={count}")
                    # Geography is nested dict: {countries: N, regions: N, cities: N}
                    geo_stats = stats.get("geography", {})
                    if isinstance(geo_stats, dict):
                        geo_total = sum(v for v in geo_stats.values() if isinstance(v, int))
                        if geo_total > 0:
                            cats.append(f"geo={geo_total}")
                    elif isinstance(geo_stats, int) and geo_stats > 0:
                        cats.append(f"geo={geo_stats}")
                    bible_categories = ", ".join(cats)
                    bible_status = f"LOADED ({bible_entries} entries)"
                else:
                    bible_status = f"DECLARED but NOT FOUND: {bible_id}"
            except Exception:
                bible_status = f"DECLARED: {bible_id} (load error)"

        # Bible sync result (check if pull was done)
        bible_sync_status = "—"
        if bible_id:
            try:
                from pipeline.metadata_processor.bible_sync import BibleSyncAgent
                sync = BibleSyncAgent(self.work_dir / volume_id, PROJECT_ROOT)
                resolved = sync.resolve(manifest)
                if resolved:
                    pull = sync.pull(manifest)
                    if pull:
                        inherited = getattr(pull, "total_inherited", 0)
                        known_chars = len(getattr(pull, "known_characters", {}))
                        bible_sync_status = f"PULL OK: {inherited} terms, {known_chars} known chars"
                    else:
                        bible_sync_status = "PULL returned empty"
                else:
                    bible_sync_status = "resolve() failed — bible not found"
            except Exception:
                bible_sync_status = "PULL not available"

        logger.info("")
        logger.info("┌─────────────────────────────────────────────────────────────┐")
        logger.info("│  SECTION 3 CONFIRMATION — Metadata Processor                 │")
        logger.info("├─────────────────────────────────────────────────────────────┤")
        logger.info(f"│  Title ({target_lang.upper()}):  {title_en[:48]:<48} │")
        logger.info(f"│  Series ({target_lang.upper()}): {series_en[:48]:<48} │")
        logger.info(f"│  Author ({target_lang.upper()}): {author_en[:48]:<48} │")
        logger.info("├─────────────────────────────────────────────────────────────┤")
        logger.info(f"│  Character Names:   {len(char_names):<5}  (JP → {target_lang.upper()} pairs)               │")
        logger.info(f"│  Character Profiles:{len(char_profiles):<5}  (rich profiles)                  │")
        logger.info(f"│  Glossary Terms:    {len(glossary):<5}                                    │")
        logger.info(f"│  Chapter Titles:    {translated_titles:<5}  translated                       │")
        logger.info("├─────────────────────────────────────────────────────────────┤")
        logger.info(f"│  📖 Bible: {bible_status[:50]:<50}│")
        if bible_categories:
            cat_str = bible_categories[:56]
            if len(bible_categories) > 56:
                cat_str = bible_categories[:53] + "..."
            logger.info(f"│     {cat_str:<56}│")
        logger.info(f"│     Sync: {bible_sync_status[:50]:<50}│")
        logger.info("└─────────────────────────────────────────────────────────────┘")

        # Show top character name samples
        if char_names and len(char_names) > 0:
            logger.info("  Sample character names:")
            for jp, en in list(char_names.items())[:5]:
                logger.info(f"    {jp} → {en}")
            if len(char_names) > 5:
                logger.info(f"    ... and {len(char_names) - 5} more")

    def _log_phase1_55_confirmation(self, volume_id: str) -> None:
        """Log verbose confirmation for Section 6 rich metadata cache results."""
        manifest = self.load_manifest(volume_id)
        if not manifest:
            return

        from pipeline.config import get_target_language
        target_lang = get_target_language()
        meta_key = f"metadata_{target_lang}"
        metadata = manifest.get(meta_key, {})
        if not metadata and target_lang == "en":
            metadata = manifest.get("metadata_en", {})

        state = manifest.get("pipeline_state", {}).get("rich_metadata_cache", {})
        status = state.get("status", "not started")
        cache_stats = state.get("cache_stats", {}) if isinstance(state, dict) else {}
        cached = int(cache_stats.get("cached_chapters", 0))
        total = int(cache_stats.get("target_chapters", 0))
        cache_used = bool(state.get("used_external_cache", False)) if isinstance(state, dict) else False
        patch_keys = state.get("patch_keys", []) if isinstance(state, dict) else []
        context_processors = state.get("context_processors", {}) if isinstance(state, dict) else {}
        processor_map = context_processors.get("processors", {}) if isinstance(context_processors, dict) else {}

        profiles = metadata.get("character_profiles", {})
        dialogue_patterns = metadata.get("dialogue_patterns", {})
        scene_contexts = metadata.get("scene_contexts", {})
        guidelines = metadata.get("translation_guidelines", {})

        logger.info("")
        logger.info("┌─────────────────────────────────────────────────────────────┐")
        logger.info("│  SECTION 6 CONFIRMATION — Rich Metadata Cache               │")
        logger.info("├─────────────────────────────────────────────────────────────┤")
        logger.info(f"│  Status:            {status[:46]:<46}│")
        logger.info(f"│  Model:             gemini-2.5-flash (temp=0.5)            │")
        logger.info(f"│  Full-LN Cache:     {'USED' if cache_used else 'FALLBACK':<46}│")
        logger.info(f"│  Cache Coverage:    {cached}/{total} JP chapters                          │")
        logger.info("├─────────────────────────────────────────────────────────────┤")
        logger.info(f"│  Character Profiles:{len(profiles):<5}  (rich profiles)                  │")
        logger.info(f"│  Dialogue Patterns: {len(dialogue_patterns):<5}                                    │")
        logger.info(f"│  Scene Contexts:    {len(scene_contexts):<5}                                    │")
        logger.info(f"│  Guidelines:        {len(guidelines):<5}                                    │")
        if processor_map:
            char_items = int(processor_map.get("character_context", {}).get("items", 0))
            cultural_items = int(processor_map.get("cultural_context", {}).get("items", 0))
            temporal_items = int(processor_map.get("temporal_context", {}).get("items", 0))
            idiom_items = int(processor_map.get("idiom_transcreation", {}).get("items", 0))
            logger.info("├─────────────────────────────────────────────────────────────┤")
            logger.info(f"│  P1 Character Ctx:  {char_items:<5}                                    │")
            logger.info(f"│  P2 Cultural Ctx:   {cultural_items:<5}                                    │")
            logger.info(f"│  P3 Temporal Ctx:   {temporal_items:<5}                                    │")
            logger.info(f"│  P4 Idiom Cache:    {idiom_items:<5}                                    │")
        logger.info("└─────────────────────────────────────────────────────────────┘")

        if patch_keys:
            shown = ", ".join(str(k) for k in patch_keys[:8])
            if len(patch_keys) > 8:
                shown += f", ... (+{len(patch_keys) - 8})"
            logger.info(f"  Patch keys: {shown}")

    def _log_phase1_6_confirmation(self, volume_id: str) -> None:
        """Log verbose confirmation for Section 8 (Multimodal) results."""
        manifest = self.load_manifest(volume_id)
        if not manifest:
            return

        vol_path = self.work_dir / volume_id

        # Visual cache
        cache_path = vol_path / "visual_cache.json"
        cache_total = 0
        cached_ok = 0
        safety_blocked = 0
        manual_override = 0
        has_ground_truth = 0
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                cache_total = len(cache)
                for entry in cache.values():
                    status = entry.get("status", "")
                    if status == "cached":
                        cached_ok += 1
                    elif status == "safety_blocked":
                        safety_blocked += 1
                    elif status == "manual_override":
                        manual_override += 1
                    vgt = entry.get("visual_ground_truth", {})
                    if vgt and vgt.get("composition"):
                        has_ground_truth += 1
            except Exception:
                pass

        # Multimodal manifest block
        mm = manifest.get("multimodal", {})
        vision_model = mm.get("models", {}).get("vision", "N/A")
        epub_map = mm.get("epub_id_to_cache_id", {})
        illust_count = mm.get("illustration_count", 0)

        # Canon Name Enforcer readiness
        canon_status = "—"
        canon_count = 0
        nickname_count = 0
        try:
            sys.path.insert(0, str(PROJECT_ROOT))
            from modules.multimodal.prompt_injector import CanonNameEnforcer
            enforcer = CanonNameEnforcer(manifest=manifest)
            canon_count = len(enforcer.canon_map)
            nickname_count = len(enforcer.nickname_map)
            canon_status = f"{canon_count} canon, {nickname_count} nicknames"
        except Exception:
            canon_status = "NOT AVAILABLE"

        # Bible connection for visual context enrichment
        bible_id = manifest.get("bible_id", None)
        bible_flat_count = 0
        if bible_id:
            try:
                from pipeline.translator.series_bible import BibleController
                bc = BibleController(PROJECT_ROOT)
                bible = bc.load(manifest)
                if bible:
                    bible_flat_count = len(bible.flat_glossary())
            except Exception:
                pass

        logger.info("")
        logger.info("┌─────────────────────────────────────────────────────────────┐")
        logger.info("│  SECTION 8 CONFIRMATION — Art Director (Multimodal)          │")
        logger.info("├─────────────────────────────────────────────────────────────┤")
        logger.info(f"│  Vision Model:      {vision_model[:40]:<40} │")
        logger.info(f"│  Illustrations:     {illust_count:<5}  total in volume                  │")
        logger.info(f"│  EPUB→Cache Map:    {len(epub_map):<5}  kuchie/embed mappings             │")
        logger.info("├─────────────────────────────────────────────────────────────┤")
        logger.info(f"│  Cache Total:       {cache_total:<5}                                    │")
        logger.info(f"│  ✓ Analyzed:        {cached_ok:<5}                                    │")
        logger.info(f"│  ✗ Safety Blocked:  {safety_blocked:<5}                                    │")
        logger.info(f"│  ⚙ Manual Override: {manual_override:<5}                                    │")
        logger.info(f"│  Ground Truth:      {has_ground_truth:<5}  (composition + directives)       │")
        logger.info("├─────────────────────────────────────────────────────────────┤")
        logger.info(f"│  Canon Names:       {canon_status:<40} │")
        if bible_flat_count > 0:
            logger.info(f"│  Bible Glossary:    {bible_flat_count:<5}  terms for GlossaryLock            │")
        logger.info("└─────────────────────────────────────────────────────────────┘")

    def _log_phase1_7_confirmation(self, volume_id: str) -> None:
        """Log verbose confirmation for Section 9 (Scene Planner) results."""
        manifest = self.load_manifest(volume_id)
        if not manifest:
            return

        planner_state = manifest.get("pipeline_state", {}).get("scene_planner", {})
        plans_dir = self.work_dir / volume_id / "PLANS"
        plan_files = list(plans_dir.glob("*_scene_plan.json")) if plans_dir.exists() else []

        generated = int(planner_state.get("generated_plans", 0))
        skipped = int(planner_state.get("skipped_plans", 0))
        failed = int(planner_state.get("failed_plans", 0))
        selected = int(planner_state.get("total_selected", len(plan_files)))
        model = str(planner_state.get("model", "N/A"))
        status = str(planner_state.get("status", "not started"))

        logger.info("")
        logger.info("┌─────────────────────────────────────────────────────────────┐")
        logger.info("│  SECTION 9 CONFIRMATION — Stage 1 Scene Planner              │")
        logger.info("├─────────────────────────────────────────────────────────────┤")
        logger.info(f"│  Status:            {status[:46]:<46}│")
        logger.info(f"│  Model:             {model[:46]:<46}│")
        logger.info(f"│  Plan Files:        {len(plan_files):<5}                                    │")
        logger.info("├─────────────────────────────────────────────────────────────┤")
        logger.info(f"│  Selected:          {selected:<5}                                    │")
        logger.info(f"│  Generated:         {generated:<5}                                    │")
        logger.info(f"│  Skipped:           {skipped:<5}                                    │")
        logger.info(f"│  Failed:            {failed:<5}                                    │")
        logger.info("└─────────────────────────────────────────────────────────────┘")

    def _run_command(self, cmd: list, description: str) -> bool:
        """Run a command with verbosity control."""
        if self.verbose:
            try:
                subprocess.run(
                    cmd,
                    check=True,
                    capture_output=False,
                    env=self._get_env()
                )
                return True
            except subprocess.CalledProcessError as e:
                logger.error(f"✗ {description} failed: {e}")
                return False

        if self.ui.rich_enabled:
            started = time.monotonic()
            try:
                with self.ui.command_status(f"Running {description}"):
                    subprocess.run(
                        cmd,
                        check=True,
                        capture_output=True,
                        env=self._get_env()
                    )
                elapsed = time.monotonic() - started
                self.ui.print_success(f"{description} completed ({elapsed:.1f}s)")
                return True
            except subprocess.CalledProcessError as e:
                elapsed = time.monotonic() - started
                self.ui.print_error(f"{description} failed ({elapsed:.1f}s)")
                if e.stdout:
                    print("\n--- STDOUT ---\n" + e.stdout.decode())
                if e.stderr:
                    print("\n--- STDERR ---\n" + e.stderr.decode())
                return False

        print(f"⏳ Running {description}...", end="", flush=True)
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                env=self._get_env()
            )
            print(f"\r✅ {description} Completed    ")
            return True
        except subprocess.CalledProcessError as e:
            print(f"\r✗ {description} Failed        ")
            if e.stdout:
                print("\n--- STDOUT ---\n" + e.stdout.decode())
            if e.stderr:
                print("\n--- STDERR ---\n" + e.stderr.decode())
            return False

    def _run_phase2_command_with_progress(self, cmd: list, expected_total: int = 1) -> bool:
        """Run translator command with live chapter progress in rich mode."""
        if self.verbose or not self.ui.rich_enabled:
            return self._run_command(cmd, "Section 10 (Translator)")

        target_re = re.compile(r"Targeting\s+(\d+)\s+chapters")
        start_re = re.compile(r"Translating\s+\[(\d+)/(\d+)\]\s+(\S+)\s+to")
        complete_re = re.compile(r"Completed\s+([^.\s]+)\.")
        failed_re = re.compile(r"Failed\s+([^:\s]+):")
        skip_re = re.compile(r"Skipping completed chapter\s+(\S+)")

        seen_terminal = set()
        line_tail: deque[str] = deque(maxlen=60)
        started = time.monotonic()

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=self._get_env(),
        )

        with self.ui.chapter_progress("Section 10 Chapters", total=max(expected_total, 1)) as tracker:
            for raw_line in iter(process.stdout.readline, ''):
                line = raw_line.rstrip("\n")
                if not line:
                    continue
                line_tail.append(line)

                target_match = target_re.search(line)
                if target_match:
                    tracker.set_total(int(target_match.group(1)))

                start_match = start_re.search(line)
                if start_match:
                    index = int(start_match.group(1))
                    total = int(start_match.group(2))
                    chapter_id = start_match.group(3)
                    tracker.set_total(total)
                    tracker.start(chapter_id, index=index, total=total)

                complete_match = complete_re.search(line)
                if complete_match:
                    chapter_id = complete_match.group(1)
                    if chapter_id not in seen_terminal:
                        tracker.complete(chapter_id)
                        seen_terminal.add(chapter_id)

                failed_match = failed_re.search(line)
                if failed_match:
                    chapter_id = failed_match.group(1)
                    if chapter_id not in seen_terminal:
                        tracker.fail(chapter_id)
                        seen_terminal.add(chapter_id)

                skip_match = skip_re.search(line)
                if skip_match:
                    chapter_id = skip_match.group(1)
                    if chapter_id not in seen_terminal:
                        tracker.skip(chapter_id)
                        seen_terminal.add(chapter_id)

                if "[ERROR]" in line or "Volume translation" in line or "[BATCH][COST]" in line:
                    logger.info(line)

            process.stdout.close()
            return_code = process.wait()

        elapsed = time.monotonic() - started
        if return_code == 0:
            self.ui.print_success(f"Section 10 (Translator) completed ({elapsed:.1f}s)")
            return True

        self.ui.print_error(f"Section 10 (Translator) failed ({elapsed:.1f}s)")
        if line_tail:
            logger.error("Last translator output lines:")
            for tail_line in list(line_tail)[-20:]:
                logger.error(tail_line)
        return False

    def _get_env(self) -> Dict[str, str]:
        """Get environment with updated PYTHONPATH."""
        env = os.environ.copy()
        # Add project root to PYTHONPATH to ensure 'pipeline' module is found
        pythonpath = env.get("PYTHONPATH", "")
        project_root_str = str(PROJECT_ROOT)
        
        # Check if PROJECT_ROOT is already in PYTHONPATH to avoid duplicates
        if pythonpath:
            paths = pythonpath.split(os.pathsep)
            if project_root_str not in paths:
                env["PYTHONPATH"] = f"{project_root_str}{os.pathsep}{pythonpath}"
        else:
            env["PYTHONPATH"] = project_root_str
        
        if self.verbose:
            logger.info(f"[DEBUG] PROJECT_ROOT: {PROJECT_ROOT}")
            logger.info(f"[DEBUG] Updated PYTHONPATH: {env['PYTHONPATH']}")
        return env
    
    
    def list_volumes_with_manifest(self) -> list:
        """Get list of all volumes with manifest.json."""
        volumes = []
        work_path = self.work_dir
        if not work_path.exists():
            return volumes
        
        for path in work_path.iterdir():
            if not path.is_dir():
                continue
            
            manifest_path = path / "manifest.json"
            if manifest_path.exists():
                try:
                    with open(manifest_path, 'r', encoding='utf-8') as f:
                        manifest = json.load(f)
                    
                    title = manifest.get('metadata', {}).get('title', path.name)
                    status = manifest.get('pipeline_state', {})
                    
                    volumes.append({
                        'id': path.name,
                        'title': title,
                        'status': status
                    })
                except:
                    # Skip invalid manifests
                    continue
        
        # Sort by modification time (newest first)
        volumes.sort(key=lambda x: (self.work_dir / x['id']).stat().st_mtime, reverse=True)
        return volumes
    
    def interactive_volume_selection(self, candidates: list = None, phase_name: str = "Section") -> Optional[str]:
        """
        Interactive menu to select a volume.
        
        Args:
            candidates: List of volume IDs to choose from (None = all volumes with manifest)
            phase_name: Name of the section for display
            
        Returns:
            Selected volume ID or None if cancelled
        """
        # Get volumes to display
        if candidates:
            # Filter to candidates only
            all_volumes = self.list_volumes_with_manifest()
            volumes = [v for v in all_volumes if v['id'] in candidates]
        else:
            # Show all volumes with manifest
            volumes = self.list_volumes_with_manifest()
        
        if not volumes:
            logger.error("No volumes found with manifest.json")
            return None

        rows = []
        for i, vol in enumerate(volumes, 1):
            title = vol['title'][:55] + "..." if len(vol['title']) > 58 else vol['title']
            vol_key = self._short_volume_id(vol['id'])
            status = vol['status']

            p1 = self._status_badge(status.get('librarian', {}).get('status', ''))
            p15 = self._status_badge(status.get('metadata_processor', {}).get('status', ''))
            p155 = self._status_badge(status.get('rich_metadata_cache', {}).get('status', ''))
            p16 = self._visual_phase_badge(vol['id'])
            p2 = self._status_badge(status.get('translator', {}).get('status', ''))
            p4 = self._status_badge(status.get('builder', {}).get('status', ''))

            rows.append({
                "index": i,
                "p1": p1,
                "p15": p15,
                "p155": p155,
                "p16": p16,
                "p2": p2,
                "p4": p4,
                "id_key": vol_key,
                "title": title,
            })

        if self.ui.rich_enabled:
            rich_rows = []
            for row in rows:
                stage_summary = " ".join([
                    self.ui.format_compact_badge(row["p1"]),
                    self.ui.format_compact_badge(row["p15"]),
                    self.ui.format_compact_badge(row["p155"]),
                    self.ui.format_compact_badge(row["p16"]),
                    self.ui.format_compact_badge(row["p2"]),
                    self.ui.format_compact_badge(row["p4"]),
                ])
                rich_rows.append([
                    str(row["index"]),
                    stage_summary,
                    row["id_key"],
                    row["title"],
                ])
            self.ui.render_table(
                title=f"Select Volume for {phase_name}",
                columns=[
                    {"header": "#", "justify": "right", "style": "bold"},
                    {"header": "Stages (P1/P1.5/P1.55/P1.6/P2/P4)", "no_wrap": True},
                    {"header": "ID Key", "style": "cyan", "no_wrap": True},
                    {"header": "Title", "no_wrap": True, "overflow": "ellipsis", "max_width": 56},
                ],
                rows=rich_rows,
                caption="0 = Cancel",
            )
        else:
            print("\n" + "=" * 118)
            print(f"MTL Studio v5.2 | Select Volume for {phase_name}")
            print("=" * 118)
            print(" #  P1   P1.5  P1.55 P1.6     P2    P4    ID key          Title")
            print("-" * 118)
            for row in rows:
                print(
                    f"{row['index']:>2}  {row['p1']:<4} {row['p15']:<5} {row['p155']:<5} {row['p16']:<8} "
                    f"{row['p2']:<5} {row['p4']:<5} {row['id_key']:<14} {row['title']}"
                )
            print("-" * 118)
            print(" 0  Cancel")
            print("=" * 118)
        
        while True:
            try:
                choice = input("Select volume (0 to cancel): ").strip()
                if not choice:
                    continue
                
                idx = int(choice)
                if idx == 0:
                    logger.info("Selection cancelled")
                    return None
                
                if 1 <= idx <= len(volumes):
                    selected = volumes[idx - 1]['id']
                    logger.info(f"Selected volume: {volumes[idx - 1]['title']}")
                    return selected
                else:
                    print(f"Invalid choice. Please enter 0-{len(volumes)}")
            except ValueError:
                print("Please enter a number")
            except (KeyboardInterrupt, EOFError):
                logger.info("\nSelection cancelled")
                return None
    
    def resolve_volume_id(self, partial_id: str, allow_interactive: bool = False, phase_name: str = "Section") -> Optional[str]:
        """
        Smartly resolve a partial volume ID to the full directory name.
        Strategies:
        1. Exact match.
        2. Matches suffix (timestamp IDs).
        3. Fuzzy/Prefix match.
        4. Interactive selection if ambiguous or requested.
        
        Args:
            partial_id: Partial or full volume ID
            allow_interactive: If True, offer interactive selection on ambiguity
            phase_name: Name of the section for display in interactive mode
        """
        if not partial_id:
            # No ID provided - offer interactive selection
            if allow_interactive:
                return self.interactive_volume_selection(phase_name=phase_name)
            return None
            
        work_path = self.work_dir
        if not work_path.exists():
            return partial_id 
            
        # 1. Exact Match
        if (work_path / partial_id).exists():
            return partial_id
            
        candidates = []
        for path in work_path.iterdir():
            if not path.is_dir():
                continue
            
            name = path.name
            # 2. Suffix Match (e.g. valid timestamps)
            if name.endswith(partial_id):
                candidates.append(name)
            # 3. Partial inclusion
            elif partial_id in name:
                # Check directly or check parts
                candidates.append(name)
        
        if len(candidates) == 1:
            resolved = candidates[0]
            if self.verbose:
                logger.info(f"✨ Resolved Volume ID: '{partial_id}' -> '{resolved}'")
            return resolved
        elif len(candidates) > 1:
            # Prefer suffix match
            suffix_matches = [c for c in candidates if c.endswith(partial_id)]
            if len(suffix_matches) == 1:
                 resolved = suffix_matches[0]
                 if self.verbose:
                    logger.info(f"✨ Resolved Volume ID (Suffix): '{resolved}'")
                 return resolved
            
            # Multiple matches - offer interactive selection if allowed
            if allow_interactive:
                logger.warning(f"⚠️ Ambiguous Volume ID '{partial_id}'. Found {len(candidates)} matches.")
                return self.interactive_volume_selection(candidates=candidates, phase_name=phase_name)
            else:
                logger.warning(f"⚠️ Ambiguous Volume ID '{partial_id}'. Matches: {candidates}")
                return None 
            
        # No matches - offer interactive selection if allowed
        if allow_interactive:
            logger.warning(f"⚠️ Volume ID '{partial_id}' not found.")
            print("\nWould you like to select from available volumes?")
            choice = input("  [1] Yes, show me the list\n  [2] No, cancel\nChoice: ").strip()
            if choice == "1":
                return self.interactive_volume_selection(phase_name=phase_name)
        
        return None

    def generate_volume_id(self, epub_path: Path) -> str:
        """Generate a volume ID from EPUB filename."""
        # Remove .epub extension and sanitize
        base_name = epub_path.stem
        # Add timestamp for uniqueness
        timestamp = datetime.now().strftime("%Y%m%d")
        # Create ID: filename_YYYYMMDD_hash
        volume_id = f"{base_name}_{timestamp}_{hash(str(epub_path)) % 10000:04x}"
        return volume_id
    
    def get_manifest_path(self, volume_id: str) -> Path:
        """Get path to manifest.json for a volume."""
        return self.work_dir / volume_id / "manifest.json"
    
    def load_manifest(self, volume_id: str) -> Optional[Dict[str, Any]]:
        """Load manifest.json for a volume."""
        manifest_path = self.get_manifest_path(volume_id)
        if not manifest_path.exists():
            return None
        
        with open(manifest_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _get_manifest_chapters(self, manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return manifest chapter list from root or legacy structure block."""
        chapters = manifest.get("chapters", [])
        if not chapters:
            chapters = manifest.get("structure", {}).get("chapters", [])
        return chapters if isinstance(chapters, list) else []

    def _missing_scene_plan_chapter_ids(
        self,
        volume_id: str,
        target_chapters: List[Dict[str, Any]],
    ) -> List[str]:
        """
        Return chapter IDs that do not have a usable Stage 1.7 scene plan reference.

        A chapter is considered missing when:
          - scene_plan_file is absent/empty, or
          - referenced plan file does not exist on disk.
        """
        work_volume_dir = self.work_dir / volume_id
        missing: List[str] = []

        for chapter in target_chapters:
            if not isinstance(chapter, dict):
                continue

            chapter_id = str(chapter.get("id", "")).strip()
            if not chapter_id:
                continue

            scene_plan_ref = chapter.get("scene_plan_file")
            if not isinstance(scene_plan_ref, str) or not scene_plan_ref.strip():
                missing.append(chapter_id)
                continue

            scene_plan_path = Path(scene_plan_ref.strip())
            if not scene_plan_path.is_absolute():
                scene_plan_path = work_volume_dir / scene_plan_path

            if not scene_plan_path.exists():
                missing.append(chapter_id)

        return missing

    def _check_full_ln_cache_state(self, manifest: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate Section 6 full-LN cache readiness from manifest pipeline state.

        Returns:
            Dict with keys:
              - ready (bool)
              - reason (str)
              - cached (int)
              - expected (int)
        """
        pipeline_state = manifest.get("pipeline_state", {})
        rich_state = pipeline_state.get("rich_metadata_cache", {})
        if not isinstance(rich_state, dict):
            return {"ready": False, "reason": "missing_state", "cached": 0, "expected": 0}

        status = str(rich_state.get("status", "not run")).lower()
        used_external_cache = bool(rich_state.get("used_external_cache", False))
        cache_stats = rich_state.get("cache_stats", {})
        if not isinstance(cache_stats, dict):
            cache_stats = {}

        expected = len(self._get_manifest_chapters(manifest))
        cached = int(cache_stats.get("cached_chapters", 0) or 0)
        target = int(cache_stats.get("target_chapters", 0) or 0)

        # Prefer chapter count from manifest; fallback to recorded target.
        expected_total = expected if expected > 0 else target

        if status != "completed":
            return {
                "ready": False,
                "reason": f"status_{status or 'unknown'}",
                "cached": cached,
                "expected": expected_total,
            }
        if not used_external_cache:
            return {
                "ready": False,
                "reason": "external_cache_not_used",
                "cached": cached,
                "expected": expected_total,
            }
        if expected_total > 0 and cached < expected_total:
            return {
                "ready": False,
                "reason": "incomplete_coverage",
                "cached": cached,
                "expected": expected_total,
            }
        if cached <= 0:
            return {
                "ready": False,
                "reason": "empty_cache_payload",
                "cached": cached,
                "expected": expected_total,
            }

        return {
            "ready": True,
            "reason": "ready",
            "cached": cached,
            "expected": expected_total,
        }

    def ensure_full_ln_cache(
        self,
        volume_id: str,
        *,
        for_phase: str,
        manifest: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Ensure Section 6 full-LN cache exists for downstream sections.

        Auto-runs Section 6 when cache is missing/incomplete.
        """
        manifest_data = manifest if manifest is not None else self.load_manifest(volume_id)
        if not manifest_data:
            logger.error(f"No manifest.json found for volume: {volume_id}")
            logger.error("  Please run Section 1 first to extract the EPUB")
            return False

        cache_state = self._check_full_ln_cache_state(manifest_data)
        if cache_state["ready"]:
            logger.info(
                f"Full-LN cache ready for {for_phase}: "
                f"{cache_state['cached']}/{cache_state['expected']} JP chapters cached."
            )
            return True

        logger.warning(
            f"Full-LN cache missing for {for_phase} "
            f"(reason={cache_state['reason']}, "
            f"coverage={cache_state['cached']}/{cache_state['expected']})."
        )
        logger.info("Auto-running Section 6 to build/update full-LN cache...")

        if not self.run_phase1_55(volume_id):
            logger.error(f"Section 6 failed; cannot continue {for_phase}.")
            return False

        refreshed_manifest = self.load_manifest(volume_id)
        if not refreshed_manifest:
            logger.error("Manifest reload failed after Section 6.")
            return False

        refreshed_state = self._check_full_ln_cache_state(refreshed_manifest)
        if not refreshed_state["ready"]:
            logger.error(
                "Full-LN cache validation still failed after Section 6 "
                f"(reason={refreshed_state['reason']}, "
                f"coverage={refreshed_state['cached']}/{refreshed_state['expected']})."
            )
            return False

        logger.info(
            f"Full-LN cache prepared for {for_phase}: "
            f"{refreshed_state['cached']}/{refreshed_state['expected']} JP chapters cached."
        )
        return True
    
    def get_pipeline_status(self, volume_id: str) -> Dict[str, str]:
        """Get status of all pipeline sections."""
        manifest = self.load_manifest(volume_id)
        if not manifest:
            return {}
        
        return manifest.get('pipeline_state', {})
    
    def run_phase1(self, epub_path: Path, volume_id: str, ref_validate: bool = False) -> bool:
        """Run Section 1: Librarian (EPUB Extraction)."""
        from pipeline.config import get_target_language

        self._ui_header("Section 1 - Librarian", "Extract EPUB, chapters, assets, and manifest state")

        # Get target language from config
        target_lang = get_target_language()

        cmd = [
            sys.executable, "-m", "pipeline.librarian.agent",
            str(epub_path),
            "--work-dir", str(self.work_dir),
            "--target-lang", target_lang
        ]

        # Only add volume-id if provided
        if volume_id:
            cmd.extend(["--volume-id", volume_id])

        if ref_validate:
            cmd.append("--ref-validate")
        
        logger.info(f"Target Language: {target_lang.upper()}")
        
        if self._run_command(cmd, "Section 1 (Librarian)"):
            logger.info("✓ Section 1 completed successfully")
            self._log_phase1_confirmation(volume_id)
            return True
        return False
    
    def run_phase1_5(self, volume_id: str) -> bool:
        """Run Section 3: Metadata Processor (Schema autoupdate + metadata translation).
        
        Runs schema autoupdate then translates metadata fields while PRESERVING v3 enhanced schema:
        - Updates: title_en, author_en, chapter titles, character_names
        - Preserves: character_profiles, localization_notes, keigo_switch configs
        """
        self._ui_header(
            "Section 3 - Metadata Processor",
            "Schema autoupdate + metadata translation with schema-safe preservation",
        )
        
        # Check for potential sequels before running
        ignore_sequel = False
        current_manifest = self.load_manifest(volume_id)
        if current_manifest:
            current_title = current_manifest.get("metadata", {}).get("title", "")
            
            # Simple scan for predecessors
            parent_candidate = None
            for vol_dir in self.work_dir.iterdir():
                if not vol_dir.is_dir() or vol_dir.name == volume_id:
                    continue
                
                # Check match
                try:
                     m_path = vol_dir / "manifest.json"
                     if m_path.exists():
                         with open(m_path, 'r') as f:
                             other_m = json.load(f)
                         other_title = other_m.get("metadata", {}).get("title", "")
                         if current_title and other_title and current_title[:10] == other_title[:10]:
                             parent_candidate = other_m.get("metadata_en", {}).get("title_en", other_title)
                             break
                except:
                    continue
            
            if parent_candidate:
                if self.verbose:
                    # Interactive mode - ask user about sequel workflow
                    print(f"\n{'='*70}")
                    print(f"🔗 SEQUEL VOLUME DETECTED")
                    print(f"{'='*70}")
                    print(f"   Prequel: '{parent_candidate}'")
                    print(f"   Current: '{current_title}'")
                    print()
                    print("   SEQUEL MODE enables maximum continuity and API cost savings:")
                    print("   ✓ Copy metadata_en.json directly from prequel")
                    print("   ✓ Skip character name extraction (inherit from prequel)")
                    print("   ✓ Inherit title/author (only update volume number)")
                    print("   ✓ Only translate NEW chapter titles")
                    print("   ✓ Preserve character profiles and localization settings")
                    print()
                    print("   [Y] Yes - Enable SEQUEL MODE (Recommended)")
                    print("   [N] No  - Generate fresh metadata (Independent volume)")
                    print()
                    choice = input("   Select [Y/n]: ").strip().lower()

                    if choice == 'n':
                        ignore_sequel = True
                        logger.info("User selected FRESH metadata generation (independent volume).")
                    else:
                        logger.info("User selected SEQUEL MODE (metadata inheritance).")
                        print()
                        print("   ⚠️  IMPORTANT: Update your character database before Section 10")
                        print(f"   • Review character_names in: {volume_id}/metadata_en.json")
                        print(f"   • Add any new characters to your reference database")
                        print(f"   • Update character relationships/profiles if needed")
                        print()
                        input("   Press Enter to continue to metadata processing...")
                else:
                    # Minimal mode - auto-inherit (recommended default)
                    logger.info(f"✨ Sequel detected, enabling SEQUEL MODE")
                    logger.info(f"   Inheriting from: {parent_candidate}")
                    logger.warning("⚠️  Remember to update character database before Section 10")
                    ignore_sequel = False

        cmd = [
            sys.executable, "-m", "pipeline.metadata_processor.agent",
            "--volume", volume_id
        ]

        if ignore_sequel:
            cmd.append("--ignore-sequel")
        else:
            # Enable sequel mode (direct metadata copy, skip name extraction)
            if parent_candidate and not ignore_sequel:
                cmd.append("--sequel-mode")
        
        if self._run_command(cmd, "Section 3 (Metadata)"):
            logger.info("✓ Section 3 completed successfully")
            self._log_phase1_5_confirmation(volume_id)
            return True
        return False

    def run_phase1_51(self, volume_id: str) -> bool:
        """Run Section 3.1: Koji Fox Voice RAG backfill only."""
        self._ui_header(
            "Section 3.1 - Voice RAG Backfill",
            "Backfill character_voice_fingerprints + scene_intent_map only",
        )

        manifest = self.load_manifest(volume_id)
        if not manifest:
            logger.error(f"No manifest.json found for volume: {volume_id}")
            logger.error("  Please run Section 1 and Section 3 first")
            return False

        cmd = [
            sys.executable,
            "-m",
            "pipeline.metadata_processor.agent",
            "--volume",
            volume_id,
            "--voice-rag-only",
        ]

        if self._run_command(cmd, "Section 3.1 (Voice RAG)"):
            logger.info("✓ Section 3.1 completed successfully")
            return True
        return False

    def run_phase1_52(self, volume_id: str) -> bool:
        """Run Section 3.2: EPS backfill only."""
        self._ui_header(
            "Section 3.2 - EPS Backfill",
            "Backfill chapter emotional_proximity_signals + scene_intents only",
        )

        manifest = self.load_manifest(volume_id)
        if not manifest:
            logger.error(f"No manifest.json found for volume: {volume_id}")
            logger.error("  Please run Section 1 and Section 3 first")
            return False

        cmd = [
            sys.executable,
            "-m",
            "pipeline.metadata_processor.agent",
            "--volume",
            volume_id,
            "--eps-only",
        ]

        if self._run_command(cmd, "Section 3.2 (EPS Backfill)"):
            logger.info("✓ Section 3.2 completed successfully")
            return True
        return False

    @staticmethod
    def _normalize_target_language_code(value: Optional[str]) -> str:
        raw = str(value or "").strip().lower()
        if raw in {"vi", "vietnamese"}:
            return "vn"
        if raw in {"en", "english"}:
            return "en"
        return raw if raw in {"en", "vn"} else "en"

    @staticmethod
    def _normalize_chapter_key_for_pronoun_shift(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        match = re.search(r"chapter[_\-\s]*0*(\d+)", raw, re.IGNORECASE)
        if not match:
            match = re.search(r"\bch[_\-\s]*0*(\d+)\b", raw, re.IGNORECASE)
        if not match:
            match = re.search(r"\b0*(\d{1,3})\b", raw)
        if not match:
            return ""
        return f"chapter_{int(match.group(1)):02d}"

    def _load_scene_plan_index_for_pronoun_shift(
        self,
        volume_path: Path,
        manifest: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        index: Dict[str, Dict[str, Any]] = {}

        chapters = manifest.get("chapters", [])
        if isinstance(chapters, list):
            for chapter in chapters:
                if not isinstance(chapter, dict):
                    continue
                chapter_key = self._normalize_chapter_key_for_pronoun_shift(chapter.get("id"))
                scene_ref = chapter.get("scene_plan_file")
                if not chapter_key or not isinstance(scene_ref, str) or not scene_ref.strip():
                    continue
                scene_path = Path(scene_ref)
                if not scene_path.is_absolute():
                    scene_path = volume_path / scene_path
                if not scene_path.exists():
                    continue
                try:
                    payload = json.loads(scene_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                scenes = payload.get("scenes", [])
                if not isinstance(scenes, list):
                    scenes = []
                index[chapter_key] = {
                    "chapter_id": chapter_key,
                    "scenes": [scene for scene in scenes if isinstance(scene, dict)],
                }

        plans_dir = volume_path / "PLANS"
        if plans_dir.exists():
            for scene_path in sorted(plans_dir.glob("*_scene_plan.json")):
                try:
                    payload = json.loads(scene_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                chapter_key = self._normalize_chapter_key_for_pronoun_shift(payload.get("chapter_id") or scene_path.stem)
                if not chapter_key or chapter_key in index:
                    continue
                scenes = payload.get("scenes", [])
                if not isinstance(scenes, list):
                    scenes = []
                index[chapter_key] = {
                    "chapter_id": chapter_key,
                    "scenes": [scene for scene in scenes if isinstance(scene, dict)],
                }
        return index

    @staticmethod
    def _infer_scene_for_pronoun_shift(
        chapter_key: str,
        line_number: int,
        scene_plan_index: Dict[str, Dict[str, Any]],
    ) -> str:
        plan = scene_plan_index.get(chapter_key, {})
        scenes = plan.get("scenes", []) if isinstance(plan, dict) else []
        if isinstance(scenes, list):
            for scene in scenes:
                if not isinstance(scene, dict):
                    continue
                start = scene.get("start_paragraph")
                end = scene.get("end_paragraph")
                if isinstance(start, int) and isinstance(end, int) and start <= line_number <= end:
                    sid = str(scene.get("id") or "").strip()
                    if sid:
                        return sid
        if isinstance(scenes, list):
            for scene in scenes:
                if isinstance(scene, dict):
                    sid = str(scene.get("id") or "").strip()
                    if sid:
                        return sid
        return f"{chapter_key.upper()}_SC01"

    @staticmethod
    def _build_pronoun_shift_directives(archetype: str, target_language: str) -> List[str]:
        if target_language == "vn":
            if archetype == "armor_drop":
                return [
                    "PRONOUN_SHIFT_DETECTED: Atashi -> Watashi (armor drop).",
                    "VN_PRONOUN_OVERRIDE: Shift from guarded peer pronoun to softer vulnerable pronoun according to relationship matrix.",
                    "VN_GRAMMAR_SYNC: Adjust sentence-ending particles (nhé/nha/ạ) to match the new emotional pronoun weight.",
                ]
            if archetype == "ego_collapse":
                return [
                    "PRONOUN_SHIFT_DETECTED: Ore -> Boku/Watashi (ego collapse).",
                    "VN_PRONOUN_OVERRIDE: De-escalate dominant pronouns toward softer/politer forms in context.",
                    "VN_GRAMMAR_SYNC: Increase hedging and respectful sentence particles for deflated emotional state.",
                ]
            if archetype == "aggression_spike":
                return [
                    "PRONOUN_SHIFT_DETECTED: Boku/Watashi -> Ore (aggression spike).",
                    "VN_PRONOUN_OVERRIDE: Escalate pronoun stance to hostile/dominant forms when source register snaps.",
                    "VN_GRAMMAR_SYNC: Use short direct syntax with reduced softening particles.",
                ]
            return [
                "PRONOUN_SHIFT_DETECTED: JP first-person register shift.",
                "VN_PRONOUN_OVERRIDE: Mirror the exact emotional register change using relationship-aware pronouns.",
                "VN_GRAMMAR_SYNC: Align sentence-ending particles with the shifted pronoun stance.",
            ]

        if archetype == "armor_drop":
            return [
                "PRONOUN_SHIFT_DETECTED: Atashi -> Watashi (armor drop).",
                "APPLY_ARMOR_DROP_FRAMEWORK: Reduce contractions sharply and allow passive/receptive phrasing at the shift point.",
                "STYLE_SHIFT: Remove slang and move toward fragile formality until scene or pronoun state resets.",
            ]
        if archetype == "ego_collapse":
            return [
                "PRONOUN_SHIFT_DETECTED: Ore -> Boku/Watashi (ego collapse).",
                "APPLY_EGO_COLLAPSE_FRAMEWORK: Increase hedging, soften verb force, and avoid blunt declaratives.",
                "STYLE_SHIFT: Add hesitant rhythm (pauses/ellipses) to signal regression and fear.",
            ]
        if archetype == "aggression_spike":
            return [
                "PRONOUN_SHIFT_DETECTED: Boku/Watashi -> Ore (aggression spike).",
                "APPLY_AGGRESSION_SPIKE_FRAMEWORK: Strip hedging and switch to short direct declaratives.",
                "STYLE_SHIFT: Increase contraction density and hard-edged lexical choices for dominance snap.",
            ]
        if archetype == "professional_boundary_drop":
            return [
                "PRONOUN_SHIFT_DETECTED: Watakushi -> Watashi/Atashi (professional boundary drop).",
                "APPLY_BOUNDARY_DROP_FRAMEWORK: Transition from formal/clinical diction to personal conversational English.",
                "STYLE_SHIFT: Introduce emotional framing and intimacy cues immediately after the shift point.",
            ]
        if archetype == "tomboy_reversal":
            return [
                "PRONOUN_SHIFT_DETECTED: Boku -> Watashi/Atashi (tomboy reversal).",
                "APPLY_TOMBOY_REVERSAL_FRAMEWORK: Reduce blunt slang and increase hesitant introspective syntax.",
                "STYLE_SHIFT: Soften sentence endings and expose vulnerable emotional subtext.",
            ]
        return [
            "PRONOUN_SHIFT_DETECTED: JP first-person register shift.",
            "APPLY_PRONOUN_SHIFT_FRAMEWORK: Preserve shift via prose rhythm, contraction density, and agency changes.",
        ]

    def run_pronoun_shift_detector(self, volume_id: str, target_language: Optional[str] = None) -> bool:
        """Run standalone deterministic JP pronoun-shift detection and persist context artifact."""
        from pipeline.config import get_target_language

        self._ui_header(
            "Standalone JP Pronoun-Shift Detector",
            "Deterministic chapter-level PRONOUN_SHIFT_EVENT extraction",
        )

        manifest = self.load_manifest(volume_id)
        if not manifest:
            logger.error(f"No manifest.json found for volume: {volume_id}")
            logger.error("  Please run Section 1 first")
            return False

        lang = self._normalize_target_language_code(target_language or get_target_language())
        volume_path = self.work_dir / volume_id
        context_dir = volume_path / ".context"
        context_dir.mkdir(parents=True, exist_ok=True)

        jp_pronoun_tokens = {
            "atashi": ("あたし", "アタシ"),
            "watashi": ("わたし", "ワタシ", "私"),
            "watakushi": ("わたくし", "ワタクシ"),
            "ore": ("俺", "おれ", "オレ"),
            "boku": ("僕", "ぼく", "ボク"),
        }
        archetype_map = {
            ("atashi", "watashi"): "armor_drop",
            ("ore", "boku"): "ego_collapse",
            ("ore", "watashi"): "ego_collapse",
            ("boku", "ore"): "aggression_spike",
            ("watashi", "ore"): "aggression_spike",
            ("watakushi", "watashi"): "professional_boundary_drop",
            ("watakushi", "atashi"): "professional_boundary_drop",
            ("boku", "watashi"): "tomboy_reversal",
            ("boku", "atashi"): "tomboy_reversal",
        }
        archetype_label = {
            "armor_drop": "Armor Drop",
            "ego_collapse": "Ego Collapse / Regression",
            "aggression_spike": "Aggression Spike",
            "professional_boundary_drop": "Professional Boundary Drop",
            "tomboy_reversal": "Tomboy Reversal",
            "pronoun_register_shift": "Pronoun Register Shift",
        }

        chapter_map: Dict[str, List[str]] = {}
        chapters = manifest.get("chapters", [])
        if isinstance(chapters, list):
            for chapter in chapters:
                if not isinstance(chapter, dict):
                    continue
                chapter_key = self._normalize_chapter_key_for_pronoun_shift(chapter.get("id", ""))
                jp_file = chapter.get("jp_file") or chapter.get("source_file")
                if not chapter_key or not jp_file:
                    continue
                source_path = volume_path / "JP" / str(jp_file)
                if not source_path.exists():
                    continue
                try:
                    chapter_map[chapter_key] = source_path.read_text(encoding="utf-8").splitlines()
                except Exception:
                    continue

        scene_plan_index = self._load_scene_plan_index_for_pronoun_shift(volume_path, manifest)
        events_by_chapter: Dict[str, List[Dict[str, Any]]] = {}

        for chapter_key, lines in chapter_map.items():
            if not isinstance(lines, list) or not lines:
                continue

            occurrences: List[Dict[str, Any]] = []
            for line_number, raw_line in enumerate(lines, start=1):
                line = str(raw_line or "")
                if not line.strip():
                    continue
                for family, tokens in jp_pronoun_tokens.items():
                    for token in tokens:
                        start = 0
                        while True:
                            idx = line.find(token, start)
                            if idx < 0:
                                break
                            occurrences.append(
                                {
                                    "family": family,
                                    "token": token,
                                    "line": line_number,
                                    "char_index": idx,
                                    "line_excerpt": line.strip()[:180],
                                }
                            )
                            start = idx + len(token)

            occurrences.sort(key=lambda item: (int(item.get("line", 0)), int(item.get("char_index", 0))))
            if len(occurrences) < 4:
                continue

            family_counts: Dict[str, int] = {}
            for item in occurrences:
                family = str(item.get("family") or "").strip()
                if family:
                    family_counts[family] = family_counts.get(family, 0) + 1
            significant = {k: v for k, v in family_counts.items() if v >= 2}
            if len(significant) < 2:
                continue

            baseline = str(occurrences[0].get("family") or "").strip()
            if not baseline:
                continue
            baseline_seen = 0
            transition_item: Optional[Dict[str, Any]] = None
            for item in occurrences:
                family = str(item.get("family") or "").strip()
                if not family:
                    continue
                if family == baseline:
                    baseline_seen += 1
                    continue
                if baseline_seen < 2:
                    continue
                if family_counts.get(family, 0) < 2:
                    continue
                transition_item = item
                break

            if not transition_item:
                continue

            shift_to = str(transition_item.get("family") or "").strip()
            if not shift_to:
                continue

            archetype = archetype_map.get((baseline, shift_to), "pronoun_register_shift")
            line_hint = int(transition_item.get("line") or 0)
            scene_id = self._infer_scene_for_pronoun_shift(chapter_key, line_hint, scene_plan_index)
            confidence = 0.58 + min(0.34, (family_counts.get(baseline, 0) + family_counts.get(shift_to, 0)) / 24.0)
            if archetype != "pronoun_register_shift":
                confidence = min(0.95, confidence + 0.05)

            event = {
                "event_id": f"PRONOUN_SHIFT_EVENT_{chapter_key.upper()}_01",
                "chapter_id": chapter_key,
                "scene_id": scene_id,
                "shift_from": baseline,
                "shift_to": shift_to,
                "shift_label": archetype_label.get(archetype, "Pronoun Register Shift"),
                "shift_archetype": archetype,
                "detected_at_line": line_hint,
                "evidence_excerpt": str(transition_item.get("line_excerpt") or ""),
                "confidence": round(confidence, 3),
                "active_directives": self._build_pronoun_shift_directives(archetype, lang),
            }
            events_by_chapter.setdefault(chapter_key, []).append(event)

        active_directives_by_chapter: Dict[str, List[str]] = {}
        for chapter_key, events in events_by_chapter.items():
            directives: List[str] = []
            for event in events:
                for directive in event.get("active_directives", []):
                    text = str(directive or "").strip()
                    if text and text not in directives:
                        directives.append(text)
            active_directives_by_chapter[chapter_key] = directives

        payload = {
            "volume_id": volume_id,
            "target_language": lang,
            "generated_at": datetime.now().isoformat(),
            "processor_version": "1.0",
            "events_by_chapter": events_by_chapter,
            "active_directives_by_chapter": active_directives_by_chapter,
            "summary": {
                "event_chapters": len(events_by_chapter),
                "event_count": sum(len(v) for v in events_by_chapter.values()),
            },
        }

        artifact_path = context_dir / f"pronoun_shift_events_{lang}.json"
        artifact_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        metadata_key = f"metadata_{lang}"
        metadata_block = manifest.get(metadata_key, {})
        if not isinstance(metadata_block, dict):
            metadata_block = {}

        emotional = metadata_block.get("emotional_pronoun_shifts", {})
        if not isinstance(emotional, dict):
            emotional = {}
        emotional["events_by_chapter"] = events_by_chapter
        emotional["summary"] = payload["summary"]
        metadata_block["emotional_pronoun_shifts"] = emotional

        chapters_block = metadata_block.get("chapters", {})
        if isinstance(chapters_block, dict):
            for chapter_key, events in events_by_chapter.items():
                chapter_payload = chapters_block.get(chapter_key)
                if not isinstance(chapter_payload, dict):
                    continue
                chapter_payload["pronoun_shift_events"] = events
                directives = chapter_payload.get("active_directives", [])
                if not isinstance(directives, list):
                    directives = []
                seen = {str(item).strip() for item in directives if str(item).strip()}
                for event in events:
                    for directive in event.get("active_directives", []):
                        text = str(directive or "").strip()
                        if text and text not in seen:
                            directives.append(text)
                            seen.add(text)
                chapter_payload["active_directives"] = directives

        manifest[metadata_key] = metadata_block
        manifest.setdefault("pipeline_state", {})["pronoun_shift_detector"] = {
            "status": "completed",
            "timestamp": datetime.now().isoformat(),
            "target_language": lang,
            "event_chapters": payload["summary"]["event_chapters"],
            "event_count": payload["summary"]["event_count"],
            "artifact": str(artifact_path.relative_to(volume_path)),
        }

        manifest_path = volume_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        metadata_file = volume_path / f"metadata_{lang}.json"
        metadata_file.write_text(json.dumps(metadata_block, ensure_ascii=False, indent=2), encoding="utf-8")

        logger.info(
            "✓ Standalone pronoun-shift detection completed: "
            f"chapters={payload['summary']['event_chapters']}, "
            f"events={payload['summary']['event_count']}"
        )
        logger.info(f"  Artifact: {artifact_path}")
        return True

    def run_phase1_55(self, volume_id: str) -> bool:
        """Run Section 6: Full-LN cache enrichment for rich metadata."""
        self._ui_header(
            "Section 6 - Rich Metadata Cache",
            "Cache full JP LN + Gemini 2.5 Flash rich-metadata enrichment",
        )

        manifest = self.load_manifest(volume_id)
        if not manifest:
            logger.error(f"No manifest.json found for volume: {volume_id}")
            logger.error("  Please run Section 1 and Section 3 first")
            return False

        cmd = [
            sys.executable, "-m", "pipeline.metadata_processor.rich_metadata_cache",
            "--volume", volume_id
        ]

        if self._run_command(cmd, "Section 6 (Rich Metadata Cache)"):
            logger.info("✓ Section 6 completed successfully")
            self._log_phase1_55_confirmation(volume_id)
            return True
        return False

    def run_phase1_55_cache_only(self, volume_id: str) -> bool:
        """
        Build/verify full-LN cache path without applying rich metadata patches.

        Used by standalone Section 10 when user skips Section 6 overwrite but still
        wants full-LN cache preparation.
        """
        self._ui_header(
            "Section 6 - Cache-Only Prep",
            "Build full JP LN cache path without metadata overwrite",
        )

        manifest = self.load_manifest(volume_id)
        if not manifest:
            logger.error(f"No manifest.json found for volume: {volume_id}")
            logger.error("  Please run Section 1 and Section 3 first")
            return False

        cmd = [
            sys.executable, "-m", "pipeline.metadata_processor.rich_metadata_cache",
            "--volume", volume_id,
            "--cache-only",
        ]

        if self._run_command(cmd, "Section 6 (Cache-Only)"):
            logger.info("✓ Section 6 cache-only prep completed successfully")
            self._log_phase1_55_confirmation(volume_id)
            return True
        return False
    
    # ── Section 7 ────────────────────────────────────────────────────────────

    def run_phase1_56(
        self,
        volume_id: str,
        force: bool = False,
        enable_prequel_brief_injection: Optional[bool] = None,
    ) -> bool:
        """Run Section 7: Translator's Guidance Brief (Anthropic batch pre-analysis)."""
        self._ui_header(
            "Section 7 - Translator's Guidance Brief",
            "Full-corpus Gemini Flash pass → single reference doc injected into every batch prompt",
        )

        manifest = self.load_manifest(volume_id)
        if not manifest:
            logger.error(f"No manifest.json found for volume: {volume_id}")
            logger.error("  Please run Section 1 and Section 3 first")
            return False

        cmd = [
            sys.executable, "-m", "pipeline.post_processor.translation_brief_agent",
            "--volume", volume_id,
        ]
        if force:
            cmd.append("--force")
        if enable_prequel_brief_injection is True:
            cmd.append("--enable-prequel-brief-injection")

        if self._run_command(cmd, "Section 7 (Translation Brief)"):
            logger.info("✓ Section 7 completed successfully")
            return True
        return False

    # ── Full Anthropic Batch Pipeline ─────────────────────────────────────────

    def run_batch(
        self,
        volume_id: str,
        force: bool = False,
        skip_multimodal: bool = False,
        force_brief: bool = False,
        enable_prequel_brief_injection: Optional[bool] = None,
        chapters: Optional[list] = None,
    ) -> bool:
        """
        Option 1: Full Anthropic Batch Pipeline.

        Runs all preparation sections in sequence, then submits the entire
        volume to the Anthropic Batch API in a single job.

          Section 3  — Metadata extraction & character roster
          Section 6 — Gemini full-LN rich metadata enrichment
          Section 7 — Translator's Guidance Brief (full-corpus pre-analysis)
          Section 8  — Multimodal visual analysis (skippable)
          Section 9  — Stage 1 Scene Planner (narrative scaffold)
          Section 10    — Anthropic Batch API translation (50% cost, ~1h latency)

        Requires:
          - Section 1 (EPUB extraction) already completed.
          - translator_provider: anthropic in config.yaml.
        """
        from pipeline.translator.config import get_translator_provider
        if get_translator_provider() != "anthropic":
            logger.error(
                "[BATCH-PIPELINE] translator_provider is not 'anthropic'. "
                "Set translator_provider: anthropic in config.yaml before running full batch pipeline."
            )
            return False

        self._ui_header(
            "Full Anthropic Batch Pipeline",
            "Section 3 → 6 → 7 → 8 → 9 → Section 10 (Batch API)",
        )

        # ── Section 3: Metadata ────────────────────────────────────────
        logger.info("[BATCH-PIPELINE] Step 1/6 — Section 3: Metadata Processor")
        if not self.run_phase1_5(volume_id):
            logger.error("[BATCH-PIPELINE] Section 3 failed. Aborting.")
            return False

        # ── Section 6: Rich Metadata Cache ───────────────────────────
        # Generates Gemini CachedContent + rich JSON.  Section 10 will purge the
        # Gemini cache resource (Anthropic path) but the metadata JSON is kept.
        logger.info("[BATCH-PIPELINE] Step 2/6 — Section 6: Rich Metadata Cache")
        if not self.run_phase1_55(volume_id):
            logger.warning(
                "[BATCH-PIPELINE] Section 6 failed or skipped — continuing. "
                "(Gemini cache is not used by Anthropic path; metadata JSON may be incomplete.)"
            )

        # ── Section 7: Translator's Guidance Brief ───────────────────
        logger.info("[BATCH-PIPELINE] Step 3/6 — Section 7: Translator's Guidance Brief")
        if not self.run_phase1_56(
            volume_id,
            force=force_brief,
            enable_prequel_brief_injection=enable_prequel_brief_injection,
        ):
            logger.warning(
                "[BATCH-PIPELINE] Section 7 brief generation failed — continuing. "
                "Batch will proceed without the volume-wide guidance brief."
            )

        # ── Section 8: Multimodal Visual Analysis ─────────────────────
        if skip_multimodal:
            logger.info("[BATCH-PIPELINE] Step 4/6 — Section 8: Skipped (--skip-multimodal)")
            enable_multimodal = False
        else:
            logger.info("[BATCH-PIPELINE] Step 4/6 — Section 8: Multimodal Visual Analysis")
            enable_multimodal = self.run_phase1_6(
                volume_id,
                standalone=False,
                full_ln_cache_mode="off",  # Anthropic path: no Gemini cache
            )
            if not enable_multimodal:
                logger.warning(
                    "[BATCH-PIPELINE] Section 8 failed or skipped — "
                    "continuing without visual context."
                )

        # ── Section 9: Scene Planner ───────────────────────────────────
        logger.info("[BATCH-PIPELINE] Step 5/6 — Section 9: Scene Planner")
        if not self.run_phase1_7(volume_id):
            logger.error("[BATCH-PIPELINE] Section 9 failed. Aborting.")
            return False

        # ── Section 10: Anthropic Batch Translation ──────────────────────
        logger.info("[BATCH-PIPELINE] Step 6/6 — Section 10: Anthropic Batch Translation")
        success = self.run_phase2(
            volume_id,
            chapters=chapters,
            force=force,
            enable_multimodal=bool(enable_multimodal),
            full_ln_cache_mode="off",   # Anthropic path: skip Gemini cache gate
            standalone=False,
            batch=True,                 # Always batch for this command
        )

        if success:
            logger.info("")
            logger.info("✓ Full Anthropic Batch Pipeline completed successfully.")
        else:
            logger.error("✗ Section 10 batch translation failed.")

        return success

    # ─────────────────────────────────────────────────────────────────────────

    def _resolve_full_ln_cache_mode(
        self,
        *,
        standalone: bool,
        full_ln_cache_mode: str,
        volume_id: str,
        manifest: Dict[str, Any],
        phase_label: str,
    ) -> bool:
        """
        Resolve whether full-LN cache preparation should run before a phase.

        Modes:
          - on: always prepare/validate full-LN cache
          - off: skip full-LN cache preparation
          - ask: standalone interactive prompt; defaults to on for non-standalone
        """
        mode = (full_ln_cache_mode or "on").strip().lower()
        valid_modes = {"ask", "on", "off"}
        if mode not in valid_modes:
            logger.warning(f"Unknown --full-ln-cache '{full_ln_cache_mode}', falling back to on.")
            mode = "on"

        if mode == "on":
            return True
        if mode == "off":
            return False

        if not standalone:
            return True
        if not sys.stdin.isatty():
            logger.info(f"{phase_label}: non-interactive shell detected; using full-LN cache mode 'on'.")
            return True

        current_manifest = manifest
        while True:
            cache_state = self._check_full_ln_cache_state(current_manifest)
            title = current_manifest.get("metadata", {}).get("title", volume_id)
            cache_detected = bool(cache_state.get("ready")) or int(cache_state.get("cached", 0) or 0) > 0

            print("")
            print(f"{phase_label} - Full-LN Cache Gate")
            print(f"  Volume: {title}")
            print(
                "  Current cache state: "
                f"{cache_state['cached']}/{cache_state['expected']} "
                f"(ready={cache_state['ready']}, reason={cache_state['reason']})"
            )
            print("")
            print("Options:")
            print("  [1] Proceed with full-LN cache preparation")
            print("  [2] Skip full-LN cache preparation")
            if cache_detected:
                print("  [3] Purge full-LN cache state and refresh this menu")
                prompt = "Select option [1/2/3]: "
            else:
                prompt = "Select option [1/2]: "
            print("")

            choice = input(prompt).strip().lower()
            if choice == "1":
                return True
            if choice == "2":
                return False
            if choice == "3" and cache_detected:
                if self._purge_full_ln_cache_state(volume_id):
                    refreshed = self.load_manifest(volume_id)
                    current_manifest = refreshed if refreshed else {}
                    print("Full-LN cache state purged. Menu refreshed.")
                else:
                    print("Failed to purge full-LN cache state. Try again.")
                continue
            if cache_detected:
                print("Invalid selection. Choose 1, 2, or 3.")
            else:
                print("Invalid selection. Choose 1 or 2.")

    def _purge_full_ln_cache_state(self, volume_id: str) -> bool:
        """
        Purge local full-LN cache state artifacts for a volume.

        This clears manifest tracking for rich_metadata_cache and removes the
        local patch artifact file, then persists manifest.json.
        """
        manifest = self.load_manifest(volume_id)
        if not manifest:
            logger.error(f"No manifest.json found for volume: {volume_id}")
            return False

        pipeline_state = manifest.get("pipeline_state", {})
        if isinstance(pipeline_state, dict) and "rich_metadata_cache" in pipeline_state:
            pipeline_state.pop("rich_metadata_cache", None)

        try:
            manifest_path = self.get_manifest_path(volume_id)
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to persist manifest while purging full-LN cache state: {e}")
            return False

        patch_path = self.work_dir / volume_id / "rich_metadata_cache_patch.json"
        try:
            if patch_path.exists():
                patch_path.unlink()
        except Exception as e:
            logger.warning(f"Failed removing patch artifact {patch_path.name}: {e}")

        logger.info("Purged local full-LN cache state for this volume.")
        return True

    def run_phase1_6(
        self,
        volume_id: str,
        standalone: bool = False,
        full_ln_cache_mode: str = "ask",
        force_override: bool = False,
    ) -> bool:
        """
        Run Section 8: Multimodal Processor (Visual Asset Pre-bake).
        
        Analyzes illustrations using Gemini 3 Pro Vision and caches
        Art Director's Notes for use during Section 10 translation.
        
        Args:
            volume_id: Volume identifier
            standalone: If True, show next-step instructions (for CLI use)
        
        Returns:
            True if successful, False otherwise
        """
        self._ui_header("Section 8 - Art Director (Multimodal)", "Gemini 3 Pro Vision -> visual_cache.json")

        # Verify manifest exists
        manifest = self.load_manifest(volume_id)
        if not manifest:
            logger.error(f"No manifest.json found for volume: {volume_id}")
            logger.error("  Please run Section 1 first to extract the EPUB")
            return False

        use_full_ln_cache = self._resolve_full_ln_cache_mode(
            standalone=standalone,
            full_ln_cache_mode=full_ln_cache_mode,
            volume_id=volume_id,
            manifest=manifest,
            phase_label="Section 8 (Multimodal)",
        )
        if use_full_ln_cache:
            if not self.ensure_full_ln_cache(volume_id, for_phase="Section 8 (Multimodal)", manifest=manifest):
                return False
            manifest = self.load_manifest(volume_id) or manifest
        else:
            logger.warning("Skipping full-LN cache preparation for Section 8 by user request.")

        logger.info(f"Volume: {manifest.get('metadata', {}).get('title', volume_id)}")

        try:
            # Import and run asset processor
            sys.path.insert(0, str(PROJECT_ROOT))

            # Pre-flight: Illustration integrity check
            from modules.multimodal.integrity_checker import check_illustration_integrity

            volume_path = self.work_dir / volume_id
            integrity = check_illustration_integrity(volume_path)

            if integrity.warnings:
                for w in integrity.warnings:
                    logger.warning(f"  ⚠ {w}")

            if not integrity.passed:
                logger.error("")
                logger.error("ILLUSTRATION INTEGRITY CHECK FAILED")
                logger.error("The following issues must be resolved before Section 8 can run:")
                for err in integrity.errors:
                    logger.error(f"  ✗ {err}")
                logger.error("")
                logger.error("Fix the JP source tags, asset files, or manifest epub_id_to_cache_id mapping,")
                logger.error("then re-run: mtl.py phase1.6 " + volume_id)
                return False

            logger.info(f"  {integrity.summary()}")

            from modules.multimodal.asset_processor import VisualAssetProcessor

            processor = VisualAssetProcessor(volume_path, force_override=force_override)
            stats = processor.process_volume()

            if stats.get("error"):
                logger.error(f"Section 8 failed: {stats['error']}")
                return False

            logger.info("")
            logger.info("Section 8 Summary:")
            logger.info(f"  Total illustrations: {stats.get('total', 0)}")
            logger.info(f"  Already cached:      {stats.get('cached', 0)}")
            logger.info(f"  Newly analyzed:      {stats.get('generated', 0)}")
            logger.info(f"  Safety blocked:      {stats.get('blocked', 0)}")

            self._log_phase1_6_confirmation(volume_id)
            
            if standalone:
                logger.info("")
                logger.info("Next: Run Section 10 to translate with visual context")
                logger.info(f"  mtl.py phase2 {volume_id} --enable-multimodal")
            
            return True

        except ImportError as e:
            logger.error(f"Failed to import multimodal module: {e}")
            logger.error("Ensure modules/multimodal/ package is installed")
            return False
        except Exception as e:
            logger.error(f"Section 8 failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def run_phase1_7(
        self,
        volume_id: str,
        chapters: Optional[list] = None,
        force: bool = False,
        temperature: float = 0.3,
        max_output_tokens: int = 65535,
    ) -> bool:
        """Run Section 9: Stage 1 Scene Planner (v1.6 architecture)."""
        self._ui_header(
            "Section 9 - Stage 1 Scene Planner",
            "Narrative beat + character rhythm scaffold before translation",
        )

        manifest = self.load_manifest(volume_id)
        if not manifest:
            logger.error(f"No manifest.json found for volume: {volume_id}")
            logger.error("  Please run Section 1 first to extract the EPUB")
            return False

        cmd = [
            sys.executable, "-m", "pipeline.planner.agent",
            "--volume", volume_id,
            "--temperature", str(temperature),
            "--max-output-tokens", str(max_output_tokens),
        ]
        if chapters:
            cmd.extend(["--chapters", *chapters])
        if force:
            cmd.append("--force")

        if self._run_command(cmd, "Section 9 (Scene Planner)"):
            latest_manifest = self.load_manifest(volume_id) or {}
            planner_state = latest_manifest.get("pipeline_state", {}).get("scene_planner", {})
            if planner_state.get("status") == "partial":
                logger.warning("⚠️  Section 9 completed with partial failures (continuing)")
            else:
                logger.info("✓ Section 9 completed successfully")
            self._log_phase1_7_confirmation(volume_id)
            return True
        return False

    def run_phase1_7_coprocessor(self, volume_id: str) -> bool:
        """
        Run Section 9 Co-Processor (standalone context-offload pack refresh).

        This is a standalone menu command that executes the four co-processors
        via Section 6 cache-only mode:
          - character_registry.json
          - cultural_glossary.json
          - timeline_map.json
          - idiom_transcreation_cache.json
        """
        self._ui_header(
            "Section 9 - Co-Processor Pack",
            "Standalone context offload refresh (cache-only, no metadata overwrite)",
        )

        manifest = self.load_manifest(volume_id)
        if not manifest:
            logger.error(f"No manifest.json found for volume: {volume_id}")
            logger.error("  Please run Section 1 and Section 3 first")
            return False

        cmd = [
            sys.executable, "-m", "pipeline.metadata_processor.rich_metadata_cache",
            "--volume", volume_id,
            "--cache-only",
        ]

        if self._run_command(cmd, "Section 9 Co-Processor (Cache-Only)"):
            logger.info("✓ Section 9 Co-Processor completed successfully")
            self._log_phase1_55_confirmation(volume_id)
            return True
        return False
    
    # Alias for backward compatibility
    def run_phase0(self, volume_id: str) -> bool:
        """Deprecated: Use run_phase1_6 instead. Kept for backward compatibility."""
        logger.warning("⚠️  'phase0' is deprecated. Use 'phase1.6' instead.")
        return self.run_phase1_6(volume_id, standalone=True)

    def _resolve_phase155_mode_for_phase2(
        self,
        *,
        standalone: bool,
        phase155_mode: str,
        volume_id: str,
        manifest: Dict[str, Any],
    ) -> str:
        """
        Resolve Section 6 behavior for Section 10 runs.

        Modes:
          - auto: run Section 6 only if cache is missing/incomplete (legacy behavior)
          - skip: skip rich-metadata overwrite, but run cache-only prep before Section 10
          - overwrite: always run Section 6 before Section 10
          - ask: standalone-only interactive prompt (skip vs overwrite)
        """
        normalized_mode = (phase155_mode or "auto").strip().lower()
        valid_modes = {"auto", "skip", "overwrite", "ask"}
        if normalized_mode not in valid_modes:
            logger.warning(f"Unknown --phase1-55-mode '{phase155_mode}', falling back to auto.")
            normalized_mode = "auto"

        if normalized_mode != "ask":
            return normalized_mode

        if not standalone:
            return "auto"

        if not sys.stdin.isatty():
            logger.info(
                "Section 10 standalone: non-interactive shell detected; "
                "using auto Section 6 policy."
            )
            return "auto"

        cache_state = self._check_full_ln_cache_state(manifest)
        title = manifest.get("metadata", {}).get("title", volume_id)
        print("")
        print("Section 10 Standalone - Section 6 Gate")
        print(f"  Volume: {title}")
        print(
            "  Current cache state: "
            f"{cache_state['cached']}/{cache_state['expected']} "
            f"(ready={cache_state['ready']}, reason={cache_state['reason']})"
        )
        print("")
        print("Options:")
        print("  [1] Skip metadata overwrite (run cache-only prep)")
        print("  [2] Continue with Section 6 (overwrite/update rich metadata)")
        print("")

        while True:
            choice = input("Select option [1/2]: ").strip().lower()
            if choice == "1":
                return "skip"
            if choice == "2":
                return "overwrite"
            print("Invalid selection. Choose 1 or 2.")

    def run_phase2(self, volume_id: str, chapters: Optional[list] = None, force: bool = False,
                   enable_gap_analysis: bool = False,
                   enable_multimodal: bool = False,
                   phase155_mode: str = "auto",
                   full_ln_cache_mode: str = "ask",
                   standalone: bool = False,
                   batch: bool = False) -> bool:
        """Run Section 10: Translator (Gemini MT / Anthropic Batch)."""
        self._ui_header(
            "Section 10 - Translator",
            "Advanced stack: Bible continuity + Tiered RAG + Vector Search + Multimodal (optional)"
        )
        runtime_lines = self._phase2_runtime_profile_lines(enable_multimodal)
        if not self.ui.render_phase2_runtime_panel(runtime_lines):
            for line in runtime_lines:
                logger.info(line)
        
        # Verify manifest exists before proceeding
        manifest = self.load_manifest(volume_id)
        if not manifest:
            logger.error(f"✗ No manifest.json found for volume: {volume_id}")
            logger.error("  Please run Section 1 first to extract the EPUB")
            return False

        # ── Anthropic provider: bypass Gemini-exclusive cache infrastructure ──
        # Section 6 (rich_metadata_cache) runs Gemini 2.5 Flash to create a
        # named CachedContent resource on Google's servers. This resource is
        # meaningless when the translator is Anthropic — skip it entirely and
        # purge any stale Gemini cache state so the gate never blocks startup.
        from pipeline.translator.config import get_translator_provider
        if get_translator_provider() == "anthropic":
            pipeline_state = manifest.get("pipeline_state", {})
            if isinstance(pipeline_state, dict) and "rich_metadata_cache" in pipeline_state:
                logger.info(
                    "[ANTHROPIC] Detected existing Gemini full-LN cache state — purging "
                    "(Gemini CachedContent resources are not used by the Anthropic translator path)."
                )
                self._purge_full_ln_cache_state(volume_id)
                manifest = self.load_manifest(volume_id) or manifest
            else:
                logger.info(
                    "[ANTHROPIC] No Gemini full-LN cache state found — nothing to purge."
                )
            logger.info(
                "[ANTHROPIC] Skipping Section 6 and Full-LN Cache Gate "
                "(Gemini-exclusive; Anthropic builds its own inline cache at translation time)."
            )
            use_full_ln_cache = False
        else:
            use_full_ln_cache = self._resolve_full_ln_cache_mode(
                standalone=standalone,
                full_ln_cache_mode=full_ln_cache_mode,
                volume_id=volume_id,
                manifest=manifest,
                phase_label="Section 10 (Translator)",
            )
        # ── end Anthropic bypass ──────────────────────────────────────────────

        if use_full_ln_cache:
            resolved_phase155_mode = self._resolve_phase155_mode_for_phase2(
                standalone=standalone,
                phase155_mode=phase155_mode,
                volume_id=volume_id,
                manifest=manifest,
            )
            if resolved_phase155_mode == "overwrite":
                logger.info(
                    "Section 10 standalone: running Section 6 before translation "
                    "(overwrite/update requested)."
                )
                if not self.run_phase1_55(volume_id):
                    logger.error("Section 6 failed; cannot continue Section 10.")
                    return False
                manifest = self.load_manifest(volume_id) or manifest
                refreshed_state = self._check_full_ln_cache_state(manifest)
                logger.info(
                    f"Full-LN cache status after overwrite: "
                    f"{refreshed_state['cached']}/{refreshed_state['expected']} "
                    f"(ready={refreshed_state['ready']}, reason={refreshed_state['reason']})."
                )
            elif resolved_phase155_mode == "skip":
                logger.info(
                    "Skipping Section 6 — translator will build the full-LN cache directly."
                )
            else:
                if not self.ensure_full_ln_cache(
                    volume_id,
                    for_phase="Section 10 (Translator)",
                    manifest=manifest,
                ):
                    return False
                manifest = self.load_manifest(volume_id) or manifest
        else:
            logger.warning("Skipping full-LN cache preparation for Section 10 by user request.")
            if phase155_mode and str(phase155_mode).lower() != "ask":
                logger.info("Ignoring --phase1-55-mode because full-LN cache mode is off.")

        if manifest.get("bible_id"):
            logger.info(
                "Bible continuity: attempting linked bible load "
                "(fallback to manifest metadata if bible is unavailable)."
            )
        else:
            logger.info("Bible continuity: no bible link, using manifest metadata only.")

        logger.info(f"✓ Loaded manifest for: {manifest.get('metadata', {}).get('title', volume_id)}")
        manifest_chapters = self._get_manifest_chapters(manifest)

        target_chapters = manifest_chapters
        if chapters:
            target_ids = {str(ch).strip() for ch in chapters}
            target_chapters = [
                c for c in manifest_chapters
                if str(c.get("id", "")).strip() in target_ids
            ]

        # Standalone Section 10 should self-heal Stage 1.7 prerequisites.
        # Full run already executes 1.7 explicitly before Section 10.
        if standalone and target_chapters:
            missing_plan_ids = self._missing_scene_plan_chapter_ids(volume_id, target_chapters)
            if missing_plan_ids:
                logger.info(
                    "Section 10 standalone: Stage 1.7 plans missing for "
                    f"{len(missing_plan_ids)} chapter(s); auto-running planner."
                )
                if not self.run_phase1_7(volume_id, chapters=missing_plan_ids):
                    logger.error("Section 9 auto-run failed; cannot continue Section 10.")
                    return False

                # Reload manifest to pick up newly written scene_plan_file paths.
                manifest = self.load_manifest(volume_id) or manifest
                manifest_chapters = self._get_manifest_chapters(manifest)
                target_chapters = manifest_chapters
                if chapters:
                    target_ids = {str(ch).strip() for ch in chapters}
                    target_chapters = [
                        c for c in manifest_chapters
                        if str(c.get("id", "")).strip() in target_ids
                    ]
            else:
                logger.info("Section 10 standalone: Stage 1.7 plans already available.")

        expected_total = len(target_chapters) if target_chapters else 1
        
        cmd = [
            sys.executable, "-m", "pipeline.translator.agent",
            "--volume", volume_id
        ]
        
        if chapters:
            cmd.extend(["--chapters"] + chapters)
        
        if force:
            cmd.append("--force")
        
        if enable_gap_analysis:
            cmd.append("--enable-gap-analysis")

        if enable_multimodal:
            cmd.append("--enable-multimodal")

        # Auto-enable Anthropic Batch API: explicit --batch flag OR Anthropic provider default.
        # get_translator_provider() is already imported above (line ~1864) within this method scope.
        use_batch = batch or (get_translator_provider() == "anthropic")
        if use_batch:
            cmd.append("--batch")
            logger.info("[ANTHROPIC] Batch API enabled — chapters will be submitted as a single batch job (50% cost, ~1h latency).")

        if self._run_phase2_command_with_progress(cmd, expected_total=expected_total):
            logger.info("✓ Section 10 completed successfully")
            
            # Run CJK validation automatically after translation
            self._validate_cjk_leaks(volume_id)
            
            return True
        return False
    
    def _validate_cjk_leaks(self, volume_id: str) -> None:
        """Run CJK character leak validation after translation."""
        logger.info("")
        logger.info("Running CJK validation...")
        
        try:
            validator = CJKValidator()
            results = validator.validate_volume(volume_id, WORK_DIR)
            
            if not results:
                logger.info("✓ No CJK character leaks detected")
            else:
                total_issues = sum(len(issues) for issues in results.values())
                logger.warning(f"⚠ Found {total_issues} CJK character leak(s)")
                logger.warning("  Run 'python scripts/cjk_validator.py --scan-volume <volume_id>' for detailed report")
                logger.warning("  These should be fixed in Section 11 (Critics)")
        except Exception as e:
            logger.warning(f"CJK validation failed: {e}")
            logger.warning("Continuing anyway...")
    
    def run_phase3_instructions(self, volume_id: str) -> None:
        """Display Section 11 instructions (Manual/Agentic Workflow)."""
        from pipeline.config import get_target_language
        
        target_lang = get_target_language()
        lang_dir = target_lang.upper()
        
        self._ui_header("Section 11 - Critics", "Audit, fix, verify, and approve for build")
        logger.info("")
        logger.info("Section 11 uses an AGENTIC WORKFLOW with Gemini CLI.")
        logger.info("Required Tool: AUDIT_AGENT.md (Agent Core Definition)")
        logger.info("")
        logger.info("WORKFLOW:")
        logger.info("  0. CJK Character Validation (Automated)")
        logger.info(f"     → Command: python scripts/cjk_validator.py --scan-volume {volume_id}")
        logger.info("     → Detects untranslated Chinese/Japanese/Korean characters")
        logger.info("     → Auto-run after Section 10, manual check recommended")
        logger.info("")
        logger.info("  1. Translation Audit (Module 1)")
        logger.info(f"     → Command: gemini -s AUDIT_AGENT.md 'Audit WORK/{volume_id}/{lang_dir}/CHAPTER_XX.md'")
        logger.info("     → System analyzes Victorian patterns, contractions, and AI-isms.")
        logger.info("     → Output: Graded report with specific fix recommendations.")
        logger.info("")
        logger.info("  2. Fix & Verify (Including CJK Leaks)")
        logger.info("     → Apply fixes based on the report.")
        logger.info("     → Aim for Grade A/B (Production Ready).")
        logger.info("")
        logger.info("  3. Illustration Insertion (Module 2)")
        logger.info("     → Command: gemini -s AUDIT_AGENT.md 'Insert illustrations for target chapter...'")
        logger.info("     → System performs semantic matching to place <img class=\"fit\"> tags.")
        logger.info("")
        logger.info("  4. Final Approval")
        logger.info("     → Verify strict adherence to 'Hybrid Localization' standards.")
        logger.info("")
        logger.info("="*60)
        logger.info("SAFETY BLOCK HANDLING (PROHIBITED_CONTENT)")
        logger.info("="*60)
        logger.info("")
        logger.info("If Gemini API refuses to translate a chapter:")
        logger.info("")
        logger.info("  1. Review Raw Material")
        logger.info("     → Check WORK/{}/JP/CHAPTER_XX.md for sensitive content".format(volume_id))
        logger.info("     → Verify if refusal is due to: violence, suggestive content, minor safety")
        logger.info("")
        logger.info("  2. Use Web Gemini Interface (Recommended Fallback)")
        logger.info("     → Open: https://gemini.google.com")
        logger.info("     → Upload: prompts/master_prompt_en_compressed.xml")
        logger.info("     → Paste: Full chapter text from JP/CHAPTER_XX.md")
        logger.info("     → Web Gemini is trained on Light Novel tropes (higher pass rate)")
        logger.info("")
        logger.info("  3. Manual Integration")
        logger.info("     → Copy Web Gemini output to EN/CHAPTER_XX.md")
        logger.info("     → Re-run Section 11 audit on the manual translation")
        logger.info("")
        logger.info("When Section 11 review is complete, proceed to Section 12.")
        logger.info("="*60)
    
    def run_phase4(self, volume_id: str, output_name: Optional[str] = None) -> bool:
        """Run Section 12: Builder (EPUB Packaging)."""
        self._ui_header("Section 12 - Builder", "Package translated resources into EPUB output")
        
        cmd = [
            sys.executable, "-m", "pipeline.builder.agent",
            volume_id
        ]
        
        if output_name:
            cmd.extend(["--output", output_name])
        
        if self._run_command(cmd, "Section 12 (Builder)"):
            logger.info("✓ Section 12 completed successfully")
            return True
        return False
    
    def run_full_pipeline(self, epub_path: Path, volume_id: Optional[str] = None,
                          skip_multimodal: bool = False) -> bool:
        """
        Run the complete pipeline (Sections 1, 3, 6, 8, 9, 10, and 12).

        Args:
            epub_path: Path to source EPUB file
            volume_id: Optional volume identifier (auto-generated if not provided)
            skip_multimodal: Skip Section 8 (visual analysis) for faster processing
        
        Returns:
            True if successful, False otherwise
        """
        from pipeline.config import (
            get_target_language, get_language_config, validate_language_setup
        )

        if not epub_path.exists():
            logger.error(f"EPUB file not found: {epub_path}")
            return False

        # Validate language setup before starting
        target_lang = get_target_language()
        is_valid, issues = validate_language_setup(target_lang)
        if not is_valid:
            logger.error(f"Language setup incomplete for '{target_lang}':")
            for issue in issues:
                logger.error(f"  - {issue}")
            logger.error("Run 'mtl.py config --language <lang>' to check setup.")
            return False

        lang_config = get_language_config(target_lang)
        language_name = lang_config.get('language_name', target_lang.upper())

        # Generate volume ID if not provided
        if not volume_id:
            volume_id = self.generate_volume_id(epub_path)
            logger.info(f"Generated volume ID: {volume_id}")

        self._ui_header("Full Pipeline Run (v5.2)", "S1 -> S3 -> S6 -> S8 -> S9 -> S10 -> S12")
        logger.info(f"Target Language: {language_name} ({target_lang.upper()})")
        logger.info(f"Source: {epub_path}")
        logger.info(f"Volume ID: {volume_id}")
        logger.info("")

        phase_total = 6 if skip_multimodal else 7
        phase_done = 0

        with self.ui.phase_progress(phase_total, "Pipeline v5.2") as pipeline_tracker:
            def _advance_pipeline(label: str) -> None:
                nonlocal phase_done
                phase_done += 1
                pipeline_tracker.advance(label)
                if not self.ui.rich_enabled:
                    self.ui.render_status_bar("Pipeline Progress", phase_done, phase_total)
                else:
                    logger.info(f"  -> {label} complete ({phase_done}/{phase_total})")

            # Section 1: Librarian
            if not self.run_phase1(epub_path, volume_id):
                pipeline_tracker.fail("S1 Librarian")
                return False
            _advance_pipeline("S1 Librarian")

            logger.info("")

            # Section 3: Metadata Processor
            if not self.run_phase1_5(volume_id):
                pipeline_tracker.fail("S3 Metadata")
                return False
            _advance_pipeline("S3 Metadata")

            logger.info("")

            # Section 6: Rich Metadata Cache Enrichment
            if not self.run_phase1_55(volume_id):
                pipeline_tracker.fail("S6 Rich Metadata")
                return False
            _advance_pipeline("S6 Rich Metadata")

            logger.info("")

            # Interactive pause after metadata enrichment (only in verbose mode)
            if self.verbose:
                while True:
                    self._ui_header("Checkpoint: Prep Complete", "Review metadata or continue to Section 10 translation")
                    logger.info("")
                    print("OPTIONS:")
                    print("  [1] Proceed to Section 10 - Translator")
                    print("  [2] Review Metadata (Title, Author, Characters, Terms)")
                    print("  [B] Back to previous menu")
                    print("  [Q] Quit Pipeline")
                    print("")

                    choice = input("Select option: ").strip().lower()

                    if choice == '1':
                        logger.info("Proceeding to Section 10...")
                        break
                    elif choice == '2':
                        print("")
                        self.show_metadata(volume_id)
                        print("")
                        print("OPTIONS:")
                        print("  [1] Proceed to Section 10 - Translator")
                        print("  [B] Back to previous menu")
                        print("")
                        sub_choice = input("Select option: ").strip().lower()
                        if sub_choice == '1':
                            logger.info("Proceeding to Section 10...")
                            break
                        elif sub_choice == 'b':
                            continue
                        else:
                            continue
                    elif choice == 'b':
                        continue
                    elif choice == 'q':
                        logger.info("Pipeline stopped by user.")
                        return True
                    else:
                        print("Invalid selection. Try again.")
                        continue
            else:
                # Minimal mode - auto-proceed
                logger.info("✓ Metadata extraction complete")

            logger.info("")

            # Section 8: Multimodal Processor (Visual Analysis)
            multimodal_success = False
            if not skip_multimodal:
                multimodal_success = self.run_phase1_6(volume_id, standalone=False)
                if not multimodal_success:
                    logger.warning("⚠️  Section 8 (Multimodal) failed or skipped")
                    logger.warning("   Continuing without visual context...")
                _advance_pipeline("S8 Art Director")
                logger.info("")
            else:
                logger.info("ℹ️  Skipping Section 8 (Multimodal) - --skip-multimodal flag set")
                logger.info("")

            # Section 9: Stage 1 Scene Planner (required before Stage 2 translation)
            if not self.run_phase1_7(volume_id):
                pipeline_tracker.fail("S9 Scene Planner")
                return False
            _advance_pipeline("S9 Scene Planner")

            logger.info("")

            # Section 10: Translator (with multimodal if Section 8 succeeded)
            enable_multimodal = multimodal_success and not skip_multimodal
            if enable_multimodal:
                logger.info("✓ Visual context enabled for translation")

            if not self.run_phase2(volume_id, enable_multimodal=enable_multimodal):
                pipeline_tracker.fail("S10 Translator")
                return False
            _advance_pipeline("S10 Translator")

            logger.info("")

            # Section 11: Manual/Agentic Workflow (Instructions only - verbose mode)
            if self.verbose:
                self.run_phase3_instructions(volume_id)

            # Interactive menu (only in verbose mode)
            if self.verbose:
                while True:
                    # Clear screen (ANSI)
                    print("\033[H\033[J", end="")

                    # Re-print Menu Header
                    self._ui_header("Interactive Menu", "Section 11 review complete; choose next action")
                    logger.info(f"Volume ID: {volume_id}")
                    logger.info("")

                    # Options
                    print("OPTIONS:")
                    print("  [1] Proceed to Section 12 - Builder (Packaging)")
                    print("  [2] Return to Menu / Exit")

                    # Toggle Status
                    status_text = "Verbose (Full Details)" if self.verbose else "Minimal (Clean Output)"
                    print(f"  [V] Toggle Logs: {status_text}")
                    print("")

                    choice = input("Select option: ").strip().lower()

                    if choice == '1':
                        print("")
                        phase4_success = self.run_phase4(volume_id)
                        if phase4_success:
                            _advance_pipeline("S12 Builder")
                        else:
                            pipeline_tracker.fail("S12 Builder")
                        return phase4_success
                    elif choice == '2':
                        return True
                    elif choice == 'v':
                        self.verbose = not self.verbose
                        # Loop will restart and redraw menu with new status
                        continue
                    else:
                        input("Invalid selection. Press Enter to try again...")
            else:
                # Minimal mode - auto-proceed to Section 12
                logger.info("")
                phase4_success = self.run_phase4(volume_id)
                if phase4_success:
                    _advance_pipeline("S12 Builder")
                else:
                    pipeline_tracker.fail("S12 Builder")
                return phase4_success
    
    def show_metadata(self, volume_id: str) -> None:
        """Display metadata in clean, readable format."""
        from pipeline.config import get_target_language, get_language_config
        
        manifest = self.load_manifest(volume_id)
        if not manifest:
            logger.error(f"Volume not found: {volume_id}")
            return
        
        # Get current target language
        target_lang = get_target_language()
        lang_config = get_language_config(target_lang)
        lang_name = lang_config.get('language_name', target_lang.upper())
        
        metadata = manifest.get('metadata', {})
        metadata_key = f'metadata_{target_lang}'
        metadata_translated = manifest.get(metadata_key, {})
        
        # Fallback to metadata_en for backward compatibility
        if not metadata_translated and target_lang == 'en':
            metadata_translated = manifest.get('metadata_en', {})
        
        self._ui_header("Metadata Review", f"Volume: {volume_id}")
        logger.info("")
        logger.info("JAPANESE (Original):")
        logger.info(f"  Title:       {metadata.get('title', 'N/A')}")
        logger.info(f"  Author:      {metadata.get('author', 'N/A')}")
        logger.info(f"  Illustrator: {metadata.get('illustrator', 'N/A')}")
        logger.info(f"  Publisher:   {metadata.get('publisher', 'N/A')}")
        logger.info(f"  Volume:      {metadata.get('volume', 'N/A')}")
        logger.info("")
        logger.info(f"{lang_name.upper()} (Translated):")
        
        # Language-specific keys (title_en, title_vn, etc.)
        title_key = f'title_{target_lang}'
        series_key = f'series_title_{target_lang}'
        author_key = f'author_{target_lang}'
        
        logger.info(f"  Title:       {metadata_translated.get(title_key, 'N/A')}")
        logger.info(f"  Series:      {metadata_translated.get(series_key, 'N/A')}")
        logger.info(f"  Author:      {metadata_translated.get(author_key, 'N/A')}")
        logger.info(f"  Volume:      {metadata_translated.get('volume', 'N/A')}")
        
        # Show ruby-extracted names from Section 1 (if available)
        ruby_names = manifest.get('ruby_names', [])
        ruby_terms = manifest.get('ruby_terms', [])
        
        logger.info("")
        if ruby_names:
            logger.info(f"RUBY-EXTRACTED NAMES (Section 1): {len(ruby_names)} entries")
            for entry in ruby_names[:10]:
                kanji = entry.get('kanji', '?')
                ruby = entry.get('ruby', '?')
                confidence = entry.get('confidence', 0.0)
                logger.info(f"  {kanji} ({ruby}) [{confidence:.2f}]")
            if len(ruby_names) > 10:
                logger.info(f"  ... and {len(ruby_names) - 10} more names")
        else:
            logger.info("RUBY-EXTRACTED NAMES (Section 1): Not extracted (re-run Section 1 to extract)")
        
        # Show character names from Section 3 translation (if available)
        logger.info("")
        
        # First check language-specific metadata file for character names (preferred)
        metadata_lang_path = self.work_dir / volume_id / f"metadata_{target_lang}.json"
        character_names_from_metadata = {}
        if metadata_lang_path.exists():
            with open(metadata_lang_path, 'r', encoding='utf-8') as f:
                metadata_lang_full = json.load(f)
                character_names_from_metadata = metadata_lang_full.get('character_names', {})
        
        # Fallback to .context/name_registry.json
        context_dir = self.work_dir / volume_id / ".context"
        name_registry_path = context_dir / "name_registry.json"
        
        character_names = character_names_from_metadata
        if not character_names and name_registry_path.exists():
            with open(name_registry_path, 'r', encoding='utf-8') as f:
                character_names = json.load(f)
        
        if character_names:
            logger.info(f"CHARACTER NAMES (Section 3 Translated): {len(character_names)} entries")
            for jp, en in list(character_names.items())[:15]:  # Show first 15
                logger.info(f"  {jp} → {en}")
            if len(character_names) > 15:
                logger.info(f"  ... and {len(character_names) - 15} more names")
        else:
            logger.info("CHARACTER NAMES (Section 3): Not yet translated (run Section 3 to translate)")
        
        # Show ruby-extracted terms from Section 1 (if available)
        logger.info("")
        if ruby_terms:
            logger.info(f"RUBY-EXTRACTED TERMS (Section 1): {len(ruby_terms)} entries")
            for entry in ruby_terms[:10]:
                kanji = entry.get('kanji', '?')
                ruby = entry.get('ruby', '?')
                logger.info(f"  {kanji} ({ruby})")
            if len(ruby_terms) > 10:
                logger.info(f"  ... and {len(ruby_terms) - 10} more terms")
        else:
            logger.info("RUBY-EXTRACTED TERMS (Section 1): Not extracted (re-run Section 1 to extract)")
        
        # Show glossary/terms (always display section)
        logger.info("")
        
        # Check language-specific metadata file for glossary (preferred)
        glossary = {}
        if metadata_lang_path.exists():
            with open(metadata_lang_path, 'r', encoding='utf-8') as f:
                metadata_lang_full = json.load(f)
                glossary = metadata_lang_full.get('glossary', {})
        
        # Fallback to metadata from manifest
        if not glossary:
            glossary = metadata_translated.get('glossary', {})
        
        if glossary:
            logger.info(f"TERMS/GLOSSARY (Section 3 Translated): {len(glossary)} entries")
            for jp, en in list(glossary.items())[:15]:  # Show first 15
                logger.info(f"  {jp} → {en}")
            if len(glossary) > 15:
                logger.info(f"  ... and {len(glossary) - 15} more terms")
        else:
            logger.info("TERMS/GLOSSARY (Section 3): 0 entries (Section 3 not yet run)")
        
        # Show chapter info
        chapters = manifest.get('chapters', [])
        logger.info("")
        logger.info(f"CHAPTERS: {len(chapters)} total")
        for ch in chapters[:5]:  # Show first 5
            logger.info(f"  {ch.get('filename', 'N/A')}: {ch.get('title', 'N/A')}")
        if len(chapters) > 5:
            logger.info(f"  ... and {len(chapters) - 5} more chapters")
        
        logger.info("="*60)
    
    def show_status(self, volume_id: str) -> None:
        """Display pipeline status for a volume."""
        from pipeline.config import get_target_language, get_language_config
        
        manifest = self.load_manifest(volume_id)
        if not manifest:
            logger.error(f"Volume not found: {volume_id}")
            return
        
        # Get current target language
        target_lang = get_target_language()
        lang_config = get_language_config(target_lang)
        lang_name = lang_config.get('language_name', target_lang.upper())
        
        self._ui_header("Pipeline Status", f"Volume: {volume_id}")
        
        # Metadata
        metadata = manifest.get('metadata', {})
        metadata_key = f'metadata_{target_lang}'
        metadata_translated = manifest.get(metadata_key, {})
        
        # Fallback to metadata_en for backward compatibility
        if not metadata_translated and target_lang == 'en':
            metadata_translated = manifest.get('metadata_en', {})
        
        # Language-specific keys
        title_key = f'title_{target_lang}'
        author_key = f'author_{target_lang}'
        
        logger.info(f"Title (JP): {metadata.get('title', 'N/A')}")
        logger.info(f"Title ({target_lang.upper()}): {metadata_translated.get(title_key, 'N/A')}")
        logger.info(f"Author (JP): {metadata.get('author', 'N/A')}")
        logger.info(f"Author ({target_lang.upper()}): {metadata_translated.get(author_key, 'N/A')}")
        logger.info("")
        
        # Pipeline state
        pipeline_state = manifest.get('pipeline_state', {})
        p1_raw = pipeline_state.get('librarian', {}).get('status', 'not started')
        p15_raw = pipeline_state.get('metadata_processor', {}).get('status', 'not started')
        p155_raw = pipeline_state.get('rich_metadata_cache', {}).get('status', 'not started')
        p2_raw = pipeline_state.get('translator', {}).get('status', 'not started')
        p3_raw = pipeline_state.get('critics', {}).get('status', 'manual review')
        p4_raw = pipeline_state.get('builder', {}).get('status', 'not started')

        logger.info("Section Overview:")
        logger.info(f"  S1   Librarian: {self._status_badge(p1_raw):<5} ({p1_raw})")
        logger.info(f"  S3   Metadata:  {self._status_badge(p15_raw):<5} ({p15_raw})")
        logger.info(f"  S6   Rich:      {self._status_badge(p155_raw):<5} ({p155_raw})")

        # Section 8 (Multimodal) - check for visual_cache.json
        volume_path = self.work_dir / volume_id
        visual_cache_path = volume_path / "visual_cache.json"
        if visual_cache_path.exists():
            try:
                import json as _json
                with open(visual_cache_path, 'r', encoding='utf-8') as _f:
                    cache_data = _json.load(_f)
                cache_count = len(cache_data)
                p16_raw = f"cached ({cache_count})"
                logger.info(f"  S8   Visual:    DONE  ({p16_raw})")
            except Exception:
                p16_raw = "cache unreadable"
                logger.info(f"  S8   Visual:    WARN  ({p16_raw})")
        else:
            p16_raw = "not run"
            logger.info(f"  S8   Visual:    TODO  ({p16_raw})")

        logger.info(f"  S10  Translator: {self._status_badge(p2_raw):<5} ({p2_raw})")
        logger.info(f"  S11  Review:     {self._status_badge(p3_raw):<5} ({p3_raw})")
        logger.info(f"  S12  Builder:    {self._status_badge(p4_raw):<5} ({p4_raw})")

        completed_sections = 0
        completed_sections += int(self._status_badge(p1_raw) == "DONE")
        completed_sections += int(self._status_badge(p15_raw) == "DONE")
        completed_sections += int(self._status_badge(p155_raw) == "DONE")
        completed_sections += int(p16_raw.startswith("cached"))
        completed_sections += int(self._status_badge(p2_raw) == "DONE")
        completed_sections += int(self._status_badge(p4_raw) == "DONE")
        self.ui.render_status_bar("Section Completion", completed_sections, 6)
        logger.info("")
        
        # Chapters
        chapters = manifest.get('chapters', [])
        logger.info(f"CHAPTERS: {len(chapters)} total")
        
        completed = sum(1 for ch in chapters if ch.get('translation_status') == 'completed')
        logger.info(f"  Translated: {completed}/{len(chapters)}")
        
        qc_pass = sum(1 for ch in chapters if ch.get('qc_status') == 'pass')
        logger.info(f"  QC Passed:  {qc_pass}/{len(chapters)}")
        logger.info("")
        
        # Assets
        assets = manifest.get('assets', {})
        logger.info(f"ASSETS:")
        logger.info(f"  Cover:         {assets.get('cover', 'N/A')}")
        logger.info(f"  Kuchi-e:       {len(assets.get('kuchie', []))} images")
        logger.info(f"  Illustrations: {len(assets.get('illustrations', []))} images")
        logger.info("")

        # Suggested next action
        if p4_raw != "completed":
            if p2_raw != "completed":
                logger.info(f"Next (S10): mtl.py phase2 {volume_id}")
            elif p3_raw != "completed":
                logger.info(f"Next (S11): manual review / critics")
            else:
                logger.info(f"Next (S12): mtl.py phase4 {volume_id}")
    
    def run_cleanup(self, volume_id: str, dry_run: bool = False) -> bool:
        """
        Run post-translation cleanup on chapter titles.
        
        Args:
            volume_id: Volume identifier
            dry_run: Preview changes without modifying files
        
        Returns:
            True if successful, False otherwise
        """
        self._ui_header("Cleanup", "Normalize translated chapter title artifacts")
        
        try:
            # Import and run cleanup script
            from scripts.cleanup_translated_titles import TitleCleanup
            
            cleanup = TitleCleanup(dry_run=dry_run)
            success = cleanup.clean_volume(volume_id, self.work_dir)
            
            if success:
                logger.info("✓ Cleanup completed successfully")
            else:
                logger.error("✗ Cleanup failed")
            
            return success
            
        except ImportError as e:
            logger.error(f"Failed to import cleanup script: {e}")
            logger.error("Make sure scripts/cleanup_translated_titles.py exists")
            return False
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
            return False
    
    def run_cjk_clean(self, volume_id: str, dry_run: bool = False) -> bool:
        """
        Run Vietnamese CJK hard substitution cleaner on translated chapters.
        
        This post-processor catches CJK leaks that slipped through Gemini's
        translation despite advisory guidance. It performs hard regex substitution
        for known patterns (少女, スタミナ, etc.) with Vietnamese equivalents.
        
        Args:
            volume_id: Volume identifier
            dry_run: Preview changes without modifying files
        
        Returns:
            True if successful, False otherwise
        """
        self._ui_header("CJK Cleaner (VN)", "Hard-substitution pass for script leak cleanup")
        
        try:
            from pipeline.post_processor.vn_cjk_cleaner import VietnameseCJKCleaner, format_cleaner_report
            
            # Find volume directory
            volume_dirs = list(self.work_dir.glob(f"*{volume_id}*"))
            if not volume_dirs:
                logger.error(f"Volume not found: {volume_id}")
                return False
            
            work_dir = volume_dirs[0]
            vn_dir = work_dir / "VN"
            
            if not vn_dir.exists():
                logger.error(f"VN directory not found: {vn_dir}")
                return False
            
            # Initialize cleaner
            cleaner = VietnameseCJKCleaner(strict_mode=not dry_run, log_substitutions=True)
            
            # Run cleaner
            results = cleaner.clean_volume(vn_dir)
            
            # Print report
            print(format_cleaner_report(results))
            
            if results['total_substitutions'] > 0:
                if dry_run:
                    logger.info(f"[DRY RUN] Would apply {results['total_substitutions']} substitutions")
                else:
                    logger.info(f"✓ Applied {results['total_substitutions']} hard substitutions")
            
            if results['total_remaining_leaks'] > 0:
                logger.warning(f"⚠ {results['total_remaining_leaks']} unknown CJK leaks remain - manual review needed")
            
            return True
            
        except ImportError as e:
            logger.error(f"Failed to import CJK cleaner: {e}")
            return False
        except Exception as e:
            logger.error(f"CJK cleaning failed: {e}")
            return False
    
    def run_heal(self, volume_id: str, dry_run: bool = False, target_language: str = None) -> bool:
        """
        Run Self-Healing Anti-AI-ism Agent on translated chapters.
        
        Three-layer detection + LLM auto-correction:
        Layer 1: Regex patterns (65+ from anti_ai_ism_patterns.json)
        Layer 2: Vector Bad Prose DB (ChromaDB semantic matching)
        Layer 3: Psychic Distance Filter (filter words, nominalizations, bloat)
        
        Args:
            volume_id: Volume to heal
            dry_run: Preview issues without modifying files
            target_language: Override language detection ('en' or 'vn')
            
        Returns:
            True if successful, False otherwise
        """
        self._ui_header(
            "Self-Healing Anti-AI-ism Agent",
            f"3-layer detection + rewrite {'(dry run)' if dry_run else '(apply mode)'}"
        )
        
        try:
            from modules.anti_ai_ism_agent import AntiAIismAgent
            
            # Find volume directory
            volume_dirs = list(self.work_dir.glob(f"*{volume_id}*"))
            if not volume_dirs:
                logger.error(f"Volume not found: {volume_id}")
                return False
            
            work_dir = volume_dirs[0]
            
            # Auto-detect language from config or directory structure
            if target_language is None:
                if (work_dir / "VN").exists() and not (work_dir / "EN").exists():
                    target_language = "vn"
                elif (work_dir / "EN").exists() and not (work_dir / "VN").exists():
                    target_language = "en"
                else:
                    # Check config
                    try:
                        import yaml
                        config_path = PROJECT_ROOT / "config.yaml"
                        if config_path.exists():
                            with open(config_path) as f:
                                cfg = yaml.safe_load(f)
                            target_language = cfg.get("target_language", "en")
                        else:
                            target_language = "en"
                    except Exception:
                        target_language = "en"
            
            logger.info(f"Target language: {target_language.upper()}")
            
            agent = AntiAIismAgent(
                config_dir=PROJECT_ROOT / "config",
                auto_heal=not dry_run,
                dry_run=dry_run,
                target_language=target_language,
            )
            
            report = agent.heal_volume(work_dir)
            agent.print_summary(report)
            
            # Save report
            audit_dir = work_dir / "audits"
            agent.save_report(report, audit_dir)
            
            return report.total_issues == 0 or report.total_healed > 0
            
        except ImportError as e:
            logger.error(f"Failed to import Anti-AI-ism Agent: {e}")
            return False
        except Exception as e:
            logger.error(f"Self-healing failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def inspect_visual_cache(self, volume_id: str, detail: bool = False) -> bool:
        """
        Inspect the visual analysis cache for a volume.

        Shows cache statistics, per-illustration status, and optionally
        full cached analysis content for debugging.

        Args:
            volume_id: Volume identifier
            detail: If True, show full cached analysis per illustration

        Returns:
            True if cache exists, False otherwise
        """
        volume_path = self.work_dir / volume_id
        cache_path = volume_path / "visual_cache.json"

        self._ui_header("Visual Cache Inspector", f"Volume: {volume_id}")

        if not cache_path.exists():
            logger.info("")
            logger.info("  ✗ No visual_cache.json found")
            logger.info("")
            logger.info("  To generate, run:")
            logger.info(f"    mtl.py phase1.6 {volume_id}")
            logger.info("="*60)
            return False

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"  ✗ Failed to read cache: {e}")
            return False

        total = len(cache)
        statuses = {}
        for illust_id, data in cache.items():
            status = data.get('status', 'unknown')
            statuses[status] = statuses.get(status, 0) + 1

        logger.info(f"\n  Total entries:     {total}")
        for status, count in sorted(statuses.items()):
            icon = "✓" if status == "analyzed" else "⚠" if status == "safety_blocked" else "?"
            logger.info(f"  {icon} {status}: {count:>3}")

        # Check for manual overrides
        manual = sum(1 for d in cache.values() if d.get('manual_override'))
        if manual > 0:
            logger.info(f"  🔒 Manual overrides: {manual}")

        logger.info("")

        # Per-illustration summary
        logger.info("ILLUSTRATIONS:")
        logger.info("-" * 50)
        for illust_id, data in sorted(cache.items()):
            status = data.get('status', 'unknown')
            icon = "✓" if status == "analyzed" else "⛔" if status == "safety_blocked" else "?"
            override = " 🔒" if data.get('manual_override') else ""
            model = data.get('model', 'N/A')

            # Show composition snippet
            vgt = data.get('visual_ground_truth', {})
            composition = vgt.get('composition', '')
            snippet = composition[:60] + "..." if len(composition) > 60 else composition

            logger.info(f"  {icon} {illust_id}{override}")
            if snippet:
                logger.info(f"      {snippet}")

            if detail:
                emotional = vgt.get('emotional_delta', 'N/A')
                directives = vgt.get('narrative_directives', [])
                spoiler = data.get('spoiler_prevention', {})
                logger.info(f"      Model: {model}")
                logger.info(f"      Emotion: {emotional}")
                if directives:
                    logger.info(f"      Directives ({len(directives)}):")
                    for d in directives[:3]:
                        logger.info(f"        - {d}")
                if spoiler.get('do_not_reveal_before_text'):
                    logger.info(f"      ⚠ Spoiler guards: {spoiler['do_not_reveal_before_text']}")
                logger.info("")

        logger.info("="*60)
        logger.info(f"Next: mtl.py phase2 {volume_id} --enable-multimodal")
        logger.info("="*60)
        return True

    def run_visual_thinking(
        self,
        volume_id: str,
        split: bool = False,
        with_cache: bool = False,
        filter_type: Optional[str] = None,
        output_dir: Optional[str] = None,
    ) -> bool:
        """
        Convert Gemini 3 Pro visual thought logs (JSON) to markdown.

        Imports the standalone converter from scripts/convert_visual_thoughts.py
        and runs it against the specified volume, producing either a consolidated
        VISUAL_THINKING.md or per-illustration split files.

        Args:
            volume_id: Volume identifier
            split: If True, generate one file per illustration
            with_cache: If True, include Art Director's Notes from visual_cache.json
            filter_type: Optional filter ('illust', 'kuchie', or 'cover')
            output_dir: Custom output directory (default: THINKING/ in volume)

        Returns:
            True if successful, False otherwise
        """
        volume_path = self.work_dir / volume_id
        thoughts_dir = volume_path / "cache" / "thoughts"

        self._ui_header("Visual Thinking Converter", "Convert cache/thoughts JSON to markdown reports")

        if not thoughts_dir.exists():
            logger.error(f"No thought logs found at: {thoughts_dir}")
            logger.error("Run Section 8 first: mtl.py phase1.6 <volume_id>")
            return False

        try:
            from scripts.convert_visual_thoughts import (
                load_thought_json,
                load_visual_cache_entry,
                render_thought_entry,
                render_consolidated_markdown,
            )
        except ImportError as e:
            logger.error(f"Failed to import convert_visual_thoughts: {e}")
            return False

        # Load thought logs
        json_files = sorted(thoughts_dir.glob("*.json"))
        if not json_files:
            logger.error("No .json files found in cache/thoughts/")
            return False

        entries = []
        for jf in json_files:
            data = load_thought_json(jf)
            if data:
                entries.append(data)

        logger.info(f"Loaded {len(entries)} thought log(s)")

        # Apply filter
        if filter_type:
            if filter_type == "cover":
                entries = [e for e in entries if e["illustration_id"] == "cover"]
            else:
                entries = [e for e in entries if e["illustration_id"].startswith(filter_type)]
            logger.info(f"Filtered to {len(entries)} entries (type={filter_type})")

        if not entries:
            logger.warning("No entries after filtering. Nothing to convert.")
            return True

        # Load visual cache if requested
        visual_cache = None
        if with_cache:
            cache_path = volume_path / "visual_cache.json"
            if cache_path.exists():
                with open(cache_path, 'r', encoding='utf-8') as f:
                    visual_cache = json.load(f)
                logger.info(f"Loaded visual_cache.json ({len(visual_cache)} entries)")
            else:
                logger.warning("visual_cache.json not found, --with-cache ignored")

        # Determine output directory
        if output_dir:
            out_dir = Path(output_dir)
        else:
            out_dir = volume_path / "THINKING"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Extract volume name from directory
        vol_name = volume_path.name.rsplit("_", 2)[0]

        from datetime import datetime as dt

        if split:
            written = 0
            for entry in entries:
                illust_id = entry["illustration_id"]
                cache_entry = None
                if visual_cache:
                    cache_entry = load_visual_cache_entry(visual_cache, illust_id)

                md_lines = []
                md_lines.append("# Visual Analysis Reasoning Process")
                md_lines.append("")
                md_lines.append(f"**Volume**: {vol_name}")
                md_lines.append(f"**Generated**: {dt.now().strftime('%Y-%m-%d %H:%M:%S')}")
                md_lines.append(f"**Model**: {entry.get('model', 'gemini-3-pro-preview')}")
                md_lines.append(f"**Phase**: 1.6 (Multimodal Processor)")
                md_lines.append("")
                md_lines.append("---")
                md_lines.append("")
                md_lines.append(render_thought_entry(entry, cache_entry, with_cache))
                md_lines.append("---")
                md_lines.append("")
                md_lines.append(
                    "*This visual thinking process is automatically generated by "
                    "Gemini 3 Pro during Section 8 (Multimodal Processor) and "
                    "provides insight into the visual analysis decision-making process.*"
                )

                out_file = out_dir / f"visual_{illust_id}_THINKING.md"
                out_file.write_text("\n".join(md_lines), encoding="utf-8")
                written += 1
                logger.info(f"  ✓ {out_file.name}")

            logger.info(f"\n✅ Generated {written} visual thinking file(s) in {out_dir}")
        else:
            markdown = render_consolidated_markdown(
                entries, vol_name, visual_cache, with_cache
            )
            out_file = out_dir / "VISUAL_THINKING.md"
            out_file.write_text(markdown, encoding="utf-8")

            total_time = sum(e.get("processing_time_seconds", 0) for e in entries)
            logger.info(f"\n✅ Generated: {out_file}")
            logger.info(f"   {len(entries)} illustrations, {total_time:.1f}s total")

        logger.info("=" * 60)
        return True

    def list_volumes(self) -> None:
        """List all volumes in WORK directory."""
        volumes = sorted(
            [d for d in self.work_dir.iterdir() if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
            reverse=True
        )
        
        if not volumes:
            logger.info("No volumes found in WORK directory.")
            return

        rows = []
        for vol_dir in volumes:
            volume_id = vol_dir.name
            manifest = self.load_manifest(volume_id)
            if not manifest:
                continue

            pipeline_state = manifest.get('pipeline_state', {})
            p1 = self._status_badge(pipeline_state.get('librarian', {}).get('status', ''))
            p15 = self._status_badge(pipeline_state.get('metadata_processor', {}).get('status', ''))
            p155 = self._status_badge(pipeline_state.get('rich_metadata_cache', {}).get('status', ''))
            p16 = self._visual_phase_badge(volume_id)
            p2 = self._status_badge(pipeline_state.get('translator', {}).get('status', ''))
            p4 = self._status_badge(pipeline_state.get('builder', {}).get('status', ''))
            lang = manifest.get('metadata', {}).get('target_language', 'n/a').upper()
            title = manifest.get('metadata_en', {}).get('title_en') or manifest.get('metadata', {}).get('title', 'Unknown')
            id_key = self._short_volume_id(volume_id)
            title_short = title[:49] + "..." if len(title) > 52 else title
            rows.append({
                "p1": p1,
                "p15": p15,
                "p155": p155,
                "p16": p16,
                "p2": p2,
                "p4": p4,
                "lang": lang,
                "id_key": id_key,
                "title": title_short,
            })

        if self.ui.rich_enabled:
            rich_rows = []
            for row in rows:
                stage_summary = " ".join([
                    self.ui.format_compact_badge(row["p1"]),
                    self.ui.format_compact_badge(row["p15"]),
                    self.ui.format_compact_badge(row["p155"]),
                    self.ui.format_compact_badge(row["p16"]),
                    self.ui.format_compact_badge(row["p2"]),
                    self.ui.format_compact_badge(row["p4"]),
                ])
                rich_rows.append([
                    stage_summary,
                    row["lang"],
                    row["id_key"],
                    row["title"],
                ])
            self.ui.render_table(
                title=f"Workspace Volumes ({len(rows)})",
                columns=[
                    {"header": "Stages (P1/P1.5/P1.55/P1.6/P2/P4)", "no_wrap": True},
                    {"header": "Lang", "justify": "center", "style": "cyan"},
                    {"header": "ID Key", "style": "cyan", "no_wrap": True},
                    {"header": "Title", "no_wrap": True, "overflow": "ellipsis", "max_width": 56},
                ],
                rows=rich_rows,
                caption="Tip: run `mtl.py status <id>` for detailed per-volume metrics.",
            )
            return

        self._ui_header("Workspace Volumes", f"Total: {len(rows)}")
        logger.info(" P1   P1.5  P1.55 P1.6     P2    P4    Lang  ID Key         Title")
        logger.info("-" * 110)
        for row in rows:
            logger.info(
                f" {row['p1']:<4} {row['p15']:<5} {row['p155']:<5} {row['p16']:<8} {row['p2']:<5} {row['p4']:<5} "
                f"{row['lang']:<5} {row['id_key']:<14} {row['title']}"
            )
        logger.info("-" * 110)
        logger.info("Tip: run `mtl.py status <id>` for detailed per-volume metrics.")
    
    def inspect_metadata(self, volume_id: str, validate: bool = False) -> bool:
        """
        Inspect and validate metadata schema for a volume.
        
        Detects which schema variant is used and shows compatibility status.
        
        Schema Variants:
        - Enhanced v2.1: characters, dialogue_patterns, scene_contexts, translation_guidelines
        - Legacy V2: character_profiles, localization_notes, speech_pattern
        - V4 Nested: character_names with nested objects {relationships, traits, pronouns}
        
        Args:
            volume_id: Volume identifier
            validate: If True, run full validation and show detailed compatibility report
            
        Returns:
            True if schema is compatible with translator, False otherwise
        """
        from pipeline.config import get_target_language
        
        manifest = self.load_manifest(volume_id)
        if not manifest:
            logger.error(f"Volume not found: {volume_id}")
            return False
        
        target_lang = get_target_language()
        metadata_key = f'metadata_{target_lang}'
        metadata = manifest.get(metadata_key, {})
        
        # Fallback to metadata_en
        if not metadata and target_lang == 'en':
            metadata = manifest.get('metadata_en', {})
        
        self._ui_header("Metadata Schema Inspection", f"Volume: {volume_id}")
        
        # Detect schema variant
        schema_variant = "Unknown"
        schema_details = []
        is_compatible = True
        
        # Check for Enhanced v2.1 markers
        has_characters = 'characters' in metadata and isinstance(metadata.get('characters'), list)
        has_dialogue_patterns = 'dialogue_patterns' in metadata
        has_translation_guidelines = 'translation_guidelines' in metadata
        has_scene_contexts = 'scene_contexts' in metadata
        
        # Check for Legacy V2 markers
        has_character_profiles = 'character_profiles' in metadata
        has_localization_notes = 'localization_notes' in metadata
        
        # Check for V4 Nested markers
        char_names = metadata.get('character_names', {})
        first_value = next(iter(char_names.values()), None) if char_names else None
        has_nested_char_names = isinstance(first_value, dict)
        
        if has_characters and has_dialogue_patterns:
            schema_variant = "Enhanced v2.1"
            schema_details = [
                f"  ✓ characters: {len(metadata.get('characters', []))} entries",
                f"  ✓ dialogue_patterns: Present" if has_dialogue_patterns else "  ○ dialogue_patterns: Missing",
                f"  ✓ translation_guidelines: Present" if has_translation_guidelines else "  ○ translation_guidelines: Missing",
                f"  ○ scene_contexts: {'Present' if has_scene_contexts else 'Missing'}"
            ]
        elif has_character_profiles or has_localization_notes:
            schema_variant = "Legacy V2"
            profiles = metadata.get('character_profiles', {})
            schema_details = [
                f"  ✓ character_profiles: {len(profiles)} entries" if has_character_profiles else "  ○ character_profiles: Missing",
                f"  ✓ localization_notes: Present" if has_localization_notes else "  ○ localization_notes: Missing",
            ]
            # Check for speech_pattern in profiles
            has_speech = any(p.get('speech_pattern') for p in profiles.values()) if profiles else False
            schema_details.append(f"  ✓ speech_pattern (in profiles): Yes" if has_speech else "  ○ speech_pattern: Not found")
        elif has_nested_char_names:
            schema_variant = "V4 Nested"
            schema_details = [
                f"  ✓ character_names (nested): {len(char_names)} entries",
                f"  → Contains: relationships, traits, pronouns"
            ]
        elif char_names and isinstance(first_value, str):
            schema_variant = "Basic (name-only)"
            schema_details = [
                f"  ✓ character_names: {len(char_names)} entries (flat mapping)"
            ]
        else:
            schema_variant = "Minimal/Empty"
            is_compatible = True  # Still compatible, just no semantic data
            schema_details = ["  ⚠ No semantic metadata found"]
        
        logger.info(f"\nDetected Schema: {schema_variant}")
        logger.info("-" * 40)
        for detail in schema_details:
            logger.info(detail)
        
        # Show transformation info
        logger.info("")
        logger.info("TRANSLATOR COMPATIBILITY:")
        logger.info("-" * 40)
        
        if schema_variant == "Enhanced v2.1":
            logger.info("  ✓ Native format - No transformation needed")
        elif schema_variant == "Legacy V2":
            logger.info("  ✓ Auto-transform: character_profiles → characters")
            logger.info("  ✓ Auto-transform: localization_notes → translation_guidelines")
            logger.info("  ✓ Auto-extract: speech_pattern → dialogue_patterns")
        elif schema_variant == "V4 Nested":
            logger.info("  ✓ Auto-transform: nested character_names → characters list")
        elif schema_variant == "Basic (name-only)":
            logger.info("  ✓ Compatible: Names used for consistency")
            logger.info("  ⚠ Limited: No character traits or dialogue patterns")
        else:
            logger.info("  ⚠ No semantic metadata - Translation will use defaults")
        
        logger.info("")
        logger.info(f"Status: {'✓ COMPATIBLE' if is_compatible else '✗ ISSUES FOUND'}")
        
        # If validate flag, show detailed field analysis
        if validate:
            logger.info("")
            logger.info("Detailed Validation Report:")
            
            # Check chapter-level title_en
            chapters = manifest.get('chapters', [])
            chapters_with_title = sum(1 for ch in chapters if ch.get('title_en'))
            logger.info(f"\nChapter Titles (title_en):")
            logger.info(f"  {chapters_with_title}/{len(chapters)} chapters have English titles")
            if chapters_with_title < len(chapters):
                logger.info("  ⚠ Missing title_en may cause builder issues")
                for i, ch in enumerate(chapters):
                    if not ch.get('title_en'):
                        logger.info(f"    - Chapter {i+1}: {ch.get('filename', 'unknown')}")
            
            # Check character_names mapping
            logger.info(f"\nCharacter Names Mapping:")
            if char_names:
                logger.info(f"  {len(char_names)} JP→EN name mappings")
                # Show sample
                for i, (jp, en) in enumerate(list(char_names.items())[:5]):
                    if isinstance(en, dict):
                        logger.info(f"    {jp} → {en.get('en', en)} (nested)")
                    else:
                        logger.info(f"    {jp} → {en}")
                if len(char_names) > 5:
                    logger.info(f"    ... and {len(char_names) - 5} more")
            else:
                logger.info("  ⚠ No character_names mapping found")
            
            # Show what translator will receive
            logger.info(f"\nTranslator Will Receive:")
            if schema_variant in ["Enhanced v2.1", "Legacy V2", "V4 Nested"]:
                logger.info("  • characters list with profiles")
                logger.info("  • dialogue_patterns for speech consistency")
                logger.info("  • translation_guidelines for style rules")
            else:
                logger.info("  • Basic name mappings only")
        
        logger.info("")
        return is_compatible
    
    def handle_config(self, toggle_pre_toc: bool = False, show: bool = False,
                     model: Optional[str] = None, temperature: Optional[float] = None,
                     top_p: Optional[float] = None, top_k: Optional[int] = None,
                     backend: Optional[str] = None,
                     language: Optional[str] = None, show_language: bool = False,
                     toggle_multimodal: bool = False,
                     toggle_smart_chunking: bool = False,
                     toggle_proxy_key: bool = False,
                     phase2_endpoint: Optional[str] = None) -> None:
        """Handle configuration commands."""
        import yaml
        import os
        import sys
        from pathlib import Path
        
        # Ensure pipeline module can be imported
        pipeline_root = PROJECT_ROOT.resolve()
        sys.path.insert(0, str(pipeline_root))
        
        # Import after path is set
        from pipeline.config import (
            get_target_language, get_language_config, get_available_languages,
            set_target_language, validate_language_setup
        )

        config_path = PROJECT_ROOT / "config.yaml"

        if not config_path.exists():
            logger.error(f"Configuration file not found: {config_path}")
            return

        # Load current config
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        changes_made = []

        backend_aliases = {
            'auto': 'auto',
            'genai': 'developer',
            'developer': 'developer',
            'vertex': 'vertex',
        }

        # Language switching
        if language:
            try:
                available = get_available_languages()
                if language not in available:
                    logger.error(f"Invalid language: '{language}'. Available: {available}")
                    return

                # Validate language resources exist
                is_valid, issues = validate_language_setup(language)
                if not is_valid:
                    logger.error(f"Language '{language}' setup incomplete:")
                    for issue in issues:
                        logger.error(f"  - {issue}")
                    return

                old_lang = get_target_language()
                set_target_language(language)  # This saves to config.yaml
                lang_config = get_language_config(language)
                changes_made.append(f"Target Language: {old_lang} → {language} ({lang_config.get('language_name', language.upper())})")

                # Reload config since set_target_language modified the file
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)

            except Exception as e:
                logger.error(f"Failed to switch language: {e}")
                return

        # Show language only
        if show_language:
            current_lang = get_target_language()
            lang_config = get_language_config(current_lang)
            self._ui_header("Current Target Language")
            logger.info(f"  Code: {current_lang}")
            logger.info(f"  Name: {lang_config.get('language_name', current_lang.upper())}")
            logger.info(f"  Master Prompt: {lang_config.get('master_prompt', 'N/A')}")
            logger.info(f"  Modules Dir: {lang_config.get('modules_dir', 'N/A')}")
            logger.info(f"  Output Suffix: {lang_config.get('output_suffix', 'N/A')}")
            return

        # Model switching
        if model:
            model_map = {
                'pro': 'gemini-3-pro-preview',
                'flash': 'gemini-3-flash-preview',
                '2.5-pro': 'gemini-2.5-pro',
                '2.5-flash': 'gemini-2.5-flash',
                'gemini-3-pro-preview': 'gemini-3-pro-preview',
                'gemini-3-flash-preview': 'gemini-3-flash-preview',
                'gemini-2.5-pro': 'gemini-2.5-pro',
                'gemini-2.5-flash': 'gemini-2.5-flash'
            }
            
            if 'gemini' not in config:
                config['gemini'] = {}
            
            old_model = config['gemini'].get('model', 'N/A')
            new_model = model_map[model]
            config['gemini']['model'] = new_model
            changes_made.append(f"Model: {old_model} → {new_model}")
        
        # Temperature adjustment
        if temperature is not None:
            if not (0.0 <= temperature <= 2.0):
                logger.error("Temperature must be between 0.0 and 2.0")
                return
            
            if 'gemini' not in config:
                config['gemini'] = {}
            if 'generation' not in config['gemini']:
                config['gemini']['generation'] = {}
            
            old_temp = config['gemini']['generation'].get('temperature', 'N/A')
            config['gemini']['generation']['temperature'] = temperature
            changes_made.append(f"Temperature: {old_temp} → {temperature}")
        
        # Top-p adjustment
        if top_p is not None:
            if not (0.0 <= top_p <= 1.0):
                logger.error("top_p must be between 0.0 and 1.0")
                return
            
            if 'gemini' not in config:
                config['gemini'] = {}
            if 'generation' not in config['gemini']:
                config['gemini']['generation'] = {}
            
            old_top_p = config['gemini']['generation'].get('top_p', 'N/A')
            config['gemini']['generation']['top_p'] = top_p
            changes_made.append(f"top_p: {old_top_p} → {top_p}")
        
        # Top-k adjustment
        if top_k is not None:
            if not (1 <= top_k <= 100):
                logger.error("top_k must be between 1 and 100")
                return
            
            if 'gemini' not in config:
                config['gemini'] = {}
            if 'generation' not in config['gemini']:
                config['gemini']['generation'] = {}
            
            old_top_k = config['gemini']['generation'].get('top_k', 'N/A')
            config['gemini']['generation']['top_k'] = top_k
            changes_made.append(f"top_k: {old_top_k} → {top_k}")

        # Backend switching
        if backend:
            requested_backend = backend_aliases.get(backend.strip().lower())
            if not requested_backend:
                logger.error("Invalid backend. Use one of: auto, genai, vertex")
                return

            if 'gemini' not in config:
                config['gemini'] = {}
            if 'vertex' not in config['gemini']:
                config['gemini']['vertex'] = {}

            old_backend = str(config['gemini'].get('backend', 'auto'))

            if requested_backend == 'vertex':
                env_project = (os.getenv("GOOGLE_CLOUD_PROJECT") or "").strip()
                cfg_project = str(config['gemini']['vertex'].get('project', '') or '').strip()
                if not env_project and not cfg_project:
                    # Graceful fallback: keep runtime healthy even when Vertex is requested.
                    config['gemini']['backend'] = 'developer'
                    changes_made.append(
                        f"Backend: {old_backend} → developer (GenAI fallback; GOOGLE_CLOUD_PROJECT / gemini.vertex.project not detected)"
                    )
                else:
                    config['gemini']['backend'] = 'vertex'
                    changes_made.append(f"Backend: {old_backend} → vertex")
            else:
                config['gemini']['backend'] = requested_backend
                display_backend = 'genai' if requested_backend == 'developer' else requested_backend
                changes_made.append(f"Backend: {old_backend} → {display_backend}")
        
        # Show current settings
        if show or (
            not toggle_pre_toc
            and not toggle_multimodal
            and not toggle_smart_chunking
            and not toggle_proxy_key
            and not phase2_endpoint
            and not model
            and temperature is None
            and top_p is None
            and top_k is None
            and not backend
            and not language
        ):
            self._ui_header("Pipeline Configuration", "MTL Studio v5.2 runtime settings")

            # Target Language
            try:
                current_lang = get_target_language()
                lang_config = get_language_config(current_lang)
                logger.info(f"\nTarget Language:")
                logger.info(f"  Language: {lang_config.get('language_name', current_lang.upper())} ({current_lang})")
                logger.info(f"  Master Prompt: {lang_config.get('master_prompt', 'N/A')}")
                logger.info(f"  Modules Dir: {lang_config.get('modules_dir', 'N/A')}")
                logger.info(f"  Output Suffix: {lang_config.get('output_suffix', 'N/A')}")

                # Validate setup
                is_valid, issues = validate_language_setup(current_lang)
                if is_valid:
                    logger.info(f"  Status: ✓ Resources validated")
                else:
                    logger.info(f"  Status: ✗ Setup incomplete")
                    for issue in issues:
                        logger.info(f"    - {issue}")
            except Exception as e:
                logger.info(f"\nTarget Language: Error loading ({e})")

            # Translation model and parameters
            gemini = config.get('gemini', {})
            generation = gemini.get('generation', {})
            vertex_cfg = gemini.get('vertex', {}) if isinstance(gemini.get('vertex', {}), dict) else {}

            logger.info(f"\nTranslation Model & Parameters:")
            current_backend = str(gemini.get('backend', 'auto')).strip().lower()
            backend_display = 'genai' if current_backend == 'developer' else current_backend
            logger.info(f"  Backend: {backend_display}")
            if current_backend in {'auto', 'vertex'}:
                active_vertex_project = (os.getenv("GOOGLE_CLOUD_PROJECT") or str(vertex_cfg.get('project', '')).strip())
                if active_vertex_project:
                    logger.info(f"  Vertex Project: {active_vertex_project}")
                    logger.info(f"  Vertex Location: {vertex_cfg.get('location', 'us-central1')}")
                else:
                    logger.info("  Vertex Project: not detected (will fallback to GenAI)")
            current_model = gemini.get('model', 'N/A')
            logger.info(f"  Model: {current_model}")
            logger.info(f"  Temperature: {generation.get('temperature', 'N/A')}")
            logger.info(f"  top_p: {generation.get('top_p', 'N/A')}")
            logger.info(f"  top_k: {generation.get('top_k', 'N/A')}")
            logger.info(f"  Max tokens: {generation.get('max_output_tokens', 'N/A')}")

            # Pre-TOC detection
            pre_toc = config.get('pre_toc_detection', {})
            enabled = pre_toc.get('enabled', True)
            status = "✓ ENABLED" if enabled else "✗ DISABLED"

            logger.info(f"\nPre-TOC Content Detection: {status}")
            logger.info("  (Detects opening hooks before prologue - RARE)")
            logger.info(f"  Min text length: {pre_toc.get('min_text_length', 50)}")
            logger.info(f"  Chapter title: {pre_toc.get('chapter_title', 'Opening')}")

            # Other settings
            logger.info(f"\nLogging:")
            logger.info(f"  Level: {config.get('logging', {}).get('level', 'INFO')}")

            # Sino-Vietnamese RAG + Vector Search Status
            logger.info(f"\nSino-Vietnamese RAG + Vector Search:")
            try:
                rag_path = PROJECT_ROOT / "config" / "sino_vietnamese_rag.json"
                chroma_path = PROJECT_ROOT / "chroma_sino_vn"
                
                if rag_path.exists():
                    import json
                    with open(rag_path, 'r', encoding='utf-8') as f:
                        rag_data = json.load(f)
                    
                    # Count patterns
                    total_patterns = 0
                    categories = []
                    for cat_name, cat_data in rag_data.get('pattern_categories', {}).items():
                        count = len(cat_data.get('patterns', []))
                        total_patterns += count
                        categories.append(f"{cat_name}({count})")
                    
                    logger.info(f"  RAG Database: ✓ ONLINE ({total_patterns} patterns)")
                    logger.info(f"  Categories: {', '.join(categories)}")
                    
                    # Check ChromaDB
                    if chroma_path.exists():
                        # Try to get vector count
                        try:
                            from modules.sino_vietnamese_store import SinoVietnameseStore
                            store = SinoVietnameseStore(
                                persist_directory=str(chroma_path),
                                rag_file_path=str(rag_path)
                            )
                            vector_count = store.vector_store.collection.count()
                            logger.info(f"  Vector Index: ✓ ONLINE ({vector_count} vectors)")
                            logger.info(f"  Hybrid Mode: ✓ Direct Lookup + Semantic Search")
                        except Exception as e:
                            logger.info(f"  Vector Index: ⚠️ Error loading ({e})")
                    else:
                        logger.info(f"  Vector Index: ✗ OFFLINE (run rebuild_index.py)")
                else:
                    logger.info(f"  RAG Database: ✗ OFFLINE (sino_vietnamese_rag.json not found)")
            except Exception as e:
                logger.info(f"  Status: ⚠️ Error checking ({e})")

            # Multimodal Configuration
            multimodal = config.get('multimodal', {})
            mm_enabled = multimodal.get('enabled', False)
            mm_status = "✓ ENABLED" if mm_enabled else "✗ DISABLED"
            logger.info(f"\nMultimodal Visual Context (Experimental): {mm_status}")
            if mm_enabled:
                mm_models = multimodal.get('models', {})
                logger.info(f"  Vision Model: {mm_models.get('vision', 'N/A')}")
                logger.info(f"  Prose Model: {mm_models.get('prose', 'N/A')}")
                mm_thinking = multimodal.get('thinking', {})
                logger.info(f"  Thinking Level: {mm_thinking.get('default_level', 'N/A')}")
                mm_cache = multimodal.get('visual_cache', {})
                logger.info(f"  Cache Enabled: {mm_cache.get('enabled', False)}")
                mm_lookahead = multimodal.get('lookahead', {})
                logger.info(f"  Lookahead Buffer: {mm_lookahead.get('buffer_size', 'N/A')} segments")
            else:
                logger.info("  Enable with: mtl.py config --toggle-multimodal")
                logger.info("  Workflow: phase1.6 → phase2 --enable-multimodal")

            # Smart chunking configuration
            massive_cfg = config.get('translation', {}).get('massive_chapter', {})
            smart_chunking_enabled = massive_cfg.get('enable_smart_chunking', True)
            smart_chunking_status = "✓ ENABLED" if smart_chunking_enabled else "✗ DISABLED"
            logger.info(f"\nSmart Chunking (Massive Chapters): {smart_chunking_status}")
            logger.info(f"  Threshold chars: {massive_cfg.get('chunk_threshold_chars', 60000)}")
            logger.info(f"  Threshold bytes: {massive_cfg.get('chunk_threshold_bytes', 120000)}")
            logger.info(f"  Target chunk chars: {massive_cfg.get('target_chunk_chars', 45000)}")
            if not smart_chunking_enabled:
                logger.info("  Enable with: mtl.py config --toggle-smart-chunking")

            logger.info("")
            logger.info("Quick Commands:")
            logger.info("  --language en|vn             Switch target language")
            logger.info("  --show-language              Show current language details")
            logger.info("  --model pro|flash|2.5-pro|2.5-flash")
            logger.info("                              Switch translation model")
            logger.info("  --backend auto|genai|vertex Set LLM backend mode")
            logger.info("  --temperature 0.6            Adjust creativity (0.0-2.0)")
            logger.info("  --top-p 0.95                 Adjust nucleus sampling")
            logger.info("  --top-k 40                   Adjust top-k sampling")
            logger.info("  --toggle-pre-toc             Toggle pre-TOC detection")
            logger.info("  --toggle-multimodal          Toggle multimodal visual context")
            logger.info("  --toggle-smart-chunking      Toggle smart chunking for massive chapters")
            logger.info("  --toggle-proxy-key           Toggle Anthropic key source (.env vs proxy settings)")
            logger.info("  --phase2-endpoint openrouter|official")
            logger.info("")
        
        # Toggle pre-TOC detection
        if toggle_pre_toc:
            if 'pre_toc_detection' not in config:
                config['pre_toc_detection'] = {}

            current = config['pre_toc_detection'].get('enabled', True)
            new_value = not current
            config['pre_toc_detection']['enabled'] = new_value
            status = "ENABLED" if new_value else "DISABLED"
            changes_made.append(f"Pre-TOC Detection: {status}")

        # Toggle multimodal visual context
        if toggle_multimodal:
            if 'multimodal' not in config:
                config['multimodal'] = {'enabled': False}

            current = config['multimodal'].get('enabled', False)
            new_value = not current
            config['multimodal']['enabled'] = new_value
            status = "ENABLED" if new_value else "DISABLED"
            changes_made.append(f"Multimodal Visual Context: {status}")
            if new_value:
                changes_made.append("  Workflow: phase1.6 <vol> → phase2 <vol> --enable-multimodal")

        # Toggle smart chunking for massive chapters
        if toggle_smart_chunking:
            if 'translation' not in config:
                config['translation'] = {}
            if 'massive_chapter' not in config['translation']:
                config['translation']['massive_chapter'] = {}

            current = config['translation']['massive_chapter'].get('enable_smart_chunking', True)
            new_value = not current
            config['translation']['massive_chapter']['enable_smart_chunking'] = new_value
            status = "ENABLED" if new_value else "DISABLED"
            changes_made.append(f"Smart Chunking: {status}")

        # Toggle Anthropic key source (.env direct key vs proxy settings key)
        if toggle_proxy_key:
            if 'anthropic' not in config:
                config['anthropic'] = {}

            current = bool(config['anthropic'].get('use_env_key', False))
            new_value = not current
            config['anthropic']['use_env_key'] = new_value
            status = ".env DIRECT" if new_value else "~/.claude/settings.json PROXY"
            changes_made.append(f"Anthropic Key Source: {status}")

        # Explicit Phase 2 endpoint override
        if phase2_endpoint:
            normalized = str(phase2_endpoint).strip().lower()
            if normalized not in {'openrouter', 'official'}:
                logger.error("Invalid phase2 endpoint. Use one of: openrouter, official")
                return

            if 'translation' not in config:
                config['translation'] = {}

            old_endpoint = str(config['translation'].get('phase2_anthropic_endpoint', 'openrouter') or 'openrouter').strip().lower()
            config['translation']['phase2_anthropic_endpoint'] = normalized
            changes_made.append(f"Phase2 Endpoint: {old_endpoint} → {normalized}")
        
        # Save changes if any were made
        if changes_made:
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            
            self._ui_header("Configuration Updated")
            for change in changes_made:
                logger.info(f"  {change}")
            logger.info(f"Saved to: {config_path}")
            logger.info("\nChanges will apply to next translation run.")


def main():
    from pipeline.cli.dispatcher import dispatch_extracted_command, resolve_volume_id_for_args
    from pipeline.cli.parser import build_parser

    parser = build_parser()
    args = parser.parse_args()
    
    if not args.command:
        logger.info("MTL Studio v5.2 CLI")
        logger.info(
            "Use one of: run | phase1 | phase1.5 | pronoun-shift | phase1.55 | phase1.6 | phase1.7 | phase1.7-cp | phase2 | phase4 | "
            "list | status | metadata | schema | bible"
        )
        parser.print_help()
        sys.exit(1)
    
    # Set logging level based on verbose flag
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Verbose mode enabled - showing debug logs")
    else:
        logging.getLogger().setLevel(logging.INFO)

    ui_mode = getattr(args, "ui", "auto")
    no_color = getattr(args, "no_color", False)
    
    controller = PipelineController(verbose=args.verbose, ui_mode=ui_mode, no_color=no_color)
    
    resolve_volume_id_for_args(args, controller, logger)

    # First-pass extracted commands for maintainability and testability.
    # Unhandled commands fall through to the existing legacy dispatch below.
    extracted_exit_code = dispatch_extracted_command(args, controller)
    if extracted_exit_code is not None:
        sys.exit(extracted_exit_code)

    # Execute command
    if args.command == 'run':
        epub_path = Path(args.epub_path)
        skip_multimodal = getattr(args, 'skip_multimodal', False)
        success = controller.run_full_pipeline(epub_path, args.volume_id, skip_multimodal=skip_multimodal)
        sys.exit(0 if success else 1)

    elif args.command == 'phase0':
        # Deprecated: redirects to phase1.6
        success = controller.run_phase0(args.volume_id)
        sys.exit(0 if success else 1)
    
    elif args.command == 'phase1.6':
        full_ln_cache_mode = getattr(args, 'full_ln_cache', 'ask')
        force_override = getattr(args, 'force_override', False)
        success = controller.run_phase1_6(
            args.volume_id,
            standalone=True,
            full_ln_cache_mode=full_ln_cache_mode,
            force_override=force_override,
        )
        sys.exit(0 if success else 1)

    elif args.command == 'phase1.7':
        success = controller.run_phase1_7(
            args.volume_id,
            chapters=getattr(args, 'chapters', None),
            force=getattr(args, 'force', False),
            temperature=getattr(args, 'temperature', 0.3),
            max_output_tokens=getattr(args, 'max_output_tokens', 65535),
        )
        sys.exit(0 if success else 1)

    elif args.command == 'phase1.7-cp':
        success = controller.run_phase1_7_coprocessor(args.volume_id)
        sys.exit(0 if success else 1)
    
    elif args.command == 'multimodal':
        # Run Section 8 first, then Section 10 with multimodal enabled
        controller._ui_header(
            "Multimodal Translator",
            "Section 6 (if needed) -> Section 8 (visual analysis) -> Section 10"
        )
        logger.info("")
        full_ln_cache_mode = getattr(args, 'full_ln_cache', 'ask')
        use_full_ln_cache = controller._resolve_full_ln_cache_mode(
            standalone=True,
            full_ln_cache_mode=full_ln_cache_mode,
            volume_id=args.volume_id,
            manifest=controller.load_manifest(args.volume_id) or {},
            phase_label="Multimodal (Section 8 + 2)",
        )
        manifest = controller.load_manifest(args.volume_id)
        rich_state = (
            manifest.get("pipeline_state", {}).get("rich_metadata_cache", {}).get("status", "not run")
            if manifest else "not run"
        )
        if use_full_ln_cache and rich_state != "completed":
            logger.info("Step 0: Running Section 6 (Rich Metadata Cache)...")
            success_p155 = controller.run_phase1_55(args.volume_id)
            if not success_p155:
                logger.error("Section 6 failed. Aborting multimodal translation.")
                sys.exit(1)
            logger.info("")
        elif not use_full_ln_cache:
            logger.warning("Step 0: Skipping full-LN cache preparation by user request.")

        logger.info("Step 1: Running Section 8 (Visual Analysis)...")
        force_override = getattr(args, 'force_override', False)
        success_p16 = controller.run_phase1_6(
            args.volume_id,
            standalone=False,
            full_ln_cache_mode="off" if not use_full_ln_cache else "on",
            force_override=force_override,
        )
        
        if not success_p16:
            logger.error("Section 8 failed. Aborting multimodal translation.")
            sys.exit(1)
        
        logger.info("")
        logger.info("Step 2: Running Section 10 (Translation with Visual Context)...")
        chapters = getattr(args, 'chapters', None)
        force = getattr(args, 'force', False)
        
        # Keep legacy verbose behavior in plain mode; rich mode has live progress.
        if not args.verbose and not controller.ui.rich_enabled:
            logger.info("ℹ️  Running Section 10 in verbose mode for detailed progress")
            controller = PipelineController(verbose=True, ui_mode=ui_mode, no_color=no_color)
        
        success_p2 = controller.run_phase2(
            args.volume_id, chapters, force,
            enable_gap_analysis=False,
            enable_multimodal=True,  # Always enable multimodal for this command
            full_ln_cache_mode="off" if not use_full_ln_cache else "on",
        )
        
        if success_p2:
            logger.info("")
            logger.info("Multimodal translation complete.")
        
        sys.exit(0 if success_p2 else 1)

    elif args.command == 'cache-inspect':
        detail = getattr(args, 'detail', False)
        success = controller.inspect_visual_cache(args.volume_id, detail=detail)
        sys.exit(0 if success else 1)

    elif args.command == 'phase1':
        epub_path = Path(args.epub_path)
        success = controller.run_phase1(epub_path, args.volume_id, ref_validate=getattr(args, 'ref_validate', False))
        sys.exit(0 if success else 1)
    
    elif args.command == 'phase1.5':
        success = controller.run_phase1_5(args.volume_id)
        sys.exit(0 if success else 1)

    elif args.command == 'phase1.51':
        success = controller.run_phase1_51(args.volume_id)
        sys.exit(0 if success else 1)

    elif args.command == 'phase1.52':
        success = controller.run_phase1_52(args.volume_id)
        sys.exit(0 if success else 1)

    elif args.command == 'pronoun-shift':
        success = controller.run_pronoun_shift_detector(
            args.volume_id,
            target_language=getattr(args, 'target_language', ''),
        )
        sys.exit(0 if success else 1)

    elif args.command == 'phase1.55':
        success = controller.run_phase1_55(args.volume_id)
        sys.exit(0 if success else 1)

    elif args.command == 'phase1.56':
        success = controller.run_phase1_56(
            args.volume_id,
            force=getattr(args, 'force', False),
            enable_prequel_brief_injection=(
                True if getattr(args, 'enable_prequel_brief_injection', False) else None
            ),
        )
        sys.exit(0 if success else 1)

    elif args.command == 'batch':
        success = controller.run_batch(
            args.volume_id,
            force=getattr(args, 'force', False),
            skip_multimodal=getattr(args, 'skip_multimodal', False),
            force_brief=getattr(args, 'force_brief', False),
            enable_prequel_brief_injection=(
                True if getattr(args, 'enable_prequel_brief_injection', False) else None
            ),
            chapters=getattr(args, 'chapters', None),
        )
        sys.exit(0 if success else 1)

    elif args.command == 'phase2':
        # Keep legacy verbose behavior in plain mode; rich mode has live chapter bars.
        if not args.verbose and not controller.ui.rich_enabled:
            logger.info("ℹ️  Running Section 10 in verbose mode (use `--ui rich` for modern progress)")
            controller = PipelineController(verbose=True, ui_mode=ui_mode, no_color=no_color)
        if getattr(args, 'enable_continuity', False):
            logger.warning(
                "Ignoring deprecated --enable-continuity flag. "
                "v5.2 uses Bible/manifest continuity automatically."
            )
        enable_gap_analysis = getattr(args, 'enable_gap_analysis', False)
        enable_multimodal = getattr(args, 'enable_multimodal', False)
        # Default to 'skip' (cache-only): the full-LN cache gate already asks whether to
        # rebuild. Only re-run Section 6 if the user explicitly passes --phase1-55-mode overwrite.
        phase155_mode = getattr(args, 'phase1_55_mode', 'skip')
        full_ln_cache_mode = getattr(args, 'full_ln_cache', 'ask')
        use_batch = getattr(args, 'batch', False)
        success = controller.run_phase2(args.volume_id, args.chapters, args.force,
                                        enable_gap_analysis, enable_multimodal,
                                        phase155_mode=phase155_mode,
                                        full_ln_cache_mode=full_ln_cache_mode,
                                        standalone=True,
                                        batch=use_batch)
        sys.exit(0 if success else 1)
    
    elif args.command == 'phase3':
        controller.run_phase3_instructions(args.volume_id)
        sys.exit(0)
    
    elif args.command == 'phase4':
        success = controller.run_phase4(args.volume_id, args.output)
        sys.exit(0 if success else 1)
    
    elif args.command == 'cleanup':
        success = controller.run_cleanup(args.volume_id, args.dry_run)
        sys.exit(0 if success else 1)
    
    elif args.command == 'cjk-clean':
        success = controller.run_cjk_clean(args.volume_id, args.dry_run)
        sys.exit(0 if success else 1)
    
    elif args.command == 'heal':
        target_lang = None
        if getattr(args, 'vn', False):
            target_lang = 'vn'
        elif getattr(args, 'en', False):
            target_lang = 'en'
        success = controller.run_heal(args.volume_id, args.dry_run, target_lang)
        sys.exit(0 if success else 1)
    
    elif args.command == 'visual-thinking':
        split = getattr(args, 'split', False)
        with_cache = getattr(args, 'with_cache', False)
        filter_type = getattr(args, 'filter', None)
        output_dir = getattr(args, 'output_dir', None)
        success = controller.run_visual_thinking(
            args.volume_id, split=split, with_cache=with_cache,
            filter_type=filter_type, output_dir=output_dir
        )
        sys.exit(0 if success else 1)
    
    elif args.command == 'schema':
        # Invoke schema manipulator agent
        import subprocess
        script_path = PROJECT_ROOT / "scripts" / "schema_manipulator.py"
        
        # Build command
        cmd = [sys.executable, str(script_path), '--volume', args.volume_id]
        cmd.extend(['--action', getattr(args, 'action', 'show')])
        
        if getattr(args, 'name', None):
            cmd.extend(['--name', args.name])
        if getattr(args, 'json', None):
            cmd.extend(['--json', args.json])
        if getattr(args, 'output', None):
            cmd.extend(['--output', args.output])
        
        # Run interactively
        result = subprocess.run(cmd)
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()

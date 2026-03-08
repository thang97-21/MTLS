"""
Metadata Processor Agent (Phase 1.5)
===================================

Handles translation of book metadata ONLY:
- Title (title_en)
- Author (author_en)
- Illustrator (illustrator_en)
- Publisher (publisher_en)
- Chapter titles (chapters[].title_en)
- Character names (character_names mapping)

IMPORTANT: This agent PRESERVES the v3 enhanced schema created by Librarian.
It only updates the translation fields without touching:
- character_profiles
- localization_notes
- keigo_switch configurations
- schema_version

Supports multi-language configuration (EN, VN, etc.)
"""

import json
import hashlib
import logging
import argparse
import sys
import datetime
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set
from pipeline.common.gemini_client import GeminiClient
from pipeline.common.phase_llm_router import PhaseLLMRouter
from pipeline.common.chapter_kind import is_afterword_chapter
from pipeline.common.name_order_normalizer import normalize_payload_names
from pipeline.metadata_processor.schema_autoupdate import SchemaAutoUpdater
from pipeline.metadata_processor.eps_calibration import calibrate_eps_chapters
from pipeline.metadata_processor.eps_signal_extractor import extract_deterministic_eps_signals
from pipeline.config import (
    PROMPTS_DIR, get_target_language, get_language_config, PIPELINE_ROOT, get_phase_model, get_phase_generation_config,
    get_eps_calibration_config,
    get_eps_signal_extraction_config,
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s - %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("MetadataProcessor")

PLACEHOLDER_TOKENS = (
    "[to be filled",
    "[to be determined",
    "[identify",
    "[fill",
    "[protagonist]",
    "[love_interest]",
    "[optional]",
    "tbd",
    "placeholder",
)


def _is_placeholder_string(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    return any(token in text for token in PLACEHOLDER_TOKENS)


def strip_json_placeholders(obj: Any) -> Any:
    """Recursively clear scaffold placeholders from metadata JSON payloads."""
    if isinstance(obj, dict):
        return {k: strip_json_placeholders(v) for k, v in obj.items()}
    if isinstance(obj, list):
        cleaned_items: List[Any] = []
        for item in obj:
            cleaned = strip_json_placeholders(item)
            if isinstance(cleaned, str) and not cleaned.strip():
                continue
            cleaned_items.append(cleaned)
        return cleaned_items
    if isinstance(obj, str):
        if _is_placeholder_string(obj):
            return ""
        return obj
    return obj


def sanitize_json_strings(obj: Any) -> Any:
    """
    Recursively sanitize JSON objects to escape unescaped quotes in string values.

    Fixes Gemini LLM output that may contain unescaped quotes like:
    "key": "value with "quotes" inside"

    Args:
        obj: JSON object (dict, list, str, etc.)

    Returns:
        Sanitized object with properly escaped quotes
    """
    if isinstance(obj, dict):
        return {k: sanitize_json_strings(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_json_strings(item) for item in obj]
    elif isinstance(obj, str):
        # Check if string contains unescaped quotes (not at boundaries)
        # This is a heuristic - if we find " in the middle, escape it
        # But skip if it's already escaped (\")
        if '"' in obj and not obj.startswith('"') and not obj.endswith('"'):
            # Replace unescaped quotes with escaped quotes
            # But preserve already escaped quotes
            obj = obj.replace('\\"', '\x00')  # Temporarily mark escaped quotes
            obj = obj.replace('"', '\\"')      # Escape unescaped quotes
            obj = obj.replace('\x00', '\\"')  # Restore escaped quotes
        return obj
    else:
        return obj


# Japanese to Arabic number mapping
JAPANESE_NUMBERS = {
    '一': '1', '二': '2', '三': '3', '四': '4', '五': '5',
    '六': '6', '七': '7', '八': '8', '九': '9', '十': '10',
    '十一': '11', '十二': '12', '十三': '13', '十四': '14', '十五': '15'
}

# Full-width to half-width number mapping
FULLWIDTH_TO_HALFWIDTH = {
    '０': '0', '１': '1', '２': '2', '３': '3', '４': '4',
    '５': '5', '６': '6', '７': '7', '８': '8', '９': '9'
}

# Vietnamese number word mapping
VIETNAMESE_NUMBERS = {
    'Một': '1', 'Hai': '2', 'Ba': '3', 'Bốn': '4', 'Năm': '5',
    'Sáu': '6', 'Bảy': '7', 'Tám': '8', 'Chín': '9', 'Mười': '10'
}


def extract_volume_number(title: str) -> Optional[int]:
    """
    Extract volume number from Japanese book title using prioritized pattern matching.

    Strategy:
    1. Check for numbers in parentheses: (3), （3）, (三), （三）
    2. Check for trailing space + number: "Title 3", "Title ３", "Title 三"
    3. Check for volume markers: "Vol.3", "Volume 3", "巻3"
    4. Fall back to first number found (lowest priority)

    Handles formats:
    - Arabic numerals: 0-9
    - Full-width numerals: ０-９
    - Kanji numerals: 一, 二, 三, etc.

    Examples:
        "この中に1人、妹がいる! 3" → 3 (not 1)
        "タイトル (5)" → 5
        "タイトル　Vol.4" → 4
        "タイトル　第三巻" → 3

    Args:
        title: Japanese book title from .opf metadata

    Returns:
        Volume number as integer, or None if not found
    """
    import re

    if not title:
        return None

    # Helper function to convert any number format to int
    def normalize_number(num_str: str) -> int:
        # Try full-width conversion
        if num_str in FULLWIDTH_TO_HALFWIDTH:
            num_str = FULLWIDTH_TO_HALFWIDTH[num_str]

        # Try multi-character full-width
        normalized = ''.join(FULLWIDTH_TO_HALFWIDTH.get(c, c) for c in num_str)

        # Try kanji conversion
        if normalized in JAPANESE_NUMBERS:
            normalized = JAPANESE_NUMBERS[normalized]

        # Convert to int
        try:
            return int(normalized)
        except ValueError:
            return None

    # Priority 1: Numbers in parentheses (half-width)
    # Matches: (3), (12), etc.
    match = re.search(r'\(([0-9０-９一二三四五六七八九十]+)\)', title)
    if match:
        vol_num = normalize_number(match.group(1))
        if vol_num:
            return vol_num

    # Priority 2: Numbers in full-width parentheses
    # Matches: （3）, （12）, etc.
    match = re.search(r'（([0-9０-９一二三四五六七八九十]+)）', title)
    if match:
        vol_num = normalize_number(match.group(1))
        if vol_num:
            return vol_num

    # Priority 3: Volume markers (Vol., Volume, 巻, etc.)
    # Matches: "Vol.3", "Volume 3", "第3巻", etc.
    match = re.search(r'(?:Vol\.?|Volume|巻|第)\s*([0-9０-９一二三四五六七八九十]+)', title, re.IGNORECASE)
    if match:
        vol_num = normalize_number(match.group(1))
        if vol_num:
            return vol_num

    # Priority 4: Trailing space + number at end of title
    # Matches: "Title 3", "Title　３", "Title 三"
    match = re.search(r'[\s　]+([0-9０-９一二三四五六七八九十]+)$', title)
    if match:
        vol_num = normalize_number(match.group(1))
        if vol_num:
            return vol_num

    # Priority 5: First number found (lowest priority)
    # This catches edge cases but may be wrong for titles like "この中に1人、妹がいる!"
    match = re.search(r'([0-9０-９]+|[一二三四五六七八九十]+)', title)
    if match:
        vol_num = normalize_number(match.group(1))
        if vol_num:
            return vol_num

    return None


def standardize_chapter_title(title: str, target_language: str = 'vn') -> str:
    """
    Standardize chapter titles to consistent Vietnamese format.
    
    Converts chapter number prefixes while preserving subtitles:
    - プロローグ → Chương Mở Đầu
    - 第X話/第X章 → Chương X (preserves subtitle if present)
    - Chuyện X, Hồi thứ X → Chương X (preserves subtitle if present)
    - 間章 → Chương Giữa
    - エピローグ → Chương Cuối
    - あとがき → Lời Bạt
    
    Examples:
        "第一章　一人ラブコメレース編" → "Chương 1　一人ラブコメレース編"
        "第二話" → "Chương 2"
        "Chuyện Hai: Tình Yêu Đầu" → "Chương 2: Tình Yêu Đầu"
    
    Args:
        title: Original chapter title
        target_language: Target language code (currently only 'vn' supported)
        
    Returns:
        Standardized chapter title with subtitle preserved
    """
    if target_language != 'vn':
        return title  # Only standardize for Vietnamese
    
    title = title.strip()
    original_title = title
    
    # Helper function to extract subtitle (everything after separator)
    def extract_subtitle(text, separators=['　', ':', '：', ' - ', '－']):
        for sep in separators:
            if sep in text:
                parts = text.split(sep, 1)
                if len(parts) == 2 and parts[1].strip():
                    return sep + parts[1]  # Include separator
        return ''
    
    # Prologue patterns (no subtitle expected)
    if title in ['プロローグ', 'Khúc Dạo Đầu', 'Lời Mở Đầu', 'Mở Đầu']:
        return 'Chương Mở Đầu'
    
    # Epilogue patterns (no subtitle expected)
    if title in ['エピローグ', 'Kết Thúc', 'Chương Cuối']:
        return 'Chương Cuối'
    
    # Afterword patterns (no subtitle expected)
    if title in ['あとがき', 'Lời bạt', 'Hậu kí']:
        return 'Lời Bạt'
    
    # Interlude/Side Story patterns (no subtitle expected)
    if title in ['間章', 'Chuyện Bên Lề', 'Màn Giữa', 'Giữa Chương']:
        return 'Chương Giữa'
    
    # Extract chapter numbers from various formats (PRESERVE SUBTITLE)
    
    # Japanese: 第二話 or 第二章 → Chương 2 (+ subtitle if present)
    if title.startswith('第') and ('話' in title or '章' in title):
        # Extract the number between 第 and 話/章
        import re
        match = re.match(r'^第([一二三四五六七八九十]+)([話章])(.*)', title)
        if match:
            jp_num = match.group(1)
            marker = match.group(2)
            subtitle = match.group(3)
            
            # Convert Japanese number to Arabic
            if jp_num in JAPANESE_NUMBERS:
                arabic = JAPANESE_NUMBERS[jp_num]
                return f'Chương {arabic}{subtitle}'
    
    # Vietnamese variants: Chuyện Hai, Hồi thứ năm → Chương 2, Chương 5 (+ subtitle)
    for vn_word, arabic in VIETNAMESE_NUMBERS.items():
        # Match: "Chuyện Hai", "Hồi thứ hai"
        patterns = [
            f'Chuyện {vn_word}',
            f'Chuyện {vn_word.lower()}',
            f'thứ {vn_word.lower()}',
            f'Hồi {vn_word}',
            f'Hồi {vn_word.lower()}'
        ]
        
        for pattern in patterns:
            if pattern in title:
                # Extract subtitle after the pattern
                subtitle = extract_subtitle(title)
                return f'Chương {arabic}{subtitle}'
        
        # Direct match: just the number word (no subtitle expected)
        if title == vn_word or title == vn_word.lower():
            return f'Chương {arabic}'
    
    # Already standardized: Chương X (preserve as-is with any subtitle)
    if title.startswith('Chương '):
        return title
    
    # If no pattern matches, return original
    return title


class MetadataProcessor:
    """
    MetadataProcessor - Phase 1 metadata extraction and translation.
    
    V3 SCHEMA MIGRATION (2026-01-28):
    - REMOVED: .context/name_registry.json creation (legacy system)
    - NOW USES: manifest.json metadata_en.character_profiles (v3 enhanced schema)
    - PRESERVED: Reading name_registry.json for backward compatibility with legacy volumes
    
    Character data now stored in manifest.json with full profiles including:
    - keigo_switch, speech_pattern, character_arc, occurrences tracking
    - Richer metadata vs flat JP→EN name mapping
    """

    LN_MEDIA_HINTS = ("light novel", "ln", "bunko", "novel", "ranobe")
    MANGA_MEDIA_HINTS = ("manga", "comic", "comics", "tankobon", "tankōbon")
    ANIME_MEDIA_HINTS = ("anime", "tv series", "animation", "ova", "movie", "film")

    @staticmethod
    def _build_eps_calibration_snapshot(
        series_id: str,
        resolved_config: Dict[str, Any],
        chapter_count: int,
    ) -> Dict[str, Any]:
        cfg = resolved_config if isinstance(resolved_config, dict) else {}
        enabled = bool(cfg.get("enabled", True))
        canonical_json = json.dumps(cfg, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        checksum = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        return {
            "source": "translation.eps_calibration",
            "series_id": series_id or None,
            "enabled": enabled,
            "applied": bool(enabled and chapter_count > 0),
            "chapter_count": int(max(0, chapter_count)),
            "resolved_config_sha256": checksum,
            "resolved_config_sha256_short": checksum[:8],
            "resolved_config": cfg,
        }

    @staticmethod
    def _enforce_deterministic_eps_coverage(
        strict_enabled: bool,
        non_afterword_chapter_ids: List[str],
        deterministic_signals: Dict[str, Dict[str, Dict[str, float]]],
    ) -> None:
        """Fail fast when strict deterministic extraction coverage requirements are not met."""
        if not strict_enabled:
            return
        if not non_afterword_chapter_ids:
            return

        covered = sum(1 for chapter_id in non_afterword_chapter_ids if deterministic_signals.get(chapter_id))
        if covered == 0:
            uncovered_ids = [chapter_id for chapter_id in non_afterword_chapter_ids if not deterministic_signals.get(chapter_id)]
            logger.info(
                "[EPS] Phase 1.52 strict coverage unmet: uncovered non-afterword chapters=%s",
                ",".join(uncovered_ids),
            )
            raise RuntimeError(
                "Phase 1.52 strict deterministic EPS extraction failed: "
                "zero character signals extracted for non-afterword chapters"
            )
    
    def __init__(
        self,
        work_dir: Path,
        model: str = None,
        target_language: str = None,
        strict_canonical: bool = False,
        canonical_source: str = "bible",
        ignore_sequel: bool = False,
    ):
        """
        Initialize MetadataProcessor.

        Args:
            work_dir: Path to the volume working directory.
            model: Optional Gemini model override.
            target_language: Target language code (e.g., 'en', 'vn').
                            If None, uses current target language from config.
        """
        self.work_dir = work_dir
        self.manifest_path = work_dir / "manifest.json"

        # Language configuration
        self.target_language = target_language if target_language else get_target_language()
        self.lang_config = get_language_config(self.target_language)
        self.language_name = self.lang_config.get('language_name', self.target_language.upper())
        self.language_code = self.lang_config.get('language_code', self.target_language)

        logger.info(f"MetadataProcessor initialized for language: {self.target_language.upper()} ({self.language_name})")

        if not self.manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found at {self.manifest_path}")

        with open(self.manifest_path, 'r', encoding='utf-8') as f:
            self.manifest = json.load(f)

        # Resolve model from config.yaml (translation.phase_models.1) with flash as fallback.
        # Only use the caller-supplied override when explicitly set.
        model = model or get_phase_model("1", "gemini-2.5-flash")
        self.phase_generation = get_phase_generation_config("1")
        logger.info(f"Using model: {model}")

        # We enable caching so that we can load the full Light Novel text
        # and translate titles as thematic hooks rather than standalone metadata.
        self.client = PhaseLLMRouter().get_client(
            "1.5",
            model=model,
            enable_caching=True,
        )
        
        # Language-specific prompt
        prompt_filename = f"metadata_processor_prompt_{self.target_language}.xml"
        language_prompt = PROMPTS_DIR / prompt_filename
        self.prompt_path = language_prompt if language_prompt.exists() else PROMPTS_DIR / "metadata_processor_prompt.xml"
        logger.info(f"Using prompt: {self.prompt_path.name}")

        # Language-specific metadata key suffix
        self.metadata_key = f"metadata_{self.target_language}"  # e.g., metadata_en, metadata_vn
        self.strict_canonical = bool(strict_canonical)
        mode = str(canonical_source or "bible").strip().lower()
        self.canonical_source = mode if mode in {"bible", "manifest"} else "bible"
        self.ignore_sequel = bool(ignore_sequel)

    def _run_schema_autoupdate(self) -> None:
        """
        Phase 1.5 pre-step:
        Auto-fill metadata_en schema fields before title/chapter translation.

        This replaces the manual IDE-agent manifest schema filling workflow.
        """
        logger.info("🤖 Running Schema Agent autoupdate (manifest schema enrichment)...")
        updater = None
        try:
            updater = SchemaAutoUpdater(self.work_dir)
            result = updater.apply(self.manifest)
            metadata_block = self.manifest.get(self.metadata_key, {})
            if isinstance(metadata_block, dict):
                self.manifest[self.metadata_key] = strip_json_placeholders(metadata_block)
            with open(self.manifest_path, 'w', encoding='utf-8') as f:
                json.dump(self.manifest, f, indent=2, ensure_ascii=False)

            updated_keys = ", ".join(result.get("updated_keys", [])) or "none"
            logger.info(
                f"✓ Schema Agent autoupdate merged into manifest "
                f"(keys: {updated_keys}, output_tokens: {result.get('output_tokens', 0)})"
            )
        except Exception as e:
            logger.warning(f"Schema Agent autoupdate failed, continuing with existing schema: {e}")
            try:
                if updater:
                    updater.mark_failed(self.manifest, e)
                else:
                    self.manifest.setdefault("pipeline_state", {})["schema_agent"] = {
                        "status": "failed",
                        "timestamp": datetime.datetime.now().isoformat(),
                        "model": get_phase_model("1.5", "gemini-2.5-flash"),
                        "temperature": get_phase_generation_config("1.5").get("temperature", 0.5),
                        "max_output_tokens": get_phase_generation_config("1.5").get("max_output_tokens", 32768),
                        "error": str(e)[:500],
                    }
                with open(self.manifest_path, 'w', encoding='utf-8') as f:
                    json.dump(self.manifest, f, indent=2, ensure_ascii=False)
            except Exception:
                # Best-effort status write only.
                pass

    def _ensure_ruby_names(self) -> List[Dict[str, Any]]:
        """
        Ruby name extraction is intentionally disabled in MetadataProcessor.

        Canon character metadata is sourced from grounding/canonical pipelines
        (Google Search + bible sync), not ruby extraction fallback.
        """
        logger.debug("Ruby extraction/recording disabled in MetadataProcessor")
        return []

    def _build_full_volume_payload(self) -> Tuple[str, Dict[str, Any]]:
        """
        Assemble the full text of all Japanese chapters in the manifest.
        This provides the LLM with deep context for translating thematic titles.
        """
        chapter_blocks: List[str] = []
        cached_chapter_ids: List[str] = []
        missing_chapter_ids: List[str] = []

        chapters = self.manifest.get("chapters", [])
        for chapter in chapters:
            chapter_id = chapter.get("id", "unknown")
            jp_file = chapter.get("jp_file") or chapter.get("source_file")
            if not jp_file:
                missing_chapter_ids.append(chapter_id)
                continue

            source_path = self.work_dir / "JP" / jp_file
            if not source_path.exists():
                missing_chapter_ids.append(chapter_id)
                continue

            try:
                jp_text = source_path.read_text(encoding="utf-8")
                chapter_blocks.append(f"<CHAPTER id='{chapter_id}'>\n{jp_text}\n</CHAPTER>")
                cached_chapter_ids.append(chapter_id)
            except Exception:
                missing_chapter_ids.append(chapter_id)

        payload = "\n\n---\n\n".join(chapter_blocks)
        stats = {
            "target_chapters": len(chapters),
            "cached_chapters": len(cached_chapter_ids),
            "cached_chapter_ids": cached_chapter_ids,
            "missing_chapter_ids": missing_chapter_ids,
            "volume_chars": len(payload),
        }
        return payload, stats

    def _apply_official_localization_overrides(self, metadata_translated: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prefer official localized metadata discovered by schema autoupdate.

        Applies only when schema step marked official data as usable.
        """
        metadata_en = self.manifest.get("metadata_en", {})
        official = metadata_en.get("official_localization", {})
        if not isinstance(official, dict) or not official:
            return metadata_translated

        def _classify_source_media(source: Dict[str, Any]) -> str:
            if not isinstance(source, dict):
                return "unknown"
            media_field = str(source.get("media_type") or source.get("media") or "").strip().lower()
            combined = " ".join(
                [
                    media_field,
                    str(source.get("title") or "").lower(),
                    str(source.get("url") or "").lower(),
                    str(source.get("notes") or "").lower(),
                ]
            )
            if any(token in combined for token in self.LN_MEDIA_HINTS):
                return "light_novel"
            if any(token in combined for token in self.MANGA_MEDIA_HINTS):
                return "manga"
            if any(token in combined for token in self.ANIME_MEDIA_HINTS):
                return "anime"
            return "unknown"

        def _ln_priority_ok(official_block: Dict[str, Any]) -> bool:
            sources = official_block.get("sources", [])
            if not isinstance(sources, list) or not sources:
                return True
            ln_count = manga_count = anime_count = 0
            for source in sources:
                media = _classify_source_media(source)
                if media == "light_novel":
                    ln_count += 1
                elif media == "manga":
                    manga_count += 1
                elif media == "anime":
                    anime_count += 1
            if ln_count > 0:
                return True
            return not (manga_count > 0 or anime_count > 0)

        should_use = official.get("should_use_official")
        confidence = str(official.get("confidence", "")).lower()
        if should_use is False:
            return metadata_translated
        if should_use is None and confidence not in {"high", "medium"}:
            return metadata_translated
        if not _ln_priority_ok(official):
            logger.warning(
                "Skipping official localization overrides: manga/anime sources found without LN-priority evidence."
            )
            return metadata_translated

        mapping = {
            "volume_title_en": "title_en",
            "author_en": "author_en",
            "publisher_en": "publisher_en",
            "series_title_en": "series_en",
        }
        overridden = []
        for source_key, target_key in mapping.items():
            value = official.get(source_key)
            if isinstance(value, str) and value.strip():
                metadata_translated[target_key] = value.strip()
                overridden.append(target_key)

        if overridden:
            logger.info(
                "🌐 Applied official localization metadata overrides: %s (confidence=%s)",
                ", ".join(overridden),
                confidence or "unknown",
            )

        return metadata_translated
    
    def _update_manifest_preserve_schema(
        self,
        title_en: str,
        author_en: str,
        chapters: Dict[str, Any],
        character_names: Dict[str, str],
        glossary: Dict[str, str] = None,
        extra_fields: Dict[str, Any] = None
    ) -> None:
        """
        Update manifest's metadata_en while PRESERVING v3 enhanced schema.
        
        This method merges translated metadata into existing metadata_en without
        overwriting character_profiles, localization_notes, keigo_switch configs, etc.
        
        Args:
            title_en: Translated title
            author_en: Translated author name
            chapters: Dict mapping chapter_id to chapter payload or title_en
            character_names: Dict mapping JP name to EN name
            glossary: Optional glossary terms
            extra_fields: Optional extra fields to add
        """
        existing_metadata_en = self.manifest.get("metadata_en", {})
        
        # Check if v3 enhanced schema exists
        has_v3_schema = (
            "schema_version" in existing_metadata_en or
            "character_profiles" in existing_metadata_en or
            "localization_notes" in existing_metadata_en or
            "character_voice_fingerprints" in existing_metadata_en or
            "scene_intent_map" in existing_metadata_en
        )
        
        if has_v3_schema:
            logger.info("✨ V3 Enhanced Schema detected - preserving structure")
            
            # Update only translation fields, preserve schema
            existing_metadata_en["title_en"] = title_en
            existing_metadata_en["author_en"] = author_en
            existing_metadata_en["character_names"] = character_names
            existing_metadata_en["target_language"] = self.target_language
            existing_metadata_en["language_code"] = self.language_code
            
            if glossary:
                existing_metadata_en["glossary"] = glossary

            def _merge_chapter_payload(existing_entry: Any, payload: Any, chapter_id: str) -> Dict[str, Any]:
                merged: Dict[str, Any]
                if isinstance(existing_entry, dict):
                    merged = dict(existing_entry)
                else:
                    merged = {}
                merged["id"] = chapter_id

                if isinstance(payload, dict):
                    for key, value in payload.items():
                        if key == "id":
                            continue
                        merged[key] = value
                elif isinstance(payload, str):
                    merged["title_en"] = payload
                return merged

            # Update chapter title_en within existing chapters structure
            if "chapters" in existing_metadata_en:
                existing_chapters = existing_metadata_en["chapters"]
                
                # Handle both list and dict formats
                if isinstance(existing_chapters, list):
                    # List format: [{"id": "chapter_01", "title_en": [...], ...}]
                    for ch in existing_chapters:
                        ch_id = ch.get("id", "")
                        if ch_id in chapters:
                            merged = _merge_chapter_payload(ch, chapters[ch_id], ch_id)
                            ch.clear()
                            ch.update(merged)
                elif isinstance(existing_chapters, dict):
                    # Dict format: {"chapter_01": {"title_jp": ..., "title_en": [...]}}
                    for ch_id, payload in chapters.items():
                        existing_chapters[ch_id] = _merge_chapter_payload(
                            existing_chapters.get(ch_id, {}),
                            payload,
                            ch_id,
                        )
            else:
                # No existing chapters, add simple format
                existing_metadata_en["chapters"] = {
                    ch_id: _merge_chapter_payload({}, payload, ch_id)
                    for ch_id, payload in chapters.items()
                }
            
            # Add extra fields
            if extra_fields:
                for key, value in extra_fields.items():
                    existing_metadata_en[key] = value

            # Coverage guard: merge partial lists with synthesized profile fallbacks
            existing_voice_fps = existing_metadata_en.get("character_voice_fingerprints", [])
            merged_voice_fps = self._augment_voice_fingerprint_coverage(
                existing_voice_fps,
                existing_metadata_en.get("character_profiles", {}),
                existing_metadata_en.get("character_names", {}),
            )
            if merged_voice_fps:
                existing_metadata_en["character_voice_fingerprints"] = merged_voice_fps
                existing_count = len(existing_voice_fps) if isinstance(existing_voice_fps, list) else 0
                if existing_count == 0:
                    logger.info(
                        f"   Backfilled {len(merged_voice_fps)} voice_fingerprints from character_profiles"
                    )
                elif len(merged_voice_fps) > existing_count:
                    logger.info(
                        f"   Augmented voice_fingerprints coverage: {existing_count} -> {len(merged_voice_fps)}"
                    )

            # Add timestamp
            existing_metadata_en["translation_timestamp"] = datetime.datetime.now().isoformat()
            visual_backfilled = self._backfill_visual_identity_non_color(existing_metadata_en)
            if visual_backfilled:
                logger.info(f"   Visual identity backfilled: {visual_backfilled} profile(s)")
            
            self.manifest["metadata_en"] = existing_metadata_en
            self._normalize_name_order_for_manifest()
            
            # Log preserved schema elements
            preserved = []
            if "character_profiles" in existing_metadata_en:
                preserved.append(f"character_profiles({len(existing_metadata_en['character_profiles'])})")
            if "localization_notes" in existing_metadata_en:
                preserved.append("localization_notes")
            if "schema_version" in existing_metadata_en:
                preserved.append(f"schema_version={existing_metadata_en['schema_version']}")
            if "character_voice_fingerprints" in existing_metadata_en:
                preserved.append(f"voice_fingerprints({len(existing_metadata_en['character_voice_fingerprints'])})")
            if "signature_phrases" in existing_metadata_en:
                preserved.append(f"signature_phrases({len(existing_metadata_en['signature_phrases'])})")
            if "scene_intent_map" in existing_metadata_en:
                preserved.append(f"scene_intent_map({len(existing_metadata_en['scene_intent_map'])})")

            logger.info(f"   Preserved: {', '.join(preserved)}")
        else:
            logger.info("📝 No v3 schema found - using simple metadata format")
            
            # Simple format (legacy/new volumes without Librarian schema)
            self.manifest["metadata_en"] = {
                "title_en": title_en,
                "author_en": author_en,
                "chapters": {
                    ch_id: (
                        dict(payload, id=ch_id) if isinstance(payload, dict)
                        else {"id": ch_id, "title_en": payload}
                    )
                    for ch_id, payload in chapters.items()
                },
                "character_names": character_names,
                "glossary": glossary or {},
                "target_language": self.target_language,
                "language_code": self.language_code,
                "timestamp": datetime.datetime.now().isoformat(),
                **(extra_fields or {})
            }
            self._normalize_name_order_for_manifest()
            visual_backfilled = self._backfill_visual_identity_non_color(self.manifest["metadata_en"])
            if visual_backfilled:
                logger.info(f"   Visual identity backfilled: {visual_backfilled} profile(s)")
        
        # Also update chapter title_en in manifest chapters list
        for ch_manifest in self.manifest.get("chapters", []):
            ch_id = ch_manifest.get("id", "")
            if ch_id in chapters:
                payload = chapters[ch_id]
                if isinstance(payload, dict):
                    title_value = payload.get("title_en", "")
                    if title_value:
                        ch_manifest["title_en"] = title_value
                    if "pipeline_review_required" in payload:
                        ch_manifest["pipeline_review_required"] = bool(
                            payload.get("pipeline_review_required", False)
                        )
                elif isinstance(payload, str):
                    ch_manifest["title_en"] = payload
        
        # Update pipeline state
        if "pipeline_state" not in self.manifest:
            self.manifest["pipeline_state"] = {}
        self.manifest["pipeline_state"]["metadata_processor"] = {
            "status": "completed",
            "target_language": self.target_language,
            "timestamp": datetime.datetime.now().isoformat(),
            "schema_preserved": has_v3_schema
        }

    def _backfill_visual_identity_non_color(self, metadata_block: Dict[str, Any]) -> int:
        """
        Ensure character_profiles include non-color visual identity payload.

        This is additive-only and does not overwrite existing explicit values.
        """
        profiles = metadata_block.get("character_profiles", {})
        if not isinstance(profiles, dict):
            return 0

        updated = 0
        for _, profile in profiles.items():
            if not isinstance(profile, dict):
                continue

            existing = profile.get("visual_identity_non_color")
            has_existing = False
            if isinstance(existing, dict):
                has_existing = any(
                    isinstance(v, str) and v.strip() or isinstance(v, list) and len(v) > 0
                    for v in existing.values()
                )
            elif isinstance(existing, str):
                has_existing = bool(existing.strip())
            elif isinstance(existing, list):
                has_existing = any(str(v).strip() for v in existing)
            if has_existing:
                continue

            appearance = profile.get("appearance", "")
            if isinstance(appearance, str) and appearance.strip():
                profile["visual_identity_non_color"] = {
                    "identity_summary": appearance.strip(),
                    "habitual_gestures": [],
                }
                updated += 1

        return updated

    def _manifest_chapter_ids(self) -> List[str]:
        metadata_en = self.manifest.get("metadata_en", {})
        existing = metadata_en.get("chapters", {})
        ids: List[str] = []

        if isinstance(existing, dict):
            ids.extend(str(ch_id).strip() for ch_id in existing.keys() if str(ch_id).strip())
        elif isinstance(existing, list):
            for chapter in existing:
                if not isinstance(chapter, dict):
                    continue
                ch_id = str(chapter.get("id", "")).strip()
                if ch_id:
                    ids.append(ch_id)

        if not ids:
            for chapter in self.manifest.get("chapters", []):
                if not isinstance(chapter, dict):
                    continue
                ch_id = str(chapter.get("id", "")).strip()
                if ch_id:
                    ids.append(ch_id)

        deduped: List[str] = []
        for ch_id in ids:
            if ch_id not in deduped:
                deduped.append(ch_id)
        return deduped

    @staticmethod
    def _afterword_directive() -> str:
        return (
            "Afterword mode: translate as warm, informative, gratitude-forward author note; "
            "bypass EPS/fingerprint/localization-policy and scene-beat constraints."
        )

    def _manifest_chapter_by_id(self, chapter_id: str) -> Dict[str, Any]:
        for chapter in self.manifest.get("chapters", []):
            if not isinstance(chapter, dict):
                continue
            if str(chapter.get("id", "")).strip() == chapter_id:
                return chapter
        return {}

    def _manifest_pipeline_review_flags(self) -> Dict[str, bool]:
        """Return chapter_id -> pipeline_review_required from manifest chapter list."""
        flags: Dict[str, bool] = {}
        for chapter in self.manifest.get("chapters", []):
            if not isinstance(chapter, dict):
                continue
            chapter_id = str(chapter.get("id", "")).strip()
            if not chapter_id:
                continue
            flags[chapter_id] = bool(chapter.get("pipeline_review_required", False))
        return flags

    def _is_afterword_chapter_id(self, chapter_id: str) -> bool:
        chapter = self._manifest_chapter_by_id(chapter_id)
        if not chapter:
            return False
        source_file = str(chapter.get("jp_file") or chapter.get("source_file") or "").strip()
        source_path = (self.work_dir / "JP" / source_file) if source_file else None
        return is_afterword_chapter(chapter, source_path=source_path)

    def _afterword_chapter_ids(self) -> Set[str]:
        return {
            str(chapter.get("id", "")).strip()
            for chapter in self.manifest.get("chapters", [])
            if isinstance(chapter, dict)
            and str(chapter.get("id", "")).strip()
            and self._is_afterword_chapter_id(str(chapter.get("id", "")).strip())
        }

    def _merge_metadata_preferring_existing(
        self,
        existing_value: Any,
        incoming_value: Any,
    ) -> Any:
        """
        Merge metadata blocks while preserving richer existing values.

        Standalone backfill phases should treat an on-disk metadata_<lang>.json
        produced by a richer standalone Phase 1.55 run as authoritative for
        nested rich metadata, while still allowing manifest-only fields to fill
        empty gaps.
        """
        if isinstance(existing_value, dict) and isinstance(incoming_value, dict):
            merged = dict(existing_value)
            for key, incoming_item in incoming_value.items():
                if key in merged:
                    merged[key] = self._merge_metadata_preferring_existing(
                        merged[key],
                        incoming_item,
                    )
                else:
                    merged[key] = incoming_item
            return merged

        if isinstance(existing_value, list) and isinstance(incoming_value, list):
            return existing_value if existing_value else incoming_value

        if existing_value in (None, "", [], {}):
            return incoming_value

        return existing_value

    def _load_existing_language_metadata(self) -> Dict[str, Any]:
        """
        Load the current language metadata, preferring richer file-backed data
        over stale manifest snapshots when both are present.
        """
        manifest_metadata = self.manifest.get(self.metadata_key, {})
        if not isinstance(manifest_metadata, dict):
            manifest_metadata = {}

        merged_metadata = dict(manifest_metadata)
        output_filename = f"metadata_{self.target_language}.json"
        output_path = self.work_dir / output_filename

        if output_path.exists():
            try:
                with open(output_path, "r", encoding="utf-8") as f:
                    file_metadata = json.load(f)
                if isinstance(file_metadata, dict):
                    merged_metadata = self._merge_metadata_preferring_existing(
                        file_metadata,
                        manifest_metadata,
                    )
            except Exception as e:
                logger.warning(f"Failed loading existing {output_filename}: {e}")

        merged_metadata = strip_json_placeholders(merged_metadata)
        self.manifest[self.metadata_key] = merged_metadata
        return merged_metadata

    def _normalize_translated_chapters(self, raw_chapters: Any) -> Dict[str, Dict[str, Any]]:
        chapter_ids = self._manifest_chapter_ids()
        manifest_review_flags = self._manifest_pipeline_review_flags()
        normalized: Dict[str, Dict[str, Any]] = {}

        def apply_afterword_policy(chapter_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
            if not self._is_afterword_chapter_id(chapter_id):
                return payload

            updated = dict(payload)
            updated["chapter_kind"] = "afterword"
            updated["afterword_policy"] = {
                "mode": "bypassed",
                "directive": self._afterword_directive(),
            }
            updated.pop("emotional_proximity_signals", None)
            updated.pop("scene_intents", None)
            return updated

        if isinstance(raw_chapters, dict):
            iterable = list(raw_chapters.items())
            for index, (raw_id, raw_payload) in enumerate(iterable):
                chapter_id = str(raw_id or "").strip() or (
                    chapter_ids[index] if index < len(chapter_ids) else f"chapter_{index + 1:02d}"
                )
                if isinstance(raw_payload, dict):
                    payload = dict(raw_payload)
                else:
                    payload = {"title_en": raw_payload}
                payload["id"] = chapter_id
                if "pipeline_review_required" in payload:
                    payload["pipeline_review_required"] = bool(payload.get("pipeline_review_required"))
                else:
                    payload["pipeline_review_required"] = bool(
                        manifest_review_flags.get(chapter_id, False)
                    )
                normalized[chapter_id] = apply_afterword_policy(chapter_id, payload)
            return normalized

        if isinstance(raw_chapters, list):
            for index, raw_payload in enumerate(raw_chapters):
                if isinstance(raw_payload, dict):
                    payload = dict(raw_payload)
                    chapter_id = str(payload.get("id", "")).strip()
                else:
                    payload = {"title_en": raw_payload}
                    chapter_id = ""
                if not chapter_id:
                    chapter_id = chapter_ids[index] if index < len(chapter_ids) else f"chapter_{index + 1:02d}"
                payload["id"] = chapter_id
                if "pipeline_review_required" in payload:
                    payload["pipeline_review_required"] = bool(payload.get("pipeline_review_required"))
                else:
                    payload["pipeline_review_required"] = bool(
                        manifest_review_flags.get(chapter_id, False)
                    )
                normalized[chapter_id] = apply_afterword_policy(chapter_id, payload)
        return normalized

    def _parse_llm_json_object(self, raw_content: str, *, label: str) -> Dict[str, Any]:
        """Parse model JSON with the same repair logic across metadata subflows."""
        content = (raw_content or "").strip()
        if content.startswith("```json"):
            content = content[7:-3].strip()
        elif content.startswith("```"):
            content = content[3:-3].strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"{label} JSON parse error: {e} — attempting fix...")
            import re
            lines = content.split('\n')
            fixed_lines = []
            for line in lines:
                try:
                    json.loads('{' + line + '}')
                    fixed_lines.append(line)
                except json.JSONDecodeError:
                    match = re.match(r'^(\s*"[^"]*":\s*")(.+)(")$', line)
                    if match:
                        prefix, value, suffix = match.groups()
                        value = value.replace('"', '\\"')
                        fixed_lines.append(prefix + value + suffix)
                    else:
                        fixed_lines.append(line)
            fixed_content = '\n'.join(fixed_lines)
            try:
                parsed = json.loads(fixed_content)
                logger.info(f"  ✓ Fixed {label.lower()} JSON")
                return parsed
            except json.JSONDecodeError:
                logger.error(f"Could not fix {label.lower()} JSON, using fallback")
        return {}

    def _normalize_name_order_for_manifest(self) -> None:
        """Normalize manifest metadata to the declared name-order policy."""
        if not isinstance(self.manifest, dict):
            return
        self.manifest = normalize_payload_names(self.manifest, self.manifest)

    def _normalize_name_order_for_metadata(self, metadata_block: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize a metadata payload against the current manifest policy."""
        if not isinstance(metadata_block, dict):
            return metadata_block
        return normalize_payload_names(metadata_block, self.manifest)

    @staticmethod
    def _canonicalize_name_key(name: str) -> str:
        """Build a relaxed lookup key for EN character labels."""
        if not isinstance(name, str):
            return ""
        return re.sub(r"[^a-z0-9]+", "", name.lower())

    def _build_bible_name_maps(self, bible_sync) -> Tuple[Dict[str, str], Dict[str, str]]:
        """Build JP→canonical and EN-variant→canonical maps from resolved bible."""
        jp_to_canonical: Dict[str, str] = {}
        variant_to_canonical: Dict[str, str] = {}

        bible = getattr(bible_sync, "bible", None)
        if not bible:
            return jp_to_canonical, variant_to_canonical

        chars = bible.get_all_characters()
        if not isinstance(chars, dict):
            return jp_to_canonical, variant_to_canonical

        for jp_name, char_data in chars.items():
            if not isinstance(char_data, dict):
                continue
            canonical = str(char_data.get("canonical_en", "") or "").strip()
            if not canonical:
                continue
            jp_key = str(jp_name or "").strip()
            if jp_key:
                jp_to_canonical[jp_key] = canonical

            for candidate in (
                canonical,
                char_data.get("short_name", ""),
            ):
                label = str(candidate or "").strip()
                if not label:
                    continue
                norm = self._canonicalize_name_key(label)
                if norm:
                    variant_to_canonical[norm] = canonical

        return jp_to_canonical, variant_to_canonical

    def _replace_bible_name_in_text(self, text: str, replacements: Dict[str, str]) -> str:
        """Apply exact/boundary-safe replacements for EN name variants in free text."""
        if not isinstance(text, str) or not text or not replacements:
            return text

        normalized = text
        for wrong, canonical in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
            if not wrong or not canonical:
                continue
            if normalized == wrong:
                normalized = canonical
                continue
            pattern = rf"(?<![A-Za-z0-9]){re.escape(wrong)}(?![A-Za-z0-9])"
            normalized = re.sub(pattern, canonical, normalized)
        return normalized

    def _normalize_bible_names_recursive(
        self,
        payload: Any,
        replacements: Dict[str, str],
    ) -> Any:
        """Normalize EN name variants in dict keys and string values recursively."""
        if isinstance(payload, dict):
            out: Dict[Any, Any] = {}
            for key, value in payload.items():
                new_key = key
                if isinstance(key, str):
                    new_key = replacements.get(key, key)

                normalized_value = self._normalize_bible_names_recursive(value, replacements)

                if new_key in out and isinstance(out[new_key], dict) and isinstance(normalized_value, dict):
                    merged = dict(out[new_key])
                    merged.update(normalized_value)
                    out[new_key] = merged
                else:
                    out[new_key] = normalized_value
            return out

        if isinstance(payload, list):
            return [self._normalize_bible_names_recursive(item, replacements) for item in payload]

        if isinstance(payload, str):
            return self._replace_bible_name_in_text(payload, replacements)

        return payload

    def _reconcile_bible_canonical_names(
        self,
        metadata_translated: Dict[str, Any],
        name_registry: Dict[str, str],
        bible_sync,
    ) -> Tuple[Dict[str, Any], Dict[str, str], int]:
        """Enforce bible canonical EN names in metadata payload and registry."""
        if not isinstance(metadata_translated, dict):
            return metadata_translated, name_registry, 0

        jp_to_canonical, variant_to_canonical = self._build_bible_name_maps(bible_sync)
        if not jp_to_canonical:
            return metadata_translated, name_registry, 0

        replacements: Dict[str, str] = {}
        updated = 0

        normalized_registry = dict(name_registry or {})
        for jp_name, canonical in jp_to_canonical.items():
            existing = normalized_registry.get(jp_name)
            if not isinstance(existing, str) or not existing.strip():
                normalized_registry[jp_name] = canonical
                updated += 1
                continue
            probe = existing.strip()
            mapped = variant_to_canonical.get(self._canonicalize_name_key(probe), canonical)
            if probe != mapped:
                replacements[probe] = mapped
                normalized_registry[jp_name] = mapped
                updated += 1

        profiles = metadata_translated.get("character_profiles", {})
        if isinstance(profiles, dict):
            for profile_key, profile in profiles.items():
                if not isinstance(profile, dict):
                    continue
                canonical = jp_to_canonical.get(str(profile_key or "").strip())
                if not canonical:
                    full_name = str(profile.get("full_name", "") or "").strip()
                    if full_name:
                        canonical = variant_to_canonical.get(self._canonicalize_name_key(full_name))
                if not canonical:
                    continue

                current_full_name = str(profile.get("full_name", "") or "").strip()
                if current_full_name and current_full_name != canonical:
                    replacements[current_full_name] = canonical
                    updated += 1
                profile["full_name"] = canonical

        voice_fps = metadata_translated.get("character_voice_fingerprints", [])
        if isinstance(voice_fps, list):
            for fp in voice_fps:
                if not isinstance(fp, dict):
                    continue
                for field in ("canonical_name_en", "character_en"):
                    current = str(fp.get(field, "") or "").strip()
                    if not current:
                        continue
                    mapped = variant_to_canonical.get(self._canonicalize_name_key(current))
                    if mapped and mapped != current:
                        replacements[current] = mapped
                        fp[field] = mapped
                        updated += 1

        replacements_ci = {
            wrong: canonical
            for wrong, canonical in replacements.items()
            if isinstance(wrong, str) and wrong.strip() and isinstance(canonical, str) and canonical.strip()
        }

        if replacements_ci:
            metadata_translated = self._normalize_bible_names_recursive(metadata_translated, replacements_ci)
            normalized_registry = {
                jp: replacements_ci.get(en, en)
                for jp, en in normalized_registry.items()
            }

        if normalized_registry:
            metadata_translated["character_names"] = normalized_registry

        return metadata_translated, normalized_registry, updated

    def _verify_bible_name_normalization(
        self,
        metadata_translated: Dict[str, Any],
        name_registry: Dict[str, str],
        bible_sync,
    ) -> Tuple[Dict[str, Any], Dict[str, str], int]:
        """Post-verification pass: normalize any remaining bible-registered name drift."""
        if not isinstance(metadata_translated, dict):
            return metadata_translated, name_registry, 0

        metadata_fixed, registry_fixed, first_pass = self._reconcile_bible_canonical_names(
            metadata_translated,
            name_registry,
            bible_sync,
        )
        metadata_fixed, registry_fixed, second_pass = self._reconcile_bible_canonical_names(
            metadata_fixed,
            registry_fixed,
            bible_sync,
        )
        return metadata_fixed, registry_fixed, first_pass + second_pass

    def _collect_remaining_canonical_mismatches(
        self,
        metadata_translated: Dict[str, Any],
        name_registry: Dict[str, str],
        bible_sync,
    ) -> List[str]:
        """Collect remaining mismatches between payload and bible canonical names."""
        jp_to_canonical, variant_to_canonical = self._build_bible_name_maps(bible_sync)
        if not jp_to_canonical:
            return []

        mismatches: List[str] = []

        registry = name_registry if isinstance(name_registry, dict) else {}
        for jp_name, canonical in jp_to_canonical.items():
            current = registry.get(jp_name)
            if not isinstance(current, str) or not current.strip():
                continue
            current = current.strip()
            if current != canonical:
                mapped = variant_to_canonical.get(self._canonicalize_name_key(current))
                if mapped and mapped == canonical:
                    mismatches.append(
                        f"character_names[{jp_name}]='{current}' expected '{canonical}'"
                    )

        profiles = metadata_translated.get("character_profiles", {}) if isinstance(metadata_translated, dict) else {}
        if isinstance(profiles, dict):
            for jp_name, canonical in jp_to_canonical.items():
                profile = profiles.get(jp_name)
                if not isinstance(profile, dict):
                    continue
                current = str(profile.get("full_name", "") or "").strip()
                if not current:
                    continue
                if current != canonical:
                    mapped = variant_to_canonical.get(self._canonicalize_name_key(current))
                    if mapped and mapped == canonical:
                        mismatches.append(
                            f"character_profiles[{jp_name}].full_name='{current}' expected '{canonical}'"
                        )

        voice_fps = metadata_translated.get("character_voice_fingerprints", []) if isinstance(metadata_translated, dict) else []
        if isinstance(voice_fps, list):
            for idx, fp in enumerate(voice_fps):
                if not isinstance(fp, dict):
                    continue
                for field in ("canonical_name_en", "character_en"):
                    current = str(fp.get(field, "") or "").strip()
                    if not current:
                        continue
                    mapped = variant_to_canonical.get(self._canonicalize_name_key(current))
                    if mapped and mapped != current:
                        mismatches.append(
                            f"character_voice_fingerprints[{idx}].{field}='{current}' expected '{mapped}'"
                        )

        # De-duplicate while preserving order
        seen = set()
        uniq: List[str] = []
        for item in mismatches:
            if item in seen:
                continue
            seen.add(item)
            uniq.append(item)
        return uniq

    def _build_standardized_chapter_titles(self) -> List[Dict[str, str]]:
        chapter_titles = []
        for chapter in self.manifest.get("chapters", []):
            original_title = chapter.get("title", "")
            standardized_title = standardize_chapter_title(original_title, self.target_language)
            if standardized_title != original_title:
                logger.info(f"📝 Standardized: '{original_title}' → '{standardized_title}'")
            chapter_titles.append(
                {
                    "id": chapter.get("id", ""),
                    "title_jp": standardized_title,
                }
            )
        return chapter_titles

    def _log_eps_coverage(self, chapters: Dict[str, Dict[str, Any]]) -> int:
        afterword_ids = self._afterword_chapter_ids()
        required_ids = [ch_id for ch_id in chapters.keys() if ch_id not in afterword_ids]
        eps_covered = sum(
            1
            for chapter_id, chapter_payload in chapters.items()
            if chapter_id in required_ids
            and isinstance(chapter_payload, dict)
            and chapter_payload.get("emotional_proximity_signals")
        )
        if required_ids:
            logger.info(
                "[EPS] Chapter signal coverage (story chapters): %s/%s",
                eps_covered,
                len(required_ids),
            )
            if eps_covered == 0:
                logger.warning(
                    "[EPS] Metadata translation returned no emotional_proximity_signals. "
                    "Manifest preservation is fixed, but the model output still needs review."
                )
        elif chapters:
            logger.info("[EPS] No story chapters require EPS coverage (afterword-only selection).")
        return eps_covered

    def _ensure_manifest_series_identity(self, bible_sync=None) -> bool:
        """Persist a stable series identity block on the manifest when bible info exists."""
        if bible_sync is None or not getattr(bible_sync, "series_id", None):
            return False

        existing_series = self.manifest.get("series", {})
        if not isinstance(existing_series, dict):
            existing_series = {}

        changed = False
        if existing_series.get("id") != bible_sync.series_id:
            existing_series["id"] = bible_sync.series_id
            changed = True

        volume_number = existing_series.get("volume_number")
        if volume_number is None:
            raw_idx = self.manifest.get("metadata", {}).get("series_index")
            if isinstance(raw_idx, (int, float)):
                volume_number = int(raw_idx)
            elif isinstance(raw_idx, str):
                try:
                    volume_number = int(raw_idx.strip())
                except ValueError:
                    volume_number = None
            if volume_number is None:
                volume_number = extract_volume_number(self.manifest.get("metadata", {}).get("title", ""))
            if volume_number is not None:
                existing_series["volume_number"] = volume_number
                changed = True

        bible = getattr(bible_sync, "bible", None)
        if bible and isinstance(getattr(bible, "series_title", None), dict):
            series_title = existing_series.get("title", {})
            if not isinstance(series_title, dict):
                series_title = {}
            bible_title = bible.series_title
            title_ja = str(bible_title.get("ja", "") or bible_title.get("jp", "") or "").strip()
            title_en = str(bible_title.get("en", "") or "").strip()
            if title_ja and series_title.get("ja") != title_ja:
                series_title["ja"] = title_ja
                changed = True
            if title_en and series_title.get("en") != title_en:
                series_title["en"] = title_en
                changed = True
            if series_title:
                existing_series["title"] = series_title

        if changed:
            self.manifest["series"] = existing_series
        return changed

    def _ensure_series_pack_skeleton(self, bible_sync=None) -> Optional[Path]:
        """Create/update a minimal series continuity skeleton for future volumes."""
        if bible_sync is None or not getattr(bible_sync, "series_id", None):
            return None

        series_root = PIPELINE_ROOT.parent / "series_continuity" / bible_sync.series_id
        series_root.mkdir(parents=True, exist_ok=True)
        pack_path = series_root / "series_pack.json"

        if pack_path.exists():
            try:
                with pack_path.open("r", encoding="utf-8") as f:
                    pack = json.load(f)
            except Exception:
                pack = {}
        else:
            pack = {}

        if not isinstance(pack, dict):
            pack = {}

        bible = getattr(bible_sync, "bible", None)
        series_title = {}
        if bible and isinstance(getattr(bible, "series_title", None), dict):
            series_title = bible.series_title

        volume_id = str(self.manifest.get("volume_id", "") or self.work_dir.name).strip()
        volume_number = (
            self.manifest.get("series", {}) if isinstance(self.manifest.get("series"), dict) else {}
        ).get("volume_number")
        if volume_number is None:
            volume_number = extract_volume_number(self.manifest.get("metadata", {}).get("title", ""))

        title_en = str(self.manifest.get(self.metadata_key, {}).get("title_en", "") or "").strip()
        title_jp = str(self.manifest.get("metadata", {}).get("title", "") or "").strip()

        volumes = pack.get("volumes", [])
        if not isinstance(volumes, list):
            volumes = []
        volume_entry = {
            "volume_id": volume_id,
            "volume_number": volume_number,
            "bible_id": getattr(bible_sync, "series_id", ""),
            "title_jp": title_jp,
            "title_en": title_en,
            "registered_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        volumes = [v for v in volumes if not (isinstance(v, dict) and v.get("volume_id") == volume_id)]
        volumes.append(volume_entry)
        volumes.sort(key=lambda item: (item.get("volume_number") is None, item.get("volume_number") or 0, item.get("volume_id", "")))

        pack.update(
            {
                "schema_version": "1.0",
                "series_id": getattr(bible_sync, "series_id", ""),
                "series_title": series_title,
                "volumes": volumes,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        )
        if "created_at" not in pack:
            pack["created_at"] = pack["updated_at"]

        with pack_path.open("w", encoding="utf-8") as f:
            json.dump(pack, f, indent=2, ensure_ascii=False)
            f.write("\n")
        logger.info(f"📚 Series pack skeleton synced: {pack_path}")
        return pack_path

    def _extract_voice_fingerprints_from_profiles(
        self,
        character_profiles: Dict[str, Any],
        character_names: Dict[str, str],
    ) -> List[Dict]:
        """
        Fallback: synthesize character_voice_fingerprints from character_profiles.

        Called when the LLM omits character_voice_fingerprints from its output.
        Derives archetype, contraction_rate, and speech patterns from the
        speech_pattern / keigo_switch / personality_traits fields already present
        in character_profiles.
        """
        if not isinstance(character_profiles, dict):
            return []

        # Build JP→EN name map for canonical_name_en lookup
        jp_to_en = {jp: en for jp, en in (character_names or {}).items()}

        # Archetype heuristics from personality_traits / speech_pattern text
        ARCHETYPE_SIGNALS = {
            "tsundere":           ["tsundere", "blunt", "harsh", "cold but warm", "reluctant"],
            "kuudere":            ["kuudere", "stoic", "emotionless", "flat", "expressionless"],
            "yandere":            ["yandere", "obsessive", "possessive", "jealous"],
            "ojou-sama":          ["ojou", "elegant", "refined", "aristocratic", "formal"],
            "genki":              ["genki", "energetic", "cheerful", "bubbly", "enthusiastic"],
            "dandere":            ["dandere", "shy", "quiet", "introverted", "reserved"],
            "narrator-protagonist": ["protagonist", "pov", "narrator", "self-deprecating"],
            "onee-san":           ["older sister", "onee", "mature", "nurturing"],
            "chuunibyou":         ["chuuni", "delusional", "eighth-grader", "dramatic"],
            "stoic-warrior":      ["stoic", "warrior", "serious", "disciplined"],
            "everyman":           ["ordinary", "average", "normal", "everyman"],
        }

        def _coerce_keigo_switch(profile: Dict[str, Any]) -> tuple[Dict[str, Any], str]:
            raw_keigo = profile.get("keigo_switch", {})
            if isinstance(raw_keigo, dict):
                return raw_keigo, json.dumps(raw_keigo, ensure_ascii=False)
            if isinstance(raw_keigo, str):
                return {}, raw_keigo
            if raw_keigo is None:
                return {}, ""
            return {}, str(raw_keigo)

        # Contraction rate heuristics from keigo_switch / speech_pattern
        def _estimate_contraction(profile: Dict) -> float:
            keigo, keigo_text = _coerce_keigo_switch(profile)
            narration = str(keigo.get("narration", "")).lower()
            speech = str(profile.get("speech_pattern", "")).lower()
            combined = f"{narration} {speech} {keigo_text}".lower()
            if any(w in combined for w in ["formal", "polite", "keigo", "refined", "elegant"]):
                return 0.2
            if any(w in combined for w in ["very casual", "slang", "gyaru", "rough", "blunt"]):
                return 0.85
            if any(w in combined for w in ["casual", "friendly", "relaxed"]):
                return 0.65
            return 0.5

        def _detect_archetype(profile: Dict) -> str:
            text = " ".join([
                str(profile.get("personality_traits", "")),
                str(profile.get("speech_pattern", "")),
                str(profile.get("relationship_to_protagonist", "")),
            ]).lower()
            for archetype, signals in ARCHETYPE_SIGNALS.items():
                if any(s in text for s in signals):
                    return archetype
            return "everyman"

        def _sentence_bias(profile: Dict) -> str:
            speech = str(profile.get("speech_pattern", "")).lower()
            if any(w in speech for w in ["short", "terse", "brief", "minimal"]):
                return "short"
            if any(w in speech for w in ["long", "elaborate", "verbose", "detailed"]):
                return "long"
            return "medium"

        fingerprints = []
        for jp_name, profile in character_profiles.items():
            if not isinstance(profile, dict):
                continue
            en_name = (
                profile.get("full_name")
                or jp_to_en.get(jp_name)
                or jp_name
            )
            canonical = str(en_name).strip()

            archetype = _detect_archetype(profile)
            contraction = _estimate_contraction(profile)
            sentence_bias = _sentence_bias(profile)

            # Extract verbal tics from keigo emotional_shifts
            verbal_tics = []
            keigo, keigo_text = _coerce_keigo_switch(profile)
            shifts = keigo.get("emotional_shifts", {})
            if isinstance(shifts, dict):
                for state, desc in shifts.items():
                    if isinstance(desc, str) and len(desc) < 60:
                        verbal_tics.append(desc)
            elif keigo_text and len(keigo_text) < 120:
                verbal_tics.append(keigo_text)

            fp = {
                "canonical_name_en": canonical,
                "archetype": archetype,
                "contraction_rate": contraction,
                "sentence_length_bias": sentence_bias,
                "forbidden_vocabulary": [],
                "preferred_vocabulary": [],
                "signature_phrases": [],
                "verbal_tics": verbal_tics[:3],
                "emotional_patterns": {},
                "dialogue_samples": [],
                "_source": "fallback_from_character_profiles",
            }
            fingerprints.append(fp)

        return fingerprints

    def _augment_voice_fingerprint_coverage(
        self,
        existing_fingerprints: Any,
        character_profiles: Dict[str, Any],
        character_names: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        """
        Ensure fingerprint coverage is complete for available character profiles.

        Partial LLM outputs are merged with synthesized fallbacks for missing
        canonical names so downstream Translator voice indexing does not regress.
        """
        merged: List[Dict[str, Any]] = []
        seen: set[str] = set()

        if isinstance(existing_fingerprints, list):
            for fp in existing_fingerprints:
                if not isinstance(fp, dict):
                    continue
                canonical = str(fp.get("canonical_name_en", "") or "").strip()
                if not canonical:
                    continue
                key = canonical.lower()
                if key in seen:
                    continue
                seen.add(key)
                merged.append(fp)

        synthesized = self._extract_voice_fingerprints_from_profiles(
            character_profiles,
            character_names,
        )
        for fp in synthesized:
            canonical = str(fp.get("canonical_name_en", "") or "").strip()
            if not canonical:
                continue
            key = canonical.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(fp)

        return merged

    def detect_sequel_parent(self) -> Optional[Dict]:
        """
        Resolve sequel continuity diagnostics from the series bible only.

        Guardrails:
        - Never scans sibling volumes' local metadata JSON files.
        - Never cross-triggers from mismatched metadata_<lang> target settings.
        - Requires a known current volume index (>1) before enabling sequel diagnostics.
        """
        if self.ignore_sequel:
            logger.info("Skipping sequel detection: --ignore-sequel enabled")
            return None

        current_title = self.manifest.get("metadata", {}).get("title", "")
        if not current_title:
            return None

        metadata_block = self.manifest.get(self.metadata_key, {})
        if not isinstance(metadata_block, dict):
            metadata_block = {}
        declared_target = str(metadata_block.get("target_language", "") or "").strip().lower()
        if declared_target and declared_target != self.target_language:
            logger.info(
                f"Skipping sequel detection: {self.metadata_key}.target_language="
                f"{declared_target} != config target_language={self.target_language}"
            )
            return None
        if not metadata_block:
            for key, value in self.manifest.items():
                if not (isinstance(key, str) and key.startswith("metadata_")):
                    continue
                if key == self.metadata_key or not isinstance(value, dict):
                    continue
                other_target = str(value.get("target_language", "") or "").strip().lower()
                if other_target and other_target != self.target_language:
                    logger.info(
                        "Skipping sequel detection: found metadata from a different target language "
                        f"({key}.target_language={other_target}, config={self.target_language})"
                    )
                    return None

        # Determine current volume index from series_index (preferred) or title fallback.
        current_vol_num = None
        series_index = self.manifest.get("metadata", {}).get("series_index")
        if isinstance(series_index, int):
            current_vol_num = series_index
        elif isinstance(series_index, str):
            try:
                current_vol_num = int(series_index.strip())
            except ValueError:
                current_vol_num = None
        elif isinstance(series_index, float):
            current_vol_num = int(series_index)
        if current_vol_num is None:
            current_vol_num = extract_volume_number(current_title)
        if current_vol_num is None or current_vol_num <= 1:
            return None

        # Resolve bible and derive predecessor from bible volume registry.
        try:
            from pipeline.metadata_processor.bible_sync import BibleSyncAgent
            from pipeline.config import PIPELINE_ROOT

            bible_sync = BibleSyncAgent(self.work_dir, PIPELINE_ROOT)
            if not bible_sync.resolve(self.manifest):
                return None
            bible = getattr(bible_sync, "bible", None)
            if not bible:
                return None
        except Exception as e:
            logger.debug(f"Sequel bible resolution skipped: {e}")
            return None

        registered = []
        for item in bible.volumes_registered:
            if not isinstance(item, dict):
                continue
            raw_idx = item.get("index")
            try:
                idx = int(raw_idx)
            except (TypeError, ValueError):
                continue
            if idx < current_vol_num:
                registered.append(
                    {
                        "index": idx,
                        "title": str(item.get("title", "") or "").strip(),
                        "volume_id": str(item.get("volume_id", "") or "").strip(),
                    }
                )

        if not registered:
            return None

        best_prequel = sorted(registered, key=lambda x: x["index"], reverse=True)[0]

        character_roster: Dict[str, str] = {}
        character_profiles: Dict[str, Dict[str, Any]] = {}
        eps_continuity: Dict[str, Dict[str, Any]] = {}
        for jp_name, char_data in bible.get_all_characters().items():
            if not isinstance(char_data, dict):
                continue
            canonical_en = str(char_data.get("canonical_en", "") or "").strip()
            if not canonical_en:
                continue

            character_roster[jp_name] = canonical_en
            profile: Dict[str, Any] = {"full_name": canonical_en}

            nickname = str(char_data.get("short_name", "") or "").strip()
            if nickname:
                profile["nickname"] = nickname

            category = str(char_data.get("category", "") or "").strip()
            if category:
                profile["relationship_to_protagonist"] = category

            affiliation = str(char_data.get("affiliation", "") or "").strip()
            if affiliation:
                profile["origin"] = affiliation

            notes = str(char_data.get("notes", "") or "").strip()
            if notes:
                traits = [p.strip() for p in re.split(r"[|,]", notes) if p.strip()]
                if traits:
                    profile["personality_traits"] = traits[:8]

            visual_identity = char_data.get("visual_identity_non_color")
            if isinstance(visual_identity, (dict, list, str)) and visual_identity:
                profile["visual_identity_non_color"] = visual_identity

            latest_eps = char_data.get("latest_eps_state")
            if isinstance(latest_eps, dict):
                profile["latest_eps_state"] = latest_eps
                eps_continuity[canonical_en] = latest_eps

            character_profiles[jp_name] = profile

        glossary = bible.flat_glossary()

        localization_notes = metadata_block.get("localization_notes", {})
        if not isinstance(localization_notes, dict):
            localization_notes = {}

        series_title = ""
        series_title_data = getattr(bible, "series_title", {})
        if isinstance(series_title_data, dict):
            series_title = str(
                series_title_data.get("en")
                or series_title_data.get("ja")
                or ""
            ).strip()

        title_seed = str(
            metadata_block.get("title_en")
            or series_title
            or current_title
        ).strip()
        author_seed = str(
            metadata_block.get("author_en")
            or self.manifest.get("metadata", {}).get("author", "")
        ).strip()

        logger.info(
            f"✓ Sequel source resolved from bible: {bible.series_id} "
            f"(vol {best_prequel['index']} → vol {current_vol_num})"
        )

        return {
            "title_en": title_seed,
            "author_en": author_seed,
            "character_roster": character_roster,
            "character_profiles": character_profiles,
            "glossary": glossary,
            "localization_notes": localization_notes,
            "eps_continuity": eps_continuity,
            "chapters": [],  # Bible currently tracks canonical terms, not chapter title map.
            "source_volume": (
                best_prequel["title"]
                or best_prequel["volume_id"]
                or f"Volume {best_prequel['index']}"
            ),
            "prequel_volume_number": best_prequel["index"],
            "inheritance_source": "series_bible",
            "bible_id": bible.series_id,
        }
    
    def _batch_translate_ruby(
        self,
        ruby_names: List[Dict],
        parent_data: Optional[Dict] = None
    ) -> Dict[str, str]:
        """
        Batch translate ruby-extracted character names.

        Returns:
            Dict mapping Japanese names to translated names
        """
        # Filter out kira-kira names (stylistic ruby, not real character names)
        real_names = [n for n in ruby_names if n.get("name_type") != "kirakira"]
        
        if len(real_names) < len(ruby_names):
            logger.info(f"Filtered out {len(ruby_names) - len(real_names)} kira-kira names (stylistic ruby)")
        
        # Filter out inherited entries
        inherited_names = parent_data.get("character_roster", {}) if parent_data else {}

        # Only translate NEW entries
        new_names = [n for n in real_names if n["kanji"] not in inherited_names]

        logger.info(f"Romanizing {len(new_names)} names")

        if not new_names:
            logger.info("No new names to translate (all inherited)")
            return inherited_names.copy()

        # Build batch translation prompt - language-specific
        if self.target_language == 'vn':
            # Vietnamese-specific name handling
            prompt_parts = [
                f"Translate the following character names from Japanese to {self.language_name}.",
                "Follow these rules:\n",
                "CHARACTER NAMES:",
                "1. Apply Hepburn romanization (keep Japanese pronunciation)",
                "2. Long vowel rules:",
                "   - For 'ou' sounds (こう, そう, etc.): KEEP both vowels (Kouki not Koki, Sousuke not Sosuke)",
                "   - For 'uu' sounds (ゆう, しゅう): Drop second 'u' (Yuki not Yuuki, Ryota not Ryouta)",
                "   - For 'ei' sounds: Use 'ei' (Kei not Kē)",
                "3. Surname-first order: Shinonome Sena not Sena Shinonome",
                "4. Match ruby reading exactly (東雲《しののめ》→ Shinonome, 康貴《こうき》→ Kouki)",
                "5. Keep romanized names (do not translate to Vietnamese equivalents)\n",
                "Output as JSON: {\"names\": {\"jp\": \"romanized\"}}\n"
            ]
        else:
            # English (default) name handling
            prompt_parts = [
                f"Translate the following character names from Japanese to {self.language_name}.",
                "Follow these rules:\n",
                "CHARACTER NAMES:",
                "1. Apply Hepburn romanization (natural English phonetics)",
                "2. Long vowel rules:",
                "   - For 'ou' sounds (こう, そう, etc.): KEEP both vowels (Kouki not Koki, Sousuke not Sosuke)",
                "   - For 'uu' sounds (ゆう, しゅう): Drop second 'u' (Yuki not Yuuki, Ryota not Ryouta)",
                "   - For 'ei' sounds: Use 'ei' (Kei not Kē)",
                "3. Surname-first order: Shinonome Sena not Sena Shinonome",
                "4. Match ruby reading exactly (東雲《しののめ》→ Shinonome, 康貴《こうき》→ Kouki)",
                "5. Consider character context for cultural adaptation\n",
                "Output as JSON: {\"names\": {\"jp\": \"en\"}}\n"
            ]
        
        # Add inherited context if present
        if inherited_names:
            prompt_parts.append("\nEXISTING CHARACTERS (maintain consistency):")
            for jp, en in list(inherited_names.items())[:10]:  # Show first 10
                prompt_parts.append(f"  {jp} → {en}")
            if len(inherited_names) > 10:
                prompt_parts.append(f"  ... and {len(inherited_names)-10} more")
        
        # Add new character names to translate
        prompt_parts.append("\nNEW CHARACTERS TO TRANSLATE:")
        for entry in new_names:
            kanji = entry["kanji"]
            ruby = entry["ruby"]
            context = entry["context"][:100]  # Truncate context
            prompt_parts.append(f"  {kanji}《{ruby}》")
            prompt_parts.append(f"    Context: \"{context}...\"")
        
        prompt = "\n".join(prompt_parts)
        
        # Call Gemini
        try:
            response = self.client.generate(
                prompt=prompt,
                temperature=self.phase_generation.get("temperature", 0.3),
                max_output_tokens=self.phase_generation.get("max_output_tokens", 32768),
                generation_config=self.phase_generation,
            )

            # Parse response
            content = response.content.strip()
            if content.startswith("```json"):
                content = content[7:-3].strip()
            elif content.startswith("```"):
                content = content[3:-3].strip()

            translations = json.loads(content)

        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error at line {e.lineno}, col {e.colno}: {e.msg}")
            logger.warning("Attempting to fix unescaped quotes...")

            # Try to fix by escaping unescaped quotes
            import re
            lines = content.split('\n')
            fixed_lines = []
            for line in lines:
                # Skip if already valid JSON line
                try:
                    json.loads('{' + line + '}')
                    fixed_lines.append(line)
                except json.JSONDecodeError:
                    # Try to escape unescaped quotes within the value
                    match = re.match(r'^(\s*"[^"]*":\s*")(.+)(")$', line)
                    if match:
                        prefix, value, suffix = match.groups()
                        value = value.replace('"', '\\"')
                        fixed_lines.append(prefix + value + suffix)
                    else:
                        fixed_lines.append(line)

            fixed_content = '\n'.join(fixed_lines)
            try:
                translations = json.loads(fixed_content)
                logger.info("Successfully fixed JSON by escaping quotes")
            except json.JSONDecodeError:
                logger.error("Could not fix JSON parse error, using empty result")
                translations = {"names": {}}
            
            # Merge with inherited
            name_registry = {**inherited_names, **translations.get("names", {})}
            
            logger.info(f"✓ Translated {len(translations.get('names', {}))} character names")
            
            return name_registry
            
        except Exception as e:
            logger.error(f"Batch translation failed: {e}")
            # Fallback: return inherited only
            return inherited_names.copy()

    def _sync_bible_post_metadata(
        self,
        bible_sync=None,
        bible_pull=None,
    ) -> None:
        """Finalize Bible continuity after manifest write.

        Ensures sequel and non-sequel paths both:
        - resolve series bible
        - persist manifest.bible_id when detected
        - push/register current volume into bible index
        - emit continuity diff report
        """
        try:
            if bible_sync is None:
                from pipeline.metadata_processor.bible_sync import BibleSyncAgent
                from pipeline.config import PIPELINE_ROOT
                bible_sync = BibleSyncAgent(self.work_dir, PIPELINE_ROOT)

            if not getattr(bible_sync, "bible", None):
                if not bible_sync.resolve(self.manifest):
                    return

            if bible_sync.series_id and self.manifest.get("bible_id") != bible_sync.series_id:
                self.manifest["bible_id"] = bible_sync.series_id
                self._ensure_manifest_series_identity(bible_sync)
                with open(self.manifest_path, "w", encoding="utf-8") as f:
                    json.dump(self.manifest, f, indent=2, ensure_ascii=False)
                logger.info(f"📖 Linked manifest to bible_id: {bible_sync.series_id}")

            push_result = bible_sync.push(
                self.manifest,
                canonical_source=self.canonical_source,
            )
            self._ensure_manifest_series_identity(bible_sync)
            self._ensure_series_pack_skeleton(bible_sync)
            with open(self.manifest_path, "w", encoding="utf-8") as f:
                json.dump(self.manifest, f, indent=2, ensure_ascii=False)
            logger.info(f"📖 Bible PUSH complete: {push_result.summary()}")

            try:
                bible_sync.generate_continuity_report(
                    self.manifest,
                    pull_result=bible_pull,
                    push_result=push_result,
                )
            except Exception as report_err:
                logger.warning(f"Continuity report generation failed: {report_err}")
        except Exception as e:
            logger.warning(f"Bible sync (post-metadata) failed: {e}")

    def process_metadata(self):
        """Translate metadata and save to metadata_en.json."""
        logger.info(f"Processing metadata for {self.work_dir.name}")

        # Prepare context for LLM
        original_metadata = self.manifest.get("metadata", {})

        # Pre-process chapter titles: standardize format BEFORE translation
        chapter_titles = self._build_standardized_chapter_titles()

        # Ruby extraction remains part of the standard flow for all volumes.
        ruby_names = self._ensure_ruby_names()

        # Check for sequel continuity diagnostics
        parent_data = self.detect_sequel_parent()

        # New flow:
        # Librarian Extraction -> Schema Agent autoupdate -> Bible Sync -> Title/Chapter translation -> Phase 2
        self._run_schema_autoupdate()

        # ── Bible Auto-Sync: PULL (Bible → Manifest) ─────────────
        # Inherit canonical terms from the series bible BEFORE ruby
        # translation, so batch_translate_ruby can skip known names.
        bible_sync = None
        bible_pull = None
        bible_known_names = {}
        try:
            from pipeline.metadata_processor.bible_sync import BibleSyncAgent
            from pipeline.config import PIPELINE_ROOT
            bible_sync = BibleSyncAgent(self.work_dir, PIPELINE_ROOT)
            if bible_sync.resolve(self.manifest):
                if bible_sync.series_id and self.manifest.get("bible_id") != bible_sync.series_id:
                    self.manifest["bible_id"] = bible_sync.series_id
                    self._ensure_manifest_series_identity(bible_sync)
                    # Persist immediately so bible linkage survives mid-phase failures.
                    with open(self.manifest_path, "w", encoding="utf-8") as f:
                        json.dump(self.manifest, f, indent=2, ensure_ascii=False)
                    logger.info(f"📖 Linked manifest to bible_id: {bible_sync.series_id}")
                bible_pull = bible_sync.pull(
                    self.manifest,
                    target_language=self.target_language,
                )
                bible_known_names = bible_pull.known_characters
                logger.info(f"📖 Bible PULL complete: {bible_pull.summary()}")
        except Exception as e:
            logger.warning(f"Bible sync (pull) skipped: {e}")
            bible_sync = None

        inheritance_context = ""

        # Append bible context block if available
        if bible_pull and bible_pull.context_block:
            inheritance_context += bible_pull.context_block

        if parent_data:
            match_title = parent_data.get('title_en', 'Unknown')
            match_author = parent_data.get('author_en', 'Unknown')
            character_roster = parent_data.get('character_roster', {})
            glossary = parent_data.get('glossary', {})
            eps_continuity = parent_data.get("eps_continuity", {})
            
            logger.info(f"✨ Sequel continuity detected from series bible: {match_title}")
            logger.info(f"   Characters: {len(character_roster)}, Glossary terms: {len(glossary)}")
            
            # Build supplemental sequel continuity context for the LLM.
            context_parts = [
                "\n" + "="*60,
                "IMPORTANT - SEQUEL CONTINUITY (MAINTAIN CONSISTENCY)",
                "="*60,
                f"\nSeries Title: {match_title}",
                f"Author Name: {match_author}\n"
            ]
            
            # Add character roster
            if character_roster:
                context_parts.append("\nCHARACTER ROSTER (use these exact spellings):")
                for jp_name, en_name in character_roster.items():
                    context_parts.append(f"  {jp_name} → {en_name}")
                context_parts.append("")
            
            # Add glossary terms
            if glossary:
                context_parts.append("GLOSSARY (established terminology):")
                for jp_term, en_term in glossary.items():
                    context_parts.append(f"  {jp_term} → {en_term}")
            context_parts.append("")

            if eps_continuity and not (bible_pull and getattr(bible_pull, "eps_states_inherited", 0)):
                context_parts.append("LATEST EPS CONTINUITY (carry forward as sequel baseline):")
                for character_name, eps_state in eps_continuity.items():
                    if not isinstance(eps_state, dict):
                        continue
                    eps_score = eps_state.get("eps_score")
                    try:
                        eps_text = f"{float(eps_score):+.2f}"
                    except (TypeError, ValueError):
                        eps_text = "n/a"
                    band = str(eps_state.get("voice_band", "")).strip().upper() or "NEUTRAL"
                    source_volume = str(eps_state.get("source_volume_id", "")).strip()
                    source_chapter = str(eps_state.get("source_chapter_id", "")).strip()
                    source_bits = [bit for bit in (source_volume, source_chapter) if bit]
                    source_text = f" | source: {' / '.join(source_bits)}" if source_bits else ""
                    context_parts.append(
                        f"  {character_name}: EPS {eps_text} [{band}]{source_text}"
                    )
                context_parts.append("")
            
            context_parts.append("="*60)
            context_parts.append("Ensure all character names and terms above remain consistent.")
            context_parts.append("Use these entries as continuity guidance; do not copy stale volume-local metadata.\n")
            
            inheritance_context += "\n".join(context_parts)
        
        # Batch translate ruby-extracted character names
        # Pre-populate with bible known names so they can be skipped
        if bible_known_names:
            name_registry = dict(bible_known_names)  # Bible as base
            logger.info(f"   Pre-populated {len(bible_known_names)} bible character names → ruby skip list")
        else:
            name_registry = {}

        if ruby_names:
            logger.info("Batch translating ruby entries...")
            ruby_translated = self._batch_translate_ruby(
                ruby_names, parent_data
            )
            # Merge: ruby translated names override bible (for newly discovered chars)
            name_registry.update(ruby_translated)
        # else: name_registry already has bible names (or empty dict)
        
        # No term glossary in simplified version
        term_glossary = {}
        
        with open(self.prompt_path, 'r', encoding='utf-8') as f:
            system_prompt = f.read()
            
        prompt = (
            f"Original Metadata:\n{json.dumps(original_metadata, indent=2, ensure_ascii=False)}\n\n"
            f"Chapter Titles:\n{json.dumps(chapter_titles, indent=2, ensure_ascii=False)}"
            f"{inheritance_context}"
        )
        
        full_volume_text, _ = self._build_full_volume_payload()
        cache_name = None
        if full_volume_text:
            logger.info("Building full text cache for thematic metadata translation...")
            volume_id = self.manifest.get("volume_id", self.work_dir.name)
            cache_name = self.client.create_cache(
                model=self.client.model,
                system_instruction=system_prompt,
                contents=[full_volume_text],
                display_name=f"{volume_id}_metadata"
            )

        response = self.client.generate(
            prompt=prompt,
            system_instruction=system_prompt,
            temperature=self.phase_generation.get("temperature", 0.3),
            max_output_tokens=self.phase_generation.get("max_output_tokens", 32768),
            generation_config=self.phase_generation,
            cached_content=cache_name
        )

        metadata_translated = self._parse_llm_json_object(
            getattr(response, "content", ""),
            label="Metadata",
        )
        metadata_translated = self._normalize_name_order_for_metadata(metadata_translated)

        # Continue with normal processing
        metadata_translated = self._apply_official_localization_overrides(metadata_translated)

        # Add character names and glossary to metadata
        if name_registry:
            metadata_translated['character_names'] = name_registry
        if term_glossary:
            metadata_translated['glossary'] = term_glossary

        # Canonical reconciliation (selectable source of truth) + post-verification
        if bible_sync and getattr(bible_sync, "bible", None) and self.canonical_source == "bible":
            metadata_translated, name_registry, normalized_count = self._verify_bible_name_normalization(
                metadata_translated,
                name_registry,
                bible_sync,
            )
            if normalized_count:
                logger.info(
                    "📖 Canonical name normalization: enforced %s bible-registered entries",
                    normalized_count,
                )

            remaining_mismatches = self._collect_remaining_canonical_mismatches(
                metadata_translated,
                name_registry,
                bible_sync,
            )
            if remaining_mismatches:
                logger.warning(
                    "⚠️  Canonical post-verification: %s mismatch(es) remain",
                    len(remaining_mismatches),
                )
                for item in remaining_mismatches[:20]:
                    logger.warning("   %s", item)
                if self.strict_canonical:
                    raise RuntimeError(
                        "Strict canonical mode failed: "
                        f"{len(remaining_mismatches)} mismatch(es) remain after post-verification"
                    )
        elif bible_sync and getattr(bible_sync, "bible", None):
            logger.info(
                "📖 Canonical normalization source: manifest (bible reconciliation skipped by option)"
            )

        # Add language metadata
        metadata_translated['target_language'] = self.target_language
        metadata_translated['language_code'] = self.language_code

        # Coverage guard: merge partial LLM output with synthesized profile fallbacks
        existing_voice_fps = metadata_translated.get('character_voice_fingerprints', [])
        merged_voice_fps = self._augment_voice_fingerprint_coverage(
            existing_voice_fps,
            metadata_translated.get('character_profiles', {}),
            metadata_translated.get('character_names', {}),
        )
        if merged_voice_fps:
            metadata_translated['character_voice_fingerprints'] = merged_voice_fps
            before_count = len(existing_voice_fps) if isinstance(existing_voice_fps, list) else 0
            if before_count == 0:
                logger.info(f"   Fallback extracted {len(merged_voice_fps)} voice_fingerprints from character_profiles")
            elif len(merged_voice_fps) > before_count:
                logger.info(
                    f"   Augmented voice_fingerprints coverage: {before_count} -> {len(merged_voice_fps)}"
                )

        # Extract Koji Fox character voice/arc fields for schema preservation
        koji_fox_fields = {}
        for field in ['character_voice_fingerprints', 'signature_phrases', 'scene_intent_map']:
            if field in metadata_translated and metadata_translated[field]:
                koji_fox_fields[field] = metadata_translated[field]
                logger.info(f"   Extracted Koji Fox field: {field}")

        metadata_translated["chapters"] = self._normalize_translated_chapters(
            metadata_translated.get("chapters", {})
        )
        metadata_translated = self._normalize_name_order_for_metadata(metadata_translated)
        self._log_eps_coverage(metadata_translated["chapters"])

        # Save to language-specific metadata file (e.g., metadata_en.json, metadata_vn.json)
        output_filename = f"metadata_{self.target_language}.json"
        output_path = self.work_dir / output_filename

        # Sanitize JSON to fix any unescaped quotes from LLM output
        metadata_translated = sanitize_json_strings(metadata_translated)
        metadata_translated = strip_json_placeholders(metadata_translated)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(metadata_translated, f, indent=2, ensure_ascii=False)

        logger.info(f"Metadata translated to {self.language_name} and saved to {output_path}")

        # Save glossary to manifest (v3 schema)
        context_dir = self.work_dir / ".context"
        context_dir.mkdir(exist_ok=True)

        # NOTE: name_registry.json DEPRECATED - v3 schema uses manifest.json character_profiles
        # Character names now stored in manifest.json metadata_en.character_names

        if term_glossary:
            # Update manifest glossary
            if "glossary" not in self.manifest:
                self.manifest["glossary"] = {}
            self.manifest["glossary"].update(term_glossary)
            logger.info(f"Added {len(term_glossary)} terms to glossary")

        # Extract chapter translations to dict format
        chapter_translations = {}
        for ch_id, chapter_payload in metadata_translated.get("chapters", {}).items():
            if not isinstance(chapter_payload, dict):
                chapter_translations[ch_id] = chapter_payload
                continue

            payload = dict(chapter_payload)
            title_value = payload.get("title_en", payload.get(f"title_{self.target_language}", ""))
            if title_value:
                payload["title_en"] = title_value
            chapter_translations[ch_id] = payload

        # Update manifest - PRESERVE v3 enhanced schema
        self._update_manifest_preserve_schema(
            title_en=metadata_translated.get("title_en", ""),
            author_en=metadata_translated.get("author_en", ""),
            chapters=chapter_translations,
            character_names=name_registry,
            glossary=term_glossary,
            extra_fields=koji_fox_fields if koji_fox_fields else None
        )

        metadata_block = self.manifest.get("metadata_en", {})
        if isinstance(metadata_block, dict):
            self.manifest["metadata_en"] = strip_json_placeholders(metadata_block)

        with open(self.manifest_path, 'w', encoding='utf-8') as f:
            json.dump(self.manifest, f, indent=2, ensure_ascii=False)

        # ── Bible Auto-Sync: PUSH (Manifest → Bible) ─────────
        # Export newly discovered terms and register volume.
        self._sync_bible_post_metadata(bible_sync=bible_sync, bible_pull=bible_pull)

    def process_eps_only(self):
        """Backfill only chapter-level EPS data without touching the rest of metadata."""
        logger.info(f"Processing EPS-only backfill for {self.work_dir.name}")

        current_metadata = self._load_existing_language_metadata()

        output_filename = f"metadata_{self.target_language}.json"
        output_path = self.work_dir / output_filename

        chapter_titles = self._build_standardized_chapter_titles()
        character_names = current_metadata.get("character_names", {})
        if not isinstance(character_names, dict):
            character_names = {}
        voice_fingerprints = current_metadata.get("character_voice_fingerprints", [])
        if not isinstance(voice_fingerprints, list):
            voice_fingerprints = []

        system_prompt = (
            "You are an EPS-only metadata backfill agent for Japanese light novels.\n"
            "Use the full JP volume context to compute chapter-level emotional_proximity_signals.\n"
            "Return one JSON object only with this exact shape:\n"
            "{\n"
            '  "chapters": [\n'
            "    {\n"
            '      "id": "chapter_01",\n'
            '      "emotional_proximity_signals": {\n'
            '        "CharacterName": {\n'
            '          "eps_score": 0.0,\n'
            '          "voice_band": "NEUTRAL",\n'
            '          "signals": {\n'
            '            "keigo_shift": 0.0,\n'
            '            "sentence_length_delta": 0.0,\n'
            '            "particle_signature": 0.0,\n'
            '            "pronoun_shift": 0.0,\n'
            '            "dialogue_volume": 0.0,\n'
            '            "direct_address": 0.0\n'
            "          }\n"
            "        }\n"
            "      },\n"
            '      "scene_intents": ["ESTABLISH_VOICE"]\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "Rules:\n"
            "- Preserve the exact chapter ids provided.\n"
            "- Use canonical English character names from the provided registry/fingerprints.\n"
            "- Include every requested chapter.\n"
            "- For afterword chapters (e.g., title/source indicates あとがき), set chapter_kind=afterword and omit emotional_proximity_signals/scene_intents.\n"
            "- If a chapter has no reliable signal for a character, omit that character instead of inventing one.\n"
            "- Do not rewrite titles, glossary, fingerprints, or any other metadata fields.\n"
        )
        prompt = (
            f"Original Metadata:\n{json.dumps(self.manifest.get('metadata', {}), indent=2, ensure_ascii=False)}\n\n"
            f"Chapter Titles:\n{json.dumps(chapter_titles, indent=2, ensure_ascii=False)}\n\n"
            f"Canonical Character Names:\n{json.dumps(character_names, indent=2, ensure_ascii=False)}\n\n"
            f"Voice Fingerprints:\n{json.dumps(voice_fingerprints, indent=2, ensure_ascii=False)}"
        )

        full_volume_text, _ = self._build_full_volume_payload()
        cache_name = None
        if full_volume_text:
            logger.info("Building full text cache for EPS-only backfill...")
            volume_id = self.manifest.get("volume_id", self.work_dir.name)
            cache_name = self.client.create_cache(
                model=self.client.model,
                system_instruction=system_prompt,
                contents=[full_volume_text],
                display_name=f"{volume_id}_eps_only",
            )

        response = self.client.generate(
            prompt=prompt,
            system_instruction=system_prompt,
            temperature=self.phase_generation.get("temperature", 0.3),
            max_output_tokens=self.phase_generation.get("max_output_tokens", 32768),
            generation_config=self.phase_generation,
            cached_content=cache_name,
        )
        eps_payload = self._parse_llm_json_object(
            getattr(response, "content", ""),
            label="EPS-only metadata",
        )
        for chapter_payload in eps_payload.get("chapters", []) if isinstance(eps_payload.get("chapters", []), list) else []:
            if not isinstance(chapter_payload, dict):
                continue
            chapter_id = str(chapter_payload.get("id", "")).strip()
            if chapter_id and self._is_afterword_chapter_id(chapter_id):
                chapter_payload["chapter_kind"] = "afterword"
                chapter_payload["afterword_policy"] = {
                    "mode": "bypassed",
                    "directive": self._afterword_directive(),
                }
                chapter_payload.pop("emotional_proximity_signals", None)
                chapter_payload.pop("scene_intents", None)
        series_id = str(self.manifest.get("bible_id", "") or "").strip()
        signal_extraction_cfg = get_eps_signal_extraction_config(series_id=series_id or None)
        chapter_list = eps_payload.get("chapters", []) if isinstance(eps_payload.get("chapters"), list) else []
        chapter_ids_for_extraction = [
            str(ch.get("id", "")).strip()
            for ch in chapter_list
            if isinstance(ch, dict) and str(ch.get("id", "")).strip()
        ]
        deterministic_signals = extract_deterministic_eps_signals(
            work_dir=self.work_dir,
            manifest=self.manifest,
            character_names=character_names,
            chapter_ids=chapter_ids_for_extraction,
            config=signal_extraction_cfg,
        )

        non_afterword_chapter_ids = [
            str(ch.get("id", "")).strip()
            for ch in chapter_list
            if isinstance(ch, dict)
            and str(ch.get("id", "")).strip()
            and str(ch.get("chapter_kind", "")).strip().lower() != "afterword"
        ]
        strict_enabled = bool(signal_extraction_cfg.get("strict_non_afterword", False))
        self._enforce_deterministic_eps_coverage(
            strict_enabled=strict_enabled,
            non_afterword_chapter_ids=non_afterword_chapter_ids,
            deterministic_signals=deterministic_signals,
        )

        if deterministic_signals and isinstance(eps_payload.get("chapters"), list):
            merged_count = 0
            for chapter_payload in eps_payload["chapters"]:
                if not isinstance(chapter_payload, dict):
                    continue
                chapter_id = str(chapter_payload.get("id", "")).strip()
                extracted_for_chapter = deterministic_signals.get(chapter_id, {})
                if not extracted_for_chapter:
                    continue

                existing_eps = chapter_payload.get("emotional_proximity_signals", {})
                if not isinstance(existing_eps, dict):
                    existing_eps = {}

                for character_name, signal_values in extracted_for_chapter.items():
                    existing_entry = existing_eps.get(character_name, {})
                    if not isinstance(existing_entry, dict):
                        existing_entry = {}
                    existing_entry["signals"] = signal_values
                    existing_eps[character_name] = existing_entry
                    merged_count += 1

                chapter_payload["emotional_proximity_signals"] = existing_eps

            logger.info(
                "[EPS] Phase 1.52 deterministic extraction merged: chapters=%d character_signals=%d",
                len(deterministic_signals),
                merged_count,
            )

        eps_calibration_cfg = get_eps_calibration_config(series_id=series_id or None)
        if isinstance(eps_payload.get("chapters"), list):
            eps_payload["chapters"] = calibrate_eps_chapters(
                eps_payload["chapters"],
                voice_fingerprints,
                calibration=eps_calibration_cfg,
            )
        eps_payload = self._normalize_name_order_for_metadata(eps_payload)
        eps_chapters = self._normalize_translated_chapters(eps_payload.get("chapters", {}))
        self._log_eps_coverage(eps_chapters)

        self._update_manifest_preserve_schema(
            title_en=str(current_metadata.get("title_en", "") or ""),
            author_en=str(current_metadata.get("author_en", "") or ""),
            chapters=eps_chapters,
            character_names=character_names,
            glossary=current_metadata.get("glossary", {}) if isinstance(current_metadata.get("glossary", {}), dict) else {},
        )

        try:
            from pipeline.metadata_processor.bible_sync import BibleSyncAgent
            from pipeline.config import PIPELINE_ROOT
            bible_sync = BibleSyncAgent(self.work_dir, PIPELINE_ROOT)
            if bible_sync.resolve(self.manifest):
                if bible_sync.series_id and self.manifest.get("bible_id") != bible_sync.series_id:
                    self.manifest["bible_id"] = bible_sync.series_id
                self._ensure_manifest_series_identity(bible_sync)
                self._ensure_series_pack_skeleton(bible_sync)
        except Exception as e:
            logger.warning(f"EPS-only bible sync skipped: {e}")

        eps_snapshot = self._build_eps_calibration_snapshot(
            series_id=series_id,
            resolved_config=eps_calibration_cfg,
            chapter_count=len(eps_chapters) if isinstance(eps_chapters, dict) else 0,
        )
        logger.info(
            "[EPS] Phase 1.52 calibration snapshot: series_id=%s cfg=%s",
            eps_snapshot.get("series_id") or "<none>",
            eps_snapshot.get("resolved_config_sha256_short", "--------"),
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "[EPS] Phase 1.52 calibration full hash: series_id=%s sha256=%s",
                eps_snapshot.get("series_id") or "<none>",
                eps_snapshot.get("resolved_config_sha256", ""),
            )

        self.manifest.setdefault("pipeline_state", {})["metadata_processor"] = {
            "status": "completed",
            "target_language": self.target_language,
            "timestamp": datetime.datetime.now().isoformat(),
            "schema_preserved": True,
            "mode": "eps_only",
            "eps_calibration": eps_snapshot,
        }

        metadata_block = self.manifest.get(self.metadata_key, {})
        if isinstance(metadata_block, dict):
            metadata_block = self._normalize_name_order_for_metadata(metadata_block)
            metadata_block = strip_json_placeholders(metadata_block)
            self.manifest[self.metadata_key] = metadata_block
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(sanitize_json_strings(metadata_block), f, indent=2, ensure_ascii=False)
                f.write("\n")
            logger.info(f"EPS-only metadata merged into {output_path}")

        self._normalize_name_order_for_manifest()
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(self.manifest, f, indent=2, ensure_ascii=False)
            f.write("\n")

        try:
            from pipeline.translator.arc_tracker import ArcTracker

            synced_records = ArcTracker(self.work_dir).sync_from_manifest()
            logger.info(
                "[EPS] Arc tracker synchronized from manifest after Phase 1.52: records=%d",
                synced_records,
            )
        except Exception as exc:
            logger.warning(f"[EPS] Arc tracker sync skipped after Phase 1.52: {exc}")

    def process_voice_rag_only(self):
        """Backfill only Koji Fox Voice RAG metadata without regenerating metadata."""
        logger.info(f"Processing Voice RAG-only backfill for {self.work_dir.name}")

        current_metadata = self._load_existing_language_metadata()

        output_filename = f"metadata_{self.target_language}.json"
        output_path = self.work_dir / output_filename

        character_names = current_metadata.get("character_names", {})
        if not isinstance(character_names, dict):
            character_names = {}
        character_profiles = current_metadata.get("character_profiles", {})
        if not isinstance(character_profiles, dict):
            character_profiles = {}
        chapters = current_metadata.get("chapters", {})
        normalized_chapters = self._normalize_translated_chapters(chapters)

        if not character_profiles and not character_names:
            logger.error(
                "Voice RAG backfill requires existing Phase 1.5 metadata "
                "(character_profiles and/or character_names)."
            )
            return

        system_prompt = (
            "You are a Koji Fox Voice RAG expansion agent for Japanese light novels.\n"
            "Read the full JP source text and existing metadata, then return STRICT JSON only.\n"
            "Required top-level keys:\n"
            "{\n"
            '  "character_voice_fingerprints": [\n'
            "    {\n"
            '      "canonical_name_en": "Klael",\n'
            '      "archetype": "narrator-protagonist",\n'
            '      "contraction_rate": 0.70,\n'
            '      "sentence_length_bias": "medium",\n'
            '      "forbidden_vocabulary": [],\n'
            '      "preferred_vocabulary": [],\n'
            '      "signature_phrases": [],\n'
            '      "verbal_tics": [],\n'
            '      "emotional_patterns": {},\n'
            '      "dialogue_samples": []\n'
            "    }\n"
            "  ],\n"
            '  "signature_phrases": [\n'
            "    {\n"
            '      "character_en": "Klael",\n'
            '      "phrase_jp": "……",\n'
            '      "phrase_en": "...",\n'
            '      "frequency": "high",\n'
            '      "context": "hesitation or trailing thought",\n'
            '      "translation_notes": "Keep the pause texture."\n'
            "    }\n"
            "  ],\n"
            '  "scene_intent_map": [\n'
            "    {\n"
            '      "chapter_id": "chapter_01",\n'
            '      "scenes": [\n'
            "        {\n"
            '          "scene_id": "chapter_01_01",\n'
            '          "location": "cathedral entrance",\n'
            '          "primary_intent": "ESTABLISH_VOICE",\n'
            '          "secondary_intents": ["WORLD_BUILDING"],\n'
            '          "emotional_goal": "Introduce the POV register and immediate tension.",\n'
            '          "key_moments": ["first entrance", "initial confrontation"]\n'
            "        }\n"
            "      ]\n"
            "    }\n"
            "  ]\n"
            "}\n"
            "Rules:\n"
            "- Use canonical English character names exactly as provided in metadata.\n"
            "- Preserve the exact chapter ids provided.\n"
            "- For afterword chapters (e.g., title/source indicates あとがき), return an empty scenes list for that chapter_id in scene_intent_map.\n"
            "- Do not rewrite title, author, glossary, character_profiles, or chapter titles.\n"
            "- If evidence is weak, return an empty list for that field instead of guessing.\n"
            "- scene_intent_map must be a list keyed by chapter_id, not a dict.\n"
        )
        prompt = (
            f"Original Metadata:\n{json.dumps(self.manifest.get('metadata', {}), indent=2, ensure_ascii=False)}\n\n"
            f"Canonical Character Names:\n{json.dumps(character_names, indent=2, ensure_ascii=False)}\n\n"
            f"Character Profiles:\n{json.dumps(character_profiles, indent=2, ensure_ascii=False)}\n\n"
            f"Chapter Registry:\n{json.dumps(normalized_chapters, indent=2, ensure_ascii=False)}"
        )

        full_volume_text, _ = self._build_full_volume_payload()
        cache_name = None
        if full_volume_text:
            logger.info("Building full text cache for Voice RAG backfill...")
            volume_id = self.manifest.get("volume_id", self.work_dir.name)
            cache_name = self.client.create_cache(
                model=self.client.model,
                system_instruction=system_prompt,
                contents=[full_volume_text],
                display_name=f"{volume_id}_voice_rag_only",
            )

        response = self.client.generate(
            prompt=prompt,
            system_instruction=system_prompt,
            temperature=self.phase_generation.get("temperature", 0.3),
            max_output_tokens=self.phase_generation.get("max_output_tokens", 32768),
            generation_config=self.phase_generation,
            cached_content=cache_name,
        )
        voice_payload = self._parse_llm_json_object(
            getattr(response, "content", ""),
            label="Voice RAG metadata",
        )
        voice_payload = self._normalize_name_order_for_metadata(voice_payload)

        voice_fields = {}
        fingerprints = voice_payload.get("character_voice_fingerprints", [])
        fingerprints = self._augment_voice_fingerprint_coverage(
            fingerprints,
            character_profiles,
            character_names,
        )
        if fingerprints:
            voice_fields["character_voice_fingerprints"] = fingerprints

        signature_phrases = voice_payload.get("signature_phrases", [])
        if isinstance(signature_phrases, list):
            voice_fields["signature_phrases"] = signature_phrases

        scene_intent_map = voice_payload.get("scene_intent_map", [])
        if isinstance(scene_intent_map, list):
            for item in scene_intent_map:
                if not isinstance(item, dict):
                    continue
                chapter_id = str(item.get("chapter_id", "")).strip()
                if chapter_id and self._is_afterword_chapter_id(chapter_id):
                    item["chapter_kind"] = "afterword"
                    item["afterword_policy"] = {
                        "mode": "bypassed",
                        "directive": self._afterword_directive(),
                    }
                    item["scenes"] = []
            voice_fields["scene_intent_map"] = scene_intent_map

        self._update_manifest_preserve_schema(
            title_en=str(current_metadata.get("title_en", "") or ""),
            author_en=str(current_metadata.get("author_en", "") or ""),
            chapters=normalized_chapters,
            character_names=character_names,
            glossary=current_metadata.get("glossary", {}) if isinstance(current_metadata.get("glossary", {}), dict) else {},
            extra_fields=voice_fields,
        )
        self._normalize_name_order_for_manifest()

        self.manifest.setdefault("pipeline_state", {})["metadata_processor"] = {
            "status": "completed",
            "target_language": self.target_language,
            "timestamp": datetime.datetime.now().isoformat(),
            "schema_preserved": True,
            "mode": "voice_rag_only",
        }

        metadata_block = self.manifest.get(self.metadata_key, {})
        if isinstance(metadata_block, dict):
            metadata_block = self._normalize_name_order_for_metadata(metadata_block)
            metadata_block = strip_json_placeholders(metadata_block)
            self.manifest[self.metadata_key] = metadata_block
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(sanitize_json_strings(metadata_block), f, indent=2, ensure_ascii=False)
                f.write("\n")
            logger.info(
                "Voice RAG metadata merged into %s "
                "(fingerprints=%s, signature_phrases=%s, scene_intent_map=%s)",
                output_path,
                len(metadata_block.get("character_voice_fingerprints", []) or []),
                len(metadata_block.get("signature_phrases", []) or []),
                len(metadata_block.get("scene_intent_map", []) or []),
            )

        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(self.manifest, f, indent=2, ensure_ascii=False)
            f.write("\n")

def main():
    parser = argparse.ArgumentParser(description="Run Metadata Processor Agent")
    parser.add_argument("--volume", type=str, required=True, help="Volume ID (directory name in WORK)")
    parser.add_argument(
        "--ignore-sequel",
        action="store_true",
        help="Disable sequel continuity detection and process metadata as an independent volume",
    )
    parser.add_argument(
        "--eps-only",
        action="store_true",
        help="Backfill only chapter emotional_proximity_signals and scene_intents without regenerating other metadata",
    )
    parser.add_argument(
        "--voice-rag-only",
        action="store_true",
        help="Backfill only Koji Fox Voice RAG metadata without regenerating other metadata",
    )
    parser.add_argument(
        "--strict-canonical",
        action="store_true",
        help="Abort Phase 1.5 if any bible-registered canonical name mismatch remains after post-verification",
    )
    parser.add_argument(
        "--canonical-source",
        choices=["bible", "manifest"],
        default="bible",
        help="Choose canonical name authority for normalization/push (default: bible)",
    )

    args = parser.parse_args()

    from pipeline.config import WORK_DIR
    volume_dir = WORK_DIR / args.volume

    if not volume_dir.exists():
        logger.error(f"Volume directory not found: {volume_dir}")
        sys.exit(1)

    processor = MetadataProcessor(
        volume_dir,
        strict_canonical=args.strict_canonical,
        canonical_source=args.canonical_source,
        ignore_sequel=args.ignore_sequel,
    )
    if args.eps_only:
        processor.process_eps_only()
    elif args.voice_rag_only:
        processor.process_voice_rag_only()
    else:
        processor.process_metadata()

if __name__ == "__main__":
    main()

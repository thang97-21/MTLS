"""
Bible Auto-Sync Agent (Phase 1.5)
==================================

Two-way sync between series bible and volume manifest during
metadata processing. Runs BEFORE the Translator (Phase 2) starts,
ensuring canonical data is always up-to-date.

PULL (Bible → Manifest):
    Read known canonical terms for current volume processing (read-only).
    Runs after SchemaAutoUpdater, before batch_translate_ruby.
    Effect: batch_translate_ruby can skip already-known names,
            inheritance_context includes bible canon.

PUSH (Manifest → Bible):
    Export newly discovered terms from manifest back to bible.
    Runs after final manifest write.
    Effect: Next volume in the series inherits these discoveries.

Usage in MetadataProcessor.process_metadata():
    sync = BibleSyncAgent(self.work_dir, PIPELINE_ROOT)
    if sync.resolve(self.manifest):
        pull_result = sync.pull(self.manifest)
        # ... use pull_result.known_names in batch_translate_ruby ...
        # ... use pull_result.context_block in inheritance_context ...
        # ... after final write ...
        push_result = sync.push(self.manifest)
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import re
from difflib import SequenceMatcher
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from pipeline.common.name_order_normalizer import (
    build_name_order_replacement_map,
    resolve_name_order_policy,
)

logger = logging.getLogger("BibleSync")


# ═══════════════════════════════════════════════════════════════════
#  Result Types
# ═══════════════════════════════════════════════════════════════════

@dataclass
class BiblePullResult:
    """Result of pulling canonical terms from bible → manifest."""

    # JP→EN dict of ALL bible terms (flat glossary)
    known_terms: Dict[str, str] = field(default_factory=dict)

    # JP→EN dict of character names only (for batch_translate_ruby skip)
    known_characters: Dict[str, str] = field(default_factory=dict)

    # Context block for injection into Gemini prompt
    context_block: str = ""

    # Pull-override log: manifest terms that override bible terms
    overrides: List[str] = field(default_factory=list)

    # Stats
    characters_inherited: int = 0
    geography_inherited: int = 0
    weapons_inherited: int = 0
    other_inherited: int = 0
    eps_states_inherited: int = 0

    @property
    def total_inherited(self) -> int:
        return (self.characters_inherited + self.geography_inherited
                + self.weapons_inherited + self.other_inherited)

    def summary(self) -> str:
        parts = []
        if self.characters_inherited:
            parts.append(f"characters={self.characters_inherited}")
        if self.geography_inherited:
            parts.append(f"geography={self.geography_inherited}")
        if self.weapons_inherited:
            parts.append(f"weapons={self.weapons_inherited}")
        if self.other_inherited:
            parts.append(f"other={self.other_inherited}")
        if self.eps_states_inherited:
            parts.append(f"eps={self.eps_states_inherited}")
        return f"PULL: {self.total_inherited} terms ({', '.join(parts)})" if parts else "PULL: 0 terms"


@dataclass
class BiblePushResult:
    """Result of pushing manifest discoveries → bible."""

    # New entries added to bible
    characters_added: int = 0
    characters_enriched: int = 0
    characters_skipped: int = 0

    # Conflict log (manifest disagrees with bible)
    conflicts: List[str] = field(default_factory=list)

    # Volume registration
    volume_registered: bool = False
    eps_states_updated: int = 0

    @property
    def total_changes(self) -> int:
        return self.characters_added + self.characters_enriched + self.eps_states_updated

    def summary(self) -> str:
        parts = [f"added={self.characters_added}",
                 f"enriched={self.characters_enriched}",
                 f"skipped={self.characters_skipped}",
                 f"eps={self.eps_states_updated}"]
        if self.conflicts:
            parts.append(f"conflicts={len(self.conflicts)}")
        if self.volume_registered:
            parts.append("volume=registered")
        return f"PUSH: {', '.join(parts)}"


# ═══════════════════════════════════════════════════════════════════
#  BibleSyncAgent
# ═══════════════════════════════════════════════════════════════════

class BibleSyncAgent:
    """Two-way sync between series bible and Phase 1.5 metadata.

    Lifecycle:
        1. resolve(manifest)  — find the bible for this volume
        2. pull(manifest)     — inherit bible context (read-only)
        3. (... Phase 1.5 processing happens ...)
        4. push(manifest)     — export discoveries → bible
    """

    def __init__(self, work_dir: Path, pipeline_root: Path):
        self.work_dir = work_dir
        self.pipeline_root = pipeline_root

        # Lazy import to avoid circular dependencies
        from pipeline.translator.series_bible import BibleController
        self.bible_ctrl = BibleController(pipeline_root)
        self.bible = None          # type: Optional[Any]  # SeriesBible
        self.series_id = None      # type: Optional[str]

    # ── Resolution ───────────────────────────────────────────────

    def resolve(self, manifest: dict) -> bool:
        """Resolve a bible for this manifest.

        Checks bible_id, volume_id, series metadata, and fuzzy match.
        Returns True if a bible was found (or bootstrapped) and loaded.
        """
        try:
            bible = self.bible_ctrl.load(manifest, self.work_dir)
            if bible:
                self.bible = bible
                self.series_id = bible.series_id
                logger.info(f"📖 Bible resolved: {self.series_id} "
                            f"({bible.entry_count()} entries)")
                return True
        except Exception as e:
            logger.warning(f"Bible resolution failed: {e}")

        # Auto-bootstrap flow:
        # For a brand-new series with no pre-existing bible, seed a new bible
        # from the current (base) manifest so this run and all subsequent runs
        # stay on the same continuity source of truth.
        if self._bootstrap_from_manifest(manifest):
            return True

        logger.info("📖 No bible found for this volume — sync skipped")
        return False

    def _bootstrap_from_manifest(self, manifest: dict) -> bool:
        """Create/seed a new bible from the current manifest when missing."""
        seed = self._derive_bootstrap_seed(manifest)
        if not seed:
            return False

        series_id = seed["series_id"]
        series_title = seed["series_title"]
        match_patterns = seed["match_patterns"]
        world_setting = seed["world_setting"]

        # If entry already exists but wasn't resolved earlier, try direct load once.
        # This handles stale pattern/volume links while preserving existing canon data.
        if self.bible_ctrl.index.get("series", {}).get(series_id):
            try:
                bible = self.bible_ctrl.get_bible(series_id)
                if bible:
                    self.bible = bible
                    self.series_id = series_id
                    manifest["bible_id"] = series_id
                    logger.info(
                        f"📖 Bible bootstrap recovered existing series: {series_id} "
                        f"({bible.entry_count()} entries)"
                    )
                    return True
            except Exception as e:
                logger.warning(f"Existing bible entry for {series_id} could not be loaded: {e}")

        try:
            self.bible_ctrl.create_bible(
                series_id=series_id,
                series_title=series_title,
                match_patterns=match_patterns,
                world_setting=world_setting,
            )
            logger.info(
                f"📖 Auto-created new bible: {series_id} "
                f"(patterns={len(match_patterns)})"
            )
        except FileExistsError:
            # Race-safe fallback: file appeared after checks.
            pass
        except Exception as e:
            logger.warning(f"Bible bootstrap create failed for {series_id}: {e}")
            return False

        try:
            summary = self.bible_ctrl.import_from_manifest(manifest, series_id)
            logger.info(f"📖 Seeded bible from base manifest: {summary}")
        except Exception as e:
            logger.warning(f"Bible bootstrap import failed for {series_id}: {e}")

        try:
            bible = self.bible_ctrl.get_bible(series_id)
        except Exception as e:
            logger.warning(f"Bible bootstrap load failed for {series_id}: {e}")
            return False

        if not bible:
            return False

        self.bible = bible
        self.series_id = series_id
        manifest["bible_id"] = series_id
        logger.info(
            f"📖 Bible bootstrapped: {series_id} "
            f"({bible.entry_count()} entries, volumes={len(bible.volumes_registered)})"
        )
        return True

    def _derive_bootstrap_seed(self, manifest: dict) -> Optional[Dict[str, Any]]:
        """Derive minimal deterministic bible seed data from a volume manifest."""
        if not isinstance(manifest, dict):
            return None

        metadata = manifest.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        metadata_en = manifest.get("metadata_en", {})
        if not isinstance(metadata_en, dict):
            metadata_en = {}

        explicit_bible_id = str(manifest.get("bible_id", "") or "").strip()
        volume_id = str(manifest.get("volume_id", "") or "").strip()

        series_raw = metadata.get("series", "")
        series_ja = ""
        series_en = ""
        series_base = ""
        if isinstance(series_raw, dict):
            # Common variants:
            # 1) {"ja": "...", "en": "..."}
            # 2) {"title": "...", "title_english": "..."}
            # 3) {"title": {"japanese": "...", "english": "...", ...}, ...}
            series_ja = str(
                series_raw.get("ja", "")
                or series_raw.get("japanese", "")
                or ""
            ).strip()
            series_en = str(
                series_raw.get("en", "")
                or series_raw.get("english", "")
                or series_raw.get("title_english", "")
                or ""
            ).strip()

            series_title_block = series_raw.get("title", "")
            if isinstance(series_title_block, dict):
                series_ja = series_ja or str(
                    series_title_block.get("ja", "")
                    or series_title_block.get("japanese", "")
                    or ""
                ).strip()
                series_en = series_en or str(
                    series_title_block.get("en", "")
                    or series_title_block.get("english", "")
                    or ""
                ).strip()
            elif isinstance(series_title_block, str):
                series_ja = series_ja or series_title_block.strip()

            series_base = series_en or series_ja
        else:
            series_base = str(series_raw or "").strip()
            series_ja = series_base
            series_en = ""

        title_ja = str(metadata.get("title", "") or "").strip()
        title_sort_ja = str(metadata.get("title_sort", "") or "").strip()
        title_en = str(metadata_en.get("title_en", "") or metadata.get("title_en", "") or "").strip()
        series_title_en = str(
            metadata_en.get("series_title_en", "")
            or metadata_en.get("series_en", "")
            or series_en
            or ""
        ).strip()
        source_epub = str(metadata.get("source_epub", "") or "").strip()
        source_epub_stem = ""
        if source_epub:
            try:
                source_epub_stem = Path(source_epub).stem.replace("_", " ").strip()
            except Exception:
                source_epub_stem = ""

        canonical_series_ja = self._strip_volume_suffix(series_ja)
        canonical_series_en = self._strip_volume_suffix(series_title_en or series_en)
        canonical_series_title_sort = self._strip_volume_suffix(title_sort_ja)
        canonical_series_epub_stem = self._strip_volume_suffix(source_epub_stem)
        canonical_title_ja = self._strip_volume_suffix(title_ja)
        canonical_title_en = self._strip_volume_suffix(title_en)

        base_name = (
            explicit_bible_id
            # OPF and librarian-derived canonical fields (highest priority)
            or canonical_series_ja
            or canonical_series_en
            or canonical_series_title_sort
            or canonical_series_epub_stem
            # Fallbacks
            or canonical_title_ja
            or canonical_title_en
        )
        if not base_name:
            return None

        if explicit_bible_id:
            series_id = explicit_bible_id
        else:
            series_id = self._build_series_id(base_name, volume_id)

        series_title = {
            "ja": canonical_series_ja or canonical_series_en or base_name,
            "en": canonical_series_en or canonical_series_ja or base_name,
            "romaji": "",
        }

        match_patterns: List[str] = []
        for candidate in [
            canonical_series_ja,
            canonical_series_en,
            canonical_series_title_sort,
            canonical_series_epub_stem,
            canonical_title_ja,
            canonical_title_en,
            series_base,
            source_epub_stem,
        ]:
            text = str(candidate or "").strip()
            if text and text not in match_patterns:
                match_patterns.append(text)
        if not match_patterns:
            match_patterns = [base_name]

        world_setting = {}
        ws = metadata_en.get("world_setting", {})
        if isinstance(ws, dict):
            world_setting = ws

        return {
            "series_id": series_id,
            "series_title": series_title,
            "match_patterns": match_patterns,
            "world_setting": world_setting,
            # ECR Component 3: bootstrap ECR data into bible on first sync
            "culturally_loaded_terms": metadata_en.get("culturally_loaded_terms", {}),
            "author_signature_patterns": metadata_en.get("author_signature_patterns", {}),
        }

    def _build_series_id(self, base_name: str, volume_id: str) -> str:
        """Build a deterministic series_id from series/title text."""
        normalized = re.sub(r"\s+", " ", str(base_name).strip().lower())
        ascii_slug = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
        if ascii_slug:
            return ascii_slug[:80]

        # For non-ASCII titles, generate stable ID from content hash so
        # all volumes in the same series resolve to the same bible_id.
        if normalized:
            digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
            return f"series_{digest}"

        fallback = self.bible_ctrl._extract_short_id(volume_id) or "unknown"
        return f"series_{fallback}"

    def _strip_volume_suffix(self, text: str) -> str:
        """Best-effort removal of trailing volume markers for stable series matching."""
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""

        patterns = [
            r"\s*(?:Vol(?:ume)?\.?|VOL\.?)\s*[0-9０-９]+$",
            r"\s*(?:Lv\.?|LV\.?|level)\s*[0-9０-９]+$",
            r"\s*[Vv]\s*[0-9０-９]+$",
            r"\s*第\s*[0-9０-９一二三四五六七八九十百千]+(?:巻|話|章)$",
            r"\s*[0-9０-９]+$",
            r"\s*[（(][0-9０-９]+[）)]$",
        ]
        for pat in patterns:
            cleaned = re.sub(pat, "", cleaned).strip()
        return cleaned

    # ── PULL: Bible → Manifest ───────────────────────────────────

    def pull(
        self,
        manifest: dict,
        target_language: str = "en",
        import_mode: str = "canon_safe",
    ) -> BiblePullResult:
        """Pull canonical terms from bible for use in metadata processing.

        Called AFTER _run_schema_autoupdate() but BEFORE _batch_translate_ruby().

        Returns:
            BiblePullResult with known terms, known characters, and
            a formatted context block for Gemini prompt injection.
        """
        if not self.bible:
            return BiblePullResult()

        mode = str(import_mode or "canon_safe").strip().lower()
        if mode not in {"canon_safe", "continuity_only", "bypassed"}:
            logger.warning(
                "[BIBLE-PULL] Unsupported import_mode '%s' -> defaulting to canon_safe",
                import_mode,
            )
            mode = "canon_safe"

        if mode == "bypassed":
            logger.info("[BIBLE-PULL] import_mode=bypassed -> skip all bible pull usage")
            return BiblePullResult()

        bypass_reason = self._detect_name_order_bypass_reason(manifest)
        if bypass_reason:
            logger.warning(
                "[BIBLE BYPASS] %s Skipping Bible pull and using local manifest only.",
                bypass_reason,
            )
            return BiblePullResult()

        result = BiblePullResult()

        if mode == "continuity_only":
            result.eps_states_inherited = sum(
                1
                for char_data in self.bible.get_all_characters().values()
                if isinstance(char_data, dict) and isinstance(char_data.get("latest_eps_state"), dict)
            )
            logger.info(
                "[BIBLE-PULL] continuity_only: skipped canonical term/context import; "
                "eps_states_inherited=%s",
                result.eps_states_inherited,
            )
            return result

        # 1. Extract category-specific glossaries
        result.known_characters = self.bible.characters_glossary()
        result.characters_inherited = len(result.known_characters)

        geo_glossary = self.bible.geography_glossary()
        result.geography_inherited = len(geo_glossary)

        weapons_glossary = self.bible.weapons_glossary()
        result.weapons_inherited = len(weapons_glossary)

        cultural_glossary = self.bible.cultural_glossary()
        result.other_inherited = len(cultural_glossary)

        # 2. Flat glossary = union of all
        result.known_terms = self.bible.flat_glossary()

        # ECR Component 3: Extend known_terms with culturally_loaded_terms from bible
        # so SeriesBibleRAG can perform term-triggered lookup on ECR JP terms.
        clt = self.bible.data.get("culturally_loaded_terms", {})
        if isinstance(clt, dict):
            for jp_term, clt_entry in clt.items():
                if not isinstance(clt_entry, dict):
                    continue
                policy = clt_entry.get("retention_policy", "")
                if policy in ("preserve_jp", "preserve_jp_first_use"):
                    romaji = clt_entry.get("romaji", "")
                    display = romaji if romaji else jp_term
                    result.known_terms.setdefault(jp_term, display)

        result.eps_states_inherited = sum(
            1
            for char_data in self.bible.get_all_characters().values()
            if isinstance(char_data, dict) and isinstance(char_data.get("latest_eps_state"), dict)
        )

        # 3. Build context block for Gemini inheritance prompt
        result.context_block = self._build_pull_context(target_language=target_language)

        # 4. Read local metadata names for override audit only (no mutation).
        metadata_key = f"metadata_{str(target_language or 'en').lower()}"
        metadata_block = manifest.get(metadata_key, {})
        if not isinstance(metadata_block, dict):
            metadata_block = manifest.get("metadata_en", {})
        if not isinstance(metadata_block, dict):
            metadata_block = {}
        existing_names = metadata_block.get("character_names", {})
        if not isinstance(existing_names, dict):
            existing_names = {}

        # Bible as base, manifest values override (manifest may have
        # volume-specific new characters that aren't in bible yet)
        merged_names = dict(result.known_characters)  # bible base

        # Log individual pull overrides where manifest disagrees with bible
        for jp, manifest_en in existing_names.items():
            bible_en = result.known_characters.get(jp)
            if bible_en and bible_en.lower() != manifest_en.lower():
                result.overrides.append(
                    f"  {jp}: bible='{bible_en}' → manifest='{manifest_en}' (manifest kept)"
                )

        merged_names.update(existing_names)             # manifest overrides
        merged_total = len(merged_names)
        logger.info(
            "   [BIBLE-PULL] Read-only mode: local metadata untouched "
            f"(view={merged_total} names; bible={len(result.known_characters)}, "
            f"local={len(existing_names)}, key={metadata_key})"
        )

        if result.overrides:
            logger.warning(f"⚠️  {len(result.overrides)} pull override(s) (manifest kept over bible):")
            for o in result.overrides:
                logger.warning(o)

        logger.info(f"   {result.summary()}")
        return result

    def _detect_name_order_bypass_reason(self, manifest: dict) -> Optional[str]:
        """Return bypass reason when bible canonical names violate local manifest policy."""
        if not self.bible or not isinstance(manifest, dict):
            return None

        replacements = build_name_order_replacement_map(manifest)
        if not replacements:
            return None

        bible_data = getattr(self.bible, "data", None)
        if not isinstance(bible_data, dict):
            return None

        serialized = json.dumps(bible_data, ensure_ascii=False)
        conflicts = []
        for wrong, canonical in replacements.items():
            count = serialized.count(wrong)
            if count > 0:
                conflicts.append((wrong, canonical, count))
        if not conflicts:
            return None

        conflicts.sort(key=lambda item: (-item[2], item[0]))
        summary = ", ".join(
            f"{wrong}->{canonical} x{count}"
            for wrong, canonical, count in conflicts[:5]
        )
        policy = resolve_name_order_policy(manifest)
        return (
            f"Bible conflicts with manifest name-order policy '{policy}' "
            f"({summary})"
        )

    def _build_pull_context(self, target_language: str = "en") -> str:
        """
        Build translator-facing bible pull context.

        Includes:
        - canonical names/terms
        - character profile layers already stored in bible (keigo, notes, category, visual identity)
        - future profile layers (voice_register, speech_patterns, translation_notes) when present
        - local project translation decisions from .context/translation_decisions.json
        """
        if not self.bible:
            return ""

        lines = [
            "",
            "=" * 60,
            "SERIES BIBLE — CANONICAL TERMS (USE EXACT SPELLINGS)",
            "=" * 60,
            "",
        ]

        chars = self.bible.get_all_characters()
        if chars:
            lines.append("CHARACTER NAMES (bible canon — use these EXACT spellings):")
            for jp_name, char_data in chars.items():
                if not isinstance(char_data, dict):
                    continue
                en = str(char_data.get("canonical_en", "")).strip()
                if not en:
                    continue
                short = str(char_data.get("short_name", "")).strip()
                suffix = f" (short: {short})" if short and short != en else ""
                lines.append(f"  {jp_name} → {en}{suffix}")
            lines.append("")

        profile_entries: List[str] = []
        for jp_name, char_data in chars.items():
            if not isinstance(char_data, dict):
                continue
            en = str(char_data.get("canonical_en", "")).strip() or jp_name
            lines_for_char = [f"  {en} ({jp_name}):"]
            has_profile = False

            category = str(char_data.get("category", "")).strip()
            if category:
                lines_for_char.append(f"    role: {category}")
                has_profile = True

            keigo = char_data.get("keigo", {})
            if isinstance(keigo, dict):
                formal = str(keigo.get("formal") or keigo.get("uses_keigo") or "").strip()
                casual = str(keigo.get("casual") or keigo.get("drops_keigo") or "").strip()
                if formal or casual:
                    parts = []
                    if formal:
                        parts.append(f"formal={formal}")
                    if casual:
                        parts.append(f"casual={casual}")
                    lines_for_char.append(f"    keigo: {', '.join(parts)}")
                    has_profile = True

            notes = str(char_data.get("notes", "")).strip()
            if notes:
                lines_for_char.append(f"    personality: {notes}")
                has_profile = True

            visual_identity = self._format_visual_identity_non_color(
                char_data.get("visual_identity_non_color")
            )
            if visual_identity:
                lines_for_char.append(f"    visual_identity_non_color: {visual_identity}")
                has_profile = True

            voice_register = str(char_data.get("voice_register", "")).strip()
            if voice_register:
                lines_for_char.append(f"    voice: {voice_register}")
                has_profile = True

            # VN: Add pair_id_default_vn if present
            if target_language in ("vn", "vi"):
                pair_id_defaults = char_data.get("pair_id_default_vn", {})
                if isinstance(pair_id_defaults, dict) and pair_id_defaults:
                    pairs_str = ", ".join(
                        f"{target}={pair}" for target, pair in pair_id_defaults.items()
                    )
                    lines_for_char.append(f"    vn_pair_defaults: {pairs_str}")
                    has_profile = True

            speech_patterns = char_data.get("speech_patterns", [])
            if isinstance(speech_patterns, list):
                items = [str(v).strip() for v in speech_patterns if str(v).strip()]
                if items:
                    lines_for_char.append(f"    patterns: {', '.join(items[:8])}")
                    has_profile = True

            tl_note = str(char_data.get("translation_notes", "")).strip()
            if tl_note:
                lines_for_char.append(f"    tl-note: {tl_note}")
                has_profile = True

            if has_profile:
                profile_entries.extend(lines_for_char)

        if profile_entries:
            lines.append("CHARACTER PROFILES (use for voice/register decisions):")
            lines.extend(profile_entries)
            lines.append("")

        eps_entries: List[str] = []
        for jp_name, char_data in chars.items():
            if not isinstance(char_data, dict):
                continue
            latest_eps = char_data.get("latest_eps_state")
            if not isinstance(latest_eps, dict):
                continue
            en = str(
                latest_eps.get("canonical_name_en")
                or char_data.get("canonical_en")
                or jp_name
            ).strip()
            if not en:
                continue
            eps_score = latest_eps.get("eps_score")
            try:
                eps_text = f"{float(eps_score):+.2f}"
            except (TypeError, ValueError):
                eps_text = "n/a"
            band = str(latest_eps.get("voice_band", "")).strip().upper() or "NEUTRAL"
            source_volume = str(latest_eps.get("source_volume_id", "")).strip()
            source_chapter = str(latest_eps.get("source_chapter_id", "")).strip()
            source_bits = [bit for bit in (source_volume, source_chapter) if bit]
            source_text = f" | source: {' / '.join(source_bits)}" if source_bits else ""
            scene_intents = latest_eps.get("scene_intents", [])
            intent_text = ""
            if isinstance(scene_intents, list):
                items = [str(v).strip() for v in scene_intents if str(v).strip()]
                if items:
                    intent_text = f" | intents: {', '.join(items[:4])}"
            eps_entries.append(
                f"  {en}: EPS {eps_text} [{band}]{source_text}{intent_text}"
            )

        if eps_entries:
            lines.append("LATEST EPS CONTINUITY (carry forward as prior-volume baseline):")
            lines.extend(eps_entries)
            lines.append("")

        geo = self.bible.data.get("geography", {})
        geo_entries = []
        for sub in ("countries", "regions", "cities"):
            for jp, data in geo.get(sub, {}).items():
                if isinstance(data, dict) and data.get("canonical_en"):
                    geo_entries.append(f"  {jp} → {data['canonical_en']}")
        if geo_entries:
            lines.append("GEOGRAPHY (bible canon):")
            lines.extend(geo_entries)
            lines.append("")

        weapons = self.bible.data.get("weapons_artifacts", {})
        weapon_entries = []
        for sub_cat, items in weapons.items():
            if not isinstance(items, dict):
                continue
            for jp, data in items.items():
                if isinstance(data, dict) and data.get("canonical_en"):
                    weapon_entries.append(f"  {jp} → {data['canonical_en']}")
        if weapon_entries:
            lines.append("WEAPONS & ARTIFACTS (bible canon):")
            lines.extend(weapon_entries)
            lines.append("")

        misc_entries = []
        for cat in ("organizations", "cultural_terms", "mythology"):
            for jp, data in self.bible.data.get(cat, {}).items():
                if isinstance(data, dict) and data.get("canonical_en"):
                    misc_entries.append(f"  {jp} → {data['canonical_en']}")
        if misc_entries:
            lines.append("TERMINOLOGY (bible canon):")
            lines.extend(misc_entries)
            lines.append("")

        local_decisions = self._load_local_translation_decisions(target_language=target_language)
        if local_decisions:
            lines.append("ESTABLISHED TRANSLATION DECISIONS (carry forward exactly):")
            for jp_pattern, rendered in local_decisions.items():
                lines.append(f"  {jp_pattern} → {rendered}")
            lines.append("")

        # ECR Component 3: Culturally Loaded Terms section
        clt = self.bible.data.get("culturally_loaded_terms", {})
        if isinstance(clt, dict) and clt:
            preserve_entries = {
                jp: entry for jp, entry in clt.items()
                if isinstance(entry, dict) and entry.get("retention_policy") in ("preserve_jp", "preserve_jp_first_use")
            }
            if preserve_entries:
                lines.append("=" * 60)
                lines.append("CULTURALLY LOADED TERMS — DO NOT SUBSTITUTE")
                lines.append("(Retained from series ECR database across volumes)")
                lines.append("")
                for jp_term, entry in preserve_entries.items():
                    romaji = entry.get("romaji", "")
                    display = romaji if romaji else jp_term
                    policy = entry.get("retention_policy", "preserve_jp")
                    usage = entry.get("usage_context", "")
                    policy_label = "(retain with inline gloss on first use)" if policy == "preserve_jp_first_use" else "(NEVER substitute)"
                    line = f"  {display} {policy_label}"
                    if usage:
                        line += f" — {usage}"
                    lines.append(line)
                lines.append("")

        # ECR Component 3: Author Signature Patterns section
        asp = self.bible.data.get("author_signature_patterns", {})
        if isinstance(asp, dict):
            asp_patterns = asp.get("detected_patterns", [])
            author_name_en = asp.get("author_name_en", "") or asp.get("author_name_jp", "")
            if isinstance(asp_patterns, list) and asp_patterns:
                lines.append("=" * 60)
                lines.append("AUTHOR SIGNATURE PATTERNS — STRUCTURAL PRESERVATION")
                if author_name_en:
                    lines.append(f"Author: {author_name_en}")
                lines.append("")
                for pat in asp_patterns:
                    if not isinstance(pat, dict):
                        continue
                    pid = pat.get("pattern_id", "")
                    en_structure = pat.get("en_structure", "")
                    preservation_rule = pat.get("preservation_rule", "")
                    lines.append(f"  [{pid}]")
                    if en_structure:
                        lines.append(f"    Structure: {en_structure}")
                    if preservation_rule:
                        lines.append(f"    Rule: {preservation_rule}")
                lines.append("")
            refs = asp.get("literary_references", [])
            if isinstance(refs, list) and refs:
                lines.append("LITERARY REFERENCES (carry exact naming across volumes):")
                for ref in refs:
                    if not isinstance(ref, dict):
                        continue
                    ref_en = ref.get("ref_en", "")
                    author_en_ref = ref.get("author_en", "")
                    handling = ref.get("handling", "preserve exact name")
                    if ref_en:
                        suffix = f" by {author_en_ref}" if author_en_ref else ""
                        lines.append(f"  {ref_en}{suffix} → {handling}")
                lines.append("")

        # VN: Load relationship state anchors from translation_decisions.json
        if target_language in ("vn", "vi"):
            rel_states = self._load_relationship_states(target_language=target_language)
            if rel_states:
                lines.append("VN RELATIONSHIP STATE — ESTABLISHED IN PRIOR VOLUMES:")
                lines.append("(Read JP signals in-scene for temporary register shifts. Do not recalculate from scratch.)")
                lines.append("")
                for pair_key, state_data in rel_states.items():
                    jp_state = state_data.get("jp_state", "unknown")
                    default_pair = state_data.get("default_pair", "—")
                    source = state_data.get("source", "")
                    lines.append(f"  {pair_key}: {jp_state}")
                    lines.append(f"    → default_pair={default_pair} ({source})")
                lines.append("")

        lines.append("=" * 60)
        lines.append("Any term above MUST use the exact spelling shown.")
        lines.append("Character voices and translation decisions MUST be maintained.\n")
        return "\n".join(lines)

    def _format_visual_identity_non_color(self, value: Any) -> str:
        """Compact formatter for visual_identity_non_color payload in bible context."""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            items = [str(v).strip() for v in value if str(v).strip()]
            return ", ".join(items[:6])
        if not isinstance(value, dict):
            return ""

        fragments: List[str] = []
        for key in (
            "identity_summary",
            "hairstyle",
            "clothing_signature",
            "expression_signature",
            "posture_signature",
            "accessory_signature",
            "body_silhouette",
        ):
            text = str(value.get(key, "")).strip()
            if text:
                fragments.append(text)
        markers = value.get("non_color_markers", [])
        if isinstance(markers, list):
            items = [str(v).strip() for v in markers if str(v).strip()]
            if items:
                fragments.append(f"markers={', '.join(items[:5])}")
        gestures = value.get("habitual_gestures", [])
        if isinstance(gestures, list):
            gesture_items = []
            for entry in gestures:
                if isinstance(entry, dict):
                    gesture = str(entry.get("gesture", "")).strip()
                    trigger = str(entry.get("trigger", "")).strip()
                    if gesture:
                        gesture_items.append(f"{gesture} ({trigger})" if trigger else gesture)
                else:
                    text = str(entry).strip()
                    if text:
                        gesture_items.append(text)
                if len(gesture_items) >= 4:
                    break
            if gesture_items:
                fragments.append(f"gestures={'; '.join(gesture_items)}")
        return " | ".join(fragments[:6])

    def _load_local_translation_decisions(self, target_language: str = "en") -> Dict[str, str]:
        """
        Load volume-local translation decisions from .context/translation_decisions.json.

        File schema:
        {
            "en": {"ラブホ": "...", ...},
            "vn": {"ラブホ": "...", ...}
        }
        """
        decisions_path = self.work_dir / ".context" / "translation_decisions.json"
        if not decisions_path.exists():
            return {}
        try:
            data = json.loads(decisions_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"[DECISIONS] Failed to load translation_decisions.json: {exc}")
            return {}
        lang_decisions = data.get(target_language, {})
        if isinstance(lang_decisions, dict):
            return {
                str(k).strip(): str(v).strip()
                for k, v in lang_decisions.items()
                if str(k).strip() and str(v).strip()
            }
        return {}

    def _load_relationship_states(self, target_language: str = "vn") -> Dict[str, Dict[str, str]]:
        """
        Load VN relationship state anchors from translation_decisions.json.

        File schema (inside "vn" key):
        {
            "character_relationship_states": {
                "有咲→真白": {
                    "jp_state": "確立したカップル",
                    "source": "vol2_ch11_confession",
                    "default_pair": "PAIR_3"
                }
            }
        }
        """
        decisions_path = self.work_dir / ".context" / "translation_decisions.json"
        if not decisions_path.exists():
            return {}
        try:
            data = json.loads(decisions_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"[DECISIONS] Failed to load translation_decisions.json: {exc}")
            return {}
        lang_data = data.get(target_language, {})
        if not isinstance(lang_data, dict):
            lang_data = data.get("vn", {})
        rel_states = lang_data.get("character_relationship_states", {})
        if isinstance(rel_states, dict):
            return rel_states
        return {}

    # ── PUSH: Manifest → Bible ───────────────────────────────────

    def push(self, manifest: dict, canonical_source: str = "bible") -> BiblePushResult:
        """Push newly discovered terms from manifest back to the bible.

        Called AFTER the final manifest write. Compares the manifest's
        finalized character_names against the bible and adds new entries.

        Args:
            manifest: The fully processed manifest dict

        Returns:
            BiblePushResult with counts and conflict log
        """
        if not self.bible:
            return BiblePushResult()

        mode = str(canonical_source or "bible").strip().lower()
        canonical_source = mode if mode in {"bible", "manifest"} else "bible"

        result = BiblePushResult()
        metadata_en = manifest.get('metadata_en', {})

        # ── Push character names ─────────────────────────────────
        # Primary source: metadata_en.character_names
        # Fallback source: metadata_en.character_profiles (v3 flow may keep character_names empty)
        char_names = metadata_en.get('character_names', {})
        if not isinstance(char_names, dict):
            char_names = {}
        profiles = metadata_en.get('character_profiles', {})
        if not isinstance(profiles, dict):
            profiles = {}

        derived_names: Dict[str, str] = {}
        for profile_key, profile_data in profiles.items():
            if not isinstance(profile_data, dict):
                continue
            full_name = str(profile_data.get('full_name', '')).strip()
            if not full_name:
                continue

            jp_name = None
            if re.search(r'[\u3040-\u30ff\u4e00-\u9fff]', profile_key):
                jp_name = profile_key
            else:
                ruby_base = str(profile_data.get('ruby_base', '')).strip()
                if ruby_base and re.search(r'[\u3040-\u30ff\u4e00-\u9fff]', ruby_base):
                    jp_name = ruby_base

            if not jp_name or jp_name in char_names:
                continue
            derived_names[jp_name] = full_name

        if derived_names:
            logger.info(
                f"   Derived {len(derived_names)} character names from character_profiles "
                "(character_names fallback)."
            )

        combined_char_names = dict(char_names)
        combined_char_names.update(derived_names)

        # Resolve JP-key continuity against legacy EN-key entries before push loop.
        self._promote_legacy_alias_keys(combined_char_names)

        for jp_name, en_name in combined_char_names.items():
            if not isinstance(en_name, str) or not en_name.strip():
                continue

            resolved_en_name = self._resolve_en_name_via_alias(jp_name, en_name)

            existing = self.bible.get_character(jp_name)
            if existing:
                # Already in bible — check for conflict
                bible_en = str(existing.get('canonical_en', '') or '').strip()

                # Fill missing canonical_en on existing entries to avoid null-canonical drift.
                if not bible_en:
                    self.bible.add_entry('characters', jp_name, {'canonical_en': resolved_en_name})
                    bible_en = resolved_en_name
                    result.characters_enriched += 1

                if bible_en and bible_en.lower() != resolved_en_name.lower():
                    if canonical_source == "manifest":
                        self.bible.add_entry('characters', jp_name, {
                            'canonical_en': resolved_en_name,
                            'source': 'phase1.5_manifest_authority',
                        })
                        result.characters_enriched += 1
                        logger.info(
                            "   [BIBLE-PUSH] Manifest authority: %s canonical_en '%s' -> '%s'",
                            jp_name,
                            bible_en,
                            resolved_en_name,
                        )
                        result.characters_skipped += 1
                        continue

                    # Alias-backed reconciliation: if a strong legacy EN-key alias supports
                    # resolved_en_name, repair polluted JP canonical_en in-place.
                    if self._has_alias_evidence_for(resolved_en_name):
                        self.bible.add_entry('characters', jp_name, {
                            'canonical_en': resolved_en_name,
                            'source': 'phase1.5_alias_reconcile',
                        })
                        result.characters_enriched += 1
                        logger.info(
                            "   [BIBLE-REPAIR] Reconciled %s canonical_en: '%s' -> '%s'",
                            jp_name,
                            bible_en,
                            resolved_en_name,
                        )
                    else:
                        # Conflict: manifest says X, bible says Y
                        # Bible wins (canonical), log the conflict
                        result.conflicts.append(
                            f"  {jp_name}: manifest='{resolved_en_name}' vs bible='{bible_en}' → bible kept"
                        )
                result.characters_skipped += 1
            else:
                # New character — add to bible
                self.bible.add_entry('characters', jp_name, {
                    'canonical_en': resolved_en_name,
                    'source': (
                        'phase1.5_auto_sync_profiles'
                        if jp_name in derived_names
                        else 'phase1.5_auto_sync'
                    ),
                    'discovered_in': manifest.get('volume_id', ''),
                })
                result.characters_added += 1
                logger.debug(f"   New character: {jp_name} → {resolved_en_name}")

        # ── Enrich with character_profiles ───────────────────────
        for profile_key, profile_data in profiles.items():
            if not isinstance(profile_data, dict):
                continue

            # Find the corresponding bible entry
            jp_key = self._resolve_profile_key(profile_key, profile_data)
            if not jp_key:
                continue

            existing = self.bible.get_character(jp_key)
            if not existing:
                continue  # Not in bible, nothing to enrich

            # Build enrichment dict from profile
            enrichments = self._extract_enrichments(profile_data)
            if enrichments:
                self.bible.add_entry('characters', jp_key, enrichments)
                result.characters_enriched += 1

        # ── Register volume ──────────────────────────────────────
        volume_id = manifest.get('volume_id', '')
        if volume_id:
            short_id = self.bible_ctrl._extract_short_id(volume_id)
            title = manifest.get('metadata', {}).get('title', '')

            # Register in bible
            from pipeline.metadata_processor.agent import extract_volume_number
            idx = extract_volume_number(title) or len(self.bible.volumes_registered) + 1
            self.bible.register_volume(
                volume_id=short_id or volume_id,
                title=title,
                index=idx
            )

            # Also link in index
            if short_id:
                self.bible_ctrl.link_volume(volume_id, self.series_id)

            result.volume_registered = True

        # ── Save & report ────────────────────────────────────────
        if result.total_changes > 0 or result.volume_registered:
            self.bible.save()
            # Update index entry count
            entry = self.bible_ctrl.index.get('series', {}).get(self.series_id, {})
            entry['entry_count'] = self.bible.entry_count()
            self.bible_ctrl._save_index()
            logger.info(f"📖 Bible updated: {self.series_id}")

        if result.conflicts:
            logger.warning(f"⚠️  {len(result.conflicts)} name conflict(s) detected (bible kept):")
            for c in result.conflicts:
                logger.warning(c)

        logger.info(f"   {result.summary()}")
        return result

    @staticmethod
    def _is_jp_key(text: str) -> bool:
        return bool(re.search(r'[\u3040-\u30ff\u4e00-\u9fff]', str(text or '')))

    @staticmethod
    def _is_latin_name_key(text: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z][A-Za-z\-\.' ]*[A-Za-z]", str(text or '').strip()))

    @staticmethod
    def _name_similarity(a: str, b: str) -> float:
        a_norm = re.sub(r"\s+", " ", str(a or '').strip().lower())
        b_norm = re.sub(r"\s+", " ", str(b or '').strip().lower())
        if not a_norm or not b_norm:
            return 0.0
        return SequenceMatcher(None, a_norm, b_norm).ratio()

    def _find_best_legacy_alias_key(self, en_name: str) -> Optional[str]:
        """Find best legacy EN-key bible entry for a potentially misspelled EN name."""
        if not self.bible:
            return None

        probe = str(en_name or '').strip()
        if not probe:
            return None

        best_key = None
        best_score = 0.0
        for key, data in self.bible.get_all_characters().items():
            if not self._is_latin_name_key(key):
                continue
            if not isinstance(data, dict):
                continue

            canonical = str(data.get('canonical_en', '') or '').strip()
            candidate = canonical or str(key).strip()
            if not candidate:
                continue

            score = self._name_similarity(probe, candidate)
            if score > best_score:
                best_score = score
                best_key = str(key).strip()

        # Conservative-but-practical threshold to catch common romanization drift
        # like Clael/Klael and Rileis/Rileys.
        if best_score >= 0.70:
            return best_key
        return None

    def _has_alias_evidence_for(self, canonical_candidate: str) -> bool:
        """Return True when a strong legacy EN-key alias supports canonical_candidate."""
        if not self.bible:
            return False

        candidate = str(canonical_candidate or '').strip()
        if not candidate:
            return False

        alias_key = self._find_best_legacy_alias_key(candidate)
        if not alias_key:
            return False

        alias_entry = self.bible.get_character(alias_key)
        if not isinstance(alias_entry, dict):
            return False

        alias_canonical = str(alias_entry.get('canonical_en', '') or '').strip() or alias_key
        return alias_canonical.lower() == candidate.lower()

    def _resolve_en_name_via_alias(self, jp_name: str, en_name: str) -> str:
        """Resolve canonical EN via legacy alias key when it is a strong match."""
        resolved = str(en_name or '').strip()
        if not resolved:
            return resolved
        if not self._is_jp_key(jp_name):
            return resolved

        alias_key = self._find_best_legacy_alias_key(resolved)
        if not alias_key:
            return resolved

        alias_entry = self.bible.get_character(alias_key) if self.bible else None
        if not isinstance(alias_entry, dict):
            return resolved

        alias_canonical = str(alias_entry.get('canonical_en', '') or '').strip() or alias_key
        if alias_canonical and alias_canonical.lower() != resolved.lower():
            logger.info(
                "   [BIBLE-ALIAS] Canonicalized '%s' via legacy alias '%s' → '%s'",
                resolved,
                alias_key,
                alias_canonical,
            )
            return alias_canonical
        return resolved

    def _promote_legacy_alias_keys(self, combined_char_names: Dict[str, str]) -> int:
        """Promote legacy EN-key character entries to JP keys and dedupe bible characters."""
        if not self.bible or not isinstance(combined_char_names, dict):
            return 0

        chars = self.bible.data.get('characters', {})
        if not isinstance(chars, dict):
            return 0

        promoted = 0
        for jp_name, en_name in combined_char_names.items():
            if not self._is_jp_key(jp_name):
                continue
            if self.bible.get_character(jp_name):
                continue

            alias_key = self._find_best_legacy_alias_key(en_name)
            if not alias_key or alias_key == jp_name:
                continue
            alias_entry = chars.get(alias_key)
            if not isinstance(alias_entry, dict):
                continue

            alias_payload = dict(alias_entry)
            alias_canonical = str(alias_payload.get('canonical_en', '') or '').strip() or alias_key
            alias_payload['canonical_en'] = alias_canonical
            alias_payload.setdefault('source', 'legacy_alias_promote')

            self.bible.add_entry('characters', jp_name, alias_payload)
            chars.pop(alias_key, None)
            promoted += 1
            logger.info(
                "   [BIBLE-DEDUPE] Promoted legacy key '%s' -> '%s' (canonical='%s')",
                alias_key,
                jp_name,
                alias_canonical,
            )

        if promoted:
            logger.info(f"   [BIBLE-DEDUPE] Promoted {promoted} legacy alias key(s)")
        return promoted

    @staticmethod
    def _eps_to_band(eps_score: float) -> str:
        """Map EPS score to a canonical band label."""
        try:
            eps = float(eps_score)
        except (TypeError, ValueError):
            return "NEUTRAL"
        if eps <= -0.5:
            return "COLD"
        if eps <= -0.1:
            return "COOL"
        if eps < 0.1:
            return "NEUTRAL"
        if eps < 0.5:
            return "WARM"
        return "HOT"

    @staticmethod
    def _chapter_sort_key(chapter_payload: Dict[str, Any]) -> tuple:
        """Sort chapter payloads in a stable chapter-first order."""
        chapter_id = str(chapter_payload.get("id", "")).strip()
        match = re.search(r"(\d+)", chapter_id)
        if match:
            return (0, int(match.group(1)), chapter_id)
        return (1, chapter_id)

    def _resolve_bible_character_key_by_en_name(self, character_name: str) -> Optional[str]:
        """Resolve an EN-facing character label back to the bible's JP key."""
        probe = str(character_name or "").strip().lower()
        if not probe or not self.bible:
            return None

        for jp_name, char_data in self.bible.get_all_characters().items():
            if not isinstance(char_data, dict):
                continue
            canonical = str(char_data.get("canonical_en", "")).strip().lower()
            if canonical and canonical == probe:
                return jp_name
            short_name = str(char_data.get("short_name", "")).strip().lower()
            if short_name and short_name == probe:
                return jp_name
        return None

    def _extract_latest_eps_states(self, manifest: dict) -> Dict[str, Dict[str, Any]]:
        """Extract the most recent per-character EPS state from manifest chapters."""
        if not self.bible:
            return {}

        metadata_block = manifest.get("metadata_en", {})
        if not isinstance(metadata_block, dict) or not metadata_block:
            metadata_block = manifest.get("metadata_vn", {})
        if not isinstance(metadata_block, dict):
            return {}

        chapters = metadata_block.get("chapters", {})
        if isinstance(chapters, dict):
            chapter_items = []
            for chapter_id, payload in chapters.items():
                if isinstance(payload, dict):
                    item = dict(payload)
                    item.setdefault("id", chapter_id)
                    chapter_items.append(item)
        elif isinstance(chapters, list):
            chapter_items = [dict(item) for item in chapters if isinstance(item, dict)]
        else:
            chapter_items = []

        latest_states: Dict[str, Dict[str, Any]] = {}
        volume_id = str(manifest.get("volume_id", "")).strip()
        for chapter_payload in sorted(chapter_items, key=self._chapter_sort_key):
            chapter_id = str(chapter_payload.get("id", "")).strip()
            eps_data = chapter_payload.get("emotional_proximity_signals", {})
            if not isinstance(eps_data, dict):
                continue
            raw_scene_intents = chapter_payload.get("scene_intents", [])
            scene_intents = []
            if isinstance(raw_scene_intents, list):
                scene_intents = [
                    str(intent).strip()
                    for intent in raw_scene_intents
                    if str(intent).strip()
                ][:6]

            for character_name, signal_data in eps_data.items():
                if not isinstance(signal_data, dict):
                    continue
                jp_key = self._resolve_bible_character_key_by_en_name(character_name)
                if not jp_key:
                    continue
                canonical_en = str(
                    signal_data.get("canonical_name_en")
                    or character_name
                ).strip()
                try:
                    eps_score = float(signal_data.get("eps_score", 0.0))
                except (TypeError, ValueError):
                    eps_score = 0.0
                signals = signal_data.get("signals", {})
                if not isinstance(signals, dict):
                    signals = {}
                clean_signals = {}
                for key, value in signals.items():
                    try:
                        clean_signals[str(key).strip()] = float(value)
                    except (TypeError, ValueError):
                        continue

                voice_band = str(signal_data.get("voice_band", "")).strip().upper()
                if not voice_band:
                    voice_band = self._eps_to_band(eps_score)

                latest_states[jp_key] = {
                    "canonical_name_en": canonical_en,
                    "source_volume_id": volume_id,
                    "source_chapter_id": chapter_id,
                    "eps_score": round(eps_score, 3),
                    "voice_band": voice_band,
                    "signals": clean_signals,
                    "scene_intents": scene_intents,
                    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }

        return latest_states

    def push_extended(
        self,
        manifest: dict,
        voice_profiles: Optional[Dict[str, Any]] = None,
        arc_resolution: str = "",
        latest_eps_states: Optional[Dict[str, Any]] = None,
    ) -> BiblePushResult:
        """
        Extended push for Phase 2.5 continuity updates.

        Adds/updates voice-layer character fields in bible:
        - voice_register
        - speech_patterns
        - translation_notes
        - established_nicknames
        - latest_eps_state
        """
        if not self.bible:
            return BiblePushResult()

        result = BiblePushResult()
        profiles = voice_profiles or {}

        for profile_key, profile_data in profiles.items():
            if not isinstance(profile_data, dict):
                continue

            jp_key: Optional[str] = None
            if re.search(r'[\u3040-\u9fff]', str(profile_key)):
                jp_key = str(profile_key)
            else:
                profile_stub = {"full_name": str(profile_key)}
                jp_key = self._resolve_profile_key(str(profile_key), profile_stub)
                if not jp_key:
                    for jp_name, char in self.bible.get_all_characters().items():
                        if not isinstance(char, dict):
                            continue
                        short = str(char.get("short_name", "")).strip().lower()
                        if short and short == str(profile_key).strip().lower():
                            jp_key = jp_name
                            break

            if not jp_key:
                continue

            existing = self.bible.get_character(jp_key)
            if not isinstance(existing, dict):
                continue

            enrichments: Dict[str, Any] = {}
            voice_register = str(profile_data.get("voice_register", "")).strip()
            if voice_register:
                enrichments["voice_register"] = voice_register

            speech_patterns = profile_data.get("speech_patterns", [])
            if isinstance(speech_patterns, list):
                items = [str(v).strip() for v in speech_patterns if str(v).strip()]
                if items:
                    enrichments["speech_patterns"] = items[:12]

            translation_notes = str(profile_data.get("translation_notes", "")).strip()
            if translation_notes:
                enrichments["translation_notes"] = translation_notes

            nicknames = profile_data.get("established_nicknames", {})
            if isinstance(nicknames, dict) and nicknames:
                clean_nicknames = {
                    str(k).strip(): str(v).strip()
                    for k, v in nicknames.items()
                    if str(k).strip() and str(v).strip()
                }
                if clean_nicknames:
                    enrichments["established_nicknames"] = clean_nicknames

            if not enrichments:
                continue

            self.bible.add_entry("characters", jp_key, enrichments)
            result.characters_enriched += 1

        eps_states = latest_eps_states if isinstance(latest_eps_states, dict) else None
        if eps_states is None:
            eps_states = self._extract_latest_eps_states(manifest)

        for jp_key, eps_state in eps_states.items():
            if not isinstance(eps_state, dict):
                continue
            existing = self.bible.get_character(jp_key)
            if not isinstance(existing, dict):
                continue
            self.bible.add_entry("characters", jp_key, {"latest_eps_state": eps_state})
            result.eps_states_updated += 1

        arc_resolution = str(arc_resolution or "").strip()
        if arc_resolution:
            continuity = self.bible.data.setdefault("continuity_notes", {})
            volume_id = str(manifest.get("volume_id", "")).strip()
            key = volume_id or datetime.datetime.now().strftime("volume_%Y%m%d")
            continuity[key] = arc_resolution

        if result.characters_enriched > 0 or result.eps_states_updated > 0 or arc_resolution:
            self.bible.save()
            entry = self.bible_ctrl.index.get("series", {}).get(self.series_id, {})
            entry["entry_count"] = self.bible.entry_count()
            self.bible_ctrl._save_index()
            logger.info(
                f"📖 Bible extended push saved: enriched={result.characters_enriched}, "
                f"eps={result.eps_states_updated}, "
                f"arc_resolution={'yes' if arc_resolution else 'no'}"
            )

        return result

    # ── Helpers ───────────────────────────────────────────────────

    def _resolve_profile_key(
        self, profile_key: str, profile_data: dict
    ) -> Optional[str]:
        """Map a character_profiles key to a JP name in the bible.

        Profiles may use JP keys (V2) or English keys (V1).
        """
        # If key is JP (contains CJK characters), use directly
        if re.search(r'[\u3040-\u9fff]', profile_key):
            return profile_key

        # English key (V1 format) — try to match via canonical_en
        en_name = profile_data.get('full_name',
                                   profile_key.replace('_', ' '))
        for jp, char in self.bible.data.get('characters', {}).items():
            if isinstance(char, dict):
                if char.get('canonical_en', '').lower() == en_name.lower():
                    return jp
        return None

    def _extract_visual_identity_non_color(self, profile_data: dict) -> Dict[str, Any]:
        """Extract normalized non-color visual identity payload from a profile."""
        identity = profile_data.get("visual_identity_non_color")
        def _normalize_habitual_gestures(value: Any) -> List[Dict[str, Any]]:
            normalized: List[Dict[str, Any]] = []
            if isinstance(value, str) and value.strip():
                return [{"gesture": value.strip()}]
            if not isinstance(value, list):
                return normalized
            for item in value:
                if isinstance(item, dict):
                    gesture = str(item.get("gesture", "")).strip()
                    if not gesture:
                        continue
                    entry: Dict[str, Any] = {"gesture": gesture}
                    for key in ("trigger", "intensity", "narrative_effect"):
                        v = item.get(key)
                        if isinstance(v, str) and v.strip():
                            entry[key] = v.strip()
                    chapters = item.get("evidence_chapters")
                    if isinstance(chapters, list):
                        items = [str(ch).strip() for ch in chapters if str(ch).strip()]
                        if items:
                            entry["evidence_chapters"] = items[:6]
                    confidence = item.get("confidence")
                    if isinstance(confidence, (int, float)):
                        entry["confidence"] = round(max(0.0, min(1.0, float(confidence))), 3)
                    normalized.append(entry)
                else:
                    text = str(item).strip()
                    if text:
                        normalized.append({"gesture": text})
                if len(normalized) >= 6:
                    break
            return normalized

        if isinstance(identity, str) and identity.strip():
            return {"identity_summary": identity.strip(), "habitual_gestures": []}

        if isinstance(identity, list):
            markers = [str(v).strip() for v in identity if str(v).strip()]
            if markers:
                return {"non_color_markers": markers[:8], "habitual_gestures": []}

        if isinstance(identity, dict):
            cleaned: Dict[str, Any] = {}
            for key in (
                "hairstyle",
                "clothing_signature",
                "expression_signature",
                "posture_signature",
                "accessory_signature",
                "identity_summary",
                "body_silhouette",
                "non_color_markers",
            ):
                value = identity.get(key)
                if isinstance(value, str) and value.strip():
                    cleaned[key] = value.strip()
                elif isinstance(value, list):
                    items = [str(v).strip() for v in value if str(v).strip()]
                    if items:
                        cleaned[key] = items[:8]
            habitual = _normalize_habitual_gestures(identity.get("habitual_gestures"))
            if habitual:
                cleaned["habitual_gestures"] = habitual
            if cleaned:
                return cleaned

        appearance = profile_data.get("appearance")
        if isinstance(appearance, str) and appearance.strip():
            return {"identity_summary": appearance.strip(), "habitual_gestures": []}
        return {}

    def _extract_enrichments(self, profile_data: dict) -> Dict[str, Any]:
        """Extract enrichable fields from a character profile."""
        enrichments: Dict[str, Any] = {}

        if profile_data.get('nickname'):
            enrichments['short_name'] = profile_data['nickname']
        if profile_data.get('relationship_to_protagonist'):
            enrichments['category'] = profile_data['relationship_to_protagonist']
        if profile_data.get('origin'):
            enrichments['affiliation'] = profile_data['origin']
        if profile_data.get('keigo_switch') and isinstance(
            profile_data['keigo_switch'], dict
        ):
            enrichments['keigo'] = profile_data['keigo_switch']
        visual_identity = self._extract_visual_identity_non_color(profile_data)
        if visual_identity:
            enrichments['visual_identity_non_color'] = visual_identity

        # Build notes from personality_traits
        traits = profile_data.get('personality_traits', [])
        if traits:
            if isinstance(traits, list):
                enrichments['notes'] = ', '.join(str(t) for t in traits)
            elif isinstance(traits, str):
                enrichments['notes'] = traits

        return enrichments

    # ── Continuity Diff Report ───────────────────────────────────

    def generate_continuity_report(
        self,
        manifest: dict,
        pull_result: Optional[BiblePullResult] = None,
        push_result: Optional[BiblePushResult] = None,
    ) -> Path:
        """Generate a continuity_diff_report.json artifact for this run.

        Captures: new terms, conflicts, overrides, rejected pushes,
        and per-run KPIs (name drift, glossary violations, sync status).

        Args:
            manifest: The processed manifest dict.
            pull_result: Result from pull(), if available.
            push_result: Result from push(), if available.

        Returns:
            Path to the written report file.
        """
        report: Dict[str, Any] = {
            "report_type": "continuity_diff",
            "timestamp": datetime.datetime.now().isoformat(),
            "volume_id": manifest.get("volume_id", ""),
            "series_id": self.series_id or "",
            "bible_resolved": self.bible is not None,
        }

        # ── Pull KPIs ────────────────────────────────────────────
        if pull_result:
            report["pull"] = {
                "characters_inherited": pull_result.characters_inherited,
                "geography_inherited": pull_result.geography_inherited,
                "weapons_inherited": pull_result.weapons_inherited,
                "other_inherited": pull_result.other_inherited,
                "total_inherited": pull_result.total_inherited,
                "overrides": pull_result.overrides,
                "override_count": len(pull_result.overrides),
            }
        else:
            report["pull"] = {"status": "skipped"}

        # ── Push KPIs ────────────────────────────────────────────
        if push_result:
            report["push"] = {
                "characters_added": push_result.characters_added,
                "characters_enriched": push_result.characters_enriched,
                "characters_skipped": push_result.characters_skipped,
                "conflicts": push_result.conflicts,
                "conflict_count": len(push_result.conflicts),
                "volume_registered": push_result.volume_registered,
                "total_changes": push_result.total_changes,
            }
        else:
            report["push"] = {"status": "skipped"}

        # ── Name Drift Detection ─────────────────────────────────
        drift_count = (
            len(getattr(pull_result, "overrides", []))
            + len(getattr(push_result, "conflicts", []))
        )
        report["kpis"] = {
            "name_drift_events": drift_count,
            "pull_overrides": len(getattr(pull_result, "overrides", [])),
            "push_conflicts": len(getattr(push_result, "conflicts", [])),
            "bible_sync_success": self.bible is not None,
            "total_inherited": getattr(pull_result, "total_inherited", 0),
            "total_pushed": getattr(push_result, "total_changes", 0),
        }

        # ── Write report ─────────────────────────────────────────
        report_path = self.work_dir / "continuity_diff_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"📋 Continuity diff report: {report_path.name} "
                     f"(drift={drift_count}, inherited={report['kpis']['total_inherited']}, "
                     f"pushed={report['kpis']['total_pushed']})")
        return report_path

    # ── Manual Sync (CLI) ────────────────────────────────────────

    @classmethod
    def manual_sync(cls, work_dir: Path, pipeline_root: Path,
                    direction: str = "both") -> dict:
        """Run bible sync manually from CLI.

        Args:
            work_dir: Volume's working directory
            pipeline_root: Pipeline root path
            direction: 'pull', 'push', or 'both'

        Returns:
            Summary dict with pull and/or push results
        """
        manifest_path = work_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")

        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)

        agent = cls(work_dir, pipeline_root)
        if not agent.resolve(manifest):
            return {'error': 'No bible found for this volume',
                    'volume_id': manifest.get('volume_id', '?')}

        result = {
            'series_id': agent.series_id,
            'volume_id': manifest.get('volume_id', ''),
        }

        if direction in ('pull', 'both'):
            pull = agent.pull(manifest)
            result['pull'] = {
                'characters_inherited': pull.characters_inherited,
                'geography_inherited': pull.geography_inherited,
                'weapons_inherited': pull.weapons_inherited,
                'other_inherited': pull.other_inherited,
                'total_inherited': pull.total_inherited,
                'manifest_updated': False,
            }

        if direction in ('push', 'both'):
            push = agent.push(manifest)
            result['push'] = {
                'characters_added': push.characters_added,
                'characters_enriched': push.characters_enriched,
                'characters_skipped': push.characters_skipped,
                'conflicts': push.conflicts,
                'volume_registered': push.volume_registered,
                'total_changes': push.total_changes,
            }

        return result

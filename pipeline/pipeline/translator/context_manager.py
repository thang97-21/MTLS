"""
Context Manager for Translation Continuity.
Maintains cross-chapter context for consistent translation.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field

from pipeline.translator.config import get_lookback_chapters, is_name_consistency_enabled

logger = logging.getLogger(__name__)


@dataclass
class ArcClosing:
    """Prose closing of a single POV arc within a chapter."""
    character_archetype: str       # e.g., "Koumi (Childhood Friend)"
    section_header: str            # e.g., "─── The Childhood-Friend College Girl Gets Jealous ───"
    closing_prose: str             # Actual last N lines of the arc (raw EN prose)
    closing_line_count: int        # How many lines were extracted
    emotional_register: str = ""   # e.g., "jealousy_suppressed", "dark_obsession"


@dataclass
class ChapterContext:
    """Context data for a single chapter."""
    chapter_id: str
    summary: str
    characters_introduced: List[str] = field(default_factory=list)
    terms_introduced: Dict[str, str] = field(default_factory=dict)
    plot_points: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    arc_closings: List[ArcClosing] = field(default_factory=list)


class ContextManager:
    """
    Manages translation context across chapters.

    Responsibilities:
    1. Track character names and their romanizations
    2. Maintain glossary of translated terms
    3. Store summaries of previous chapters for continuity
    4. Provide context prompts for the translator
    """

    def __init__(self, work_dir: Path):
        """
        Initialize ContextManager.

        Args:
            work_dir: Volume working directory (contains JP/, EN/, manifest.json).
        """
        self.work_dir = work_dir
        self.context_dir = work_dir / ".context"
        self.context_dir.mkdir(exist_ok=True)

        # File paths
        self.name_registry_path = self.context_dir / "name_registry.json"
        self.glossary_path = self.context_dir / "glossary.json"
        self.chapter_summaries_path = self.context_dir / "chapter_summaries.json"

        # Load existing data
        self.name_registry: Dict[str, str] = self._load_json(self.name_registry_path, {})
        self.glossary: Dict[str, str] = self._load_json(self.glossary_path, {})
        self.chapter_summaries: Dict[str, ChapterContext] = self._load_chapter_summaries()

        # Config
        self.lookback_chapters = get_lookback_chapters()
        self.enforce_names = is_name_consistency_enabled()

    def _load_json(self, path: Path, default: Any) -> Any:
        """Load JSON file or return default."""
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load {path}: {e}")
        return default

    def _save_json(self, path: Path, data: Any):
        """Save data to JSON file."""
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save {path}: {e}")

    def _load_chapter_summaries(self) -> Dict[str, ChapterContext]:
        """Load chapter summaries from disk."""
        raw = self._load_json(self.chapter_summaries_path, {})
        summaries = {}
        for chapter_id, data in raw.items():
            try:
                raw_arc_closings = data.get("arc_closings", [])
                arc_closings = []
                for ac in raw_arc_closings:
                    if isinstance(ac, dict):
                        arc_closings.append(ArcClosing(
                            character_archetype=ac.get("character_archetype", ""),
                            section_header=ac.get("section_header", ""),
                            closing_prose=ac.get("closing_prose", ""),
                            closing_line_count=ac.get("closing_line_count", 0),
                            emotional_register=ac.get("emotional_register", ""),
                        ))
                summaries[chapter_id] = ChapterContext(
                    chapter_id=data.get("chapter_id", chapter_id),
                    summary=data.get("summary", ""),
                    characters_introduced=data.get("characters_introduced", []),
                    terms_introduced=data.get("terms_introduced", {}),
                    plot_points=data.get("plot_points", []),
                    metadata=data.get("metadata", {}),
                    arc_closings=arc_closings,
                )
            except Exception as e:
                logger.warning(f"Failed to parse chapter context {chapter_id}: {e}")
        return summaries

    def _save_chapter_summaries(self):
        """Save chapter summaries to disk."""
        data = {cid: asdict(ctx) for cid, ctx in self.chapter_summaries.items()}
        self._save_json(self.chapter_summaries_path, data)

    def get_context_prompt(self, chapter_id: str) -> str:
        """
        Build context prompt for a chapter translation.

        Args:
            chapter_id: Current chapter being translated.

        Returns:
            Formatted context string for injection into translation prompt.
        """
        parts = []

        # 1. Character Name Registry
        if self.enforce_names and self.name_registry:
            parts.append("=== CHARACTER NAME REGISTRY ===")
            parts.append("Use these EXACT romanizations consistently:")
            for jp_name, en_name in sorted(self.name_registry.items()):
                parts.append(f"  {jp_name} → {en_name}")
            parts.append("")

        # 2. Glossary of Terms
        if self.glossary:
            parts.append("=== TERMINOLOGY GLOSSARY ===")
            parts.append("Use these established translations:")
            for jp_term, en_term in sorted(self.glossary.items()):
                parts.append(f"  {jp_term} → {en_term}")
            parts.append("")

        # 3. Previous Chapter Summaries (for continuity)
        previous_summaries = self._get_previous_summaries(chapter_id)
        if previous_summaries:
            parts.append("=== PREVIOUS CHAPTER CONTEXT ===")
            for ctx in previous_summaries:
                parts.append(f"[{ctx.chapter_id}] {ctx.summary}")
                if ctx.plot_points:
                    parts.append(f"  Key events: {', '.join(ctx.plot_points)}")
            parts.append("")

        if not parts:
            return "No previous context available. This appears to be the first chapter."

        return "\n".join(parts)

    def get_retrospective_arc_prompt(
        self,
        chapter_id: str,
        active_characters: Optional[List[str]] = None,
        max_arcs: int = 5,
        lines_per_closing: int = 20,
    ) -> str:
        """
        Build the retrospective POV anchor block for a chapter.

        Unlike get_context_prompt() which injects summary-based metadata,
        this method injects the actual closing prose of each POV arc from
        prior chapters — the emotional anchors that define character entry
        points in multi-POV retrospective series.

        Args:
            chapter_id: Current chapter being translated.
            active_characters: Characters whose arcs are active in this chapter.
                               If None, injects all characters with stored arc closings.
            max_arcs: Maximum arc closings to inject (token budget control).
            lines_per_closing: Lines to include per arc closing (informational only;
                               actual prose was extracted at storage time).

        Returns:
            Formatted retrospective anchor string, or "" if no arc closings available.
        """
        previous_summaries = self._get_previous_summaries(chapter_id)
        if not previous_summaries:
            return ""

        # Collect arc closings from previous chapters, newest first
        all_arcs: List[tuple] = []  # (chapter_id, ArcClosing)
        for ctx in reversed(previous_summaries):
            for arc in ctx.arc_closings:
                if active_characters:
                    # Filter to active characters (substring match on archetype)
                    if not any(
                        ch.lower() in arc.character_archetype.lower()
                        for ch in active_characters
                    ):
                        continue
                all_arcs.append((ctx.chapter_id, arc))

        if not all_arcs:
            return ""

        # Cap to max_arcs
        all_arcs = all_arcs[:max_arcs]

        lines = [
            "=== RETROSPECTIVE POV ANCHORS ===",
            "",
            "The following are the EXACT CLOSING PROSE passages from each character's",
            "most recent POV arc in prior chapters. These are not summaries — they are",
            "the character's actual last words to the reader before the current chapter.",
            "When you encounter this character's POV in the current chapter, their",
            "emotional register MUST continue from this exact pitch.",
            "",
        ]

        for src_chapter_id, arc in all_arcs:
            sep = "─" * 50
            lines.append(sep)
            lines.append(f"[{src_chapter_id.upper()}] {arc.character_archetype.upper()} — \"{arc.section_header}\"")
            lines.append(sep)
            lines.append(arc.closing_prose.strip())
            lines.append("")

        lines.append(
            "TRANSLATION INSTRUCTION — RETROSPECTIVE CONTINUITY:\n"
            "When translating each POV arc in this chapter, treat the corresponding\n"
            "anchor above as the emotional baseline. The current arc OPENS from where\n"
            "that anchor CLOSED. The closing staccato rhythm, the italicized interior\n"
            "voice, the specific emotional conflict — all carry forward unchanged until\n"
            "the current arc introduces a new development."
        )

        return "\n".join(lines)

    def _get_previous_summaries(self, current_chapter_id: str) -> List[ChapterContext]:
        """
        Get summaries of chapters preceding the current one.

        Uses chapter ordering based on chapter_id sorting or explicit order.
        Returns up to `lookback_chapters` previous summaries.
        """
        if not self.chapter_summaries:
            return []

        # Sort chapter IDs to determine order
        # Assumes chapter IDs are sortable (e.g., chapter_01, chapter_02)
        sorted_ids = sorted(self.chapter_summaries.keys())

        # Find position of current chapter
        try:
            current_idx = sorted_ids.index(current_chapter_id)
        except ValueError:
            # Current chapter not in summaries yet, use all previous
            current_idx = len(sorted_ids)

        # Get previous N chapters
        start_idx = max(0, current_idx - self.lookback_chapters)
        previous_ids = sorted_ids[start_idx:current_idx]

        return [self.chapter_summaries[cid] for cid in previous_ids]

    def add_chapter_context(
        self,
        chapter_id: str,
        summary: str,
        metadata: Optional[Dict[str, Any]] = None,
        characters: Optional[List[str]] = None,
        terms: Optional[Dict[str, str]] = None,
        plot_points: Optional[List[str]] = None,
        arc_closings: Optional[List[ArcClosing]] = None,
    ):
        """
        Add or update context for a translated chapter.

        Args:
            chapter_id: Chapter identifier.
            summary: Brief summary of chapter content.
            metadata: Additional metadata (word count, etc.).
            characters: New characters introduced in this chapter.
            terms: New terms/translations established.
            plot_points: Key plot events.
        """
        context = ChapterContext(
            chapter_id=chapter_id,
            summary=summary,
            characters_introduced=characters or [],
            terms_introduced=terms or {},
            plot_points=plot_points or [],
            metadata=metadata or {},
            arc_closings=arc_closings or [],
        )

        self.chapter_summaries[chapter_id] = context
        self._save_chapter_summaries()

        # Update global registries if new entries provided
        if characters:
            for char in characters:
                if char not in self.name_registry:
                    # Character without explicit translation - store as-is
                    logger.debug(f"New character noted: {char}")

        if terms:
            self.glossary.update(terms)
            self._save_json(self.glossary_path, self.glossary)

        logger.debug(f"Added context for {chapter_id}")

    def register_chapter_complete(
        self,
        chapter_id: str,
        chapter_num: Optional[int] = None,
        chapter_title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        arc_closings: Optional[List[ArcClosing]] = None,
    ) -> None:
        """
        Register minimal completion metadata for a translated chapter.

        This replaces inline per-chapter summarizer calls in Phase 2 while keeping
        chapter ordering and basic continuity metadata available.
        """
        title = (chapter_title or "").strip()
        if title:
            summary = title
        elif chapter_num is not None:
            summary = f"Chapter {chapter_num}"
        else:
            summary = "Translated chapter"

        payload = dict(metadata or {})
        if chapter_num is not None:
            payload.setdefault("chapter_num", chapter_num)
        if title:
            payload.setdefault("chapter_title", title)
        payload.setdefault("summary_skipped", True)
        payload.setdefault("context_mode", "minimal_registration")

        self.add_chapter_context(
            chapter_id=chapter_id,
            summary=summary,
            metadata=payload,
            characters=[],
            terms={},
            plot_points=[],
            arc_closings=arc_closings or [],
        )

    def register_name(self, jp_name: str, en_name: str):
        """
        Register a character name translation.

        Args:
            jp_name: Japanese name (kanji/kana).
            en_name: English romanization.
        """
        self.name_registry[jp_name] = en_name
        self._save_json(self.name_registry_path, self.name_registry)
        logger.info(f"Registered name: {jp_name} → {en_name}")

    def register_term(self, jp_term: str, en_term: str):
        """
        Register a term translation for consistency.

        Args:
            jp_term: Japanese term.
            en_term: English translation.
        """
        self.glossary[jp_term] = en_term
        self._save_json(self.glossary_path, self.glossary)
        logger.info(f"Registered term: {jp_term} → {en_term}")

    def get_name_registry(self) -> Dict[str, str]:
        """Get the full character name registry."""
        return self.name_registry.copy()

    def get_glossary(self) -> Dict[str, str]:
        """Get the full terminology glossary."""
        return self.glossary.copy()

    def clear_context(self):
        """Clear all context data (for fresh start)."""
        self.name_registry = {}
        self.glossary = {}
        self.chapter_summaries = {}

        # Remove files
        for path in [self.name_registry_path, self.glossary_path, self.chapter_summaries_path]:
            if path.exists():
                path.unlink()

        logger.info("Context cleared")

    def import_context_from_previous_volume(self, previous_context_dir: Path):
        """
        Import context from a previous volume for series continuity.

        Args:
            previous_context_dir: Path to .context/ directory of previous volume.
        """
        if not previous_context_dir.exists():
            logger.warning(f"Previous context directory not found: {previous_context_dir}")
            return

        # Import name registry
        prev_names = self._load_json(previous_context_dir / "name_registry.json", {})
        self.name_registry.update(prev_names)
        self._save_json(self.name_registry_path, self.name_registry)

        # Import glossary
        prev_glossary = self._load_json(previous_context_dir / "glossary.json", {})
        self.glossary.update(prev_glossary)
        self._save_json(self.glossary_path, self.glossary)

        logger.info(f"Imported context from {previous_context_dir}")
        logger.info(f"  Names: {len(prev_names)}, Terms: {len(prev_glossary)}")

    def export_volume_summary(self) -> Dict[str, Any]:
        """
        Export a summary of the volume's context for archival.

        Returns:
            Dictionary containing all context data.
        """
        return {
            "name_registry": self.name_registry,
            "glossary": self.glossary,
            "chapter_count": len(self.chapter_summaries),
            "chapters": {
                cid: asdict(ctx) for cid, ctx in self.chapter_summaries.items()
            }
        }

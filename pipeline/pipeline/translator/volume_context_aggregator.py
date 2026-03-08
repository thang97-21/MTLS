"""
Volume Context Aggregator - Builds comprehensive context from previous chapters.
Leverages Gemini's 1M token window for volume-level translation consistency.

Based on official Gemini Full Long Context specifications:
- Context window: 1 million tokens
- Best practice: Put query at END after all context
- Optimization: Use context caching for 4x cost reduction
"""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import json
import logging
import re
from dataclasses import dataclass, field
from collections import defaultdict

from pipeline.translator.context_manager import ArcClosing
from pipeline.translator.config import is_volume_context_legacy_mode

logger = logging.getLogger(__name__)


def _is_jp_retention_active(manifest: Dict[str, Any]) -> bool:
    """
    Gate check for ECR (Enhanced Cultural Retention) activation.

    Returns True when BOTH conditions hold:
      1. world_setting.type contains 'japan' (case-insensitive) or signals contemporary Japan
      2. translation_rules.cultural_terms_policy is 'retention' or 'retention_with_gloss'
         (if the policy key is absent, default to True for Japan-type settings)
    """
    if not isinstance(manifest, dict):
        return False
    metadata_en = manifest.get("metadata_en", {})
    if not isinstance(metadata_en, dict):
        return False

    ws = metadata_en.get("world_setting", {})
    if not isinstance(ws, dict):
        ws = {}
    ws_type = str(ws.get("type", "")).lower()
    ws_label = str(ws.get("label", "")).lower()
    world_ok = (
        "japan" in ws_type
        or "japan" in ws_label
        or "modern_japan" in ws_type
        or "contemporary_japan" in ws_type
        or "historical_japan" in ws_type
        or "rural_japan" in ws_type
        or "urban_japan" in ws_type
    )

    tr = metadata_en.get("translation_rules", {})
    if not isinstance(tr, dict):
        tr = {}
    policy = str(tr.get("cultural_terms_policy", "")).lower()
    # If policy is not set, treat as active for Japan-type worlds
    policy_ok = (not policy) or ("retention" in policy)

    return world_ok and policy_ok


@dataclass
class CharacterEntry:
    """Character information extracted from previous chapters."""
    name_en: str
    name_jp: str
    first_appearance_chapter: int
    personality_traits: List[str] = field(default_factory=list)
    relationships: Dict[str, str] = field(default_factory=dict)
    dialogue_style: str = ""
    honorifics_used: List[str] = field(default_factory=list)


@dataclass
class ChapterSummary:
    """Summary of a single chapter for context building."""
    chapter_num: int
    title: str
    plot_points: List[str] = field(default_factory=list)
    emotional_tone: str = ""
    new_characters: List[str] = field(default_factory=list)
    name_rendering: Dict[str, str] = field(default_factory=dict)  # full name → nickname used
    running_jokes: List[str] = field(default_factory=list)
    tone_shifts: List[str] = field(default_factory=list)


@dataclass
class VolumeContext:
    """Complete volume-level context for translation."""
    volume_title: str
    total_chapters_processed: int
    character_registry: Dict[str, CharacterEntry] = field(default_factory=dict)
    chapter_summaries: List[ChapterSummary] = field(default_factory=list)
    established_terminology: Dict[str, str] = field(default_factory=dict)
    recurring_patterns: Dict[str, Any] = field(default_factory=dict)
    overall_tone: str = ""
    translator_notes: List[Dict[str, Any]] = field(default_factory=list)
    # ECR (Component 1 + 2) — injected from manifest by VolumeContextAggregator
    culturally_loaded_terms: Dict[str, Any] = field(default_factory=dict)
    author_signature_patterns: Dict[str, Any] = field(default_factory=dict)

    def to_prompt_section(self) -> str:
        """
        Convert volume context to structured prompt section.
        Format optimized for Gemini's long context processing.
        """
        sections = []

        # Section 1: Volume Overview
        sections.append("# VOLUME-LEVEL CONTEXT")
        sections.append(f"**Title:** {self.volume_title}")
        sections.append(f"**Chapters Processed:** {self.total_chapters_processed}")
        sections.append(f"**Overall Tone:** {self.overall_tone}")
        sections.append("")

        # Section 2: Locked Name Rendering Table
        # Aggregated from all previous chapter name_rendering dicts.
        # This is the single most critical continuity signal — prevents per-chapter
        # name drift (e.g. "Luna" vs "Runa") by locking the rendering decision made
        # in the chapter where the character was first addressed by name.
        consolidated_rendering: Dict[str, str] = {}
        for summary in self.chapter_summaries:
            for full_name, nickname in summary.name_rendering.items():
                if full_name not in consolidated_rendering:
                    consolidated_rendering[full_name] = nickname  # first-seen wins
        if consolidated_rendering:
            sections.append("## LOCKED NAME RENDERING")
            sections.append(
                "These name forms are ESTABLISHED. Use them exactly — do not alternate:"
            )
            sections.append("")
            for full_name, nickname in consolidated_rendering.items():
                sections.append(f"- **{full_name}** → call as **{nickname}**")
            sections.append("")

        # Section 3: Character Registry
        if self.character_registry:
            sections.append("## CHARACTER REGISTRY")
            sections.append("Established characters from previous chapters:")
            sections.append("")
            for name, char in self.character_registry.items():
                jp_part = f" ({char.name_jp})" if char.name_jp else ""
                sections.append(f"### {char.name_en}{jp_part}")
                sections.append(f"- **First appearance:** Chapter {char.first_appearance_chapter}")
                if char.personality_traits:
                    sections.append(f"- **Personality:** {', '.join(char.personality_traits)}")
                if char.dialogue_style:
                    sections.append(f"- **Dialogue style:** {char.dialogue_style}")
                if char.relationships:
                    sections.append(f"- **Relationships:** {', '.join(f'{k}: {v}' for k, v in char.relationships.items())}")
                if char.honorifics_used:
                    sections.append(f"- **Honorifics:** {', '.join(char.honorifics_used)}")
                sections.append("")

        # Section 4: Chapter Progression
        if self.chapter_summaries:
            sections.append("## CHAPTER PROGRESSION")
            for summary in self.chapter_summaries[-3:]:  # Last 3 chapters for relevance (JIT sliding window)
                sections.append(f"### Chapter {summary.chapter_num}: {summary.title}")
                if summary.plot_points:
                    sections.append(f"**Plot:** {'; '.join(summary.plot_points[:3])}")
                if summary.emotional_tone:
                    sections.append(f"**Tone:** {summary.emotional_tone}")
                if summary.new_characters:
                    sections.append(f"**New characters:** {', '.join(summary.new_characters)}")
                sections.append("")

        # Section 5: Established Patterns
        if self.recurring_patterns:
            sections.append("## RECURRING PATTERNS")
            for pattern_type, pattern_data in self.recurring_patterns.items():
                sections.append(f"**{pattern_type}:** {pattern_data}")
            sections.append("")

        # Section 6: Terminology Consistency
        if self.established_terminology:
            sections.append("## ESTABLISHED TERMINOLOGY")
            for jp_term, en_translation in self.established_terminology.items():
                sections.append(f"- {jp_term} → {en_translation}")
            sections.append("")

        # Section 7: Translator Notes (from manifest.json)        # These are volume-specific directives that must be respected for every chapter.
        if self.translator_notes:
            critical = [n for n in self.translator_notes if n.get("priority") == "CRITICAL"]
            high = [n for n in self.translator_notes if n.get("priority") == "HIGH"]
            other = [n for n in self.translator_notes if n.get("priority") not in ("CRITICAL", "HIGH")]

            sections.append("## TRANSLATOR NOTES")
            sections.append(
                "These notes are MANDATORY directives for this volume. "
                "They apply to every chapter unless the note specifies otherwise."
            )
            sections.append("")

            for note in critical + high + other:
                priority_tag = f"[{note.get('priority', 'NOTE')}]"
                topic = note.get("topic", "")
                note_text = note.get("note", "")
                applies = note.get("applies_to_chapters", "")
                sections.append(f"### {priority_tag} {topic}")
                if applies:
                    sections.append(f"*Applies to: {applies}*")
                sections.append("")
                sections.append(note_text)
                sections.append("")

                # Render immersion_logic sub-entries if present
                for entry in note.get("immersion_logic", []):
                    name = entry.get("name", "")
                    desc = entry.get("description", "")
                    if name or desc:
                        sections.append(f"**{name}:** {desc}")
                        sections.append("")

                # Render known_anchor_lines if present
                anchor_lines = note.get("known_anchor_lines", [])
                if anchor_lines:
                    sections.append("**Known Anchor Lines:**")
                    for anchor in anchor_lines:
                        phrase = anchor.get("phrase_jp", "")
                        rule = anchor.get("rule", "")
                        register = anchor.get("register_note", "")
                        tooru_loc = anchor.get("tooru_pov_location", "")
                        echo_loc = anchor.get("tanaka_pov_echo", "")
                        sections.append(f"- JP: 「{phrase}」")
                        if tooru_loc:
                            sections.append(f"  - Source location: {tooru_loc}")
                        if echo_loc:
                            sections.append(f"  - Echo location: {echo_loc}")
                        if rule:
                            sections.append(f"  - Rule: {rule}")
                        if register:
                            sections.append(f"  - Register: {register}")
                    sections.append("")

                # Render locked_rendering as an explicit quoted block (highest visibility)
                locked = note.get("locked_rendering")
                if locked and isinstance(locked, dict):
                    jp = locked.get("jp", "")
                    en = locked.get("en", "")
                    instruction = locked.get("instruction", "")
                    sections.append(f"**LOCKED RENDERING — copy verbatim:**")
                    sections.append(f"  JP: {jp}")
                    sections.append(f"  EN: \"{en}\"")
                    if instruction:
                        sections.append(f"  {instruction}")
                    for usage_key in ("ch17_usage", "ch18_usage"):
                        usage = locked.get(usage_key, "")
                        if usage:
                            sections.append(f"  [{usage_key}] {usage}")
                    sections.append("")

                # Render options/recommendation if present (legacy fallback)
                options = note.get("options", [])
                if options:
                    sections.append("**Rendering options:**")
                    for opt in options:
                        sections.append(f"  - {opt}")
                recommendation = note.get("recommendation", "")
                if recommendation:
                    sections.append(f"**Recommendation:** {recommendation}")
                sections.append("")

        # Section 8: ECR — Culturally Loaded Terms (Component 1)
        clt = self.culturally_loaded_terms
        if isinstance(clt, dict) and clt:
            preserve_terms = {
                jp: entry for jp, entry in clt.items()
                if isinstance(entry, dict) and entry.get("retention_policy") in ("preserve_jp", "preserve_jp_first_use")
            }
            if preserve_terms:
                sections.append("## CULTURALLY LOADED TERMS — DO NOT SUBSTITUTE")
                sections.append(
                    "These JP terms MUST be retained in translation. "
                    "Do NOT genericize to English descriptors."
                )
                sections.append("")
                for jp_term, entry in preserve_terms.items():
                    romaji = entry.get("romaji", "")
                    policy = entry.get("retention_policy", "preserve_jp")
                    usage = entry.get("usage_context", "")
                    display = romaji if romaji else jp_term
                    policy_note = "(retain on first use with inline gloss, then short form)" if policy == "preserve_jp_first_use" else "(NEVER substitute)"
                    line = f"- {display} → retain '{display}' {policy_note}"
                    if usage:
                        line += f"  [{usage}]"
                    sections.append(line)
                sections.append("")

        # Section 9: Author Signature Patterns (Component 2)
        asp = self.author_signature_patterns
        if isinstance(asp, dict):
            patterns = asp.get("detected_patterns", [])
            author_name_en = asp.get("author_name_en", "") or asp.get("author_name_jp", "")
            if isinstance(patterns, list) and patterns:
                sections.append("## AUTHOR SIGNATURE PATTERNS — STRUCTURAL PRESERVATION")
                if author_name_en:
                    sections.append(f"Author: {author_name_en}")
                sections.append(
                    "These structural patterns are MANDATORY to preserve. "
                    "See each rule below."
                )
                sections.append("")
                for pat in patterns:
                    if not isinstance(pat, dict):
                        continue
                    pid = pat.get("pattern_id", "")
                    en_structure = pat.get("en_structure", "")
                    preservation_rule = pat.get("preservation_rule", "")
                    sections.append(f"### {pid}")
                    if en_structure:
                        sections.append(f"Structure: {en_structure}")
                    if preservation_rule:
                        sections.append(f"Rule: {preservation_rule}")
                    sections.append("")
            # Literary references
            refs = asp.get("literary_references", [])
            if isinstance(refs, list) and refs:
                sections.append("## LITERARY REFERENCES")
                for ref in refs:
                    if not isinstance(ref, dict):
                        continue
                    ref_en = ref.get("ref_en", "")
                    author_en = ref.get("author_en", "")
                    handling = ref.get("handling", "preserve exact name")
                    if ref_en:
                        suffix = f" (by {author_en})" if author_en else ""
                        sections.append(f"- {ref_en}{suffix} → {handling}")
                sections.append("")

        return "\n".join(sections)


class VolumeContextAggregator:
    """
    Aggregates context from all previous chapters for volume-aware translation.

    Builds context structure:
    1. Character registry (all characters from previous chapters)
    2. Previous chapters summary (plot, tone, style)
    3. Established patterns (dialogue rhythm, running jokes, tone shifts)
    4. Translation consistency rules (names, honorifics, terminology)

    Total size: 10-20 KB per volume (well under 1M token limit)
    """

    def __init__(self, work_dir: Path):
        self.work_dir = work_dir
        self.bible_path = work_dir / '.bible.json'
        self.context_path = work_dir / '.context'
        self.context_cache = {}
        self.legacy_mode = is_volume_context_legacy_mode()

        # Ensure context directory exists
        self.context_path.mkdir(exist_ok=True)

    def aggregate_volume_context(
        self,
        current_chapter_num: int,
        source_dir: Path,
        en_dir: Path
    ) -> VolumeContext:
        """
        Aggregate context from chapters 1 to (current_chapter_num - 1).

        Args:
            current_chapter_num: The chapter being translated (1-indexed)
            source_dir: Directory containing JP source chapters
            en_dir: Directory containing EN translated chapters

        Returns:
            VolumeContext with all previous chapter information
        """
        if not self.legacy_mode:
            logger.info(
                "[VOLUME-CTX][LEGACY] aggregate_volume_context is disabled. "
                "Phase 2 now uses bible pull context block."
            )
            ecr_data = self._load_ecr_data()
            return VolumeContext(
                volume_title=self._get_volume_title(),
                total_chapters_processed=max(0, current_chapter_num - 1),
                translator_notes=self._load_translator_notes(),
                culturally_loaded_terms=ecr_data.get("culturally_loaded_terms", {}),
                author_signature_patterns=ecr_data.get("author_signature_patterns", {}),
            )

        logger.info(f"Aggregating volume context for Chapter {current_chapter_num}")

        # Initialize volume context
        volume_context = VolumeContext(
            volume_title=self._get_volume_title(),
            total_chapters_processed=current_chapter_num - 1
        )

        # Load translator notes from manifest.json — applies to ALL chapters including ch01.
        # These are volume-level directives (POV mirror rules, anchor lines, rendering decisions)
        # that the translator must observe from the very first chapter.
        volume_context.translator_notes = self._load_translator_notes()

        # If this is Chapter 1, return context with only translator notes
        if current_chapter_num <= 1:
            logger.info("Chapter 1: No previous chapter context — translator notes loaded")
            return volume_context

        # Phase 1.56 artifacts: use as primary source for batch-mode context
        # where EN chapter outputs do not exist yet.
        phase_assets = self._load_phase156_context_assets()

        # Load bible for character registry baseline
        bible_data = self._load_bible()
        if bible_data:
            volume_context.character_registry = self._extract_characters_from_bible(bible_data)
        elif phase_assets.get("character_registry"):
            volume_context.character_registry = self._extract_characters_from_phase_assets(phase_assets)

        # Process each previous chapter
        for chapter_num in range(1, current_chapter_num):
            chapter_summary = self._build_chapter_summary_from_phase_assets(
                chapter_num, phase_assets
            )
            if chapter_summary is None:
                chapter_summary = self._process_chapter(chapter_num, source_dir, en_dir)
            if chapter_summary:
                volume_context.chapter_summaries.append(chapter_summary)

                # Update character registry with new characters
                for char_name in chapter_summary.new_characters:
                    if char_name not in volume_context.character_registry:
                        # Create new character entry (will be enriched by subsequent chapters)
                        volume_context.character_registry[char_name] = CharacterEntry(
                            name_en=char_name,
                            name_jp="",  # To be filled from bible or context
                            first_appearance_chapter=chapter_num
                        )

        # Phase 1.56 character registry should be preferred when available because
        # it captures full-corpus identity/voice planning before Chapter 2 starts.
        if phase_assets.get("character_registry"):
            phase_characters = self._extract_characters_from_phase_assets(phase_assets)
            if phase_characters:
                volume_context.character_registry.update(phase_characters)

        # Extract recurring patterns from chapter summaries
        volume_context.recurring_patterns = self._extract_recurring_patterns(
            volume_context.chapter_summaries
        )

        # Determine overall tone from chapter progression
        volume_context.overall_tone = self._determine_overall_tone(
            volume_context.chapter_summaries
        )

        # Extract established terminology from bible and chapters
        volume_context.established_terminology = self._extract_terminology(bible_data)
        phase_terms = self._extract_terminology_from_phase_assets(phase_assets)
        for jp_term, en_translation in phase_terms.items():
            volume_context.established_terminology.setdefault(jp_term, en_translation)

        # ECR: Load culturally_loaded_terms and author_signature_patterns from manifest
        ecr_data = self._load_ecr_data()
        volume_context.culturally_loaded_terms = ecr_data.get("culturally_loaded_terms", {})
        volume_context.author_signature_patterns = ecr_data.get("author_signature_patterns", {})

        # Cache the context for this chapter
        self._save_context_cache(current_chapter_num, volume_context)

        logger.info(
            f"Volume context aggregated: {len(volume_context.character_registry)} characters, "
            f"{len(volume_context.chapter_summaries)} chapters, "
            f"{len(volume_context.established_terminology)} terminology entries"
        )

        return volume_context

    def _load_phase156_context_assets(self) -> Dict[str, Any]:
        """
        Load Phase 1.56 context artifacts from .context/.

        Expected files (optional):
          - character_registry.json
          - timeline_map.json
          - cultural_glossary.json
          - TRANSLATION_BRIEF.md
        """
        assets: Dict[str, Any] = {}
        candidates = {
            "character_registry": "character_registry.json",
            "timeline_map": "timeline_map.json",
            "cultural_glossary": "cultural_glossary.json",
            "translation_brief": "TRANSLATION_BRIEF.md",
        }
        loaded = 0
        for key, filename in candidates.items():
            path = self.context_path / filename
            if not path.exists():
                continue
            try:
                if path.suffix.lower() == ".md":
                    assets[key] = path.read_text(encoding="utf-8")
                else:
                    with open(path, "r", encoding="utf-8") as f:
                        assets[key] = json.load(f)
                loaded += 1
            except Exception as e:
                logger.debug(f"[VOL-CTX] Failed loading Phase 1.56 asset {filename}: {e}")

        if loaded > 0:
            char_count = len(assets.get("character_registry", {}).get("characters", [])) if isinstance(assets.get("character_registry"), dict) else 0
            chapter_count = len(assets.get("timeline_map", {}).get("chapter_timeline", [])) if isinstance(assets.get("timeline_map"), dict) else 0
            term_count = len(assets.get("cultural_glossary", {}).get("terms", [])) if isinstance(assets.get("cultural_glossary"), dict) else 0
            logger.info(
                f"[VOL-CTX] Phase 1.56 assets loaded: files={loaded}, "
                f"characters={char_count}, timeline_chapters={chapter_count}, terms={term_count}"
            )
        return assets

    def _extract_characters_from_phase_assets(self, phase_assets: Dict[str, Any]) -> Dict[str, CharacterEntry]:
        """Extract character registry from Phase 1.56 character_registry.json."""
        registry = phase_assets.get("character_registry", {})
        if not isinstance(registry, dict):
            return {}
        raw_chars = registry.get("characters", [])
        if not isinstance(raw_chars, list):
            return {}

        characters: Dict[str, CharacterEntry] = {}
        for idx, row in enumerate(raw_chars):
            if not isinstance(row, dict):
                continue
            name_en = str(row.get("canonical_name", "")).strip()
            name_jp = str(row.get("japanese_name", "")).strip()
            if not name_en and not name_jp:
                continue
            key = name_en or name_jp or f"character_{idx+1}"
            relationships_raw = row.get("relationship_edges", [])
            relationships: Dict[str, str] = {}
            if isinstance(relationships_raw, list):
                for rel in relationships_raw[:12]:
                    if not isinstance(rel, dict):
                        continue
                    target = str(rel.get("target", "")).strip()
                    rtype = str(rel.get("type", "")).strip()
                    if target:
                        relationships[target] = rtype or "related"
            personality_raw = row.get("emotional_arc", [])
            if isinstance(personality_raw, str):
                personality = [personality_raw] if personality_raw else []
            elif isinstance(personality_raw, list):
                personality = [str(v).strip() for v in personality_raw if str(v).strip()]
            else:
                personality = []

            characters[key] = CharacterEntry(
                name_en=name_en or key,
                name_jp=name_jp,
                first_appearance_chapter=1,
                personality_traits=personality[:8],
                relationships=relationships,
                dialogue_style=str(row.get("voice_register", "")).strip(),
                honorifics_used=[],
            )
        return characters

    def _build_chapter_summary_from_phase_assets(
        self,
        chapter_num: int,
        phase_assets: Dict[str, Any],
    ) -> Optional[ChapterSummary]:
        """Build ChapterSummary from Phase 1.56 timeline_map.json."""
        timeline_map = phase_assets.get("timeline_map", {})
        if not isinstance(timeline_map, dict):
            return None
        timeline = timeline_map.get("chapter_timeline", [])
        if not isinstance(timeline, list) or not timeline:
            return None

        target_row: Optional[Dict[str, Any]] = None
        for row in timeline:
            if not isinstance(row, dict):
                continue
            seq_idx = row.get("sequence_index")
            if isinstance(seq_idx, int) and seq_idx == chapter_num:
                target_row = row
                break
            chapter_id = str(row.get("chapter_id", "")).strip()
            match = re.search(r"(\d+)$", chapter_id)
            if match and int(match.group(1)) == chapter_num:
                target_row = row
                break
        if target_row is None:
            return None

        chapter_id = str(target_row.get("chapter_id", f"chapter_{chapter_num:02d}")).strip()
        scenes = target_row.get("scenes", [])
        plot_points: List[str] = []
        if isinstance(scenes, list):
            for scene in scenes[:4]:
                if isinstance(scene, dict):
                    summary = str(scene.get("summary", "")).strip()
                    if summary:
                        plot_points.append(summary)

        continuity_constraints = target_row.get("continuity_constraints", [])
        tone = ""
        if isinstance(scenes, list) and scenes:
            first_scene = scenes[0] if isinstance(scenes[0], dict) else {}
            prose = first_scene.get("prose_rhythm", {}) if isinstance(first_scene, dict) else {}
            if isinstance(prose, dict):
                tone = str(prose.get("prose_temperature", "")).strip()

        return ChapterSummary(
            chapter_num=chapter_num,
            title=chapter_id,
            plot_points=plot_points,
            emotional_tone=tone,
            new_characters=[],
            name_rendering={},
            running_jokes=[],
            tone_shifts=[
                str(v).strip()
                for v in continuity_constraints[:6]
                if str(v).strip()
            ] if isinstance(continuity_constraints, list) else [],
        )

    def _extract_terminology_from_phase_assets(self, phase_assets: Dict[str, Any]) -> Dict[str, str]:
        """Extract JP→EN terminology map from Phase 1.56 cultural_glossary.json."""
        glossary = phase_assets.get("cultural_glossary", {})
        if not isinstance(glossary, dict):
            return {}
        terms = glossary.get("terms", [])
        if not isinstance(terms, list):
            return {}

        out: Dict[str, str] = {}
        for row in terms:
            if not isinstance(row, dict):
                continue
            jp = str(row.get("term_jp", "")).strip()
            en = str(row.get("preferred_en", "")).strip()
            if jp and en:
                out[jp] = en
        return out

    # Series-agnostic POV section header patterns.
    # Matches all common formats used across different light novel series:
    #   **─── The Childhood-Friend Gets Jealous ───**   (0824-style)
    #   *Chloe's POV*                                   (0965-style italic)
    #   (Kasumi's POV)                                  (0965-style paren)
    #   [Nayuta's POV]                                  (bracket style)
    #   **Nayuta's POV**                                (bold style)
    #   ─── Section Title ───                           (bare em-dash style)
    _POV_PATTERNS: List[re.Pattern] = [
        re.compile(r"^\*\*─+\s+(.+?)\s+─+\*\*\s*$"),          # **─── ... ───**
        re.compile(r"^─+\s+(.+?)\s+─+\s*$"),                   # ─── ... ───
        re.compile(r"^\*\*\*(.+?)\*\*\*\s*$"),                  # ***...***
        re.compile(r"^\*\*(.+?)\*\*\s*$"),                      # **...**
        re.compile(r"^\*(.+?)\*\s*$"),                          # *...*
        re.compile(r"^\((.+?)\)\s*$"),                          # (...)
        re.compile(r"^\[(.+?)\]\s*$"),                          # [...]
    ]
    # Minimum length for a header candidate to avoid matching inline emphasis
    _POV_HEADER_MIN_LEN: int = 4
    # Keywords that strongly suggest a POV/section header (series-agnostic)
    _POV_KEYWORDS: List[str] = [
        "pov", "perspective", "chapter", "arc", "side", "interlude",
        "epilogue", "prologue", "scene", "part",
        "'s", "\u2019s",  # possessive — "Chloe's POV"
    ]

    def _is_pov_header(self, text: str) -> bool:
        """
        Heuristic: is this extracted text likely a POV/section header?

        Accepts if it contains a POV keyword OR is short enough to be a title
        (≤ 80 chars) and does not look like a sentence (no period mid-text).
        """
        t = text.strip()
        if len(t) < self._POV_HEADER_MIN_LEN:
            return False
        lower = t.lower()
        if any(kw in lower for kw in self._POV_KEYWORDS):
            return True
        # Short title-like text without sentence punctuation mid-string
        if len(t) <= 80 and not re.search(r"[.!?][^.!?]", t):
            return True
        return False

    def extract_arc_closings(
        self,
        en_chapter_path: Path,
        chapter_num: int,
        lines_per_closing: int = 20,
    ) -> List[ArcClosing]:
        """
        Parse an EN chapter file and extract the closing prose of each POV arc.

        Detection strategy (series-agnostic):
        1. Scan for section headers matching any of _POV_PATTERNS
        2. Apply _is_pov_header() heuristic to filter false positives
        3. For each section, extract last N content lines as closing prose
        4. Use header text directly as character_archetype (no hardcoded mapping)

        Args:
            en_chapter_path: Path to the translated EN chapter markdown file.
            chapter_num: Chapter number (for logging).
            lines_per_closing: Number of lines to extract per arc closing.

        Returns:
            List of ArcClosing objects, one per detected POV arc.
        """
        if not en_chapter_path.exists():
            logger.debug(f"[ARC-CLOSE] Chapter file not found: {en_chapter_path}")
            return []

        try:
            text = en_chapter_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"[ARC-CLOSE] Failed to read {en_chapter_path}: {e}")
            return []

        # Split into lines, preserving order
        all_lines = text.splitlines()

        def _match_header(line: str) -> Optional[str]:
            """Return extracted header text if line matches any POV pattern."""
            stripped = line.strip()
            for pat in self._POV_PATTERNS:
                m = pat.match(stripped)
                if m:
                    candidate = m.group(1).strip()
                    if self._is_pov_header(candidate):
                        return candidate
            return None

        # Find all section header positions using series-agnostic matching
        sections: List[tuple] = []  # (line_index, header_text)
        for idx, line in enumerate(all_lines):
            header_text = _match_header(line)
            if header_text:
                sections.append((idx, header_text))

        if not sections:
            logger.debug(f"[ARC-CLOSE] No POV arc headers found in chapter {chapter_num}")
            return []

        arc_closings: List[ArcClosing] = []

        for i, (header_idx, header_text) in enumerate(sections):
            # Determine end of this section (start of next section or end of file)
            if i + 1 < len(sections):
                section_end = sections[i + 1][0]
            else:
                section_end = len(all_lines)

            # Extract content lines for this section (skip header itself)
            section_lines = all_lines[header_idx + 1:section_end]

            # Filter: remove blank lines and illustration tags
            content_lines = [
                ln for ln in section_lines
                if ln.strip()
                and not ln.strip().startswith("![")
                and not ln.strip().startswith("<!--")
                and not ln.strip().startswith("{{")
            ]

            if not content_lines:
                continue

            # Take last N lines as the closing prose
            closing_lines = content_lines[-lines_per_closing:]
            closing_prose = "\n".join(closing_lines)

            # Use header text directly as character archetype (series-agnostic)
            # No hardcoded mapping — the header IS the identifier
            character_archetype = header_text

            arc_closings.append(ArcClosing(
                character_archetype=character_archetype,
                section_header=header_text,
                closing_prose=closing_prose,
                closing_line_count=len(closing_lines),
                emotional_register="",  # Could be enriched by future analysis
            ))

        logger.info(
            f"[ARC-CLOSE] Chapter {chapter_num}: extracted {len(arc_closings)} arc closings "
            f"({', '.join(a.character_archetype for a in arc_closings)})"
        )
        return arc_closings

    def _get_volume_title(self) -> str:
        """Extract volume title from work directory name."""
        # Format: "Title_20260213_1234"
        dir_name = self.work_dir.name
        # Remove date and ID suffix
        title = dir_name.split('_')[0] if '_' in dir_name else dir_name
        return title

    def _load_ecr_data(self) -> Dict[str, Any]:
        """Load ECR fields (culturally_loaded_terms + author_signature_patterns) from manifest.

        Bridge rule: if culturally_loaded_terms is empty but cultural_terms entries carry a
        retention_policy key, synthesize culturally_loaded_terms from them.  This handles
        volumes processed before ECR was fully integrated, where Gemini wrote the ECR data
        into the pre-existing cultural_terms container instead of the new key.
        """
        manifest_path = self.work_dir / 'manifest.json'
        if not manifest_path.exists():
            return {}
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
            meta = manifest.get('metadata_en', {})
            clt = meta.get('culturally_loaded_terms', {})
            if not isinstance(clt, dict):
                clt = {}

            # Bridge: synthesize from cultural_terms when CLT is empty
            if not clt:
                raw_ct = meta.get('cultural_terms', {})
                if isinstance(raw_ct, dict):
                    for _key, entry in raw_ct.items():
                        if not isinstance(entry, dict):
                            continue
                        policy = entry.get('retention_policy', '')
                        if not policy:
                            continue
                        jp_key = entry.get('canonical_jp') or _key
                        clt[jp_key] = {
                            'retention_policy': policy,
                            'display': entry.get('canonical_jp') or _key,
                            'romaji': entry.get('romaji', ''),
                            'definition': entry.get('usage_context', ''),
                            'category': entry.get('category', ''),
                            'notes': entry.get('notes', ''),
                        }
                    if clt:
                        logger.info(
                            f"[ECR] Bridged {len(clt)} terms from cultural_terms → "
                            "culturally_loaded_terms (Phase 1.5 key mismatch)"
                        )

            return {
                'culturally_loaded_terms': clt,
                'author_signature_patterns': meta.get('author_signature_patterns', {}),
            }
        except Exception as e:
            logger.debug(f"[VOL-CTX] Could not load ECR data from manifest: {e}")
            return {}

    def _load_translator_notes(self) -> List[Dict[str, Any]]:
        """
        Load translator_notes array from manifest.json.

        These are volume-specific directives (POV mirror rules, anchor lines,
        rendering decisions) that must be injected into every chapter's context.
        Returns empty list if manifest.json has no translator_notes field.
        """
        manifest_path = self.work_dir / 'manifest.json'
        if not manifest_path.exists():
            return []
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
            notes = manifest.get('translator_notes', [])
            if not isinstance(notes, list):
                return []
            valid = [n for n in notes if isinstance(n, dict)]
            if valid:
                logger.info(f"[VOL-CTX] Loaded {len(valid)} translator_notes from manifest.json")
            return valid
        except Exception as e:
            logger.warning(f"[VOL-CTX] Failed to load translator_notes from manifest: {e}")
            return []

    def _load_bible(self) -> Optional[Dict[str, Any]]:
        """Load bible.json if exists, falling back to manifest.json character_profiles."""
        if self.bible_path.exists():
            try:
                with open(self.bible_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load bible: {e}")

        # Fallback: synthesize bible-compatible structure from manifest.json
        manifest_path = self.work_dir / 'manifest.json'
        manifest_exists = manifest_path.exists()
        synthesis_failed = False
        if manifest_path.exists():
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)
                meta = manifest.get('metadata_en', {})
                if not isinstance(meta, dict):
                    meta = {}
                profiles = meta.get('character_profiles', {})
                if not isinstance(profiles, dict):
                    profiles = {}
                if profiles:
                    logger.info(
                        f"[VOL-CTX] Bible not found — synthesizing character registry "
                        f"from manifest.json ({len(profiles)} profiles)"
                    )
                    # Convert character_profiles to bible-compatible format
                    bible_chars = {}
                    skipped_profiles = 0
                    for char_name, p in profiles.items():
                        if not isinstance(p, dict):
                            skipped_profiles += 1
                            continue

                        ruby_base = str(
                            p.get('ruby_base')
                            or p.get('character_name_jp')
                            or ''
                        ).strip()
                        nickname = str(p.get('nickname', '')).strip()
                        full_name = str(
                            p.get('full_name')
                            or p.get('canonical_en')
                            or p.get('character_name_en')
                            or p.get('name_en')
                            or p.get('english_name')
                            or char_name
                        ).strip()

                        personality_raw = p.get('personality_traits', [])
                        if isinstance(personality_raw, str):
                            personality = [personality_raw] if personality_raw.strip() else []
                        elif isinstance(personality_raw, list):
                            personality = [str(v).strip() for v in personality_raw if str(v).strip()]
                        else:
                            personality = []

                        dialogue = str(
                            p.get('speech_pattern')
                            or p.get('dialogue_style')
                            or ''
                        ).strip()

                        keigo = p.get('keigo_switch', {})
                        honorifics: List[str] = []
                        if isinstance(keigo, dict):
                            speaking_to = keigo.get('speaking_to', {})
                            if isinstance(speaking_to, dict):
                                honorifics = [str(k).strip() for k in speaking_to.keys() if str(k).strip()]
                            elif isinstance(speaking_to, list):
                                honorifics = [str(v).strip() for v in speaking_to if str(v).strip()]

                        relationships = {
                            'role': str(p.get('relationship_to_protagonist', '')).strip(),
                        }
                        if p.get('relationship_to_others'):
                            relationships['others'] = str(p['relationship_to_others']).strip()
                        en_name = full_name
                        if nickname and nickname.lower() not in full_name.lower():
                            en_name = f"{full_name} (nickname: {nickname})"
                        bible_chars[char_name] = {
                            'name_en': en_name,
                            'name_jp': ruby_base,
                            'first_appearance': 1,
                            'personality': personality,
                            'dialogue_style': dialogue,
                            'honorifics': honorifics,
                            'relationships': relationships,
                        }
                    if skipped_profiles:
                        logger.warning(
                            f"[VOL-CTX] Skipped {skipped_profiles} malformed character_profiles entries "
                            f"while synthesizing registry from manifest.json"
                        )
                    return {'characters': bible_chars}
            except Exception as e:
                synthesis_failed = True
                logger.warning(f"[VOL-CTX] Failed to synthesize from manifest: {e}")

        if not manifest_exists:
            logger.warning(f"[VOL-CTX] No bible or manifest found at {self.work_dir}")
        elif synthesis_failed:
            logger.warning(
                f"[VOL-CTX] Bible not found and manifest synthesis failed at {manifest_path}"
            )
        else:
            logger.warning(
                f"[VOL-CTX] Bible not found and manifest has no usable character_profiles at {manifest_path}"
            )
        return None

    def _extract_characters_from_bible(self, bible_data: Dict[str, Any]) -> Dict[str, CharacterEntry]:
        """Extract character registry from bible-compatible dict."""
        characters = {}

        bible_characters = bible_data.get('characters', {})

        for char_name, char_data in bible_characters.items():
            name_en = char_data.get('name_en', char_name)
            personality_raw = char_data.get('personality', [])
            personality = (
                [personality_raw] if isinstance(personality_raw, str) and personality_raw
                else personality_raw if isinstance(personality_raw, list)
                else []
            )
            relationships_raw = char_data.get('relationships', {})
            relationships = (
                relationships_raw if isinstance(relationships_raw, dict)
                else {}
            )
            characters[char_name] = CharacterEntry(
                name_en=name_en,
                name_jp=char_data.get('name_jp', ''),
                first_appearance_chapter=char_data.get('first_appearance', 1),
                personality_traits=personality,
                dialogue_style=char_data.get('dialogue_style', ''),
                honorifics_used=char_data.get('honorifics', []),
                relationships=relationships,
            )

        return characters

    def _process_chapter(
        self,
        chapter_num: int,
        source_dir: Path,
        en_dir: Path
    ) -> Optional[ChapterSummary]:
        """
        Process a single chapter to extract summary information.

        Reads from .context/{chapter}_SUMMARY.json if exists, otherwise creates lightweight summary.
        """
        # Check for existing summary in .context
        summary_file = self.context_path / f"CHAPTER_{chapter_num:02d}_SUMMARY.json"

        if summary_file.exists():
            try:
                with open(summary_file, 'r', encoding='utf-8') as f:
                    summary_data = json.load(f)
                # Tolerate summaries written before name_rendering field was added
                summary_data.setdefault('name_rendering', {})
                # Keep only fields that ChapterSummary accepts
                valid_fields = {f.name for f in ChapterSummary.__dataclass_fields__.values()}
                filtered = {k: v for k, v in summary_data.items() if k in valid_fields}
                return ChapterSummary(**filtered)
            except Exception as e:
                logger.warning(f"Failed to load summary for Chapter {chapter_num}: {e}")

        # If no summary exists, create basic summary from chapter file
        chapter_file = en_dir / f"CHAPTER_{chapter_num:02d}_EN.md"

        def _extract_heading(path: Path) -> str:
            """Extract first markdown heading as chapter title (best effort)."""
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        text = line.strip()
                        if text.startswith("#"):
                            return text.lstrip("#").strip() or f"Chapter {chapter_num}"
            except Exception:
                pass
            return f"Chapter {chapter_num}"

        if not chapter_file.exists():
            # Batch mode often builds prompts before EN chapters are finalized.
            # Fall back to JP source chapter presence to avoid noisy warnings.
            source_chapter_file = source_dir / f"CHAPTER_{chapter_num:02d}.md"
            if source_chapter_file.exists():
                logger.debug(
                    f"[VOL-CTX] EN chapter not available yet for Chapter {chapter_num}; "
                    "using JP source placeholder summary."
                )
                return ChapterSummary(
                    chapter_num=chapter_num,
                    title=_extract_heading(source_chapter_file),
                    plot_points=[],
                    emotional_tone="",
                    new_characters=[],
                    name_rendering={},
                    running_jokes=[],
                    tone_shifts=[],
                )

            logger.debug(
                f"[VOL-CTX] Chapter source missing for Chapter {chapter_num}: "
                f"EN={chapter_file} JP={source_chapter_file}"
            )
            return None

        # Create lightweight summary (title only for now)
        # Full summarization would be done by a separate Gemini call in production
        return ChapterSummary(
            chapter_num=chapter_num,
            title=_extract_heading(chapter_file),
            plot_points=[],  # To be filled by summarization agent
            emotional_tone="",  # To be filled by summarization agent
            new_characters=[],  # To be filled by character detection
            name_rendering={},
            running_jokes=[],
            tone_shifts=[]
        )

    def _extract_recurring_patterns(self, chapter_summaries: List[ChapterSummary]) -> Dict[str, Any]:
        """Extract recurring patterns from chapter summaries."""
        patterns = {}

        # Collect all running jokes
        all_jokes = []
        for summary in chapter_summaries:
            all_jokes.extend(summary.running_jokes)

        if all_jokes:
            # Count frequency of each joke
            joke_counts = defaultdict(int)
            for joke in all_jokes:
                joke_counts[joke] += 1

            # Keep jokes that appear in multiple chapters
            recurring_jokes = [joke for joke, count in joke_counts.items() if count >= 2]
            if recurring_jokes:
                patterns['running_jokes'] = recurring_jokes

        # Detect tone progression
        tones = [s.emotional_tone for s in chapter_summaries if s.emotional_tone]
        if len(tones) >= 3:
            patterns['tone_progression'] = " → ".join(tones[-3:])  # Last 3 chapters

        return patterns

    def _determine_overall_tone(self, chapter_summaries: List[ChapterSummary]) -> str:
        """Determine overall volume tone from chapter progression."""
        if not chapter_summaries:
            return "Unknown"

        # Collect all emotional tones
        tones = [s.emotional_tone for s in chapter_summaries if s.emotional_tone]

        if not tones:
            return "Neutral"

        # Simple majority vote (in production, use Gemini to synthesize)
        from collections import Counter
        tone_counts = Counter(tones)
        most_common_tone = tone_counts.most_common(1)[0][0]

        return most_common_tone

    def _extract_terminology(self, bible_data: Optional[Dict[str, Any]]) -> Dict[str, str]:
        """Extract established terminology from bible or manifest."""
        terminology = {}

        if bible_data:
            # Standard bible structure: {"terminology": {"JP_term": "EN_translation"}}
            for jp_term, en_translation in bible_data.get('terminology', {}).items():
                terminology[jp_term] = str(en_translation)

        # Also pull from manifest cultural_terms if available
        manifest_path = self.work_dir / 'manifest.json'
        if manifest_path.exists():
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)
                meta = manifest.get('metadata_en', {})
                cultural = meta.get('cultural_terms', {})
                if isinstance(cultural, dict):
                    for jp_term, data in cultural.items():
                        if jp_term in terminology:
                            continue  # bible takes precedence
                        if isinstance(data, str):
                            terminology[jp_term] = data
                        elif isinstance(data, dict):
                            en = data.get('translation') or data.get('en') or data.get('meaning', '')
                            if en:
                                terminology[jp_term] = str(en)
            except Exception as e:
                logger.debug(f"[VOL-CTX] Could not read manifest cultural_terms: {e}")

        return terminology

    def _save_context_cache(self, chapter_num: int, context: VolumeContext):
        """Save aggregated context to cache for inspection/debugging."""
        cache_file = self.context_path / f"CHAPTER_{chapter_num:02d}_VOLUME_CONTEXT.json"

        try:
            # Convert to dict for JSON serialization
            context_dict = {
                'volume_title': context.volume_title,
                'total_chapters_processed': context.total_chapters_processed,
                'character_registry': {
                    name: {
                        'name_en': char.name_en,
                        'name_jp': char.name_jp,
                        'first_appearance_chapter': char.first_appearance_chapter,
                        'personality_traits': char.personality_traits,
                        'relationships': char.relationships,
                        'dialogue_style': char.dialogue_style,
                        'honorifics_used': char.honorifics_used
                    }
                    for name, char in context.character_registry.items()
                },
                'chapter_summaries': [
                    {
                        'chapter_num': s.chapter_num,
                        'title': s.title,
                        'plot_points': s.plot_points,
                        'emotional_tone': s.emotional_tone,
                        'new_characters': s.new_characters,
                        'name_rendering': s.name_rendering,
                        'running_jokes': s.running_jokes,
                        'tone_shifts': s.tone_shifts
                    }
                    for s in context.chapter_summaries
                ],
                'established_terminology': context.established_terminology,
                'recurring_patterns': context.recurring_patterns,
                'overall_tone': context.overall_tone
            }

            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(context_dict, f, indent=2, ensure_ascii=False)

            logger.info(f"Context cache saved: {cache_file}")
        except Exception as e:
            logger.error(f"Failed to save context cache: {e}")

    def load_cached_context(self, chapter_num: int) -> Optional[VolumeContext]:
        """Load previously cached context for a chapter."""
        cache_file = self.context_path / f"CHAPTER_{chapter_num:02d}_VOLUME_CONTEXT.json"

        if not cache_file.exists():
            return None

        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                context_dict = json.load(f)

            # Reconstruct VolumeContext from dict
            context = VolumeContext(
                volume_title=context_dict['volume_title'],
                total_chapters_processed=context_dict['total_chapters_processed'],
                overall_tone=context_dict.get('overall_tone', '')
            )

            # Reconstruct character registry
            for name, char_data in context_dict.get('character_registry', {}).items():
                context.character_registry[name] = CharacterEntry(**char_data)

            # Reconstruct chapter summaries
            for summary_data in context_dict.get('chapter_summaries', []):
                context.chapter_summaries.append(ChapterSummary(**summary_data))

            context.established_terminology = context_dict.get('established_terminology', {})
            context.recurring_patterns = context_dict.get('recurring_patterns', {})

            logger.info(f"Loaded cached context for Chapter {chapter_num}")
            return context
        except Exception as e:
            logger.error(f"Failed to load cached context: {e}")
            return None

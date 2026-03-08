"""
Master Prompt and RAG Module Loader.
Handles loading of system instructions and injecting RAG knowledge modules.
Supports Three-Tier RAG system with context-aware selective injection.
Supports multi-language configuration (EN, VN, etc.)
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Any, Union
from pipeline.translator.config import (
    get_master_prompt_path, get_modules_directory, get_genre_prompt_path
)
from pipeline.config import get_target_language, get_language_config, PIPELINE_ROOT

logger = logging.getLogger(__name__)


class PromptLoader:
    def __init__(self, target_language: str = None, prompts_dir: Path = None, modules_dir: Path = None): # type: ignore
        """
        Initialize PromptLoader.

        Args:
            target_language: Target language code (e.g., 'en', 'vn').
                            If None, uses current target language from config.
            prompts_dir: Override path to prompts directory.
            modules_dir: Override path to modules directory.
        """
        self.target_language = target_language if target_language else get_target_language()
        self.lang_config = get_language_config(self.target_language)
        self._genre = None  # Genre for JIT literacy_techniques injection

        self.prompts_path = prompts_dir if prompts_dir else get_master_prompt_path(self.target_language)
        self.modules_dir = modules_dir if modules_dir else get_modules_directory(self.target_language)
        
        # Three-Tier RAG paths
        self.reference_dir = None
        self.reference_index_path = None
        # DEPRECATED: kanji_difficult_path - replaced by vietnamese_grammar_rag.json for VN
        # self.kanji_difficult_path = None
        self.cjk_prevention_path = None  # Initialize for all languages
        self.anti_ai_ism_path = None  # Anti-AI-ism pattern library (v3.5)
        self.english_grammar_rag_path = None  # English Grammar RAG (Tier 1) - EN only
        self.english_grammar_validation_t1_path = None  # EN Grammar Validation T1 (Tier 1) - EN only
        self.literacy_techniques_path = None  # Literary techniques (Tier 1) - language-agnostic
        self.formatting_standards_path = None  # Formatting standards + romanization (Tier 1)

        # Setup Three-Tier RAG paths for VN
        self.vietnamese_grammar_rag_path = None  # Vietnamese Grammar RAG (Tier 1) - VN only
        if self.target_language == 'vn':
            reference_dir_config = self.lang_config.get('reference_dir')
            if reference_dir_config:
                self.reference_dir = PIPELINE_ROOT / reference_dir_config
            
            # DEPRECATED: kanji_difficult.json - replaced by vietnamese_grammar_rag.json
            # reference_index.json is in VN/ root
            # cjk_prevention_schema_vn.json is in prompts/modules/rag/
            vn_root = PIPELINE_ROOT / 'VN'
            prompts_root = PIPELINE_ROOT / 'prompts' / 'modules' / 'rag'
            # self.kanji_difficult_path = vn_root / 'kanji_difficult.json'  # DEPRECATED
            self.cjk_prevention_path = prompts_root / 'cjk_prevention_schema_vn.json'
            self.reference_index_path = vn_root / 'reference_index.json'
            # Vietnamese Grammar RAG (Tier 1) - Anti-AI-ism + particle system for JP→VN
            self.vietnamese_grammar_rag_path = vn_root / 'vietnamese_grammar_rag.json'
        
        # Setup CJK prevention for EN (English also needs CJK prevention)
        elif self.target_language == 'en':
            prompts_root = PIPELINE_ROOT / 'prompts' / 'modules' / 'rag'
            self.cjk_prevention_path = prompts_root / 'cjk_prevention_schema_en.json'
            # Anti-AI-ism pattern library (v3.5) - EN only for now
            config_dir = PIPELINE_ROOT / 'config'
            self.anti_ai_ism_path = config_dir / 'anti_ai_ism_patterns.json'
            # English Grammar RAG (Tier 1) - Natural idiom patterns for JP→EN
            self.english_grammar_rag_path = config_dir / 'english_grammar_rag.json'
            # Negative Signals (Tier 1 EN) - ICL-backed quality enforcement
            # Note: This replaces the deprecated kanji_difficult.json for EN
            self.negative_signals_path = config_dir / 'negative_signals.json'
            # English Grammar Validation T1 (Tier 1) - rhythm/literal/repetition guardrails
            self.english_grammar_validation_t1_path = config_dir / 'english_grammar_validation_t1.json'

        # Literacy Techniques (Tier 1 - language-agnostic, applies to both EN and VN)
        config_dir = PIPELINE_ROOT / 'config'
        self.literacy_techniques_path = config_dir / 'literacy_techniques.json'
        self.literacy_techniques_compressed_path = config_dir / 'literacy_techniques_compressed.json'  # 1 example/mood, for large chapters
        self.formatting_standards_path = config_dir / 'formatting_standards.json'

        self._master_prompt_cache = None
        self._rag_modules_cache = {}
        self._reference_index = None  # Three-Tier RAG metadata
        # self._kanji_difficult = None  # DEPRECATED: Tier 1 kanji data
        self._cjk_prevention = None  # CJK prevention schema with substitution patterns
        self._anti_ai_ism = None  # Anti-AI-ism pattern library (v3.5)
        self._english_grammar_rag = None  # English Grammar RAG (Tier 1) - natural idioms
        self._negative_signals = None  # Negative Signals (Tier 1 EN) - ICL-backed quality enforcement
        self._english_grammar_validation_t1 = None  # EN Grammar Validation T1 (Tier 1)
        self._vietnamese_grammar_rag = None  # Vietnamese Grammar RAG (Tier 1) - anti-AI-ism + particle system
        self._literacy_techniques = None  # Literary techniques (Tier 1) - language-agnostic narrative techniques
        self._literacy_techniques_compressed = None  # Compressed literacy techniques (1 example/mood) for large-chapter routing
        self._formatting_standards = None  # Formatting standards + romanization (Tier 1)
        self._continuity_pack = None  # Continuity pack from previous volume
        self._character_names = None  # Character names from manifest
        self._glossary = None  # Glossary terms from manifest
        self._semantic_metadata = None  # Full semantic metadata (Enhanced v2.1: dialogue patterns, scenes, emotional states)
        self._style_guide = None  # Style guide for Vietnamese translation (experimental)
        self._bible_prompt = None  # Series Bible categorized prompt block
        self._bible_world_directive = None  # World setting one-liner for top-of-prompt
        self._bible_glossary_keys = set()  # JP keys covered by bible (for glossary dedup)
        self._book_type = None  # Content type: 'fiction' (default), 'memoir', 'biography', 'non_fiction'
        self._music_industry_vocab = None  # Music-industry vocabulary supplement (memoir mode only)
        self._title_motif_catchphrase_directive = ""  # Title Philosopher motif-aligned catchphrase rule

        # Koji Fox voice directives (Phase 1-2 expansion)
        self._voice_directive = ""  # CHARACTER VOICE DIRECTIVE from VoiceRAGManager
        self._arc_directive = ""    # CHARACTER ARC STATES from ArcTracker

        # POV character fingerprint override (Gap 8.2 — batch-safe injection)
        # Set when a chapter's POV shifts to a non-protagonist character with a fingerprint.
        # Injected as a high-priority block so batch+thinking mode sees the correct register
        # without relying on tool_use (which batch mode does not support).
        self._pov_character_name: str = ""
        self._pov_fingerprint: dict = {}  # character_voice_fingerprints entry

        # Multi-POV intra-chapter hot-switch segments (Gap 8.2 extension)
        # Set when a chapter has multiple POV segments each belonging to a different
        # fingerprinted character. When non-empty, takes precedence over the single-POV
        # fields above. Each entry is a dict with keys:
        #   character: str          — canonical EN name
        #   fingerprint: dict       — character_voice_fingerprints entry
        #   start_line: int | None  — source JP line hint (optional)
        #   end_line: int | None    — source JP line hint (optional)
        #   description: str        — human-readable segment description (optional)
        self._pov_segments: list = []
        self._secondary_fingerprints: list = []
        self._inline_afterword_override: dict = {}

        # ECR — volume-level translation directives (Enhanced Cultural Retention + Author Signature)
        # Set once at volume init from metadata_en fields. Persists across all chapter builds.
        self._ecr_clt: dict = {}         # culturally_loaded_terms
        self._ecr_asp: dict = {}         # author_signature_patterns
        self._ecr_cvf_list: list = []    # character_voice_fingerprints (all chars)
        self._ecr_sig_phrases: list = [] # signature_phrases

        # Style guide paths (experimental - Vietnamese only for now)
        self.style_guides_dir = PIPELINE_ROOT / 'style_guides'
        # Normalize Vietnamese: vn→vi for file lookups (files use 'vi' suffix)
        style_lang = 'vi' if self.target_language in ['vi', 'vn'] else self.target_language
        self.style_lang = style_lang  # Store for reuse in load methods
        self.base_style_path = self.style_guides_dir / f'base_style_{style_lang}.json'
        self.genres_dir = self.style_guides_dir / 'genres'
        self.publishers_dir = self.style_guides_dir / 'publishers'

        logger.info(f"PromptLoader initialized for language: {self.target_language.upper()} ({self.lang_config.get('language_name', 'Unknown')})")
        logger.info(f"  Master Prompt: {self.prompts_path}")
        logger.info(f"  Modules Dir: {self.modules_dir}")
        if self.reference_dir:
            logger.info(f"  Reference Dir: {self.reference_dir}")
        # DEPRECATED: kanji_difficult_path logging
        # if self.kanji_difficult_path and self.kanji_difficult_path.exists():
        #     logger.info(f"  Kanji Difficult: {self.kanji_difficult_path}")
        
        # Check for style guide system (experimental)
        if self.target_language in ['vi', 'vn'] and self.style_guides_dir.exists():
            logger.info(f"  Style Guides Dir: {self.style_guides_dir} [EXPERIMENTAL]")
    
    def set_continuity_pack(self, continuity_text: str):
        """Set continuity pack for injection into prompts."""
        self._continuity_pack = continuity_text
        logger.info(f"Continuity pack set ({len(continuity_text)} characters)")
    
    def set_character_names(self, character_names: Dict[str, str]):
        """Set character names for injection into cached system instruction."""
        self._character_names = character_names
        logger.info(f"Character names set ({len(character_names)} entries)")
    
    def set_glossary(self, glossary: Dict[str, str]):
        """Set glossary for injection into cached system instruction."""
        self._glossary = glossary
        logger.info(f"Glossary set ({len(glossary)} entries)")
    
    def set_semantic_metadata(self, semantic_metadata: Dict[str, Any]):
        """Set full semantic metadata for injection into system instruction (Enhanced v2.1)."""
        if not isinstance(semantic_metadata, dict):
            logger.warning(
                f"Semantic metadata has invalid type {type(semantic_metadata).__name__}; using empty dict"
            )
            semantic_metadata = {}
        self._semantic_metadata = semantic_metadata
        char_count = len(semantic_metadata.get('characters', []))
        pattern_count = len(semantic_metadata.get('dialogue_patterns', {}))
        scene_count = len(semantic_metadata.get('scene_contexts', {}))
        logger.info(f"Semantic metadata set: {char_count} characters, {pattern_count} dialogue patterns, {scene_count} scenes")

    def set_voice_directive(self, voice_directive: str, arc_directive: str = "") -> None:
        """
        Set Koji Fox voice directives for injection into the thinking block context.

        Args:
            voice_directive: Formatted CHARACTER VOICE DIRECTIVE block from VoiceRAGManager
            arc_directive: Formatted CHARACTER ARC STATES block from ArcTracker
        """
        self._voice_directive = voice_directive or ""
        self._arc_directive = arc_directive or ""
        if voice_directive:
            logger.info(f"Voice directive set ({len(voice_directive)} chars)")
        if arc_directive:
            logger.info(f"Arc directive set ({len(arc_directive)} chars)")

    def set_title_motif_catchphrase_directive(self, directive: str) -> None:
        """Set title-motif catchphrase directive for chapter prompt injection."""
        self._title_motif_catchphrase_directive = (directive or "").strip()
        if self._title_motif_catchphrase_directive:
            logger.info(
                "[TITLE MOTIF] Catchphrase directive set (%s chars)",
                len(self._title_motif_catchphrase_directive),
            )

    def set_ecr_directives(
        self,
        culturally_loaded_terms: dict,
        author_signature_patterns: dict,
        character_voice_fingerprints: list,
        signature_phrases: list,
    ) -> None:
        """Store ECR volume-level directives for injection into the system instruction.

        Called once at volume initialisation. The four fields originate from
        metadata_en and are appended as hard-rule directive blocks in
        build_system_instruction() so they apply to every chapter.

        Args:
            culturally_loaded_terms:      ECR term → {retention_policy, display, …} dict.
            author_signature_patterns:    {detected_patterns, literary_references} dict.
            character_voice_fingerprints: List of per-character fingerprint dicts.
            signature_phrases:            Flat list of {character_en, phrase_jp, phrase_en, …}.
        """
        self._ecr_clt = culturally_loaded_terms if isinstance(culturally_loaded_terms, dict) else {}
        self._ecr_asp = author_signature_patterns if isinstance(author_signature_patterns, dict) else {}
        self._ecr_cvf_list = character_voice_fingerprints if isinstance(character_voice_fingerprints, list) else []
        self._ecr_sig_phrases = signature_phrases if isinstance(signature_phrases, list) else []
        tot = (
            len(self._ecr_clt)
            + bool(self._ecr_asp)
            + len(self._ecr_cvf_list)
            + len(self._ecr_sig_phrases)
        )
        logger.info(
            f"[ECR] Directives set: {len(self._ecr_clt)} CLT terms, "
            f"{len(self._ecr_cvf_list)} CVF fingerprints, "
            f"{len(self._ecr_sig_phrases)} signature phrases, "
            f"ASP={'yes' if self._ecr_asp else 'no'} ({tot} total entries)"
        )

    def set_pov_character_override(self, character_name: str, fingerprint: dict) -> None:
        """
        Set a POV character fingerprint override for a chapter narrator.

        Called by the translator agent when a chapter's scene plan identifies the
        active POV character and that character has a voice fingerprint. The
        fingerprint is injected as a high-priority block in
        build_system_instruction() so batch+thinking mode receives the correct
        register, contraction ceiling, and verbal-tic constraints without relying
        on declare_translation_parameters.

        Args:
            character_name: Canonical EN name of the POV character (e.g. "Sudou Ayami")
            fingerprint: character_voice_fingerprints entry dict
        """
        self._pov_segments = []
        self._pov_character_name = character_name or ""
        self._pov_fingerprint = fingerprint or {}
        if character_name and fingerprint:
            archetype = fingerprint.get("archetype", "unknown")
            contraction_rate = fingerprint.get("contraction_rate", "?")
            logger.info(
                f"[POV OVERRIDE] Set POV Character: {character_name} "
                f"(archetype={archetype}, contraction_rate={contraction_rate})"
            )

    def set_pov_segments(self, segments: list) -> None:
        """
        Set multi-POV intra-chapter hot-switch segments (Gap 8.2 extension).

        Called by the translator agent when a chapter contains multiple first-person
        POV sections belonging to different fingerprinted characters (e.g. alternating
        Hikari / Ayami perspectives within a single chapter).  When set, the multi-
        segment directive replaces the simpler single-POV override block so the model
        receives per-segment voice constraints and explicit transition cues.

        Batch+thinking mode compatible — no tool_use required.

        Args:
            segments: List of segment dicts, each with:
                - character (str): canonical EN name
                - fingerprint (dict): character_voice_fingerprints entry
                - start_line (int | None): source JP line hint
                - end_line (int | None): source JP line hint
                - description (str | None): human-readable segment label
        """
        self._pov_character_name = ""
        self._pov_fingerprint = {}
        self._pov_segments = [s for s in (segments or []) if s.get("character") and s.get("fingerprint")]
        if self._pov_segments:
            names = [s["character"] for s in self._pov_segments]
            logger.info(
                f"[POV SEGMENTS] Set {len(self._pov_segments)}-segment multi-POV override: "
                f"{' → '.join(names)}"
            )

    def add_secondary_fingerprint(self, character_name: str, fingerprint: dict) -> None:
        """Inject a compact voice anchor for an important non-POV speaker."""
        if not character_name or not fingerprint:
            return

        canonical_name = fingerprint.get("canonical_name_en", character_name) or character_name
        existing = {
            str(item.get("character", "")).strip().lower()
            for item in self._secondary_fingerprints
            if isinstance(item, dict)
        }
        if canonical_name.strip().lower() in existing:
            return

        self._secondary_fingerprints.append(
            {
                "character": canonical_name,
                "fingerprint": fingerprint,
            }
        )
        logger.info(f"[SECONDARY FP] Added secondary voice anchor: {canonical_name}")

    def set_inline_afterword_override(self, marker_info: Optional[dict]) -> None:
        """Set chapter-scoped inline afterword override metadata."""
        if isinstance(marker_info, dict) and marker_info:
            self._inline_afterword_override = marker_info
            logger.info(
                "[INLINE AFTERWORD] Set inline override (%s)",
                marker_info.get("source", "unknown"),
            )
        else:
            self._inline_afterword_override = {}

    def clear_scene_voice_overrides(self) -> None:
        """Clear chapter-scoped voice injections before processing the next chapter."""
        self._pov_character_name = ""
        self._pov_fingerprint = {}
        self._pov_segments = []
        self._secondary_fingerprints = []
        self._inline_afterword_override = {}

    def set_series_bible_prompt(
        self,
        bible_prompt: str,
        world_directive: str = None, # type: ignore
        bible_glossary_keys: set = None, # type: ignore
    ):
        """Set series bible prompt block for injection into system instruction.

        Args:
            bible_prompt: Full categorized bible block (CHARACTERS, GEOGRAPHY, etc.)
            world_directive: One-line world setting directive for top-of-prompt injection
            bible_glossary_keys: Set of JP keys covered by bible (deduplicates glossary)
        """
        self._bible_prompt = bible_prompt
        self._bible_world_directive = world_directive or None
        self._bible_glossary_keys = bible_glossary_keys or set()
        parts = [f"Bible prompt set ({len(bible_prompt)} chars)"]
        if world_directive:
            parts.append(f"world directive ({len(world_directive)} chars)")
        if bible_glossary_keys:
            parts.append(f"{len(bible_glossary_keys)} dedup keys")
        logger.info(" | ".join(parts))

    def set_genre(self, genre: str) -> None:
        """Set genre for JIT literacy_techniques injection.

        Args:
            genre: Genre key (e.g., 'romcom', 'fantasy', 'shoujo_romance')
        """
        self._genre = genre
        logger.debug(f"Genre set for JIT literacy techniques: {genre}")

    def set_book_type(self, book_type: str = None) -> None: # type: ignore
        """Set content type for module gating.

        Args:
            book_type: Content type - 'fiction' (default), 'memoir', 'biography',
                      'autobiography', 'non_fiction', 'essay'

        Side-effects when memoir/autobiography detected:
            - Loads music_industry_vocabulary supplement from vietnamese_grammar_rag_v2.json.
              This covers 40 J-music domain terms (レーベル, デビュー, ライブ, etc.) with
              VN equivalents and register notes for use in artist autobiography translation.
        """
        self._book_type = book_type
        logger.info(f"Book type set: {book_type or 'fiction (default)'}")

        # Memoir mode: load music-industry vocabulary supplement from grammar RAG v2.
        # Injected into cached system instruction alongside glossary/cultural-retention blocks.
        _memoir_types = {
            "memoir", "autobiography", "biography",
            "non_fiction", "non-fiction", "essay",
            "自伝", "ノンフィクション", "散文",
        }
        if (book_type or "").lower().strip() in _memoir_types:
            self._load_music_industry_vocab()

    @staticmethod
    def _is_memoir_like_tag(value: str) -> bool:
        """Return True when a genre/book_type token indicates memoir/autobiography."""
        token = (value or "").lower().replace("-", "_").strip()
        if not token:
            return False
        memoir_kws = (
            "memoir",
            "autobiography",
            "autobiographical",
            "biography",
            "biographical",
            "non_fiction",
            "nonfiction",
            "essay",
            "自伝",
            "自叙伝",
            "回顧録",
            "ノンフィクション",
            "散文",
        )
        return any(kw in token for kw in memoir_kws)

    def _load_music_industry_vocab(self) -> None:
        """Load music-industry vocabulary supplement from vietnamese_grammar_rag_v2.json.

        Called automatically by set_book_type() when memoir/autobiography is detected.
        Populates self._music_industry_vocab with the 40-term music domain registry;
        injected into the cached system instruction alongside the glossary block.
        """
        rag_v2_path = PIPELINE_ROOT / "config" / "vietnamese_grammar_rag_v2.json"
        if not rag_v2_path.exists():
            logger.warning(
                f"[MEMOIR] vietnamese_grammar_rag_v2.json not found at {rag_v2_path} "
                f"— music_industry_vocabulary supplement skipped"
            )
            return
        try:
            import json as _json
            with open(rag_v2_path, encoding="utf-8") as fh:
                rag_data = _json.load(fh)
            music_cat = rag_data.get("pattern_categories", {}).get("music_industry_vocabulary")
            if music_cat:
                self._music_industry_vocab = music_cat.get("patterns", [])
                logger.info(
                    f"[MEMOIR] Loaded {len(self._music_industry_vocab)} music-industry "
                    f"vocabulary terms from vietnamese_grammar_rag_v2.json"
                )
            else:
                logger.warning(
                    "[MEMOIR] music_industry_vocabulary category not found in "
                    "vietnamese_grammar_rag_v2.json — supplement skipped"
                )
        except Exception as exc:
            logger.warning(f"[MEMOIR] Failed to load music_industry_vocabulary: {exc}")

    def load_style_guide(self, genres: Union[List[str], str, None] = None, publisher: str = None) -> Optional[Dict[str, Any]]: # type: ignore
        """
        Load and merge hierarchical style guides with multi-genre semantic selection (EXPERIMENTAL - Vietnamese only).
        
        Loading Order:
        1. base_style_vi.json (universal rules)
        2. genres/{genre}_vi.json (one or more genre-specific guides)
        3. publishers/{publisher}_vi.json (publisher preferences)
        
        Multi-Genre Semantic Selection:
        - If genres=[list]: Loads specified genres with conditional instructions
        - If genres=None: Loads ALL available genres for semantic selection
        - If genres='single': Loads single genre (legacy behavior)
        
        The AI will semantically select appropriate genre rules based on scene context:
        - Fantasy battle → applies fantasy rules
        - Romance confession → applies romcom rules
        - Mixed scenes → merges relevant genre rules
        
        Args:
            genres: Genre key(s). Can be:
                   - List[str]: ['fantasy', 'romcom'] - Load specific genres
                   - str: 'romcom_school_life' - Load single genre (legacy)
                   - None: Load ALL available genres for semantic selection
            publisher: Publisher key (e.g., 'overlap')
        
        Returns:
            Style guide dictionary with genre metadata or None if not available
        """
        # Style guide system: VN (all genres) and EN (memoir only — called explicitly by agent.py)
        if self.target_language not in ['vi', 'vn', 'en']:
            logger.debug(f"Style guide system not available for language: {self.target_language}")
            return None
        
        if not self.style_guides_dir.exists():
            logger.debug(f"Style guides directory not found: {self.style_guides_dir}")
            return None
        
        try:
            merged_guide = {
                '_metadata': {
                    'mode': 'multi-genre' if (isinstance(genres, list) or genres is None) else 'single-genre',
                    'genres_loaded': [],
                    'publisher': publisher
                },
                'base': {},
                'genres': {},  # Will contain individual genre guides
                'publisher': {}
            }
            
            # 1. Load base style (universal Vietnamese rules)
            if self.base_style_path.exists():
                with open(self.base_style_path, 'r', encoding='utf-8') as f:
                    base_guide = json.load(f)
                    merged_guide['base'] = base_guide
                    logger.info(f"✓ Loaded base style guide: {self.base_style_path.name}")
            else:
                logger.warning(f"Base style guide not found: {self.base_style_path}")
                return None
            
            # 2. Load genre-specific styles (MULTI-GENRE SUPPORT)
            genres_to_load = []
            
            if genres is None:
                # Load ALL available genres for semantic selection
                if self.genres_dir.exists():
                    genre_files = [f for f in self.genres_dir.glob(f'*_{self.style_lang}.json')]
                    genres_to_load = [f.stem.replace(f'_{self.style_lang}', '') for f in genre_files]
                    logger.info(f"Multi-genre mode: Loading ALL {len(genres_to_load)} available genres")
            elif isinstance(genres, list):
                # Load specified genres
                genres_to_load = genres
                logger.info(f"Multi-genre mode: Loading {len(genres_to_load)} specified genres")
            elif isinstance(genres, str):
                # Single genre (legacy behavior)
                genres_to_load = [genres]
                merged_guide['_metadata']['mode'] = 'single-genre'
                logger.info(f"Single-genre mode: Loading {genres}")
            
            # Load each genre guide
            for genre_key in genres_to_load:
                genre_path = self.genres_dir / f'{genre_key}_{self.style_lang}.json'
                if genre_path.exists():
                    with open(genre_path, 'r', encoding='utf-8') as f:
                        genre_guide = json.load(f)
                        merged_guide['genres'][genre_key] = genre_guide
                        merged_guide['_metadata']['genres_loaded'].append(genre_key)
                        logger.info(f"✓ Loaded genre style guide: {genre_path.name}")
                else:
                    logger.warning(f"Genre style guide not found: {genre_path}")
            
            # 3. Load publisher-specific style
            if publisher:
                publisher_path = self.publishers_dir / f'{publisher}_{self.style_lang}.json'
                if publisher_path.exists():
                    with open(publisher_path, 'r', encoding='utf-8') as f:
                        publisher_guide = json.load(f)
                        merged_guide['publisher'] = publisher_guide
                        logger.info(f"✓ Loaded publisher style guide: {publisher_path.name}")
                else:
                    logger.warning(f"Publisher style guide not found: {publisher_path}")
            
            self._style_guide = merged_guide
            guide_size_kb = len(json.dumps(merged_guide, ensure_ascii=False).encode('utf-8')) / 1024
            genres_loaded = len(merged_guide['_metadata']['genres_loaded'])
            mode = merged_guide['_metadata']['mode']
            logger.info(f"✓ Style guide loaded: {mode}, {genres_loaded} genre(s), {guide_size_kb:.1f}KB [EXPERIMENTAL]")
            return merged_guide
            
        except Exception as e:
            logger.error(f"Failed to load style guide: {e}")
            return None
    
    def _merge_guides(self, base: Dict, override: Dict) -> Dict:
        """Deep merge two style guide dictionaries, with override taking precedence."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_guides(result[key], value)
            else:
                result[key] = value
        return result

    def load_master_prompt(self, genre: str = None) -> str: # type: ignore
        """
        Load the master prompt XML content.

        Args:
            genre: Optional genre key for configured prompt overrides.

        Returns:
            Master prompt content as string.
        """
        if self._master_prompt_cache:
            return self._master_prompt_cache

        # Determine path based on genre if specified
        target_path = self.prompts_path
        if genre:
            target_path = get_genre_prompt_path(genre, self.target_language)
            if target_path != self.prompts_path:
                logger.info(f"Using configured prompt override for '{genre}': {target_path}")
            else:
                logger.debug(
                    f"Genre '{genre}' resolves to the universal master prompt: {target_path}"
                )

        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self._master_prompt_cache = content
            logger.info(f"Master prompt loaded: {len(content)} chars from {target_path.name}")
            return content
        except Exception as e:
            logger.error(f"Failed to load master prompt from {target_path}: {e}")
            raise

    # DEPRECATED: load_kanji_difficult - replaced by vietnamese_grammar_rag.json
    # def load_kanji_difficult(self) -> Optional[Dict[str, Any]]:
    #     """Load kanji_difficult.json (Tier 1 - always inject)."""
    #     if self._kanji_difficult:
    #         return self._kanji_difficult
    #
    #     if not self.kanji_difficult_path or not self.kanji_difficult_path.exists():
    #         logger.debug("kanji_difficult.json not found")
    #         return None
    #
    #     try:
    #         with open(self.kanji_difficult_path, 'r', encoding='utf-8') as f:
    #             self._kanji_difficult = json.load(f)
    #         entries_count = self._kanji_difficult.get('metadata', {}).get('total_entries', 0)
    #         size_kb = self.kanji_difficult_path.stat().st_size / 1024
    #         logger.info(f"✓ Loaded kanji_difficult.json: {entries_count} entries ({size_kb:.1f}KB)")
    #         return self._kanji_difficult
    #     except Exception as e:
    #         logger.warning(f"Failed to load kanji_difficult.json: {e}")
    #         return None

    def load_negative_signals(self) -> Optional[Dict[str, Any]]:
        """Load negative_signals.json (Tier 1 EN).

        Contains ICL-backed quality enforcement patterns built from a 40-chapter
        production audit (メインヒロインより可愛いモブの田中さん + 男女比1:5 Vols 1-3).
        instruction_block.prompt_text is the verbatim injection string.
        """
        if self._negative_signals:
            return self._negative_signals

        neg_path = getattr(self, 'negative_signals_path', None)
        if not neg_path or not neg_path.exists():
            logger.debug("negative_signals.json not found (EN Tier 1 slot)")
            return None

        try:
            with open(neg_path, 'r', encoding='utf-8') as f:
                self._negative_signals = json.load(f)
            meta = self._negative_signals.get('_meta', {})
            version = meta.get('version', '?')
            total_patterns = meta.get('total_patterns', 0)
            total_categories = meta.get('total_categories', 0)
            size_kb = neg_path.stat().st_size / 1024
            logger.info(
                f"✓ Loaded negative_signals.json v{version}: "
                f"{total_patterns} patterns across {total_categories} categories ({size_kb:.1f}KB)"
            )
            return self._negative_signals
        except Exception as e:
            logger.warning(f"Failed to load negative_signals.json: {e}")
            return None

    def load_cjk_prevention(self) -> Optional[Dict[str, Any]]:
        """Load CJK prevention schema for target language (EN/VN)."""
        if self._cjk_prevention:
            return self._cjk_prevention
        
        if not self.cjk_prevention_path or not self.cjk_prevention_path.exists():
            logger.debug(f"CJK prevention schema not found for language: {self.target_language}")
            return None
        
        try:
            with open(self.cjk_prevention_path, 'r', encoding='utf-8') as f:
                self._cjk_prevention = json.load(f)
            size_kb = self.cjk_prevention_path.stat().st_size / 1024
            
            # Calculate total substitution patterns
            total_substitutions = sum([
                len(self._cjk_prevention.get('common_substitutions', {}).get(key, {}))
                for key in ['everyday_vocabulary', 'emotional_expressions', 'actions_and_states', 
                           'character_descriptions', 'chinese_phrases']
            ])
            
            schema_name = self.cjk_prevention_path.name
            logger.info(f"✓ Loaded {schema_name}: {total_substitutions} substitution patterns ({size_kb:.1f}KB)")
            return self._cjk_prevention
        except Exception as e:
            logger.warning(f"Failed to load CJK prevention schema: {e}")
            return None
    
    def load_anti_ai_ism_patterns(self) -> Optional[Dict[str, Any]]:
        """Load anti-AI-ism pattern library (v3.5)."""
        if self._anti_ai_ism:
            return self._anti_ai_ism
        
        if not self.anti_ai_ism_path or not self.anti_ai_ism_path.exists():
            logger.debug(f"Anti-AI-ism pattern library not found for language: {self.target_language}")
            return None
        
        try:
            with open(self.anti_ai_ism_path, 'r', encoding='utf-8') as f:
                self._anti_ai_ism = json.load(f)
            size_kb = self.anti_ai_ism_path.stat().st_size / 1024
            
            # Count patterns by severity (v2.0 structure)
            critical_patterns = len(self._anti_ai_ism.get('CRITICAL', {}).get('patterns', []))
            
            # Count MAJOR patterns across categories
            major_count = 0
            major_categories = self._anti_ai_ism.get('MAJOR', {}).get('categories', {})
            for category_data in major_categories.values():
                major_count += len(category_data.get('patterns', []))
            
            # Count MINOR patterns across categories
            minor_count = 0
            minor_categories = self._anti_ai_ism.get('MINOR', {}).get('categories', {})
            for category_data in minor_categories.values():
                minor_count += len(category_data.get('patterns', []))
            
            total_patterns = critical_patterns + major_count + minor_count
            
            # Check if echo detection is enabled (from _meta)
            meta = self._anti_ai_ism.get('_meta', {})
            echo_enabled = meta.get('echo_detection', {}).get('enabled', False)
            echo_status = "enabled" if echo_enabled else "disabled"
            
            logger.info(f"✓ Loaded anti_ai_ism_patterns.json: {total_patterns} patterns "
                       f"(CRITICAL: {critical_patterns}, MAJOR: {major_count}, "
                       f"MINOR: {minor_count}), echo detection {echo_status} ({size_kb:.1f}KB)")
            return self._anti_ai_ism
        except Exception as e:
            logger.warning(f"Failed to load anti-AI-ism pattern library: {e}")
            return None

    def load_english_grammar_rag(self) -> Optional[Dict[str, Any]]:
        """Load english_grammar_rag.json (Tier 1) - Natural idiom patterns for JP→EN translation."""
        if self._english_grammar_rag:
            return self._english_grammar_rag
        
        # Check for path attribute (only set for EN translations)
        if not hasattr(self, 'english_grammar_rag_path') or not self.english_grammar_rag_path:
            logger.debug("English Grammar RAG not configured for this language")
            return None
        
        if not self.english_grammar_rag_path.exists():
            logger.debug(f"English Grammar RAG not found: {self.english_grammar_rag_path}")
            return None
        
        try:
            with open(self.english_grammar_rag_path, 'r', encoding='utf-8') as f:
                self._english_grammar_rag = json.load(f)
            size_kb = self.english_grammar_rag_path.stat().st_size / 1024
            
            # Count patterns across categories
            pattern_categories = self._english_grammar_rag.get('pattern_categories', {})
            total_patterns = 0
            category_names = []
            
            for cat_name, cat_data in pattern_categories.items():
                patterns = cat_data.get('patterns', [])
                total_patterns += len(patterns)
                category_names.append(cat_name)
            
            # Count high-frequency transcreation patterns specifically
            hf_patterns = pattern_categories.get('high_frequency_transcreations', {}).get('patterns', [])
            transcreation_count = len(hf_patterns)
            
            logger.info(f"✓ Loaded english_grammar_rag.json: {total_patterns} patterns "
                       f"({transcreation_count} high-frequency transcreations) across "
                       f"{len(category_names)} categories ({size_kb:.1f}KB)")
            return self._english_grammar_rag
        except Exception as e:
            logger.warning(f"Failed to load English Grammar RAG: {e}")
            return None

    def load_english_grammar_validation_t1(self) -> Optional[Dict[str, Any]]:
        """Load english_grammar_validation_t1.json (Tier 1) - EN rhythm/literal/repetition guardrails."""
        if self._english_grammar_validation_t1:
            return self._english_grammar_validation_t1

        # Check for path attribute (only set for EN translations)
        if not hasattr(self, 'english_grammar_validation_t1_path') or not self.english_grammar_validation_t1_path:
            logger.debug("English Grammar Validation T1 not configured for this language")
            return None

        if not self.english_grammar_validation_t1_path.exists():
            logger.debug(f"English Grammar Validation T1 not found: {self.english_grammar_validation_t1_path}")
            return None

        try:
            with open(self.english_grammar_validation_t1_path, 'r', encoding='utf-8') as f:
                self._english_grammar_validation_t1 = json.load(f)
            size_kb = self.english_grammar_validation_t1_path.stat().st_size / 1024

            validation_categories = self._english_grammar_validation_t1.get('validation_categories', {})
            rhythm_rules = len(validation_categories.get('rhythm_and_emphasis', {}).get('patterns', []))
            literal_rules = len(validation_categories.get('literal_phrasing', {}).get('patterns', []))

            logger.info(
                f"✓ Loaded english_grammar_validation_t1.json: "
                f"{len(validation_categories)} categories "
                f"({rhythm_rules} rhythm/emphasis, {literal_rules} literal-phrasing rules) "
                f"({size_kb:.1f}KB)"
            )
            return self._english_grammar_validation_t1
        except Exception as e:
            logger.warning(f"Failed to load English Grammar Validation T1: {e}")
            return None

    def load_vietnamese_grammar_rag(self) -> Optional[Dict[str, Any]]:
        """Load vietnamese_grammar_rag.json (Tier 1) - Anti-AI-ism + particle system for JP→VN translation."""
        if self._vietnamese_grammar_rag:
            return self._vietnamese_grammar_rag
        
        # Check for path attribute (only set for VN translations)
        if not hasattr(self, 'vietnamese_grammar_rag_path') or not self.vietnamese_grammar_rag_path:
            logger.debug("Vietnamese Grammar RAG not configured for this language")
            return None
        
        if not self.vietnamese_grammar_rag_path.exists():
            logger.debug(f"Vietnamese Grammar RAG not found: {self.vietnamese_grammar_rag_path}")
            return None
        
        try:
            with open(self.vietnamese_grammar_rag_path, 'r', encoding='utf-8') as f:
                self._vietnamese_grammar_rag = json.load(f)
            size_kb = self.vietnamese_grammar_rag_path.stat().st_size / 1024
            
            # Count patterns across all categories
            total_patterns = 0
            category_stats = []
            
            # Count AI-ism patterns
            sentence_ai_isms = self._vietnamese_grammar_rag.get('sentence_structure_ai_isms', {}).get('patterns', [])
            dialogue_ai_isms = self._vietnamese_grammar_rag.get('dialogue_ai_isms', {}).get('patterns', [])
            total_patterns += len(sentence_ai_isms) + len(dialogue_ai_isms)
            category_stats.append(f"{len(sentence_ai_isms) + len(dialogue_ai_isms)} AI-ism rules")
            
            # Count particles (question + statement + exclamation)
            particle_system = self._vietnamese_grammar_rag.get('particle_system', {})
            question_particles = particle_system.get('question_particles', [])
            statement_particles = particle_system.get('statement_particles', [])
            exclamation_particles = particle_system.get('exclamation_particles', [])
            particle_combos = particle_system.get('combination_patterns', [])
            particle_count = len(question_particles) + len(statement_particles) + len(exclamation_particles)
            total_patterns += particle_count + len(particle_combos)
            category_stats.append(f"{particle_count} particles + {len(particle_combos)} combos")
            
            # Count archetypes
            archetypes = self._vietnamese_grammar_rag.get('archetype_register_matrix', {}).get('archetypes', {})
            total_patterns += len(archetypes)
            category_stats.append(f"{len(archetypes)} archetypes")
            
            # Count pronoun tiers
            pronoun_tiers = self._vietnamese_grammar_rag.get('pronoun_tiers', {})
            pronoun_count = 0
            for tier_type in ['friendship', 'romance_scale']:
                tier_data = pronoun_tiers.get(tier_type, {})
                if isinstance(tier_data, dict):
                    pronoun_count += len(tier_data)
            total_patterns += pronoun_count
            category_stats.append(f"{pronoun_count} pronoun tiers")
            
            logger.info(f"✓ Loaded vietnamese_grammar_rag.json: {total_patterns} patterns "
                       f"({', '.join(category_stats)}) ({size_kb:.1f}KB)")
            return self._vietnamese_grammar_rag
        except Exception as e:
            logger.warning(f"Failed to load Vietnamese Grammar RAG: {e}")
            return None

    def load_literacy_techniques(self) -> Optional[Dict[str, Any]]:
        """Load literacy_techniques.json (Tier 1) - Language-agnostic narrative techniques."""
        if self._literacy_techniques:
            return self._literacy_techniques

        if not self.literacy_techniques_path or not self.literacy_techniques_path.exists():
            logger.debug(f"Literacy techniques not found: {self.literacy_techniques_path}")
            return None

        try:
            with open(self.literacy_techniques_path, 'r', encoding='utf-8') as f:
                self._literacy_techniques = json.load(f)
            size_kb = self.literacy_techniques_path.stat().st_size / 1024

            # Count techniques
            first_person = self._literacy_techniques.get('narrative_techniques', {}).get('first_person', {}).get('subtechniques', {})
            third_person = self._literacy_techniques.get('narrative_techniques', {}).get('third_person', {}).get('subtechniques', {})
            psychic_distance_levels = len(self._literacy_techniques.get('psychic_distance_levels', {}).get('levels', {}))
            genre_presets = len(self._literacy_techniques.get('genre_specific_presets', {}))

            total_techniques = len(first_person) + len(third_person) + 1  # +1 for FID

            logger.info(f"✓ Loaded literacy_techniques.json: {total_techniques} narrative techniques, "
                       f"{psychic_distance_levels} psychic distance levels, {genre_presets} genre presets ({size_kb:.1f}KB)")
            return self._literacy_techniques
        except Exception as e:
            logger.warning(f"Failed to load literacy techniques: {e}")
            return None

    def load_literacy_techniques_compressed(self) -> Optional[Dict[str, Any]]:
        """Load literacy_techniques_compressed.json — 1 best example per mood (24 total).

        Used by the ICL auto-cap when pre-ICL system instruction > 220KB so that even a
        small max_examples cap (e.g. 5) still covers 5 *different* mood types rather than
        all 5 from the first priority category in the full JSON.
        """
        if self._literacy_techniques_compressed:
            return self._literacy_techniques_compressed

        if not self.literacy_techniques_compressed_path or not self.literacy_techniques_compressed_path.exists():
            logger.debug(f"Compressed literacy techniques not found: {self.literacy_techniques_compressed_path}")
            return None

        try:
            with open(self.literacy_techniques_compressed_path, 'r', encoding='utf-8') as f:
                self._literacy_techniques_compressed = json.load(f)
            size_kb = self.literacy_techniques_compressed_path.stat().st_size / 1024
            icl_section = self._literacy_techniques_compressed.get('real_world_jp_en_corpus', {}).get('professional_prose_icl_examples', {})
            total = sum(len(v.get('examples', [])) for v in icl_section.get('examples_by_mood', {}).values())
            logger.info(f"✓ Loaded literacy_techniques_compressed.json: {total} exemplars (1/mood) ({size_kb:.1f}KB)")
            return self._literacy_techniques_compressed
        except Exception as e:
            logger.warning(f"Failed to load compressed literacy techniques: {e}")
            return None

    def load_formatting_standards(self) -> Optional[Dict[str, Any]]:
        """Load formatting_standards.json (Tier 1) - punctuation + romanization standards."""
        if self._formatting_standards:
            return self._formatting_standards

        if not self.formatting_standards_path or not self.formatting_standards_path.exists():
            logger.debug(f"Formatting standards not found: {self.formatting_standards_path}")
            return None

        try:
            with open(self.formatting_standards_path, 'r', encoding='utf-8') as f:
                self._formatting_standards = json.load(f)
            size_kb = self.formatting_standards_path.stat().st_size / 1024
            categories = self._formatting_standards.get('pattern_categories', {})
            category_count = len(categories) if isinstance(categories, dict) else 0
            logger.info(
                f"✓ Loaded formatting_standards.json: {category_count} categories "
                f"({size_kb:.1f}KB)"
            )
            return self._formatting_standards
        except Exception as e:
            logger.warning(f"Failed to load formatting standards: {e}")
            return None

    def load_narrative_tense_standards(self) -> Optional[Dict[str, Any]]:
        """
        Load narrative tense consistency standards from literacy_techniques.json.

        Returns:
            Dict containing tense standards or None if not found
        """
        if not hasattr(self, '_literacy_techniques') or not self._literacy_techniques:
            self._literacy_techniques = self.load_literacy_techniques()

        if not self._literacy_techniques:
            return None

        # Check both at root level and under narrative_techniques
        tense_standards = self._literacy_techniques.get('narrative_tense_standards', {})
        if not tense_standards:
            # Try nested under narrative_techniques
            narrative_techniques = self._literacy_techniques.get('narrative_techniques', {})
            tense_standards = narrative_techniques.get('narrative_tense_standards', {})

        if tense_standards:
            logger.debug(f"Loaded narrative tense standards with {len(tense_standards.get('allowed_present_tense_contexts', []))} whitelist contexts")
        return tense_standards if tense_standards else None

    def load_reference_index(self) -> Optional[Dict[str, Any]]:
        """Load reference_index.json (Three-Tier RAG metadata)."""
        if self._reference_index:
            return self._reference_index
        
        if not self.reference_index_path or not self.reference_index_path.exists():
            logger.debug("reference_index.json not found")
            return None
        
        try:
            with open(self.reference_index_path, 'r', encoding='utf-8') as f:
                self._reference_index = json.load(f)
            total_files = self._reference_index.get('total_files', 0)
            total_lines = self._reference_index.get('total_lines', 0)
            logger.info(f"✓ Loaded reference_index.json: {total_files} files, {total_lines} lines indexed")
            return self._reference_index
        except Exception as e:
            logger.warning(f"Failed to load reference_index.json: {e}")
            return None

    def load_reference_modules(self, genre: str = None) -> Dict[str, str]: # type: ignore
        """
        Load reference modules from VN/Reference/ (Tier 2 - context-aware).
        
        For now, implements simplified loading logic based on genre.
        Full context-aware loading (PAIR_ID, scene types, etc.) is Week 2 enhancement.
        
        Args:
            genre: Novel genre (romcom, fantasy, etc.) for genre-based filtering
            
        Returns:
            Dictionary of reference module filenames to content
        """
        if not self.reference_dir or not self.reference_dir.exists():
            return {}
        
        reference_index = self.load_reference_index()
        if not reference_index:
            logger.warning("reference_index.json not loaded - skipping reference modules")
            return {}
        
        modules = {}
        
        # Get list of reference modules from config
        reference_module_names = self.lang_config.get('reference_modules', [])
        if not reference_module_names:
            logger.debug("No reference modules configured in config.yaml")
            return {}
        
        # Load reference modules
        for module_name in reference_module_names:
            module_path = self.reference_dir / module_name
            
            # Try with original name and common variants
            if not module_path.exists():
                # Try appending .md if missing
                if not module_name.endswith('.md'):
                    module_path = self.reference_dir / f"{module_name}.md"
                
                # Try with _VN suffix variations
                if not module_path.exists() and not '_VN' in module_name:
                    module_path = self.reference_dir / module_name.replace('.md', '_VN.md')
            
            if module_path.exists():
                try:
                    with open(module_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    modules[module_path.name] = content
                    size_kb = len(content.encode('utf-8')) / 1024
                    logger.info(f"Loaded reference module: {module_path.name} ({size_kb:.1f}KB)")
                except Exception as e:
                    logger.warning(f"Failed to load reference module {module_path.name}: {e}")
            else:
                logger.debug(f"Reference module not found: {module_name}")
        
        return modules

    def load_rag_modules(self) -> Dict[str, str]:
        """Load all RAG knowledge modules into memory."""
        if self._rag_modules_cache:
            return self._rag_modules_cache

        modules = {}
        if not self.modules_dir.exists():
            logger.warning(f"Modules directory not found: {self.modules_dir}")
            return modules

        # Load all .md files that are not explicitly disabled
        for file_path in self.modules_dir.glob("*.md"):
            if file_path.name.startswith("DISABLED_"):
                logger.info(f"Skipping disabled module: {file_path.name}")
                continue
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    modules[file_path.name] = content
                    module_size_kb = len(content.encode('utf-8')) / 1024
                    logger.info(f"Loaded RAG module: {file_path.name} ({module_size_kb:.1f}KB)")
            except Exception as e:
                logger.warning(f"Failed to load module {file_path.name}: {e}")

        # Log summary
        total_modules = len(modules)
        total_size_kb = sum(len(c.encode('utf-8')) for c in modules.values()) / 1024
        logger.info(f"Total RAG modules loaded: {total_modules} files ({total_size_kb:.1f}KB)")

        # Verify anti-AI-ism module is present (v3.0 consolidated)
        anti_aiism = "ANTI_AIISM_MODULE.md" in modules
        anti_translationese = "ANTI_TRANSLATIONESE_MODULE_VN.md" in modules

        if anti_aiism:
            logger.info("✓ Anti-AI-ism module detected (ANTI_AIISM_MODULE.md v3.0)")
        elif anti_translationese:
            logger.info("✓ Anti-AI-ism module detected (ANTI_TRANSLATIONESE v2.1 for VN)")
        else:
            logger.warning("⚠ Anti-AI-ism module NOT found - using legacy prompt only")

        self._rag_modules_cache = modules
        return modules

    def build_system_instruction(self, genre: str = None) -> str: # type: ignore
        """
        Construct the final system instruction with Three-Tier RAG injection.

        Tier 1 (Always inject):
          - Core modules (MEGA_CORE, ANTI_TRANSLATIONESE, MEGA_CHARACTER_VOICE)
          - DEPRECATED: kanji_difficult.json (replaced by vietnamese_grammar_rag.json for VN)
          - cjk_prevention_schema_*.json (language-specific)
          - anti_ai_ism_patterns.json (EN only)
          - english_grammar_rag.json (EN only)
          - vietnamese_grammar_rag.json (VN only)
          - literacy_techniques.json (language-agnostic)
          - formatting_standards.json (language-agnostic)

        Tier 2 (Context-aware / genre-gated):
          - Reference modules based on genre/triggers
          - FANTASY_TRANSLATION_MODULE_EN.md: only for fantasy/isekai/action genres

        Tier 3 (On-demand):
          - Deferred to Week 3 (retrieval-based)

        Args:
            genre: Novel genre for context-aware module selection

        Returns:
            Complete system instruction with injected RAG modules
        """
        logger.debug("[VERBOSE] Building system instruction...")
        import time
        start_time = time.time()

        # Store genre for JIT literacy_techniques injection
        if genre:
            self._genre = genre

        logger.debug("[VERBOSE] Loading master prompt...")
        master_prompt = self.load_master_prompt(genre)
        logger.debug(f"[VERBOSE] Master prompt loaded: {len(master_prompt)} chars")
        
        # Load Tier 1: Core RAG modules
        logger.debug("[VERBOSE] Loading Tier 1 RAG modules (core)...")
        tier1_modules = self.load_rag_modules()
        logger.debug(f"[VERBOSE] Tier 1 modules loaded: {len(tier1_modules)} files")
        
        # DEPRECATED: kanji_difficult.json - replaced by vietnamese_grammar_rag.json
        # logger.debug("[VERBOSE] Loading Tier 1: kanji_difficult.json...")
        # kanji_data = self.load_kanji_difficult()
        kanji_data = None  # DEPRECATED

        # Load Tier 1: negative_signals.json (EN only - ICL-backed quality enforcement)
        logger.debug("[VERBOSE] Loading Tier 1: negative_signals.json...")
        negative_signals_data = self.load_negative_signals()

        # Load Tier 1: cjk_prevention_schema_vn.json
        logger.debug("[VERBOSE] Loading Tier 1: cjk_prevention_schema_vn.json...")
        cjk_prevention_data = self.load_cjk_prevention()
        
        # Load Tier 1: anti_ai_ism_patterns.json (v3.5)
        logger.debug("[VERBOSE] Loading Tier 1: anti_ai_ism_patterns.json...")
        anti_ai_ism_data = self.load_anti_ai_ism_patterns()
        
        # Load Tier 1: english_grammar_rag.json (EN only - natural idiom patterns)
        logger.debug("[VERBOSE] Loading Tier 1: english_grammar_rag.json...")
        english_grammar_rag_data = self.load_english_grammar_rag()

        # Load Tier 1: english_grammar_validation_t1.json (EN only - rhythm/literal/repetition guardrails)
        logger.debug("[VERBOSE] Loading Tier 1: english_grammar_validation_t1.json...")
        english_grammar_validation_t1_data = self.load_english_grammar_validation_t1()
        
        # Load Tier 1: vietnamese_grammar_rag.json (VN only - anti-AI-ism + particle system)
        logger.debug("[VERBOSE] Loading Tier 1: vietnamese_grammar_rag.json...")
        vietnamese_grammar_rag_data = self.load_vietnamese_grammar_rag()

        # Load Tier 1: literacy_techniques.json (language-agnostic narrative techniques)
        logger.debug("[VERBOSE] Loading Tier 1: literacy_techniques.json...")
        literacy_techniques_data = self.load_literacy_techniques()

        # Load Tier 1: formatting_standards.json (language-agnostic formatting + romanization)
        logger.debug("[VERBOSE] Loading Tier 1: formatting_standards.json...")
        formatting_standards_data = self.load_formatting_standards()

        # Load Tier 2: Reference modules (context-aware)
        logger.debug("[VERBOSE] Loading Tier 2 reference modules...")
        reference_modules = self.load_reference_modules(genre)
        logger.debug(f"[VERBOSE] Tier 2 modules loaded: {len(reference_modules)} files")
        
        # Merge all modules for injection
        all_modules = {**tier1_modules, **reference_modules}

        # EN memoir/autobiography: ensure Tier-1 autobiography style guide is loaded
        # even when manifest book_type is missing and only genre carries memoir tags.
        _genre_token = (genre or "").lower().replace("-", "_").strip()
        _book_type_token = (self._book_type or "").lower().replace("-", "_").strip()
        _memoir_mode_from_meta = self._is_memoir_like_tag(_book_type_token)
        _memoir_mode_from_genre = self._is_memoir_like_tag(_genre_token)
        _memoir_mode = _memoir_mode_from_meta or _memoir_mode_from_genre
        if self.target_language in ["en", "english"] and _memoir_mode and not self._style_guide:
            try:
                self.load_style_guide(genres=["autobiography_memoir"], publisher=None) # type: ignore
                logger.info(
                    "[TIER1][EN MEMOIR] Loaded autobiography_memoir_en style guide "
                    "(trigger=%s)",
                    "book_type" if _memoir_mode_from_meta else "genre",
                )
            except Exception as e:
                logger.warning(f"[TIER1][EN MEMOIR] Failed to load autobiography_memoir_en style guide: {e}")

        # Tier 2 gate:
        # 1) Hard exception: skip FANTASY module for modern/contemporary Japan world settings
        #    even when genre contains fantasy tags (e.g., modern_urban_fantasy, reincarnation in modern JP).
        # 2) Legacy fallback: skip ONLY for confirmed non-fantasy genres.
        # 3) Unknown genre: keep module (fail-open).
        #
        # The `genre` string may be a free-text genre tag OR a world_setting.type value such as
        # "fantasy_european_nobility_academy", "steampunk_fantasy", "modern_japan", etc.
        # Both paths use the same keyword-substring match so no special pre-processing needed.
        #
        _world_ctx = " ".join([
            (genre or "").lower().replace("-", "_"),
            (self._bible_world_directive or "").lower().replace("-", "_"),
        ])
        _modern_world_kws = {
            "modern", "contemporary", "present_day", "presentday", "real_world",
            "modern_japan", "contemporary_japan", "japan", "japanese_society",
        }
        _reincarnation_kws = {"reincarnation", "reincarnat", "tensei", "transmigration", "reborn"}
        _modern_world_reflection = any(mkw in _world_ctx for mkw in _modern_world_kws)
        _has_reincarnation = any(rkw in _world_ctx for rkw in _reincarnation_kws)

        # Non-fantasy keywords (all must be absent from fantasy branch):
        _non_fantasy_kws = {"romcom", "contemporary", "slice_of_life", "school_life", "modern_japan", "modern_urban"}
        # Fantasy / non-modern-world keywords (any match → keep module):
        _fantasy_kws = {
            "fantasy", "isekai", "action", "adventure", "dark_fantasy",
            "noble_academy", "sword", "magic", "steampunk", "academy",
            "noble", "european", "medieval", "vrmmo", "virtual_reality",
        }
        _current_genre = (genre or "").lower().replace("-", "_")
        _genre_known = bool(_current_genre)
        _is_fantasy = any(fkw in _current_genre for fkw in _fantasy_kws)
        _is_non_fantasy = _genre_known and not _is_fantasy and any(nfkw in _current_genre for nfkw in _non_fantasy_kws)

        fantasy_key = next(
            (k for k in all_modules if "FANTASY_TRANSLATION_MODULE" in k), None
        )
        if _modern_world_reflection:
            if fantasy_key:
                del all_modules[fantasy_key]
                logger.info(
                    f"Skipped {fantasy_key} (modern-world exception: genre='{genre}', "
                    f"world_directive_present={bool(self._bible_world_directive)}, reincarnation={_has_reincarnation})"
                )
        elif _is_non_fantasy:
            if fantasy_key:
                del all_modules[fantasy_key]
                logger.info(f"Skipped {fantasy_key} (genre='{genre}' confirmed non-fantasy — Tier 2 gate)")
        elif _is_fantasy:
            logger.info(f"FANTASY module active (genre='{genre}')")
        else:
            logger.info(f"FANTASY module retained (genre unknown — fail-open default)")

        # Tier 2 gate: memoir/non-fiction mode skips LN-fiction modules and enables memoir module.
        # Memoir mode can be activated by explicit book_type OR memoir-like genre tag.
        _book_type = (self._book_type or "").lower().strip() if self._book_type else ""
        _is_non_fiction = _book_type in {"memoir", "biography", "autobiography", "non_fiction", "non-fiction", "essay", "散文", "自伝", "ノンフィクション"}
        _is_memoir_genre = self._is_memoir_like_tag(_current_genre)
        _memoir_mode_active = _is_non_fiction or _is_memoir_genre

        # LN-specific modules to skip for non-fiction (VN-specific)
        _ln_modules_to_skip_vn = {
            "MEGA_CHARACTER_VOICE_SYSTEM_VN.md",
            "Library_LOCALIZATION_PRIMER_VN.md",
            "ANTI_TRANSLATIONESE_MODULE_VN.md",
            "MEGA_CORE_TRANSLATION_ENGINE_VN.md",
        }
        # LN-specific modules to skip for non-fiction (EN-specific)
        _ln_modules_to_skip_en = {
            "MEGA_CHARACTER_VOICE_SYSTEM.md",
            "Library_LOCALIZATION_PRIMER_EN.md",
        }
        _ln_modules_to_skip = _ln_modules_to_skip_vn if self.target_language == 'vn' else _ln_modules_to_skip_en

        memoir_key = next((k for k in all_modules if "MEMOIR_TRANSLATION_MODULE.md" in k), None)

        if _memoir_mode_active:
            skipped_ln_modules = []
            for ln_module in _ln_modules_to_skip:
                if ln_module in all_modules:
                    del all_modules[ln_module]
                    skipped_ln_modules.append(ln_module)
            if skipped_ln_modules:
                logger.info(
                    f"Skipped LN-specific modules for memoir mode "
                    f"(book_type='{_book_type or 'n/a'}', genre='{genre}'): {skipped_ln_modules}"
                )
            if memoir_key:
                logger.info(
                    f"MEMOIR module active (book_type='{_book_type or 'n/a'}', genre='{genre or 'n/a'}')"
                )
            else:
                logger.warning(
                    f"No MEMOIR_TRANSLATION_MODULE.md found for memoir mode "
                    f"(book_type='{_book_type or 'n/a'}', genre='{genre or 'n/a'}') "
                    f"— LN modules skipped with no replacement"
                )
        else:
            # Prevent memoir rules from leaking into fiction prompts.
            if memoir_key:
                del all_modules[memoir_key]
                logger.debug("Skipped MEMOIR_TRANSLATION_MODULE.md (memoir mode inactive)")
            logger.info(f"LN-specific modules retained (book_type='{_book_type or 'fiction/default'}')")

        final_prompt = master_prompt
        injected_count = 0
        anti_ai_ism_injected = []

        # Inject markdown modules
        for filename, content in all_modules.items():
            if filename in final_prompt:
                 module_size_kb = len(content.encode('utf-8')) / 1024
                 # Size Check: Skip modules larger than 500KB to prevent TPM exhaustion
                 if module_size_kb > 500:
                     logger.warning(f"Skipping injection of massive module {filename} ({module_size_kb:.1f}KB) to prevent TPM exhaustion.")
                     continue

                 # Inject content
                 logger.info(f"Injecting RAG module: {filename} ({module_size_kb:.1f}KB)")
                 injected_content = f"\n<!-- START MODULE: {filename} -->\n{content}\n<!-- END MODULE: {filename} -->\n"
                 final_prompt = final_prompt.replace(filename, injected_content)
                 injected_count += 1

                 # Track anti-AI-ism modules
                 if "ANTI_AIISM" in filename or "ANTI_TRANSLATIONESE" in filename:
                     anti_ai_ism_injected.append(filename)
            else:
                 logger.debug(f"Module {filename} loaded but not referenced in master prompt.")

        # DEPRECATED: kanji_difficult.json injection - replaced by vietnamese_grammar_rag.json
        # if kanji_data and "kanji_difficult.json" in final_prompt:
        #     kanji_entries = kanji_data.get('kanji_entries', [])
        #     kanji_formatted = self._format_kanji_for_injection(kanji_entries, genre)
        #     kanji_size_kb = len(kanji_formatted.encode('utf-8')) / 1024
        #
        #     logger.info(f"Injecting kanji_difficult.json: {len(kanji_entries)} entries ({kanji_size_kb:.1f}KB)")
        #     kanji_injection = f"\n<!-- START MODULE: kanji_difficult.json -->\n{kanji_formatted}\n<!-- END MODULE: kanji_difficult.json -->\n"
        #     final_prompt = final_prompt.replace("kanji_difficult.json", kanji_injection)
        #     injected_count += 1

        # Inject negative_signals.json (Tier 1 EN - ICL-backed quality enforcement)
        # Auto-appends (no placeholder needed).
        if negative_signals_data and self.target_language in ['en', 'english']:
            neg_formatted = self._format_negative_signals_for_injection(negative_signals_data)
            neg_size_kb = len(neg_formatted.encode('utf-8')) / 1024
            meta_ns = negative_signals_data.get('_meta', {})
            total_patterns_ns = meta_ns.get('total_patterns', 0)
            total_categories_ns = meta_ns.get('total_categories', 0)
            version_ns = meta_ns.get('version', '?')
            logger.info(
                f"Injecting negative_signals.json v{version_ns}: "
                f"{total_patterns_ns} patterns ({total_categories_ns} categories) ({neg_size_kb:.1f}KB)"
            )
            neg_injection = (
                f"\n<!-- START MODULE: negative_signals.json v{version_ns} -->\n"
                f"{neg_formatted}\n"
                f"<!-- END MODULE: negative_signals.json -->\n"
            )
            final_prompt += f"\n\n{neg_injection}"
            injected_count += 1
            anti_ai_ism_injected.append(
                f'negative_signals.json v{version_ns} (Tier 1 EN, {total_patterns_ns} patterns, {total_categories_ns} categories)'
            )

        # Inject cjk_prevention_schema_vn.json (Tier 1)
        if cjk_prevention_data and "cjk_prevention_schema_vn.json" in final_prompt:
            cjk_formatted = self._format_cjk_prevention_for_injection(cjk_prevention_data)
            cjk_size_kb = len(cjk_formatted.encode('utf-8')) / 1024
            
            logger.info(f"Injecting cjk_prevention_schema_vn.json: CJK prevention rules ({cjk_size_kb:.1f}KB)")
            cjk_injection = f"\n<!-- START MODULE: cjk_prevention_schema_vn.json -->\n{cjk_formatted}\n<!-- END MODULE: cjk_prevention_schema_vn.json -->\n"
            final_prompt = final_prompt.replace("cjk_prevention_schema_vn.json", cjk_injection)
            injected_count += 1
        
        # Inject anti_ai_ism_patterns.json (Tier 1 - v3.5)
        if anti_ai_ism_data and "anti_ai_ism_patterns.json" in final_prompt:
            anti_ai_ism_formatted = self._format_anti_ai_ism_for_injection(anti_ai_ism_data)
            anti_ai_ism_size_kb = len(anti_ai_ism_formatted.encode('utf-8')) / 1024
            
            # Count patterns
            critical_count = len(anti_ai_ism_data.get('CRITICAL', {}).get('patterns', []))
            major_categories = anti_ai_ism_data.get('MAJOR', {}).get('categories', {})
            major_count = sum(len(cat.get('patterns', [])) for cat in major_categories.values())
            total_count = critical_count + major_count
            
            logger.info(f"Injecting anti_ai_ism_patterns.json: {total_count} patterns ({critical_count} CRITICAL, {major_count} MAJOR) + echo detection ({anti_ai_ism_size_kb:.1f}KB)")
            anti_ai_ism_injection = f"\n<!-- START MODULE: anti_ai_ism_patterns.json -->\n{anti_ai_ism_formatted}\n<!-- END MODULE: anti_ai_ism_patterns.json -->\n"
            final_prompt = final_prompt.replace("anti_ai_ism_patterns.json", anti_ai_ism_injection)
            injected_count += 1
            anti_ai_ism_injected.append('anti_ai_ism_patterns.json (v3.5)')

        # Inject english_grammar_rag.json (Tier 1 - EN only, natural idioms)
        if english_grammar_rag_data and "english_grammar_rag.json" in final_prompt:
            english_grammar_formatted = self._format_english_grammar_rag_for_injection(english_grammar_rag_data)
            grammar_size_kb = len(english_grammar_formatted.encode('utf-8')) / 1024
            
            # Count patterns
            pattern_categories = english_grammar_rag_data.get('pattern_categories', {})
            total_patterns = sum(len(cat.get('patterns', [])) for cat in pattern_categories.values())
            hf_transcreations = len(pattern_categories.get('high_frequency_transcreations', {}).get('patterns', []))
            
            logger.info(f"Injecting english_grammar_rag.json: {total_patterns} patterns ({hf_transcreations} high-frequency transcreations) ({grammar_size_kb:.1f}KB)")
            grammar_injection = f"\n<!-- START MODULE: english_grammar_rag.json -->\n{english_grammar_formatted}\n<!-- END MODULE: english_grammar_rag.json -->\n"
            final_prompt = final_prompt.replace("english_grammar_rag.json", grammar_injection)
            injected_count += 1
            anti_ai_ism_injected.append('english_grammar_rag.json (Tier 1)')
        elif english_grammar_rag_data:
            # Auto-append if placeholder not found (fallback for prompts without placeholder)
            english_grammar_formatted = self._format_english_grammar_rag_for_injection(english_grammar_rag_data)
            grammar_size_kb = len(english_grammar_formatted.encode('utf-8')) / 1024
            
            pattern_categories = english_grammar_rag_data.get('pattern_categories', {})
            total_patterns = sum(len(cat.get('patterns', [])) for cat in pattern_categories.values())
            
            logger.info(f"Appending english_grammar_rag.json (no placeholder found): {total_patterns} patterns ({grammar_size_kb:.1f}KB)")
            final_prompt += f"\n\n<!-- START MODULE: english_grammar_rag.json (AUTO-APPENDED) -->\n{english_grammar_formatted}\n<!-- END MODULE: english_grammar_rag.json -->\n"
            injected_count += 1
            anti_ai_ism_injected.append('english_grammar_rag.json (Tier 1, auto-appended)')

        # english_grammar_validation_t1.json — NOT injected into generation context.
        # Contains post-hoc validation rules that Opus cannot act on at generation time.
        # Data is loaded only for literacy_techniques injection reference.
        if english_grammar_validation_t1_data:
            logger.debug("english_grammar_validation_t1.json loaded (literacy_techniques reference only)")

        # Inject vietnamese_grammar_rag.json (Tier 1 - VN only, anti-AI-ism + particle system)
        if vietnamese_grammar_rag_data and "vietnamese_grammar_rag.json" in final_prompt:
            vietnamese_grammar_formatted = self._format_vietnamese_grammar_rag_for_injection(vietnamese_grammar_rag_data)
            grammar_size_kb = len(vietnamese_grammar_formatted.encode('utf-8')) / 1024
            
            # Count patterns
            sentence_ai_isms = len(vietnamese_grammar_rag_data.get('sentence_structure_ai_isms', {}).get('patterns', []))
            dialogue_ai_isms = len(vietnamese_grammar_rag_data.get('dialogue_ai_isms', {}).get('patterns', []))
            # Count particles from correct keys
            particle_system = vietnamese_grammar_rag_data.get('particle_system', {})
            particles = len(particle_system.get('question_particles', [])) + len(particle_system.get('statement_particles', [])) + len(particle_system.get('exclamation_particles', []))
            total_patterns = sentence_ai_isms + dialogue_ai_isms + particles
            
            logger.info(f"Injecting vietnamese_grammar_rag.json: {total_patterns} patterns ({sentence_ai_isms + dialogue_ai_isms} AI-isms, {particles} particles) ({grammar_size_kb:.1f}KB)")
            grammar_injection = f"\n<!-- START MODULE: vietnamese_grammar_rag.json -->\n{vietnamese_grammar_formatted}\n<!-- END MODULE: vietnamese_grammar_rag.json -->\n"
            final_prompt = final_prompt.replace("vietnamese_grammar_rag.json", grammar_injection)
            injected_count += 1
            anti_ai_ism_injected.append('vietnamese_grammar_rag.json (Tier 1)')
        elif vietnamese_grammar_rag_data:
            # Auto-append if placeholder not found (fallback for prompts without placeholder)
            vietnamese_grammar_formatted = self._format_vietnamese_grammar_rag_for_injection(vietnamese_grammar_rag_data)
            grammar_size_kb = len(vietnamese_grammar_formatted.encode('utf-8')) / 1024
            
            sentence_ai_isms = len(vietnamese_grammar_rag_data.get('sentence_structure_ai_isms', {}).get('patterns', []))
            dialogue_ai_isms = len(vietnamese_grammar_rag_data.get('dialogue_ai_isms', {}).get('patterns', []))
            # Count particles from correct keys
            particle_system = vietnamese_grammar_rag_data.get('particle_system', {})
            particles = len(particle_system.get('question_particles', [])) + len(particle_system.get('statement_particles', [])) + len(particle_system.get('exclamation_particles', []))
            total_patterns = sentence_ai_isms + dialogue_ai_isms + particles
            
            logger.info(f"Appending vietnamese_grammar_rag.json (no placeholder found): {total_patterns} patterns ({grammar_size_kb:.1f}KB)")
            final_prompt += f"\n\n<!-- START MODULE: vietnamese_grammar_rag.json (AUTO-APPENDED) -->\n{vietnamese_grammar_formatted}\n<!-- END MODULE: vietnamese_grammar_rag.json -->\n"
            injected_count += 1
            anti_ai_ism_injected.append('vietnamese_grammar_rag.json (Tier 1, auto-appended)')

        # Inject literacy_techniques.json (Tier 1 - language-agnostic narrative techniques)
        if literacy_techniques_data and "literacy_techniques.json" in final_prompt:
            literacy_formatted = self._format_literacy_techniques_for_injection(
                literacy_techniques_data,
                english_grammar_validation_t1_data,
                self.target_language,
                genre or self._genre  # JIT: only inject matching genre preset
            )
            literacy_size_kb = len(literacy_formatted.encode('utf-8')) / 1024

            # Count techniques
            first_person = len(literacy_techniques_data.get('narrative_techniques', {}).get('first_person', {}).get('subtechniques', {}))
            third_person = len(literacy_techniques_data.get('narrative_techniques', {}).get('third_person', {}).get('subtechniques', {}))
            psychic_levels = len(literacy_techniques_data.get('psychic_distance_levels', {}).get('levels', {}))
            genre_presets = len(literacy_techniques_data.get('genre_specific_presets', {}))

            _active_genre = genre or self._genre
            logger.info(
                f"[JIT] literacy_techniques.json: {first_person + third_person + 1} narrative techniques, "
                f"{psychic_levels} psychic levels, genre={_active_genre or 'all'} ({literacy_size_kb:.1f}KB)"
            )
            literacy_injection = f"\n<!-- START MODULE: literacy_techniques.json -->\n{literacy_formatted}\n<!-- END MODULE: literacy_techniques.json -->\n"
            final_prompt = final_prompt.replace("literacy_techniques.json", literacy_injection)
            injected_count += 1
        elif literacy_techniques_data:
            # Auto-append if placeholder not found (fallback for prompts without placeholder)
            literacy_formatted = self._format_literacy_techniques_for_injection(
                literacy_techniques_data,
                english_grammar_validation_t1_data,
                self.target_language,
                genre or self._genre  # JIT: only inject matching genre preset
            )
            literacy_size_kb = len(literacy_formatted.encode('utf-8')) / 1024

            first_person = len(literacy_techniques_data.get('narrative_techniques', {}).get('first_person', {}).get('subtechniques', {}))
            third_person = len(literacy_techniques_data.get('narrative_techniques', {}).get('third_person', {}).get('subtechniques', {}))

            _active_genre = genre or self._genre
            logger.info(
                f"[JIT] literacy_techniques.json (auto-appended): {first_person + third_person + 1} techniques, "
                f"genre={_active_genre or 'all'} ({literacy_size_kb:.1f}KB)"
            )
            final_prompt += f"\n\n<!-- START MODULE: literacy_techniques.json (AUTO-APPENDED) -->\n{literacy_formatted}\n<!-- END MODULE: literacy_techniques.json -->\n"
            injected_count += 1

        # Inject professional prose ICL examples from literacy_techniques.json (Tier 1 - always appended)
        # These are real published J-Novel English passages used as quality anchors.
        # Token cost: up to ~41K tokens (76 examples × ~540 tokens avg). Auto-capped when system
        # instruction is large to prevent exceeding Claude's 200K token context window.
        # Rendered separately from _format_literacy_techniques_for_injection() to keep structural
        # technique rules and prose exemplars as distinct prompt sections.
        #
        # ICL AUTO-CAP + SOURCE ROUTING:
        #   Compressed JSON (1 example/mood, 24 total) is used whenever pre-ICL > 180KB.
        #   This ensures that even a small max_examples cap covers N *different* mood types
        #   rather than N examples from the same first-priority category in the full JSON.
        #
        #   Thresholds calibrated at 0.43 tok/char (conservative, JP-heavy content).
        #   User message tokens for a large chapter (~215K chars) ≈ 92K tokens, leaving
        #   ~108K token budget for the system (= ~251KB at 0.43 tok/char).
        #
        #   > 225KB → compressed + 3  examples  (3 diverse moods, ~5.5KB, ~39K tokens saved)
        #   > 205KB → compressed + 12 examples  (12 diverse moods, ~15.6KB,~30K tokens saved)
        #   > 180KB → compressed + None          (all 24 moods,    ~31.3KB, ~15K tokens saved)
        #   ≤ 180KB → full    + None             (all 76 examples, ~98.4KB, full quality)
        _pre_icl_size_kb = len(final_prompt.encode('utf-8')) / 1024
        _use_compressed_icl = _pre_icl_size_kb > 180
        if _pre_icl_size_kb > 225:
            _icl_max_examples = 3
            logger.warning(
                f"[ICL-CAP] Pre-ICL system instruction is {_pre_icl_size_kb:.1f}KB — "
                f"routing to compressed ICL, capping at 3 diverse-mood exemplars (extreme chapter guard)."
            )
        elif _pre_icl_size_kb > 205:
            _icl_max_examples = 12
            logger.info(
                f"[ICL-CAP] Pre-ICL system instruction is {_pre_icl_size_kb:.1f}KB — "
                f"routing to compressed ICL, capping at 12 diverse-mood exemplars."
            )
        elif _pre_icl_size_kb > 180:
            _icl_max_examples = None  # all 24 from compressed
            logger.info(
                f"[ICL-CAP] Pre-ICL system instruction is {_pre_icl_size_kb:.1f}KB — "
                f"routing to compressed ICL (all 24 moods)."
            )
        else:
            _icl_max_examples = None  # full set
        # Select ICL data source: compressed for danger zones, full otherwise
        _icl_data_source = literacy_techniques_data
        if _use_compressed_icl:
            _compressed = self.load_literacy_techniques_compressed()
            if _compressed:
                _icl_data_source = _compressed
            else:
                logger.warning("[ICL-CAP] Compressed ICL not found — falling back to full JSON with cap.")
        if _icl_data_source and _icl_max_examples != 0:
            icl_formatted = self._format_icl_prose_examples_for_injection(
                _icl_data_source,
                max_examples=_icl_max_examples,
                target_language=self.target_language,
            )
            if icl_formatted:
                icl_size_kb = len(icl_formatted.encode('utf-8')) / 1024
                corpus = _icl_data_source.get('real_world_jp_en_corpus', {})
                icl_section = corpus.get('professional_prose_icl_examples', {})
                examples_by_mood = icl_section.get('examples_by_mood', {})
                total_source_examples = sum(len(v.get('examples', [])) for v in examples_by_mood.values())
                total_icl_categories = len(examples_by_mood)
                # Compute actual injected count: min(source, cap) where None cap = all
                actual_injected = (
                    min(total_source_examples, _icl_max_examples)
                    if _icl_max_examples is not None
                    else total_source_examples
                )
                source_label = "compressed" if _use_compressed_icl else "full"
                logger.info(
                    f"Appending professional_prose_icl_examples ({source_label}): "
                    f"{actual_injected}/{total_source_examples} exemplars across {total_icl_categories} categories "
                    f"({icl_size_kb:.1f}KB, cap={_icl_max_examples})"
                )
                _icl_file = "literacy_techniques_compressed.json" if _use_compressed_icl else "literacy_techniques.json"
                final_prompt += (
                    f"\n\n<!-- START MODULE: professional_prose_icl_examples (from {_icl_file}) -->\n"
                    f"{icl_formatted}\n"
                    f"<!-- END MODULE: professional_prose_icl_examples -->\n"
                )
                injected_count += 1

        # Inject formatting_standards.json (Tier 1 - punctuation + Hepburn romanization standards)
        if formatting_standards_data and "formatting_standards.json" in final_prompt:
            formatting_formatted = self._format_formatting_standards_for_injection(formatting_standards_data)
            formatting_size_kb = len(formatting_formatted.encode('utf-8')) / 1024
            category_count = len(formatting_standards_data.get('pattern_categories', {}))

            logger.info(
                f"Injecting formatting_standards.json: {category_count} categories "
                f"({formatting_size_kb:.1f}KB)"
            )
            formatting_injection = (
                "\n<!-- START MODULE: formatting_standards.json -->\n"
                f"{formatting_formatted}\n"
                "<!-- END MODULE: formatting_standards.json -->\n"
            )
            final_prompt = final_prompt.replace("formatting_standards.json", formatting_injection)
            injected_count += 1
        elif formatting_standards_data:
            formatting_formatted = self._format_formatting_standards_for_injection(formatting_standards_data)
            formatting_size_kb = len(formatting_formatted.encode('utf-8')) / 1024
            category_count = len(formatting_standards_data.get('pattern_categories', {}))

            logger.info(
                f"Appending formatting_standards.json (no placeholder found): "
                f"{category_count} categories ({formatting_size_kb:.1f}KB)"
            )
            final_prompt += (
                "\n\n<!-- START MODULE: formatting_standards.json (AUTO-APPENDED) -->\n"
                f"{formatting_formatted}\n"
                "<!-- END MODULE: formatting_standards.json -->\n"
            )
            injected_count += 1

        final_size_kb = len(final_prompt.encode('utf-8')) / 1024
        elapsed = time.time() - start_time
        logger.info(f"Final System Instruction Size: {final_size_kb:.1f}KB ({injected_count} modules injected) - built in {elapsed:.2f}s")

        # ── Token Budget Gate ────────────────────────────────────
        # Gemini 2.5 Pro context window is 1M tokens (~2.5MB text).
        # System instruction should stay well under 400KB to leave room
        # for the JP source text + visual notes + thinking tokens.
        WARN_THRESHOLD_KB = 300
        HARD_CAP_KB = 500
        if final_size_kb > HARD_CAP_KB:
            logger.error(
                f"🚨 SYSTEM INSTRUCTION EXCEEDS HARD CAP: {final_size_kb:.1f}KB > {HARD_CAP_KB}KB. "
                f"Risk of context overflow. Review bible block size, RAG modules, and glossary."
            )
        elif final_size_kb > WARN_THRESHOLD_KB:
            logger.warning(
                f"⚠ System instruction is large: {final_size_kb:.1f}KB > {WARN_THRESHOLD_KB}KB threshold. "
                f"Consider pruning lower-priority RAG modules or glossary terms."
            )

        # Confirm anti-AI-ism modules are active
        if anti_ai_ism_injected:
            logger.info(f"✓ Anti-AI-ism enforcement active: {', '.join(anti_ai_ism_injected)}")
        else:
            logger.warning("⚠ No anti-AI-ism modules injected into system instruction")

        # Inject hard anti-AI-ism policy at TOP (prompt-time enforcement only, no post-healing)
        if anti_ai_ism_data and self.target_language in ['en', 'english']:
            hard_policy = self._format_hard_anti_ai_ism_policy(anti_ai_ism_data, self._semantic_metadata)
            if hard_policy:
                final_prompt = f"<!-- HARD ANTI-AI-ISM POLICY -->\n{hard_policy}\n\n{final_prompt}"
                logger.info("✓ Injected hard anti-AI-ism policy block at TOP of system instruction")
        
        # LEGACY CHARACTER NAME INJECTION DISABLED (v3 Enhanced Schema)
        # Character names are now loaded via character_profiles in semantic_metadata
        # which provides full context (keigo_switch, relationships, speech patterns)
        # instead of just JP→EN name mappings
        # The legacy _character_names dict is no longer used or logged
        
        # ── Phase E: World Setting Directive (TOP-LEVEL RULE) ─────────
        # Injected near the top of the final prompt so the LLM treats it as a
        # binding translation directive for honorifics and name order.
        if self._bible_world_directive:
            final_prompt = f"<!-- WORLD SETTING DIRECTIVE -->\n{self._bible_world_directive}\n\n{final_prompt}"
            logger.info(f"✓ Injected world setting directive at TOP of system instruction")

        # ── Phase E: Series Bible Block (BEFORE glossary) ────────────
        if self._bible_prompt:
            final_prompt += f"\n\n{self._bible_prompt}"
            logger.info(f"✓ Injected Series Bible block ({len(self._bible_prompt)} chars)")

        # Inject glossary into cached system instruction (if available)
        # Phase E: Deduplicate — skip terms already covered by bible block
        if self._glossary:
            if self._bible_glossary_keys:
                # Only emit volume-specific overrides not in bible
                volume_only = {jp: en for jp, en in self._glossary.items()
                               if jp not in self._bible_glossary_keys}
                if volume_only:
                    glossary_text = "\n\n<!-- GLOSSARY — Volume-Specific Overrides (CACHED) -->\n"
                    glossary_text += "Volume-specific terms (supplement the Series Bible above):\n"
                    for jp, en in volume_only.items():
                        glossary_text += f"  {jp} = {en}\n"
                    final_prompt += glossary_text
                    logger.info(f"✓ Injected {len(volume_only)} volume-specific glossary terms "
                                f"(deduplicated {len(self._glossary) - len(volume_only)} bible terms)")
                else:
                    logger.info(f"✓ Glossary fully covered by Series Bible ({len(self._glossary)} terms deduplicated)")
            else:
                glossary_text = "\n\n<!-- GLOSSARY (CACHED) -->\n"
                glossary_text += "Use these established term translations consistently throughout ALL chapters:\n"
                for jp, en in self._glossary.items():
                    glossary_text += f"  {jp} = {en}\n"
                final_prompt += glossary_text
                logger.info(f"✓ Injected {len(self._glossary)} glossary terms into cached system instruction")
        
        # Inject music-industry vocabulary supplement (MEMOIR MODE only)
        # Sourced from vietnamese_grammar_rag_v2.json music_industry_vocabulary category.
        # Loaded by set_book_type() when book_type is memoir/autobiography/biography.
        if self._music_industry_vocab:
            mv_lines = [
                "\n\n<!-- MUSIC_INDUSTRY_VOCABULARY (MEMOIR MODE — CACHED) -->",
                "Domain vocabulary supplement for J-music artist autobiography translation.",
                "For each term: use vn_primary in literary prose; vn_alternative in dialogue/fan context where noted.",
                "register note specifies which form applies in which context.",
                "CRITICAL: Never output Japanese katakana characters in VN prose — always use the VN form.\n",
            ]
            # Group by implied category from id prefix
            categories = {}
            for term in self._music_industry_vocab:
                tid = term.get("id", "")
                # Extract group from id (MUS_STAGE_001 → STAGE, MUS_LABEL_009 → LABEL)
                parts = tid.split("_")
                grp = parts[1] if len(parts) >= 2 else "OTHER"
                # Map to readable group names
                group_map = {
                    "STAGE": "PERFORMANCE", "LIVE": "PERFORMANCE", "ARTIST": "PERFORMANCE",
                    "SINGER": "PERFORMANCE", "DEBUT": "PERFORMANCE", "ANON": "PERFORMANCE",
                    "SOLO": "PERFORMANCE", "VOCAL": "PERFORMANCE",
                    "LABEL": "INDUSTRY", "AGENCY": "INDUSTRY", "PRODUCER": "INDUSTRY",
                    "CONTRACT": "INDUSTRY", "INDIE": "INDUSTRY", "MAINSTREAM": "INDUSTRY",
                    "RECORDING": "PRODUCTION", "MV": "PRODUCTION", "ALBUM": "PRODUCTION",
                    "SINGLE": "PRODUCTION", "RELEASE": "PRODUCTION", "SONGWRITING": "PRODUCTION",
                    "TRACK": "PRODUCTION", "LYRICS": "PRODUCTION", "OST": "PRODUCTION",
                    "COLLAB": "PRODUCTION", "STREAMING": "PRODUCTION",
                    "FAN": "AUDIENCE", "FANBASE": "AUDIENCE", "CHART": "AUDIENCE",
                    "VIRAL": "AUDIENCE", "INTERVIEW": "AUDIENCE",
                    "TOUR": "LIVE_EVENTS", "CONCERT": "LIVE_EVENTS", "FESTIVAL": "LIVE_EVENTS",
                    "ACTIVITIES": "LIVE_EVENTS", "AUDITION": "LIVE_EVENTS",
                    "SONGLIST": "LIVE_EVENTS", "REVENUE": "LIVE_EVENTS",
                    "STAGEFRIGHT": "LIVE_EVENTS", "SOUNDCHECK": "LIVE_EVENTS",
                    "SPOTLIGHT": "LIVE_EVENTS",
                }
                grp_name = group_map.get(grp, grp)
                categories.setdefault(grp_name, []).append(term)

            for grp_name, terms in categories.items():
                mv_lines.append(f"  --- {grp_name} ---")
                for t in terms:
                    primary = t.get("vn_primary", "?")
                    alt = t.get("vn_alternative")
                    reg = t.get("register", "")
                    jp = t.get("jp_term", "?")
                    alt_str = f" | alt: {alt}" if alt else ""
                    mv_lines.append(f"  {jp} → {primary}{alt_str}")
                    if reg:
                        mv_lines.append(f"    register: {reg}")
            final_prompt += "\n".join(mv_lines)
            logger.info(
                f"✓ [MEMOIR] Injected {len(self._music_industry_vocab)} music-industry "
                f"vocabulary terms into cached system instruction"
            )

        # Inject semantic metadata into system instruction (Enhanced v2.1)
        if self._semantic_metadata:
            semantic_injection = self._format_semantic_metadata(self._semantic_metadata)
            # Replace placeholder in master prompt
            if "SEMANTIC_METADATA_PLACEHOLDER" in final_prompt:
                final_prompt = final_prompt.replace("SEMANTIC_METADATA_PLACEHOLDER", semantic_injection)
                logger.info(f"✓ Injected semantic metadata ({len(semantic_injection)} chars)")
            else:
                # Fallback: append if placeholder not found
                final_prompt += f"\n\n<!-- SEMANTIC METADATA (Enhanced v2.1) -->\n{semantic_injection}\n"
                logger.warning("⚠ SEMANTIC_METADATA_PLACEHOLDER not found, appended to end")

        # Inject Koji Fox voice + arc directives (Phase 1-2 expansion)
        if self._voice_directive or self._arc_directive:
            koji_fox_block = "\n<!-- KOJI FOX VOICE DIRECTIVES -->"
            if self._voice_directive:
                koji_fox_block += f"\n{self._voice_directive}"
            if self._arc_directive:
                koji_fox_block += f"\n{self._arc_directive}"
            final_prompt += koji_fox_block
            logger.info(f"✓ Injected Koji Fox voice directives ({len(koji_fox_block)} chars)")

        # ── ECR Volume-Level Directives ───────────────────────────────────────
        # Injected once per volume at prompt-build time. Covers four JSON fields
        # populated by Phase 1.5 (schema_autoupdate):
        #   culturally_loaded_terms    → hard CLT retention rules (preserve/transcreate)
        #   author_signature_patterns  → prose structure preservation mandates
        #   character_voice_fingerprints → all-character voice directive table
        #   signature_phrases          → character-defining phrase consistency table
        _ecr_block = self._format_ecr_directive_block()
        if _ecr_block:
            final_prompt += f"\n\n<!-- ECR VOLUME DIRECTIVES -->\n{_ecr_block}\n<!-- END ECR VOLUME DIRECTIVES -->"
            logger.info(
                f"✓ [ECR] Injected volume directives block ({len(_ecr_block)} chars): "
                f"{len(self._ecr_clt)} CLT terms, {len(self._ecr_cvf_list)} CVF fingerprints, "
                f"{len(self._ecr_sig_phrases)} sig phrases, ASP={'yes' if self._ecr_asp else 'no'}"
            )

        # ── Gap 8.2: POV Character Fingerprint Override (batch-safe) ──────────
        # When a chapter's narration belongs to a fingerprinted POV character,
        # inject a high-priority override block. This fires at prompt-construction
        # time and requires no tool_use calls, making it fully compatible with
        # batch+thinking mode.
        #
        # Two sub-cases:
        #   A) _pov_segments is set → multi-POV intra-chapter hot-switch
        #      (Gap 8.2 extension): each segment gets its own fingerprint block
        #      with explicit transition guidance.
        #   B) _pov_character_name is set (and _pov_segments is empty) →
        #      single whole-chapter POV (original Gap 8.2).
        if self._pov_segments:
            # ── Case A: Multi-POV hot-switch directive ────────────────────────
            all_names = [s["character"] for s in self._pov_segments]
            pov_lines = [
                f"\n<!-- MULTI-POV HOT-SWITCH FINGERPRINT OVERRIDE (Gap 8.2 ext.) -->",
                f"## ⚠ INTRA-CHAPTER POV HOT-SWITCH: {len(self._pov_segments)} NARRATORS",
                f"",
                f"This chapter contains **{len(self._pov_segments)} distinct first-person POV",
                f"segments**, each belonging to a different character:",
                f"**{' → '.join(all_names)}**",
                f"",
                f"Switch voice fingerprint precisely at each segment boundary.",
                f"Carry NO vocal residue from one segment's narrator into the next.",
                f"",
            ]
            for i, seg in enumerate(self._pov_segments, start=1):
                char = seg["character"]
                fp = seg["fingerprint"]
                archetype = fp.get("archetype", "unknown")
                contraction_rate = fp.get("contraction_rate", 0.5)
                forbidden_vocab = fp.get("forbidden_vocabulary", [])
                verbal_tics = fp.get("verbal_tics", [])
                sentence_bias = fp.get("sentence_length_bias", "medium")
                signature_phrases = fp.get("signature_phrases", [])
                description = seg.get("description") or f"Segment {i}"
                # Build line-range hint if available
                start_l = seg.get("start_line")
                end_l = seg.get("end_line")
                range_hint = (
                    f" (JP lines {start_l}–{end_l})"
                    if start_l is not None and end_l is not None
                    else ""
                )
                pov_lines += [
                    f"### Segment {i} — {char}{range_hint}: {description}",
                    f"",
                    f"- **Archetype**: {archetype}",
                    f"- **Contraction ceiling**: {contraction_rate:.0%} — "
                    f"default register is {'formal/expanded' if contraction_rate < 0.6 else 'natural/colloquial'}",
                    f"- **Sentence length bias**: {sentence_bias}",
                ]
                if verbal_tics:
                    pov_lines.append(f"- **Verbal tics**: {'; '.join(verbal_tics)}")
                if forbidden_vocab:
                    pov_lines.append(f"- **Forbidden vocabulary**: {', '.join(forbidden_vocab)}")
                if signature_phrases:
                    pov_lines.append(f"- **Signature phrases**: {', '.join(signature_phrases)}")
                pov_lines.append(f"")
            pov_lines += [
                f"Each narrator's contraction rate, verbal tics, and vocabulary are independent.",
                f"Apply the segment fingerprint above for every narration sentence and internal",
                f"monologue in that segment. Do not blend or average across segments.",
                f"<!-- END MULTI-POV HOT-SWITCH FINGERPRINT OVERRIDE -->",
            ]
            pov_block = "\n".join(pov_lines)
            final_prompt += pov_block
            logger.info(
                f"✓ [POV SEGMENTS] Injected {len(self._pov_segments)}-segment multi-POV directive "
                f"({' → '.join(all_names)})"
            )

        elif self._pov_character_name and self._pov_fingerprint:
            # ── Case B: Single whole-chapter POV ──────────────────────────────
            fp = self._pov_fingerprint
            archetype = fp.get("archetype", "unknown")
            contraction_rate = fp.get("contraction_rate", 0.5)
            forbidden_vocab = fp.get("forbidden_vocabulary", [])
            verbal_tics = fp.get("verbal_tics", [])
            sentence_bias = fp.get("sentence_length_bias", "medium")
            signature_phrases = fp.get("signature_phrases", [])

            pov_lines = [
                f"\n<!-- POV CHARACTER FINGERPRINT OVERRIDE (Gap 8.2) -->",
                f"## ⚠ POV CHARACTER: {self._pov_character_name}",
                f"",
                f"This chapter's narration and internal monologue belong to "
                f"**{self._pov_character_name}**.",
                f"Apply the following voice fingerprint exclusively for all narration and",
                f"internal monologue in this chapter:",
                f"",
                f"- **Archetype**: {archetype}",
                f"- **Contraction ceiling**: {contraction_rate:.0%} — contractions permitted",
                f"  only at genuine emotional breakthrough moments; default register is",
                f"  expanded/formal (e.g. 'that is not my concern', 'I do not know').",
                f"- **Sentence length bias**: {sentence_bias}",
            ]
            if verbal_tics:
                pov_lines.append(
                    f"- **Verbal tics**: {'; '.join(verbal_tics)}"
                )
            if forbidden_vocab:
                pov_lines.append(
                    f"- **Forbidden vocabulary**: {', '.join(forbidden_vocab)}"
                )
            if signature_phrases:
                pov_lines.append(
                    f"- **Signature phrases**: {', '.join(signature_phrases)}"
                )
            pov_lines += [
                f"",
                f"Do NOT infer the narrator from pronouns alone. Follow the scene-plan POV",
                f"assignment and surrounding narrative ownership cues first.",
                f"Do NOT apply any other character's narration register ({self.target_language})",
                f"to this chapter. Other characters' contraction rates, verbal tics, and",
                f"vocabulary patterns are suspended for narration unless a later POV switch is",
                f"explicitly declared.",
                f"<!-- END POV CHARACTER FINGERPRINT OVERRIDE -->",
            ]
            pov_block = "\n".join(pov_lines)
            final_prompt += pov_block
            logger.info(
                f"✓ [POV OVERRIDE] Injected fingerprint block for {self._pov_character_name} "
                f"(archetype={archetype}, contraction_ceiling={contraction_rate:.0%})"
            )

        if self._secondary_fingerprints:
            secondary_lines = [
                "\n<!-- SECONDARY CHARACTER VOICE ANCHORS -->",
                "## ⚠ SECONDARY CHARACTER VOICE ANCHORS",
                "",
                "REGISTER ISOLATION: The scene plan's dialogue_register describes the",
                "ambient narrator/scene tone only. Characters with explicit fingerprints",
                "must keep their own register, contraction ceiling, and vocabulary patterns",
                "even when the scene tag suggests a different ambient mood.",
                "",
            ]
            for anchor in self._secondary_fingerprints:
                character_name = anchor.get("character", "")
                fp = anchor.get("fingerprint", {}) or {}
                archetype = fp.get("archetype", "unknown")
                contraction_rate = fp.get("contraction_rate", 0.5)
                sentence_bias = fp.get("sentence_length_bias", "medium")
                signature_phrases = fp.get("signature_phrases", [])
                secondary_lines += [
                    f"### {character_name}",
                    f"- **Archetype**: {archetype}",
                    f"- **Contraction ceiling**: {contraction_rate:.0%}",
                    f"- **Sentence length bias**: {sentence_bias}",
                ]
                verbal_tics = fp.get("verbal_tics", [])
                if verbal_tics:
                    secondary_lines.append(f"- **Verbal tics**: {'; '.join(verbal_tics)}")
                forbidden_vocab = fp.get("forbidden_vocabulary", [])
                if forbidden_vocab:
                    secondary_lines.append(f"- **Forbidden vocabulary**: {', '.join(forbidden_vocab)}")
                if signature_phrases:
                    secondary_lines.append(f"- **Signature phrases**: {', '.join(signature_phrases)}")
                secondary_lines.append("")
            secondary_lines.append("<!-- END SECONDARY CHARACTER VOICE ANCHORS -->")
            final_prompt += "\n".join(secondary_lines)
            logger.info(
                "✓ [SECONDARY FP] Injected %d secondary voice anchor(s)",
                len(self._secondary_fingerprints),
            )

        if self._inline_afterword_override:
            marker = str(self._inline_afterword_override.get("marker", "あとがき") or "あとがき")
            source = str(self._inline_afterword_override.get("source", "scene_plan") or "scene_plan")
            description = str(self._inline_afterword_override.get("description", "") or "").strip()
            start_line = self._inline_afterword_override.get("start_line")
            end_line = self._inline_afterword_override.get("end_line")
            if start_line is not None and end_line is not None:
                range_hint = f"JP lines {start_line}–{end_line}"
            elif start_line is not None:
                range_hint = f"JP line {start_line}+"
            else:
                range_hint = "JP range unspecified"

            inline_lines = [
                "\n<!-- INLINE AFTERWORD SEGMENT OVERRIDE -->",
                "## ⚠ INLINE AFTERWORD MODE (あとがき SEGMENT)",
                "",
                f"Detected marker: **{marker}** ({source}; {range_hint}).",
            ]
            if description:
                inline_lines.append(f"Segment note: {description}")
            inline_lines += [
                "",
                "When narration enters this afterword/author-note segment, override normal chapter constraints:",
                "- **Contraction target**: 95% (highly natural, spoken-author cadence)",
                "- **Tone**: warm, informative, gratitude-forward; clear acknowledgements and updates",
                "- **Constraint override**: suspend EPS-band voice limits and character-fingerprint narration constraints",
                "- **Validator override**: treat this segment as author note (Koji Fox / voice consistency constraints bypassed)",
                "Outside the afterword segment, continue normal chapter translation behavior.",
                "<!-- END INLINE AFTERWORD SEGMENT OVERRIDE -->",
            ]
            final_prompt += "\n".join(inline_lines)
            logger.info("✓ [INLINE AFTERWORD] Injected inline afterword override block")

        # Inject style guide into system instruction (EXPERIMENTAL - VN all genres / EN memoir only)
        _autobio_slot = (
            '<JSON id="AUTOBIOGRAPHY_MEMOIR_EN" '
            'condition="genre_or_book_type=memoir|autobiography">'
            'autobiography_memoir_en.json</JSON>'
        )
        if self._style_guide:
            style_guide_injection = self._format_style_guide(self._style_guide)
            _lang_label = "Vietnamese" if self.target_language in ['vi', 'vn'] else "English"
            _comment_tag = f"<!-- {_lang_label.upper()} STYLE GUIDE (Experimental) -->"
            # Replace placeholder in master prompt
            if "STYLE_GUIDE_PLACEHOLDER" in final_prompt:
                final_prompt = final_prompt.replace("STYLE_GUIDE_PLACEHOLDER", style_guide_injection)
                logger.info(f"✓ [EXPERIMENTAL] Injected {_lang_label} style guide ({len(style_guide_injection)} chars)")
            elif self.target_language in ['en', 'english'] and _autobio_slot in final_prompt:
                final_prompt = final_prompt.replace(_autobio_slot, style_guide_injection)
                logger.info(
                    f"✓ [EXPERIMENTAL] Injected {_lang_label} style guide via "
                    "autobiography_memoir_en.json Tier-1 slot "
                    f"({len(style_guide_injection)} chars)"
                )
            else:
                # Fallback: append if placeholder not found
                final_prompt += f"\n\n{_comment_tag}\n{style_guide_injection}\n"
                logger.info(f"✓ [EXPERIMENTAL] {_lang_label} style guide appended ({len(style_guide_injection)} chars)")

        # Cleanup unresolved EN memoir Tier-1 slot so filename tokens never leak into prompt text.
        if _autobio_slot in final_prompt:
            final_prompt = final_prompt.replace(_autobio_slot, "")
            logger.debug("Removed unresolved autobiography_memoir_en Tier-1 slot (style guide not injected)")

        # NOTE: Anthropic Thinking Discipline was previously injected here.
        # Moved to _build_user_prompt() in chapter_processor.py because the system
        # instruction is replaced by cached blocks when caching is active — meaning
        # this injection was silently dropped on every cached chapter call.
        # The user turn is always sent fresh, so that's the correct injection point.

        return final_prompt

    def build_retrospective_anchor_block(self, retrospective_text: str) -> str:
        """
        Wrap a retrospective arc prompt in the standard module comment block.

        Args:
            retrospective_text: Output of ContextManager.get_retrospective_arc_prompt().

        Returns:
            Formatted block ready for injection into system prompt or user prompt.
            Returns "" if retrospective_text is empty.
        """
        if not retrospective_text or not retrospective_text.strip():
            return ""
        return (
            "\n<!-- START MODULE: retrospective_pov_anchor -->\n"
            f"{retrospective_text.strip()}\n"
            "<!-- END MODULE: retrospective_pov_anchor -->\n"
        )

    def _format_ecr_directive_block(self) -> str:
        """Build the ECR volume-level hard-directive block for system instruction injection.

        Renders four metadata_en fields as LLM-facing hard directives:
          - culturally_loaded_terms      : per-term retention policy table
          - author_signature_patterns    : prose structure preservation mandates
          - character_voice_fingerprints : voice fingerprint table (all characters)
          - signature_phrases            : character-defining phrase consistency table

        Returns empty string when none of the four fields are populated.
        """
        parts: List[str] = []

        # ── 1. Culturally Loaded Terms ────────────────────────────────────────
        clt = self._ecr_clt
        if isinstance(clt, dict) and clt:
            retain_hard  = [(jp, e) for jp, e in clt.items() if isinstance(e, dict) and e.get("retention_policy") == "preserve_jp"]
            retain_first = [(jp, e) for jp, e in clt.items() if isinstance(e, dict) and e.get("retention_policy") == "preserve_jp_first_use"]
            transcreate  = [(jp, e) for jp, e in clt.items() if isinstance(e, dict) and e.get("retention_policy") == "transcreate"]
            context_dep  = [(jp, e) for jp, e in clt.items() if isinstance(e, dict) and e.get("retention_policy") == "context_dependent"]

            lines = [
                "## CULTURALLY LOADED TERMS — HARD RETENTION RULES",
                "Policies below are BINDING. Violating them is the most critical translation failure.\n",
            ]
            if retain_hard:
                lines.append("### RETAIN JP — use display form directly; NEVER paraphrase or transcreate:")
                for jp, e in retain_hard:
                    display = e.get("display", jp)
                    romaji  = e.get("romaji", "")
                    defn    = e.get("definition", "")
                    ln = f"  {jp}"
                    if display and display != jp:
                        ln += f" \u2192 render as: {display}"
                    if romaji:
                        ln += f" ({romaji})"
                    if defn:
                        ln += f" \u2014 {defn}"
                    lines.append(ln)
                lines.append("")

            if retain_first:
                lines.append("### RETAIN JP — first occurrence: 'display (gloss)', all subsequent uses: JP display only:")
                for jp, e in retain_first:
                    display = e.get("display", jp)
                    romaji  = e.get("romaji", "")
                    defn    = e.get("definition", "")
                    ln = f"  {jp}"
                    if romaji:
                        ln += f" ({romaji})"
                    if defn:
                        ln += f' \u2014 first use: "{display} ({defn})"'
                    lines.append(ln)
                lines.append("")

            if transcreate:
                lines.append("### ALWAYS TRANSCREATE to target-language equivalent:")
                for jp, e in transcreate:
                    en_eq = e.get("en_equivalent") or e.get("display", "")
                    lines.append(f"  {jp}" + (f" \u2192 {en_eq}" if en_eq else ""))
                lines.append("")

            if context_dep:
                lines.append("### CONTEXT-DEPENDENT (keep JP as archetype label; EN as plain descriptor):")
                for jp, e in context_dep:
                    ln = f"  {jp}"
                    info = e.get("definition") or e.get("display", "")
                    if info:
                        ln += f" \u2014 {info}"
                    lines.append(ln)
                lines.append("")

            parts.append("\n".join(lines))

        # ── 2. Author Signature Patterns ─────────────────────────────────────
        asp = self._ecr_asp
        if isinstance(asp, dict) and asp:
            lines = [
                "## AUTHOR SIGNATURE PATTERNS — STRUCTURAL PRESERVATION MANDATE",
                "Replicate these structural patterns exactly. They constitute the author's prose identity.\n",
            ]
            for pat in asp.get("detected_patterns", []):
                if not isinstance(pat, dict):
                    continue
                # Schema uses pattern_id (not pattern_name), preservation_rule (not translation_instruction)
                name  = pat.get("pattern_name") or pat.get("pattern_id", "")
                jp_s  = pat.get("jp_structure", "")
                en_s  = pat.get("en_structure", "")
                rule  = pat.get("preservation_rule") or pat.get("translation_instruction") or pat.get("description", "")
                freq  = pat.get("frequency", "")
                exs   = pat.get("evidence_excerpts") or pat.get("specific_patterns", [])
                lines.append(f"### {name}" if name else "### (unnamed pattern)")
                if jp_s:
                    lines.append(f"  JP structure: {jp_s}")
                if en_s:
                    lines.append(f"  EN structure: {en_s}")
                if rule:
                    lines.append(f"  Rule: {rule}")
                if freq:
                    lines.append(f"  Frequency: {freq}")
                if exs:
                    lines.append(f"  Evidence: {'; '.join(str(x) for x in exs[:2])}")
                lines.append("")

            refs = asp.get("literary_references", [])
            if refs:
                lines.append("Literary references shaping author's stylistic DNA:")
                for ref in refs[:5]:
                    if isinstance(ref, dict):
                        title = ref.get("title", "")
                        inf   = ref.get("influence", "")
                        lines.append(f"  \u2022 {title}: {inf}" if title else f"  \u2022 {inf}")
                    elif isinstance(ref, str):
                        lines.append(f"  \u2022 {ref}")
                lines.append("")

            parts.append("\n".join(lines))

        # ── 3. Character Voice Fingerprints (all characters) ─────────────────
        cvf = self._ecr_cvf_list
        if cvf:
            lines = [
                "## CHARACTER VOICE FINGERPRINTS — ALL CHARACTERS",
                "Apply the matching fingerprint for each character's dialogue and internal monologue.\n",
            ]
            for fp in cvf:
                if not isinstance(fp, dict):
                    continue
                name     = fp.get("canonical_name_en") or fp.get("character_en", "Unknown")
                archetype = fp.get("archetype", "")
                cr       = fp.get("contraction_rate")
                forbidden = fp.get("forbidden_vocabulary", [])
                preferred = fp.get("preferred_vocabulary", [])
                tics     = fp.get("verbal_tics", [])
                slen     = fp.get("sentence_length_bias", "")

                lines.append(f"### {name} [{archetype}]" if archetype else f"### {name}")
                if cr is not None:
                    register = "formal/expanded" if cr < 0.5 else ("neutral" if cr < 0.7 else "colloquial")
                    lines.append(f"  Contractions: {cr:.0%} ceiling \u2014 default register: {register}")
                if slen:
                    lines.append(f"  Sentence length: {slen}")
                if forbidden:
                    lines.append(f"  FORBIDDEN: {', '.join(str(x) for x in forbidden[:5])}")
                if preferred:
                    lines.append(f"  Preferred: {', '.join(str(x) for x in preferred[:5])}")
                if tics:
                    lines.append(f"  Verbal tics: {', '.join(str(x) for x in tics[:4])}")
                lines.append("")

            parts.append("\n".join(lines))

        # ── 4. Signature Phrases ─────────────────────────────────────────────
        sig = self._ecr_sig_phrases
        if sig:
            lines = [
                "## SIGNATURE PHRASES — CONSISTENT TRANSLATION REQUIRED",
                "These phrases are character-defining. Translate each one as specified every time.\n",
            ]
            by_char: Dict[str, list] = {}
            for entry in sig:
                if not isinstance(entry, dict):
                    continue
                char = entry.get("character_en", "Unknown")
                by_char.setdefault(char, []).append(entry)

            for char, phrases in by_char.items():
                lines.append(f"  [{char}]")
                for p in phrases:
                    jp    = p.get("phrase_jp", "")
                    en    = p.get("phrase_en", "")
                    freq  = p.get("frequency", "")
                    notes = p.get("translation_notes", "")
                    ln    = f"    {jp} \u2192 {en}"
                    if freq:
                        ln += f" [{freq}]"
                    lines.append(ln)
                    if notes:
                        lines.append(f"      Note: {notes}")
                lines.append("")

            parts.append("\n".join(lines))

        return "\n\n".join(parts)

    def _format_semantic_metadata(self, metadata: Dict[str, Any]) -> str:
        """
        Format semantic metadata for prompt injection.
        
        Supports both Enhanced v2.1 schema AND Legacy V2 schema (after transformation).
        
        Formats:
        - Character profiles with pronouns/relationships
        - Dialogue patterns with speech fingerprints
        - Scene contexts with formality guidance
        - Emotional pronoun shifts state machines
        - Translation guidelines priority system
        """
        if not isinstance(metadata, dict):
            logger.warning(
                f"Skipping semantic metadata injection due to invalid type: {type(metadata).__name__}"
            )
            return ""

        lines = []
        
        # 1. CHARACTER PROFILES
        characters = metadata.get('characters', [])
        if not isinstance(characters, list):
            characters = []
        if characters:
            lines.append("=== CHARACTER PROFILES (Full Semantic Data) ===\n")
            for char in characters:
                if not isinstance(char, dict):
                    continue
                # Handle both v2.1 format and transformed legacy format
                name_display = char.get('name_kanji') or char.get('name_en', 'Unknown')
                name_target = char.get('name_vn') or char.get('name_en', 'Unknown')
                
                # Include nickname in display if available
                nickname = char.get('nickname', '')
                if nickname:
                    name_target = f"{name_target} ({nickname})"
                
                lines.append(f"【{name_display} → {name_target}】")
                lines.append(f"  Role: {char.get('role', 'N/A')}")
                lines.append(f"  Gender: {char.get('gender', 'N/A')}, Age: {char.get('age', 'N/A')}")
                
                # Origin
                origin = char.get('origin', '')
                if origin:
                    lines.append(f"  Origin: {origin}")
                
                # Pronouns (handle both dict and string formats)
                pronouns = char.get('pronouns', {})
                if pronouns:
                    if isinstance(pronouns, dict):
                        pron_parts = [f"{k}: {v}" for k, v in pronouns.items()]
                        lines.append(f"  Pronouns: {', '.join(pron_parts)}")
                    else:
                        lines.append(f"  Pronouns: {pronouns}")
                
                # Keigo Switch / Register Shifts (PHASE 0 — PREVIOUSLY INVISIBLE)
                keigo = char.get('keigo_switch', {})
                if keigo and isinstance(keigo, dict):
                    speaking_to = keigo.get('speaking_to', {})
                    if speaking_to:
                        lines.append(f"  Register Shifts:")
                        contraction_data = char.get('contraction_rate', {})
                        contraction_speaking = contraction_data.get('speaking_to', {}) if isinstance(contraction_data, dict) else {}
                        for target, register in list(speaking_to.items())[:10]:
                            cr_info = ""
                            if target in contraction_speaking:
                                cr_info = f" (contraction: {contraction_speaking[target]})"
                            lines.append(f"    → {target}: {register}{cr_info}")
                    # Narration/internal thoughts register
                    narration = keigo.get('narration', '')
                    thoughts = keigo.get('internal_thoughts', '')
                    if narration or thoughts:
                        extras = []
                        if narration:
                            extras.append(f"narration={narration}")
                        if thoughts:
                            extras.append(f"thoughts={thoughts}")
                        lines.append(f"  Base Register: {', '.join(extras)}")
                
                # Contraction Rate baseline (if keigo not shown, show standalone)
                contraction = char.get('contraction_rate', {})
                if contraction and isinstance(contraction, dict) and not keigo:
                    baseline = contraction.get('baseline', '')
                    if baseline:
                        lines.append(f"  Contraction Rate: {baseline}")
                    cr_speaking = contraction.get('speaking_to', {})
                    if cr_speaking:
                        lines.append(f"  Per-Target Contraction:")
                        for target, rate in list(cr_speaking.items())[:8]:
                            lines.append(f"    → {target}: {rate}")
                
                # How Character Refers To Others (PHASE 0 — PREVIOUSLY INVISIBLE)
                refers = char.get('how_refers_to_others', {})
                if refers and isinstance(refers, dict):
                    lines.append(f"  Refers To Others:")
                    for jp_target, ref_pattern in list(refers.items())[:10]:
                        lines.append(f"    → {ref_pattern}")
                
                # PAIR_ID Relationships (PHASE 0 — PREVIOUSLY INVISIBLE)
                relationships = char.get('relationships', {})
                if relationships and isinstance(relationships, dict):
                    # Check for structured PAIR_ID format (not legacy {'context': ...})
                    if 'context' not in relationships:
                        lines.append(f"  Key Relationships:")
                        for target, rel_data in list(relationships.items())[:8]:
                            if isinstance(rel_data, dict):
                                rtype = rel_data.get('type', '')
                                score = rel_data.get('pair_id', rel_data.get('rtas_score', ''))
                                rnotes = rel_data.get('notes', '')
                                score_str = f" ({score})" if score else ""
                                notes_str = f" — {rnotes}" if rnotes else ""
                                lines.append(f"    → {target}: {rtype}{score_str}{notes_str}")
                            else:
                                lines.append(f"    → {target}: {rel_data}")
                    else:
                        # Legacy format
                        lines.append(f"  Relationships: {relationships.get('context', '')}")
                
                # Notes (includes transformed personality/appearance from legacy)
                if 'notes' in char:
                    lines.append(f"  Notes: {char['notes']}")
                
                # Character arc (preserved from legacy transformation)
                if 'character_arc' in char:
                    lines.append(f"  Character Arc: {char['character_arc']}")
                
                lines.append("")
        
        # 2. DIALOGUE PATTERNS
        dialogue_patterns = metadata.get('dialogue_patterns', {})
        if not isinstance(dialogue_patterns, dict):
            dialogue_patterns = {}
        if dialogue_patterns:
            lines.append("\n=== DIALOGUE PATTERNS (Speech Fingerprints) ===\n")
            for char_name, pattern in dialogue_patterns.items():
                if not isinstance(pattern, dict):
                    lines.append(f"【{char_name}】")
                    lines.append(f"  Speech Style: {pattern}")
                    lines.append("")
                    continue
                lines.append(f"【{char_name}】")
                lines.append(f"  Speech Style: {pattern.get('speech_style', 'N/A')}")
                
                # Common phrases
                phrases = pattern.get('common_phrases', [])
                if phrases:
                    lines.append(f"  Common Phrases: {', '.join(str(p) for p in phrases[:5])}")  # Limit to 5 for brevity
                
                # Sentence endings
                if 'sentence_endings' in pattern:
                    lines.append(f"  Sentence Endings: {pattern['sentence_endings']}")
                
                # Tone shifts (most important)
                tone_shifts = pattern.get('tone_shifts', {})
                if tone_shifts:
                    lines.append(f"  Tone Shifts:")
                    for context, shift_desc in list(tone_shifts.items())[:3]:  # Top 3 contexts
                        lines.append(f"    {context}: {shift_desc}")
                
                lines.append("")
        
        # 3. SCENE CONTEXTS
        scene_contexts = metadata.get('scene_contexts', {})
        if not isinstance(scene_contexts, dict):
            scene_contexts = {}
        if scene_contexts:
            lines.append("\n=== SCENE CONTEXTS (Location-Based Guidance) ===\n")
            for location, context in scene_contexts.items():
                if not isinstance(context, dict):
                    lines.append(f"【{location}】")
                    lines.append(f"  Context: {context}")
                    lines.append("")
                    continue
                lines.append(f"【{location}】")
                lines.append(f"  Privacy: {context.get('privacy', 'N/A')}, Formality: {context.get('formality', 'N/A')}")
                if 'pronoun_guidance' in context:
                    lines.append(f"  Pronoun Guidance: {context['pronoun_guidance']}")
                if 'special_note' in context:
                    lines.append(f"  ⚠ Special Note: {context['special_note']}")
                lines.append("")
        
        # 4. EMOTIONAL PRONOUN SHIFTS
        emotional_shifts = metadata.get('emotional_pronoun_shifts', {})
        if not isinstance(emotional_shifts, dict):
            emotional_shifts = {}
        if emotional_shifts:
            lines.append("\n=== EMOTIONAL PRONOUN SHIFTS (State Machines) ===\n")
            for char_states_key, states_data in emotional_shifts.items():
                lines.append(f"【{char_states_key}】")
                if isinstance(states_data, dict):
                    for state_name, state_info in list(states_data.items())[:3]:  # Top 3 states for brevity
                        lines.append(f"  State: {state_name}")
                        if isinstance(state_info, dict):
                            if 'self' in state_info:
                                lines.append(f"    Self: {state_info['self']}")
                            if 'triggers' in state_info:
                                triggers = state_info['triggers']
                                triggers_str = ', '.join(str(t) for t in triggers[:3]) if isinstance(triggers, list) else str(triggers)
                                lines.append(f"    Triggers: {triggers_str}")
                lines.append("")
        
        # 5. TRANSLATION GUIDELINES (Priority System) - Handles both v2.1 and transformed legacy
        guidelines = metadata.get('translation_guidelines', {})
        if not isinstance(guidelines, dict):
            guidelines = {}
        if guidelines:
            lines.append("\n=== TRANSLATION GUIDELINES (Priority System) ===\n")
            
            # v2.1 format: pronoun_selection_priority
            priority = guidelines.get('pronoun_selection_priority', [])
            if priority:
                lines.append("Pronoun Selection Priority (Highest → Lowest):")
                for i, step in enumerate(priority, 1):
                    lines.append(f"  {i}. {step}")
            
            # Legacy transformed: character_exceptions (from british_speech_exception)
            char_exceptions = guidelines.get('character_exceptions', {})
            if not isinstance(char_exceptions, dict):
                char_exceptions = {}
            if char_exceptions:
                lines.append("\n⚠ Character Speech Exceptions:")
                for char_name, exception in char_exceptions.items():
                    if not isinstance(exception, dict):
                        lines.append(f"  【{char_name}】")
                        lines.append(f"    Exception: {exception}")
                        continue
                    lines.append(f"  【{char_name}】")
                    allowed = exception.get('allowed_patterns', [])
                    if allowed:
                        lines.append(f"    Allowed patterns: {', '.join(allowed)}")
                    if 'rationale' in exception:
                        lines.append(f"    Rationale: {exception['rationale']}")
            
            # Legacy transformed: forbidden_patterns
            forbidden = guidelines.get('forbidden_patterns', [])
            if forbidden:
                lines.append(f"\n❌ Forbidden Patterns: {', '.join(forbidden)}")
            
            # Legacy transformed: preferred_alternatives
            alternatives = guidelines.get('preferred_alternatives', {})
            if not isinstance(alternatives, dict):
                alternatives = {}
            if alternatives:
                lines.append("\n✓ Preferred Alternatives:")
                for forbidden_word, replacements in alternatives.items():
                    lines.append(f"  {forbidden_word} → {replacements}")
            
            # Legacy transformed: target_metrics
            metrics = guidelines.get('target_metrics', {})
            if not isinstance(metrics, dict):
                metrics = {}
            if metrics:
                lines.append("\n📊 Target Metrics:")
                for metric_name, target_val in metrics.items():
                    lines.append(f"  {metric_name}: {target_val}")
            
            # Legacy transformed: narrator_voice
            narrator = guidelines.get('narrator_voice', '')
            if narrator:
                lines.append(f"\n🎭 Narrator Voice: {narrator}")
            
            # Legacy transformed: dialogue_rules
            dialogue_rules = guidelines.get('dialogue_rules', {})
            if not isinstance(dialogue_rules, dict):
                dialogue_rules = {}
            if dialogue_rules:
                lines.append("\n💬 Dialogue Rules (per character):")
                for char_name, rule in dialogue_rules.items():
                    lines.append(f"  {char_name}: {rule}")
            
            # Legacy transformed: naming_conventions
            naming = guidelines.get('naming_conventions', {})
            if not isinstance(naming, dict):
                naming = {}
            if naming:
                lines.append("\n📛 Naming Conventions:")
                for category, info in naming.items():
                    if isinstance(info, dict):
                        order = info.get('order', '')
                        chars = info.get('characters', [])
                        if order and chars:
                            lines.append(f"  {category}: {order} ({', '.join(chars[:3])}...)")
                    else:
                        lines.append(f"  {category}: {info}")
            
            # Legacy transformed: volume_context
            volume_ctx = guidelines.get('volume_context', {})
            if volume_ctx:
                lines.append("\n📖 Volume-Specific Context:")
                if isinstance(volume_ctx, dict):
                    for key, val in volume_ctx.items():
                        lines.append(f"  {key}: {val}")
                else:
                    lines.append(f"  {volume_ctx}")
            
            # v2.1 format: consistency_rules
            consistency = guidelines.get('consistency_rules', {})
            if not isinstance(consistency, dict):
                consistency = {}
            if consistency:
                lines.append("\nConsistency Rules:")
                for rule_key, rule_desc in list(consistency.items())[:3]:
                    lines.append(f"  - {rule_key}: {rule_desc}")
            
            # v2.1 format: quality_markers
            quality = guidelines.get('quality_markers', {})
            if not isinstance(quality, dict):
                quality = {}
            if 'good_translation' in quality:
                lines.append("\n✓ Good Translation Markers:")
                for marker in quality['good_translation'][:3]:
                    lines.append(f"  - {marker}")
            
            if 'red_flags' in quality:
                lines.append("\n❌ Red Flags:")
                for flag in quality['red_flags'][:3]:
                    lines.append(f"  - {flag}")
        
        return '\n'.join(lines)
    
    def _format_style_guide(self, style_guide: Dict[str, Any]) -> str:
        """
        Format style guide for prompt injection with multi-genre semantic selection (EXPERIMENTAL - Vietnamese only).
        
        Supports two modes:
        1. SINGLE-GENRE: Traditional merged guide (legacy behavior)
        2. MULTI-GENRE: Multiple genre guides with conditional semantic selection
        
        In multi-genre mode, formats genre-specific rules with conditional instructions:
        - "For fantasy scenes, apply these rules..."
        - "For romance scenes, apply these rules..."
        - AI semantically determines which rules to apply based on scene context
        
        Converts JSON style guide into readable prompt instructions focusing on:
        1. Contextual Sino-Vietnamese decision framework
        2. Pronoun evolution system
        3. Forbidden archaic patterns
        4. Genre-specific vocabulary preferences
        
        Args:
            style_guide: Style guide dictionary with metadata and genre sections
            
        Returns:
            Formatted style guide text for prompt injection
        """
        metadata = style_guide.get('_metadata', {})
        mode = metadata.get('mode', 'single-genre')
        genres_loaded = metadata.get('genres_loaded', [])

        _is_vn = self.target_language in ['vi', 'vn']
        if _is_vn:
            lines = ["# VIETNAMESE TRANSLATION STYLE GUIDE (Experimental)\n"]
            lines.append("## CRITICAL: This style guide addresses two core Vietnamese translation challenges:\n")
            lines.append("## 1. PRONOUN SYSTEM - Navigate complex age/gender/familiarity encoding")
            lines.append("## 2. CONTEXTUAL SINO-VIETNAMESE - Choose appropriate vocabulary register\n")
        else:
            lines = ["# ENGLISH TRANSLATION STYLE GUIDE (Experimental)\n"]
            lines.append("## CRITICAL: This style guide enforces quality standards for English translation:\n")
            lines.append("## 1. VOICE FIDELITY - Preserve author's distinct voice; avoid homogenization")
            lines.append("## 2. NATURAL IDIOM - Never carry JP syntax into EN; find the English equivalent\n")
        
        # Mode indicator
        if mode == 'multi-genre':
            lines.append(f"🎭 MULTI-GENRE SEMANTIC SELECTION MODE ({len(genres_loaded)} genres loaded)\n")
            lines.append("INSTRUCTION: Analyze each scene's genre and apply appropriate style rules.")
            lines.append("You may combine rules from multiple genres for mixed scenes (e.g., fantasy romance).\n")
        else:
            lines.append("📖 SINGLE-GENRE MODE\n")
        
        # Extract base guide for universal rules
        base_guide = style_guide.get('base', style_guide)  # Fallback to root for single-genre mode
        
        # 1. CORE PRINCIPLES (from base guide)
        if 'fundamental_principles' in base_guide:
            lines.append("=== FUNDAMENTAL PRINCIPLES (Apply to ALL genres) ===\n")
            principles = base_guide['fundamental_principles']
            for key, value in principles.items():
                lines.append(f"• {key}: {value}")
            lines.append("")
        
        # 2. CONTEXTUAL SINO-VIETNAMESE (CRITICAL - from base guide)
        vocab_strategy = base_guide.get('vocabulary_strategy', {})
        if vocab_strategy:
            lines.append("=== CONTEXTUAL SINO-VIETNAMESE DECISION FRAMEWORK ===\n")
            
            core_principle = vocab_strategy.get('core_principle', '')
            if core_principle:
                lines.append(f"**{core_principle}**\n")
            
            # Decision framework
            decision_framework = vocab_strategy.get('decision_framework', {})
            if decision_framework:
                lines.append("DECISION TREE:")
                for context_type, rules in decision_framework.items():
                    lines.append(f"\n【{context_type.upper().replace('_', ' ')}】")
                    if 'ratio' in rules:
                        lines.append(f"  Sino-Vietnamese Ratio: {rules['ratio']}")
                    if 'situations' in rules:
                        situations = ', '.join(rules['situations'][:3])
                        lines.append(f"  Applies to: {situations}")
                    if 'examples' in rules:
                        for ex_key, ex_val in list(rules['examples'].items())[:2]:
                            lines.append(f"  {ex_key}: {ex_val}")
            
            # Forbidden patterns (MOST IMPORTANT)
            forbidden = vocab_strategy.get('critical_forbidden_patterns', {})
            if forbidden:
                lines.append("\n❌ CRITICAL FORBIDDEN PATTERNS (NEVER USE):\n")
                for category, data in forbidden.items():
                    if 'wrong' in data and 'correct' in data:
                        wrong_terms = ', '.join(data['wrong'][:5])
                        correct_terms = ', '.join(data['correct'][:5])
                        lines.append(f"  ❌ {category}:")
                        lines.append(f"     WRONG: {wrong_terms}")
                        lines.append(f"     CORRECT: {correct_terms}")
                        if 'explanation' in data:
                            lines.append(f"     Why: {data['explanation']}")
            lines.append("")
        
        # 3. GENRE-SPECIFIC RULES (MULTI-GENRE MODE)
        if mode == 'multi-genre' and genres_loaded:
            lines.append("=== GENRE-SPECIFIC STYLE RULES (Semantic Selection) ===\n")
            lines.append("🎯 INSTRUCTION: Apply the appropriate genre rules based on scene context:\n")
            
            genres_dict = style_guide.get('genres', {})
            for genre_key in genres_loaded:
                genre_guide = genres_dict.get(genre_key, {})
                if not genre_guide:
                    continue
                
                # Format genre header
                genre_name = genre_key.replace('_', ' ').title()
                lines.append(f"\n{'='*60}")
                lines.append(f"🎭 GENRE: {genre_name.upper()}")
                lines.append(f"{'='*60}\n")
                
                # Genre description/when to apply
                genre_desc = self._get_genre_description(genre_key)
                lines.append(f"📌 Apply these rules when: {genre_desc}\n")
                
                # Pronoun system (if genre has specific pronoun rules)
                if 'pronoun_system' in genre_guide:
                    lines.append(f"--- {genre_name} Pronoun Conventions ---\n")
                    pronoun_system = genre_guide['pronoun_system']
                    
                    framework = pronoun_system.get('framework', '')
                    if framework:
                        lines.append(f"Framework: {framework}\n")
                    
                    # Show key pronoun mappings (abbreviated)
                    for role_key, role_data in pronoun_system.items():
                        if role_key in ['framework', 'note', 'critical_fixes']:
                            continue
                        if isinstance(role_data, dict) and 'self_reference' in role_data:
                            _sr = role_data['self_reference']
                            _sr_val = _sr.get('casual', 'N/A') if isinstance(_sr, dict) else _sr
                            lines.append(f"  • {role_key.replace('_', ' ')}: {_sr_val}")
                    lines.append("")
                
                # Dialogue style
                if 'dialogue_style' in genre_guide:
                    lines.append(f"--- {genre_name} Dialogue Style ---\n")
                    dialogue = genre_guide['dialogue_style']
                    
                    if 'teen_speech_patterns' in dialogue:
                        teen_speech = dialogue['teen_speech_patterns']
                        if 'exclamations' in teen_speech:
                            exclamations = teen_speech['exclamations']
                            # Show first 2 emotion types
                            for emotion, examples in list(exclamations.items())[:2]:
                                lines.append(f"  {emotion}: {', '.join(examples[:2])}")
                    lines.append("")
                
                # Vocabulary preferences
                if 'vocabulary_preferences' in genre_guide:
                    lines.append(f"--- {genre_name} Vocabulary ---\n")
                    vocab_prefs = genre_guide['vocabulary_preferences']
                    for category, data in list(vocab_prefs.items())[:3]:  # First 3 categories
                        if isinstance(data, dict) and 'prefer' in data:
                            prefer_terms = ', '.join(data['prefer'][:3])
                            lines.append(f"  • {category}: {prefer_terms}")
                    lines.append("")
            
            lines.append(f"{'='*60}\n")
        
        # 4. PRONOUN SYSTEM (SINGLE-GENRE MODE or fallback)
        elif 'pronoun_system' in style_guide:
            lines.append("=== PRONOUN EVOLUTION SYSTEM (Character Relationship Tracking) ===\n")
            pronoun_system = style_guide['pronoun_system']
            
            framework = pronoun_system.get('framework', '')
            if framework:
                lines.append(f"Framework: {framework}\n")
            
            note = pronoun_system.get('note', '')
            if note:
                lines.append(f"⚠️  {note}\n")
            
            # Protagonist pronoun maps
            for role_key, role_data in pronoun_system.items():
                if role_key in ['framework', 'note', 'critical_fixes']:
                    continue
                if isinstance(role_data, dict) and 'self_reference' in role_data:
                    lines.append(f"\n【{role_key.upper().replace('_', ' ')}】")
                    
                    # Self reference
                    self_ref = role_data.get('self_reference', {})
                    if self_ref:
                        lines.append("  Self Reference:")
                        for context, pronoun in list(self_ref.items())[:3]:
                            lines.append(f"    {context}: {pronoun}")
                    
                    # To other characters (with evolution)
                    for target_key, target_data in role_data.items():
                        if target_key in ['self_reference', 'avoid']:
                            continue
                        if isinstance(target_data, dict) and any('phase' in k for k in target_data.keys()):
                            lines.append(f"\n  To {target_key.replace('to_', '').replace('_', ' ')}:")
                            # Show evolution phases
                            for phase_key, phase_data in target_data.items():
                                if 'phase' in phase_key:
                                    chapters = phase_data.get('chapters', '')
                                    pronouns = phase_data.get('pronouns', '')
                                    note_phase = phase_data.get('note', '')
                                    lines.append(f"    Phase {phase_key.split('_')[1]}: {pronouns} ({chapters})")
                                    if note_phase:
                                        lines.append(f"       → {note_phase}")
            
            # Critical fixes
            critical_fixes = pronoun_system.get('critical_fixes', {})
            if critical_fixes:
                lines.append("\n⚠️  CRITICAL PRONOUN FIXES:\n")
                for fix_key, fix_data in critical_fixes.items():
                    if isinstance(fix_data, dict):
                        wrong = fix_data.get('wrong', '')
                        correct = fix_data.get('correct', '')
                        explanation = fix_data.get('explanation', '')
                        lines.append(f"  • {fix_key}:")
                        lines.append(f"    ❌ WRONG: {wrong}")
                        lines.append(f"    ✓ CORRECT: {correct}")
                        lines.append(f"    Why: {explanation}")
            lines.append("")
        
        # 5. PUBLISHER-SPECIFIC OVERRIDES
        publisher_guide = style_guide.get('publisher', {})
        if publisher_guide:
            lines.append("=== PUBLISHER-SPECIFIC PREFERENCES ===\n")
            lines.append("⚠️  These override genre conventions when specified.\n")
            
            if 'tone' in publisher_guide:
                tone = publisher_guide['tone']
                for key, value in tone.items():
                    lines.append(f"  • {key}: {value}")
            lines.append("")
        
        # 6. DIALOGUE STYLE (single-genre fallback)
        if mode == 'single-genre' and 'dialogue_style' in style_guide:
            lines.append("=== DIALOGUE STYLE (Teen Speech Patterns) ===\n")
            dialogue = style_guide['dialogue_style']
            
            teen_speech = dialogue.get('teen_speech_patterns', {})
            if teen_speech and 'exclamations' in teen_speech:
                exclamations = teen_speech['exclamations']
                lines.append("Teen Exclamations:")
                for emotion, examples in list(exclamations.items())[:4]:
                    lines.append(f"  {emotion}: {', '.join(examples[:3])}")
            
            avoid = teen_speech.get('avoid', [])
            if avoid:
                lines.append(f"\n❌ Avoid in teen dialogue: {', '.join(avoid[:5])}")
            lines.append("")
        
        # 7. QUALITY CHECKLIST
        quality_checklist = base_guide.get('quality_checklist', style_guide.get('quality_checklist', {}))
        if quality_checklist:
            lines.append("=== TRANSLATION QUALITY CHECKLIST ===\n")
            for item, desc in quality_checklist.items():
                lines.append(f"  ✓ {item}: {desc}")
            lines.append("")
        
        lines.append("---")
        if mode == 'multi-genre':
            lines.append("🎯 REMINDER: Semantically analyze each scene and apply appropriate genre rules.")
            lines.append("Mix rules from multiple genres for hybrid scenes (e.g., fantasy battle with romance tension).")
        lines.append("⚠️  EXPERIMENTAL FEATURE - Report issues for style guide refinement")
        
        return '\n'.join(lines)
    
    def _get_genre_description(self, genre_key: str) -> str:
        """
        Get human-readable description of when to apply genre rules.
        
        Args:
            genre_key: Genre identifier (e.g., 'romcom_school_life')
            
        Returns:
            Description of applicable scenes
        """
        descriptions = {
            'romcom_school_life': 'Romance scenes, teen dialogue, school life, slice-of-life moments',
            'fantasy': 'Magic, battles, world-building, fantasy elements, supernatural events',
            'action': 'Fight scenes, chase sequences, intense physical conflicts',
            'mystery': 'Investigation scenes, clue discovery, suspenseful moments',
            'slice_of_life': 'Everyday activities, casual conversations, mundane events',
            'drama': 'Emotional conflicts, serious discussions, character development moments',
            'autobiography_memoir': (
                'ALL prose in this volume — applies to every chapter. '
                'Direct emotional assertion (no epistemic hedging). '
                'First-person introspective narration, retrospective time framing, '
                'inner-monologue patterns, artist/music industry register. '
                'CRITICAL_ANTI_HEDGING_RULE is ABSOLUTE (not optional/scene-conditional).'
            ),
        }
        return descriptions.get(genre_key, f'Scenes matching {genre_key.replace("_", " ")} genre')

    def _format_kanji_for_injection(self, kanji_entries: List[Dict], genre: str = None) -> str: # type: ignore
        """
        Format kanji_difficult.json entries for prompt injection.
        
        Applies genre filtering if specified to reduce token usage.
        
        Args:
            kanji_entries: List of kanji entry dictionaries
            genre: Optional genre for filtering (romcom, fantasy, historical, etc.)
            
        Returns:
            Formatted kanji reference text
        """
        lines = ["# KANJI DIFFICULT REFERENCE (108 entries - production-validated)\n"]
        lines.append("## Usage: Consult for difficult/archaic kanji with readings, Han-Viet, compounds\n")
        
        # Filter by genre if specified
        if genre:
            filtered_entries = [
                e for e in kanji_entries 
                if not e.get('genre_relevance') or genre in e.get('genre_relevance', []) or 'universal' in e.get('genre_relevance', [])
            ]
            if filtered_entries:
                lines.append(f"## Filtered for genre: {genre} ({len(filtered_entries)} relevant entries)\n")
                kanji_entries = filtered_entries
        
        # Prioritize TOP and HIGH priority entries
        kanji_entries_sorted = sorted(
            kanji_entries,
            key=lambda e: (
                0 if e.get('priority') == 'TOP' else
                1 if e.get('priority') == 'HIGH' else
                2 if e.get('priority') == 'MEDIUM' else 3
            )
        )
        
        for entry in kanji_entries_sorted:
            kanji = entry.get('kanji', '')
            on_reading = entry.get('on_reading', '')
            kun_reading = entry.get('kun_reading', '')
            han_viet = entry.get('han_viet', 'N/A')
            meaning = entry.get('meaning', '')
            notes = entry.get('translation_notes', '')
            priority = entry.get('priority', 'LOW')
            
            # Compact format for token efficiency
            line = f"{kanji} [{on_reading}|{kun_reading}] "
            if han_viet != 'N/A':
                line += f"HV:{han_viet} "
            line += f"({meaning})"
            if priority in ['TOP', 'HIGH']:
                line += f" **{priority}**"
            if notes:
                line += f" — {notes[:100]}"  # Truncate long notes
            lines.append(line)
        
        return "\n".join(lines)

    def _format_cjk_prevention_for_injection(self, cjk_data: Dict[str, Any]) -> str:
        """
        Format CJK prevention schema for prompt injection (EN/VN).
        
        Converts JSON schema into concise, actionable instructions for the AI.
        
        Args:
            cjk_data: CJK prevention schema dictionary
            
        Returns:
            Formatted CJK prevention instructions
        """
        lines = ["# CJK CHARACTER PREVENTION PROTOCOL\n"]
        lines.append("## ⚠️ CRITICAL: Zero CJK Tolerance Policy\n")
        lines.append("**ABSOLUTE RULE:** Output must contain ZERO CJK characters (U+4E00–U+9FFF).\n")
        
        # Language-specific warning
        if self.target_language == 'vn':
            lines.append("Vietnamese uses Latin alphabet exclusively. CJK characters = Translation failure.\n")
        elif self.target_language == 'en':
            lines.append("English uses Latin alphabet exclusively. CJK characters = Translation failure.\n")
        
        # Common substitutions - most important section
        substitutions = cjk_data.get('common_substitutions', {})
        
        # Determine language key (vietnamese or english)
        lang_key = 'vietnamese' if self.target_language == 'vn' else 'english'
        lang_name = 'Vietnamese' if self.target_language == 'vn' else 'English'
        
        # Everyday vocabulary (most common)
        everyday = substitutions.get('everyday_vocabulary', {})
        if everyday:
            lines.append(f"\n## Common Phrase Substitutions (Must Use {lang_name})")
            for jp_phrase, data in list(everyday.items())[:15]:  # Top 15 most common
                options = data.get(lang_key, [])
                if options:
                    lines.append(f"- {jp_phrase} → {', '.join(options[:3])}")
        
        # Emotional expressions
        emotions = substitutions.get('emotional_expressions', {})
        if emotions:
            lines.append("\n## Emotional Expressions")
            for jp_word, data in list(emotions.items())[:10]:  # Top 10
                options = data.get(lang_key, [])
                if options:
                    lines.append(f"- {jp_word} → {', '.join(options[:2])}")
        
        # Actions and states
        actions = substitutions.get('actions_and_states', {})
        if actions:
            lines.append("\n## Common Actions/States")
            for jp_word, data in list(actions.items())[:10]:  # Top 10
                options = data.get(lang_key, [])
                if options:
                    lines.append(f"- {jp_word} → {', '.join(options[:2])}")
        
        # Pre-output validation checklist
        lines.append("\n## ✅ MANDATORY PRE-OUTPUT CHECK")
        lines.append("Before submitting EACH sentence:")
        lines.append("1. Scan for ANY CJK characters (漢字) → If found: STOP and translate")
        lines.append(f"2. Verify 100% {lang_name} (Latin alphabet + diacritics only)")
        lines.append(f"3. Confirm all phrases have {lang_name} equivalents (no mixed scripts)")
        lines.append("4. Check quotation marks are standard \"...\" (not 「」 or 《》)")
        
        lines.append(f"\n**Golden Rule:** If {lang_name} reader with ZERO Japanese knowledge can understand 100% → Success.")
        lines.append("**Failure Condition:** Even 1 CJK character = Translation incomplete = Unacceptable quality.\n")
        
        return "\n".join(lines)
    
    def _format_anti_ai_ism_for_injection(self, anti_ai_ism_data: Dict[str, Any]) -> str:
        """
        Format anti-AI-ism pattern library for prompt injection (v3.5).
        
        Converts JSON pattern library into concise enforcement rules with proximity penalties.
        
        Args:
            anti_ai_ism_data: Anti-AI-ism pattern library dictionary
            
        Returns:
            Formatted anti-AI-ism enforcement instructions
        """
        lines = ["# ANTI-AI-ISM PATTERN LIBRARY (v3.5 LTS)\n"]
        lines.append("## ⚠️ CRITICAL: Human-Level Natural Prose Standard\n")
        
        meta = anti_ai_ism_data.get('_meta', {})
        target_density = meta.get('target_density_per_1k_words', 0.02)
        lines.append(f"**TARGET:** <{target_density} AI-ism instances per 1,000 words (Yen Press/J-Novel Club benchmark)\n")
        
        # CRITICAL patterns (max impact)
        critical_section = anti_ai_ism_data.get('CRITICAL', {})
        critical_patterns = critical_section.get('patterns', [])
        if critical_patterns:
            lines.append("\n## 🔴 CRITICAL PATTERNS (Eliminate 100%)")
            lines.append(critical_section.get('description', ''))
            for pattern in critical_patterns[:8]:  # Top 8
                display = pattern.get('display', '')
                fix = pattern.get('fix', '')
                lines.append(f"- **ELIMINATE:** \"{display}\" → {fix}")
        
        # MAJOR patterns (high priority)
        major_section = anti_ai_ism_data.get('MAJOR', {})
        major_categories = major_section.get('categories', {})
        if major_categories:
            lines.append("\n## 🟠 MAJOR PATTERNS (Minimize to <2 per chapter)")
            lines.append(major_section.get('description', ''))
            
            for category_name, category_data in list(major_categories.items())[:4]:  # Top 4 categories
                category_patterns = category_data.get('patterns', [])
                if category_patterns:
                    lines.append(f"\n### {category_name.replace('_', ' ').title()}")
                    for pattern in category_patterns[:3]:  # 3 samples per category
                        display = pattern.get('display', '')
                        fix = pattern.get('fix', '')
                        lines.append(f"- \"{display}\" → {fix}")
        
        # MINOR patterns (awareness level)
        minor_section = anti_ai_ism_data.get('MINOR', {})
        minor_categories = minor_section.get('categories', {})
        if minor_categories:
            lines.append("\n## 🟡 MINOR PATTERNS (Limit to 3-5 per chapter)")
            
            # Just show category names and 1-2 samples
            for category_name, category_data in list(minor_categories.items())[:2]:  # Just 2 categories
                category_patterns = category_data.get('patterns', [])
                if category_patterns:
                    lines.append(f"- {category_name.replace('_', ' ').title()}: Reduce hedge words, process verbs")
        
        # Echo detection rules (from _meta)
        meta_echo = meta.get('echo_detection', {})
        if meta_echo.get('enabled'):
            lines.append("\n## 🔵 ECHO DETECTION (Proximity-Based)")
            lines.append("**RULE:** Avoid repeating phrases within close proximity (triggers escalating penalties)\n")
            lines.append(f"**Default Window:** {meta_echo.get('default_proximity_window', 100)} words")
            
            thresholds = meta_echo.get('proximity_thresholds', {})
            if thresholds:
                lines.append("\n### Proximity Thresholds")
                for severity, distance in thresholds.items():
                    lines.append(f"- {severity.upper()}: within {distance} words")
            
            lines.append("\n**Note:** Many patterns have proximity_penalty fields that trigger when reused too close together.")
        
        # Enforcement checklist
        lines.append("\n## ✅ PRE-OUTPUT VALIDATION")
        lines.append("Before submitting translation:")
        lines.append("1. **Pattern Scan:** Check for CRITICAL/MAJOR AI-ism patterns")
        lines.append("2. **Echo Check:** Scan last 5 sentences for repeated phrases")
        lines.append("3. **Hedge Audit:** Count hedging words (somewhat, rather, quite) - limit to 3-5/chapter")
        lines.append("4. **Process Verbs:** Replace \"started to/began to\" with direct action verbs")
        lines.append("5. **Natural Flow:** Read aloud - does it sound like a human translator wrote it?")
        
        lines.append("\n**Success Metric:** Translation indistinguishable from human professional localizer.")
        lines.append(f"**Failure Condition:** AI-ism density >{target_density}/1k words = Below professional standard.\n")
        
        return "\n".join(lines)

    def _format_hard_anti_ai_ism_policy(
        self,
        anti_ai_ism_data: Dict[str, Any],
        semantic_metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Build a concise, high-priority anti-AI-ism policy block for top-of-prompt injection.

        This is prompt-time enforcement only (self-healing remains disabled by design).
        """
        lines = ["## 🔒 HARD ANTI-AI-ISM OUTPUT POLICY\n"]
        lines.append("Treat this as binding output policy, not optional style advice.\n")

        lines.append("### Non-Negotiable Rules")
        lines.append("1. Output ZERO CRITICAL anti-AI-ism patterns.")
        lines.append("2. Minimize MAJOR anti-AI-ism patterns aggressively.")
        lines.append("3. Rewrite any flagged phrase before final output; do not explain, just fix.")
        lines.append("4. Prefer direct verbs, concrete phrasing, and concise modern rhythm.\n")
        lines.append("5. Keep CRITICAL+MAJOR anti-AI-ism count <= 5 per chapter.\n")

        critical_patterns = anti_ai_ism_data.get('CRITICAL', {}).get('patterns', [])
        if isinstance(critical_patterns, list) and critical_patterns:
            lines.append("### CRITICAL Patterns (Never Output)")
            for p in critical_patterns[:12]:
                if not isinstance(p, dict):
                    continue
                display = p.get('display', '').strip()
                fix = p.get('fix', '').strip()
                if display and fix:
                    lines.append(f"- `{display}` -> {fix}")
                elif display:
                    lines.append(f"- `{display}`")
            lines.append("")

        # Pull project-level overrides from semantic metadata translation guidelines, if available.
        guidelines = {}
        if isinstance(semantic_metadata, dict):
            maybe = semantic_metadata.get('translation_guidelines', {})
            if isinstance(maybe, dict):
                guidelines = maybe

        forbidden = guidelines.get('forbidden_patterns', [])
        if isinstance(forbidden, list) and forbidden:
            lines.append("### Project Forbidden Patterns (Volume Override)")
            for item in forbidden[:20]:
                lines.append(f"- `{item}`")
            lines.append("")

        preferred = guidelines.get('preferred_alternatives', {})
        if isinstance(preferred, dict) and preferred:
            lines.append("### Project Preferred Alternatives")
            for bad, replacement in list(preferred.items())[:12]:
                if isinstance(replacement, list):
                    replacement_str = ", ".join(str(x) for x in replacement[:3])
                else:
                    replacement_str = str(replacement)
                lines.append(f"- `{bad}` -> {replacement_str}")
            lines.append("")

        target_metrics = guidelines.get('target_metrics', {})
        if isinstance(target_metrics, dict) and target_metrics:
            lines.append("### Project Quality Targets")
            for k, v in target_metrics.items():
                lines.append(f"- `{k}`: `{v}`")
            lines.append("")

        lines.append("### Final Self-Check (Before Responding)")
        lines.append("- Scan draft for CRITICAL patterns and remove all.")
        lines.append("- Replace MAJOR filter phrases (e.g., seemed to, started to, couldn't help but) where natural.")
        lines.append("- Keep tone/honorific consistency while de-AI-ising phrasing.\n")

        return "\n".join(lines)

    def _select_diverse_examples(
        self,
        examples: List[Any],
        max_examples: int = 2
    ) -> List[Dict[str, Any]]:
        """
        Select a compact set of non-duplicate examples for few-shot injection.
        """
        selected: List[Dict[str, Any]] = []
        seen = set()
        for ex in examples:
            if not isinstance(ex, dict):
                continue
            key = (
                str(ex.get("jp", "")).strip(),
                str(ex.get("literal", ex.get("incorrect", ex.get("original", "")))).strip(),
                str(ex.get("natural", ex.get("preferred", ex.get("correct", "")))).strip(),
            )
            if key in seen:
                continue
            seen.add(key)
            selected.append(ex)
            if len(selected) >= max_examples:
                break
        return selected
    
    def _format_english_grammar_rag_for_injection(self, grammar_rag_data: Dict[str, Any]) -> str:
        """
        Format English Grammar RAG for prompt injection (Tier 1).
        
        Converts JSON pattern database into natural English idiom guidance.
        Focuses on high-frequency transcreation patterns for maximum impact.
        
        Args:
            grammar_rag_data: English Grammar RAG dictionary with pattern_categories
            
        Returns:
            Formatted natural idiom guidance for prompt injection
        """
        lines = ["# ENGLISH GRAMMAR RAG: NATURAL IDIOM PATTERNS (Tier 1)\n"]
        lines.append("## 📖 JP→EN Transcreation for Natural English Prose\n")
        lines.append("Apply these idiomatic patterns instead of literal translation.\n")
        
        pattern_categories = grammar_rag_data.get('pattern_categories', {})
        
        # HIGH PRIORITY: High-frequency transcreation patterns
        hf_patterns = pattern_categories.get('high_frequency_transcreations', {}).get('patterns', [])
        if hf_patterns:
            lines.append("## 🔥 HIGH-FREQUENCY TRANSCREATIONS (Top Priority)\n")
            lines.append("These patterns appear frequently in Japanese LN. Apply natural English equivalents:\n")
            
            # Sort by corpus_frequency if available
            sorted_patterns = sorted(hf_patterns, key=lambda x: x.get('corpus_frequency', 0), reverse=True)
            
            for pattern in sorted_patterns[:10]:  # Top 10 most frequent, richer examples
                pattern_id = pattern.get('id', '')
                jp_indicators = pattern.get('japanese_indicators', [])
                en_pattern = pattern.get('english_pattern', '')
                examples = pattern.get('examples', [])
                usage_rules = pattern.get('usage_rules', [])
                
                # Format indicators
                jp_display = ', '.join(jp_indicators[:3])
                
                lines.append(f"### {jp_display}")
                lines.append(f"**Pattern:** {en_pattern}")
                
                # Add diverse examples (up to two)
                selected_examples = self._select_diverse_examples(examples, max_examples=2)
                for i, ex in enumerate(selected_examples, 1):
                    lines.append(f"Example {i}:")
                    if ex.get('literal'):
                        lines.append(f"❌ Literal: \"{ex.get('literal', '')}\"")
                    if ex.get('natural'):
                        lines.append(f"✅ Natural: \"{ex.get('natural', '')}\"")
                
                # Add key usage rules
                for rule in usage_rules[:2]:
                    lines.append(f"📌 {rule}")
                
                lines.append("")
        
        # EMOTIONAL INTENSIFIERS
        emotional_patterns = pattern_categories.get('emotional_intensifiers', {}).get('patterns', [])
        if emotional_patterns:
            lines.append("## 💥 EMOTIONAL INTENSIFIERS\n")
            for pattern in emotional_patterns[:5]:
                jp_indicators = pattern.get('japanese_indicators', [])[:2]
                en_pattern = pattern.get('english_pattern', '')
                lines.append(f"- **{', '.join(jp_indicators)}** → {en_pattern}")
            lines.append("")
        
        # CONTRASTIVE COMPARISON
        contrastive_patterns = pattern_categories.get('contrastive_comparison', {}).get('patterns', [])
        if contrastive_patterns:
            lines.append("## ⚖️ CONTRASTIVE COMPARISON\n")
            for pattern in contrastive_patterns[:3]:
                jp_indicators = pattern.get('japanese_indicators', [])[:2]
                en_pattern = pattern.get('english_pattern', '')
                examples = pattern.get('examples', [])
                lines.append(f"- **{', '.join(jp_indicators)}** → \"{en_pattern}\"")
                for ex in self._select_diverse_examples(examples, max_examples=2):
                    natural = ex.get('natural')
                    if natural:
                        lines.append(f"  Example: {natural}")
            lines.append("")
        
        # CONDITIONAL RESTRUCTURING (important for natural flow)
        conditional_patterns = pattern_categories.get('conditional_restructuring', {}).get('patterns', [])
        if conditional_patterns:
            lines.append("## 🔀 CONDITIONAL RESTRUCTURING\n")
            for pattern in conditional_patterns[:3]:
                jp_indicators = pattern.get('japanese_indicators', [])[:2]
                en_pattern = pattern.get('english_pattern', '')
                lines.append(f"- **{', '.join(jp_indicators)}** → \"{en_pattern}\"")
                for ex in self._select_diverse_examples(pattern.get('examples', []), max_examples=2):
                    natural = ex.get('natural')
                    if natural:
                        lines.append(f"  Example: {natural}")
            lines.append("")

        # 17a8 quality-audit upgrades: expressive intensity + cultural clarity
        lines.append("## 🎭 EMOTIONAL INTENSITY MAPPING (17a8 Upgrade)\n")
        lines.append("Map JP emotional pressure to EN rhythm. Keep meaning stable, shift delivery style:")
        lines.append("- **panic / crisis**: short fragments, hard stops, selective caps for inner-shout")
        lines.append("- **nervous excitement**: short declaratives + occasional exclamation")
        lines.append("- **calm reflection**: flowing clauses, softer punctuation")
        lines.append("- Preserve character voice while changing cadence.")
        lines.append("")

        lines.append("## ⚡ DRAMATIC PUNCTUATION ENGINE (17a8 Upgrade)\n")
        lines.append("When JP line is panic/emphasis-heavy (ムリ, やばい, 危機, 無理):")
        lines.append("- Prefer staccato emphasis where natural: \"No. Freaking. Way.\"")
        lines.append("- Use em-dash for abrupt emotional turn: \"—Total. Crisis. Mode.\"")
        lines.append("- Keep readability first; avoid gimmick overuse.")
        lines.append("")

        lines.append("## 🧠 CHARACTER-SPECIFIC EXPANSION GUARDRAILS (17a8 Upgrade)\n")
        lines.append("Do NOT summarize emotional confession beats into one flat sentence.")
        lines.append("For key confession/realization moments, preserve progression:")
        lines.append("1) reaction/body cue → 2) internal realization → 3) explicit declaration")
        lines.append("Only expand when JP clearly carries these beats.")
        lines.append("")

        lines.append("## 🌐 CULTURAL TERM FIRST-MENTION EXPANSION\n")
        lines.append("On first mention, expand uncommon JP shorthand in-context once:")
        lines.append("- Example: \"Supadari — short for Super Darling.\"")
        lines.append("After first expansion, use short form naturally.")
        lines.append("")

        lines.append("## 🗣️ HIGH-VALUE IDIOM EQUIVALENCE OVERRIDES (17a8 Upgrade)\n")
        lines.append("Prefer natural EN equivalents over literal carry-over:")
        lines.append("- 目が潰れる → \"it just about broke my eyes to look at\" / \"my eyes practically fell out\"")
        lines.append("- 場違い → \"like a fish out of water\" / \"completely out of place\"")
        lines.append("- モジモジする → \"fidgeting\" / \"shuffling\"")
        lines.append("")
        
        # QUICK REFERENCE: Avoid Literal Translations
        lines.append("## ⚠️ AVOID THESE LITERAL TRANSLATIONS\n")
        lines.append("| Japanese Pattern | ❌ Don't Write | ✅ Write Instead |")
        lines.append("|-----------------|----------------|------------------|")
        lines.append("| やっぱり | \"As expected\" | \"Sure enough\", \"I knew it\" |")
        lines.append("| さすが | \"As expected of X\" | \"That's X for you\", \"Classic X\" |")
        lines.append("| しょうがない | \"It can't be helped\" | \"Oh well\", \"What can you do\" |")
        lines.append("| まさか | \"Could it be...\" | \"Wait...\", \"No way\" |")
        lines.append("| 絶対 | \"Absolutely\" | \"No way\", \"For sure\", \"I swear\" |")
        lines.append("| まったく | \"Completely\" | \"Good grief\", \"Honestly\", \"Jeez\" |")
        lines.append("")
        
        lines.append("**Golden Rule:** Natural English TRUMPS dictionary accuracy.")
        lines.append("**Success Metric:** Native English reader experiences NO translation friction.\n")
        
        return "\n".join(lines)

    def _format_english_grammar_validation_t1_for_injection(self, validation_data: Dict[str, Any]) -> str:
        """
        Format english_grammar_validation_t1.json for prompt injection (EN Tier 1).

        Emits only high-signal prose guardrails to keep prompt size controlled:
        - literal_phrasing
        - rhythm_and_emphasis
        """
        lines = ["# ENGLISH GRAMMAR VALIDATION T1: RHYTHM-FIRST PROSE GUARDRAILS (Tier 1)\n"]
        lines.append("## ✂️ Prioritize Sharp Rhythm Over Over-Exposition\n")
        lines.append("Use these as live rewrite checks during generation, not post-hoc fixes.\n")

        categories = validation_data.get('validation_categories', {})

        literal_phrasing = categories.get('literal_phrasing', {})
        if literal_phrasing:
            lines.append("## 🧭 AVOID LITERAL TRANSLATION")
            lines.append("If both options are accurate, choose the more idiomatic, scene-natural line.")
            patterns = literal_phrasing.get('patterns', [])
            for pattern in patterns[:4]:
                issue = pattern.get('issue', '')
                if issue:
                    lines.append(f"- {issue}")
                examples = pattern.get('examples', [])
                for ex in examples[:2]:
                    incorrect = ex.get('incorrect') or ex.get('original')
                    correct = ex.get('correct') or ex.get('preferred')
                    if incorrect and correct:
                        lines.append(f"  ❌ {incorrect}")
                        lines.append(f"  ✅ {correct}")
            lines.append("")

        rhythm = categories.get('rhythm_and_emphasis', {})
        if rhythm:
            lines.append("## ⚡ RHYTHM & EMPHASIS CONTROL")
            policy = rhythm.get('enforcement_policy', '')
            if policy:
                lines.append(f"- Policy: {policy}")

            patterns = rhythm.get('patterns', [])
            for pattern in patterns:
                rule_id = pattern.get('id', '')
                issue = pattern.get('issue', '')
                if rule_id:
                    lines.append(f"- **{rule_id}**: {issue}")
                examples = pattern.get('examples', [])
                for ex in examples[:2]:
                    original = ex.get('original') or ex.get('incorrect') or ex.get('over_emphasis')
                    preferred = ex.get('preferred') or ex.get('correct')
                    if original and preferred:
                        lines.append(f"  ❌ {original}")
                        lines.append(f"  ✅ {preferred}")
            lines.append("")

            exceptions = rhythm.get('exceptions', [])
            if exceptions:
                lines.append("### Allowed Exceptions")
                for exc in exceptions[:3]:
                    lines.append(f"- {exc}")
                lines.append("")

            # Genre/subculture profile: MMO/SNS/online chat rhythm policy
            subculture_profiles = rhythm.get('subculture_profiles', {})
            mmo_profile = subculture_profiles.get('mmo_sns_online_chat', {})
            if mmo_profile and mmo_profile.get('enabled'):
                lines.append("### MMO/SNS/Online-Chat Scene Profile")
                priority = mmo_profile.get('priority', '')
                if priority:
                    lines.append(f"- Priority: {priority}")
                style_targets = mmo_profile.get('style_targets', {})
                if style_targets:
                    lines.append(
                        "- Style targets: "
                        f"comedic_timing={style_targets.get('comedic_timing', 'tight')}, "
                        f"chat_authenticity={style_targets.get('chat_authenticity', 'high')}, "
                        f"youthful_voice={style_targets.get('youthful_voice', 'high')}"
                    )
                over_exposition = mmo_profile.get('over_exposition_control', {})
                if over_exposition:
                    target = over_exposition.get('target', '')
                    if target:
                        lines.append(f"- Over-exposition control: {target}")
                    ratio_cap = over_exposition.get('max_expository_lines_per_10_dialogue_lines')
                    if ratio_cap is not None:
                        lines.append(f"- Cap guidance: <= {ratio_cap} expository lines per 10 dialogue lines")
                preserve_strengths = mmo_profile.get('preserve_strengths', [])
                if preserve_strengths:
                    lines.append(f"- Preserve strengths: {', '.join(preserve_strengths[:3])}")
                lines.append("")

            # Concrete 9-10 word dialogue anchors for live generation
            target_examples = rhythm.get('target_length_dialogue_examples', {})
            if target_examples:
                lines.append("### Target-Length Dialogue Anchors (9-10 words)")
                target_range = target_examples.get('target_word_range', {})
                min_words = target_range.get('min')
                max_words = target_range.get('max')
                if min_words is not None and max_words is not None:
                    lines.append(f"- Preferred range: {min_words}-{max_words} words")
                use_case = target_examples.get('use_case', '')
                if use_case:
                    lines.append(f"- Use case: {use_case}")

                real_world = target_examples.get('real_world_successes_0116', [])
                if real_world:
                    lines.append("- Validated examples:")
                    for ex in real_world[:5]:
                        text = ex.get('text', '')
                        word_count = ex.get('word_count')
                        if text and word_count is not None:
                            lines.append(f"  - ({word_count}w) \"{text}\"")

                curated = target_examples.get('curated_examples', {})
                if curated:
                    lines.append("- Curated pattern anchors:")
                    for category, entries in curated.items():
                        if not entries:
                            continue
                        label = category.replace('_', ' ')
                        first = entries[0]
                        text = first.get('text', '')
                        word_count = first.get('word_count')
                        if text and word_count is not None:
                            lines.append(f"  - {label}: ({word_count}w) \"{text}\"")

                guardrails = target_examples.get('guardrails', [])
                if guardrails:
                    lines.append("- Guardrails:")
                    for rule in guardrails[:3]:
                        lines.append(f"  - {rule}")
                lines.append("")

        lines.append("## 🔗 INTERLOCK WITH LITERACY TECHNIQUES")
        lines.append("- Use `literacy_techniques.rhythm_first_prose_enforcement` as primary style intent.")
        lines.append("- Use this module's rule IDs as concrete rewrite triggers during drafting.")
        lines.append("- If conflict occurs: preserve plot facts + character intent, then choose tighter cadence.\n")

        lines.append("**Success Metric:** Reads like native contemporary prose, not a translated paraphrase.")
        lines.append("**Failure:** Repetitive emphasis loops, noun-heavy literalness, or explanatory drag.\n")

        return "\n".join(lines)

    def _format_vietnamese_grammar_rag_for_injection(self, grammar_rag_data: Dict[str, Any]) -> str:
        """
        Format Vietnamese Grammar RAG for prompt injection (Tier 1).
        
        Converts JSON pattern database into Vietnamese translation guidance.
        Focuses on:
        1. AI-ism elimination (sentence + dialogue patterns)
        2. Particle system by archetype/PAIR_ID
        3. Pronoun tier system (friendship/romance)
        4. Japanese structure carryover prevention
        
        Args:
            grammar_rag_data: Vietnamese Grammar RAG dictionary
            
        Returns:
            Formatted Vietnamese grammar guidance for prompt injection
        """
        lines = ["# VIETNAMESE GRAMMAR RAG: ANTI-AI-ISM + PARTICLE SYSTEM (Tier 1)\n"]
        lines.append("## 🇻🇳 JP→VN Transcreation for Natural Vietnamese Prose\n")
        lines.append("Sử dụng hệ thống particle và cấu trúc câu tự nhiên của tiếng Việt.\n")
        
        # CRITICAL: AI-ISM ELIMINATION
        lines.append("## 🚫 CRITICAL: XÓA AI-ISM PATTERNS\n")
        
        # Sentence structure AI-isms  
        sentence_ai_isms = grammar_rag_data.get('sentence_structure_ai_isms', {}).get('patterns', [])
        if sentence_ai_isms:
            lines.append("### Cấu Trúc Câu AI-ism (CẤM DÙNG)\n")
            for pattern in sentence_ai_isms:
                rule_id = pattern.get('id', '')
                rule = pattern.get('rule', '')
                severity = pattern.get('severity', 'high')
                forbidden = pattern.get('forbidden', [])[:3]  # First 3 examples
                corrections = pattern.get('corrections', {})
                
                lines.append(f"**{rule_id}** [{severity.upper()}]")
                lines.append(f"Rule: {rule}")
                if forbidden:
                    lines.append(f"❌ Forbidden: {', '.join(forbidden)}")
                if corrections:
                    # Show first correction
                    for wrong, correct in list(corrections.items())[:1]:
                        lines.append(f"   ❌ \"{wrong}\"")
                        lines.append(f"   ✅ \"{correct}\"")
                lines.append("")
        
        # Dialogue AI-isms
        dialogue_ai_isms = grammar_rag_data.get('dialogue_ai_isms', {}).get('patterns', [])
        if dialogue_ai_isms:
            lines.append("### Hội Thoại AI-ism (TRÁNH)\n")
            for pattern in dialogue_ai_isms:
                rule_id = pattern.get('id', '')
                rule = pattern.get('rule', '')
                
                lines.append(f"**{rule_id}**")
                lines.append(f"Rule: {rule}")
                
                # Handle different pattern structures
                if pattern.get('mappings'):
                    lines.append("Mappings:")
                    for jp, vn_options in list(pattern.get('mappings', {}).items())[:3]:
                        options = ', '.join(vn_options) if isinstance(vn_options, list) else vn_options
                        lines.append(f"  {jp} → {options}")
                elif pattern.get('correct_patterns'):
                    for style, example in list(pattern.get('correct_patterns', {}).items())[:2]:
                        lines.append(f"  {style}: {example}")
                lines.append("")
        
        # PARTICLE SYSTEM (CORE)
        lines.append("## 💬 PARTICLE SYSTEM: SẮC THÁI HỘI THOẠI\n")
        
        particle_system = grammar_rag_data.get('particle_system', {})
        
        # Question particles
        question_particles = particle_system.get('question_particles', [])
        if question_particles:
            lines.append("### Question Particles\n")
            lines.append("| Particle | Register | Gender | Archetype | Ví dụ |")
            lines.append("|----------|----------|--------|-----------|-------|")
            
            for p in question_particles[:8]:
                particle = p.get('particle', '')
                register = p.get('register', 'neutral')
                gender = p.get('gender', 'both')
                archetypes = p.get('archetype_affinity', ['universal'])[:2]
                examples = p.get('examples', [''])
                example = examples[0] if examples else ''
                arch_str = ', '.join(archetypes)
                lines.append(f"| **{particle}** | {register} | {gender} | {arch_str} | {example} |")
            lines.append("")
        
        # Statement particles
        statement_particles = particle_system.get('statement_particles', [])
        if statement_particles:
            lines.append("### Statement Particles\n")
            lines.append("| Particle | Register | Function | Ví dụ |")
            lines.append("|----------|----------|----------|-------|")
            
            for p in statement_particles[:8]:
                particle = p.get('particle', '')
                register = p.get('register', 'neutral')
                function = p.get('function', '')
                examples = p.get('examples', [''])
                example = examples[0] if examples else ''
                lines.append(f"| **{particle}** | {register} | {function} | {example} |")
            lines.append("")
        
        # Combination patterns
        combo_patterns = particle_system.get('combination_patterns', [])
        if combo_patterns:
            lines.append("### Particle Combinations\n")
            for combo in combo_patterns[:5]:
                combination = combo.get('combination', '')
                register = combo.get('register', '')
                function = combo.get('function', '')
                example = combo.get('example', '')
                lines.append(f"- **{combination}** ({register}): {function}")
                if example:
                    lines.append(f"  Ví dụ: \"{example}\"")
            lines.append("")
        
        # ARCHETYPE REGISTER MATRIX
        lines.append("## 🎭 ARCHETYPE-PARTICLE MAPPING\n")
        
        archetypes = grammar_rag_data.get('archetype_register_matrix', {}).get('archetypes', {})
        if archetypes:
            lines.append("| Archetype | Register | Casual | Forbidden |")
            lines.append("|-----------|----------|--------|-----------|")
            
            for arch_name, arch_data in list(archetypes.items())[:8]:
                register = arch_data.get('preferred_register', 'standard')
                casual = ', '.join(arch_data.get('casual_particles', [])[:3])
                forbidden = ', '.join(arch_data.get('forbidden_particles', [])[:3])
                lines.append(f"| **{arch_name}** | {register} | {casual} | {forbidden} |")
            lines.append("")
        
        # PRONOUN TIERS
        lines.append("## 👤 PRONOUN EVOLUTION BY RELATIONSHIP\n")
        
        pronoun_tiers = grammar_rag_data.get('pronoun_tiers', {})
        
        # Friendship tiers
        friendship = pronoun_tiers.get('friendship', {})
        if friendship:
            lines.append("### Friendship Progression\n")
            for tier_name, tier_data in friendship.items():
                if isinstance(tier_data, dict):
                    pair_id = tier_data.get('pair_id', tier_data.get('rtas_range', ''))
                    pronouns = tier_data.get('pronouns', {})
                    first_person = pronouns.get('first_person', [])[:2]
                    second_person = pronouns.get('second_person', [])[:2]
                    first_str = ', '.join(first_person) if first_person else '-'
                    second_str = ', '.join(second_person) if second_person else '-'
                    lines.append(f"**{tier_name}** (PAIR_ID {pair_id}): xưng {first_str} / gọi {second_str}")
            lines.append("")
        
        # Romance scale
        romance = pronoun_tiers.get('romance_scale', {})
        if romance:
            lines.append("### Romance Evolution\n")
            for stage, stage_data in list(romance.items())[:4]:
                if isinstance(stage_data, dict):
                    pair_id = stage_data.get('pair_id', stage_data.get('rtas', ''))
                    pronouns = stage_data.get('pronouns', {})
                    first = pronouns.get('first_person', [''])[:1]
                    second = pronouns.get('second_person', [''])[:1]
                    lines.append(f"**{stage}** (PAIR_ID {pair_id}): {first[0] if first else ''} ↔ {second[0] if second else ''}")
            lines.append("")

        # PAIR_ID PARTICLE EVOLUTION
        pair_id_evolution = grammar_rag_data.get('pair_id_particle_evolution', grammar_rag_data.get('rtas_particle_evolution', {}))
        if pair_id_evolution:
            lines.append("## 📈 PAIR_ID PARTICLE EVOLUTION\n")
            for pair_id_tier, tier_data in list(pair_id_evolution.items())[:4]:
                if isinstance(tier_data, dict):
                    register = tier_data.get('register', '')
                    particles_list = tier_data.get('particles', [])[:4]
                    lines.append(f"**{pair_id_tier}** ({register}): {', '.join(particles_list)}")
            lines.append("")
        
        # FREQUENCY THRESHOLDS (warnings)
        frequency = grammar_rag_data.get('frequency_thresholds', {})
        if frequency:
            lines.append("## ⚠️ AI-ISM DENSITY WARNINGS\n")
            max_markers = frequency.get('max_markers_per_1k_words', {})
            if max_markers:
                lines.append("| Marker | Max/1000 từ | Severity |")
                lines.append("|--------|-------------|----------|")
                for marker, limit in list(max_markers.items())[:6]:
                    severity = "🔴" if limit <= 1 else "🟡" if limit <= 2 else "🟢"
                    lines.append(f"| {marker} | {limit} | {severity} |")
            lines.append("")
        
        # GOLDEN RULES
        lines.append("## 📌 GOLDEN RULES\n")
        lines.append("1. **Particle là Linh Hồn Hội Thoại** - Không có particle = đọc như robot")
        lines.append("2. **Match Archetype với Register** - Tsundere ≠ Ojou-sama particle set")
        lines.append("3. **PAIR_ID Drives Pronoun Evolution** - Mức độ thân thiết → thay đổi xưng hô")
        lines.append("4. **Zero AI-ism Tolerance** - \"Có lẽ X...\" patterns = FAIL\n")
        lines.append("")
        lines.append("**Success Metric:** Người đọc Việt Nam không nhận ra là bản dịch.")
        lines.append("**Failure Condition:** AI-ism density >2/1k words = Chưa đạt chuẩn.\n")
        
        return "\n".join(lines)

    def _format_literacy_techniques_for_injection(
        self,
        literacy_data: Dict[str, Any],
        english_validation_t1_data: Optional[Dict[str, Any]] = None,
        target_language: Optional[str] = None,
        genre: Optional[str] = None,
    ) -> str:
        """
        Format Literary Techniques for prompt injection (Tier 1).

        Converts JSON literary technique database into narrative transcreation guidance.
        Focuses on:
        1. Narrative POV techniques (1st person, 3rd person, Free Indirect Discourse)
        2. Psychic distance levels
        3. Show Don't Tell principles
        4. Genre-specific presets

        Args:
            literacy_data: Literary techniques dictionary with narrative_techniques, psychic_distance_levels, etc.
            english_validation_t1_data: Optional EN validation config for cross-module rhythm interlock.
            target_language: Target language code ('en', 'vn', etc.). If 'vn', includes vn_instruction.

        Returns:
            Formatted literary technique guidance for prompt injection
        """
        # Use instance target_language if not specified
        if target_language is None:
            target_language = self.target_language

        is_vn = target_language in ['vn', 'vi']

        lines = ["# LITERARY TECHNIQUES: CREATIVE TRANSCREATION (Tier 1)\n"]
        lines.append("## 🎭 What You Are Doing: NOT Translation, But Creative Transcreation\n")
        lines.append("You are not a dictionary—you are a **method actor** performing a script.")
        lines.append("Transform Japanese narrative quirks into natural prose using literary techniques.\n")

        # NARRATIVE TECHNIQUES
        narrative_techniques = literacy_data.get('narrative_techniques', {})

        # Third Person (most common in LN)
        third_person = narrative_techniques.get('third_person', {})
        if third_person:
            lines.append("## 📖 THIRD PERSON NARRATIVE TECHNIQUES\n")

            third_person_subs = third_person.get('subtechniques', {})

            # Third Person Limited (most important for Shoujo/Romance)
            tp_limited = third_person_subs.get('third_person_limited', {})
            if tp_limited:
                lines.append("### 🎯 Third Person Limited (Ngôi thứ ba hạn tri)\n")
                lines.append(f"**Definition:** {tp_limited.get('definition', '')}\n")
                lines.append(f"**Psychic Distance:** {tp_limited.get('psychic_distance', 'close')}")

                filter_removal = tp_limited.get('filter_removal', {})
                if filter_removal and filter_removal.get('enabled'):
                    banned_filters = filter_removal.get('banned_filters', [])
                    lines.append("\n**CRITICAL: Eliminate Filter Words**")
                    lines.append("❌ BANNED: " + ", ".join([f'"{f}"' for f in banned_filters[:5]]))
                    lines.append(f"✅ FIX: {filter_removal.get('instruction', '')}\n")

                vocab_infection = tp_limited.get('vocabulary_infection', {})
                if vocab_infection and vocab_infection.get('enabled'):
                    lines.append(f"**Vocabulary Infection:** {vocab_infection.get('instruction', '')}\n")

                # VN-specific instruction
                if is_vn and tp_limited.get('vn_instruction'):
                    lines.append(f"**Hướng dẫn VN:** {tp_limited['vn_instruction']}\n")

            # Third Person Omniscient
            tp_omniscient = third_person_subs.get('third_person_omniscient', {})
            if tp_omniscient:
                lines.append("### 🌍 Third Person Omniscient (Ngôi thứ ba toàn tri)\n")
                lines.append(f"**Definition:** {tp_omniscient.get('definition', '')}")
                lines.append(f"**Psychic Distance:** {tp_omniscient.get('psychic_distance', 'far')}")
                if is_vn and tp_omniscient.get('vn_instruction'):
                    lines.append(f"**Hướng dẫn VN:** {tp_omniscient['vn_instruction']}")
                lines.append("")

            # Third Person Objective
            tp_objective = third_person_subs.get('third_person_objective', {})
            if tp_objective:
                lines.append("### 📹 Third Person Objective (Ngôi thứ ba khách quan)\n")
                lines.append(f"**Definition:** {tp_objective.get('definition', '')}")
                banned_content = tp_objective.get('banned_content', [])
                if banned_content:
                    lines.append("\n**BANNED:** " + ", ".join(banned_content[:4]))
                if is_vn and tp_objective.get('vn_instruction'):
                    lines.append(f"**Hướng dẫn VN:** {tp_objective['vn_instruction']}")
                lines.append("")

        # FREE INDIRECT DISCOURSE (Critical for Shoujo)
        fid = narrative_techniques.get('free_indirect_discourse', {})
        if fid:
            lines.append("## 🎨 FREE INDIRECT DISCOURSE (Gián tiếp tự do)\n")
            lines.append(f"**Definition:** {fid.get('description', '')}\n")
            lines.append(f"**Instruction:** {fid.get('instruction', '')}\n")

            examples = fid.get('examples', {})
            if examples:
                lines.append("**Example Transformation:**")
                lines.append(f"❌ Standard 3rd: {examples.get('standard_third', '')}")
                lines.append(f"✅ Free Indirect: {examples.get('free_indirect', '')}")
                lines.append(f"📌 {examples.get('explanation', '')}\n")

            key_features = fid.get('key_features', [])
            if key_features:
                lines.append("**Key Features:**")
                for feature in key_features[:5]:
                    lines.append(f"- {feature}")
                lines.append("")

        # PSYCHIC DISTANCE LEVELS
        psychic_distance = literacy_data.get('psychic_distance_levels', {})
        if psychic_distance:
            levels = psychic_distance.get('levels', {})
            lines.append("## 📏 PSYCHIC DISTANCE SCALE (John Gardner)\n")
            lines.append("Control how close the narration is to the character's consciousness:\n")

            for level_key in ['level_4_very_close', 'level_3_close', 'level_2_distant']:
                level = levels.get(level_key, {})
                if level:
                    description = level.get('description', '')
                    example = level.get('example', '')
                    lines.append(f"**{level_key.replace('_', ' ').title()}**")
                    lines.append(f"- {description}")
                    if example:
                        lines.append(f"- Example: \"{example}\"")
                    lines.append("")

        # SHOW DON'T TELL
        show_dont_tell = literacy_data.get('show_dont_tell', {})
        if show_dont_tell and show_dont_tell.get('enabled'):
            lines.append("## 🎬 SHOW DON'T TELL (Fundamental Rule)\n")
            lines.append(f"**Principle:** {show_dont_tell.get('description', '')}\n")

            banned_phrases = show_dont_tell.get('banned_tell_phrases', [])
            if banned_phrases:
                lines.append("**❌ BANNED TELL PHRASES:**")
                for phrase in banned_phrases[:5]:
                    lines.append(f"- {phrase}")
                lines.append("")

            show_alternatives = show_dont_tell.get('show_alternatives', {})
            if show_alternatives:
                lines.append("**✅ SHOW ALTERNATIVES:**")
                for tell, show in list(show_alternatives.items())[:3]:
                    lines.append(f"- **{tell}** → \"{show}\"")
                lines.append("")

        # RHYTHM-FIRST PROSE ENFORCEMENT (new Tier 1 block)
        rhythm_first = literacy_data.get('rhythm_first_prose_enforcement', {})
        if rhythm_first and rhythm_first.get('enabled'):
            lines.append("## ⚡ RHYTHM-FIRST PROSE ENFORCEMENT\n")
            principle = rhythm_first.get('principle', '')
            instruction = rhythm_first.get('instruction', '')
            if principle:
                lines.append(f"**Principle:** {principle}")
            if instruction:
                lines.append(f"**Instruction:** {instruction}")
            lines.append("")

            rules = rhythm_first.get('rules', {})

            avoid_literal = rules.get('avoid_literal_translation', {})
            if avoid_literal:
                lines.append("### Avoid Literal Translation")
                if avoid_literal.get('description'):
                    lines.append(f"- {avoid_literal.get('description')}")
                for enforcement in avoid_literal.get('enforcement', [])[:3]:
                    lines.append(f"- {enforcement}")
                rewrite_examples = avoid_literal.get('rewrite_examples', [])
                for ex in rewrite_examples[:2]:
                    literal = ex.get('literal', '')
                    preferred = ex.get('preferred', '')
                    if literal and preferred:
                        lines.append(f"  ❌ {literal}")
                        lines.append(f"  ✅ {preferred}")
                lines.append("")

            avoid_repetition = rules.get('avoid_repetition_and_over_emphasis', {})
            if avoid_repetition:
                lines.append("### Avoid Repetition & Over-Emphasis")
                if avoid_repetition.get('description'):
                    lines.append(f"- {avoid_repetition.get('description')}")
                for enforcement in avoid_repetition.get('enforcement', [])[:3]:
                    lines.append(f"- {enforcement}")
                markers = avoid_repetition.get('intensity_stack_markers', [])
                if markers:
                    lines.append(f"- Intensity stack markers to minimize: {', '.join(markers[:6])}")
                rewrite_examples = avoid_repetition.get('rewrite_examples', [])
                for ex in rewrite_examples[:2]:
                    original = ex.get('over_emphasis', '')
                    preferred = ex.get('preferred', '')
                    if original and preferred:
                        lines.append(f"  ❌ {original}")
                        lines.append(f"  ✅ {preferred}")
                lines.append("")

            tie_breaker = rhythm_first.get('tie_breaker_policy', {})
            if tie_breaker:
                lines.append("### Tie-Breaker")
                if tie_breaker.get('if_conflict'):
                    lines.append(f"- {tie_breaker.get('if_conflict')}")
                must_preserve = tie_breaker.get('must_preserve', [])
                if must_preserve:
                    lines.append(f"- Must preserve: {', '.join(must_preserve)}")
                lines.append("")

            # Scene profile: MMO/SNS/online chat subculture
            scene_profiles = rhythm_first.get('scene_profiles', {})
            mmo_scene = scene_profiles.get('mmo_sns_online_chat', {})
            if mmo_scene and mmo_scene.get('enabled'):
                lines.append("### MMO/SNS/Online-Chat Rhythm Profile")
                objective = mmo_scene.get('primary_objective', '')
                if objective:
                    lines.append(f"- Objective: {objective}")
                timing_policy = mmo_scene.get('timing_policy', {})
                if timing_policy:
                    target = timing_policy.get('target', '')
                    if target:
                        lines.append(f"- Timing policy: {target}")
                    ratio_cap = timing_policy.get('max_expository_lines_per_10_dialogue_lines')
                    if ratio_cap is not None:
                        lines.append(f"- Cap guidance: <= {ratio_cap} expository lines per 10 dialogue lines")
                    for rule in timing_policy.get('enforcement', [])[:3]:
                        lines.append(f"- {rule}")
                emotional_pivot = mmo_scene.get('emotional_pivot_preservation', {})
                if emotional_pivot:
                    pivot_instruction = emotional_pivot.get('instruction', '')
                    if pivot_instruction:
                        lines.append(f"- Emotional pivot rule: {pivot_instruction}")
                rewrite_examples = mmo_scene.get('rewrite_examples', [])
                for ex in rewrite_examples[:2]:
                    original = ex.get('over_exposition') or ex.get('over_flattened')
                    preferred = ex.get('preferred', '')
                    if original and preferred:
                        lines.append(f"  ❌ {original}")
                        lines.append(f"  ✅ {preferred}")
                lines.append("")

        # Cross-module interlock with english_grammar_validation_t1.json (EN only)
        if english_validation_t1_data:
            validation_categories = english_validation_t1_data.get('validation_categories', {})
            rhythm_rules = validation_categories.get('rhythm_and_emphasis', {})
            literal_rules = validation_categories.get('literal_phrasing', {})
            if rhythm_rules or literal_rules:
                lines.append("## 🔗 CROSS-MODULE INTERLOCK (Literacy + EN Grammar T1)\n")
                lines.append("Apply style intent from `rhythm_first_prose_enforcement` using concrete rule triggers below:\n")

                literal_patterns = literal_rules.get('patterns', [])
                if literal_patterns:
                    lines.append("**Literal Translation Triggers:**")
                    for pattern in literal_patterns[:2]:
                        lines.append(f"- {pattern.get('id', '')}: {pattern.get('issue', '')}")
                    lines.append("")

                rhythm_patterns = rhythm_rules.get('patterns', [])
                if rhythm_patterns:
                    lines.append("**Rhythm/Emphasis Triggers:**")
                    for pattern in rhythm_patterns[:4]:
                        lines.append(f"- {pattern.get('id', '')}: {pattern.get('issue', '')}")
                    lines.append("")

                mmo_profile = rhythm_rules.get('subculture_profiles', {}).get('mmo_sns_online_chat', {})
                if mmo_profile and mmo_profile.get('enabled'):
                    lines.append("**MMO/SNS Profile Interlock:**")
                    over_exposition = mmo_profile.get('over_exposition_control', {})
                    target = over_exposition.get('target', '')
                    if target:
                        lines.append(f"- {target}")
                    preserve_strengths = mmo_profile.get('preserve_strengths', [])
                    if preserve_strengths:
                        lines.append(f"- Preserve: {', '.join(preserve_strengths[:3])}")
                    lines.append("")

                lines.append("**Execution Rule:** Keep meaning and voice, then prefer the tightest natural cadence.\n")

        # GENRE-SPECIFIC PRESETS (JIT: only inject relevant genre preset)
        genre_presets = literacy_data.get('genre_specific_presets', {})
        if genre_presets and genre:
            # Map common genre names to literacy_techniques keys
            genre_map = {
                'romcom': 'shoujo_romance',
                'romantic_comedy': 'shoujo_romance',
                'shoujo_romance': 'shoujo_romance',
                'shoujo': 'shoujo_romance',
                'noir': 'noir_hardboiled',
                'hardboiled': 'noir_hardboiled',
                'noir_hardboiled': 'noir_hardboiled',
                'horror': 'psychological_horror',
                'psychological_horror': 'psychological_horror',
                'fantasy': 'epic_fantasy',
                'epic_fantasy': 'epic_fantasy',
            }
            matched_genre_key = genre_map.get(genre.lower().strip(), genre.lower().strip())
            matched_genre = genre_presets.get(matched_genre_key, {})

            if matched_genre:
                lines.append("## 🎯 GENRE-SPECIFIC NARRATIVE PRESET\n")
                genre_display = matched_genre_key.replace('_', ' ').title()
                lines.append(f"### {genre_display}")
                lines.append(f"- **Technique:** {matched_genre.get('narrative_technique', '')}")
                lines.append(f"- **Psychic Distance:** {matched_genre.get('psychic_distance', '')}")
                lines.append(f"- **Sensory Focus:** {matched_genre.get('sensory_focus', '')}")
                lines.append(f"- **Pacing:** {matched_genre.get('sentence_pacing', '')}")
                lines.append(f"- **Vocabulary:** {matched_genre.get('emotional_vocabulary', '')}")
                if is_vn and matched_genre.get('vn_instruction'):
                    lines.append(f"- **Hướng dẫn VN:** {matched_genre['vn_instruction']}")
                lines.append("")
            # If no match, inject nothing (JIT: only inject when genre detected)

        # GOLDEN RULES
        lines.append("## 📌 INTEGRATION RULES\n")
        lines.append("1. **Match Narrative Technique to Source** - If JP uses 3rd person limited, maintain it")
        lines.append("2. **Remove Filter Words** - 'She saw', 'He felt' → Direct perception")
        lines.append("3. **Apply Free Indirect Discourse** - Merge narrator voice with character vocabulary")
        lines.append("4. **Show Emotions Through Actions** - Not 'sad', but 'throat tight, eyes stinging'")
        lines.append("5. **Psychic Distance = Genre** - Shoujo = Very Close, Epic Fantasy = Distant\n")

        lines.append("**Success Metric:** Translation reads as if originally written in target language.")
        lines.append("**Failure:** Reads like a translated document with stiff, unnatural phrasing.\n")

        return "\n".join(lines)

    def _format_icl_prose_examples_for_injection(
        self,
        literacy_data: Dict[str, Any],
        model_id: Optional[str] = None,
        max_examples: Optional[int] = None,
        target_language: Optional[str] = None,
    ) -> str:
        """
        Format professional prose ICL examples from real_world_jp_en_corpus for prompt injection.

        Renders the ``professional_prose_icl_examples.examples_by_mood`` section that
        _format_literacy_techniques_for_injection() intentionally omits (structural rules vs.
        prose exemplars are separate concerns).

        Injection strategy:
        - For Opus models (128 K context): inject ALL examples ordered by scene-type diversity
          priority. Token cost ~21 K tokens — well within the ~102 K available headroom.
        - For Sonnet/Haiku models (shorter contexts): cap at max_examples (default 24, covering
          every major scene type with at least 1 example).
        - Category order follows narrative utility: most universally needed scene types first
          (mystery/deduction → kinetic action → romance → GL → psychological → comedy → poetic).
        - Within each category examples are emitted in the order they appear in the JSON
          (already curated highest-quality first).

        Args:
            literacy_data: Full literary techniques dict (contains real_world_jp_en_corpus).
            model_id: Optional model string (e.g. 'claude-opus-4-6'). Used to determine
                      full vs. capped injection.
            max_examples: Hard cap on total examples injected. None = no cap (Opus default).
            target_language: Target language code ('en', 'vn', etc.). If 'vn', includes vn_instruction.

        Returns:
            Formatted ICL prose block for prompt injection, or empty string if no data.
        """
        # Use instance target_language if not specified
        if target_language is None:
            target_language = self.target_language

        is_vn = target_language in ['vn', 'vi']
        corpus = literacy_data.get('real_world_jp_en_corpus', {})
        icl_section = corpus.get('professional_prose_icl_examples', {})
        examples_by_mood = icl_section.get('examples_by_mood', {})

        if not examples_by_mood:
            return ''

        # Determine if this is an Opus-class model (full injection) or not (capped)
        is_opus = model_id and 'opus' in model_id.lower()

        # Priority order: most universally applicable scene types first.
        # Categories not listed here are appended afterwards in alphabetical order.
        PRIORITY_ORDER = [
            'mystery_deduction',
            'kinetic_action_sequence',
            'grief_romance',
            'psychological_duel',
            'gl_intimate_crescendo',
            'cold_intellectual_narrator',
            'cunning_heroine_agency',
            'dramatized_romance',
            'comedic_escalation_chain',
            'slapstick_interiority',
            'observation_as_affection',
            'silent_channel_intimacy',
            'sibling_grief_payoff',
            'retrospective_layering',
            'earned_softening',
            'sardonic_analysis_loop',
            'literary_poetic',
            'deep_introspection',
            'endurance_as_devotion',
            'tension_suspense',
            'wistful_bittersweet',
            'intimate_quiet_moments',
            'playful_banter',
            'genre_aware_epilogue',
        ]

        # Build ordered category list (priority-listed first, then any unlisted alphabetically)
        ordered_categories = [c for c in PRIORITY_ORDER if c in examples_by_mood]
        remaining = sorted(k for k in examples_by_mood if k not in PRIORITY_ORDER)
        ordered_categories.extend(remaining)

        lines = ["# PROFESSIONAL PROSE ICL: PUBLISHED J-NOVEL ENGLISH EXEMPLARS\n"]
        lines.append(
            "These are verbatim passages from officially published J-Novel English translations "
            "(Yen Press / Seven Seas / J-Novel Club). "
            "Use them as **quality anchors** — not templates to copy, but proof of what "
            "premium LN prose sounds like in English. "
            "Match their register, rhythm, and emotional precision.\n"
        )

        total_injected = 0
        for cat_key in ordered_categories:
            if max_examples is not None and total_injected >= max_examples:
                break

            cat = examples_by_mood[cat_key]
            cat_label = cat_key.replace('_', ' ').title()
            cat_desc = cat.get('description', '')
            cat_vn_instruction = cat.get('vn_instruction', '')
            examples = cat.get('examples', [])

            if not examples:
                continue

            lines.append(f"## {cat_label}")
            if cat_desc:
                lines.append(f"*{cat_desc}*")
            # For VN: add vn_instruction
            if is_vn and cat_vn_instruction:
                lines.append(f"\n**Hướng dẫn Tiếng Việt:** {cat_vn_instruction}")
            lines.append("")

            for ex in examples:
                if max_examples is not None and total_injected >= max_examples:
                    break

                ex_id = ex.get('id', '')
                source = ex.get('source', '')
                context = ex.get('context', '')
                text = ex.get('text', '')
                techniques = ex.get('techniques', [])
                why_premium = ex.get('why_premium', '')

                if not text:
                    continue

                lines.append(f"### [{ex_id}] — {source}")
                if context:
                    lines.append(f"**Scene context:** {context}")
                if techniques:
                    lines.append(f"**Techniques:** {', '.join(techniques)}")
                lines.append("\n```")
                lines.append(text.strip())
                lines.append("```")
                if why_premium:
                    lines.append(f"\n> **Why premium:** {why_premium}")
                lines.append("")
                total_injected += 1

        lines.append(f"---\n*{total_injected} exemplars from {len(set(examples_by_mood.keys()))} scene-type categories.*\n")
        lines.append("**Usage rule:** These are reference anchors. When translating similar scenes, "
                     "match the prose register—never copy verbatim.\n")

        return "\n".join(lines)

    def build_translation_prompt(
        self,
        source_text: str,
        chapter_title: str,
        chapter_id: Optional[str] = None,
        previous_context: Optional[str] = None,
        name_registry: Optional[Dict[str, str]] = None,
        jp_title: Optional[str] = None,
        title_pipeline: Optional[str] = None,
    ) -> str:
        """
        Build the complete translation prompt for a chapter.

        Args:
            source_text: Japanese source text to translate.
            chapter_title: Translated chapter title (EN or target language).
                           For MINIMAL_NOUN philosophy, this is the short toc label (e.g., "Love").
            chapter_id: Stable pipeline identifier (e.g., chapter_02). Does NOT reflect
                        the book's internal chapter numbering — use jp_title/chapter_title for that.
            previous_context: Context from previous chapters.
            name_registry: Character name mappings (JP -> Target Language).
            jp_title: Original Japanese chapter title from the EPUB TOC (e.g., "第一章").
                      Injected alongside chapter_title so the model has zero ambiguity about
                      which chapter it is translating. Prevents thinking-budget waste on
                      chapter_id vs. JP heading reconciliation.
            title_pipeline: Thematic working title for internal pipeline use (e.g., "A Firework Date
                            and a First Kiss"). Provides scene/emotional framing for the translator
                            when chapter_title is a minimal noun. Never used as EPUB heading.

        Returns:
            Complete prompt for translation.
        """
        parts = []
        reference_docs: List[str] = []
        doc_index = 1

        def _append_reference_doc(source_name: str, content: str):
            nonlocal doc_index
            if not content:
                return
            reference_docs.extend([
                f'  <document index="{doc_index}">',
                f"    <source>{source_name}</source>",
                "    <document_content>",
                content,
                "    </document_content>",
                "  </document>",
            ])
            doc_index += 1

        # Continuity pack from previous volume
        if self._continuity_pack:
            _append_reference_doc("continuity_pack", self._continuity_pack)

        # Previous chapter context
        if previous_context:
            _append_reference_doc("previous_chapter_context", previous_context)

        # Character name registry
        if name_registry:
            registry_lines = ["Use these established name translations consistently:"]
            for jp, translated in name_registry.items():
                registry_lines.append(f"  {jp} = {translated}")
            _append_reference_doc("character_name_registry", "\n".join(registry_lines))

        if reference_docs:
            parts.append("<!-- LONG CONTEXT REFERENCE DOCUMENTS -->")
            parts.append("<documents>")
            parts.extend(reference_docs)
            parts.append("</documents>")
            parts.append("")

        # Source text
        if chapter_id or jp_title or chapter_title:
            parts.append("<target_chapter>")
            if chapter_id:
                parts.append(f"Pipeline ID: {chapter_id}  (internal only — do NOT use as heading)")
            if jp_title:
                parts.append(f"JP title: {jp_title}")
            if chapter_title:
                parts.append(f"EN title: {chapter_title}")
            if title_pipeline and title_pipeline != chapter_title:
                parts.append(f"Scene context (pipeline, do NOT use as heading): {title_pipeline}")
            if self._title_motif_catchphrase_directive:
                parts.append(
                    "Title motif catchphrase policy: "
                    f"{self._title_motif_catchphrase_directive}"
                )
            parts.append("Use EN title (above) as the output heading. Ignore any chapter number embedded in the source filename or pipeline ID.")
            parts.append("</target_chapter>")
            parts.append("")
        parts.append("<!-- SOURCE TEXT TO TRANSLATE -->")
        parts.append("<source_text>")
        parts.append(f"# {chapter_title}")
        parts.append("")
        parts.append(source_text)
        parts.append("</source_text>")
        parts.append("")

        # Language-specific instructions
        parts.append("<!-- INSTRUCTIONS -->")
        lang_name = self.lang_config.get('language_name', self.target_language.upper())

        if self.target_language == 'vn':
            # Vietnamese-specific instructions
            parts.append(f"Translate ONLY the Japanese text inside the <source_text> tags to {lang_name}, following all guidelines in the system prompt.")
            parts.append("CRITICAL SCOPE: Ignore any Japanese text that appears in cache/reference/continuity context.")
            parts.append("IMPORTANT: Preserve all [ILLUSTRATION: filename] tags exactly as they appear.")
            parts.append("IMPORTANT: Apply character archetypes and pronoun systems as defined in the prompt.")
            parts.append("IMPORTANT: Transcreate SFX to Vietnamese prose (except for Gyaru archetype with high boldness).")
            parts.append("IMPORTANT: Maintain translation fidelity - 1:1 semantic preservation required.")
            parts.append("")
            parts.append("<!-- GAIJI TRANSCREATION PROTOCOL -->")
            parts.append("CRITICAL: Gaiji markers [ILLUSTRATION: gaiji-*.png] are special character glyphs, NOT real illustrations.")
            parts.append("They represent typographical elements that must be transcreated and the marker REMOVED:")
            parts.append("")
            parts.append("PATTERN RECOGNITION:")
            parts.append("  1. gaiji-dakuon-* (濁音 = voiced marks)")
            parts.append("     Context: Stuttering, hesitation, guttural sounds, emphasized reactions")
            parts.append("     Examples:")
            parts.append("       「[gaiji-dakuon_du_s]、う、うぅ……」 → \"U-Uuu...\" (stammering)")
            parts.append("       「[gaiji-dakuon-n]っ!?」 → \"Ngh?!\" (startled grunt)")
            parts.append("       「[gaiji-dakuon-na]っ……」 → \"Ngh...\" (suppressed sound)")
            parts.append("     Action: Render as phonetic sound effect matching emotional context")
            parts.append("")
            parts.append("  2. gaiji-exclhatena (exclamation + はてな)")
            parts.append("     Context: Surprised confusion, shocked question")
            parts.append("     Examples:")
            parts.append("       「っ[gaiji-exclhatena]」 → \"!?\" (standalone reaction)")
            parts.append("       「え[gaiji-exclhatena]」 → \"Eh!?\" (questioning surprise)")
            parts.append("     Action: Replace with '!?' punctuation, preserve surrounding dialogue")
            parts.append("")
            parts.append("  3. gaiji-handakuon (半濁音 = semi-voiced marks)")
            parts.append("     Context: Softer emphasis, gentler sounds")
            parts.append("     Action: Render as appropriate soft sound (\"Mm\", \"Hm\", etc.)")
            parts.append("")
            parts.append("  4. Other gaiji patterns:")
            parts.append("     - gaiji-ellipsis → Use standard '...' (remove marker)")
            parts.append("     - gaiji-dash → Use em-dash '—' (remove marker)")
            parts.append("     - gaiji-heart/star → Context-appropriate description or omit if purely decorative")
            parts.append("")
            parts.append("EXECUTION RULES:")
            parts.append("  ✓ ALWAYS remove the [ILLUSTRATION: gaiji-*] marker itself")
            parts.append("  ✓ Preserve surrounding dialogue structure (quotes, punctuation)")
            parts.append("  ✓ Match emotional intensity (hesitation vs. shock vs. emphasis)")
            parts.append("  ✓ Use character voice (timid character = softer sounds, bold character = stronger)")
            parts.append("  ✓ If gaiji appears mid-dialogue, integrate naturally without breaking flow")
        else:
            # English instructions (default)
            parts.append(f"Translate ONLY the Japanese text inside the <source_text> tags to {lang_name}, following all guidelines in the system prompt.")
            parts.append("CRITICAL SCOPE: Ignore any Japanese text that appears in cache/reference/continuity context.")
            parts.append("IMPORTANT: Preserve all [ILLUSTRATION: filename] tags exactly as they appear.")
            parts.append("IMPORTANT: Use contractions naturally (target 80%+ contraction rate).")
            parts.append("IMPORTANT: Avoid AI-isms and formal language patterns.")
            parts.append("")
            parts.append("<!-- GAIJI TRANSCREATION PROTOCOL -->")
            parts.append("CRITICAL: Gaiji markers [ILLUSTRATION: gaiji-*.png] are special character glyphs, NOT real illustrations.")
            parts.append("They represent typographical elements that must be transcreated and the marker REMOVED:")
            parts.append("")
            parts.append("PATTERN RECOGNITION:")
            parts.append("  1. gaiji-dakuon-* (濁音 = voiced marks)")
            parts.append("     Context: Stuttering, hesitation, guttural sounds, emphasized reactions")
            parts.append("     Examples:")
            parts.append("       「[gaiji-dakuon_du_s]、う、うぅ……」 → \"U-Uuu...\" (stammering)")
            parts.append("       「[gaiji-dakuon-n]っ!?」 → \"Ngh?!\" (startled grunt)")
            parts.append("       「[gaiji-dakuon-na]っ……」 → \"Ngh...\" (suppressed sound)")
            parts.append("     Action: Render as phonetic sound effect matching emotional context")
            parts.append("")
            parts.append("  2. gaiji-exclhatena (exclamation + はてな)")
            parts.append("     Context: Surprised confusion, shocked question")
            parts.append("     Examples:")
            parts.append("       「っ[gaiji-exclhatena]」 → \"!?\" (standalone reaction)")
            parts.append("       「え[gaiji-exclhatena]」 → \"Eh!?\" (questioning surprise)")
            parts.append("     Action: Replace with '!?' punctuation, preserve surrounding dialogue")
            parts.append("")
            parts.append("  3. gaiji-handakuon (半濁音 = semi-voiced marks)")
            parts.append("     Context: Softer emphasis, gentler sounds")
            parts.append("     Action: Render as appropriate soft sound (\"Mm\", \"Hm\", etc.)")
            parts.append("")
            parts.append("  4. Other gaiji patterns:")
            parts.append("     - gaiji-ellipsis → Use standard '...' (remove marker)")
            parts.append("     - gaiji-dash → Use em-dash '—' (remove marker)")
            parts.append("     - gaiji-heart/star → Context-appropriate description or omit if purely decorative")
            parts.append("")
            parts.append("EXECUTION RULES:")
            parts.append("  ✓ ALWAYS remove the [ILLUSTRATION: gaiji-*] marker itself")
            parts.append("  ✓ Preserve surrounding dialogue structure (quotes, punctuation)")
            parts.append("  ✓ Match emotional intensity (hesitation vs. shock vs. emphasis)")
            parts.append("  ✓ Use character voice (timid character = softer sounds, bold character = stronger)")
            parts.append("  ✓ If gaiji appears mid-dialogue, integrate naturally without breaking flow")

        return "\n".join(parts)

    def _format_formatting_standards_for_injection(
        self,
        formatting_data: Dict[str, Any],
    ) -> str:
        """
        Format formatting_standards.json for Tier 1 prompt injection.

        Focuses on high-impact punctuation rules and Standard Hepburn romanization
        guidance (ASCII style: no macrons, use ou/oo/ei/ii/uu).
        """
        lines = ["# FORMATTING STANDARDS (Tier 1)\n"]
        lines.append("Apply these rules consistently across all chapters.\n")

        categories = formatting_data.get("pattern_categories", {})
        if not isinstance(categories, dict):
            return "\n".join(lines)

        punctuation = categories.get("punctuation_conversion", {})
        punctuation_patterns = punctuation.get("patterns", []) if isinstance(punctuation, dict) else []
        if punctuation_patterns:
            lines.append("## Punctuation Conversion")
            for pattern in punctuation_patterns:
                if not isinstance(pattern, dict):
                    continue
                jp_symbol = pattern.get("japanese_symbol", "")
                target_en = pattern.get("target_en", "")
                target_vn = pattern.get("target_vn", "")
                rule = pattern.get("rule", "")
                if jp_symbol and rule:
                    target = target_en if self.target_language == "en" else target_vn or target_en
                    if target:
                        lines.append(f"- {jp_symbol} -> {target} | {rule}")
                    else:
                        lines.append(f"- {jp_symbol}: {rule}")
            lines.append("")

        romanization = categories.get("romanization_standards", {})
        romanization_patterns = romanization.get("patterns", []) if isinstance(romanization, dict) else []
        if romanization_patterns:
            lines.append("## Romanization (Standard Hepburn)")
            for pattern in romanization_patterns:
                if not isinstance(pattern, dict):
                    continue
                rule = pattern.get("rule", "")
                if rule:
                    lines.append(f"- {rule}")
                usage_rules = pattern.get("usage_rules", [])
                for usage in usage_rules[:4]:
                    lines.append(f"  - {usage}")

                examples = pattern.get("examples", [])
                for example in examples[:4]:
                    if not isinstance(example, dict):
                        continue
                    jp = example.get("jp", "")
                    correct = example.get("correct", "")
                    incorrect = example.get("incorrect", "")
                    if jp and correct:
                        lines.append(f"  - {jp}: {correct} (not {incorrect})" if incorrect else f"  - {jp}: {correct}")
            lines.append("")

        emphasis = categories.get("emphasis_texture", {})
        emphasis_patterns = emphasis.get("patterns", []) if isinstance(emphasis, dict) else []
        ruby_rule = next(
            (
                p for p in emphasis_patterns
                if isinstance(p, dict) and p.get("id") == "ruby_text_authority"
            ),
            None,
        )
        if isinstance(ruby_rule, dict):
            lines.append("## Ruby/Furigana Priority")
            lines.append(f"- {ruby_rule.get('rule', 'Ruby text is authoritative.')}")
            for usage in ruby_rule.get("usage_rules", [])[:3]:
                lines.append(f"  - {usage}")
            lines.append("")

        lines.append("## Final Checks")
        lines.append("- Keep punctuation normalized (no JP quote brackets in final output).")
        lines.append("- Lock romanization on first appearance and stay consistent chapter-to-chapter.")
        lines.append("- Use ASCII Hepburn long vowels (ou/oo/ei/ii/uu), not macrons.")
        return "\n".join(lines)

    def _format_negative_signals_for_injection(self, negative_signals_data: Dict[str, Any]) -> str:
        """Format negative_signals.json instruction_block for prompt injection.

        The instruction_block.prompt_text array is the authoritative verbatim injection
        text, built from a 40-chapter production audit with inline ICL pairs.
        Falls back to a minimal header if instruction_block is absent.
        """
        instruction_block = negative_signals_data.get('instruction_block', {})
        prompt_text_lines = instruction_block.get('prompt_text', [])
        if prompt_text_lines:
            return "\n".join(prompt_text_lines)

        # Fallback: compact summary from raw pattern data
        meta = negative_signals_data.get('_meta', {})
        version = meta.get('version', '?')
        total_patterns = meta.get('total_patterns', 0)
        lines = [
            f"# NEGATIVE SIGNAL ENFORCEMENT v{version}",
            f"## Source: {meta.get('source', 'QC audit')}",
            f"## Total patterns: {total_patterns} (CRITICAL + MAJOR)",
            "",
            "Avoid the following translation failure modes:",
        ]
        for severity in ['CRITICAL', 'MAJOR']:
            section = negative_signals_data.get(severity, {})
            categories = section.get('categories', {})
            for cat_id, cat_data in categories.items():
                patterns = cat_data.get('patterns', [])
                for p in patterns[:2]:
                    bad = p.get('bad', '')
                    good = p.get('good', '')
                    if bad and good:
                        lines.append(f"- [{severity}] {p.get('id', cat_id)}: ❌ {bad} → ✅ {good}")
        return "\n".join(lines)

    def get_total_rag_size(self) -> int:
        """Get total size of RAG modules in characters."""
        modules = self.load_rag_modules()
        return sum(len(c) for c in modules.values())

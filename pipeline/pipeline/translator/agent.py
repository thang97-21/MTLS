"""
Translator Agent Orchestrator.
Main entry point for Phase 2: Translation.
Supports multi-language configuration (EN, VN, etc.)
"""

import json
import logging
import argparse
import sys
import time
import re
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field

from pipeline.common.gemini_client import GeminiClient
from pipeline.common.anthropic_client import AnthropicClient
from pipeline.common.openrouter_client import OpenRouterLLMClient
from pipeline.common.name_order_normalizer import (
    build_name_order_replacement_map,
    detect_name_order_conflicts,
    normalize_volume_artifacts,
    resolve_name_order_policy,
)
from pipeline.common.chapter_kind import is_afterword_chapter
from pipeline.translator.config import (
    get_gemini_config, get_anthropic_config, get_translator_provider,
    get_translation_config, get_model_name, get_fallback_model_name,
    get_tool_mode_config, get_phase2_openrouter_route,
    is_openrouter_opus_1m_confirmed,
    get_full_prequel_cache_gate_config,
    evaluate_full_prequel_cache_gate,
    FULL_PREQUEL_CACHE_REASON_CODES,
)
from pipeline.translator.prompt_loader import PromptLoader
from pipeline.translator.context_manager import ContextManager
from pipeline.translator.volume_context_aggregator import VolumeContextAggregator
from pipeline.translator.chapter_processor import ChapterProcessor, TranslationResult
from pipeline.translator.continuity_manager import ContinuityPackManager
from pipeline.translator.per_chapter_workflow import PerChapterWorkflow
from pipeline.translator.glossary_lock import GlossaryLock
from pipeline.translator.series_bible import BibleController
from pipeline.translator.cost_audit import (
    build_run_cost_audit,
    merge_chapter_cost_audits,
    write_cost_audit_artifacts,
)
from pipeline.metadata_processor.bible_sync import BibleSyncAgent
from pipeline.post_processor.copyedit_post_pass import CopyeditPostPass
from pipeline.post_processor.translation_brief_agent import AnthropicTranslationBriefAgent
from pipeline.post_processor.volume_bible_update_agent import VolumeBibleUpdateAgent
from pipeline.config import get_target_language, get_language_config, PIPELINE_ROOT
from pipeline.translator.voice_rag_manager import VoiceRAGManager
from pipeline.translator.arc_tracker import ArcTracker


@dataclass
class TranslationReport:
    """Summary report from Translator agent."""
    volume_id: str
    chapters_total: int
    chapters_completed: int
    chapters_failed: int
    total_input_tokens: int
    total_output_tokens: int
    average_quality_score: float
    status: str  # 'completed', 'partial', 'failed'
    started_at: str
    completed_at: str
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
    total_input_cost_usd: float = 0.0
    total_output_cost_usd: float = 0.0
    total_cache_read_cost_usd: float = 0.0
    total_cache_creation_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PreflightInvariantReport:
    """Blocking pre-Phase-2 invariant report."""
    hard_failures: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.hard_failures

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # Changed from INFO to DEBUG for verbose output
    format="[%(levelname)s] %(asctime)s - %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("TranslatorAgent")

# Silence chatty HTTP-level loggers — they flood the log with per-request
# TCP/TLS handshake details and raw JSON parsing traces that are rarely useful.
for _noisy_logger in (
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "anthropic._base_client",
    "anthropic.resources",
    "httpx",
):
    logging.getLogger(_noisy_logger).setLevel(logging.WARNING)

_TOOL_MODE_ORDER = [
    "declare_translation_parameters",
    "validate_glossary_term",
    "lookup_cultural_term",
    "report_translation_qc",
    "flag_structural_constraint",
]

class TranslatorAgent:
    _CHAPTER_ID_PATTERN = re.compile(r"chapter[_\-](\d+)", re.IGNORECASE)
    _EN_CHAPTER_NUM_PATTERN = re.compile(r"\bchapter\s+(\d+)\b", re.IGNORECASE)
    _INLINE_AFTERWORD_PATTERN = re.compile(
        r"(あとがき|後書き|afterword|author(?:'s)?\s+note|postscript)",
        re.IGNORECASE,
    )

    @staticmethod
    def _build_afterword_tone_directive() -> str:
        return (
            "AFTERWORD MODE (chapter type: author note / あとがき): "
            "Use warm, informative, and gratitude-forward prose from the author's perspective. "
            "Do not enforce character voice fingerprints, EPS arc constraints, scene-beat scaffolding, "
            "or story-world localization/honorific policy when it sounds unnatural for an author afterword. "
            "Keep acknowledgements, publication updates, and thanks clear and natural."
        )

    @staticmethod
    def _build_inline_afterword_tone_directive(marker_info: Dict[str, Any]) -> str:
        marker = str(marker_info.get("marker", "あとがき") or "あとがき")
        source = str(marker_info.get("source", "scene_plan") or "scene_plan")
        start_line = marker_info.get("start_line")
        end_line = marker_info.get("end_line")
        if start_line is not None and end_line is not None:
            range_hint = f"JP lines {start_line}-{end_line}"
        elif start_line is not None:
            range_hint = f"JP line {start_line}+"
        else:
            range_hint = "JP range unspecified"
        return (
            "INLINE AFTERWORD OVERRIDE (scene-level author note / あとがき): "
            f"Detected marker '{marker}' from {source} ({range_hint}). "
            "For the afterword segment only, use warm, informative, gratitude-forward author voice; "
            "set narration contraction target to 95%; suspend EPS-band constraints and character voice "
            "fingerprint enforcement while inside that segment."
        )

    def _detect_inline_afterword_segment(
        self,
        scene_plan: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(scene_plan, dict):
            return None

        def _match_marker(value: Any) -> str:
            text = str(value or "").strip()
            if not text:
                return ""
            m = self._INLINE_AFTERWORD_PATTERN.search(text)
            return m.group(1) if m else ""

        pov_tracking = scene_plan.get("pov_tracking")
        if isinstance(pov_tracking, list):
            for seg in pov_tracking:
                if not isinstance(seg, dict):
                    continue
                for key in ("character", "description", "label", "notes", "segment"):
                    marker = _match_marker(seg.get(key, ""))
                    if marker:
                        return {
                            "source": f"pov_tracking.{key}",
                            "marker": marker,
                            "start_line": seg.get("start_line"),
                            "end_line": seg.get("end_line"),
                            "description": seg.get("description", ""),
                        }

        scenes = scene_plan.get("scenes")
        if isinstance(scenes, list):
            for idx, scene in enumerate(scenes, start=1):
                if not isinstance(scene, dict):
                    continue
                for key in (
                    "title",
                    "description",
                    "scene_goal",
                    "transition",
                    "beat_summary",
                    "summary",
                    "notes",
                    "dialogue_register",
                ):
                    marker = _match_marker(scene.get(key, ""))
                    if marker:
                        return {
                            "source": f"scenes[{idx}].{key}",
                            "marker": marker,
                            "start_line": scene.get("start_line"),
                            "end_line": scene.get("end_line"),
                            "description": scene.get("description", "") or scene.get("summary", ""),
                        }
        return None

    def __init__(self, work_dir: Path, target_language: str = None, enable_continuity: bool = False,
                 enable_gap_analysis: bool = False, enable_multimodal: bool = False,
                 use_env_key: bool = False, fallback_model_override: Optional[str] = None,
                 tool_mode: bool = False):
        """
        Initialize TranslatorAgent.

        Args:
            work_dir: Path to the volume working directory.
            target_language: Target language code (e.g., 'en', 'vn').
                            If None, uses current target language from config.
            enable_continuity: Enable schema extraction and continuity features (default: False).
                             ⚠️  ALPHA EXPERIMENTAL - Highly unstable, may cause interruptions.
            enable_gap_analysis: Enable semantic gap analysis (Week 2-3 integration).
                               Detects and guides translation of emotion+action, ruby jokes, and sarcasm.
            enable_multimodal: Enable multimodal visual context injection (default: False).
                             Injects pre-baked visual analysis into translation prompts.
                             Requires Phase 1.6 (mtl.py phase1.6) to have been run first.
        """
        self.work_dir = work_dir
        self.manifest_path = work_dir / "manifest.json"
        self.enable_continuity = enable_continuity
        self.enable_gap_analysis = enable_gap_analysis

        # Language configuration
        self.target_language = target_language if target_language else get_target_language()
        self.lang_config = get_language_config(self.target_language)
        self.language_name = self.lang_config.get('language_name', self.target_language.upper())

        logger.info(f"TranslatorAgent initialized for language: {self.target_language.upper()} ({self.language_name})")
        
        if enable_continuity:
            logger.warning("⚠️  [ALPHA EXPERIMENTAL] Continuity system enabled - highly unstable!")
            logger.warning("   This feature may cause interruptions and requires manual schema review.")
        else:
            logger.info("✓ Using standard translation mode (continuity disabled)")
        
        if enable_gap_analysis:
            logger.info("✓ Gap analysis enabled (Week 2-3 integration)")
            logger.info("  Semantic gaps will be detected and guide translation decisions")

        if not self.manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found at {self.manifest_path}")

        self.manifest = self._load_manifest()
        self._enforce_name_order_guard()
        self._bible_name_order_bypass_reason: Optional[str] = None
        self._bible_import_mode: str = "bypassed"
        self._bible_import_mode_reason: str = "No bible resolved"
        self.translation_config = get_translation_config()
        self._setup_project_debug_logging()
        self._effective_book_type = self._resolve_book_type()
        self._genre = self._resolve_genre()
        self._tool_mode_cli_requested = bool(tool_mode)
        self.tool_mode_config = self._resolve_tool_mode_config(cli_enabled=tool_mode)
        self._tool_mode_requested = bool(
            self.tool_mode_config.get(
                "configured_enabled",
                self.tool_mode_config.get("enabled", False),
            )
        )
        self.tool_mode_enabled = bool(self.tool_mode_config.get("enabled", False))
        self._tool_mode_auto_disabled_reason = self.tool_mode_config.get(
            "auto_disabled_reason"
        )
        self._tool_mode_provider_gate_reason: Optional[str] = None
        self._fallback_model_override = (str(fallback_model_override).strip() if fallback_model_override else None)
        if self._fallback_model_override:
            logger.info(f"[PHASE2] Retry fallback model override: {self._fallback_model_override}")

        massive_cfg = self.translation_config.get("massive_chapter", {})
        self.volume_cache_enabled = massive_cfg.get("enable_volume_cache", True)
        self.volume_cache_ttl_seconds = int(massive_cfg.get("volume_cache_ttl_seconds", 7200))
        self.volume_cache_name: Optional[str] = None
        self._volume_cache_stats: Dict[str, Any] = {}
        self._full_prequel_gate_config = get_full_prequel_cache_gate_config()
        self._full_prequel_gate_decision: Dict[str, Any] = {
            "requested": bool(self._full_prequel_gate_config.get("enabled", False)),
            "allowed": False,
            "active_mode": str(self._full_prequel_gate_config.get("fallback_mode", "series_bible_rag")),
            "fallback_mode": str(self._full_prequel_gate_config.get("fallback_mode", "series_bible_rag")),
            "reason_code": FULL_PREQUEL_CACHE_REASON_CODES["default_rag_mode"],
            "reason": "Gate not evaluated yet.",
            "context_tokens_estimate": 0,
            "context_tokens_ceiling": 0,
            "runtime_fallback": False,
            "events": [],
        }
        self._full_prequel_5xx_streak = 0
        
        # Auto-detect enable_multimodal from config.yaml if not explicitly set
        if not enable_multimodal:
            enable_multimodal = self.translation_config.get('enable_multimodal', False)
            if enable_multimodal:
                logger.info("✓ Multimodal translation enabled (config.yaml)")
        
        self.enable_multimodal = enable_multimodal

        if self.enable_multimodal:
            logger.info("✓ Multimodal visual analysis active")
            logger.info("  Pre-baked visual context will be injected into translation prompts")

        # Initialize translator LLM client — provider-routed
        provider = get_translator_provider()
        self.translator_provider = provider
        logger.info(f"Translator provider: {provider.upper()}")
        if self._tool_mode_auto_disabled_reason and not self._tool_mode_cli_requested:
            logger.info("[TOOL-MODE] %s", self._tool_mode_auto_disabled_reason)
        if self.tool_mode_enabled and provider != "anthropic":
            self._tool_mode_provider_gate_reason = (
                f"Tool mode was requested, but provider '{provider}' does not support "
                "translator tool integration."
            )
            logger.warning(
                "[TOOL-MODE] Enabled but translator provider is %s. Disabling tool mode.",
                provider,
            )
            self.tool_mode_enabled = False
            self.tool_mode_config["enabled"] = False
        elif self.tool_mode_enabled:
            logger.info("✓ Claude tool mode enabled for streaming chapter translation")
        gemini_config = get_gemini_config()
        self._gemini_subagent_config = gemini_config

        if provider == "anthropic":
            anthropic_cfg = get_anthropic_config()
            model_name = anthropic_cfg.get("model", "claude-sonnet-4-6")
            phase2_or_route = get_phase2_openrouter_route()
            route_enabled = bool(phase2_or_route.get("enabled", False))

            if route_enabled:
                configured_base_url = phase2_or_route.get("base_url")
                configured_api_key_env = phase2_or_route.get("api_key_env", "OPENROUTER_API_KEY")
                configured_api_key = os.getenv(str(configured_api_key_env).strip() or "OPENROUTER_API_KEY")
                logger.info(
                    "[ROUTER] Phase 2 OpenRouter route enabled (endpoint=%s, api_key_env=%s)",
                    configured_base_url,
                    configured_api_key_env,
                )
            else:
                configured_base_url = anthropic_cfg.get("base_url")
                configured_api_key_env = anthropic_cfg.get("api_key_env", "ANTHROPIC_API_KEY")
                configured_api_key = os.getenv(str(configured_api_key_env).strip() or "ANTHROPIC_API_KEY")
                logger.info("[ROUTER] Phase 2 legacy direct Anthropic route enabled")
            
            # If not explicitly passed via CLI, fallback to config.yaml
            if route_enabled:
                # OpenRouter path must not force-reset to api.anthropic.com.
                use_env_key = False
            elif not use_env_key:
                use_env_key = anthropic_cfg.get("use_env_key", False)
                
            caching_cfg = anthropic_cfg.get("caching", {})
            enable_caching = caching_cfg.get("enabled", True)
            cache_ttl_minutes = caching_cfg.get("ttl_minutes", 5)  # default 5m (free refresh)
            batch_cfg = anthropic_cfg.get("batch", {}) if isinstance(anthropic_cfg, dict) else {}
            batch_promote_ttl_1h = bool(batch_cfg.get("promote_cache_ttl_1h", True))
            fast_mode_cfg = anthropic_cfg.get("fast_mode", {})
            enable_fast_mode = fast_mode_cfg.get("enabled", False)
            fast_mode_fallback = fast_mode_cfg.get("fallback_on_rate_limit", True)
            logger.info(f"Using model: {model_name}")
            if enable_caching:
                ttl_label = "5m" if cache_ttl_minutes <= 5 else "1h"
                if ttl_label == "5m" and batch_promote_ttl_1h:
                    logger.info(
                        "✓ Anthropic prompt caching enabled "
                        "(ephemeral, TTL=5m -> 1h auto-promote in batch)"
                    )
                else:
                    logger.info(f"✓ Anthropic prompt caching enabled (ephemeral, TTL={ttl_label})")
            if enable_fast_mode:
                logger.info("✓ Opus fast mode enabled (up to 2.5x OTPS, beta)")
            if route_enabled:
                routed_model = model_name if "/" in str(model_name) else f"anthropic/{model_name}"
                self.client = OpenRouterLLMClient(
                    api_key=configured_api_key,
                    model=routed_model,
                    enable_caching=enable_caching,
                    timeout_seconds=float(anthropic_cfg.get("http_timeout_seconds", 600) or 600),
                    base_url=configured_base_url,
                )
                if self.tool_mode_enabled:
                    self.tool_mode_enabled = False
                    self.tool_mode_config["enabled"] = False
                    logger.info(
                        "[TOOL-MODE] Disabled for OpenRouter route: chat-completions adapter "
                        "does not run Anthropic tool-loop execution."
                    )
            else:
                self.client = AnthropicClient(
                    api_key=configured_api_key,
                    model=model_name,
                    enable_caching=enable_caching,
                    fast_mode=enable_fast_mode,
                    fast_mode_fallback=fast_mode_fallback,
                    use_env_key=use_env_key,
                    api_key_env=configured_api_key_env,
                    base_url=configured_base_url,
                )
            self.client.set_cache_ttl(cache_ttl_minutes)
            # Sub-agents (summarizer, etc.) always use Gemini — keep a dedicated client
            self._gemini_subagent_client = GeminiClient(
                model=gemini_config.get("fallback_model", "gemini-2.5-flash"),
                enable_caching=False,
            )
        else:
            model_name = get_model_name()
            logger.info(f"Using model: {model_name}")
            caching_config = gemini_config.get("caching", {})
            enable_caching = caching_config.get("enabled", True)
            cache_ttl = caching_config.get("ttl_minutes", 120)
            if enable_caching:
                logger.info(f"✓ Context caching enabled (TTL: {cache_ttl} minutes)")
            else:
                logger.info("Context caching disabled")
            self.client = GeminiClient(model=model_name, enable_caching=enable_caching)
            self.client.set_cache_ttl(cache_ttl)
            self._gemini_subagent_client = self.client  # same client for all agents

        # Active model name — used by cache/prewarm helpers (provider-agnostic)
        self._active_model_name = model_name

        # Initialize PromptLoader with target language
        self.prompt_loader = PromptLoader(target_language=self.target_language)
        title_philosophy = self.manifest.get("title_philosophy", {})
        if isinstance(title_philosophy, dict):
            motif_directive = str(title_philosophy.get("motif_catchphrase_directive", "") or "").strip()
            if motif_directive:
                self.prompt_loader.set_title_motif_catchphrase_directive(motif_directive)
                logger.info("[TITLE MOTIF] Loaded catchphrase directive from manifest.title_philosophy")
        # Set genre for JIT literacy_techniques injection
        if self._genre:
            self.prompt_loader.set_genre(self._genre)

        # Set book_type from manifest metadata (gates LN-specific modules for memoir/non-fiction)
        _manifest_meta = self.manifest.get("metadata", {})
        _book_type = self._effective_book_type
        if _book_type:
            self.prompt_loader.set_book_type(_book_type)

        # Load style guide for Vietnamese translations (genre-specific selection)
        if self.target_language in ['vi', 'vn']:
            logger.info("Loading Vietnamese style guide system...")
            try:
                # Extract publisher from manifest if available
                publisher = self.manifest.get('publisher_id', 'overlap')
                
                # Determine genre from manifest metadata (default to romcom for modern settings)
                genre_from_manifest = self.manifest.get('genre', 'romcom_school_life')

                # Memoir/autobiography override: book_type takes priority over manifest.genre.
                # When book_type signals non-fiction, always load the autobiography_memoir
                # style guide — it carries the CRITICAL_ANTI_HEDGING_RULE (absolute), temporal
                # framing markers, inner-monologue patterns, and memoir-specific ICL examples.
                _bt = (_book_type or "").lower().strip()
                _memoir_book_types = {
                    "memoir", "autobiography", "biography",
                    "non_fiction", "non-fiction", "essay",
                    "自伝", "ノンフィクション", "散文",
                }
                if _bt in _memoir_book_types:
                    genres_to_load = ["autobiography_memoir"]
                    # Signal memoir mode to prompt_loader so it activates the
                    # music-industry vocabulary supplement and absolute anti-hedging guard.
                    self.prompt_loader.set_book_type(_bt)
                    logger.info(
                        f"[MEMOIR MODE] book_type='{_bt}' → loading autobiography_memoir "
                        f"style guide + music_industry_vocabulary supplement"
                    )
                else:
                    genres_to_load = [genre_from_manifest] if genre_from_manifest else ['romcom_school_life']

                # Load specific genre (not all genres - avoids fantasy rules in modern romcom)
                self.prompt_loader.load_style_guide(genres=genres_to_load, publisher=publisher)
            except Exception as e:
                logger.warning(f"Failed to load style guide: {e}")
                logger.warning("Continuing without style guide (translation quality may be reduced)")

        # Load style guide for EN memoir translations
        # EN non-memoir uses no style guide (standard grammar RAG handles it).
        # EN memoir loads autobiography_memoir_en.json — anti-hedging, temporal framing,
        # inner-monologue, and 40-term music vocabulary are all embedded in that guide.
        elif self.target_language == 'en':
            _bt_en = (_book_type or "").lower().strip()
            _memoir_book_types_en = {
                "memoir", "autobiography", "biography",
                "non_fiction", "non-fiction", "essay",
                "自伝", "ノンフィクション", "散文",
            }
            if _bt_en in _memoir_book_types_en:
                logger.info("Loading English memoir style guide system...")
                try:
                    self.prompt_loader.load_style_guide(
                        genres=['autobiography_memoir'], publisher=None
                    )
                    logger.info(
                        f"[EN MEMOIR MODE] book_type='{_bt_en}' → loaded "
                        f"autobiography_memoir_en style guide "
                        f"(anti-hedging + temporal framing + music vocabulary)"
                    )
                except Exception as e:
                    logger.warning(f"Failed to load EN memoir style guide: {e}")
                    logger.warning("Continuing without style guide (translation quality may be reduced)")

        self.context_manager = ContextManager(work_dir)

        # ── Bible System (Phase C) ─────────────────────────────────
        # Load series bible BEFORE glossary — bible terms supplement manifest names
        self.bible = None
        self._bible_glossary = {}
        try:
            bible_ctrl = BibleController(PIPELINE_ROOT)
            self.bible = bible_ctrl.load(self.manifest, work_dir)
            if self.bible:
                bypass_reason = self._detect_bible_name_order_bypass_reason(self.bible)
                self._bible_name_order_bypass_reason = bypass_reason
                self._bible_import_mode, self._bible_import_mode_reason = self._resolve_bible_import_mode(
                    self.bible,
                    bypass_reason,
                )

                stats = self.bible.stats()
                logger.info(
                    "[BIBLE-MODE] %s | %s",
                    self._bible_import_mode,
                    self._bible_import_mode_reason,
                )
                logger.info(f"✓ Series Bible loaded: {self.bible.series_id}")
                logger.info(f"  {stats['total_entries']} entries across {stats['volumes']} volumes")

                if self._bible_import_mode == "canon_safe":
                    self._bible_glossary = self.bible.flat_glossary()
                    logger.info(f"  Bible glossary: {len(self._bible_glossary)} terms")
                    # Phase E: Manifest overrides bible for volume-specific settings
                    self._apply_manifest_world_setting_override()
                    # Phase E: Inject bible prompt + world directive + dedup keys
                    bible_prompt = self.bible.format_for_prompt()
                    world_directive = self.bible.format_world_setting_directive()
                    self.prompt_loader.set_series_bible_prompt(
                        bible_prompt,
                        world_directive=world_directive,
                        bible_glossary_keys=set(self._bible_glossary.keys())
                    )
                elif self._bible_import_mode == "continuity_only":
                    self._bible_glossary = {}
                    logger.warning(
                        "[BIBLE-MODE] continuity_only active: suppressing bible glossary/prompt injection; "
                        "allowing continuity hydration only"
                    )
                else:
                    logger.warning("[BIBLE-MODE] bypassed: skipping bible usage for this run")
                    self.bible = None
                    self._bible_glossary = {}
            else:
                self._bible_import_mode = "bypassed"
                self._bible_import_mode_reason = "No series bible found for this volume"
                logger.info(
                    "[BIBLE-MODE] %s | %s",
                    self._bible_import_mode,
                    self._bible_import_mode_reason,
                )
                logger.debug("No series bible found for this volume (standalone)")
        except Exception as e:
            # Hard fallback path: ignore bible and continue with manifest-only continuity.
            self.bible = None
            self._bible_glossary = {}
            self._bible_import_mode = "bypassed"
            self._bible_import_mode_reason = f"Bible system error: {e}"
            logger.warning(
                f"Bible system error (non-fatal): {e}. "
                "Falling back to manifest-based continuity."
            )
        self._log_world_localization_profile()

        # ── Koji Fox Voice System ──────────────────────────────────────────────
        self._voice_rag = VoiceRAGManager(work_dir)
        self._arc_tracker = ArcTracker(work_dir)
        try:
            n_voices = self._voice_rag.index_from_manifest()
            n_carried_arcs = self._arc_tracker.hydrate_from_bible(self.bible) if self.bible else 0
            n_arcs = self._arc_tracker.sync_from_manifest()
            if n_voices:
                logger.info(f"✓ Koji Fox: {n_voices} voice fingerprint(s) indexed")
            if n_carried_arcs:
                logger.info(f"✓ Koji Fox: {n_carried_arcs} carried-forward EPS state(s) loaded from bible")
            if n_arcs:
                logger.info(f"✓ Koji Fox: {n_arcs} EPS arc record(s) synced")
        except Exception as e:
            logger.warning(f"Koji Fox init non-fatal: {e}")

        # Load and inject character names from manifest (for cached system instruction)
        character_names = self._load_character_names()
        self.glossary_lock = GlossaryLock(
            work_dir,
            target_language=self.target_language,
            bible_glossary=self._bible_glossary
        )
        locked_glossary = self.glossary_lock.get_locked_names()
        if locked_glossary:
            logger.info(f"✓ GlossaryLock loaded {len(locked_glossary)} locked name mappings")
        else:
            logger.warning("GlossaryLock found no manifest name mappings; name drift checks may be weaker")
        
        # Load full semantic metadata (Enhanced v2.1)
        semantic_metadata = self._load_semantic_metadata()
        
        if character_names:
            self.prompt_loader.set_character_names(character_names)
            logger.info(f"✓ Character names loaded and set for caching ({len(character_names)} entries)")
            if locked_glossary:
                self.prompt_loader.set_glossary(locked_glossary)
                logger.info(f"✓ Loaded {len(locked_glossary)} locked glossary terms from manifest")
        elif locked_glossary:
            self.prompt_loader.set_glossary(locked_glossary)
            logger.info(f"✓ Loaded {len(locked_glossary)} locked glossary terms from manifest")
        
        # Inject semantic metadata (Enhanced v2.1) into system instruction
        if semantic_metadata:
            self.prompt_loader.set_semantic_metadata(semantic_metadata)
            char_count = len(semantic_metadata.get('characters', []))
            pattern_count = len(semantic_metadata.get('dialogue_patterns', {}))
            scene_count = len(semantic_metadata.get('scene_contexts', {}))
            logger.info(f"✓ Semantic metadata injected: {char_count} characters, {pattern_count} dialogue patterns, {scene_count} scenes")

        # Inject ECR volume-level directives (culturally_loaded_terms, author_signature_patterns,
        # character_voice_fingerprints, signature_phrases) from metadata_en into system instruction.
        ecr_meta = self._load_ecr_metadata()
        self.prompt_loader.set_ecr_directives(
            culturally_loaded_terms=ecr_meta.get('culturally_loaded_terms', {}),
            author_signature_patterns=ecr_meta.get('author_signature_patterns', {}),
            character_voice_fingerprints=ecr_meta.get('character_voice_fingerprints', []),
            signature_phrases=ecr_meta.get('signature_phrases', []),
        )

        self.processor = ChapterProcessor(
            self.client,
            self.prompt_loader,
            self.context_manager,
            target_language=self.target_language,
            work_dir=self.work_dir,
            tool_mode_config=self.tool_mode_config,
        )
        self.processor.set_glossary_lock(self.glossary_lock)

        # Propagate series identity + flat glossary so ChapterProcessor can activate
        # SeriesBibleRAG (ships at 200K; requires ./mtl index-series-bible <series_id>).
        if self.bible:
            if self._bible_import_mode == "canon_safe":
                self.processor._series_id = self.bible.series_id
                self.processor._bible_glossary = self._bible_glossary  # already computed above
                logger.debug(
                    f"[BIBLE-RAG] Set processor._series_id={self.bible.series_id!r}, "
                    f"{len(self._bible_glossary)} glossary terms available"
                )
            else:
                logger.info(
                    "[BIBLE-RAG] disabled (mode=%s)",
                    self._bible_import_mode,
                )

        # Bible pull context becomes the default volume-context source for Phase 2.
        self.bible_sync_agent = BibleSyncAgent(self.work_dir, PIPELINE_ROOT)
        self.bible_pull_context_block: Optional[str] = None
        try:
            resolved_for_pull = False
            if self.bible:
                self.bible_sync_agent.bible = self.bible
                self.bible_sync_agent.series_id = self.bible.series_id
                resolved_for_pull = True
            elif self.manifest.get("bible_id") and self._bible_import_mode == "canon_safe":
                resolved_for_pull = self.bible_sync_agent.resolve(self.manifest)
            elif self._bible_name_order_bypass_reason:
                logger.warning(
                    "[BIBLE BYPASS] Skipping Bible pull context for this run: %s",
                    self._bible_name_order_bypass_reason,
                )

            if resolved_for_pull:
                pull_result = self.bible_sync_agent.pull(
                    self.manifest,
                    target_language=self.target_language.lower(),
                    import_mode=self._bible_import_mode,
                )
                if pull_result.context_block:
                    self.bible_pull_context_block = pull_result.context_block
                    self.processor.set_bible_context_block(self.bible_pull_context_block)
                    logger.info(
                        f"[BIBLE-CTX] Loaded pull context block "
                        f"({len(self.bible_pull_context_block):,} chars)"
                    )
                else:
                    logger.warning("[BIBLE-CTX] Pull returned empty context block")
            else:
                logger.info("[BIBLE-CTX] No resolved bible for pull context; running without bible context block")
        except Exception as e:
            logger.warning(f"[BIBLE-CTX] Failed to load pull context block: {e}")

        # Initialize multimodal visual cache if enabled
        self.visual_cache_manager = None
        if self.enable_multimodal:
            try:
                from modules.multimodal.cache_manager import VisualCacheManager
                self.visual_cache_manager = VisualCacheManager(work_dir)
                if self.visual_cache_manager.has_cache():
                    stats = self.visual_cache_manager.get_cache_stats()
                    logger.info(f"✓ Visual cache loaded: {stats['total']} entries "
                               f"({stats['cached']} cached, {stats['safety_blocked']} blocked, "
                               f"{stats['manual_override']} manual)")
                    logger.info(
                        "[MULTIMODAL] visual_cache.json attached to translator: "
                        "inline=%s kuchie=%s cover=%s",
                        stats.get("inline", 0),
                        stats.get("kuchie", 0),
                        stats.get("cover", 0),
                    )
                    # Connect to processor
                    self.processor.enable_multimodal = True
                    self.processor.visual_cache = self.visual_cache_manager
                else:
                    logger.warning("⚠️  No visual cache found. Run 'mtl.py phase1.6 <volume_id>' first.")
                    logger.warning("   Continuing without multimodal context (text-only mode)")
                    self.enable_multimodal = False
            except Exception as e:
                logger.warning(f"Failed to initialize multimodal: {e}")
                logger.warning("Continuing without multimodal context")
                self.enable_multimodal = False

        # Initialize gap analyzer if enabled (Week 2-3 integration)
        if self.enable_gap_analysis:
            try:
                from modules.gap_integration import GapIntegrationEngine
                self.gap_analyzer = GapIntegrationEngine(self.work_dir, target_language=self.target_language)
                # Enable gap analysis in processor
                self.processor.enable_gap_analysis = True
                self.processor.gap_analyzer = self.gap_analyzer
                logger.info("✓ Gap analyzer initialized and connected to processor")
            except Exception as e:
                logger.warning(f"Failed to initialize gap analyzer: {e}")
                logger.warning("Continuing without gap analysis")
                self.enable_gap_analysis = False
                self.gap_analyzer = None
        else:
            self.gap_analyzer = None

        # Translation Log
        self.log_path = work_dir / "translation_log.json"
        self.translation_log = self._load_log()

        # Inline chapter summarizer is retired from Phase 2 loops.
        if self.translation_config.get("enable_chapter_summarizer", False):
            logger.info(
                "[CH-SUMMARY] Deprecated for inline Phase 2 context. "
                "Use Phase 2.5 volume bible update instead."
            )
        self.enable_chapter_summarizer = False
        self.chapter_summarizer = None

        # Phase 2.5 (optional): post-translation bible update after QC clearance.
        phase25_cfg = self.translation_config.get("phase_2_5", {})
        if not isinstance(phase25_cfg, dict):
            phase25_cfg = {}
        self._phase25_run_enabled = bool(phase25_cfg.get("run_bible_update", False))
        self._phase25_qc_cleared = bool(phase25_cfg.get("qc_cleared", False))
        self.bible_update_agent: Optional[VolumeBibleUpdateAgent] = None
        if self._phase25_run_enabled and self.bible_sync_agent and self.bible_sync_agent.bible:
            self.bible_update_agent = VolumeBibleUpdateAgent(
                gemini_client=self._gemini_subagent_client,
                bible_sync=self.bible_sync_agent,
                work_dir=self.work_dir,
                model=str(
                    phase25_cfg.get("model")
                    or gemini_config.get("model")
                    or "gemini-2.5-pro"
                ),
                max_output_tokens=int(phase25_cfg.get("max_output_tokens", 65535)),
            )
            logger.info(
                "[PHASE 2.5] Volume bible update agent initialized "
                f"(qc_cleared={self._phase25_qc_cleared})"
            )
        elif self._phase25_run_enabled:
            if self._bible_import_mode == "bypassed" and self._bible_name_order_bypass_reason:
                logger.warning(
                    "[PHASE 2.5] Requested but skipped: Bible was bypassed for this run (%s)",
                    self._bible_name_order_bypass_reason,
                )
            else:
                logger.warning(
                    "[PHASE 2.5] Requested but skipped: no resolved series bible available"
                )
        
        # Per-Chapter Workflow (schema extraction, review, caching)
        self.per_chapter_workflow = PerChapterWorkflow(
            work_dir=work_dir,
            target_language=self.target_language,
            enable_caching=enable_caching,
            gemini_client=self.client.client if hasattr(self.client, 'client') else None
        )

    def _load_ecr_metadata(self) -> Dict:
        """Load ECR fields from metadata_en.json (or manifest[\"metadata_en\"] fallback).

        Returns a dict containing whatever subset of the four ECR keys is present:
          culturally_loaded_terms, author_signature_patterns,
          character_voice_fingerprints, signature_phrases

        ECR fields are written exclusively by schema_autoupdate into metadata_en;
        they are not language-specific so no target-language variant is checked.
        """
        _ECR_KEYS = (
            'culturally_loaded_terms',
            'author_signature_patterns',
            'character_voice_fingerprints',
            'signature_phrases',
        )
        try:
            # Prefer standalone metadata_en.json (written by phase 1.5)
            metadata_en_path = self.work_dir / 'metadata_en.json'
            if metadata_en_path.exists():
                with open(metadata_en_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                if isinstance(meta, dict):
                    extracted = {k: meta[k] for k in _ECR_KEYS if k in meta}
                    if extracted:
                        total = sum(
                            len(v) if isinstance(v, (dict, list)) else int(bool(v))
                            for v in extracted.values()
                        )
                        logger.info(
                            f"[ECR] Loaded ECR metadata from metadata_en.json: "
                            f"{list(extracted.keys())} ({total} entries)"
                        )
                        return extracted

            # Fallback: manifest['metadata_en']
            if self.manifest:
                meta = self.manifest.get('metadata_en', {})
                if isinstance(meta, dict):
                    extracted = {k: meta[k] for k in _ECR_KEYS if k in meta}
                    if extracted:
                        total = sum(
                            len(v) if isinstance(v, (dict, list)) else int(bool(v))
                            for v in extracted.values()
                        )
                        logger.info(
                            f"[ECR] Loaded ECR metadata from manifest.json metadata_en: "
                            f"{list(extracted.keys())} ({total} entries)"
                        )
                        return extracted

            logger.debug("[ECR] No ECR metadata found (no metadata_en.json and no manifest metadata_en)")
            return {}

        except Exception as e:
            logger.warning(f"[ECR] Failed to load ECR metadata (non-fatal): {e}")
            return {}

    def _load_character_names(self) -> Dict[str, str]:
        """
        Load character names from language-specific metadata file.

        Character names are injected into prompt cache for stronger name consistency
        (in addition to the richer semantic metadata payload).
        """
        try:
            # Try language-specific metadata file first (preferred)
            metadata_lang_path = self.work_dir / f"metadata_{self.target_language}.json"
            if metadata_lang_path.exists():
                with open(metadata_lang_path, 'r', encoding='utf-8') as f:
                    metadata_lang = json.load(f)
                    if isinstance(metadata_lang, dict):
                        return metadata_lang.get('character_names', {})
            
            # Fallback to metadata_en for backward compatibility
            # Gate: skip metadata_en.json if manifest.metadata_en is already populated
            if self.manifest:
                manifest_meta_en = self.manifest.get('metadata_en', {})
                if manifest_meta_en and isinstance(manifest_meta_en, dict):
                    char_names = manifest_meta_en.get('character_names', {})
                    if char_names:
                        return char_names

            metadata_en_path = self.work_dir / "metadata_en.json"
            if metadata_en_path.exists():
                with open(metadata_en_path, 'r', encoding='utf-8') as f:
                    metadata_en = json.load(f)
                    if isinstance(metadata_en, dict):
                        return metadata_en.get('character_names', {})
            
            # Fallback to manifest.json
            if self.manifest:
                metadata_key = f'metadata_{self.target_language}'
                metadata_lang = self.manifest.get(metadata_key, {})
                if isinstance(metadata_lang, dict) and metadata_lang:
                    return metadata_lang.get('character_names', {})
                # Last resort: metadata_en from manifest
                metadata_en = self.manifest.get('metadata_en', {})
                if not isinstance(metadata_en, dict):
                    return {}
                return metadata_en.get('character_names', {})
            
            return {}
            
        except Exception as e:
            logger.warning(f"Failed to load character names: {e}")
            return {}
    
    def _load_semantic_metadata(self) -> Dict:
        """
        Load full semantic metadata from language-specific metadata file.
        
        Supports both Enhanced v2.1 schema AND legacy V2 schema (backward compatible).
        
        Enhanced v2.1 schema fields:
        - characters: Full profiles with pronouns/relationships
        - dialogue_patterns: Speech fingerprints per character
        - scene_contexts: Location-based formality guidance
        - emotional_pronoun_shifts: State machines for dynamic pronouns
        - translation_guidelines: Priority system and quality markers
        
        Legacy V2 schema fields (auto-transformed):
        - character_profiles → characters
        - localization_notes → translation_guidelines
        - character_profiles.{name}.speech_pattern → dialogue_patterns
        
        Returns:
            Dictionary containing semantic metadata or empty dict if not found
        """
        try:
            # Load from metadata_{language}.json (preferred)
            metadata_lang_path = self.work_dir / f"metadata_{self.target_language}.json"
            if metadata_lang_path.exists():
                with open(metadata_lang_path, 'r', encoding='utf-8') as f:
                    full_metadata = json.load(f)
                    semantic_data = self._extract_semantic_metadata(full_metadata if isinstance(full_metadata, dict) else {})
                    
                    if semantic_data:
                        schema_type = "Enhanced v2.1" if 'characters' in full_metadata else "Legacy V2 (transformed)"
                        logger.info(f"✓ Loaded semantic metadata ({schema_type}) from {metadata_lang_path.name}")
                        return semantic_data
                    else:
                        logger.debug("No semantic metadata found in metadata file")
            
            # Fallback to manifest.json
            if self.manifest:
                metadata_key = f'metadata_{self.target_language}'
                metadata_lang = self.manifest.get(metadata_key, {})
                
                if isinstance(metadata_lang, dict) and metadata_lang:
                    semantic_data = self._extract_semantic_metadata(metadata_lang)
                    
                    if semantic_data:
                        schema_type = "Enhanced v2.1" if 'characters' in metadata_lang else "Legacy V2 (transformed)"
                        logger.info(f"✓ Loaded semantic metadata ({schema_type}) from manifest.json")
                        return semantic_data
            
            return {}
            
        except Exception as e:
            logger.warning(f"Failed to load semantic metadata: {e}")
            return {}
    
    def _extract_semantic_metadata(self, full_metadata: Dict) -> Dict:
        """
        Extract semantic metadata from any of the three schema variants:
        
        1. Enhanced v2.1 schema (preferred): characters, dialogue_patterns, scene_contexts...
        2. Legacy V2 schema: character_profiles, localization_notes
        3. V4 nested schema: character_names with nested objects containing relationships/traits
        
        Handles all schema versions with automatic transformation.
        """
        if not isinstance(full_metadata, dict):
            return {}

        semantic_data = {}
        
        # ===== ENHANCED V2.1 SCHEMA (preferred) =====
        if 'characters' in full_metadata:
            semantic_data['characters'] = full_metadata['characters']
        if 'dialogue_patterns' in full_metadata:
            semantic_data['dialogue_patterns'] = full_metadata['dialogue_patterns']
        if 'scene_contexts' in full_metadata:
            semantic_data['scene_contexts'] = full_metadata['scene_contexts']
        if 'emotional_pronoun_shifts' in full_metadata:
            semantic_data['emotional_pronoun_shifts'] = full_metadata['emotional_pronoun_shifts']
        if 'translation_guidelines' in full_metadata:
            raw_guidelines = full_metadata.get('translation_guidelines')
            if isinstance(raw_guidelines, dict):
                semantic_data['translation_guidelines'] = raw_guidelines
            elif raw_guidelines:
                logger.warning(
                    "translation_guidelines present but not dict; ignoring invalid value "
                    f"(type={type(raw_guidelines).__name__})"
                )
        
        # ===== LEGACY V2 SCHEMA (backward compatibility) =====
        # Transform character_profiles → characters (if not already present)
        if 'character_profiles' in full_metadata and 'characters' not in semantic_data:
            transformed_characters = self._transform_character_profiles(full_metadata['character_profiles'])
            if transformed_characters:
                semantic_data['characters'] = transformed_characters
                logger.debug(f"  → Transformed {len(transformed_characters)} character_profiles to characters format")
        
        # Transform localization_notes → translation_guidelines.
        # If translation_guidelines exists but is empty/partial, fill gaps from transformed notes.
        if 'localization_notes' in full_metadata:
            transformed_guidelines = self._transform_localization_notes(full_metadata['localization_notes'])
            if transformed_guidelines:
                existing_guidelines = semantic_data.get('translation_guidelines')
                if isinstance(existing_guidelines, dict) and existing_guidelines:
                    merged_guidelines = self._merge_translation_guidelines(
                        primary=existing_guidelines,
                        fallback=transformed_guidelines
                    )
                    semantic_data['translation_guidelines'] = merged_guidelines
                    if merged_guidelines != existing_guidelines:
                        logger.debug(
                            "  → Merged localization_notes into translation_guidelines "
                            "(filled empty/missing guideline fields)"
                        )
                else:
                    semantic_data['translation_guidelines'] = transformed_guidelines
                    logger.debug(
                        "  → Fallback: translation_guidelines empty/missing, "
                        "using transformed localization_notes"
                    )
        
        # Extract dialogue_patterns from character_profiles speech_pattern (if not already present)
        if 'character_profiles' in full_metadata and 'dialogue_patterns' not in semantic_data:
            dialogue_patterns = self._extract_dialogue_patterns(full_metadata['character_profiles'])
            if dialogue_patterns:
                semantic_data['dialogue_patterns'] = dialogue_patterns
                logger.debug(f"  → Extracted {len(dialogue_patterns)} dialogue_patterns from character_profiles")
        
        # V4 NESTED SCHEMA REMOVED (Phase 0) — no volume uses this format.
        # character_names with dict values is not generated by any code path.
        
        return semantic_data

    @staticmethod
    def _is_empty_guideline_value(value: Any) -> bool:
        """Return True when a guideline value is effectively empty."""
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip() == ""
        if isinstance(value, (list, tuple, set, dict)):
            return len(value) == 0
        return False

    def _merge_translation_guidelines(self, primary: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge translation guideline dicts while preserving explicit primary values.

        Rules:
        - Keep non-empty values from primary.
        - Fill empty/missing values from fallback.
        - For nested dicts, fill empty/missing nested keys from fallback.
        """
        merged: Dict[str, Any] = dict(primary)
        for key, fallback_value in fallback.items():
            if key not in merged or self._is_empty_guideline_value(merged.get(key)):
                merged[key] = fallback_value
                continue

            primary_value = merged.get(key)
            if isinstance(primary_value, dict) and isinstance(fallback_value, dict):
                nested = dict(primary_value)
                for nested_key, nested_fallback in fallback_value.items():
                    if (
                        nested_key not in nested
                        or self._is_empty_guideline_value(nested.get(nested_key))
                    ):
                        nested[nested_key] = nested_fallback
                merged[key] = nested

        return merged
    
    # _transform_v4_character_names REMOVED (Phase 0) — dead code, no volume uses V4 nested schema.
    
    def _transform_character_profiles(self, profiles: Dict) -> List[Dict]:
        """
        Transform legacy character_profiles dict to Enhanced v2.1 characters list.
        
        Legacy V2: {"ティグル＝ヴォルン": {"full_name": "Tigrevurmud Vorn", "pronouns": "he/him", ...}}
        Enhanced v2.1: [{"name_kanji": "ティグル＝ヴォルン", "name_en": "Tigrevurmud Vorn", ...}]
        
        PHASE 0 FIX: Preserves ALL rich fields (PAIR_ID/relationships, keigo, contraction, nickname,
        how_character_refers_to_others) that were previously dropped.
        Also fixes the name_en/name_kanji swap — dict key is JP, full_name is EN.
        """
        characters = []
        if not isinstance(profiles, dict):
            return characters

        for jp_name, profile in profiles.items():
            if not isinstance(profile, dict):
                continue

            pronouns_raw = profile.get('pronouns', '')
            if not isinstance(pronouns_raw, str):
                pronouns_raw = str(pronouns_raw)

            char = {
                # FIX: dict key IS the JP name, full_name is the EN name
                'name_kanji': jp_name,
                'name_en': profile.get('full_name', jp_name),
                'nickname': profile.get('nickname', ''),
                'role': profile.get('relationship_to_protagonist', 'supporting'),
                'gender': 'female' if 'she/her' in pronouns_raw else 'male' if 'he/him' in pronouns_raw else 'unknown',
                'age': profile.get('age', 'unknown'),
                'origin': profile.get('origin', ''),
            }
            
            # Parse pronouns string to dict
            if pronouns_raw:
                if 'she/her' in pronouns_raw.lower():
                    char['pronouns'] = {'subject': 'she', 'object': 'her', 'possessive': 'her'}
                elif 'he/him' in pronouns_raw.lower():
                    char['pronouns'] = {'subject': 'he', 'object': 'him', 'possessive': 'his'}
            
            # === PAIR_ID Relationships (PREVIOUSLY DROPPED) ===
            rtas = profile.get('rtas_relationships', profile.get('pair_id_relationships', []))
            if rtas and isinstance(rtas, list):
                char['relationships'] = {}
                for rel in rtas:
                    if isinstance(rel, dict):
                        target = rel.get('target', '')
                        if target:
                            char['relationships'][target] = {
                                'type': rel.get('relationship_type', ''),
                                'rtas_score': rel.get('rtas_score', 0),
                                'contraction_rate': rel.get('contraction_rate_override', None),
                                'notes': rel.get('notes', '')
                            }
            elif 'relationship_to_others' in profile:
                char['relationships'] = {'context': profile['relationship_to_others']}
            
            # === Keigo Switch (PREVIOUSLY DROPPED) ===
            keigo = profile.get('keigo_switch', {})
            if keigo and isinstance(keigo, dict):
                char['keigo_switch'] = keigo
            
            # === Contraction Rate (PREVIOUSLY DROPPED) ===
            contraction = profile.get('contraction_rate', {})
            if contraction and isinstance(contraction, dict):
                char['contraction_rate'] = contraction
            
            # === How Character Refers To Others (PREVIOUSLY DROPPED) ===
            refers = profile.get('how_character_refers_to_others', {})
            if refers and isinstance(refers, dict):
                char['how_refers_to_others'] = refers
            
            # Preserve key traits as notes
            notes = []
            if 'personality_traits' in profile:
                traits = profile['personality_traits']
                if isinstance(traits, list):
                    notes.append(f"Personality: {', '.join(str(t) for t in traits)}")
                else:
                    notes.append(f"Personality: {traits}")
            if 'key_traits' in profile:
                notes.append(f"Key traits: {profile['key_traits']}")
            if 'appearance' in profile:
                notes.append(f"Appearance: {profile['appearance']}")
            if notes:
                char['notes'] = ' | '.join(notes)
            
            # Preserve character arc info
            for key in profile:
                if key.startswith('character_arc'):
                    char['character_arc'] = profile[key]
                    break
            
            characters.append(char)
        
        return characters
    
    def _transform_localization_notes(self, notes: Dict) -> Dict:
        """
        Transform legacy localization_notes to Enhanced v2.1 translation_guidelines.
        """
        guidelines = {}
        if not isinstance(notes, dict):
            return guidelines
        
        # British speech exception → character_exceptions
        if 'british_speech_exception' in notes:
            bse = notes['british_speech_exception']
            if isinstance(bse, dict):
                guidelines['character_exceptions'] = {
                    bse.get('character', 'Unknown'): {
                        'allowed_patterns': bse.get('allowed_patterns', []),
                        'rationale': bse.get('rationale', ''),
                        'examples': bse.get('examples', [])
                    }
                }
        
        # All other characters → forbidden_patterns & target_metrics
        if 'all_other_characters' in notes:
            aoc = notes['all_other_characters']
            if isinstance(aoc, dict):
                guidelines['forbidden_patterns'] = aoc.get('forbidden_patterns', [])
                guidelines['preferred_alternatives'] = aoc.get('preferred_alternatives', {})
                guidelines['target_metrics'] = aoc.get('target_metrics', {})
                guidelines['narrator_voice'] = aoc.get('narrator_voice', '')
        
        # Name order → naming_conventions
        if 'name_order' in notes:
            guidelines['naming_conventions'] = notes['name_order']
        
        # Dialogue guidelines → dialogue_rules
        if 'dialogue_guidelines' in notes:
            guidelines['dialogue_rules'] = notes['dialogue_guidelines']
        
        # Volume-specific notes → volume_context
        for key in notes:
            if 'volume' in key.lower() and 'specific' in key.lower():
                guidelines['volume_context'] = notes[key]
                break
        
        return guidelines
    
    def _extract_dialogue_patterns(self, profiles: Dict) -> Dict:
        """
        Extract dialogue_patterns from character_profiles.
        
        Phase 0 rewrite: Derives tone_shifts from keigo_switch data instead of
        using hardcoded phrase lists. The keigo_switch.speaking_to map directly
        tells us how a character's register shifts per conversation partner.
        """
        patterns = {}
        if not isinstance(profiles, dict):
            return patterns

        for name, profile in profiles.items():
            if not isinstance(profile, dict):
                continue

            speech_pattern = profile.get('speech_pattern')
            if not (isinstance(speech_pattern, str) and speech_pattern):
                continue
            
            pattern_entry = {
                'speech_style': speech_pattern,
                'tone_shifts': {}
            }
            
            # Derive tone_shifts from keigo_switch (real data, not guesses)
            keigo = profile.get('keigo_switch', {})
            if isinstance(keigo, dict):
                speaking_to = keigo.get('speaking_to', {})
                if isinstance(speaking_to, dict):
                    for target, register in speaking_to.items():
                        pattern_entry['tone_shifts'][target] = register
                # Add narration/thought register
                narration = keigo.get('narration', '')
                if narration:
                    pattern_entry['tone_shifts']['[narration]'] = narration
                thoughts = keigo.get('internal_thoughts', '')
                if thoughts:
                    pattern_entry['tone_shifts']['[internal_thoughts]'] = thoughts
            
            # Contraction rate as speech metric
            contraction = profile.get('contraction_rate', {})
            if isinstance(contraction, dict):
                baseline = contraction.get('baseline')
                if baseline is not None:
                    pattern_entry['contraction_baseline'] = baseline
            
            patterns[name] = pattern_entry
        
        return patterns

    def _setup_project_debug_logging(self) -> None:
        """Attach a file logger so full translator debug output is stored per volume."""
        enabled = bool(self.translation_config.get("debug_log_to_project", True))
        if not enabled:
            return

        debug_dir = self.work_dir / "DEBUG"
        debug_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        debug_path = debug_dir / f"translator_debug_{ts}.log"

        root_logger = logging.getLogger()
        # Keep only one project debug handler attached at a time to avoid duplicated log lines.
        stale_handlers = [h for h in root_logger.handlers if getattr(h, "_mtl_project_debug_handler", False)]
        for stale in stale_handlers:
            root_logger.removeHandler(stale)
            try:
                stale.close()
            except Exception:
                pass

        file_handler = logging.FileHandler(debug_path, mode="w", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter("[%(levelname)s] %(asctime)s - %(name)s - %(message)s"))
        file_handler._mtl_project_debug_handler = True  # type: ignore[attr-defined]
        root_logger.addHandler(file_handler)

        latest_ptr = debug_dir / "LATEST_TRANSLATOR_DEBUG_LOG.txt"
        latest_ptr.write_text(str(debug_path) + "\n", encoding="utf-8")

        logger.info(f"[DEBUG-LOG] Translator debug log file: {debug_path}")

    def _load_manifest(self) -> Dict:
        with open(self.manifest_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _enforce_name_order_guard(self) -> None:
        """Pause startup if manifest policy conflicts with canonical name artifacts."""
        policy = resolve_name_order_policy(self.manifest)
        conflicts = detect_name_order_conflicts(
            self.work_dir,
            self.manifest,
            include_outputs=False,
        )
        if not conflicts:
            return

        logger.warning(
            "[NAME-ORDER GUARD] Detected %s artifact(s) conflicting with manifest policy '%s'.",
            len(conflicts),
            policy,
        )
        for item in conflicts[:5]:
            detail = ", ".join(
                f"{wrong} x{count}" for wrong, count in sorted(item.get("counts", {}).items())
            )
            logger.warning("[NAME-ORDER GUARD] %s :: %s", item.get("path"), detail)

        if not sys.stdin.isatty():
            logger.warning(
                "[NAME-ORDER GUARD] Non-interactive session detected. Continuing without normalization."
            )
            return

        print("\n[NAME-ORDER GUARD] Canonical-name conflict detected before translation.")
        print(f"Manifest policy: {policy}")
        print("Conflicting artifacts:")
        for item in conflicts[:5]:
            detail = ", ".join(
                f"{wrong} x{count}" for wrong, count in sorted(item.get("counts", {}).items())
            )
            print(f"  - {item.get('path')}: {detail}")
        print("\nSelect option:")
        print("  [1] Skip normalization and continue")
        print("  [2] Normalize all names per manifest.json policy, then continue")

        while True:
            choice = input("Select option [1/2]: ").strip().lower()
            if choice in {"", "1", "s", "skip"}:
                logger.warning("[NAME-ORDER GUARD] Operator skipped normalization.")
                return
            if choice in {"2", "n", "normalize"}:
                summary = normalize_volume_artifacts(
                    self.work_dir,
                    self.manifest,
                    include_outputs=True,
                )
                self.manifest = self._load_manifest()
                logger.info(
                    "[NAME-ORDER GUARD] Normalized %s file(s), replacements=%s",
                    summary.get("files_touched", 0),
                    summary.get("replacements", 0),
                )
                return
            print("Invalid selection. Enter 1 or 2.")

    def _detect_bible_name_order_bypass_reason(self, bible: Any) -> Optional[str]:
        """Return bypass reason when a loaded bible conflicts with local name-order canon."""
        replacements = build_name_order_replacement_map(self.manifest)
        if not replacements:
            return None

        bible_data = getattr(bible, "data", None)
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
        policy = resolve_name_order_policy(self.manifest)
        return (
            f"Loaded bible conflicts with manifest name-order policy '{policy}' "
            f"({summary})"
        )

    def _resolve_bible_import_mode(self, bible: Any, bypass_reason: Optional[str]) -> tuple[str, str]:
        """Resolve runtime bible import mode: canon_safe | continuity_only | bypassed."""
        if not bible:
            return "bypassed", "No bible resolved"

        requested_mode = ""
        manifest_mode = str(self.manifest.get("bible_import_mode", "") or "").strip().lower()
        config_mode = str(self.translation_config.get("bible_import_mode", "") or "").strip().lower()
        if manifest_mode:
            requested_mode = manifest_mode
        elif config_mode:
            requested_mode = config_mode

        valid_modes = {"canon_safe", "continuity_only", "bypassed"}
        if requested_mode and requested_mode not in valid_modes:
            logger.warning(
                "[BIBLE-MODE] Unsupported mode '%s'. Falling back to default routing.",
                requested_mode,
            )
            requested_mode = ""

        if requested_mode == "bypassed":
            return "bypassed", "Explicitly configured by manifest/config"
        if requested_mode == "continuity_only":
            if bypass_reason:
                return "continuity_only", f"Configured continuity_only + conflict guard: {bypass_reason}"
            return "continuity_only", "Explicitly configured by manifest/config"
        if requested_mode == "canon_safe":
            if bypass_reason:
                return "continuity_only", f"Downgraded from canon_safe: {bypass_reason}"
            return "canon_safe", "Explicitly configured by manifest/config"

        if bypass_reason:
            return "continuity_only", bypass_reason
        return "canon_safe", "Default mode: bible canon compatible with local manifest"

    def _run_pre_phase2_invariant_gate(
        self,
        target_chapters: List[Dict[str, Any]],
        *,
        batch_mode: bool,
    ) -> PreflightInvariantReport:
        """Blocking invariant gate before Phase 2 starts."""
        report = PreflightInvariantReport()

        conflicts = detect_name_order_conflicts(
            self.work_dir,
            self.manifest,
            include_outputs=False,
        )
        report.metrics["name_order_conflict_files"] = len(conflicts)
        if conflicts:
            top_conflicts = ", ".join(
                f"{Path(item.get('path', '')).name}:{int(item.get('total', 0))}"
                for item in conflicts[:5]
            )
            report.hard_failures.append(
                f"Name-order conflicts detected in persisted artifacts ({top_conflicts})"
            )

        canonical_name_set: set[str] = set()
        metadata_en = self.manifest.get("metadata_en", {})
        if isinstance(metadata_en, dict):
            char_names = metadata_en.get("character_names", {})
            if isinstance(char_names, dict):
                for v in char_names.values():
                    name = str(v or "").strip().lower()
                    if name:
                        canonical_name_set.add(name)
            profiles = metadata_en.get("character_profiles", {})
            if isinstance(profiles, dict):
                for k in profiles.keys():
                    name = str(k or "").strip().lower()
                    if name:
                        canonical_name_set.add(name)
            for fp in metadata_en.get("character_voice_fingerprints", []) or []:
                if not isinstance(fp, dict):
                    continue
                name = str(fp.get("canonical_name_en", "") or "").strip().lower()
                if name:
                    canonical_name_set.add(name)
        for fp in self._voice_rag.all_fingerprints() or []:
            if not isinstance(fp, dict):
                continue
            name = str(fp.get("canonical_name_en", "") or "").strip().lower()
            if name:
                canonical_name_set.add(name)

        noncanonical_scene_names: List[str] = []
        canonical_names_without_fingerprint: List[str] = []
        fingerprint_total = 0
        fingerprint_resolved = 0
        chapters_with_scene_plans = 0
        afterword_chapters = 0

        for chapter in target_chapters:
            source_file = str(chapter.get("jp_file") or chapter.get("source_file") or "").strip()
            source_path = (self.work_dir / "JP" / source_file) if source_file else None
            if is_afterword_chapter(chapter, source_path=source_path):
                afterword_chapters += 1
                continue

            scene_ref = chapter.get("scene_plan_file")
            scene_plan = self._load_scene_plan_context(chapter)
            if scene_ref:
                chapters_with_scene_plans += 1
            if scene_ref and not scene_plan:
                report.hard_failures.append(
                    f"Scene plan missing/invalid for chapter '{chapter.get('id', '?')}'"
                )
                continue
            if not scene_plan:
                continue

            scene_names: set[str] = set()
            for item in scene_plan.get("pov_tracking", []) or []:
                if isinstance(item, dict):
                    name = str(item.get("character", "") or "").strip()
                    if name:
                        scene_names.add(name)
            chapter_profiles = scene_plan.get("character_profiles", {})
            if isinstance(chapter_profiles, dict):
                for raw_name in chapter_profiles.keys():
                    name = str(raw_name or "").strip()
                    if name:
                        scene_names.add(name)

            for raw_name in scene_names:
                canonical_name, fp = self._resolve_scene_fingerprint(raw_name)

                normalized = str(canonical_name or raw_name).strip().lower()
                if not normalized:
                    continue
                if normalized in {"unknown", "n/a", "na", "none", "narrator"}:
                    continue
                if normalized in canonical_name_set:
                    if fp is None:
                        canonical_names_without_fingerprint.append(
                            f"{chapter.get('id', '?')}:{raw_name}"
                        )
                        continue
                    fingerprint_total += 1
                    fingerprint_resolved += 1
                    continue
                if fp is not None:
                    fingerprint_total += 1
                    fingerprint_resolved += 1
                    continue
                noncanonical_scene_names.append(f"{chapter.get('id', '?')}:{raw_name}")

        report.metrics["scene_plan_chapters"] = chapters_with_scene_plans
        report.metrics["afterword_chapters_exempted"] = afterword_chapters
        report.metrics["scene_names_noncanonical"] = len(noncanonical_scene_names)
        report.metrics["canonical_names_without_fingerprint"] = len(canonical_names_without_fingerprint)
        report.metrics["fingerprint_total_refs"] = fingerprint_total
        report.metrics["fingerprint_resolved_refs"] = fingerprint_resolved

        if canonical_names_without_fingerprint:
            report.warnings.append(
                "Canonical scene-plan names without resolved voice fingerprint "
                f"({', '.join(canonical_names_without_fingerprint[:8])})"
            )

        if noncanonical_scene_names:
            report.hard_failures.append(
                "Non-canonical scene-plan character names detected "
                f"({', '.join(noncanonical_scene_names[:8])})"
            )

        min_fp_coverage = float(
            self.translation_config.get("preflight_min_pov_fingerprint_coverage", 0.80)
        )
        fp_coverage = (fingerprint_resolved / fingerprint_total) if fingerprint_total else 1.0
        report.metrics["fingerprint_coverage"] = round(fp_coverage, 4)
        report.metrics["fingerprint_min_required"] = round(min_fp_coverage, 4)
        if fingerprint_total and fp_coverage < min_fp_coverage:
            report.hard_failures.append(
                "POV fingerprint resolution coverage below threshold "
                f"({fingerprint_resolved}/{fingerprint_total}={fp_coverage:.1%} < {min_fp_coverage:.1%})"
            )

        metadata_chapters = metadata_en.get("chapters", {}) if isinstance(metadata_en, dict) else {}
        chapter_eps_lookup: Dict[str, Dict[str, Any]] = {}
        if isinstance(metadata_chapters, dict):
            for chapter_id, chapter_data in metadata_chapters.items():
                if isinstance(chapter_data, dict):
                    chapter_eps_lookup[str(chapter_id)] = chapter_data
        elif isinstance(metadata_chapters, list):
            for chapter_data in metadata_chapters:
                if not isinstance(chapter_data, dict):
                    continue
                chapter_id = str(chapter_data.get("id", "")).strip()
                if chapter_id:
                    chapter_eps_lookup[chapter_id] = chapter_data

        eps_missing: List[str] = []
        for chapter in target_chapters:
            chapter_id = str(chapter.get("id", "")).strip()
            if not chapter_id:
                continue
            source_file = str(chapter.get("jp_file") or chapter.get("source_file") or "").strip()
            source_path = (self.work_dir / "JP" / source_file) if source_file else None
            if is_afterword_chapter(chapter, source_path=source_path):
                continue
            chapter_meta = chapter_eps_lookup.get(chapter_id, {})
            eps_data = chapter_meta.get("emotional_proximity_signals", {}) if isinstance(chapter_meta, dict) else {}
            if not isinstance(eps_data, dict):
                eps_missing.append(chapter_id)
                continue

            populated_eps_entries = [
                character_name
                for character_name, signal_payload in eps_data.items()
                if str(character_name or "").strip() and isinstance(signal_payload, dict)
            ]

            # Unknown POV signals are optional for this gate; only require at least one
            # populated EPS entry in the chapter map.
            if not populated_eps_entries:
                eps_missing.append(chapter_id)

        report.metrics["eps_missing_chapters"] = len(eps_missing)
        report.metrics["eps_target_chapters"] = len(target_chapters)
        if eps_missing:
            report.hard_failures.append(
                "Incomplete EPS coverage for target chapters "
                f"({', '.join(eps_missing[:10])})"
            )

        mode_label = "batch" if batch_mode else "stream"
        if report.passed:
            logger.info(
                "[PREFLIGHT] PASS (%s): name_order_conflicts=%s | noncanonical_scene_names=%s | "
                "fingerprint_coverage=%.1f%% | canonical_names_without_fingerprint=%s | eps_missing=%s",
                mode_label,
                report.metrics.get("name_order_conflict_files", 0),
                report.metrics.get("scene_names_noncanonical", 0),
                float(report.metrics.get("fingerprint_coverage", 1.0)) * 100.0,
                report.metrics.get("canonical_names_without_fingerprint", 0),
                report.metrics.get("eps_missing_chapters", 0),
            )
        else:
            logger.error("[PREFLIGHT] FAIL (%s):", mode_label)
            for idx, reason in enumerate(report.hard_failures, 1):
                logger.error("  [%s] %s", idx, reason)

        return report

    def _apply_manifest_world_setting_override(self) -> None:
        """Override bible world_setting with manifest values when they explicitly differ.

        The series bible holds series-level defaults. The manifest is volume-specific
        and operator-edited — it is the authoritative source for this run. If the manifest's
        metadata_en.world_setting contains an explicit honorifics.mode or name_order.default
        that differs from the bible, the manifest wins.

        Called after bible load, before format_world_setting_directive().
        """
        if not self.bible:
            return

        manifest_ws = (self.manifest.get("metadata_en") or {}).get("world_setting") or {}
        if not isinstance(manifest_ws, dict) or not manifest_ws:
            return

        bible_ws = self.bible.world_setting
        if not isinstance(bible_ws, dict):
            bible_ws = {}

        changed = False

        # Honorifics mode: manifest explicit value overrides bible
        manifest_hon = manifest_ws.get("honorifics") or {}
        manifest_mode = manifest_hon.get("mode", "")
        bible_hon = bible_ws.get("honorifics") or {}
        bible_mode = bible_hon.get("mode", "")
        if manifest_mode and manifest_mode != bible_mode:
            bible_hon = dict(bible_hon)
            bible_hon["mode"] = manifest_mode
            if manifest_hon.get("policy"):
                bible_hon["policy"] = manifest_hon["policy"]
            bible_ws = dict(bible_ws)
            bible_ws["honorifics"] = bible_hon
            self.bible.data["world_setting"] = bible_ws
            changed = True
            logger.info(
                f"[MANIFEST-OVERRIDE] world_setting.honorifics.mode: '{bible_mode}' → '{manifest_mode}' "
                f"(manifest takes precedence over bible)"
            )

        # Name order: manifest explicit value overrides bible
        manifest_no = manifest_ws.get("name_order") or {}
        manifest_order = manifest_no.get("default", "")
        bible_no = bible_ws.get("name_order") or {}
        bible_order = bible_no.get("default", "")
        if manifest_order and manifest_order != bible_order:
            bible_no = dict(bible_no)
            bible_no["default"] = manifest_order
            bible_ws = dict(bible_ws)
            bible_ws["name_order"] = bible_no
            self.bible.data["world_setting"] = bible_ws
            changed = True
            logger.info(
                f"[MANIFEST-OVERRIDE] world_setting.name_order.default: '{bible_order}' → '{manifest_order}' "
                f"(manifest takes precedence over bible)"
            )

        if not changed:
            logger.debug("[MANIFEST-OVERRIDE] world_setting: manifest and bible agree, no override needed")

    def _log_world_localization_profile(self) -> None:
        """Log world + localization profile with JSON source attribution."""
        def _pick_block(candidates: List[tuple[str, Any]]) -> tuple[str, dict]:
            for source_name, block in candidates:
                if isinstance(block, dict) and block:
                    return source_name, block
            return "unavailable", {}

        local_meta: dict = {}
        manifest_meta = self.manifest.get("metadata_en", {}) if isinstance(self.manifest, dict) else {}
        # Gate: skip metadata_en.json patch if manifest.metadata_en is already populated
        if not (manifest_meta and isinstance(manifest_meta, dict)):
            meta_path = self.work_dir / "metadata_en.json"
            if meta_path.exists():
                try:
                    with open(meta_path, "r", encoding="utf-8") as fh:
                        loaded = json.load(fh)
                        if isinstance(loaded, dict):
                            local_meta = loaded
                except Exception as exc:
                    logger.debug(f"[WORLD-LOC] metadata_en.json load failed: {exc}")

        manifest_meta = self.manifest.get("metadata_en", {}) if isinstance(self.manifest, dict) else {}
        source_root = "bible" if self.bible else "local_manifest"

        bible_ws = self.bible.world_setting if (self.bible and isinstance(self.bible.world_setting, dict)) else {}
        ws_source, world_setting = _pick_block([
            ("bible.world_setting", bible_ws),
            ("manifest.metadata_en.world_setting", manifest_meta.get("world_setting") if isinstance(manifest_meta, dict) else {}),
            ("manifest.world_setting", self.manifest.get("world_setting", {})),
            ("metadata_en.json.world_setting", local_meta.get("world_setting", {})),
        ])

        official_source, official_localization = _pick_block([
            ("manifest.metadata_en.official_localization", manifest_meta.get("official_localization") if isinstance(manifest_meta, dict) else {}),
            ("manifest.official_localization", self.manifest.get("official_localization", {})),
            ("metadata_en.json.official_localization", local_meta.get("official_localization", {})),
        ])

        honorifics = world_setting.get("honorifics", {}) if isinstance(world_setting, dict) else {}
        name_order = world_setting.get("name_order", {}) if isinstance(world_setting, dict) else {}
        localization_mode = {
            "honorifics_mode": honorifics.get("mode", "unknown") if isinstance(honorifics, dict) else "unknown",
            "name_order": name_order.get("default", "unknown") if isinstance(name_order, dict) else "unknown",
            "official_titles": (
                "official_localization"
                if bool(official_localization.get("should_use_official", False))
                else "project_localization"
            ),
        }

        world_type = world_setting.get("type", "?") if isinstance(world_setting, dict) else "?"
        world_label = world_setting.get("label", world_type) if isinstance(world_setting, dict) else world_type
        logger.info(
            "[WORLD-LOC] source=%s | world=%s | localization_mode={honorifics:%s, name_order:%s, titles:%s}",
            source_root,
            world_label,
            localization_mode["honorifics_mode"],
            localization_mode["name_order"],
            localization_mode["official_titles"],
        )

    @staticmethod
    def _has_memoir_signal(*values: Any) -> bool:
        """Return True when free-text metadata strongly signals memoir/autobiography."""
        memoir_kws = (
            "memoir",
            "autobiography",
            "autobiographical",
            "biography",
            "biographical",
            "non fiction",
            "non_fiction",
            "nonfiction",
            "artist memoir",
            "real person memoir",
            "life story",
            "自伝",
            "自叙伝",
            "回顧録",
            "ノンフィクション",
            "散文",
        )

        flattened: List[str] = []

        def _collect(value: Any) -> None:
            if value is None:
                return
            if isinstance(value, str):
                stripped = value.strip()
                if stripped:
                    flattened.append(stripped)
                return
            if isinstance(value, dict):
                for nested in value.values():
                    _collect(nested)
                return
            if isinstance(value, (list, tuple, set)):
                for nested in value:
                    _collect(nested)

        for value in values:
            _collect(value)

        haystack = " ".join(flattened).lower().replace("-", "_")
        return any(kw.replace("-", "_") in haystack for kw in memoir_kws)

    def _resolve_book_type(self) -> str:
        """Resolve explicit or inferred book_type for memoir/non-fiction gating."""
        manifest_meta = self.manifest.get("metadata", {}) if isinstance(self.manifest, dict) else {}
        explicit = (
            manifest_meta.get("book_type")
            or self.manifest.get("book_type")
            or self.manifest.get("metadata_en", {}).get("book_type")
        )
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()

        manifest_meta_en = self.manifest.get("metadata_en", {}) if isinstance(self.manifest, dict) else {}
        memoir_hint_sources = [
            manifest_meta.get("title"),
            manifest_meta.get("series"),
            self.manifest.get("title"),
            self.manifest.get("genre"),
            self.manifest.get("world_setting"),
            manifest_meta_en.get("world_setting"),
            manifest_meta_en.get("schema_note"),
        ]
        if self._has_memoir_signal(*memoir_hint_sources):
            logger.info("[MEMOIR MODE] Inferred book_type='autobiography' from metadata signals")
            return "autobiography"
        return ""

    def _resolve_genre(self) -> str:
        """
        Resolve novel genre for the Tier 2 module gate.

        Cascade (first non-empty string wins):
          1. metadata_en.json  top-level "genre"
          2. metadata_en.json  content_info.genre / genres
          3. manifest.json     top-level "genre"
          4. manifest.json     translation_guidance.genre / genres
          5. manifest.json     metadata_en.content_info.genre / genres
          6. manifest.json     world_setting.type  (top-level or under metadata_en)
          7. metadata_en.json  world_setting.type

        world_setting.type is the most reliably populated field in practice (set by the
        Librarian schema agent). Its value is used verbatim so the Tier 2 gate's keyword
        check ("fantasy", "isekai", "steampunk", "academy", etc.) can fire on it.

        Falls back to "" — the Tier 2 gate defaults to fail-open (keep FANTASY module)
        when genre is completely unknown.
        """
        work_dir = self.manifest_path.parent

        def _extract(obj: Any, *keys: str) -> str:
            """Walk dict keys, return first non-empty string or space-joined list."""
            for key in keys:
                val = obj.get(key) if isinstance(obj, dict) else None
                if not val:
                    continue
                if isinstance(val, str) and val.strip():
                    return val.strip()
                if isinstance(val, list) and val:
                    return " ".join(str(v) for v in val if v)
            return ""

        def _world_setting_type(obj: Any) -> str:
            """Extract world_setting.type from a manifest/metadata dict."""
            ws = obj.get("world_setting") if isinstance(obj, dict) else None
            if isinstance(ws, dict):
                t = ws.get("type", "")
                if isinstance(t, str) and t.strip():
                    return t.strip()
            return ""

        def _world_setting_label(obj: Any) -> str:
            """Extract world_setting.label from a manifest/metadata dict."""
            ws = obj.get("world_setting") if isinstance(obj, dict) else None
            if isinstance(ws, dict):
                label = ws.get("label", "")
                if isinstance(label, str) and label.strip():
                    return label.strip()
            return ""

        try:
            # Gate: If manifest.metadata_en exists (complete), skip metadata_en.json patch file
            manifest_meta_en = self.manifest.get("metadata_en", {}) if isinstance(self.manifest, dict) else {}
            use_manifest_directly = bool(manifest_meta_en and isinstance(manifest_meta_en, dict))

            meta: dict = {}
            if not use_manifest_directly:
                # Only load metadata_en.json patch if manifest.metadata_en is missing/empty
                meta_path = work_dir / "metadata_en.json"
                if meta_path.exists():
                    with open(meta_path, encoding="utf-8") as fh:
                        meta = json.load(fh)

            # ── Cascade 1-2: metadata_en.json explicit genre ──
            genre = _extract(meta, "genre")
            if genre:
                logger.debug(f"[GENRE] metadata_en.json genre: {genre!r}")
                return genre
            genre = _extract(meta.get("content_info", {}), "genre", "genres")
            if genre:
                logger.debug(f"[GENRE] metadata_en.json content_info.genre: {genre!r}")
                return genre

            # ── Cascade 3-5: manifest.json explicit genre ──
            genre = _extract(self.manifest, "genre")
            if genre:
                logger.debug(f"[GENRE] manifest.json genre: {genre!r}")
                return genre
            genre = _extract(self.manifest.get("translation_guidance", {}), "genre", "genres")
            if genre:
                logger.debug(f"[GENRE] manifest.json translation_guidance.genre: {genre!r}")
                return genre
            meta_en = self.manifest.get("metadata_en", {})
            genre = _extract(meta_en.get("content_info", self.manifest.get("content_info", {})), "genre", "genres")
            if genre:
                logger.debug(f"[GENRE] manifest.json metadata_en.content_info.genre: {genre!r}")
                return genre

            # ── Cascade 6: manifest.json world_setting.type ──
            # Check top-level first, then under metadata_en (where Librarian puts it)
            ws_type = _world_setting_type(self.manifest) or _world_setting_type(meta_en)
            ws_label = _world_setting_label(self.manifest) or _world_setting_label(meta_en)
            if ws_type and self._has_memoir_signal(ws_type, ws_label):
                inferred = ws_type if "memoir" in ws_type.lower().replace("-", "_") else f"{ws_type}_memoir"
                logger.debug(
                    f"[GENRE] manifest.json world_setting memoir inference: type={ws_type!r}, "
                    f"label={ws_label!r} -> {inferred!r}"
                )
                return inferred
            if ws_type:
                logger.debug(f"[GENRE] manifest.json world_setting.type: {ws_type!r}")
                return ws_type

            # ── Cascade 7: metadata_en.json world_setting.type ──
            ws_type = _world_setting_type(meta)
            ws_label = _world_setting_label(meta)
            if ws_type and self._has_memoir_signal(ws_type, ws_label):
                inferred = ws_type if "memoir" in ws_type.lower().replace("-", "_") else f"{ws_type}_memoir"
                logger.debug(
                    f"[GENRE] metadata_en.json world_setting memoir inference: type={ws_type!r}, "
                    f"label={ws_label!r} -> {inferred!r}"
                )
                return inferred
            if ws_type:
                logger.debug(f"[GENRE] metadata_en.json world_setting.type: {ws_type!r}")
                return ws_type

            logger.debug("[GENRE] No genre/world_setting found — Tier 2 gate will use fail-open default")
            return ""

        except Exception as exc:
            logger.warning(f"[GENRE] Failed to resolve genre: {exc}")
            return ""

    def _resolve_tool_mode_config(self, *, cli_enabled: bool = False) -> Dict[str, Any]:
        """Merge global config, manifest overrides, and CLI override for tool mode."""
        resolved = dict(get_tool_mode_config())
        resolved_tools = dict(resolved.get("tools", {}))

        manifest_tool_mode = self.manifest.get("tool_mode", {})
        if isinstance(manifest_tool_mode, dict):
            if "enabled" in manifest_tool_mode:
                resolved_enabled = bool(manifest_tool_mode.get("enabled"))
                resolved["enabled"] = resolved_enabled
                resolved["configured_enabled"] = resolved_enabled
                resolved["auto_disabled_reason"] = None
            if "force_pre_commit" in manifest_tool_mode:
                resolved["force_pre_commit"] = bool(
                    manifest_tool_mode.get("force_pre_commit")
                )
            if "log_tool_calls" in manifest_tool_mode:
                resolved["log_tool_calls"] = bool(
                    manifest_tool_mode.get("log_tool_calls")
                )

            manifest_tools = manifest_tool_mode.get("tools", {})
            if isinstance(manifest_tools, dict):
                for key, value in manifest_tools.items():
                    resolved_tools[str(key)] = bool(value)

        if cli_enabled:
            resolved["enabled"] = True
            resolved["configured_enabled"] = True
            resolved["auto_disabled_reason"] = None

        resolved["tools"] = resolved_tools
        return resolved

    def _configured_tool_names(self) -> List[str]:
        """Return enabled tool names in stable order for logging."""
        tools_cfg = self.tool_mode_config.get("tools", {})
        if not isinstance(tools_cfg, dict):
            tools_cfg = {}
        return [
            name for name in _TOOL_MODE_ORDER
            if bool(tools_cfg.get(name, True))
        ]

    def _tool_mode_resolution_note(self) -> str:
        """Describe which setting resolved tool mode for this run."""
        if self._tool_mode_cli_requested:
            return "CLI --tool-mode was passed"

        if self._tool_mode_auto_disabled_reason:
            return self._tool_mode_auto_disabled_reason

        manifest_tool_mode = self.manifest.get("tool_mode", {})
        if isinstance(manifest_tool_mode, dict) and "enabled" in manifest_tool_mode:
            return (
                "manifest.json set "
                f"tool_mode.enabled={bool(manifest_tool_mode.get('enabled'))}"
            )

        translation_tool_mode = self.translation_config.get("tool_mode", {})
        if isinstance(translation_tool_mode, dict) and "enabled" in translation_tool_mode:
            return (
                "config.yaml set "
                f"translation.tool_mode.enabled={bool(translation_tool_mode.get('enabled'))}"
            )

        return f"default tool-mode policy resolved enabled={self._tool_mode_requested}"

    def _build_tool_mode_log_status(
        self,
        *,
        batch_mode: bool,
        tool_call_count: int = 0,
        declared_params: Any = None,
    ) -> Dict[str, Any]:
        """Build explicit tool-mode status for log entries and run summaries."""
        active = bool(
            self.tool_mode_enabled
            and not batch_mode
            and self.translator_provider == "anthropic"
        )
        configured_tools = self._configured_tool_names()

        if active:
            if tool_call_count > 0 or declared_params is not None:
                status = "active"
                reason = "Tool mode was active on the Anthropic streaming path."
            else:
                status = "active_no_calls"
                reason = (
                    "Tool mode was active on the Anthropic streaming path, but no "
                    "tool-call metadata was captured for this chapter."
                )
        elif self._tool_mode_auto_disabled_reason and not self._tool_mode_cli_requested:
            status = "disabled_by_auto_switch"
            if batch_mode:
                reason = (
                    f"{self._tool_mode_auto_disabled_reason} This run used Anthropic "
                    "Batch API."
                )
            else:
                reason = self._tool_mode_auto_disabled_reason
        elif batch_mode:
            status = "disabled_for_batch"
            reason = (
                "Anthropic Batch API was used, so streaming-only multi-turn tool mode "
                f"was unavailable. Resolution: {self._tool_mode_resolution_note()}."
            )
        elif self.translator_provider != "anthropic":
            status = "disabled_for_provider"
            reason = self._tool_mode_provider_gate_reason or (
                f"Translator provider '{self.translator_provider}' does not support "
                "translator tool integration."
            )
        elif not self._tool_mode_requested:
            status = "disabled_by_config"
            reason = (
                "Tool mode was not enabled for this run. "
                f"Resolution: {self._tool_mode_resolution_note()}."
            )
        else:
            status = "disabled"
            reason = "Tool mode was requested but was not active for this chapter."

        return {
            "requested": bool(self._tool_mode_requested),
            "active": active,
            "configured_tools": configured_tools,
            "status": status,
            "reason": reason,
        }

    def _save_manifest(self):
        with open(self.manifest_path, 'w', encoding='utf-8') as f:
            json.dump(self.manifest, f, indent=2, ensure_ascii=False)

    def _load_log(self) -> Dict:
        base = {"chapters": [], "summary": {}, "last_run_summary": {}}
        if not self.log_path.exists():
            return dict(base)
        try:
            with open(self.log_path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                return dict(base)
            payload.setdefault("chapters", [])
            payload.setdefault("summary", {})
            payload.setdefault("last_run_summary", {})
            return payload
        except Exception:
            return dict(base)

    def _save_log(self):
        self.translation_log["summary"] = self._compute_totals_from_entries(
            self.translation_log.get("chapters", []),
            include_label=False,
        )
        self.translation_log["updated_at"] = datetime.now().isoformat()
        with open(self.log_path, 'w', encoding='utf-8') as f:
            json.dump(self.translation_log, f, indent=2, ensure_ascii=False)

    def _merge_result_cost_audits(
        self,
        first_result: TranslationResult,
        second_result: TranslationResult,
        *,
        merge_reason: str,
    ) -> Dict[str, Any]:
        return merge_chapter_cost_audits(
            first_result.cost_audit,
            second_result.cost_audit,
            merge_reason=merge_reason,
        )

    def _write_last_run_cost_audit(
        self,
        *,
        run_entries: List[Dict[str, Any]],
        run_summary: Dict[str, Any],
        batch_mode: bool,
    ) -> None:
        batch_provider_audit = {}
        if batch_mode and isinstance(getattr(self.client, "_last_batch_audit", None), dict):
            batch_provider_audit = getattr(self.client, "_last_batch_audit", {})

        audit = build_run_cost_audit(
            volume_id=self.work_dir.name,
            provider=self.translator_provider,
            run_entries=run_entries,
            logged_summary=run_summary,
            batch_mode=batch_mode,
            batch_provider_audit=batch_provider_audit,
        )
        paths = write_cost_audit_artifacts(
            work_dir=self.work_dir,
            audit=audit,
        )
        self.translation_log["last_run_cost_audit"] = {
            "generated_at": audit.get("generated_at"),
            "json_path": paths["json_path"],
            "markdown_path": paths["markdown_path"],
            "actual_total_cost_usd": audit.get("actual_summary", {}).get("total_cost_usd", 0.0),
            "extra_cost_vs_logged_usd": audit.get("delta_vs_logged", {}).get("extra_total_cost_usd", 0.0),
        }
        logger.info(
            "[COST-AUDIT] Wrote audit artifacts: total=$%.6f | delta_vs_logged=$%.6f",
            float(audit.get("actual_summary", {}).get("total_cost_usd", 0.0) or 0.0),
            float(audit.get("delta_vs_logged", {}).get("extra_total_cost_usd", 0.0) or 0.0),
        )

    @staticmethod
    def _to_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _estimate_entry_costs(
        self,
        *,
        model: Optional[str],
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int,
        cache_creation_tokens: int,
        batch_mode: bool,
        fast_mode_pricing: bool,
    ) -> Dict[str, float]:
        if self.translator_provider != "anthropic":
            return {
                "input_cost_usd": 0.0,
                "output_cost_usd": 0.0,
                "cache_read_cost_usd": 0.0,
                "cache_creation_cost_usd": 0.0,
                "total_cost_usd": 0.0,
            }
        cache_ttl = getattr(self.client, "_cache_ttl", "5m")
        cost = AnthropicClient.estimate_usage_cost_usd(
            model_name=model or self._active_model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cached_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cache_ttl=cache_ttl,
            batch_mode=batch_mode,
            fast_mode=fast_mode_pricing,
        )
        return {
            "input_cost_usd": cost["input_cost_usd"],
            "output_cost_usd": cost["output_cost_usd"],
            "cache_read_cost_usd": cost["cache_read_cost_usd"],
            "cache_creation_cost_usd": cost["cache_creation_cost_usd"],
            "total_cost_usd": cost["total_cost_usd"],
        }

    def _build_log_entry(
        self,
        *,
        chapter_id: str,
        result: TranslationResult,
        batch_mode: bool = False,
    ) -> Dict[str, Any]:
        model_name = result.model or self._active_model_name
        cached_tokens = self._to_int(result.cached_tokens)
        cache_creation_tokens = self._to_int(result.cache_creation_tokens)
        input_cost = self._to_float(result.input_cost_usd)
        output_cost = self._to_float(result.output_cost_usd)
        cache_read_cost = self._to_float(result.cache_read_cost_usd)
        cache_creation_cost = self._to_float(result.cache_creation_cost_usd)
        total_cost = self._to_float(result.total_cost_usd)

        # Backward compatibility: compute costs if provider response didn't populate them.
        if (
            self.translator_provider == "anthropic"
            and (result.input_tokens > 0 or result.output_tokens > 0 or cached_tokens > 0 or cache_creation_tokens > 0)
            and (input_cost + output_cost + cache_read_cost + cache_creation_cost + total_cost) <= 0.0
        ):
            estimated = self._estimate_entry_costs(
                model=model_name,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cached_tokens=cached_tokens,
                cache_creation_tokens=cache_creation_tokens,
                batch_mode=batch_mode or bool(result.batch_mode),
                fast_mode_pricing=bool(result.fast_mode_pricing),
            )
            input_cost = estimated["input_cost_usd"]
            output_cost = estimated["output_cost_usd"]
            cache_read_cost = estimated["cache_read_cost_usd"]
            cache_creation_cost = estimated["cache_creation_cost_usd"]
            total_cost = estimated["total_cost_usd"]

        effective_batch_mode = bool(batch_mode or result.batch_mode)
        tool_mode_status = self._build_tool_mode_log_status(
            batch_mode=effective_batch_mode,
            tool_call_count=self._to_int(result.tool_call_count),
            declared_params=getattr(result, "declared_params", None),
        )

        adn_review_flags = result.adn_review_flags if isinstance(result.adn_review_flags, dict) else {}

        return {
            "chapter_id": chapter_id,
            "model": model_name,
            "input_tokens": self._to_int(result.input_tokens),
            "output_tokens": self._to_int(result.output_tokens),
            "cached_tokens": cached_tokens,
            "cache_creation_tokens": cache_creation_tokens,
            "input_cost_usd": input_cost,
            "output_cost_usd": output_cost,
            "cache_read_cost_usd": cache_read_cost,
            "cache_creation_cost_usd": cache_creation_cost,
            "total_cost_usd": total_cost,
            "batch_mode": effective_batch_mode,
            "fast_mode_pricing": bool(result.fast_mode_pricing),
            "success": result.success,
            "error": result.error,
            "quality": result.audit_result.to_dict() if result.audit_result else None,
            "declared_params": (
                result.declared_params.to_dict()
                if getattr(result.declared_params, "to_dict", None)
                else None
            ),
            "declared_vs_actual": result.declared_vs_actual,
            "tool_calls_made": list(result.tool_calls_made or []),
            "tool_call_count": self._to_int(result.tool_call_count),
            "qc_intent_gap": result.qc_intent_gap,
            "structural_constraints": [
                item.to_dict() if getattr(item, "to_dict", None) else item
                for item in (result.structural_constraints or [])
            ],
            "koji_fox": (
                result.koji_fox_report.to_dict()
                if getattr(result.koji_fox_report, "to_dict", None)
                else None
            ),
            "qc_self_report": (
                result.qc_self_report.to_dict()
                if getattr(result.qc_self_report, "to_dict", None)
                else None
            ),
            "adn_review_flags": adn_review_flags,
            "cost_audit": result.cost_audit if isinstance(result.cost_audit, dict) else {},
            "tool_mode": tool_mode_status,
        }

    @staticmethod
    def _apply_adn_review_flags_to_chapter(
        chapter: Dict[str, Any],
        result: TranslationResult,
    ) -> None:
        """Persist ADN pipeline-review flags into chapter metadata when present."""
        if not isinstance(chapter, dict):
            return
        flags = result.adn_review_flags if isinstance(result.adn_review_flags, dict) else {}
        if flags:
            chapter["adn_review_flags"] = flags
            chapter["pipeline_review_required"] = bool(flags.get("requires_review"))
            return
        chapter.pop("adn_review_flags", None)
        chapter.pop("pipeline_review_required", None)

    def _compute_totals_from_entries(
        self,
        entries: List[Dict[str, Any]],
        *,
        include_label: bool = True,
    ) -> Dict[str, Any]:
        totals = {
            "total_chapters": len(entries),
            "completed": 0,
            "failed": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cache_read_tokens": 0,
            "total_cache_creation_tokens": 0,
            "total_input_cost_usd": 0.0,
            "total_output_cost_usd": 0.0,
            "total_cache_read_cost_usd": 0.0,
            "total_cache_creation_cost_usd": 0.0,
            "total_cost_usd": 0.0,
            "total_tokens": 0,
        }

        for entry in entries:
            in_tokens = self._to_int(entry.get("input_tokens", 0))
            out_tokens = self._to_int(entry.get("output_tokens", 0))
            cached_tokens = self._to_int(entry.get("cached_tokens", 0))
            cache_creation_tokens = self._to_int(entry.get("cache_creation_tokens", 0))

            in_cost = self._to_float(entry.get("input_cost_usd", 0.0))
            out_cost = self._to_float(entry.get("output_cost_usd", 0.0))
            cache_read_cost = self._to_float(entry.get("cache_read_cost_usd", 0.0))
            cache_creation_cost = self._to_float(entry.get("cache_creation_cost_usd", 0.0))
            total_cost = self._to_float(entry.get("total_cost_usd", 0.0))

            if (
                self.translator_provider == "anthropic"
                and (in_tokens > 0 or out_tokens > 0 or cached_tokens > 0 or cache_creation_tokens > 0)
                and (in_cost + out_cost + cache_read_cost + cache_creation_cost + total_cost) <= 0.0
            ):
                estimated = self._estimate_entry_costs(
                    model=entry.get("model") or self._active_model_name,
                    input_tokens=in_tokens,
                    output_tokens=out_tokens,
                    cached_tokens=cached_tokens,
                    cache_creation_tokens=cache_creation_tokens,
                    batch_mode=bool(entry.get("batch_mode", False)),
                    fast_mode_pricing=bool(entry.get("fast_mode_pricing", False)),
                )
                in_cost = estimated["input_cost_usd"]
                out_cost = estimated["output_cost_usd"]
                cache_read_cost = estimated["cache_read_cost_usd"]
                cache_creation_cost = estimated["cache_creation_cost_usd"]
                total_cost = estimated["total_cost_usd"]

            totals["completed"] += 1 if entry.get("success") else 0
            totals["failed"] += 0 if entry.get("success") else 1
            totals["total_input_tokens"] += in_tokens
            totals["total_output_tokens"] += out_tokens
            totals["total_cache_read_tokens"] += cached_tokens
            totals["total_cache_creation_tokens"] += cache_creation_tokens
            totals["total_input_cost_usd"] += in_cost
            totals["total_output_cost_usd"] += out_cost
            totals["total_cache_read_cost_usd"] += cache_read_cost
            totals["total_cache_creation_cost_usd"] += cache_creation_cost
            totals["total_cost_usd"] += total_cost

        totals["total_tokens"] = totals["total_input_tokens"] + totals["total_output_tokens"]
        if include_label:
            totals["provider"] = self.translator_provider
        return totals

    def _log_run_cost_summary(
        self,
        run_entries: List[Dict[str, Any]],
        *,
        batch_mode: bool,
    ) -> Dict[str, Any]:
        summary = self._compute_totals_from_entries(run_entries)
        total_tool_calls = sum(
            self._to_int(entry.get("tool_call_count", 0)) for entry in run_entries
        )
        chapters_with_tool_calls = sum(
            1 for entry in run_entries
            if self._to_int(entry.get("tool_call_count", 0)) > 0
        )
        summary["tool_mode"] = self._build_tool_mode_log_status(
            batch_mode=batch_mode,
            tool_call_count=total_tool_calls,
        )
        summary["tool_mode"]["total_tool_calls"] = total_tool_calls
        summary["tool_mode"]["chapters_with_tool_calls"] = chapters_with_tool_calls
        logger.info(
            "Volume translation token summary: "
            f"in={summary['total_input_tokens']:,} | "
            f"out={summary['total_output_tokens']:,} | "
            f"cache_read={summary['total_cache_read_tokens']:,} | "
            f"cache_write={summary['total_cache_creation_tokens']:,}"
        )
        logger.info(
            "Volume translation cost summary: "
            f"input=${summary['total_input_cost_usd']:.6f} | "
            f"output=${summary['total_output_cost_usd']:.6f} | "
            f"cache_read=${summary['total_cache_read_cost_usd']:.6f} | "
            f"cache_write=${summary['total_cache_creation_cost_usd']:.6f} | "
            f"total=${summary['total_cost_usd']:.6f}"
        )
        return summary

    def _canonical_title_from_chapter_id(self, chapter_id: str) -> Optional[str]:
        """Derive stable title from chapter_id (chapter_01 -> Chapter 1)."""
        match = self._CHAPTER_ID_PATTERN.search(str(chapter_id or ""))
        if not match:
            return None
        try:
            number = int(match.group(1))
        except Exception:
            return None
        return f"Chapter {number}"

    def _extract_english_chapter_number(self, title: str) -> Optional[int]:
        """Extract Arabic chapter number from EN-style titles like 'Chapter 4 (Part 1)'."""
        if not title:
            return None
        match = self._EN_CHAPTER_NUM_PATTERN.search(title)
        if not match:
            return None
        try:
            return int(match.group(1))
        except Exception:
            return None

    @staticmethod
    def _is_generic_english_chapter_title(title: Optional[str]) -> bool:
        """
        Return True if title is a generic English chapter label without subtitle.

        Examples:
          - "Chapter 3"            -> True
          - "Chapter 3:"           -> True
          - "Chapter 3 - ..."      -> False
          - "Chapter 3: ..."       -> False
        """
        if not isinstance(title, str):
            return False
        raw = title.strip()
        if not raw:
            return False
        return re.match(r"^chapter\s+\d+\s*:?\s*$", raw, flags=re.IGNORECASE) is not None

    def _resolve_chapter_number(
        self,
        chapter_id: str,
        source_filename: Optional[str] = None,
        fallback: Optional[int] = None,
    ) -> Optional[int]:
        """Resolve chapter number from chapter id/source file with safe fallback."""
        for candidate in (chapter_id, source_filename):
            if not candidate:
                continue
            match = self._CHAPTER_ID_PATTERN.search(str(candidate))
            if not match:
                continue
            try:
                return int(match.group(1))
            except Exception:
                continue
        return fallback

    def _build_context_summary_text(self, plot_points: List[str], chapter_title: str) -> str:
        """Build compact summary text for ContextManager continuity prompt."""
        cleaned = [str(p).strip() for p in (plot_points or []) if str(p).strip()]
        if cleaned:
            return " | ".join(cleaned[:2])
        return chapter_title or "Translated chapter"

    def _resolve_prompt_titles(self, chapters: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
        """
        Resolve chapter titles for prompt/output usage.

        Ambiguous generic titles (duplicates, mismatched chapter numbers) are normalized to
        canonical titles derived from chapter_id.
        """
        title_key = f"title_{self.target_language}"
        raw_by_id: Dict[str, Optional[str]] = {}
        normalized_counter: Dict[str, int] = {}

        for chapter in chapters:
            chapter_id = chapter.get("id", "")
            raw = chapter.get(title_key) or chapter.get("title_en")
            raw = raw.strip() if isinstance(raw, str) else None
            raw_by_id[chapter_id] = raw
            if raw:
                norm = re.sub(r"\s+", " ", raw).strip().lower()
                normalized_counter[norm] = normalized_counter.get(norm, 0) + 1

        resolved: Dict[str, Optional[str]] = {}
        for chapter in chapters:
            chapter_id = chapter.get("id", "")
            raw = raw_by_id.get(chapter_id)
            canonical = self._canonical_title_from_chapter_id(chapter_id)

            if not raw:
                resolved[chapter_id] = canonical
                continue

            norm = re.sub(r"\s+", " ", raw).strip().lower()
            duplicate = normalized_counter.get(norm, 0) > 1
            title_num = self._extract_english_chapter_number(raw)
            canonical_num = self._extract_english_chapter_number(canonical or "")
            mismatch = (
                title_num is not None
                and canonical_num is not None
                and title_num != canonical_num
            )

            # Do NOT normalize descriptive titles solely due chapter number mismatch:
            # prologue/extra sections can shift chapter_id numbering by +1.
            # Normalize only when clearly generic or duplicated.
            generic_raw = self._is_generic_english_chapter_title(raw)
            should_normalize = duplicate or (mismatch and generic_raw)
            if canonical and should_normalize:
                reason = "duplicate title" if duplicate else "generic title/chapter_id mismatch"
                logger.warning(
                    f"[TITLE] Normalizing ambiguous title for {chapter_id}: "
                    f"'{raw}' -> '{canonical}' ({reason})"
                )
                resolved[chapter_id] = canonical
            else:
                resolved[chapter_id] = raw

        return resolved

    def _load_scene_plan_context(self, chapter: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Load per-chapter Stage 1 scene plan from manifest entry.

        Expected manifest key:
          chapter["scene_plan_file"] = "PLANS/chapter_XX_scene_plan.json"
        """
        scene_plan_ref = chapter.get("scene_plan_file")
        if not scene_plan_ref:
            return None
        if not isinstance(scene_plan_ref, str):
            logger.warning(
                f"[STAGE2] Invalid scene_plan_file type for {chapter.get('id')}: "
                f"{type(scene_plan_ref).__name__}"
            )
            return None

        scene_plan_path = Path(scene_plan_ref)
        if not scene_plan_path.is_absolute():
            scene_plan_path = self.work_dir / scene_plan_path

        if not scene_plan_path.exists():
            logger.warning(
                f"[STAGE2] Scene plan file missing for {chapter.get('id')}: {scene_plan_path}"
            )
            return None

        try:
            with scene_plan_path.open("r", encoding="utf-8") as f:
                scene_plan = json.load(f)
        except Exception as e:
            logger.warning(f"[STAGE2] Failed reading scene plan {scene_plan_path}: {e}")
            return None

        if not isinstance(scene_plan, dict):
            logger.warning(f"[STAGE2] Invalid scene plan format (not object): {scene_plan_path}")
            return None

        scenes = scene_plan.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            logger.warning(f"[STAGE2] Scene plan has no scenes: {scene_plan_path}")
            return None

        if not scene_plan.get("chapter_id"):
            scene_plan["chapter_id"] = chapter.get("id")

        pov_tracking = scene_plan.get("pov_tracking")
        if not isinstance(pov_tracking, list) or not pov_tracking:
            chapter_profiles = scene_plan.get("character_profiles", {})
            fallback_name = next(iter(chapter_profiles), "") if isinstance(chapter_profiles, dict) else ""
            if fallback_name:
                scene_plan["pov_tracking"] = [
                    {
                        "character": fallback_name,
                        "start_line": 1,
                        "end_line": None,
                        "description": "POV character (legacy synthesized fallback)",
                    }
                ]
                logger.info(
                    f"[STAGE2] Synthesized missing pov_tracking for {chapter.get('id')} "
                    f"from character_profiles: {fallback_name}"
                )

        logger.info(
            f"[STAGE2] Loaded scene scaffold for {chapter.get('id')}: "
            f"{len(scenes)} beat(s) from {scene_plan_path.name}"
        )
        return scene_plan

    @staticmethod
    def _is_protagonist_name(candidate: str, protagonist_name: str) -> bool:
        if not protagonist_name or not candidate:
            return False
        candidate_l = candidate.lower()
        protagonist_l = protagonist_name.lower()
        return protagonist_l in candidate_l or candidate_l in protagonist_l

    def _resolve_scene_fingerprint(
        self,
        raw_name: str,
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        name = str(raw_name or "").strip()
        if not name:
            return "", None
        fp = self._voice_rag.get_fingerprint(name)
        if not fp:
            return name, None
        canonical = str(fp.get("canonical_name_en", "") or name).strip() or name
        return canonical, fp

    def _apply_scene_plan_voice_overrides(
        self,
        scene_plan: Optional[Dict[str, Any]],
        all_fingerprints: List[Dict[str, Any]],
        *,
        log_prefix: str = "",
    ) -> None:
        self.prompt_loader.clear_scene_voice_overrides()
        self.processor._chapter_pov = ""
        self.processor._chapter_pov_segments = []

        if not scene_plan:
            return

        protagonist_name = ""
        for fp in all_fingerprints:
            if "narrator-protagonist" in str(fp.get("archetype", "")).lower():
                protagonist_name = str(fp.get("canonical_name_en", "") or "").strip()
                break

        profile_prefix = f"[{log_prefix}]" if log_prefix else ""
        pov_tracking: list = scene_plan.get("pov_tracking") or []
        resolved_pov_names: set[str] = set()
        fallback_segment_name = ""
        fallback_segment_fp: Optional[Dict[str, Any]] = None

        if len(pov_tracking) >= 2:
            segments = []
            unique_segment_names: set[str] = set()
            for seg_meta in pov_tracking:
                if not isinstance(seg_meta, dict):
                    continue
                char_name = seg_meta.get("character", "")
                canonical_name, pov_fp = self._resolve_scene_fingerprint(char_name)
                if not pov_fp:
                    logger.debug(
                        f"[POV SEGMENTS]{profile_prefix} No fingerprint for '{char_name}' — segment skipped"
                    )
                    continue
                resolved_pov_names.add(canonical_name.lower())
                unique_segment_names.add(canonical_name.lower())
                segments.append(
                    {
                        "character": canonical_name,
                        "fingerprint": pov_fp,
                        "start_line": seg_meta.get("start_line"),
                        "end_line": seg_meta.get("end_line"),
                        "description": seg_meta.get("description", ""),
                    }
                )
            if len(segments) >= 2 and len(unique_segment_names) >= 2:
                self.prompt_loader.set_pov_segments(segments)
                self.processor._chapter_pov_segments = segments
                logger.info(
                    f"[POV SEGMENTS]{profile_prefix}[Gap 8.2 ext.] Multi-POV hot-switch: "
                    f"{len(segments)} segments ({' → '.join(s['character'] for s in segments)})"
                )
            else:
                if segments:
                    fallback_segment_name = str(segments[0].get("character", "") or "").strip()
                    fallback_segment_fp = segments[0].get("fingerprint")
                logger.debug(
                    f"[POV SEGMENTS]{profile_prefix} Multi-POV plan collapsed to "
                    f"{len(unique_segment_names)} unique fingerprinted voice(s) — falling back "
                    f"to single-POV check"
                )

        if not self.processor._chapter_pov_segments:
            pov_char_name = ""
            pov_fp = None
            if len(pov_tracking) == 1 and isinstance(pov_tracking[0], dict):
                pov_char_name = str(pov_tracking[0].get("character", "") or "").strip()
            elif fallback_segment_name:
                pov_char_name = fallback_segment_name
                pov_fp = fallback_segment_fp
            if not pov_char_name:
                chapter_profiles = scene_plan.get("character_profiles", {})
                pov_char_name = next(iter(chapter_profiles), "") if isinstance(chapter_profiles, dict) else ""

            canonical_pov, resolved_pov_fp = self._resolve_scene_fingerprint(pov_char_name)
            if resolved_pov_fp is not None:
                pov_fp = resolved_pov_fp
            if canonical_pov:
                resolved_pov_names.add(canonical_pov.lower())
            if pov_fp and not self._is_protagonist_name(canonical_pov, protagonist_name):
                self.prompt_loader.set_pov_character_override(canonical_pov, pov_fp)
                self.processor._chapter_pov = canonical_pov
                if protagonist_name:
                    logger.info(
                        f"[POV OVERRIDE]{profile_prefix}[Gap 8.2] POV Character: "
                        f"'{canonical_pov}' (distinct from narrator-protagonist '{protagonist_name}')"
                    )
                else:
                    logger.info(
                        f"[POV OVERRIDE]{profile_prefix}[Gap 8.2] POV Character: '{canonical_pov}'"
                    )
            elif pov_fp and canonical_pov:
                self.processor._chapter_pov = canonical_pov
                logger.debug(
                    f"[POV OVERRIDE]{profile_prefix} POV Character '{canonical_pov}' matches "
                    "the narrator-protagonist fingerprint; no override needed"
                )
            elif pov_char_name:
                logger.debug(
                    f"[POV OVERRIDE]{profile_prefix} No usable POV fingerprint for "
                    f"'{pov_char_name}'"
                )

        chapter_profiles = scene_plan.get("character_profiles", {})
        secondary_count = 0
        if isinstance(chapter_profiles, dict):
            for raw_name in chapter_profiles.keys():
                canonical_name, fp = self._resolve_scene_fingerprint(str(raw_name or "").strip())
                if not fp or not canonical_name:
                    continue
                if self._is_protagonist_name(canonical_name, protagonist_name):
                    continue
                if canonical_name.lower() in resolved_pov_names:
                    continue
                self.prompt_loader.add_secondary_fingerprint(canonical_name, fp)
                secondary_count += 1

        if secondary_count:
            logger.info(
                f"[SECONDARY FP]{profile_prefix} Added {secondary_count} secondary character "
                f"voice anchor(s) from scene plan"
            )

    @staticmethod
    def _estimate_tokens_from_chars(text_or_chars: Any) -> int:
        """Rough token estimator using ~0.5 tokens/char heuristic for JP-heavy prompts."""
        if isinstance(text_or_chars, str):
            chars = len(text_or_chars)
        else:
            try:
                chars = int(text_or_chars)
            except (TypeError, ValueError):
                chars = 0
        if chars <= 0:
            return 0
        return max(1, int(chars * 0.5))

    def _estimate_full_prequel_context_tokens(self, target_chapters: List[Dict[str, Any]]) -> Dict[str, int]:
        """Build a conservative context estimate used by full-prequel cache gate."""
        cfg = self._full_prequel_gate_config
        estimated_system_tokens = int(cfg.get("estimated_system_tokens", 0) or 0)
        estimated_prequel_tokens = int(cfg.get("estimated_prequel_bundle_tokens", 0) or 0)
        estimated_chapter_tokens = int(cfg.get("estimated_chapter_prompt_tokens", 0) or 0)

        try:
            system_instruction = self.prompt_loader.build_system_instruction(genre=self._genre)
            estimated_system_tokens = max(
                estimated_system_tokens,
                self._estimate_tokens_from_chars(system_instruction),
            )
        except Exception:
            pass

        max_source_chars = 0
        for chapter in target_chapters:
            jp_file = chapter.get("jp_file") or chapter.get("source_file")
            if not jp_file:
                continue
            source_path = self.work_dir / "JP" / str(jp_file)
            if not source_path.exists():
                continue
            try:
                max_source_chars = max(max_source_chars, len(source_path.read_text(encoding="utf-8")))
            except Exception:
                continue

        estimated_chapter_tokens = max(
            estimated_chapter_tokens,
            self._estimate_tokens_from_chars(max_source_chars),
        )

        if self.bible_pull_context_block:
            estimated_prequel_tokens = max(
                estimated_prequel_tokens,
                self._estimate_tokens_from_chars(self.bible_pull_context_block),
            )

        total_estimate = max(0, estimated_system_tokens + estimated_prequel_tokens + estimated_chapter_tokens)
        return {
            "estimated_system_tokens": max(0, estimated_system_tokens),
            "estimated_prequel_bundle_tokens": max(0, estimated_prequel_tokens),
            "estimated_chapter_prompt_tokens": max(0, estimated_chapter_tokens),
            "total_estimated_tokens": total_estimate,
        }

    def _evaluate_full_prequel_cache_gate(
        self,
        *,
        target_chapters: List[Dict[str, Any]],
        preflight: PreflightInvariantReport,
    ) -> Dict[str, Any]:
        """Evaluate enforceable full-prequel gate and persist decision for this run."""
        estimates = self._estimate_full_prequel_context_tokens(target_chapters)
        route = get_phase2_openrouter_route()
        adn_cfg = self.translation_config.get("adn_v2_enforcement", {})
        if not isinstance(adn_cfg, dict):
            adn_cfg = {}

        decision = evaluate_full_prequel_cache_gate(
            provider=self.translator_provider,
            route_enabled=bool(route.get("enabled", False)),
            adn_v2_enabled=bool(adn_cfg.get("enabled", False)),
            name_order_preflight_passed=preflight.passed,
            context_tokens_estimate=estimates.get("total_estimated_tokens", 0),
            config=self._full_prequel_gate_config,
        )
        decision.update(estimates)
        decision.setdefault("runtime_fallback", False)
        decision.setdefault("events", [])
        self._full_prequel_gate_decision = decision
        return decision

    def _record_full_prequel_gate_event(
        self,
        *,
        reason_code: str,
        reason: str,
        chapter_id: Optional[str] = None,
    ) -> None:
        event = {
            "at": datetime.now().isoformat(),
            "reason_code": reason_code,
            "reason": reason,
            "chapter_id": chapter_id,
        }
        events = self._full_prequel_gate_decision.setdefault("events", [])
        if isinstance(events, list):
            events.append(event)

    def _trigger_full_prequel_runtime_fallback(
        self,
        *,
        reason_code: str,
        reason: str,
        chapter_id: Optional[str] = None,
    ) -> None:
        if self._full_prequel_gate_decision.get("runtime_fallback"):
            return
        self._full_prequel_gate_decision["allowed"] = False
        self._full_prequel_gate_decision["active_mode"] = self._full_prequel_gate_decision.get(
            "fallback_mode", "series_bible_rag"
        )
        self._full_prequel_gate_decision["runtime_fallback"] = True
        self._full_prequel_gate_decision["reason_code"] = reason_code
        self._full_prequel_gate_decision["reason"] = reason
        self._record_full_prequel_gate_event(
            reason_code=reason_code,
            reason=reason,
            chapter_id=chapter_id,
        )
        logger.warning("[FULL-PREQUEL][FALLBACK] %s: %s", reason_code, reason)

        if self.volume_cache_name:
            try:
                self.client.delete_cache(self.volume_cache_name)
            except Exception as exc:
                logger.warning("[FULL-PREQUEL][FALLBACK] Failed deleting active cache: %s", exc)
            finally:
                self.volume_cache_name = None

    def _maybe_trigger_full_prequel_runtime_fallback(
        self,
        *,
        chapter_id: str,
        result: TranslationResult,
    ) -> None:
        if not self._full_prequel_gate_decision.get("requested"):
            return
        if not self._full_prequel_gate_decision.get("allowed"):
            return
        if self._full_prequel_gate_decision.get("runtime_fallback"):
            return

        error_text = str(result.error or "")
        lower_error = error_text.lower()

        if "401" in lower_error and ("authentication" in lower_error or "x-api-key" in lower_error):
            self._trigger_full_prequel_runtime_fallback(
                reason_code=FULL_PREQUEL_CACHE_REASON_CODES["fallback_auth_401"],
                reason="Authentication error detected while full-prequel cache mode was active.",
                chapter_id=chapter_id,
            )
            return

        if re.search(r"\b5\d\d\b", lower_error):
            self._full_prequel_5xx_streak += 1
            max_5xx = int(self._full_prequel_gate_config.get("max_transport_5xx_before_fallback", 2) or 2)
            if self._full_prequel_5xx_streak >= max_5xx:
                self._trigger_full_prequel_runtime_fallback(
                    reason_code=FULL_PREQUEL_CACHE_REASON_CODES["fallback_transport_5xx"],
                    reason=(
                        "Transport 5xx failures exceeded configured threshold "
                        f"({self._full_prequel_5xx_streak}/{max_5xx})."
                    ),
                    chapter_id=chapter_id,
                )
                return
        else:
            self._full_prequel_5xx_streak = 0

        flags = result.adn_review_flags if isinstance(result.adn_review_flags, dict) else {}
        if bool(flags.get("hard_fail", False)):
            self._trigger_full_prequel_runtime_fallback(
                reason_code=FULL_PREQUEL_CACHE_REASON_CODES["fallback_adn_hard_fail"],
                reason="ADN hard_fail flag detected while full-prequel cache mode was active.",
                chapter_id=chapter_id,
            )

    def _persist_full_prequel_gate_state(self) -> None:
        translator_state = self.manifest.setdefault("pipeline_state", {}).setdefault("translator", {})
        translator_state["full_prequel_cache_gate"] = dict(self._full_prequel_gate_decision)
        self.translation_log["last_full_prequel_cache_gate"] = dict(self._full_prequel_gate_decision)
    
    def _prewarm_cache(self):
        """Pre-warm context cache with system instruction before translation starts."""
        try:
            # Build system instruction (same as what translation will use)
            system_instruction = self.prompt_loader.build_system_instruction(genre=self._genre)

            # Use active model name (provider-agnostic)
            model_name = self._active_model_name

            # Create cache
            success = self.client.warm_cache(system_instruction, model_name)
            
            if success:
                logger.info("✓ Cache pre-warmed successfully. All chapters will use cached context.")
            else:
                logger.warning("Cache pre-warming failed. First chapter will create cache.")
                
        except Exception as e:
            logger.warning(f"Cache pre-warming error: {e}. Will create cache during first chapter.")

    def _create_volume_cache(
        self,
        chapter_configs: List[Dict[str, Any]],
        model_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        Create one Gemini cache containing full JP volume text + system instruction.

        This cache is shared across all chapter translations in the run.
        """
        if not self.client.enable_caching:
            return None
        if not self.volume_cache_enabled:
            logger.info("Volume-level cache disabled by translation.massive_chapter.enable_volume_cache")
            return None
        openrouter_route_active = bool(get_phase2_openrouter_route().get("enabled", False))

        chapter_blocks: List[str] = []
        cached_chapter_ids: List[str] = []
        missing_chapter_ids: List[str] = []
        total_target_chapters = len(chapter_configs)
        missing_files = 0

        for chapter in chapter_configs:
            chapter_id = chapter.get("id", "unknown")
            jp_file = chapter.get("jp_file") or chapter.get("source_file")
            if not jp_file:
                missing_chapter_ids.append(chapter_id)
                continue

            source_path = self.work_dir / "JP" / jp_file
            if not source_path.exists():
                missing_files += 1
                missing_chapter_ids.append(chapter_id)
                continue

            try:
                jp_text = source_path.read_text(encoding="utf-8")
                canonical_title = self._canonical_title_from_chapter_id(chapter_id) or chapter_id
                chapter_blocks.append(
                    f"<CHAPTER id='{chapter_id}' canonical_title='{canonical_title}' source_file='{jp_file}'>\n"
                    f"<!-- TARGET_CHAPTER: {chapter_id} | {canonical_title} -->\n"
                    f"{jp_text}\n"
                    f"</CHAPTER>"
                )
                cached_chapter_ids.append(chapter_id)
            except Exception as e:
                missing_chapter_ids.append(chapter_id)
                logger.warning(f"Failed reading JP source for cache ({chapter_id}): {e}")

        if not chapter_blocks:
            logger.warning("Volume cache skipped: no JP chapter text available")
            return None

        cache_guardrail = (
            "=== REFERENCE CORPUS (DO NOT TRANSLATE DIRECTLY) ===\n"
            "This cached corpus is continuity/reference memory only.\n"
            "When translating, output must be based ONLY on the runtime <SOURCE_TEXT> block.\n"
            "Never translate this cached corpus itself.\n"
            "=== END REFERENCE CORPUS GUARDRAIL ===\n"
        )
        full_volume_text = f"{cache_guardrail}\n\n" + "\n\n---\n\n".join(chapter_blocks)
        system_instruction = self.prompt_loader.build_system_instruction(genre=self._genre)

        try:
            target_model = model_name or get_model_name()
            cache_name = self.client.create_cache(
                model=target_model,
                system_instruction=system_instruction,
                contents=[full_volume_text],
                ttl_seconds=self.volume_cache_ttl_seconds,
                display_name=f"{self.manifest.get('volume_id', self.work_dir.name)}_full",
            )
            if cache_name:
                self._volume_cache_stats = {
                    "target_chapters": total_target_chapters,
                    "cached_chapters": len(cached_chapter_ids),
                    "missing_files": missing_files,
                    "missing_chapter_ids": missing_chapter_ids,
                    "cached_chapter_ids": cached_chapter_ids,
                    "volume_chars": len(full_volume_text),
                }
                if openrouter_route_active:
                    logger.info(
                        f"[CACHE] Created OpenRouter emulated cache key {cache_name} "
                        f"({len(chapter_blocks)} chapters prepared, {len(full_volume_text)} chars, "
                        f"missing={missing_files})"
                    )
                    logger.info(
                        "[CACHE] OpenRouter adapter compatibility mode: full-LN corpus is prepared for "
                        "coverage/accounting, but not persisted server-side as external prompt cache."
                    )
                else:
                    logger.info(
                        f"[CACHE] Created volume cache {cache_name} "
                        f"({len(chapter_blocks)} chapters, {len(full_volume_text)} chars, "
                        f"missing={missing_files})"
                    )
                logger.info(
                    f"[CACHE] Source coverage verification: "
                    f"{len(cached_chapter_ids)}/{total_target_chapters} chapters packaged"
                )
                if missing_chapter_ids:
                    logger.warning(
                        f"[CACHE] Chapters missing from cache payload: "
                        f"{', '.join(missing_chapter_ids[:10])}"
                    )
                return cache_name
        except Exception as e:
            logger.warning(f"Failed to create volume-level cache: {e}")

        return None

    def translate_volume(self, clean_start: bool = False, chapters: List[str] = None):
        """
        Run translation for the volume.
        """
        logger.info(f"Starting translation for volume in {self.work_dir}")
        
        # ===== PRE-FLIGHT VALIDATION: v3.6 Manifest Check =====
        schema_version = self.manifest.get("schema_version", "unknown")
        if schema_version == "v3.6_enhanced":
            logger.info("Detected v3.6 enhanced schema - running manifest validator...")
            validator_script = Path(__file__).parent.parent.parent / "scripts" / "validate_manifest_v3_6.py"
            manifest_path = self.work_dir / "manifest.json"
            
            if validator_script.exists():
                import subprocess
                result = subprocess.run(
                    ["python3", str(validator_script), str(manifest_path)],
                    capture_output=True,
                    text=True
                )
                
                # Print validator output
                print(result.stdout)
                
                if result.returncode != 0:
                    logger.warning(
                        "Manifest validation found issues. "
                        "Translation can proceed but quality may be affected."
                    )
                    response = input("Continue anyway? (y/N): ")
                    if response.lower() != 'y':
                        logger.info("Translation cancelled by user.")
                        return
                else:
                    logger.info("✓ Manifest validation passed - ready for quality translation")
            else:
                logger.warning(f"Validator script not found at {validator_script}")
        
        # Check prerequisite
        librarian_status = self.manifest.get("pipeline_state", {}).get("librarian", {}).get("status")
        if librarian_status != "completed":
            logger.warning(f"Librarian phase not marked as completed (status: {librarian_status})")
            # Proceed with warning? Or stop? Let's stop to be safe unless forced (not imp yet)
            # For now, just warn.
        
        # Support both v2 (chapters at root) and v3.5 (chapters under structure)
        manifest_chapters = self.manifest.get("chapters", [])
        if not manifest_chapters:
            manifest_chapters = self.manifest.get("structure", {}).get("chapters", [])
        
        if not manifest_chapters:
            logger.error("No chapters found in manifest (checked both root and structure.chapters)")
            return

        # Filter chapters if specific list provided
        target_chapters = manifest_chapters
        if chapters:
            target_chapters = [c for c in manifest_chapters if c["id"] in chapters]
            
        total = len(target_chapters)
        logger.info(f"Targeting {total} chapters")
        resolved_titles = self._resolve_prompt_titles(target_chapters)

        preflight = self._run_pre_phase2_invariant_gate(target_chapters, batch_mode=False)
        if not preflight.passed:
            logger.error("[PREFLIGHT] Blocking Phase 2 startup due to invariant failure(s).")
            return

        self._evaluate_full_prequel_cache_gate(
            target_chapters=target_chapters,
            preflight=preflight,
        )
        if self._full_prequel_gate_decision.get("requested"):
            if self._full_prequel_gate_decision.get("allowed"):
                logger.info(
                    "[FULL-PREQUEL][GATE] Enabled (%s)",
                    self._full_prequel_gate_decision.get("reason_code"),
                )
            else:
                logger.warning(
                    "[FULL-PREQUEL][GATE] Denied (%s): %s",
                    self._full_prequel_gate_decision.get("reason_code"),
                    self._full_prequel_gate_decision.get("reason"),
                )

        # Update pipeline state
        if "translator" not in self.manifest["pipeline_state"]:
            self.manifest["pipeline_state"]["translator"] = {}
        self.manifest["pipeline_state"]["translator"]["status"] = "in_progress"
        self.manifest["pipeline_state"]["translator"]["target_language"] = self.target_language
        self.manifest["pipeline_state"]["translator"]["started_at"] = datetime.now().isoformat()
        self._persist_full_prequel_gate_state()
        self._save_manifest()

        # Cache strategy — provider-dependent:
        #   Gemini:    full-LN corpus cache (1M context, named CachedContent resource)
        #   Anthropic: system-instruction-only cache (200K context limit; JP corpus
        #              excluded to avoid exceeding the limit — continuity is handled
        #              by per-chapter context summaries instead)
        if self.client.enable_caching:
            provider = get_translator_provider()
            openrouter_route_active = bool(get_phase2_openrouter_route().get("enabled", False))
            if self._full_prequel_gate_decision.get("allowed"):
                logger.info(
                    "[FULL-PREQUEL][CACHE] Attempting full-prequel cache path under enforced gate."
                )
                self.volume_cache_name = self._create_volume_cache(
                    target_chapters,
                    model_name=self._active_model_name,
                )
                if self.volume_cache_name:
                    logger.info(
                        "[FULL-PREQUEL][CACHE] Full-prequel cache active: %s",
                        self.volume_cache_name,
                    )
                else:
                    self._trigger_full_prequel_runtime_fallback(
                        reason_code=FULL_PREQUEL_CACHE_REASON_CODES["cache_warm_failed"],
                        reason="Full-prequel cache warm/create failed at run start; reverting to fallback mode.",
                    )

            if openrouter_route_active:
                logger.info(
                    "[CACHE] OpenRouter route active: adapter cache is emulated and stores "
                    "system instruction only (no server-side full-LN prompt cache persistence)."
                )
                self._prewarm_cache()
                logger.info(
                    "[CACHE VERIFY] OpenRouter emulated cache warmed (system instruction cached). "
                    "JP corpus continuity remains chapter-scoped/context-managed."
                )
            elif provider == "anthropic":
                logger.info(
                    "[CACHE] Anthropic provider: using system-instruction-only cache "
                    "(full-LN corpus excluded — 200K context limit; continuity via summaries)"
                )
                self._prewarm_cache()
                logger.info("[CACHE VERIFY] System instruction cached. JP corpus handled per-chapter via context summaries.")
            else:
                if not self.volume_cache_name:
                    self.volume_cache_name = self._create_volume_cache(target_chapters, model_name=self._active_model_name)
                if self.volume_cache_name:
                    logger.info(f"[CACHE] Volume cache ready for run: {self.volume_cache_name}")
                    if self._volume_cache_stats:
                        logger.info(
                            f"[CACHE] Run verification: "
                            f"cached {self._volume_cache_stats.get('cached_chapters', 0)}/"
                            f"{self._volume_cache_stats.get('target_chapters', 0)} chapter sources"
                        )
                    logger.info(
                        "[CACHE VERIFY] Full-LN JP corpus + system instruction are bundled "
                        "in the active external cache for chapter translation."
                    )
                else:
                    logger.info("Pre-warming context cache (volume cache unavailable)...")
                    self._prewarm_cache()
                    logger.info(
                        "[CACHE VERIFY] Falling back to prompt-only internal cache "
                        "(no full-LN external cache)."
                    )
        
        success_count = 0
        run_entries: List[Dict[str, Any]] = []
        
        # Language-specific output directory (e.g., EN/, VN/)
        output_dir_name = self.target_language.upper()
        output_dir = self.work_dir / output_dir_name
        output_dir.mkdir(exist_ok=True)

        for i, chapter in enumerate(target_chapters):
            chapter_id = chapter["id"]
            # File names from manifest
            jp_file = chapter.get("jp_file") or chapter.get("source_file")
            # Usually Librarian outputs simple filenames, assume paths relative to JP/ and output dir

            if not jp_file:
                logger.error(f"Chapter {chapter_id} missing source filename config")
                continue

            source_path = self.work_dir / "JP" / jp_file

            # Target file: Use manifest's translated_file or language-specific file
            # Fallback: add language suffix to source filename if not specified
            translated_filename = (
                chapter.get(f"{self.target_language}_file") or 
                chapter.get("translated_file") or
                jp_file.replace('.md', f'_{self.target_language.upper()}.md')
            )
            output_path = output_dir / translated_filename

            # Check if already done (unless clean_start)
            if not clean_start and chapter.get("translation_status") == "completed":
                # Check if file actually exists
                if output_path.exists():
                    logger.info(f"Skipping completed chapter {chapter_id}")
                    success_count += 1
                    continue

            # Get translated title from manifest (language-specific or fallback to EN)
            title_key = f"title_{self.target_language}"
            translated_title = resolved_titles.get(chapter_id)
            # JP title: the original EPUB TOC label (e.g. "第一章"). Sent to the model
            # alongside the EN title so it has unambiguous chapter identity without
            # spending thinking budget reconciling pipeline ID vs. JP source heading.
            jp_chapter_title = chapter.get("title") or chapter.get("title_jp")

            logger.info(f"Translating [{i+1}/{total}] {chapter_id} to {self.language_name}...")

            # Check for model override in chapter metadata
            chapter_model = chapter.get("model")
            if chapter_model:
                logger.info(f"     [OVERRIDE] Using model: {chapter_model}")
            
            # Select cache for this chapter:
            # 1) Volume-level full JP cache (preferred for massive LNs)
            # 2) Continuity schema cache (legacy fallback)
            cached_content_name = self.volume_cache_name
            if self.enable_continuity and i > 0 and not cached_content_name:  # Not first chapter
                try:
                    cached_content_name = self.per_chapter_workflow.get_cache_for_chapter(i + 1)
                    if cached_content_name:
                        logger.info(f"     [CONTINUITY] Using cached schema from Chapter {i}")
                except Exception as e:
                    logger.warning(f"Could not load cached schema: {e}")
            # === END CACHE CHECK ===

            effective_cache_name = cached_content_name
            default_model = get_model_name()
            if chapter_model and chapter_model != default_model and cached_content_name:
                logger.info(
                    f"     [CACHE] Skipping cache for model override "
                    f"({chapter_model} != {default_model})"
                )
                effective_cache_name = None

            if i == 0:
                if self.volume_cache_name and effective_cache_name:
                    logger.info(
                        "[CACHE VERIFY] Chapter translation will use external full-LN cache "
                        "with embedded prompt instructions."
                    )
                elif effective_cache_name:
                    logger.info("[CACHE VERIFY] Chapter translation will use cached prompt context.")
                else:
                    # For Anthropic provider, cache is inline (not a named resource).
                    # effective_cache_name is always None for Anthropic — this is expected,
                    # not a cache miss. The actual cache injection happens inside AnthropicClient.generate().
                    if get_translator_provider() == "anthropic":
                        logger.info("[CACHE VERIFY] Anthropic inline cache active (system blocks injected per-chapter).")
                    else:
                        logger.warning("[CACHE VERIFY] Chapter translation running without cache.")

            scene_plan = self._load_scene_plan_context(chapter)
            is_afterword = is_afterword_chapter(chapter, source_path=source_path)
            inline_afterword_marker: Optional[Dict[str, Any]] = None
            chapter_translation_brief: Optional[str] = None
            self.processor._afterword_mode_override = False
            self.prompt_loader.set_inline_afterword_override(None)
            if is_afterword:
                scene_plan = None
                self.prompt_loader.set_voice_directive("", "")
                chapter_translation_brief = self._build_afterword_tone_directive()
                self.processor._afterword_mode_override = True
                logger.info(
                    "[AFTERWORD] %s detected: bypassing EPS/fingerprint/scene-plan constraints.",
                    chapter_id,
                )
            else:
                inline_afterword_marker = self._detect_inline_afterword_segment(scene_plan)
                if inline_afterword_marker:
                    self.processor._afterword_mode_override = True
                    self.prompt_loader.set_inline_afterword_override(inline_afterword_marker)
                    chapter_translation_brief = self._build_inline_afterword_tone_directive(
                        inline_afterword_marker
                    )
                    logger.info(
                        "[INLINE AFTERWORD] %s detected (%s): enabling segment override + EPS/KF bypass",
                        chapter_id,
                        inline_afterword_marker.get("source", "scene_plan"),
                    )

            # ── Koji Fox Voice Directive Injection ───────────────────────────
            if not is_afterword:
                try:
                    # Extract characters in this chapter from JP source
                    jp_text = source_path.read_text(encoding="utf-8") if source_path.exists() else ""
                    chapter_chars = self._voice_rag.extract_characters_from_jp(jp_text)

                    # Get EPS data for this chapter
                    chapter_eps = self._arc_tracker.get_eps_for_chapter(chapter_id)

                    # Build voice directive
                    voice_dir = self._voice_rag.get_voice_directive(chapter_chars, chapter_eps)
                    arc_dir = self._arc_tracker.get_arc_directive(chapter_chars, chapter_id)

                    # Inject into prompt_loader
                    if voice_dir or arc_dir:
                        self.prompt_loader.set_voice_directive(voice_dir, arc_dir)
                        logger.debug(f"[KOJI FOX] Injected voice directives for {chapter_chars}")

                    # Populate ChapterProcessor fields for scene-anchor injection
                    all_fingerprints = self._voice_rag.all_fingerprints()
                    self.processor._voice_fingerprints = all_fingerprints
                    self.processor._eps_data = chapter_eps

                    self._apply_scene_plan_voice_overrides(scene_plan, all_fingerprints)

                except Exception as e:
                    logger.warning(f"[KOJI FOX] Non-fatal error injecting voice directives: {e}")
            else:
                self.processor._voice_fingerprints = []
                self.processor._eps_data = {}
                self._apply_scene_plan_voice_overrides(None, [])
            # ── End Koji Fox ─────────────────────────────────────────────────

            result = self.processor.translate_chapter(
                source_path,
                output_path,
                chapter_id,
                en_title=translated_title,  # en_title param kept for backward compatibility
                jp_title=jp_chapter_title,
                model_name=chapter_model,
                cached_content=effective_cache_name,
                volume_cache=effective_cache_name if self.volume_cache_name else None,
                scene_plan=scene_plan,
                translation_brief=chapter_translation_brief,
            )
            initial_result = result

            # Fallback to configured fallback model on failure (safety blocks, rate limits, etc)
            if not result.success and not chapter_model:
                # Use provider-correct fallback model
                if self._fallback_model_override:
                    fallback_model = self._fallback_model_override
                elif get_translator_provider() == "anthropic":
                    fallback_model = get_anthropic_config().get("fallback_model", "claude-haiku-4-5-20251001")
                else:
                    fallback_model = get_fallback_model_name()
                logger.warning(f"Translation failed, retrying with fallback model ({fallback_model})...")

                # Clear cache since we're switching models (cache is model-specific)
                if self.client.enable_caching:
                    logger.info("Clearing cache before switching to fallback model...")
                    self.client.clear_cache()

                result = self.processor.translate_chapter(
                    source_path,
                    output_path,
                    chapter_id,
                    en_title=translated_title,
                    jp_title=jp_chapter_title,
                    model_name=fallback_model,
                    cached_content=None,
                    volume_cache=None,
                    scene_plan=scene_plan,
                    translation_brief=chapter_translation_brief,
                )
                if isinstance(result.cost_audit, dict):
                    for attempt in list(result.cost_audit.get("attempts", []) or []):
                        if not isinstance(attempt, dict):
                            continue
                        if attempt.get("attempt_type") == "translation_primary":
                            attempt["attempt_type"] = "fallback_model_retry"
                            attempt["note"] = f"Retry using fallback model {fallback_model}"
                result.cost_audit = self._merge_result_cost_audits(
                    initial_result,
                    result,
                    merge_reason=f"fallback_model_retry:{fallback_model}",
                )
                if result.success:
                    logger.info(f"     [FALLBACK] Successfully translated with {fallback_model}")
                    # Save fallback model to manifest for tracking
                    chapter["model"] = fallback_model

            self._apply_adn_review_flags_to_chapter(chapter, result)
            self._maybe_trigger_full_prequel_runtime_fallback(
                chapter_id=chapter_id,
                result=result,
            )
            
            # Update log + run summary entry
            log_entry = self._build_log_entry(
                chapter_id=chapter_id,
                result=result,
                batch_mode=False,
            )
            run_entries.append(log_entry)
            
            # Remove old entry if exists
            self.translation_log["chapters"] = [c for c in self.translation_log["chapters"] if c["chapter_id"] != chapter_id]
            self.translation_log["chapters"].append(log_entry)
            self._save_log()

            if result.success:
                chapter["translation_status"] = "completed"
                # Use language-specific key (e.g., "vn_file" or "en_file")
                file_key = f"{self.target_language}_file"
                # Store the actual output filename (not the fallback variable)
                chapter[file_key] = output_path.name  # e.g., "CHAPTER_01_EN.md"

                translation_text = ""
                try:
                    with open(output_path, 'r', encoding='utf-8') as f:
                        translation_text = f.read()
                except Exception as e:
                    logger.error(f"Failed reading translated chapter for post-processing: {e}")
                
                # === PER-CHAPTER WORKFLOW: Extract schema, review, cache ===
                if self.enable_continuity:
                    logger.info(f"\n{'─'*60}")
                    logger.info(f"  Starting per-chapter schema workflow...")
                    logger.info(f"{'─'*60}\n")
                    
                    try:
                        if not translation_text.strip():
                            logger.warning("Translated chapter text is empty; skipping continuity schema extraction")
                        else:
                            # Process chapter (extract, review, cache)
                            workflow_success, cache_name = self.per_chapter_workflow.process_chapter(
                                chapter_num=i + 1,  # 1-indexed chapter number
                                chapter_id=chapter_id,
                                translation_text=translation_text,
                                skip_review=False  # User review required
                            )

                            if not workflow_success:
                                logger.warning("Per-chapter workflow failed or was cancelled by user")
                                # User cancelled - should we stop the pipeline?
                                if input("\nContinue to next chapter anyway? (y/N): ").strip().lower() != 'y':
                                    logger.info("Pipeline stopped by user")
                                    break

                            # Store cache info in chapter metadata
                            if cache_name:
                                chapter["schema_cache"] = cache_name
                        
                    except Exception as e:
                        logger.error(f"Per-chapter workflow error: {e}")
                        logger.warning("Continuing without schema extraction...")
                else:
                    logger.info(f"\n{'─'*60}")
                    logger.info(f"  [CONTINUITY DISABLED] Skipping schema extraction")
                    logger.info(f"{'─'*60}\n")
                
                # === END PER-CHAPTER WORKFLOW ===

                # === CHAPTER SUMMARIZATION + CONTEXT UPDATE ===
                chapter_num = self._resolve_chapter_number(
                    chapter_id=chapter_id,
                    source_filename=jp_file,
                    fallback=i + 1,
                )

                # === ARC-CLOSING EXTRACTION ===
                # Extract POV arc closings from the translated output for retrospective anchoring.
                # Runs only when prose_anchor is enabled and the output file exists.
                _arc_closings = []
                _prose_anchor_cfg = get_translation_config().get("context", {}).get("prose_anchor", {})
                if _prose_anchor_cfg.get("enabled", False) and output_path.exists():
                    try:
                        _aggregator = VolumeContextAggregator(self.work_dir)
                        _arc_closings = _aggregator.extract_arc_closings(
                            en_chapter_path=output_path,
                            chapter_num=chapter_num or (i + 1),
                            lines_per_closing=_prose_anchor_cfg.get("lines_per_closing", 20),
                        )
                    except Exception as _ae:
                        logger.warning(f"[ARC-CLOSE] Extraction failed for {chapter_id}: {_ae}")
                # === END ARC-CLOSING EXTRACTION ===
                context_title = (
                    translated_title
                    or chapter.get(f"title_{self.target_language}")
                    or chapter.get("title_en")
                    or chapter.get("title")
                    or self._canonical_title_from_chapter_id(chapter_id)
                    or chapter_id
                )

                self.context_manager.register_chapter_complete(
                    chapter_id=chapter_id,
                    chapter_num=chapter_num,
                    chapter_title=context_title,
                    arc_closings=_arc_closings,
                )
                
                success_count += 1
                if result.warnings:
                    logger.warning(
                        f"{chapter_id} completed with {len(result.warnings)} warning(s): "
                        f"{'; '.join(result.warnings[:3])}"
                    )
                logger.info(f"Completed {chapter_id}. Audit passed: {result.audit_result.passed if result.audit_result else 'N/A'}")
            else:
                chapter["translation_status"] = "failed"
                logger.error(f"Failed {chapter_id}: {result.error}")
            
            # Update manifest checkpoint
            self._save_manifest()

            # Rate limiting delay for TPM management
            # With context caching, TPM usage is reduced by 87%, so only need short delay
            if i < total - 1:
                delay = 5 if self.client.enable_caching else 60
                logger.info(f"Waiting {delay} seconds before next chapter (TPM management)...")
                time.sleep(delay)

        # Final Status
        if success_count == total:
            self.manifest["pipeline_state"]["translator"]["status"] = "completed"
            logger.info("Volume translation COMPLETED")
            logger.info("Post-processing profile: deterministic copyedit pass + CJK cleanup/validation.")
            
            # Finalize continuity pack (aggregate all chapter snapshots)
            logger.info("\nFinalizing continuity pack...")
            try:
                pack_summary = self.per_chapter_workflow.finalize()
                logger.info(f"✓ Continuity pack finalized with {len(pack_summary.get('chapter_snapshots', []))} snapshots")
            except Exception as e:
                logger.error(f"Failed to finalize continuity pack: {e}")
            
            # Save continuity pack for future volumes (old system for backward compat)
            logger.info("Saving legacy continuity pack format...")
            try:
                continuity_manager = ContinuityPackManager(self.work_dir)
                pack = continuity_manager.extract_continuity_from_volume(self.work_dir, self.manifest, target_language=self.target_language)
                continuity_manager.save_continuity_pack(pack)
                logger.info(f"✓ Continuity pack saved ({len(pack.roster)} names, {len(pack.glossary)} terms)")
            except Exception as e:
                logger.warning(f"Failed to save continuity pack: {e}")
        else:
            self.manifest["pipeline_state"]["translator"]["status"] = "partial"
            logger.warning(f"Volume translation PARTIAL ({success_count}/{total} completed)")

        copyedit_summary = None
        if success_count > 0:
            copyedit_summary = self._run_copyedit_post_pass()

        if success_count == total:
            self._run_phase25_bible_update()

        run_summary = self._log_run_cost_summary(run_entries, batch_mode=False)
        run_summary["full_prequel_cache_gate"] = dict(self._full_prequel_gate_decision)
        if copyedit_summary:
            run_summary["copyedit_post_pass"] = copyedit_summary
            self.translation_log["last_copyedit_post_pass"] = copyedit_summary
        self.translation_log["last_run_summary"] = run_summary
        self._persist_full_prequel_gate_state()
        self.translation_log["last_run_at"] = datetime.now().isoformat()
        self._write_last_run_cost_audit(
            run_entries=run_entries,
            run_summary=run_summary,
            batch_mode=False,
        )
        self._save_log()

        self._save_manifest()

        # Clean up context cache
        if self.client.enable_caching:
            if self.volume_cache_name:
                logger.info(f"Clearing volume cache: {self.volume_cache_name}...")
                self.client.delete_cache(self.volume_cache_name)
                self.volume_cache_name = None
            logger.info("Clearing context cache...")
            self.client.clear_cache()
    
    def translate_volume_batch(self, clean_start: bool = False, chapters: List[str] = None):
        """
        Translate an entire volume using Anthropic's Batch API (50% cost reduction).

        Three-phase orchestration:
          Phase 1 — Collect prompts: call processor.extract_prompt() for each chapter.
                    Massive (chunked) chapters return None -> streamed immediately.
          Phase 2 — Submit batch: call client.batch_generate() for all collected prompts.
                    Blocks (polling every 60s) until Anthropic returns all results.
          Phase 3 — Finalize: call processor.finalize_from_batch_result() per chapter,
                    register chapter completion metadata, and update manifest / translation_log.

        Only valid when provider == "anthropic". Raises ValueError otherwise.
        """
        if self.tool_mode_enabled:
            logger.warning(
                "[TOOL-MODE] Batch mode is incompatible with the current multi-turn tool "
                "integration. Falling back to streaming chapter translation."
            )
            return self.translate_volume(clean_start=clean_start, chapters=chapters)

        route = get_phase2_openrouter_route()
        if bool(route.get("enabled", False)):
            logger.warning(
                "[ROUTER] OpenRouter is selected as main proxy. "
                "Phase 2 batch mode is disabled on this route; falling back to streaming translation."
            )
            return self.translate_volume(clean_start=clean_start, chapters=chapters)

        from pipeline.translator.config import get_translator_provider
        if get_translator_provider() != "anthropic":
            raise ValueError(
                "--batch mode requires provider=anthropic. "
                "Set translator_provider: anthropic in config.yaml."
            )
        if not hasattr(self.client, "batch_generate"):
            raise ValueError("AnthropicClient.batch_generate() not found. Update anthropic_client.py.")

        logger.info(f"[BATCH] Starting batch translation for volume in {self.work_dir}")

        # Load chapters (same logic as translate_volume)
        manifest_chapters = self.manifest.get("chapters", [])
        if not manifest_chapters:
            manifest_chapters = self.manifest.get("structure", {}).get("chapters", [])
        if not manifest_chapters:
            logger.error("[BATCH] No chapters found in manifest")
            return

        target_chapters = manifest_chapters
        if chapters:
            target_chapters = [c for c in manifest_chapters if c["id"] in chapters]

        total = len(target_chapters)
        logger.info(f"[BATCH] Targeting {total} chapters")
        resolved_titles = self._resolve_prompt_titles(target_chapters)

        preflight = self._run_pre_phase2_invariant_gate(target_chapters, batch_mode=True)
        if not preflight.passed:
            logger.error("[PREFLIGHT][BATCH] Blocking Phase 2 startup due to invariant failure(s).")
            return

        self._evaluate_full_prequel_cache_gate(
            target_chapters=target_chapters,
            preflight=preflight,
        )
        if self._full_prequel_gate_decision.get("requested"):
            if self._full_prequel_gate_decision.get("allowed"):
                logger.info(
                    "[FULL-PREQUEL][GATE][BATCH] Enabled (%s)",
                    self._full_prequel_gate_decision.get("reason_code"),
                )
            else:
                logger.warning(
                    "[FULL-PREQUEL][GATE][BATCH] Denied (%s): %s",
                    self._full_prequel_gate_decision.get("reason_code"),
                    self._full_prequel_gate_decision.get("reason"),
                )

        # Pipeline state
        if "translator" not in self.manifest["pipeline_state"]:
            self.manifest["pipeline_state"]["translator"] = {}
        self.manifest["pipeline_state"]["translator"]["status"] = "in_progress"
        self.manifest["pipeline_state"]["translator"]["target_language"] = self.target_language
        self.manifest["pipeline_state"]["translator"]["started_at"] = datetime.now().isoformat()
        self._persist_full_prequel_gate_state()
        self._save_manifest()

        # Pre-warm inline system instruction cache
        if self.client.enable_caching:
            self._prewarm_cache()
            logger.info("[BATCH][CACHE] System instruction pre-warmed.")

        # ── Phase 1.56: Translator's Guidance Brief ────────────────────
        # Generate a single full-volume brief via Gemini Flash (reads entire JP
        # corpus in one call).  The brief replaces the sequential per-chapter
        # summary feed: every chapter in the batch receives the complete picture
        # simultaneously rather than only what came before it.
        translation_brief: Optional[str] = None
        if is_openrouter_opus_1m_confirmed():
            logger.warning(
                "[BATCH][BRIEF][GATE] Hard-disabled under OpenRouter + Opus 1M confirmation. "
                "Skipping Phase 1.56 auto-run and brief metadata artifacts."
            )
        else:
            try:
                brief_route = get_phase2_openrouter_route()
                brief_route_base = str(brief_route.get("base_url") or "https://openrouter.ai/api/v1").strip().rstrip("/")
                brief_endpoint = brief_route_base
                brief_api_key_env = str(brief_route.get("api_key_env") or "OPENROUTER_API_KEY").strip() or "OPENROUTER_API_KEY"
                brief_api_key = os.getenv(brief_api_key_env)

                if not brief_api_key:
                    raise ValueError(
                        f"Missing OpenRouter key for Phase 1.56 brief route: {brief_api_key_env}"
                    )

                brief_client = AnthropicClient(
                    api_key=brief_api_key,
                    model="anthropic/claude-sonnet-4",
                    enable_caching=True,
                    use_env_key=False,
                    api_key_env=brief_api_key_env,
                    base_url=brief_endpoint,
                )

                brief_agent = AnthropicTranslationBriefAgent(
                    anthropic_client=brief_client,
                    work_dir=self.work_dir,
                    manifest=self.manifest,
                    target_language=self.target_language,
                    model="anthropic/claude-sonnet-4",
                    book_type=self.manifest.get("metadata", {}).get("book_type"),
                )
                brief_result = brief_agent.generate_brief()
                if brief_result.success:
                    translation_brief = brief_result.brief_text
                    status = "cached" if brief_result.cached else "generated"
                    logger.info(
                        f"[BATCH][BRIEF] Translator's Guidance brief {status} "
                        f"({len(translation_brief):,} chars) — injecting into all {total} chapter prompts."
                    )
                else:
                    logger.warning(
                        f"[BATCH][BRIEF] Brief generation failed: {brief_result.error}. "
                        "Continuing without volume brief."
                    )
            except Exception as _brief_exc:
                logger.warning(
                    f"[BATCH][BRIEF] Unexpected error during brief generation: {_brief_exc}. "
                    "Continuing without volume brief."
                )
        # ── end Phase 1.56 ─────────────────────────────────────────────

        output_dir = self.work_dir / self.target_language.upper()
        output_dir.mkdir(exist_ok=True)

        # ── Phase 1: Collect prompts ───────────────────────────────────
        logger.info("[BATCH] Phase 1: Collecting prompts for all chapters...")
        batch_requests: List[dict] = []
        chapter_metadata: dict = {}
        run_entries: List[Dict[str, Any]] = []

        for i, chapter in enumerate(target_chapters):
            chapter_id = chapter["id"]
            jp_file = chapter.get("jp_file") or chapter.get("source_file")
            if not jp_file:
                logger.error(f"[BATCH] Chapter {chapter_id} missing source filename — skipping")
                continue

            translated_filename = (
                chapter.get(f"{self.target_language}_file")
                or chapter.get("translated_file")
                or jp_file.replace('.md', f'_{self.target_language.upper()}.md')
            )
            output_path = output_dir / translated_filename

            # Skip already-completed chapters unless forced
            if not clean_start and chapter.get("translation_status") == "completed" and output_path.exists():
                logger.info(f"[BATCH] Skipping completed chapter {chapter_id}")
                chapter_metadata[chapter_id] = {"output_path": output_path, "chapter": chapter, "skipped": True}
                continue

            source_path = self.work_dir / "JP" / jp_file
            translated_title = resolved_titles.get(chapter_id)
            jp_chapter_title = chapter.get("title") or chapter.get("title_jp")
            chapter_model = chapter.get("model")
            scene_plan = self._load_scene_plan_context(chapter)
            is_afterword = is_afterword_chapter(chapter, source_path=source_path)
            inline_afterword_marker: Optional[Dict[str, Any]] = None
            chapter_translation_brief = translation_brief
            self.processor._afterword_mode_override = False
            self.prompt_loader.set_inline_afterword_override(None)
            if is_afterword:
                scene_plan = None
                self.prompt_loader.set_voice_directive("", "")
                chapter_translation_brief = self._build_afterword_tone_directive()
                self.processor._afterword_mode_override = True
                logger.info(
                    "[AFTERWORD][BATCH] %s detected: bypassing EPS/fingerprint/scene-plan constraints.",
                    chapter_id,
                )
            else:
                inline_afterword_marker = self._detect_inline_afterword_segment(scene_plan)
                if inline_afterword_marker:
                    self.processor._afterword_mode_override = True
                    self.prompt_loader.set_inline_afterword_override(inline_afterword_marker)
                    inline_brief = self._build_inline_afterword_tone_directive(inline_afterword_marker)
                    chapter_translation_brief = (
                        f"{chapter_translation_brief}\n{inline_brief}"
                        if chapter_translation_brief
                        else inline_brief
                    )
                    logger.info(
                        "[INLINE AFTERWORD][BATCH] %s detected (%s): enabling segment override + EPS/KF bypass",
                        chapter_id,
                        inline_afterword_marker.get("source", "scene_plan"),
                    )

            # ── Koji Fox Voice Directive Injection (Batch Mode) ─────────────────
            if not is_afterword:
                try:
                    jp_text = source_path.read_text(encoding="utf-8") if source_path.exists() else ""
                    chapter_chars = self._voice_rag.extract_characters_from_jp(jp_text)
                    chapter_eps = self._arc_tracker.get_eps_for_chapter(chapter_id)
                    voice_dir = self._voice_rag.get_voice_directive(chapter_chars, chapter_eps)
                    arc_dir = self._arc_tracker.get_arc_directive(chapter_chars, chapter_id)
                    if voice_dir or arc_dir:
                        self.prompt_loader.set_voice_directive(voice_dir, arc_dir)
                    # Populate ChapterProcessor fields for scene-anchor injection
                    all_fingerprints = self._voice_rag.all_fingerprints()
                    self.processor._voice_fingerprints = all_fingerprints
                    self.processor._eps_data = chapter_eps

                    self._apply_scene_plan_voice_overrides(
                        scene_plan,
                        all_fingerprints,
                        log_prefix="BATCH",
                    )

                except Exception as e:
                    logger.warning(f"[KOJI FOX] Batch mode injection error: {e}")
            else:
                self.processor._voice_fingerprints = []
                self.processor._eps_data = {}
                self._apply_scene_plan_voice_overrides(None, [], log_prefix="BATCH")
            # ── End Koji Fox ─────────────────────────────────────────────────

            prompt_dict = self.processor.extract_prompt(
                source_path=source_path,
                chapter_id=chapter_id,
                en_title=translated_title,
                jp_title=jp_chapter_title,
                cached_content=None,
                scene_plan=scene_plan,
                model_name=chapter_model,
                translation_brief=chapter_translation_brief,
            )

            if prompt_dict is None:
                # Massive chapter — stream immediately as Phase 1 fallback
                logger.info(f"[BATCH] {chapter_id} is massive — streaming now (Phase 1 fallback)...")
                result = self.processor.translate_chapter(
                    source_path, output_path, chapter_id,
                    en_title=translated_title,
                    jp_title=jp_chapter_title,
                    model_name=chapter_model,
                    cached_content=None,
                    scene_plan=scene_plan,
                    translation_brief=chapter_translation_brief,
                )
                chapter_metadata[chapter_id] = {
                    "output_path": output_path,
                    "chapter": chapter,
                    "result": result,
                    "skipped": False,
                    "streamed": True,
                }
                self._apply_adn_review_flags_to_chapter(chapter, result)
                self._maybe_trigger_full_prequel_runtime_fallback(
                    chapter_id=chapter_id,
                    result=result,
                )
                if result.success:
                    chapter["translation_status"] = "completed"
                    chapter[f"{self.target_language}_file"] = output_path.name
                    logger.info(f"[BATCH] Streamed {chapter_id} successfully.")
                else:
                    chapter["translation_status"] = "failed"
                    logger.error(f"[BATCH] Streaming fallback failed for {chapter_id}: {result.error}")

                log_entry = self._build_log_entry(
                    chapter_id=chapter_id,
                    result=result,
                    batch_mode=False,  # streamed fallback uses standard per-request pricing
                )
                run_entries.append(log_entry)
                self.translation_log["chapters"] = [
                    c for c in self.translation_log["chapters"] if c["chapter_id"] != chapter_id
                ]
                self.translation_log["chapters"].append(log_entry)
                self._save_log()
                self._save_manifest()
                continue

            batch_requests.append({
                "custom_id":          chapter_id,
                "prompt":             prompt_dict["prompt"],
                "system_instruction": prompt_dict["system_instruction"],
                "cached_content":     prompt_dict["effective_cache"],
                "model_name":         prompt_dict.get("model_name"),
                "max_output_tokens":  prompt_dict.get("max_output_tokens", 65536),
                "temperature":        prompt_dict.get("temperature", 0.7),
            })
            chapter_metadata[chapter_id] = {
                "output_path": output_path,
                "chapter":     chapter,
                "prompt_dict": prompt_dict,
                "en_title":    translated_title,
                "skipped":     False,
                "streamed":    False,
            }

        streamed_count = sum(1 for m in chapter_metadata.values() if m.get("streamed"))
        logger.info(
            f"[BATCH] Phase 1 complete: {len(batch_requests)} queued, "
            f"{streamed_count} streamed immediately."
        )

        # ── Phase 2: Submit batch ──────────────────────────────────────
        batch_results: dict = {}
        if batch_requests:
            logger.info(f"[BATCH] Phase 2: Submitting {len(batch_requests)} requests...")
            batch_state_path = self.work_dir / ".batch_state.json"
            logger.debug(f"[BATCH] batch_state_path: {batch_state_path} (exists={batch_state_path.exists()})")
            # Force fresh batch by removing stale state
            if batch_state_path.exists() and batch_requests:
                try:
                    batch_state_path.unlink()
                    logger.info(f"[BATCH] Cleared stale batch state file: {batch_state_path}")
                except Exception as e:
                    logger.warning(f"[BATCH] Could not clear batch state file: {e}")
            batch_results = self.client.batch_generate(
                requests=batch_requests,
                poll_interval_seconds=60,
                batch_state_path=batch_state_path,
            )
            # Normalize result keys to canonical chapter IDs to avoid lookup misses
            # caused by provider-side ID formatting differences.
            if batch_results:
                import re as _re

                expected_ids = {str(req.get("custom_id", "")).strip() for req in batch_requests}
                normalized: dict = {}
                for raw_id, resp in batch_results.items():
                    key = str(raw_id).strip()
                    if not key:
                        continue
                    if key in expected_ids:
                        normalized.setdefault(key, resp)
                        continue

                    candidate = None
                    m = _re.search(r"chapter[_\-\s]?(\d+)", key, flags=_re.IGNORECASE)
                    if m:
                        n = int(m.group(1))
                        for form in (f"chapter_{n:02d}", f"chapter_{n}"):
                            if form in expected_ids:
                                candidate = form
                                break

                    if candidate:
                        normalized.setdefault(candidate, resp)

                if normalized:
                    batch_results = {**batch_results, **normalized}

                matched = len(set(batch_results.keys()).intersection(expected_ids))
                if matched == 0:
                    sample_expected = list(sorted(expected_ids))[:5]
                    sample_received = list(batch_results.keys())[:5]
                    logger.error(
                        "[BATCH] Result ID mismatch: no returned keys match queued chapter IDs. "
                        f"expected_sample={sample_expected} received_sample={sample_received}"
                    )
                    if batch_state_path.exists():
                        try:
                            batch_state_path.unlink()
                        except Exception:
                            pass
                    raise RuntimeError("Batch result ID mismatch; aborted finalize to avoid writing wrong chapters.")
            logger.info(f"[BATCH] Phase 2 complete: {len(batch_results)} results received.")

        # ── Phase 3: Finalize ──────────────────────────────────────────
        logger.info("[BATCH] Phase 3: Finalizing chapters...")
        success_count = sum(
            1 for m in chapter_metadata.values()
            if m.get("skipped") or (m.get("streamed") and m.get("result") and m["result"].success)
        )

        for i, chapter in enumerate(target_chapters):
            chapter_id = chapter["id"]
            meta = chapter_metadata.get(chapter_id)
            if meta is None or meta.get("skipped") or meta.get("streamed"):
                continue

            output_path = meta["output_path"]
            prompt_dict = meta["prompt_dict"]
            en_title    = meta.get("en_title")
            response    = batch_results.get(chapter_id)

            if response is None:
                logger.error(f"[BATCH] No result for {chapter_id}")
                chapter["translation_status"] = "failed"
                failed_result = TranslationResult(
                    success=False,
                    output_path=output_path,
                    model=meta.get("prompt_dict", {}).get("model_name") or self._active_model_name,
                    batch_mode=True,
                    error="Batch result missing for chapter",
                )
                log_entry = self._build_log_entry(
                    chapter_id=chapter_id,
                    result=failed_result,
                    batch_mode=True,
                )
                run_entries.append(log_entry)
                self.translation_log["chapters"] = [
                    c for c in self.translation_log["chapters"] if c["chapter_id"] != chapter_id
                ]
                self.translation_log["chapters"].append(log_entry)
                self._save_log()
                self._save_manifest()
                continue

            result = self.processor.finalize_from_batch_result(
                response=response,
                metadata=prompt_dict["metadata"],
                chapter_id=chapter_id,
                output_path=output_path,
                en_title=en_title,
            )

            self._apply_adn_review_flags_to_chapter(chapter, result)
            self._maybe_trigger_full_prequel_runtime_fallback(
                chapter_id=chapter_id,
                result=result,
            )

            log_entry = self._build_log_entry(
                chapter_id=chapter_id,
                result=result,
                batch_mode=True,
            )
            run_entries.append(log_entry)
            self.translation_log["chapters"] = [
                c for c in self.translation_log["chapters"] if c["chapter_id"] != chapter_id
            ]
            self.translation_log["chapters"].append(log_entry)
            self._save_log()

            if result.success:
                chapter["translation_status"] = "completed"
                chapter[f"{self.target_language}_file"] = output_path.name
                success_count += 1

                chapter_num = self._resolve_chapter_number(
                    chapter_id=chapter_id,
                    source_filename=chapter.get("jp_file") or chapter.get("source_file"),
                    fallback=i + 1,
                )

                # === ARC-CLOSING EXTRACTION (batch path) ===
                _arc_closings_b = []
                _prose_anchor_cfg_b = get_translation_config().get("context", {}).get("prose_anchor", {})
                if _prose_anchor_cfg_b.get("enabled", False) and output_path.exists():
                    try:
                        _aggregator_b = VolumeContextAggregator(self.work_dir)
                        _arc_closings_b = _aggregator_b.extract_arc_closings(
                            en_chapter_path=output_path,
                            chapter_num=chapter_num or (i + 1),
                            lines_per_closing=_prose_anchor_cfg_b.get("lines_per_closing", 20),
                        )
                    except Exception as _ae:
                        logger.warning(f"[ARC-CLOSE] Batch extraction failed for {chapter_id}: {_ae}")
                # === END ARC-CLOSING EXTRACTION ===
                context_title = (
                    en_title
                    or chapter.get(f"title_{self.target_language}")
                    or chapter.get("title_en")
                    or chapter.get("title")
                    or self._canonical_title_from_chapter_id(chapter_id)
                    or chapter_id
                )

                self.context_manager.register_chapter_complete(
                    chapter_id=chapter_id,
                    chapter_num=chapter_num,
                    chapter_title=context_title,
                    arc_closings=_arc_closings_b,
                )
            else:
                chapter["translation_status"] = "failed"
                logger.error(f"[BATCH] Failed {chapter_id}: {result.error}")

            self._save_manifest()

        # Final status
        if success_count == total:
            self.manifest["pipeline_state"]["translator"]["status"] = "completed"
            logger.info(f"[BATCH] Volume translation COMPLETED ({success_count}/{total})")
        else:
            self.manifest["pipeline_state"]["translator"]["status"] = "partial"
            logger.warning(f"[BATCH] Volume translation PARTIAL ({success_count}/{total})")

        copyedit_summary = None
        if success_count > 0:
            copyedit_summary = self._run_copyedit_post_pass()

        if success_count == total:
            self._run_phase25_bible_update()

        run_summary = self._log_run_cost_summary(run_entries, batch_mode=True)
        run_summary["full_prequel_cache_gate"] = dict(self._full_prequel_gate_decision)
        if copyedit_summary:
            run_summary["copyedit_post_pass"] = copyedit_summary
            self.translation_log["last_copyedit_post_pass"] = copyedit_summary
        self.translation_log["last_run_summary"] = run_summary
        self._persist_full_prequel_gate_state()
        self.translation_log["last_run_at"] = datetime.now().isoformat()
        self._write_last_run_cost_audit(
            run_entries=run_entries,
            run_summary=run_summary,
            batch_mode=True,
        )
        self._save_log()

        self._save_manifest()

        if self.client.enable_caching:
            self.client.clear_cache()

    def _run_phase25_bible_update(self) -> None:
        """Optional Phase 2.5 post-translation bible update."""
        if not self._phase25_run_enabled:
            return
        if not self.bible_update_agent:
            logger.warning("[PHASE 2.5] Skipped: update agent not initialized")
            return
        logger.info("[PHASE 2.5] Running post-translation bible update...")
        result = self.bible_update_agent.run(
            en_dir=self.work_dir / self.target_language.upper(),
            manifest=self.manifest,
            qc_cleared=self._phase25_qc_cleared,
            target_language=self.target_language.lower(),
        )
        if result.success:
            logger.info(f"[PHASE 2.5] Bible update complete: {result.summary()}")
        else:
            logger.warning(f"[PHASE 2.5] Bible update skipped/failed: {result.summary()}")

    def _run_copyedit_post_pass(self) -> Optional[Dict[str, Any]]:
        """Run deterministic formatting/grammar cleanup on translated chapter output."""
        logger.info("[COPYEDIT] Running deterministic Phase 2 post-pass...")
        try:
            report = CopyeditPostPass(
                work_dir=self.work_dir,
                target_language=self.target_language,
            ).run()
            report_dict = report.to_dict()
            translator_state = self.manifest.setdefault("pipeline_state", {}).setdefault("translator", {})
            translator_state["copyedit_post_pass"] = report_dict
            logger.info(
                "[COPYEDIT] files=%s modified=%s typography=%s whitespace=%s paragraph=%s headers=%s grammar=%s",
                report.files_processed,
                report.files_modified,
                report.typography_fixes,
                report.whitespace_fixes,
                report.paragraph_spacing_fixes,
                report.header_deduplications,
                report.grammar_auto_fixed,
            )
            return report_dict
        except Exception as exc:
            logger.warning("[COPYEDIT] Post-pass failed non-fatally: %s", exc)
            return None

    def generate_report(self) -> TranslationReport:
        """Generate a summary report of the translation."""
        log_chapters = self.translation_log.get("chapters", [])
        totals = self._compute_totals_from_entries(log_chapters, include_label=False)

        quality_scores = []
        for c in log_chapters:
            if c.get("quality") and c["quality"].get("overall_score"):
                quality_scores.append(c["quality"]["overall_score"])

        avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0

        completed = sum(1 for c in log_chapters if c.get("success"))
        failed = sum(1 for c in log_chapters if not c.get("success"))
        errors = [c.get("error") for c in log_chapters if c.get("error")]

        status = self.manifest.get("pipeline_state", {}).get("translator", {}).get("status", "unknown")

        return TranslationReport(
            volume_id=self.manifest.get("volume_id", "unknown"),
            chapters_total=len(log_chapters),
            chapters_completed=completed,
            chapters_failed=failed,
            total_input_tokens=totals["total_input_tokens"],
            total_output_tokens=totals["total_output_tokens"],
            average_quality_score=avg_quality,
            status=status,
            started_at=self.manifest.get("pipeline_state", {}).get("translator", {}).get("started_at", ""),
            completed_at=datetime.now().isoformat(),
            total_cache_read_tokens=totals["total_cache_read_tokens"],
            total_cache_creation_tokens=totals["total_cache_creation_tokens"],
            total_input_cost_usd=totals["total_input_cost_usd"],
            total_output_cost_usd=totals["total_output_cost_usd"],
            total_cache_read_cost_usd=totals["total_cache_read_cost_usd"],
            total_cache_creation_cost_usd=totals["total_cache_creation_cost_usd"],
            total_cost_usd=totals["total_cost_usd"],
            errors=errors
        )


def run_translator(
    volume_id: str,
    chapters: Optional[List[str]] = None,
    force: bool = False,
    work_base: Optional[Path] = None,
    enable_continuity: bool = False,
    enable_multimodal: bool = False,
    batch_mode: bool = False,
    fallback_model_override: Optional[str] = None,
    tool_mode: bool = False,
) -> TranslationReport:
    """
    Main entry point for Translator agent.

    Args:
        volume_id: Volume identifier (directory name in WORK/).
        chapters: Specific chapter IDs to translate (None = all).
        force: Force re-translation of completed chapters.
        work_base: Base working directory (defaults to WORK/).
        enable_continuity: Enable schema extraction and continuity features (ALPHA - unstable).
        enable_multimodal: Enable multimodal visual context injection.
        batch_mode: Submit all chapters as one Anthropic batch (50% cost, ~1h latency).
                    Requires provider=anthropic in config.yaml.
        fallback_model_override: Optional retry fallback model override for failed chapters.
        tool_mode: Enable Anthropic translator tool mode for streaming chapter translation.

    Returns:
        TranslationReport with results.
    """
    from pipeline.config import WORK_DIR

    work_base = work_base or WORK_DIR
    volume_dir = work_base / volume_id

    if not volume_dir.exists():
        raise FileNotFoundError(f"Volume directory not found: {volume_dir}")

    agent = TranslatorAgent(
        volume_dir,
        enable_continuity=enable_continuity,
        enable_multimodal=enable_multimodal,
        fallback_model_override=fallback_model_override,
        tool_mode=tool_mode,
    )
    if batch_mode:
        agent.translate_volume_batch(clean_start=force, chapters=chapters)
    else:
        agent.translate_volume(clean_start=force, chapters=chapters)
    return agent.generate_report()


def main():
    parser = argparse.ArgumentParser(description="Run Translator Agent")
    parser.add_argument("--volume", type=str, required=True, help="Volume ID (directory name in WORK)")
    parser.add_argument("--chapters", nargs="+", help="Specific chapter IDs to translate")
    parser.add_argument("--force", action="store_true", help="Force re-translation of completed chapters")
    parser.add_argument("--enable-continuity", action="store_true", 
                       help="[ALPHA] Enable schema extraction and continuity (experimental, unstable)")
    parser.add_argument("--enable-gap-analysis", action="store_true",
                       help="Enable semantic gap analysis (Week 2-3 integration) for improved translation quality")
    parser.add_argument("--enable-multimodal", action="store_true",
                       help="Enable multimodal visual context injection (requires Phase 1.6)")
    parser.add_argument("--batch", action="store_true",
                       help="Submit all chapters as one Anthropic batch (50%% cost, ~1h latency). "
                            "Requires provider=anthropic in config.yaml.")
    parser.add_argument(
        "--tool-mode",
        action="store_true",
        help="Enable Anthropic pre-commit translation tool mode (streaming only; disables batch mode).",
    )
    parser.add_argument("--use-env-key", action="store_true",
                       help="Bypass proxy settings and use default .env keys")
    parser.add_argument(
        "--fallback-model-override",
        type=str,
        default="",
        help="Optional retry fallback model override for failed chapters (provider-specific).",
    )

    args = parser.parse_args()
    
    # Locate work dir
    # Assuming run from pipeline root
    config = get_translation_config()
    # Or get global directories config... relying on config.py having implicit access
    # But usually we need the root path.
    # Hardcoding path relative to CWD for this CLI:
    root_work = Path("WORK") 
    volume_dir = root_work / args.volume
    
    if not volume_dir.exists():
        logger.error(f"Volume directory not found: {volume_dir}")
        sys.exit(1)
        
    try:
        agent = TranslatorAgent(volume_dir, enable_continuity=args.enable_continuity,
                               enable_gap_analysis=args.enable_gap_analysis,
                               enable_multimodal=args.enable_multimodal,
                               use_env_key=args.use_env_key,
                               fallback_model_override=(args.fallback_model_override or None),
                               tool_mode=args.tool_mode)
        if args.batch and agent.tool_mode_enabled:
            logger.warning("[TOOL-MODE] Ignoring --batch because tool mode requires streaming requests.")
        if args.batch and not agent.tool_mode_enabled:
            agent.translate_volume_batch(clean_start=args.force, chapters=args.chapters)
        else:
            agent.translate_volume(clean_start=args.force, chapters=args.chapters)
    except Exception as e:
        logger.exception("Translator Agent crashed")
        sys.exit(1)

if __name__ == "__main__":
    main()

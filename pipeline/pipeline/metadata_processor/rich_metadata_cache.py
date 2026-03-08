"""
Rich Metadata Cache Updater (Phase 1.55)
========================================

Runs after Phase 1.5 metadata processing and before Phase 1.6 multimodal.

Workflow:
1. Resolve/load bible continuity for the target volume.
2. Build one full-volume JP cache (all chapter source markdown).
3. Resolve motif source context using afterword-first strategy:
    - mode=afterword_first when afterword chapters exist
    - mode=full_volume_fallback when afterword chapters are unavailable
4. Emit Phase 1.55 runtime motif-source trace line for QC:
    [P1.55][MOTIF] volume=<id> mode=<afterword_first|full_volume_fallback> afterword_chapters=<n>
5. Call Gemini (model configured via translation.phase_models.1_55) with cached volume context.
6. Merge sanitized patch into manifest metadata_<lang> (placeholder-safe, protected-field aware),
    then enforce official localization overrides when verifiable LN-priority evidence is present.
7. Run context offload co-processors and write language-scoped .context caches:
   - character_registry_<lang>.json
   - cultural_glossary_<lang>.json
   - timeline_map_<lang>.json
   - idiom_transcreation_cache_<lang>.json (with Google Search grounding)
    - dialect_fingerprint_<lang>.json (setting-aware; disabled for non-contemporary contexts)
8. Support cache-only/fallback modes with pipeline_state traceability.
9. Push enriched profile data back to the series bible when available.
"""

import argparse
import datetime
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from google.genai import types
except Exception:
    types = None
from pipeline.common.phase_llm_router import PhaseLLMRouter
from pipeline.common.name_order_normalizer import normalize_payload_names
from pipeline.config import PIPELINE_ROOT, WORK_DIR, get_target_language, get_phase_model, get_phase_generation_config

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s - %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("RichMetadataCache")


class RichMetadataCacheUpdater:
    """Cache full LN JP context and enrich rich metadata fields."""

    # Fallback model — real value resolved from translation.phase_models.1_55 in config.yaml
    MODEL_NAME = "gemini-2.5-flash"
    TEMPERATURE = 0.5
    CACHE_TTL_SECONDS = 7200
    PROCESSOR_MAX_OUTPUT_TOKENS = 24576
    CONTEXT_DIR = ".context"
    CONTEXT_PROCESSOR_FILES = {
        "character_context": "character_registry.json",
        "cultural_context": "cultural_glossary.json",
        "temporal_context": "timeline_map.json",
        "idiom_transcreation": "idiom_transcreation_cache.json",
        "dialect_fingerprint": "dialect_fingerprint.json",
        "pronoun_shift_events": "pronoun_shift_events.json",
    }
    CULTURAL_TERM_DEFAULTS: Dict[str, str] = {
        "球技大会": "ball game tournament",
        "内申": "internal school record",
        "特別推薦": "special recommendation admission",
        "里親": "foster parent",
        "軟禁": "house confinement",
        "万歳三唱": "three cheers",
        "おにいちゃん": "big brother",
        "お姉さん": "big sister",
        "幼女": "little girl",
        "大和撫子": "Yamato Nadeshiko",
        "コミカライズ": "manga adaptation",
    }
    LOCATION_TERM_DEFAULTS: Dict[str, str] = {
        "教室": "classroom",
        "屋上": "rooftop",
        "体育館": "gymnasium",
        "保健室": "nurse's office",
        "職員室": "faculty room",
        "図書室": "library room",
        "校庭": "schoolyard",
        "部室": "club room",
        "廊下": "hallway",
        "昇降口": "shoe-locker entrance",
    }
    IDIOM_LIBRARY: Dict[str, Dict[str, str]] = {
        "雨降って地固まる": {
            "literal": "after the rain, the ground hardens",
            "meaning": "adversity can strengthen relationships",
            "category": "proverb",
        },
        "猫を被る": {
            "literal": "to wear a cat",
            "meaning": "to hide one's true nature and act innocent",
            "category": "set_phrase",
        },
        "二兎を追う者は一兎をも得ず": {
            "literal": "chase two rabbits and catch neither",
            "meaning": "trying to do too much leads to failure",
            "category": "proverb",
        },
        "百聞は一見に如かず": {
            "literal": "hearing a hundred times is not equal to seeing once",
            "meaning": "seeing is believing",
            "category": "proverb",
        },
        "一期一会": {
            "literal": "one time, one meeting",
            "meaning": "treasure each encounter as unique",
            "category": "set_phrase",
        },
        "七転八起": {
            "literal": "fall seven times, rise eight",
            "meaning": "keep getting back up",
            "category": "set_phrase",
        },
        "以心伝心": {
            "literal": "heart-to-heart transmission",
            "meaning": "understanding without words",
            "category": "set_phrase",
        },
    }
    BODY_IDIOM_LIBRARY: Dict[str, Dict[str, str]] = {
        "鼻が高い": {
            "literal": "my nose is high",
            "meaning": "to feel proud",
            "category": "body_part_idiom",
        },
        "頭が上がらない": {
            "literal": "can't raise my head",
            "meaning": "I am indebted and cannot oppose them",
            "category": "body_part_idiom",
        },
        "耳が痛い": {
            "literal": "my ears hurt",
            "meaning": "a criticism hits too close to home",
            "category": "body_part_idiom",
        },
        "目を丸くする": {
            "literal": "eyes become round",
            "meaning": "to stare in surprise",
            "category": "body_part_idiom",
        },
        "心が痛む": {
            "literal": "my heart hurts",
            "meaning": "to feel emotional pain",
            "category": "metaphorical_imagery",
        },
    }
    ONOMATOPOEIA_EQUIVALENTS: Dict[str, Dict[str, str]] = {
        "ドキドキ": {
            "literal": "doki-doki",
            "meaning": "heart pounding with nerves or excitement",
            "default_en": "my heart pounded",
        },
        "ワクワク": {
            "literal": "waku-waku",
            "meaning": "excited anticipation",
            "default_en": "I was buzzing with excitement",
        },
        "ニヤニヤ": {
            "literal": "niya-niya",
            "meaning": "grinning to oneself",
            "default_en": "he wore a smug grin",
        },
        "イライラ": {
            "literal": "ira-ira",
            "meaning": "irritated and restless",
            "default_en": "my irritation kept building",
        },
        "バタバタ": {
            "literal": "bata-bata",
            "meaning": "hurried commotion",
            "default_en": "everyone rushed around in a flurry",
        },
        "ガタガタ": {
            "literal": "gata-gata",
            "meaning": "rattling or trembling",
            "default_en": "it rattled violently",
        },
        "ゴロゴロ": {
            "literal": "goro-goro",
            "meaning": "rumbling / lazing around",
            "default_en": "thunder rolled in the distance",
        },
    }

    # Keep translation outputs untouched in this phase.
    PROTECTED_FIELDS = {
        # EN book metadata (Phase 1.5 translated)
        "title_en",
        "author_en",
        "illustrator_en",
        "publisher_en",
        "series_en",
        # VN book metadata (Phase 1.5 translated) - added Rev.5 to prevent overwriting
        "title_vi",
        "author_vi",
        "illustrator_vi",
        "publisher_vi",
        "series_vi",
        # Shared fields
        "character_names",
        "chapters",
        "target_language",
        "language_code",
        "glossary",
        "translation_timestamp",
    }
    # Restrict patch structure to v4.0 fields (bible + rich metadata).
    ALLOWED_PATCH_FIELDS = {
        "character_profiles",
        "relationship_progress",
        "localization_notes",
        "world_setting",
        "geography",
        "weapons_artifacts",
        "organizations",
        "cultural_terms",
        "mythology",
        "translation_rules",
        "dialogue_patterns",
        "scene_contexts",
        "emotional_pronoun_shifts",
        "translation_guidelines",
        "schema_version",
        "official_localization",
        "cross_chapter_rules",
    }
    OFFICIAL_LOCALIZATION_EN_FIELD_MAP = {
        "volume_title_en": "title_en",
        "series_title_en": "series_en",
        "author_en": "author_en",
        "publisher_en": "publisher_en",
    }
    LN_MEDIA_HINTS = (
        "light novel",
        "ln",
        "bunko",
        "novel",
        "ranobe",
    )
    MANGA_MEDIA_HINTS = (
        "manga",
        "comic",
        "comics",
        "tankobon",
        "tankōbon",
    )
    ANIME_MEDIA_HINTS = (
        "anime",
        "tv series",
        "animation",
        "ova",
        "movie",
        "film",
    )

    PLACEHOLDER_TOKENS = (
        "[to be filled",
        "[to be determined",
        "[identify",
        "[fill",
        "tbd",
    )
    SEMANTIC_RUBY_READING_BLOCKLIST = {
        "ともだち",
        "トモダチ",
        "クラスメイト",
        "くらすめいと",
        "あなた",
        "きみ",
        "おまえ",
        "かれ",
        "かのじょ",
    }
    JP_PRONOUN_FAMILY_TOKENS: Dict[str, Tuple[str, ...]] = {
        "atashi": ("あたし", "アタシ"),
        "watashi": ("わたし", "ワタシ", "私"),
        "watakushi": ("わたくし", "ワタクシ"),
        "ore": ("俺", "おれ", "オレ"),
        "boku": ("僕", "ぼく", "ボク"),
    }
    PRONOUN_SHIFT_ARCHETYPE_MAP: Dict[Tuple[str, str], str] = {
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

    def __init__(
        self,
        work_dir: Path,
        target_language: Optional[str] = None,
        cache_only: bool = False,
    ):
        self.work_dir = work_dir
        self.manifest_path = work_dir / "manifest.json"
        self.schema_spec_path = PIPELINE_ROOT / "SCHEMA_V3.9_AGENT.md"
        self.target_language = self._normalize_target_language(target_language or get_target_language())
        self.metadata_key = f"metadata_{self.target_language}"
        # Resolve model from config.yaml (translation.phase_models.1_55) with class constant as fallback
        self.MODEL_NAME = get_phase_model("1.55", self.MODEL_NAME)
        self._phase_generation = get_phase_generation_config("1.55")
        self.TEMPERATURE = float(self._phase_generation.get("temperature", self.TEMPERATURE))
        self.PROCESSOR_MAX_OUTPUT_TOKENS = int(
            self._phase_generation.get("max_output_tokens", self.PROCESSOR_MAX_OUTPUT_TOKENS)
        )
        self.client = PhaseLLMRouter().get_client(
            "1.55",
            model=self.MODEL_NAME,
            enable_caching=True,
        )
        self.manifest: Dict[str, Any] = {}
        self.cache_only = cache_only
        self._chapter_text_cache: Optional[Dict[str, List[str]]] = None
        self._idiom_fallback_cache: Optional[Dict[str, Any]] = None

    @staticmethod
    def _normalize_target_language(value: Any) -> str:
        raw = str(value or "").strip().lower()
        aliases = {
            "vi": "vn",
            "vietnamese": "vn",
            "english": "en",
        }
        raw = aliases.get(raw, raw)
        if raw not in {"en", "vn"}:
            return "en"
        return raw

    def _target_language_name(self) -> str:
        return "Vietnamese" if self.target_language == "vn" else "English"

    def _localized_field(self, base: str) -> str:
        return f"{base}_{self.target_language}"

    def _preferred_term_key(self) -> str:
        return f"preferred_{self.target_language}"

    def _location_term_key(self) -> str:
        return self.target_language

    def _lang_value(self, en: str, vn: str) -> str:
        return vn if self.target_language == "vn" else en

    def run(self) -> bool:
        if not self.manifest_path.exists():
            logger.error(f"Manifest not found: {self.manifest_path}")
            return False

        self.manifest = self._load_manifest()
        self._ensure_ruby_names()
        volume_id = self.manifest.get("volume_id", self.work_dir.name)

        logger.info("Starting Phase 1.55 rich metadata cache update")
        logger.info(f"Volume: {volume_id}")
        logger.info(f"Model: {self.MODEL_NAME} (temperature={self.TEMPERATURE})")
        logger.info(
            f"Target language: {self.target_language.upper()} ({self._target_language_name()}) "
            f"| metadata key: {self.metadata_key}"
        )
        if self.cache_only:
            logger.info("Mode: cache_only (skip metadata patch merge)")

        bible_sync = None
        pull_result = None
        try:
            from pipeline.metadata_processor.bible_sync import BibleSyncAgent

            bible_sync = BibleSyncAgent(self.work_dir, PIPELINE_ROOT)
            if bible_sync.resolve(self.manifest):
                if bible_sync.series_id and self.manifest.get("bible_id") != bible_sync.series_id:
                    self.manifest["bible_id"] = bible_sync.series_id
                    # Persist immediately so linkage survives downstream API failures.
                    self._save_manifest()
                    logger.info(f"Linked manifest to bible_id: {bible_sync.series_id}")
                pull_result = bible_sync.pull(
                    self.manifest,
                    target_language=self.target_language,
                )
                logger.info(f"Bible continuity loaded: {pull_result.summary()}")
            else:
                logger.info("No bible linked/resolved for this volume; running manifest-only enrichment")
        except Exception as e:
            logger.warning(f"Bible continuity load failed (continuing): {e}")

        full_volume_text, cache_stats = self._build_full_volume_payload()
        if not full_volume_text:
            logger.error("No JP chapter content found. Cannot build full-LN cache.")
            self._mark_pipeline_state(
                status="failed",
                error="No JP chapter content available for cache payload",
                cache_stats=cache_stats,
            )
            self._save_manifest()
            return False

        motif_source_context = self._build_afterword_motif_context(max_chars=0)
        logger.info(
            "[P1.55][MOTIF] volume=%s mode=%s afterword_chapters=%s",
            volume_id,
            motif_source_context.get("mode", "full_volume_fallback"),
            motif_source_context.get("chapter_count", 0),
        )

        system_instruction = self._build_system_instruction()
        scene_plan_index = self._load_scene_plan_index()
        context_processor_stats: Dict[str, Any] = {
            "status": "not_started",
            "processors": {},
            "output_files": [],
        }

        if self.cache_only:
            cache_name = None
            used_external_cache = False
            cache_error: Optional[str] = None
            try:
                cache_name = self.client.create_cache(
                    model=self.MODEL_NAME,
                    system_instruction=system_instruction,
                    contents=[full_volume_text],
                    ttl_seconds=self.CACHE_TTL_SECONDS,
                    display_name=f"{volume_id}_richmeta_cacheonly",
                )
                if cache_name:
                    used_external_cache = True
                    logger.info(
                        f"[CACHE] Full-LN cache created (cache-only): {cache_name} "
                        f"({cache_stats.get('cached_chapters', 0)}/{cache_stats.get('target_chapters', 0)} chapters)"
                    )
                else:
                    logger.warning("[CACHE] Full-LN cache creation failed in cache-only mode")
            except Exception as e:
                cache_error = str(e)[:500]
                logger.warning(
                    "Cache-only run could not create external cache; "
                    f"continuing in fallback mode: {cache_error}"
                )
            finally:
                if cache_name:
                    self.client.delete_cache(cache_name)

            metadata_snapshot = self._get_metadata_block()
            context_processor_stats = self._run_context_processors(
                full_volume_text=full_volume_text,
                metadata_en=metadata_snapshot,
                cache_stats=cache_stats,
                scene_plan_index=scene_plan_index,
            )

            if not used_external_cache:
                fallback_reason = (
                    cache_error
                    if cache_error
                    else "Cache-only mode could not create external full-LN cache"
                )
                logger.warning(
                    "[CACHE] Cache-only fallback: external full-LN cache unavailable. "
                    "Proceeding without cache verification."
                )
                self._mark_pipeline_state(
                    status="completed",
                    error=f"fallback_no_external_cache: {fallback_reason}",
                    cache_stats=cache_stats,
                    used_external_cache=False,
                    mode="cache_only",
                    context_processor_stats=context_processor_stats,
                )
                self._save_manifest()
                logger.info(
                    "Phase 1.55 cache-only complete in FALLBACK mode: "
                    f"external cache not verified ({cache_stats.get('cached_chapters', 0)}/"
                    f"{cache_stats.get('target_chapters', 0)} chapters payload prepared)."
                )
                return True

            self._mark_pipeline_state(
                status="completed",
                cache_stats=cache_stats,
                used_external_cache=True,
                output_tokens=0,
                patch_keys=[],
                mode="cache_only",
                context_processor_stats=context_processor_stats,
            )
            self._save_manifest()
            logger.info(
                "Phase 1.55 cache-only complete: full-LN cache path verified "
                f"({cache_stats.get('cached_chapters', 0)}/{cache_stats.get('target_chapters', 0)} chapters)."
            )
            return True

        prompt = self._build_prompt(
            metadata_en=self._get_metadata_block(),
            bible_context=(pull_result.context_block if pull_result else ""),
            cache_stats=cache_stats,
        )

        response = None
        cache_name = None
        used_external_cache = False
        try:
            cache_name = self.client.create_cache(
                model=self.MODEL_NAME,
                system_instruction=system_instruction,
                contents=[full_volume_text],
                ttl_seconds=self.CACHE_TTL_SECONDS,
                display_name=f"{volume_id}_richmeta",
            )
            if cache_name:
                used_external_cache = True
                logger.info(
                    f"[CACHE] Full-LN cache created: {cache_name} "
                    f"({cache_stats.get('cached_chapters', 0)}/{cache_stats.get('target_chapters', 0)} chapters)"
                )
                response = self.client.generate(
                    prompt=prompt,
                    temperature=self.TEMPERATURE,
                    generation_config=self._phase_generation,
                    model=self.MODEL_NAME,
                    cached_content=cache_name,
                )
            else:
                logger.warning("[CACHE] Full-LN cache creation failed; using direct prompt mode")
                response = self.client.generate(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    temperature=self.TEMPERATURE,
                    generation_config=self._phase_generation,
                    model=self.MODEL_NAME,
                )
        except Exception as e:
            logger.error(f"Gemini enrichment call failed: {e}")
            self._mark_pipeline_state(
                status="failed",
                error=str(e)[:500],
                cache_stats=cache_stats,
                used_external_cache=used_external_cache,
            )
            self._save_manifest()
            return False
        finally:
            if cache_name:
                self.client.delete_cache(cache_name)

        if not response or not response.content:
            logger.error("Gemini returned empty content for rich metadata update")
            self._mark_pipeline_state(
                status="failed",
                error="Empty Gemini response content",
                cache_stats=cache_stats,
                used_external_cache=used_external_cache,
            )
            self._save_manifest()
            return False

        try:
            payload = self._parse_json_response(response.content)
            patch_key = f"metadata_{self.target_language}_patch"
            patch = payload.get(patch_key, payload.get("metadata_en_patch", payload))
            if not isinstance(patch, dict):
                raise ValueError(f"Response did not include a valid {patch_key} object")
            patch = self._sanitize_patch(patch)
        except Exception as e:
            logger.error(f"Failed to parse rich metadata patch: {e}")
            self._save_parse_failure_payload(
                stage="rich_metadata_patch",
                content=(response.content if response else ""),
                error=e,
            )
            metadata_block = self._get_metadata_block()
            self._set_metadata_block(metadata_block)
            self._save_metadata_file(metadata_block)
            context_processor_stats = self._run_context_processors(
                full_volume_text=full_volume_text,
                metadata_en=metadata_block,
                cache_stats=cache_stats,
                scene_plan_index=scene_plan_index,
            )
            self._mark_pipeline_state(
                status="completed",
                error=(
                    f"Patch parse error (fallback metadata retained): {str(e)[:420]}"
                ),
                cache_stats=cache_stats,
                used_external_cache=used_external_cache,
                output_tokens=getattr(response, "output_tokens", 0),
                patch_keys=[],
                mode="full_fallback_no_patch",
                context_processor_stats=context_processor_stats,
            )
            self._save_manifest()
            logger.warning(
                "Phase 1.55 continued in fallback mode (metadata patch skipped, context processors still executed)."
            )
            return True

        metadata_block = self._get_metadata_block()
        filtered_patch = self._filter_patch_to_placeholders(metadata_block, patch)
        merged_metadata = self._deep_merge_dict(metadata_block, filtered_patch)
        filtered_patch = self._strip_placeholder_scaffolds(filtered_patch)
        merged_metadata = self._strip_placeholder_scaffolds(merged_metadata)
        visual_backfilled = self._backfill_visual_identity_non_color(merged_metadata)
        if visual_backfilled:
            logger.info(f"Visual identity backfilled: {visual_backfilled} profile(s)")

        # ── Title Philosophy Routing: Generate title_pipeline for all strategies ──
        # title_philosophy is set by Phase 1.15 TitlePhilosophyAnalyzer
        title_philosophy = self.manifest.get("title_philosophy", {})
        strategy = title_philosophy.get("strategy", "pipeline_generated")

        if strategy in ("toc_direct", "toc_transcreation"):
            # For toc_direct/toc_transcreation: title_en is already set (from toc.json or transcreation)
            # Only generate title_pipeline (thematic working title for internal pipeline use)
            logger.info(f"Title strategy: {strategy} - generating title_pipeline for chapters")
            merged_metadata = self._generate_title_pipeline(merged_metadata, title_philosophy)
        else:
            # pipeline_generated: title_en was generated by Phase 1.55, also generate title_pipeline
            logger.info(f"Title strategy: {strategy} - generating title_en and title_pipeline")
            merged_metadata = self._generate_title_pipeline(merged_metadata, title_philosophy)

        merged_metadata = normalize_payload_names(merged_metadata, self.manifest)
        filtered_patch = normalize_payload_names(filtered_patch, self.manifest)

        pronoun_shift_events = self._detect_pronoun_shift_events(
            merged_metadata,
            scene_plan_index,
        )
        if pronoun_shift_events:
            merged_metadata = self._apply_pronoun_shift_metadata(
                merged_metadata,
                pronoun_shift_events,
            )
            logger.info(
                "Detected pronoun-shift events: "
                f"chapters={len(pronoun_shift_events)}, "
                f"events={sum(len(v) for v in pronoun_shift_events.values())}"
            )

        official_applied_fields = self._enforce_official_english_metadata(merged_metadata)
        if official_applied_fields:
            logger.info(
                "Applied official localization EN metadata overrides: "
                + ", ".join(sorted(official_applied_fields))
            )

        self._set_metadata_block(merged_metadata)
        self._save_metadata_file(merged_metadata)

        patch_path = self.work_dir / f"rich_metadata_cache_patch_{self.target_language}.json"
        try:
            with open(patch_path, "w", encoding="utf-8") as f:
                json.dump(filtered_patch, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Could not write patch artifact: {e}")

        if bible_sync and getattr(bible_sync, "bible", None):
            try:
                event_stats = self._push_volume_event_metadata_only(bible_sync, merged_metadata)
                logger.info(
                    "Bible event sync complete: "
                    f"updated={event_stats['updated']}, skipped={event_stats['skipped']}, "
                    f"missing_in_bible={event_stats['missing_in_bible']}"
                )
            except Exception as e:
                logger.warning(f"Bible PUSH after rich update failed (non-fatal): {e}")

        context_processor_stats = self._run_context_processors(
            full_volume_text=full_volume_text,
            metadata_en=merged_metadata,
            cache_stats=cache_stats,
            scene_plan_index=scene_plan_index,
        )

        self._mark_pipeline_state(
            status="completed",
            cache_stats=cache_stats,
            used_external_cache=used_external_cache,
            output_tokens=getattr(response, "output_tokens", 0),
            patch_keys=sorted(list(filtered_patch.keys())),
            mode="full",
            context_processor_stats=context_processor_stats,
        )
        self._save_manifest()

        logger.info(
            "Phase 1.55 complete: rich metadata merged "
            f"({len(filtered_patch)} top-level keys, cache_used={used_external_cache})"
        )
        return True

    def _generate_title_pipeline(
        self,
        metadata: Dict[str, Any],
        title_philosophy: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Generate title_pipeline (thematic working title) for each chapter.

        For toc_direct strategy: title_en is already set from toc.json, generate title_pipeline
        For toc_transcreation: title_en is transcreated, generate title_pipeline
        For pipeline_generated: generate both title_en and title_pipeline

        title_pipeline is used internally by the pipeline for context/emotional framing.
        title_en is the final EPUB title.
        """
        chapters = metadata.get("chapters", {})
        if not chapters or not isinstance(chapters, dict):
            return metadata

        strategy = title_philosophy.get("strategy", "pipeline_generated")
        logger.debug(f"Generating title_pipeline for {len(chapters)} chapters (strategy: {strategy})")

        for chapter_id, chapter_data in chapters.items():
            if not isinstance(chapter_data, dict):
                continue

            # Skip if already has title_pipeline
            if chapter_data.get("title_pipeline"):
                continue

            # Use existing title_en as the base for title_pipeline
            title_en = chapter_data.get("title_en", "")

            # Generate a thematic title_pipeline based on title_en
            # This is a simple heuristic - in production could use LLM
            if title_en:
                # title_pipeline is the more elaborate thematic version
                title_pipeline = title_en
                chapter_data["title_pipeline"] = title_pipeline

                # If strategy is pipeline_generated, also set title_source
                if strategy == "pipeline_generated" and not chapter_data.get("title_source"):
                    chapter_data["title_source"] = "pipeline_generated"

            # Ensure title_source is set for toc strategies
            if strategy in ("toc_direct", "toc_transcreation") and not chapter_data.get("title_source"):
                chapter_data["title_source"] = strategy

        logger.debug(f"Generated title_pipeline for chapters")
        return metadata

    def _ensure_ruby_names(self) -> None:
        """
        Ruby name extraction is intentionally disabled in Phase 1.55.

        Canon character metadata should come from grounding/bible sync flows,
        not ruby extraction fallback.
        """
        logger.debug("Ruby extraction/recording disabled in RichMetadataCache")

    def _load_manifest(self) -> Dict[str, Any]:
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_manifest(self) -> None:
        metadata_block = self.manifest.get(self.metadata_key, {})
        if isinstance(metadata_block, dict):
            self.manifest[self.metadata_key] = self._strip_placeholder_scaffolds(metadata_block)
            if self.target_language == "en":
                self.manifest["metadata_en"] = self.manifest[self.metadata_key]
        self.manifest = normalize_payload_names(self.manifest, self.manifest)
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(self.manifest, f, indent=2, ensure_ascii=False)

    def _save_metadata_file(self, metadata: Dict[str, Any]) -> None:
        """Persist merged rich metadata to metadata_<lang>.json as translator source-of-truth."""
        metadata_path = self.work_dir / f"metadata_{self.target_language}.json"
        try:
            metadata = self._strip_placeholder_scaffolds(metadata)
            metadata = normalize_payload_names(metadata, self.manifest)
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Could not write {metadata_path.name}: {e}")

    def _get_manifest_chapters(self) -> List[Dict[str, Any]]:
        chapters = self.manifest.get("chapters", [])
        if not chapters:
            chapters = self.manifest.get("structure", {}).get("chapters", [])
        return chapters if isinstance(chapters, list) else []

    def _is_afterword_marker(self, value: Any) -> bool:
        text = str(value or "").strip().lower()
        if not text:
            return False
        compact = re.sub(r"[\s_\-:：・]+", "", text)
        return any(
            marker in compact
            for marker in (
                "afterword",
                "postscript",
                "epilogueafter",
                "あとがき",
                "後書き",
                "後書",
                "後記",
                "跋",
            )
        )

    def _build_afterword_motif_context(self, max_chars: int = 16000) -> Dict[str, Any]:
        afterword_entries: List[Dict[str, str]] = []
        afterword_blocks: List[str] = []
        chapters = self._get_manifest_chapters()

        for chapter in chapters:
            chapter_id = str(chapter.get("id") or "").strip()
            chapter_title = str(chapter.get("title") or "").strip()
            jp_file = chapter.get("jp_file") or chapter.get("source_file")
            if not jp_file:
                continue

            is_afterword = self._is_afterword_marker(chapter_id) or self._is_afterword_marker(chapter_title)
            if not is_afterword:
                continue

            source_path = self.work_dir / "JP" / str(jp_file)
            if not source_path.exists():
                continue

            try:
                jp_text = source_path.read_text(encoding="utf-8")
            except Exception:
                continue

            afterword_entries.append(
                {
                    "id": chapter_id,
                    "title": chapter_title,
                    "jp_file": str(jp_file),
                }
            )
            afterword_blocks.append(
                f"<AFTERWORD id='{chapter_id or 'unknown'}' title='{chapter_title}'>\n{jp_text}\n</AFTERWORD>"
            )

        afterword_text = "\n\n---\n\n".join(afterword_blocks)
        afterword_text = afterword_text[:max_chars] if max_chars > 0 else afterword_text

        if not afterword_entries:
            return {
                "mode": "full_volume_fallback",
                "chapter_count": 0,
                "chapter_ids": [],
                "chapter_titles": [],
                "content_chars": 0,
                "content": "",
                "reason": "no_afterword_chapters_detected",
            }

        return {
            "mode": "afterword_first",
            "chapter_count": len(afterword_entries),
            "chapter_ids": [entry["id"] for entry in afterword_entries if entry.get("id")],
            "chapter_titles": [entry["title"] for entry in afterword_entries if entry.get("title")],
            "content_chars": len(afterword_text),
            "content": afterword_text,
        }

    def _build_full_volume_payload(self) -> Tuple[str, Dict[str, Any]]:
        chapter_blocks: List[str] = []
        cached_chapter_ids: List[str] = []
        missing_chapter_ids: List[str] = []

        chapters = self._get_manifest_chapters()
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

    def _load_chapter_text_map(self) -> Dict[str, List[str]]:
        """Load JP chapter text lines keyed by normalized chapter id."""
        if self._chapter_text_cache is not None:
            return self._chapter_text_cache

        chapter_map: Dict[str, List[str]] = {}
        for chapter in self._get_manifest_chapters():
            chapter_id = self._normalize_chapter_key(chapter.get("id", ""))
            jp_file = chapter.get("jp_file") or chapter.get("source_file")
            if not chapter_id or not jp_file:
                continue
            source_path = self.work_dir / "JP" / jp_file
            if not source_path.exists():
                continue
            try:
                chapter_map[chapter_id] = source_path.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue

        self._chapter_text_cache = chapter_map
        return chapter_map

    def _infer_scene_for_line(
        self,
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
                if isinstance(start, int) and isinstance(end, int):
                    if start <= line_number <= end:
                        sid = str(scene.get("id", "")).strip()
                        if sid:
                            return sid
        if isinstance(scenes, list):
            for scene in scenes:
                if isinstance(scene, dict):
                    sid = str(scene.get("id", "")).strip()
                    if sid:
                        return sid
        return f"{chapter_key.upper()}_SC01"

    @staticmethod
    def _detect_pronoun_family_transition(
        occurrences: List[Dict[str, Any]],
        family_counts: Dict[str, int],
    ) -> Optional[Tuple[str, Dict[str, Any]]]:
        if not occurrences:
            return None
        baseline = str(occurrences[0].get("family") or "").strip()
        if not baseline:
            return None

        baseline_seen = 0
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
            return baseline, item
        return None

    def _collect_jp_pronoun_occurrences(self, chapter_lines: List[str]) -> List[Dict[str, Any]]:
        occurrences: List[Dict[str, Any]] = []
        for line_number, raw_line in enumerate(chapter_lines, start=1):
            line = str(raw_line or "")
            if not line.strip():
                continue
            for family, tokens in self.JP_PRONOUN_FAMILY_TOKENS.items():
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
        return occurrences

    def _classify_pronoun_shift(self, shift_from: str, shift_to: str) -> str:
        return self.PRONOUN_SHIFT_ARCHETYPE_MAP.get((shift_from, shift_to), "pronoun_register_shift")

    @staticmethod
    def _pronoun_shift_label(archetype: str) -> str:
        labels = {
            "armor_drop": "Armor Drop",
            "ego_collapse": "Ego Collapse / Regression",
            "aggression_spike": "Aggression Spike",
            "professional_boundary_drop": "Professional Boundary Drop",
            "tomboy_reversal": "Tomboy Reversal",
            "pronoun_register_shift": "Pronoun Register Shift",
        }
        return labels.get(archetype, "Pronoun Register Shift")

    def _build_pronoun_shift_directives(self, archetype: str) -> List[str]:
        if self.target_language == "vn":
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

    def _detect_pronoun_shift_events(
        self,
        metadata_en: Dict[str, Any],
        scene_plan_index: Dict[str, Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        chapter_map = self._load_chapter_text_map()
        events_by_chapter: Dict[str, List[Dict[str, Any]]] = {}

        for chapter_key, lines in chapter_map.items():
            if not isinstance(lines, list) or not lines:
                continue

            occurrences = self._collect_jp_pronoun_occurrences(lines)
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

            transition = self._detect_pronoun_family_transition(occurrences, family_counts)
            if not transition:
                continue

            shift_from, transition_item = transition
            shift_to = str(transition_item.get("family") or "").strip()
            if not shift_to:
                continue

            line_number = int(transition_item.get("line") or 0)
            archetype = self._classify_pronoun_shift(shift_from, shift_to)
            scene_id = self._infer_scene_for_line(chapter_key, line_number, scene_plan_index)
            confidence = 0.58 + min(
                0.34,
                (family_counts.get(shift_from, 0) + family_counts.get(shift_to, 0)) / 24.0,
            )
            if archetype != "pronoun_register_shift":
                confidence = min(0.95, confidence + 0.05)

            event = {
                "event_id": f"PRONOUN_SHIFT_EVENT_{chapter_key.upper()}_01",
                "chapter_id": chapter_key,
                "scene_id": scene_id,
                "shift_from": shift_from,
                "shift_to": shift_to,
                "shift_label": self._pronoun_shift_label(archetype),
                "shift_archetype": archetype,
                "detected_at_line": line_number,
                "evidence_excerpt": str(transition_item.get("line_excerpt") or ""),
                "confidence": round(confidence, 3),
                "active_directives": self._build_pronoun_shift_directives(archetype),
            }
            events_by_chapter.setdefault(chapter_key, []).append(event)

        return events_by_chapter

    def _apply_pronoun_shift_metadata(
        self,
        metadata_block: Dict[str, Any],
        events_by_chapter: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        if not isinstance(metadata_block, dict):
            return metadata_block

        emotional = metadata_block.get("emotional_pronoun_shifts", {})
        if not isinstance(emotional, dict):
            emotional = {}

        emotional["events_by_chapter"] = events_by_chapter
        emotional["summary"] = {
            "event_chapters": len(events_by_chapter),
            "event_count": sum(len(v) for v in events_by_chapter.values()),
        }
        metadata_block["emotional_pronoun_shifts"] = emotional

        chapters = metadata_block.get("chapters", {})
        if isinstance(chapters, dict):
            for chapter_key, events in events_by_chapter.items():
                chapter_payload = chapters.get(chapter_key)
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

        return metadata_block

    def _transcreation_priority_from_category(self, category: str) -> str:
        cat = str(category or "").lower()
        if cat in {"wordplay", "cultural_subtext"}:
            return "critical"
        if cat in {"proverb", "body_part_idiom", "set_phrase"}:
            return "high"
        if cat in {"onomatopoeia", "metaphorical_imagery"}:
            return "medium"
        return "low"

    def _confidence_for_category(self, category: str, heuristic: bool = False) -> float:
        cat = str(category or "").lower()
        base = {
            "wordplay": 0.84,
            "proverb": 0.90,
            "set_phrase": 0.82,
            "body_part_idiom": 0.88,
            "onomatopoeia": 0.92,
            "metaphorical_imagery": 0.78,
            "cultural_subtext": 0.86,
        }.get(cat, 0.70)
        if heuristic:
            base -= 0.12
        return max(0.45, min(0.98, base))

    def _build_transcreation_options(
        self,
        *,
        japanese: str,
        literal: str,
        meaning: str,
        category: str,
    ) -> List[Dict[str, Any]]:
        cat = str(category or "").lower()
        equivalent = meaning.strip() if meaning else literal.strip()
        if cat == "onomatopoeia":
            source = self.ONOMATOPOEIA_EQUIVALENTS.get(japanese, {})
            default_en = source.get("default_en", "")
            if self.target_language == "vn":
                equivalent = equivalent or literal or "âm thanh được nhấn mạnh"
            else:
                equivalent = default_en or equivalent or "the sound was emphasized"

        creative = equivalent
        if cat == "proverb":
            creative = f"{equivalent[:1].upper() + equivalent[1:]}."
        elif cat == "body_part_idiom":
            creative = self._lang_value(
                f"The feeling hit all at once: {equivalent}.",
                f"Cảm giác ập đến cùng lúc: {equivalent}.",
            )
        elif cat == "wordplay":
            creative = self._lang_value(
                f"Recast as natural English wordplay around: {equivalent}.",
                f"Viết lại thành lối chơi chữ tự nhiên bằng tiếng Việt xoay quanh: {equivalent}.",
            )
        elif cat == "onomatopoeia":
            creative = self._lang_value(
                f"A sharper beat: {equivalent}.",
                f"Nhịp câu sắc hơn: {equivalent}.",
            )

        options: List[Dict[str, Any]] = [
            {
                "rank": 1,
                "text": equivalent or literal or japanese,
                "type": "english_equivalent",
                "confidence": round(self._confidence_for_category(category), 2),
                "reasoning": self._lang_value(
                    "Best balance of natural target-language flow and original meaning.",
                    "Cân bằng tốt nhất giữa độ tự nhiên tiếng Việt và nghĩa gốc.",
                ),
                "register": "neutral",
                "preserves_imagery": cat in {"proverb", "metaphorical_imagery", "onomatopoeia"},
                "preserves_meaning": True,
                "literary_impact": "high" if cat in {"proverb", "wordplay"} else "medium",
            },
            {
                "rank": 2,
                "text": creative or equivalent or literal or japanese,
                "type": "creative_transcreation",
                "confidence": round(max(0.55, self._confidence_for_category(category) - 0.08), 2),
                "reasoning": self._lang_value(
                    "Stylized rendering for scenes requiring stronger literary punch.",
                    "Bản diễn đạt giàu sắc thái cho cảnh cần lực văn chương mạnh hơn.",
                ),
                "register": "literary",
                "preserves_imagery": True,
                "preserves_meaning": True,
                "literary_impact": "high",
            },
            {
                "rank": 3,
                "text": literal or japanese,
                "type": "literal",
                "confidence": round(max(0.40, self._confidence_for_category(category) - 0.26), 2),
                "reasoning": self._lang_value(
                    "Literal fallback; use only if context already explains intent.",
                    "Phương án dịch sát; chỉ dùng khi ngữ cảnh đã tự làm rõ dụng ý.",
                ),
                "register": "literal",
                "preserves_imagery": True,
                "preserves_meaning": cat in {"onomatopoeia", "metaphorical_imagery"},
                "literary_impact": "low",
            },
        ]
        return options

    def _build_idiom_transcreation_from_text(
        self,
        scene_plan_index: Dict[str, Dict[str, Any]],
        min_items: int = 15,
    ) -> Dict[str, Any]:
        chapter_map = self._load_chapter_text_map()
        opportunities: List[Dict[str, Any]] = []
        wordplay_entries: List[Dict[str, Any]] = []
        seen: set = set()
        seen_wordplay: set = set()

        idiom_sources: List[Tuple[str, Dict[str, str]]] = []
        idiom_sources.extend(list(self.IDIOM_LIBRARY.items()))
        idiom_sources.extend(list(self.BODY_IDIOM_LIBRARY.items()))

        for chapter_key in sorted(chapter_map.keys()):
            lines = chapter_map.get(chapter_key, [])
            for line_no, raw_line in enumerate(lines, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                location = f"{chapter_key.upper()}_LINE_{line_no}"
                scene_id = self._infer_scene_for_line(chapter_key, line_no, scene_plan_index)

                for phrase, meta in idiom_sources:
                    if phrase not in line:
                        continue
                    dedupe = (location, phrase)
                    if dedupe in seen:
                        continue
                    seen.add(dedupe)
                    category = meta.get("category", "set_phrase")
                    confidence = self._confidence_for_category(category)
                    opportunities.append(
                        {
                            "id": f"trans_{len(opportunities) + 1:03d}",
                            "location": location,
                            "japanese": phrase,
                            "literal": meta.get("literal", phrase),
                            "meaning": meta.get("meaning", ""),
                            "category": category,
                            "context": {
                                "scene": scene_id,
                                "emotional_tone": "contextual",
                                "beat_type": "event",
                            },
                            "transcreation_priority": self._transcreation_priority_from_category(category),
                            "confidence": round(confidence, 2),
                            "options": self._build_transcreation_options(
                                japanese=phrase,
                                literal=meta.get("literal", phrase),
                                meaning=meta.get("meaning", ""),
                                category=category,
                            ),
                            "stage_2_guidance": self._lang_value(
                                "Prefer rank 1 unless scene voice requires a stronger literary beat.",
                                "Ưu tiên phương án hạng 1, trừ khi giọng cảnh cần nhịp văn chương đậm hơn.",
                            ),
                        }
                    )

                for sound, meta in self.ONOMATOPOEIA_EQUIVALENTS.items():
                    if sound not in line:
                        continue
                    dedupe = (location, sound)
                    if dedupe in seen:
                        continue
                    seen.add(dedupe)
                    opportunities.append(
                        {
                            "id": f"trans_{len(opportunities) + 1:03d}",
                            "location": location,
                            "japanese": sound,
                            "literal": meta.get("literal", sound),
                            "meaning": meta.get("meaning", ""),
                            "category": "onomatopoeia",
                            "context": {
                                "scene": scene_id,
                                "emotional_tone": "expressive",
                                "beat_type": "escalation",
                            },
                            "transcreation_priority": "medium",
                            "confidence": round(self._confidence_for_category("onomatopoeia"), 2),
                            "options": self._build_transcreation_options(
                                japanese=sound,
                                literal=meta.get("literal", sound),
                                meaning=meta.get("meaning", ""),
                                category="onomatopoeia",
                            ),
                            "stage_2_guidance": self._lang_value(
                                "Use rank 1 for clean readability; rank 2 for heightened emotional prose.",
                                "Dùng hạng 1 để giữ độ mượt; chuyển sang hạng 2 nếu cần đẩy cảm xúc.",
                            ),
                        }
                    )

                for match in re.finditer(r"([一-龯ぁ-んァ-ンA-Za-z]+)だけに", line):
                    anchor = match.group(1)
                    dedupe = (location, anchor)
                    if dedupe in seen_wordplay:
                        continue
                    seen_wordplay.add(dedupe)
                    wordplay_entries.append(
                        {
                            "id": f"wordplay_{len(wordplay_entries) + 1:03d}",
                            "location": location,
                            "japanese": match.group(0),
                            "meaning": self._lang_value(
                                f"Wordplay emphasis around {anchor}.",
                                f"Nhấn chơi chữ xoay quanh {anchor}.",
                            ),
                            "transcreation_priority": "critical",
                            "confidence": 0.83,
                            "options": [
                                {
                                    "rank": 1,
                                    "text": self._lang_value(
                                        f"Target-language wordplay centered on '{anchor}'.",
                                        f"Chơi chữ tiếng Việt xoay quanh '{anchor}'.",
                                    ),
                                    "confidence": 0.83,
                                },
                                {
                                    "rank": 2,
                                    "text": self._lang_value(
                                        "Keep meaning and explain the pun through narration.",
                                        "Giữ nghĩa chính và chuyển phần chơi chữ bằng diễn giải tự sự.",
                                    ),
                                    "confidence": 0.76,
                                },
                            ],
                            "stage_2_guidance": self._lang_value(
                                "Recast into natural target-language wit; avoid literal carryover.",
                                "Viết lại theo lối dí dỏm tự nhiên bằng tiếng Việt, tránh bê nguyên câu chữ.",
                            ),
                        }
                    )

        if len(opportunities) < min_items:
            for chapter_key in sorted(chapter_map.keys()):
                lines = chapter_map.get(chapter_key, [])
                for line_no, raw_line in enumerate(lines, start=1):
                    line = raw_line.strip()
                    if not line:
                        continue
                    location = f"{chapter_key.upper()}_LINE_{line_no}"
                    scene_id = self._infer_scene_for_line(chapter_key, line_no, scene_plan_index)
                    for four in re.findall(r"[一-龯]{4}", line):
                        dedupe = (location, four)
                        if dedupe in seen:
                            continue
                        seen.add(dedupe)
                        opportunities.append(
                            {
                                "id": f"trans_{len(opportunities) + 1:03d}",
                                "location": location,
                                "japanese": four,
                                "literal": four,
                                "meaning": self._lang_value(
                                    "Potential four-character idiom; verify context before transcreation.",
                                    "Khả năng là thành ngữ bốn chữ; cần kiểm chứng ngữ cảnh trước khi chuyển ý.",
                                ),
                                "category": "set_phrase",
                                "context": {
                                    "scene": scene_id,
                                    "emotional_tone": "contextual",
                                    "beat_type": "event",
                                },
                                "transcreation_priority": "low",
                                "confidence": round(self._confidence_for_category("set_phrase", heuristic=True), 2),
                                "options": self._build_transcreation_options(
                                    japanese=four,
                                    literal=four,
                                    meaning=self._lang_value(
                                        "Potential idiomatic emphasis.",
                                        "Khả năng có sắc thái thành ngữ.",
                                    ),
                                    category="set_phrase",
                                ),
                                "stage_2_guidance": self._lang_value(
                                    "Only transcreate if surrounding context confirms idiomatic usage.",
                                    "Chỉ chuyển ý khi ngữ cảnh xung quanh xác nhận đây là cách dùng thành ngữ.",
                                ),
                            }
                        )
                        if len(opportunities) >= min_items:
                            break
                    if len(opportunities) >= min_items:
                        break
                if len(opportunities) >= min_items:
                    break

        priority_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        confidence_sum = 0.0

        # ECR Component 1.5: Prepend rank-0 preserve_jp entries for CLT terms
        # found in chapter text so they appear first in the options list.
        metadata_en = self.manifest.get("metadata_en", {}) if isinstance(self.manifest, dict) else {}
        clt = metadata_en.get("culturally_loaded_terms", {}) if isinstance(metadata_en, dict) else {}
        if isinstance(clt, dict):
            all_text = "\n".join("\n".join(lines) for lines in chapter_map.values())
            ecr_prepend: List[Dict[str, Any]] = []
            ecr_idx = 1
            for jp_term, clt_entry in clt.items():
                if not isinstance(clt_entry, dict):
                    continue
                policy = clt_entry.get("retention_policy", "")
                if policy not in ("preserve_jp", "preserve_jp_first_use"):
                    continue
                if jp_term not in all_text:
                    continue
                romaji = clt_entry.get("romaji", "")
                display = romaji if romaji else jp_term
                ecr_prepend.append({
                    "id": f"ecr_{ecr_idx:03d}",
                    "location": "ECR_GLOBAL",
                    "japanese": jp_term,
                    "literal": display,
                    "meaning": clt_entry.get("usage_context", ""),
                    "category": clt_entry.get("category", "cultural_archetype"),
                    "context": {"scene": "global", "emotional_tone": "neutral", "beat_type": "any"},
                    "transcreation_priority": "critical",
                    "confidence": 1.0,
                    "options": [
                        {
                            "rank": 0,
                            "text": display,
                            "approach": "ecr_retain_jp",
                            "notes": f"ECR: Retain '{display}'. Do not transcreate.",
                            "register": "any",
                        }
                    ],
                    "stage_2_guidance": f"ECR: Use rank 0 ({display}). Override only if localization policy changes at runtime.",
                })
                ecr_idx += 1
            if ecr_prepend:
                opportunities = ecr_prepend + opportunities

        for item in opportunities:
            priority = str(item.get("transcreation_priority", "low")).lower()
            if priority in priority_counts:
                priority_counts[priority] += 1
            confidence_sum += float(item.get("confidence", 0.0) or 0.0)

        avg_conf = confidence_sum / len(opportunities) if opportunities else 0.0
        return {
            "volume_id": self.manifest.get("volume_id", self.work_dir.name),
            "generated_at": datetime.datetime.now().isoformat(),
            "processor_version": "1.1",
            "transcreation_opportunities": opportunities[:140],
            "wordplay_transcreations": wordplay_entries[:60],
            "summary": {
                "total_opportunities": len(opportunities[:140]),
                "by_priority": priority_counts,
                "avg_confidence": round(avg_conf, 3),
            },
        }

    def _get_or_build_idiom_fallback(self, scene_plan_index: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        if self._idiom_fallback_cache is None:
            self._idiom_fallback_cache = self._build_idiom_transcreation_from_text(
                scene_plan_index=scene_plan_index,
                min_items=15,
            )
        return json.loads(json.dumps(self._idiom_fallback_cache))

    def _resolve_cultural_term_translation(self, jp_term: str, source: Any) -> Tuple[str, List[str], str]:
        preferred_key = self._preferred_term_key()
        canonical_key = f"canonical_{self.target_language}"
        meaning_key = f"meaning_{self.target_language}"
        if isinstance(source, dict):
            preferred = (
                source.get(preferred_key)
                or source.get(canonical_key)
                or source.get(meaning_key)
                # Backward compatibility for legacy EN-keyed metadata.
                or source.get("preferred_en")
                or source.get("canonical_en")
                or source.get("meaning_en")
                or source.get("translation")
                or source.get(self._location_term_key())
                or ""
            )
            aliases = source.get("aliases") or source.get("aliases_en") or []
        else:
            preferred = str(source or "")
            aliases = []

        preferred = str(preferred).strip()
        if not preferred and self.target_language == "en":
            preferred = self.CULTURAL_TERM_DEFAULTS.get(jp_term, "").strip()
        elif not preferred:
            # Avoid injecting EN defaults into non-EN metadata blocks.
            preferred = ""

        normalized_aliases: List[str] = []
        if isinstance(aliases, list):
            for alias in aliases:
                text = str(alias).strip()
                if text and text != preferred and text not in normalized_aliases:
                    normalized_aliases.append(text)

        reason = "Taken from canonical metadata."
        if jp_term in self.CULTURAL_TERM_DEFAULTS and preferred == self.CULTURAL_TERM_DEFAULTS[jp_term]:
            reason = "Fallback dictionary mapping for stable LN translation consistency."
        if not preferred:
            reason = "No stable equivalent found; requires model translation."
        return preferred, normalized_aliases, reason

    def _is_contemporary_japan_setting(self, metadata_en: Dict[str, Any]) -> bool:
        """Heuristic detector for modern/contemporary Japan setting."""
        text_chunks: List[str] = []

        metadata = self.manifest.get("metadata", {})
        if isinstance(metadata, dict):
            for key in ("title", "series", "description", "genre", "publisher"):
                value = metadata.get(key)
                if isinstance(value, str) and value.strip():
                    text_chunks.append(value.strip())

        for key in ("world_setting", "localization_notes", "translation_rules", "geography", "scene_contexts"):
            value = metadata_en.get(key)
            if value:
                text_chunks.append(json.dumps(value, ensure_ascii=False))

        haystack = " ".join(text_chunks).lower()
        if not haystack:
            return False

        positive_signals = (
            "contemporary japan",
            "modern japan",
            "present-day japan",
            "present day japan",
            "modern_japan",
            "contemporary_japan",
            "modern_japan_parallel_world",
            "japanese high school",
            "japanese university",
            "japan",
            "tokyo",
            "osaka",
            "kyoto",
            "reiwa",
            "heisei",
            "slice-of-life",
            "school life",
        )
        parallel_or_isekai_markers = (
            "isekai",
            "alternate world",
            "parallel world",
            "otherworld",
            "reincarnation",
            "transmigration",
            "tensei",
        )
        hard_fantasy_world_signals = (
            "fantasy world",
            "magic academy",
            "dungeon",
            "kingdom",
            "empire",
            "medieval",
            "feudal",
            "royal court",
            "noble academy",
            "sword and sorcery",
        )

        has_positive = any(token in haystack for token in positive_signals)
        has_parallel_or_isekai = any(token in haystack for token in parallel_or_isekai_markers)
        has_hard_fantasy_world = any(token in haystack for token in hard_fantasy_world_signals)

        # Modern-world exception (matches prompt_loader fantasy-module gate):
        # if the world is explicitly modern/contemporary Japan, keep contemporary policy
        # even when isekai/reincarnation/parallel-world framing exists.
        if has_positive and not has_hard_fantasy_world:
            return True

        # Backward-compatible strict fallback.
        has_negative = has_parallel_or_isekai or has_hard_fantasy_world
        return has_positive and not has_negative

    def _is_fantasy_or_non_contemporary_setting(self, metadata_en: Dict[str, Any]) -> bool:
        """
        Detect fantasy/non-contemporary world settings.

        Rule: if Contemporary Japan is detected, this returns False.
        """
        if self._is_contemporary_japan_setting(metadata_en):
            return False

        text_chunks: List[str] = []
        metadata = self.manifest.get("metadata", {})
        if isinstance(metadata, dict):
            for key in ("title", "series", "description", "genre", "publisher"):
                value = metadata.get(key)
                if isinstance(value, str) and value.strip():
                    text_chunks.append(value.strip())

        for key in ("world_setting", "localization_notes", "translation_rules", "geography", "scene_contexts"):
            value = metadata_en.get(key)
            if value:
                text_chunks.append(json.dumps(value, ensure_ascii=False))

        haystack = " ".join(text_chunks).lower()
        if not haystack:
            return False

        modern_japan_signals = (
            "contemporary japan",
            "modern japan",
            "present-day japan",
            "present day japan",
            "modern_japan",
            "contemporary_japan",
            "modern_japan_parallel_world",
            "japanese high school",
            "japanese university",
            "slice-of-life",
            "school life",
            "tokyo",
            "osaka",
            "kyoto",
            "reiwa",
            "heisei",
        )
        hard_fantasy_world_signals = (
            "fantasy world",
            "medieval",
            "feudal",
            "kingdom",
            "empire",
            "royal court",
            "noble academy",
            "magic academy",
            "dungeon",
            "sword and sorcery",
        )
        has_modern_japan = any(token in haystack for token in modern_japan_signals)
        has_hard_fantasy_world = any(token in haystack for token in hard_fantasy_world_signals)

        # Modern-world exception: contemporary JP remains non-fantasy policy even when
        # "isekai/parallel world/reincarnation" strings appear.
        if has_modern_japan and not has_hard_fantasy_world:
            return False

        fantasy_or_noncontemporary_signals = (
            "fantasy",
            "isekai",
            "alternate world",
            "parallel world",
            "otherworld",
            "reincarnation",
            "transmigration",
            "tensei",
            "medieval",
            "feudal",
            "historical",
            "pre-modern",
            "kingdom",
            "empire",
            "royal court",
            "magic academy",
            "sword",
            "sorcery",
            "dungeon",
            "noble academy",
            "non-contemporary",
        )
        return any(token in haystack for token in fantasy_or_noncontemporary_signals)

    def _is_noble_setting(self, metadata_en: Dict[str, Any]) -> bool:
        """Detect aristocratic/noble settings requiring title transcreation."""
        text_chunks: List[str] = []
        metadata = self.manifest.get("metadata", {})
        if isinstance(metadata, dict):
            for key in ("title", "series", "description", "genre"):
                value = metadata.get(key)
                if isinstance(value, str) and value.strip():
                    text_chunks.append(value.strip())

        for key in ("world_setting", "localization_notes", "translation_rules", "organizations", "geography", "scene_contexts"):
            value = metadata_en.get(key)
            if value:
                text_chunks.append(json.dumps(value, ensure_ascii=False))

        haystack = " ".join(text_chunks).lower()
        if not haystack:
            return False

        noble_signals = (
            "noble",
            "aristocrat",
            "aristocracy",
            "duke",
            "duchess",
            "count",
            "countess",
            "marquis",
            "marchioness",
            "earl",
            "baron",
            "viscount",
            "viscountess",
            "lord",
            "lady",
            "your grace",
            "your highness",
            "royal",
            "princess",
            "prince",
            "king",
            "queen",
            "court",
            "knight",
        )
        return any(token in haystack for token in noble_signals)

    def _is_isekai_with_jp_characters_setting(self, metadata_en: Dict[str, Any]) -> bool:
        """
        Detect isekai/reincarnation settings where the cast is Japanese-origin.
        These volumes retain JP honorifics and family-given name order even though
        the story takes place in a fantasy world (not contemporary Japan).
        Triggered by world_setting.type containing both isekai and japan signals,
        OR by world_setting.honorifics.mode == 'retain' in an isekai context.
        """
        ws = metadata_en.get("world_setting", {})
        if not isinstance(ws, dict):
            return False

        # Explicit manifest signal: retain mode inside a fantasy/isekai world_setting
        hon = ws.get("honorifics", {})
        if isinstance(hon, dict) and hon.get("mode") == "retain":
            ws_type = str(ws.get("type", "")).lower()
            ws_label = str(ws.get("label", "")).lower()
            isekai_tokens = ("isekai", "reincarnation", "transmigration", "tensei", "parallel world", "otherworld")
            if any(t in ws_type or t in ws_label for t in isekai_tokens):
                return True

        # Heuristic: world_setting.type explicitly encodes both isekai + japan markers
        ws_type = str(ws.get("type", "")).lower()
        isekai_in_type = any(t in ws_type for t in ("isekai", "reincarnation", "transmigration"))
        japan_in_type = any(t in ws_type for t in ("japan", "modern_japan", "contemporary_japan"))
        if isekai_in_type and japan_in_type:
            return True

        # Heuristic: world_setting.label references both dimensions
        ws_label = str(ws.get("label", "")).lower()
        isekai_in_label = any(t in ws_label for t in ("isekai", "reincarnation", "summoned", "transported", "otherworld"))
        japan_in_label = any(t in ws_label for t in ("japan", "japanese", "modern japan", "high school"))
        if isekai_in_label and japan_in_label:
            return True

        return False

    def _contemporary_japan_honorific_policies(self) -> List[Dict[str, Any]]:
        """Canonical honorific retention policy for modern Japan settings."""
        return [
            {
                "pattern": "-san",
                "strategy": "retain_in_english",
                "rule": "Retain as suffix in English (e.g., Saki-san); do not omit or translate.",
            },
            {
                "pattern": "-chan",
                "strategy": "retain_in_english",
                "rule": "Retain as suffix in English (e.g., Emma-chan) to preserve intimacy nuance.",
            },
            {
                "pattern": "-kun",
                "strategy": "retain_in_english",
                "rule": "Retain as suffix in English (e.g., Yuuta-kun); do not flatten to first-name only.",
            },
            {
                "pattern": "-sama",
                "strategy": "retain_in_english",
                "rule": "Retain as suffix in English for elevated politeness/register.",
            },
            {
                "pattern": "-senpai",
                "strategy": "retain_in_english",
                "rule": "Retain senpai as title/suffix in English; do not translate to 'senior'.",
            },
            {
                "pattern": "-sensei",
                "strategy": "retain_in_english",
                "rule": "Retain sensei as title/suffix in English; do not translate to 'teacher/professor'.",
            },
            {
                "pattern": "先輩",
                "strategy": "retain_in_english",
                "rule": "Render as senpai in English output.",
            },
            {
                "pattern": "先生",
                "strategy": "retain_in_english",
                "rule": "Render as sensei in English output.",
            },
        ]

    def _fantasy_noncontemporary_honorific_policies(self) -> List[Dict[str, Any]]:
        """Default policy for fantasy/non-contemporary settings."""
        return [
            {
                "pattern": "name_order",
                "strategy": "given_name_first_convert_to_english_equivalent",
                "rule": "Use given-name-first order for character naming and prefer natural English equivalents.",
            },
            {
                "pattern": "-san",
                "strategy": "transcreate_to_english_equivalent",
                "rule": "Do not retain '-san'; convert to context-appropriate English address (Mr./Ms./title).",
            },
            {
                "pattern": "-chan",
                "strategy": "transcreate_to_english_equivalent",
                "rule": "Do not retain '-chan'; express closeness with tone, nickname, or Miss/young-lady styling by context.",
            },
            {
                "pattern": "-kun",
                "strategy": "transcreate_to_english_equivalent",
                "rule": "Do not retain '-kun'; convert to natural English peer/junior address.",
            },
            {
                "pattern": "-senpai",
                "strategy": "transcreate_to_english_equivalent",
                "rule": "Do not retain '-senpai'; convert to senior role/title in English context.",
            },
            {
                "pattern": "-sensei",
                "strategy": "transcreate_to_english_equivalent",
                "rule": "Do not retain '-sensei'; convert to Master/Instructor/Teacher based on world context.",
            },
        ]

    def _noble_honorific_policies(self) -> List[Dict[str, Any]]:
        """Policy for noble/aristocratic settings: transcreate JP honorifics to noble English titles."""
        return [
            {
                "pattern": "name_order",
                "strategy": "given_name_first_convert_to_english_equivalent",
                "rule": "Use given-name-first order and naturalized English naming in noble dialogue/narration.",
            },
            {
                "pattern": "-sama/様",
                "strategy": "transcreate_to_noble_english_equivalent",
                "rule": "Transcreate to noble address (e.g., My Lord, My Lady, Your Grace/Highness by rank).",
            },
            {
                "pattern": "-san",
                "strategy": "transcreate_to_noble_english_equivalent",
                "rule": "Transcreate to Lord/Lady or formal title based on status and scene register.",
            },
            {
                "pattern": "-kun",
                "strategy": "transcreate_to_noble_english_equivalent",
                "rule": "Transcreate to Young Lord/Young Master or equivalent noble junior address.",
            },
            {
                "pattern": "-chan",
                "strategy": "transcreate_to_noble_english_equivalent",
                "rule": "Transcreate to Lady/Miss or affectionate noble equivalent (avoid JP suffix retention).",
            },
            {
                "pattern": "-senpai/先輩",
                "strategy": "transcreate_to_noble_english_equivalent",
                "rule": "Transcreate to senior rank-role (e.g., Senior Knight, elder court member) by context.",
            },
            {
                "pattern": "-sensei/先生",
                "strategy": "transcreate_to_noble_english_equivalent",
                "rule": "Transcreate to Master, Tutor, or Court Instructor based on role.",
            },
        ]

    def _isekai_japan_retention_honorific_policies(self) -> List[Dict[str, Any]]:
        """
        Honorific policy for isekai/reincarnation volumes where the protagonist
        and cast are Japanese-origin but the story takes place in a fantasy world.
        JP honorifics are retained for JP characters; fantasy NPCs do not carry
        JP suffixes. Name order: family-given for JP characters.
        """
        return [
            {
                "pattern": "name_order",
                "strategy": "family_given_for_japanese_characters",
                "rule": "Use Family-Given order for Japanese-origin characters (e.g., Fuwa Souji, Shikishima Saeko). "
                        "Given-Family only for explicitly non-Japanese characters.",
            },
            {
                "pattern": "-san",
                "strategy": "retain_for_jp_characters",
                "rule": "Retain -san for Japanese characters; fantasy NPCs use natural English address instead.",
            },
            {
                "pattern": "-chan",
                "strategy": "retain_for_jp_characters",
                "rule": "Retain -chan for JP characters to preserve intimacy; not used for fantasy-world NPCs.",
            },
            {
                "pattern": "-kun",
                "strategy": "retain_for_jp_characters",
                "rule": "Retain -kun for JP characters; not used for fantasy-world NPCs.",
            },
            {
                "pattern": "-sama",
                "strategy": "retain_for_jp_characters",
                "rule": "Retain -sama for JP characters; for fantasy royalty/nobles use natural English title.",
            },
            {
                "pattern": "-senpai",
                "strategy": "retain_for_jp_characters",
                "rule": "Retain senpai for JP school-context characters; not applied to fantasy NPCs.",
            },
            {
                "pattern": "-sensei",
                "strategy": "retain_for_jp_characters",
                "rule": "Retain sensei for JP characters; use Master/Tutor/Instructor for fantasy-world teachers.",
            },
        ]

    def _build_honorific_policies(self, metadata_en: Dict[str, Any]) -> List[Dict[str, Any]]:
        ws = metadata_en.get("world_setting", {})
        if isinstance(ws, dict):
            hon = ws.get("honorifics", {})
            if isinstance(hon, dict):
                if hon.get("mode") == "retain":
                    # Manifest explicitly signals JP retention — honour it
                    if self._is_isekai_with_jp_characters_setting(metadata_en):
                        return self._isekai_japan_retention_honorific_policies()
                    return self._contemporary_japan_honorific_policies()
                elif hon.get("mode") == "localize":
                    pass  # Proceed to default omission policies below
            # mode absent or unrecognised — fall through to heuristic detection
            if self._is_contemporary_japan_setting(metadata_en):
                return self._contemporary_japan_honorific_policies()
            if self._is_fantasy_or_non_contemporary_setting(metadata_en):
                if self._is_isekai_with_jp_characters_setting(metadata_en):
                    return self._isekai_japan_retention_honorific_policies()
                if self._is_noble_setting(metadata_en):
                    return self._noble_honorific_policies()
                return self._fantasy_noncontemporary_honorific_policies()
        else:
            if self._is_contemporary_japan_setting(metadata_en):
                return self._contemporary_japan_honorific_policies()
            elif self._is_fantasy_or_non_contemporary_setting(metadata_en):
                if self._is_isekai_with_jp_characters_setting(metadata_en):
                    return self._isekai_japan_retention_honorific_policies()
                if self._is_noble_setting(metadata_en):
                    return self._noble_honorific_policies()
                return self._fantasy_noncontemporary_honorific_policies()

        policies: List[Dict[str, Any]] = [
            {
                "pattern": "-san",
                "strategy": "omit_in_english",
                "rule": "Default omission; keep role distance via tone or title when context requires.",
            },
            {
                "pattern": "-chan",
                "strategy": "omit_with_tender_tone",
                "rule": "Reflect intimacy through diction, not suffix carryover.",
            },
            {
                "pattern": "-kun",
                "strategy": "omit_with_peer_register",
                "rule": "Use casual peer voice in English lines.",
            },
            {
                "pattern": "先輩",
                "strategy": "translate_to_senior",
                "rule": "Use 'senior' when hierarchy matters; otherwise infer via voice dynamics.",
            },
            {
                "pattern": "先生",
                "strategy": "translate_to_teacher",
                "rule": "Prefer teacher/professor by setting context.",
            },
        ]

        localization_notes = metadata_en.get("localization_notes", {})
        if isinstance(localization_notes, dict):
            british = localization_notes.get("british_speech_exception", {})
            if isinstance(british, dict):
                chars = british.get("character")
                if chars:
                    policies.append(
                        {
                            "pattern": "formal_exception",
                            "strategy": "retain_formality_for_listed_characters",
                            "rule": f"Apply formal register to: {chars}",
                        }
                    )
        return policies

    def _build_location_terms(self) -> List[Dict[str, Any]]:
        chapter_map = self._load_chapter_text_map()
        all_text = "\n".join("\n".join(lines) for lines in chapter_map.values())
        location_terms: List[Dict[str, Any]] = []
        localized_key = self._location_term_key()
        for jp, en in self.LOCATION_TERM_DEFAULTS.items():
            if jp in all_text:
                localized_value = en if self.target_language == "en" else ""
                location_terms.append(
                    {
                        "jp": jp,
                        localized_key: localized_value,
                        "notes": "Detected in volume source text.",
                    }
                )
        return location_terms

    def _enhance_character_registry_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        chars = payload.get("characters", [])
        if not isinstance(chars, list):
            return payload

        def _compact(text: Any) -> str:
            return re.sub(r"[\s　]+", "", str(text or "").strip())

        def _norm_reading(text: Any) -> str:
            return _compact(text).lower()

        def _is_semantic_reading(reading: Any) -> bool:
            norm = _norm_reading(reading)
            return norm in {item.lower() for item in self.SEMANTIC_RUBY_READING_BLOCKLIST}

        metadata_block = self.manifest.get(self.metadata_key, {})
        profiles = metadata_block.get("character_profiles", {}) if isinstance(metadata_block, dict) else {}
        legal_by_base: Dict[str, Tuple[str, str]] = {}
        if isinstance(profiles, dict):
            for _, profile in profiles.items():
                if not isinstance(profile, dict):
                    continue
                base = str(profile.get("ruby_base_full") or profile.get("ruby_base") or "").strip()
                reading = str(profile.get("ruby_reading_full") or profile.get("ruby_reading") or "").strip()
                base_compact = _compact(base)
                if base_compact and reading:
                    legal_by_base[base_compact] = (base, reading)

        ruby_lookup: Dict[str, Tuple[str, str]] = {}
        for item in self.manifest.get("ruby_names", []):
            if not isinstance(item, dict):
                continue
            base = str(item.get("kanji") or "").strip()
            reading = str(item.get("ruby") or "").strip()
            if not base or not reading:
                continue
            base_compact = _compact(base)
            if not base_compact:
                continue
            legal_pair = legal_by_base.get(base_compact)
            if legal_pair and _norm_reading(reading) != _norm_reading(legal_pair[1]):
                continue
            ruby_style = str(item.get("ruby_style") or "").strip().lower()
            name_type = str(item.get("name_type") or "").strip().lower()
            if legal_pair is None and (
                ruby_style == "kirakira"
                or name_type == "kirakira"
                or _is_semantic_reading(reading)
            ):
                continue
            current = ruby_lookup.get(base_compact)
            if current is None or len(base) > len(current[0]):
                ruby_lookup[base_compact] = (base, reading)

        for char in chars:
            if not isinstance(char, dict):
                continue
            if "full_name" not in char:
                char["full_name"] = ""
            if "ruby_base_full" not in char:
                char["ruby_base_full"] = ""
            if "ruby_reading_full" not in char:
                char["ruby_reading_full"] = ""
            if "kira_kira_name_canonical" not in char:
                char["kira_kira_name_canonical"] = ""

            japanese_name = str(char.get("japanese_name") or "").strip()
            if japanese_name:
                name_compact = _compact(japanese_name)
                full_pair = ruby_lookup.get(name_compact)
                if full_pair:
                    char["ruby_base_full"] = full_pair[0]
                    char["ruby_reading_full"] = full_pair[1]

                legal_pair = legal_by_base.get(name_compact)
                if legal_pair:
                    current_reading = str(char.get("ruby_reading_full") or "").strip()
                    if _norm_reading(current_reading) != _norm_reading(legal_pair[1]):
                        char["ruby_base_full"] = legal_pair[0]
                        char["ruby_reading_full"] = legal_pair[1]
                else:
                    if _is_semantic_reading(char.get("ruby_reading_full")):
                        char["ruby_reading_full"] = ""

            nicknames = char.get("kira_kira_name_nicknames", [])
            if isinstance(nicknames, list):
                normalized_nicknames: List[str] = []
                for item in nicknames:
                    text = str(item).strip()
                    if text and text not in normalized_nicknames:
                        normalized_nicknames.append(text)
                char["kira_kira_name_nicknames"] = normalized_nicknames
            else:
                char["kira_kira_name_nicknames"] = []

            handles = char.get("sns_handles", [])
            if isinstance(handles, list):
                normalized_handles: List[str] = []
                for item in handles:
                    text = str(item).strip()
                    if text and text not in normalized_handles:
                        normalized_handles.append(text)
                char["sns_handles"] = normalized_handles
            else:
                char["sns_handles"] = []

            pronouns = [str(p).lower() for p in char.get("pronoun_hints_en", []) if isinstance(p, str)]
            if not char.get("gender"):
                if any(p in {"she", "her", "hers"} for p in pronouns):
                    char["gender"] = "female"
                elif any(p in {"he", "him", "his"} for p in pronouns):
                    char["gender"] = "male"
                else:
                    char["gender"] = "unknown"

            if "emotional_arc" not in char:
                char["emotional_arc"] = {}

            edges = char.get("relationship_edges", [])
            if isinstance(edges, list):
                for edge in edges:
                    if not isinstance(edge, dict):
                        continue
                    type_text = str(edge.get("type", "")).lower()
                    taxonomy = "friendship"
                    if any(k in type_text for k in ("romantic", "partner", "crush", "love")):
                        taxonomy = "romantic"
                    elif any(k in type_text for k in ("sister", "brother", "father", "mother", "family", "guardian")):
                        taxonomy = "familial"
                    elif any(k in type_text for k in ("teacher", "student", "mentor", "colleague", "professional")):
                        taxonomy = "professional"
                    elif any(k in type_text for k in ("hostile", "antagon", "strained", "conflict")):
                        taxonomy = "antagonistic"
                    edge["taxonomy"] = taxonomy

        summary = payload.get("summary", {})
        if isinstance(summary, dict):
            summary["total_characters"] = len([c for c in chars if isinstance(c, dict)])
        return payload

    def _enhance_cultural_glossary_payload(
        self,
        payload: Dict[str, Any],
        metadata_en: Dict[str, Any],
        scene_plan_index: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        preferred_key = self._preferred_term_key()
        source_terms = metadata_en.get("cultural_terms", {})
        if not isinstance(source_terms, dict):
            source_terms = {}

        # ECR: Component 1.5 — culturally_loaded_terms takes precedence
        clt_terms = metadata_en.get("culturally_loaded_terms", {})
        if not isinstance(clt_terms, dict):
            clt_terms = {}

        raw_terms = payload.get("terms", [])
        if not isinstance(raw_terms, list) or not raw_terms:
            seed_terms = list(source_terms.keys())
            if not seed_terms:
                chapter_map = self._load_chapter_text_map()
                all_text = "\n".join("\n".join(lines) for lines in chapter_map.values())
                for jp_term in self.CULTURAL_TERM_DEFAULTS.keys():
                    if jp_term in all_text:
                        seed_terms.append(jp_term)
            raw_terms = [{"term_jp": key} for key in seed_terms[:80]]

        # Also seed terms from CLT that aren't in raw_terms yet
        existing_jp_set = {
            str(t.get("term_jp") or t.get("jp") or "").strip()
            for t in raw_terms if isinstance(t, dict)
        }
        for clt_jp in clt_terms:
            if clt_jp and clt_jp not in existing_jp_set:
                raw_terms.append({"term_jp": clt_jp})

        enriched_terms: List[Dict[str, Any]] = []
        consistency_rules: List[str] = []
        seen_terms: set = set()

        for term in raw_terms:
            if not isinstance(term, dict):
                continue
            term_jp = str(term.get("term_jp") or term.get("jp") or "").strip()
            if not term_jp or term_jp in seen_terms:
                continue
            seen_terms.add(term_jp)
            source = source_terms.get(term_jp, {})
            preferred, aliases, reason = self._resolve_cultural_term_translation(term_jp, source)
            notes = str(term.get("notes") or "").strip()
            if not notes and isinstance(source, dict):
                notes = str(source.get("notes") or source.get("context") or "").strip()

            # ECR: check culturally_loaded_terms for policy override
            ecr_policy = None
            ecr_verified = False
            clt_entry = clt_terms.get(term_jp)
            if isinstance(clt_entry, dict):
                ecr_policy = clt_entry.get("retention_policy", "")
                romaji = clt_entry.get("romaji", "")
                usage_context = clt_entry.get("usage_context", "")
                ecr_verified = True
                if ecr_policy == "preserve_jp":
                    # Override preferred with romaji; set consistency rule to retain JP
                    ecr_display = romaji if romaji else term_jp
                    preferred = ecr_display
                    reason = f"ECR preserve_jp: Retain '{ecr_display}' — do not genericize."
                    notes = notes or usage_context
                elif ecr_policy == "preserve_jp_first_use":
                    ecr_display = romaji if romaji else term_jp
                    preferred = ecr_display
                    reason = f"ECR preserve_jp_first_use: Use '{ecr_display}' on first occurrence with inline gloss."
                    notes = notes or usage_context
                elif ecr_policy == "transcreate" and not preferred:
                    # Allow fallback to standard translation
                    reason = f"ECR transcreate: Render in English; JP form '{term_jp}' is informational."

            entry = {
                "term_jp": term_jp,
                preferred_key: preferred,
                "alternatives": aliases[:4],
                "chosen_reason": reason,
                "consistency_rule": (
                    f"RETAIN JP — Always use '{preferred}' for {term_jp}. Do NOT substitute with English description."
                    if ecr_policy in ("preserve_jp", "preserve_jp_first_use")
                    else (f"Always translate {term_jp} as '{preferred}'." if preferred else "")
                ),
                "notes": notes,
            }
            if ecr_policy:
                entry["ecr_policy"] = ecr_policy
            if ecr_verified:
                entry["ecr_verified"] = True
            enriched_terms.append(entry)
            if entry["consistency_rule"]:
                consistency_rules.append(entry["consistency_rule"])

        payload["terms"] = enriched_terms[:120]

        idioms = payload.get("idioms")
        if not isinstance(idioms, list) or not idioms:
            idiom_seed = self._get_or_build_idiom_fallback(scene_plan_index)
            idioms = []
            for item in idiom_seed.get("transcreation_opportunities", []):
                if not isinstance(item, dict):
                    continue
                category = str(item.get("category", "")).lower()
                if category not in {"proverb", "set_phrase", "body_part_idiom"}:
                    continue
                idioms.append(
                    {
                        "japanese": item.get("japanese", ""),
                        "meaning": item.get("meaning", ""),
                        "preferred_rendering": item.get("options", [{}])[0].get("text", "") if isinstance(item.get("options"), list) else "",
                        "confidence": item.get("confidence", 0.7),
                    }
                )
                if len(idioms) >= 20:
                    break
        payload["idioms"] = idioms if isinstance(idioms, list) else []

        honorifics = payload.get("honorific_policies")
        if not isinstance(honorifics, list) or not honorifics:
            honorifics = self._build_honorific_policies(metadata_en)
        
        explicit_retain = False
        explicit_localize = False
        ws = metadata_en.get("world_setting", {})
        if isinstance(ws, dict):
            hon = ws.get("honorifics", {})
            if isinstance(hon, dict):
                if hon.get("mode") == "retain":
                    explicit_retain = True
                    policy_text = str(hon.get("policy", "")).strip()
                    if policy_text:
                        consistency_rules.append(f"Explicit Honorifics Retention Policy: {policy_text}")
                elif hon.get("mode") == "localize":
                    explicit_localize = True
                    policy_text = str(hon.get("policy", "")).strip()
                    if policy_text:
                        consistency_rules.append(f"Explicit Honorifics Policy: {policy_text}")
                    else:
                        consistency_rules.append("Explicit policy detected: drop/localize all Japanese honorifics.")

        if explicit_retain:
            # Manifest explicitly requests JP retention — apply appropriate retention policy
            if self._is_isekai_with_jp_characters_setting(metadata_en):
                honorifics = self._isekai_japan_retention_honorific_policies()
                consistency_rules.append(
                    "Isekai/reincarnation with Japanese characters: retain all JP honorifics in English "
                    "(-san, -chan, -kun, -sama, senpai, sensei) for JP-origin characters. "
                    "Fantasy-world NPCs do not carry JP honorifics — use natural English address."
                )
                consistency_rules.append(
                    "Name-order policy: family-given (Japanese order) for JP-origin characters; "
                    "given-family only for explicitly non-Japanese characters."
                )
            else:
                honorifics = self._contemporary_japan_honorific_policies()
                consistency_rules.append(
                    "Manifest retain policy: retain all honorifics in English "
                    "(-san, -chan, -kun, -sama, senpai, sensei)."
                )
        elif not explicit_localize:
            if self._is_contemporary_japan_setting(metadata_en):
                honorifics = self._contemporary_japan_honorific_policies()
                consistency_rules.append(
                    "Contemporary Japan setting detected: retain all honorifics in English "
                    "(-san, -chan, -kun, -sama, senpai, sensei)."
                )
            elif self._is_fantasy_or_non_contemporary_setting(metadata_en):
                if self._is_isekai_with_jp_characters_setting(metadata_en):
                    honorifics = self._isekai_japan_retention_honorific_policies()
                    consistency_rules.append(
                        "Isekai/reincarnation with Japanese characters: retain all JP honorifics in English "
                        "(-san, -chan, -kun, -sama, senpai, sensei) for JP-origin characters. "
                        "Fantasy-world NPCs do not carry JP honorifics — use natural English address."
                    )
                    consistency_rules.append(
                        "Name-order policy: family-given (Japanese order) for JP-origin characters; "
                        "given-family only for explicitly non-Japanese characters."
                    )
                elif self._is_noble_setting(metadata_en):
                    honorifics = self._noble_honorific_policies()
                    consistency_rules.append(
                        "Noble fantasy setting detected: transcreate JP honorifics into noble English equivalents "
                        "(My Lord/My Lady/Your Grace/Your Highness/Master/Tutor by rank/context)."
                    )
                    consistency_rules.append(
                        "Name-order policy: given-name-first with English-equivalent naming in non-contemporary settings."
                    )
                else:
                    honorifics = self._fantasy_noncontemporary_honorific_policies()
                    consistency_rules.append(
                        "Fantasy/non-contemporary setting detected: use given-name-first order and "
                        "convert JP honorifics to natural English equivalents."
                    )
                    consistency_rules.append(
                        "Name-order policy: given-name-first with English-equivalent naming in non-contemporary settings."
                    )
        payload["honorific_policies"] = honorifics

        location_terms = payload.get("location_terms")
        if not isinstance(location_terms, list) or not location_terms:
            location_terms = self._build_location_terms()
        payload["location_terms"] = location_terms

        payload["consistency_rules"] = consistency_rules[:200]
        payload["summary"] = {
            "total_terms": len(payload["terms"]),
            "total_idioms": len(payload["idioms"]),
            "translated_terms": len(
                [t for t in payload["terms"] if isinstance(t, dict) and t.get(preferred_key)]
            ),
            "consistency_rules": len(payload["consistency_rules"]),
        }
        return payload

    def _enhance_timeline_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        chapters = payload.get("chapter_timeline", [])
        if not isinstance(chapters, list):
            return payload

        flashback_markers = (
            "flashback",
            "past",
            "years ago",
            "middle school",
            "childhood",
            "昔",
            "回想",
            "hồi tưởng",
            "quá khứ",
            "năm trước",
        )

        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            scenes = chapter.get("scenes", [])
            if not isinstance(scenes, list):
                continue
            for scene in scenes:
                if not isinstance(scene, dict):
                    continue
                summary = str(scene.get("summary", "")).lower()
                is_flashback = any(marker in summary for marker in flashback_markers)
                if self.target_language == "vn":
                    scene["temporal_type"] = "hồi_tưởng" if is_flashback else "dòng_thời_gian_hiện_tại"
                else:
                    scene["temporal_type"] = "flashback" if is_flashback else "present_timeline"
                if is_flashback and "flashback_info" not in scene:
                    scene["flashback_info"] = {
                        "relative_time": self._lang_value("past", "quá_khứ"),
                        "trigger": self._lang_value("narrative recollection", "hồi_tưởng_tự_sự"),
                        "content": str(scene.get("summary", ""))[:160],
                    }
                if self.target_language == "vn":
                    scene["tense_guidance"] = {
                        "narrative": "quá_khứ",
                        "dialogue": "hiện_tại",
                        "flashback": "quá_khứ_hoàn_thành" if is_flashback else "quá_khứ",
                    }
                else:
                    scene["tense_guidance"] = {
                        "narrative": "past",
                        "dialogue": "present",
                        "flashback": "past_perfect" if is_flashback else "past",
                    }

                # Prose rhythm guidance derived from beat_type
                beat = str(scene.get("beat_type", "setup")).lower()
                if self.target_language == "vn":
                    _BEAT_PROSE_RHYTHM = {
                        "setup":                {"sentence_length": "trung bình (10-14 từ)",      "prose_temperature": "miêu_tả"},
                        "inciting_incident":    {"sentence_length": "gọn, dứt (6-10 từ)",          "prose_temperature": "khẩn_trương"},
                        "rising_action":        {"sentence_length": "linh hoạt (8-14 từ)",         "prose_temperature": "chủ_động"},
                        "climax":               {"sentence_length": "ngắn, dồn nhịp (4-8 từ)",     "prose_temperature": "cao_trào"},
                        "falling_action":       {"sentence_length": "trung bình (10-14 từ)",       "prose_temperature": "chiêm_nghiệm"},
                        "resolution":           {"sentence_length": "dài/linh hoạt (12-18 từ)",    "prose_temperature": "ấm"},
                        "character_development":{"sentence_length": "linh hoạt (10-16 từ)",        "prose_temperature": "nội_tâm"},
                        "flashback":            {"sentence_length": "trung bình (10-14 từ)",       "prose_temperature": "hoài_niệm_trầm"},
                        "foreshadowing":        {"sentence_length": "trung bình (10-14 từ)",       "prose_temperature": "tiết_chế"},
                    }
                else:
                    _BEAT_PROSE_RHYTHM = {
                        "setup":                {"sentence_length": "medium (10-14w)",      "prose_temperature": "descriptive"},
                        "inciting_incident":    {"sentence_length": "punchy (6-10w)",       "prose_temperature": "urgent"},
                        "rising_action":        {"sentence_length": "variable (8-14w)",     "prose_temperature": "active"},
                        "climax":               {"sentence_length": "short/punchy (4-8w)",  "prose_temperature": "high-intensity"},
                        "falling_action":       {"sentence_length": "medium (10-14w)",      "prose_temperature": "reflective"},
                        "resolution":           {"sentence_length": "long/variable (12-18w)", "prose_temperature": "warm"},
                        "character_development":{"sentence_length": "variable (10-16w)",    "prose_temperature": "introspective"},
                        "flashback":            {"sentence_length": "medium (10-14w)",      "prose_temperature": "muted/nostalgic"},
                        "foreshadowing":        {"sentence_length": "medium (10-14w)",      "prose_temperature": "understated"},
                    }
                scene["prose_rhythm"] = _BEAT_PROSE_RHYTHM.get(
                    beat,
                    self._lang_value(
                        {"sentence_length": "variable (8-14w)", "prose_temperature": "neutral"}, # type: ignore
                        {"sentence_length": "linh hoạt (8-14 từ)", "prose_temperature": "trung_tính"}, # type: ignore
                    ),
                )

            chapter["scene_count"] = len([s for s in scenes if isinstance(s, dict)])

        payload["summary"] = {
            "chapter_count": len([c for c in chapters if isinstance(c, dict)]),
            "event_count": sum(int(c.get("scene_count", 0) or 0) for c in chapters if isinstance(c, dict)),
        }
        return payload

    def _enhance_idiom_payload(
        self,
        payload: Dict[str, Any],
        scene_plan_index: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        fallback = self._get_or_build_idiom_fallback(scene_plan_index)
        opportunities = payload.get("transcreation_opportunities", [])
        if not isinstance(opportunities, list):
            opportunities = []
        wordplay = payload.get("wordplay_transcreations", [])
        if not isinstance(wordplay, list):
            wordplay = []

        should_merge_fallback = True
        if self.target_language == "vn" and opportunities:
            # For VN runs, keep model-provided opportunities as primary and avoid
            # injecting EN heuristic fallback entries unless payload is empty.
            should_merge_fallback = False

        if not opportunities:
            opportunities = fallback.get("transcreation_opportunities", [])
        elif should_merge_fallback:
            existing = {
                (str(item.get("location", "")), str(item.get("japanese", "")))
                for item in opportunities
                if isinstance(item, dict)
            }
            for item in fallback.get("transcreation_opportunities", []):
                if not isinstance(item, dict):
                    continue
                key = (str(item.get("location", "")), str(item.get("japanese", "")))
                if key in existing:
                    continue
                opportunities.append(item)
                if len(opportunities) >= 140:
                    break

        if not wordplay and (should_merge_fallback or not opportunities):
            wordplay = fallback.get("wordplay_transcreations", [])

        normalized: List[Dict[str, Any]] = []
        for item in opportunities[:140]:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category", "set_phrase"))
            priority = str(item.get("transcreation_priority") or self._transcreation_priority_from_category(category)).lower()
            confidence = float(item.get("confidence", 0.0) or self._confidence_for_category(category))
            literal = str(item.get("literal", "") or item.get("japanese", ""))
            meaning = str(item.get("meaning", ""))
            options = item.get("options")
            if not isinstance(options, list) or not options:
                options = self._build_transcreation_options(
                    japanese=str(item.get("japanese", "")),
                    literal=literal,
                    meaning=meaning,
                    category=category,
                )
            item["transcreation_priority"] = priority if priority in {"critical", "high", "medium", "low"} else "medium"
            item["confidence"] = round(max(0.40, min(0.99, confidence)), 2)
            item["options"] = options[:4]
            if not item.get("stage_2_guidance"):
                item["stage_2_guidance"] = self._lang_value(
                    "Prefer rank 1 unless scene register requires stylistic lift.",
                    "Ưu tiên hạng 1, trừ khi nhịp/giọng cảnh cần nâng sắc thái.",
                )
            normalized.append(item)

        priority_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        conf_sum = 0.0
        for item in normalized:
            p = str(item.get("transcreation_priority", "low")).lower()
            if p in priority_counts:
                priority_counts[p] += 1
            conf_sum += float(item.get("confidence", 0.0) or 0.0)

        payload["transcreation_opportunities"] = normalized
        payload["wordplay_transcreations"] = [w for w in wordplay[:60] if isinstance(w, dict)]
        payload["summary"] = {
            "total_opportunities": len(normalized),
            "by_priority": priority_counts,
            "avg_confidence": round(conf_sum / len(normalized), 3) if normalized else 0.0,
        }
        return payload

    def _postprocess_context_processor_payload(
        self,
        processor_id: str,
        payload: Dict[str, Any],
        metadata_en: Dict[str, Any],
        scene_plan_index: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return payload

        payload["generated_at"] = datetime.datetime.now().isoformat()
        payload.setdefault("processor_version", "1.1")

        if processor_id == "character_context":
            return self._enhance_character_registry_payload(payload)
        if processor_id == "cultural_context":
            return self._enhance_cultural_glossary_payload(payload, metadata_en, scene_plan_index)
        if processor_id == "temporal_context":
            return self._enhance_timeline_payload(payload)
        if processor_id == "idiom_transcreation":
            return self._enhance_idiom_payload(payload, scene_plan_index)
        if processor_id == "dialect_fingerprint":
            return self._enhance_dialect_fingerprint_payload(payload, metadata_en)
        return payload

    def _enhance_dialect_fingerprint_payload(
        self,
        payload: Dict[str, Any],
        metadata_en: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            payload = {}

        reason = str(payload.get("reason", "")).strip()
        disabled = reason == "disabled_non_contemporary_setting"

        volume_summary = payload.get("volume_dialect_summary")
        if not isinstance(volume_summary, dict):
            volume_summary = {}
        volume_summary.setdefault("primary_dialect", "none")
        volume_summary.setdefault(
            "assessment",
            (
                "Dialect fingerprint disabled for non-contemporary setting."
                if disabled
                else "No significant regional dialect pattern detected."
            ),
        )
        try:
            confidence = float(volume_summary.get("confidence", 0.8))
        except Exception:
            confidence = 0.8
        volume_summary["confidence"] = round(max(0.0, min(1.0, confidence)), 2)

        chapter_profiles_raw = payload.get("chapter_profiles")
        chapter_profiles: List[Dict[str, Any]] = []
        if isinstance(chapter_profiles_raw, list):
            for item in chapter_profiles_raw:
                if not isinstance(item, dict):
                    continue
                chapter_key = self._normalize_chapter_key(item.get("chapter_id")) or str(item.get("chapter_id") or "")
                has_dialect = bool(item.get("has_dialect", False))
                profile = {
                    "chapter_id": chapter_key,
                    "has_dialect": has_dialect,
                    "dialect_type": str(item.get("dialect_type") or ("none" if not has_dialect else "unspecified")),
                    "markers": item.get("markers") if isinstance(item.get("markers"), list) else [],
                    "translation_guidance": str(item.get("translation_guidance") or "").strip(),
                }
                chapter_profiles.append(profile)

        character_map = payload.get("character_dialect_map")
        if not isinstance(character_map, dict):
            character_map = {}

        exclusions = payload.get("false_positive_exclusions")
        if not isinstance(exclusions, list):
            exclusions = []

        summary = payload.get("summary")
        if not isinstance(summary, dict):
            summary = {}
        summary.setdefault("total_chapters_scanned", len(chapter_profiles))
        summary.setdefault("chapters_with_dialect", sum(1 for p in chapter_profiles if p.get("has_dialect")))
        summary.setdefault("false_positives_suppressed", len(exclusions))

        payload["volume_id"] = self.manifest.get("volume_id", self.work_dir.name)
        payload["processor_version"] = str(payload.get("processor_version") or "1.0")
        payload["volume_dialect_summary"] = volume_summary
        payload["chapter_profiles"] = chapter_profiles
        payload["character_dialect_map"] = character_map
        payload["false_positive_exclusions"] = exclusions
        payload["summary"] = summary
        payload.setdefault(
            "translation_guidance",
            "Prioritize natural dialogue register; only preserve region-specific flavor when source evidence is explicit.",
        )
        if disabled:
            payload["reason"] = "disabled_non_contemporary_setting"
        elif reason and reason != "disabled_non_contemporary_setting":
            payload["reason"] = reason
        elif "reason" in payload:
            payload.pop("reason", None)

        return payload

    def _build_system_instruction(self) -> str:
        patch_key = f"metadata_{self.target_language}_patch"
        title_field = self._localized_field("title")
        author_field = self._localized_field("author")
        language_label = self._target_language_name()
        base_instruction = (
            "You are the Phase 1.55 Rich Metadata Updater for MTL Studio.\n"
            "Use the cached full Japanese LN text to refine rich metadata quality.\n"
            "CRITICAL: Output ONLY valid JSON. No markdown, no explanations, no prose. Start with { and end with }.\n"
            "Output shape:\n"
            "{\n"
            f'  "{patch_key}": {{\n'
            '    "character_profiles": {...},\n'
            '    "relationship_progress": [...],\n'
            '    "localization_notes": {...},\n'
            '    "world_setting": {...},\n'
            '    "geography": {...},\n'
            '    "weapons_artifacts": {...},\n'
            '    "organizations": {...},\n'
            '    "cultural_terms": {...},\n'
            '    "mythology": {...},\n'
            '    "translation_rules": {...},\n'
            '    "dialogue_patterns": {...},\n'
            '    "scene_contexts": {...},\n'
            '    "emotional_pronoun_shifts": {...},\n'
            '    "translation_guidelines": {...},\n'
            '    "official_localization": {...},\n'
            '    "cross_chapter_rules": [...],\n'
            '    "schema_version": "v4.0_cached_enrichment"\n'
            "  }\n"
            "}\n"
            "Rules:\n"
            "0) Scan the ENTIRE cached LN corpus before deciding updates.\n"
            "1) Keep Japanese surname-first order for Japanese characters (absolute).\n"
            f"2) Follow v4.0 schema structure exactly for {patch_key} fields.\n"
            "3) ONLY fill blank/placeholder values. Do NOT overwrite already-populated fields.\n"
            f"4) Do NOT modify {title_field}/{author_field}/chapter title fields/character_names/glossary.\n"
            "5) Keep unknown values empty instead of guessing.\n"
            "6) Prefer concrete character evidence from cached chapter text.\n"
            f"6.1) All newly generated human-readable values must be in {language_label}.\n"
            "6.2) Name extraction must explicitly detect and preserve:\n"
            "     - Full legal names (surname + given name),\n"
            "     - Kira-kira names (canonical stylized form and nickname variants),\n"
            "     - SNS handles/usernames as separate fields (do not collapse into legal names).\n"
            "     Preserve source distinctions between legal name, stylized name, nickname, and handle.\n"
            "7) Maintain character_profiles.*.visual_identity_non_color with non-color identity markers:\n"
            "   hairstyle, outfit silhouette/signature, expression baseline, posture/gesture, accessories.\n"
            "   Include habitual_gestures as a structured array when evidence exists.\n"
            "   Required per habitual_gestures entry: gesture; optional: trigger, intensity,\n"
            "   narrative_effect, evidence_chapters[], confidence(0-1).\n"
            "   Do not invent habitual gestures. Use only source-grounded recurring actions.\n"
            "8) Keep Bible-compatible continuity fields schema-safe: world_setting/geography/weapons_artifacts/"
            "organizations/cultural_terms/mythology/translation_rules.\n"
            f"9) Always include {patch_key}.relationship_progress as an array.\n"
            "   For slow-burn romance arcs, encode chapter-scoped progression entries with contraction_override.\n"
            "   This progression policy can override global contraction targets within the scoped scene/voice context.\n"
            "10) CRITICAL: Always generate a `cross_chapter_rules` array of strings based on structural continuity.\n"
            "    For motif fingerprinting, inspect afterword chapter(s) first when available, then verify against the full volume.\n"
            "    If afterword chapter(s) are unavailable, fall back to scanning the full volume directly.\n"
            "    Scan all chapters for recurring thematic/emotional motifs, callback phrases, 'thesis statement'\n"
            "    sentences that repeat, or core rules that must remain consistent across the entire volume.\n"
            "    Prefix these rules with 'MOTIF CALLBACK:', 'PHRASE CALLBACK:', or 'MUST_FIX:'.\n"
            "11) Valid extended character_profiles fields (fill when source evidence exists):\n"
            "    body_description_vocabulary: sensory/tactile vocabulary guide for physically described characters.\n"
            "    Fields: principle, preferred_adjectives[], forbidden_alternatives[], specific_mappings{}.\n"
            "11) Valid extended dialogue_patterns fields:\n"
            "    default_register: describes the character's baseline emotional delivery mode (wit, deflection, etc.).\n"
            "    sincere_mode: describes when/how the character drops their default register.\n"
            "    gaming_stat_mode: for characters who express emotion as game stats. Fields: principle,\n"
            "    canonical_example, preserve_literally[], emotional_states_as_stats{}.\n"
            "12) Valid extended localization_notes fields:\n"
            "    register_precision_rules.beauty_descriptor_hierarchy: JP beauty-term → EN register mapping.\n"
            "    minor_character_archetypes: per-archetype rendering rules for affectation-speech characters.\n"
            "    Fields: description, rendering_principle, preferred_markers[], avoid.\n"
            "13) POV MIRROR DIALOGUE DETECTION — scan the entire corpus for dual-POV structure:\n"
            "    A dual-POV volume has chapters in Character A's POV and chapters in Character B's POV\n"
            "    covering the same timeline (e.g., JP 「」 speech in one block, 『』 speech in another block).\n"
            "    If detected, populate translation_guidelines.pov_mirror_consistency with:\n"
            "    {\n"
            "      'detected': true,\n"
            "      'pov_a': {'character': '...', 'chapters': [...], 'jp_speech_marks': '「」'},\n"
            "      'pov_b': {'character': '...', 'chapters': [...], 'jp_speech_marks': '『』'},\n"
            "      'identical_dialogue_rule': 'If a spoken line appears in both POV sections as the same speech act, the EN translation MUST be character-for-character identical in both occurrences. Do not rephrase or reword a line simply because the surrounding narrator has changed.',\n"
            "      'anchor_lines': [\n"
            "        {'event': '...', 'pov_a_location': '...', 'pov_b_location': '...', 'jp_line': '...', 'enforcement': 'copy verbatim from first EN rendering'}\n"
            "      ]\n"
            "    }\n"
            "    The anchor_lines list must enumerate every confirmed cross-POV shared speech act found in the JP corpus.\n"
            "    For lines where the JP wording DIFFERS between the two POV sections (recollection variant), add:\n"
            "    {'verdict': 'wording differs — translate fresh but match register and key vocabulary from POV-A rendering'}\n"
            "14) OFFICIAL LOCALIZATION ENFORCEMENT DATA (critical):\n"
            "    If authoritative official English localization is found, populate official_localization with:\n"
            "    - should_use_official=true\n"
            "    - confidence (high/medium/low or 0-1)\n"
            "    - series_title_en / volume_title_en / author_en / publisher_en when available\n"
            "    - sources[] with title + URL evidence for each official claim.\n"
            "    - media_type per source when inferable: light_novel | manga | anime | unknown.\n"
            "    MEDIA PRIORITY RULE: if multiple official media localizations exist,\n"
            "    choose LIGHT NOVEL localization first; manga/anime naming is secondary.\n"
            "    Only set should_use_official=true when evidence is verifiable and not fan-only.\n"
        )
        if self.schema_spec_path.exists():
            try:
                schema_text = self.schema_spec_path.read_text(encoding="utf-8")
                return f"{base_instruction}\n\nReference schema (v4.0):\n{schema_text}"
            except Exception:
                pass
        return base_instruction

    def _build_prompt(
        self,
        metadata_en: Dict[str, Any],
        bible_context: str,
        cache_stats: Dict[str, Any],
    ) -> str:
        current_key = f"metadata_{self.target_language}_current"
        prompt_payload = {
            "metadata": self.manifest.get("metadata", {}),
            current_key: metadata_en,
            "cache_stats": cache_stats,
            "bible_id": self.manifest.get("bible_id", ""),
            "series_context": bible_context[:32000] if bible_context else "",
            "motif_source_context": self._build_afterword_motif_context(max_chars=12000),
            "target_language": self.target_language,
        }
        return (
            "Refine and expand rich metadata for this volume using the cached full LN text.\n"
            "Focus on character_profiles, localization_notes, dialogue/register behavior,\n"
            "and any semantic guidance that improves Phase 2 translation consistency.\n"
            "Also maintain relationship progression for long-running/slow-burn romance in relationship_progress array,\n"
            "including chapter scope and contraction_override when needed.\n"
            "Keep Bible continuity categories aligned and schema-safe:\n"
            "world_setting, geography, weapons_artifacts, organizations, cultural_terms, mythology, translation_rules.\n"
            "For motif callback extraction in cross_chapter_rules, use afterword chapter(s) as the first-pass motif fingerprint source,\n"
            "then validate/extend across full-volume evidence. If afterword is unavailable, use full-volume-only fallback.\n"
            "For character_profiles, fill/maintain `visual_identity_non_color` with non-color descriptors.\n"
            "Include `visual_identity_non_color.habitual_gestures` as structured entries when evidence supports recurrence.\n"
            "Use entry shape: {gesture, trigger, intensity, narrative_effect, evidence_chapters, confidence}.\n"
            "Never infer or invent habitual gestures without textual/scene evidence.\n"
            "ADDITIONAL EXTRACTION TARGETS (fill if blank; do not overwrite populated values):\n"
            "A) character_profiles[name].body_description_vocabulary — for physically active characters, extract:\n"
            "   principle: how their physicality should read (grace vs strength vs cuteness etc.)\n"
            "   preferred_adjectives: sensory/tactile adjectives that match their character register\n"
            "   forbidden_alternatives: generic/jarring adjectives that break their voice\n"
            "   specific_mappings: JP adjective → preferred EN mapping with rationale\n"
            "   Only populate when the JP source uses distinct physical descriptor vocabulary.\n"
            "B) localization_notes.register_precision_rules.beauty_descriptor_hierarchy — extract if the volume\n"
            "   features characters who self-assess beauty at a different register than external confirmation.\n"
            "   Map each JP beauty term (美少女/可愛い/美人/綺麗 etc.) to its English register equivalent.\n"
            "   Flag canonical conflict example if the gap between self-assessed and confirmed register is a comedic beat.\n"
            "C) dialogue_patterns[name].default_register — add for characters whose DEFAULT emotional delivery mode\n"
            "   is indirect (wit, deflection, irony). Describe: what registers as affection vs what registers as alarm.\n"
            "   Add dialogue_patterns[name].sincere_mode describing when/how they drop their default guard.\n"
            "D) localization_notes.minor_character_archetypes — for one-off or recurring comic archetypes:\n"
            "   Identify speech affectation type (fake_ojousan, chuunibyou, etc.), rendering_principle,\n"
            "   preferred_markers (English patterns that signal the affectation), and what to avoid.\n"
            "   Only add entries grounded in source-text evidence of a character using that affectation.\n"
            "E) dialogue_patterns[name].gaming_stat_mode — for characters who report emotional state using\n"
            "   game/stat terminology (HP, MP, status effects). Extract:\n"
            "   principle: the rendering rule (preserve literalness — not metaphor, but status report)\n"
            "   canonical_example: JP source line → correct EN (with incorrect EN alternative to avoid)\n"
            "   preserve_literally: list of game terms to keep as-is in EN\n"
            "   emotional_states_as_stats: mapping of emotion/situation → game-stat framing\n"
            "F) translation_guidelines.pov_mirror_consistency — CRITICAL for dual-POV volumes:\n"
            "   Scan the entire JP corpus for dual-POV structure (e.g., one block uses 「」 for speech,\n"
            "   another block uses 『』 for the same timeline from a different character's perspective).\n"
            "   If dual-POV structure is detected:\n"
            "   1. Identify pov_a (primary POV character, chapters, JP speech mark) and pov_b (mirror POV).\n"
            "   2. Find every dialogue line that appears in BOTH POV sections as the same speech act.\n"
            "      A 'same speech act' is when Character X speaks a line that is heard/shown in BOTH blocks,\n"
            "      even if the JP wording differs slightly between the two POV renderings.\n"
            "   3. For each match, record: event name, pov_a location (chapter + approximate paragraph),\n"
            "      pov_b location, the JP source line(s) from both POVs, and enforcement verdict:\n"
            "      - 'verbatim_match': JP is identical → EN must be copied character-for-character from first rendering\n"
            "      - 'wording_differs': JP differs (recollection variant) → translate pov_b fresh but anchor key words\n"
            "        to the pov_a EN rendering (same verb choices, same register, same emotional coloring).\n"
            "   4. Output as translation_guidelines.pov_mirror_consistency with fields:\n"
            "      detected (bool), pov_a {}, pov_b {}, identical_dialogue_rule (string), anchor_lines []\n"
            "G) Name extraction reinforcement for character_profiles:\n"
            "   For each character, explicitly look for and preserve:\n"
            "   - full_name (legal/canonical full name when evidenced),\n"
            "   - ruby_base_full (full kanji name base as written, e.g., 藤崎徹; never surname-only/given-only when full form exists),\n"
            "   - ruby_reading_full (full furigana reading aligned to ruby_base_full, e.g., とうざきとおる; never partial reading),\n"
            "   - kira_kira_name_canonical (stylized canonical display/readings),\n"
            "   - kira_kira_name_nicknames (nickname variants of stylized names),\n"
            "   - sns_handles (app IDs, @handles, account/display IDs).\n"
            "   Never overwrite already populated values; only fill blanks/placeholders.\n"
            f"Language directive: all newly generated descriptive values must be in {self._target_language_name()}.\n"
            f"Directive: only fill blank or placeholder values in current metadata_{self.target_language}.\n"
            "Do not overwrite existing populated values.\n"
            "OFFICIAL LOCALIZATION POLICY:\n"
            "- If official EN localization is found with verifiable source URLs, populate official_localization\n"
            "  and set should_use_official=true.\n"
            "- Include grounded evidence in official_localization.sources[] (title + url).\n"
            "- Prioritize LIGHT NOVEL media localization over manga/anime localization when conflicting.\n"
            "- Add source-level media_type whenever inferable (light_novel/manga/anime/unknown).\n"
            "- If evidence is uncertain or fan-only, set should_use_official=false.\n"
            "Return only valid JSON in the required output shape.\n\n"
            f"INPUT:\n{json.dumps(prompt_payload, ensure_ascii=False, indent=2)}"
        )

    def _confidence_meets_official_threshold(self, confidence: Any) -> bool:
        if isinstance(confidence, (int, float)):
            return float(confidence) >= 0.6
        label = str(confidence or "").strip().lower()
        return label in {"high", "medium", "med", "strong", "confirmed"}

    def _has_verifiable_official_sources(self, official: Dict[str, Any]) -> bool:
        sources = official.get("sources", [])
        if not isinstance(sources, list) or not sources:
            return False
        for source in sources:
            if not isinstance(source, dict):
                continue
            url = str(source.get("url") or "").strip().lower()
            title = str(source.get("title") or "").strip()
            if url.startswith(("http://", "https://")) and title:
                return True
        return False

    def _classify_source_media(self, source: Dict[str, Any]) -> str:
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

    def _official_sources_ln_priority_ok(self, official: Dict[str, Any]) -> bool:
        sources = official.get("sources", [])
        if not isinstance(sources, list) or not sources:
            return False

        ln_count = 0
        manga_count = 0
        anime_count = 0

        for source in sources:
            media = self._classify_source_media(source)
            if media == "light_novel":
                ln_count += 1
            elif media == "manga":
                manga_count += 1
            elif media == "anime":
                anime_count += 1

        if ln_count > 0:
            return True
        if manga_count > 0 or anime_count > 0:
            return False
        return True

    def _enforce_official_english_metadata(self, metadata_block: Dict[str, Any]) -> List[str]:
        """
        Enforce canonical EN metadata when official localization is verified.

        This is a code-level guardrail, not only a prompt directive:
        when official_localization.should_use_official is true and evidence is strong,
        mapped EN metadata fields are deterministically overridden.
        """
        if self.target_language != "en" or not isinstance(metadata_block, dict):
            return []

        official = metadata_block.get("official_localization", {})
        if not isinstance(official, dict):
            return []

        should_use = bool(official.get("should_use_official", False))
        confidence_ok = self._confidence_meets_official_threshold(official.get("confidence"))
        sources_ok = self._has_verifiable_official_sources(official)
        media_priority_ok = self._official_sources_ln_priority_ok(official)
        if not (should_use and confidence_ok and sources_ok and media_priority_ok):
            if should_use and sources_ok and not media_priority_ok:
                logger.warning(
                    "Skipped official EN override: sources appear manga/anime-only without LN-priority evidence."
                )
            return []

        applied: List[str] = []
        for official_key, metadata_key in self.OFFICIAL_LOCALIZATION_EN_FIELD_MAP.items():
            value = official.get(official_key)
            if not isinstance(value, str):
                continue
            normalized = value.strip()
            if not normalized:
                continue
            if metadata_block.get(metadata_key) != normalized:
                metadata_block[metadata_key] = normalized
                applied.append(metadata_key)

        if applied:
            official["enforcement_applied"] = True
            official["enforced_fields"] = sorted(applied)
            metadata_block["official_localization"] = official

        return applied

    def _get_metadata_block(self) -> Dict[str, Any]:
        metadata = self.manifest.get(self.metadata_key, {})
        if isinstance(metadata, dict) and metadata:
            return metadata
        if self.target_language == "en":
            fallback = self.manifest.get("metadata_en", {})
            if isinstance(fallback, dict):
                return fallback
        return {}

    def _set_metadata_block(self, value: Dict[str, Any]) -> None:
        value = normalize_payload_names(value, self.manifest)
        self.manifest[self.metadata_key] = value
        if self.target_language == "en":
            self.manifest["metadata_en"] = value

    def _sanitize_patch(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        cleaned: Dict[str, Any] = {}
        for key, value in patch.items():
            if key in self.PROTECTED_FIELDS:
                continue
            if key not in self.ALLOWED_PATCH_FIELDS:
                continue
            if key == "relationship_progress" and not isinstance(value, list):
                continue
            cleaned[key] = value
        return cleaned

    def _is_blank_or_placeholder(self, value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return True
            lower = s.lower()
            if lower in {"unknown", "n/a"}:
                return True
            return any(tok in lower for tok in self.PLACEHOLDER_TOKENS)
        if isinstance(value, list):
            if len(value) == 0:
                return True
            return all(self._is_blank_or_placeholder(v) for v in value)
        if isinstance(value, dict):
            if len(value) == 0:
                return True
            return all(self._is_blank_or_placeholder(v) for v in value.values())
        return False

    def _is_placeholder_scaffold_string(self, value: str) -> bool:
        lowered = str(value or "").strip().lower()
        if not lowered:
            return False
        if (
            "[protagonist]" in lowered
            or "[love_interest]" in lowered
            or "[optional]" in lowered
        ):
            return True
        return any(tok in lowered for tok in self.PLACEHOLDER_TOKENS)

    def _strip_placeholder_scaffolds(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: self._strip_placeholder_scaffolds(v) for k, v in value.items()}
        if isinstance(value, list):
            cleaned: List[Any] = []
            for item in value:
                normalized = self._strip_placeholder_scaffolds(item)
                if isinstance(normalized, str) and not normalized.strip():
                    continue
                cleaned.append(normalized)
            return cleaned
        if isinstance(value, str):
            if self._is_placeholder_scaffold_string(value):
                return ""
            return value
        return value

    def _filter_patch_to_placeholders(
        self,
        current: Dict[str, Any],
        patch: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Allow patch writes only where current metadata is blank/placeholder/missing."""
        filtered: Dict[str, Any] = {}
        for key, new_value in patch.items():
            if key not in current:
                filtered[key] = new_value
                continue

            cur_value = current.get(key)

            if key == "relationship_progress":
                if self._should_replace_relationship_progress(cur_value):
                    filtered[key] = new_value
                continue

            if isinstance(new_value, dict) and isinstance(cur_value, dict):
                nested = self._filter_patch_to_placeholders(cur_value, new_value)
                if nested:
                    filtered[key] = nested
                continue

            if self._is_blank_or_placeholder(cur_value):
                filtered[key] = new_value
        return filtered

    def _should_replace_relationship_progress(self, current_value: Any) -> bool:
        """
        Allow relationship_progress updates when existing value is effectively template-only.

        This keeps the "fill placeholders only" policy while permitting Phase 1.55
        to replace Librarian scaffold entries such as [PROTAGONIST]/[LOVE_INTEREST].
        """
        if self._is_blank_or_placeholder(current_value):
            return True
        if not isinstance(current_value, list):
            return False
        if not current_value:
            return True
        return self._contains_relationship_progress_template_markers(current_value)

    def _contains_relationship_progress_template_markers(self, value: Any) -> bool:
        """Detect scaffold/template markers in relationship_progress payloads."""
        if isinstance(value, str):
            lowered = value.strip().lower()
            if (
                "[protagonist]" in lowered
                or "[love_interest]" in lowered
                or "[optional]" in lowered
                or "slow_burn_main_pair" in lowered
                or "guarded_formal" in lowered
            ):
                return True
            return any(tok in lowered for tok in self.PLACEHOLDER_TOKENS)
        if isinstance(value, list):
            return any(self._contains_relationship_progress_template_markers(v) for v in value)
        if isinstance(value, dict):
            return any(self._contains_relationship_progress_template_markers(v) for v in value.values())
        return False

    def _deep_merge_dict(self, base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(base)
        for key, value in patch.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._deep_merge_dict(result[key], value)
            else:
                result[key] = value
        return result

    def _backfill_visual_identity_non_color(self, metadata_block: Dict[str, Any]) -> int:
        """
        Add baseline non-color visual identity payload where missing.

        Uses existing `appearance` text as a safe fallback summary.
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

            appearance = profile.get("appearance")
            if isinstance(appearance, str) and appearance.strip():
                profile["visual_identity_non_color"] = {
                    "identity_summary": appearance.strip(),
                    "habitual_gestures": [],
                }
                updated += 1

        return updated

    def _extract_balanced_json_object(self, text: str) -> Optional[str]:
        """Extract first balanced top-level JSON object from arbitrary text."""
        start = text.find("{")
        if start < 0:
            return None

        depth = 0
        in_string = False
        escaped = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escaped:
                    escaped = False
                    continue
                if ch == "\\":
                    escaped = True
                    continue
                if ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue
            if ch == "{":
                depth += 1
                continue
            if ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : idx + 1]
        return None

    def _normalize_json_candidate(self, text: str) -> str:
        """Apply lightweight cleanup to likely-JSON text."""
        cleaned = text.replace("\ufeff", "").replace("“", '"').replace("”", '"')
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)  # trailing commas
        cleaned = re.sub(r"//.*", "", cleaned)  # single-line comments
        cleaned = re.sub(r"/\*[\s\S]*?\*/", "", cleaned)  # block comments
        # Repair malformed keys like: temporal_markers": [...]
        cleaned = re.sub(r'(?m)^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\"?)\s*:', r'\1"\2":', cleaned)
        # Repair malformed chapter timeline object entries like:
        #   {
        #     "chapter_04",
        #     "sequence_index": 4,
        #   }
        # -> {
        #      "chapter_id": "chapter_04",
        #      "sequence_index": 4,
        #    }
        cleaned = re.sub(
            r'(?m)^(\s*)"(chapter_\d{1,3})"\s*,\s*\n(\s*"sequence_index"\s*:)',
            r'\1"chapter_id": "\2",\n\3',
            cleaned,
        )
        # Repair malformed chapter object entries like:
        #   "chapter_04",
        #   "event": "..."
        # -> "chapter_id": "chapter_04",
        # Scope guard: only when next non-empty line is an object key (contains colon).
        cleaned = re.sub(
            r'(?m)^(\s*)"(chapter_\d{1,3})"\s*,?\s*$\n(?=\s*"[A-Za-z_][A-Za-z0-9_]*"\s*:)',
            r'\1"chapter_id": "\2",\n',
            cleaned,
        )
        # Remove non-JSON control chars that models occasionally emit in long outputs.
        cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", " ", cleaned)
        return cleaned.strip()

    def _repair_chapter_wrapper_missing_outer_brace_with_decoder_feedback(
        self,
        text: str,
        *,
        max_attempts: int = 10,
    ) -> Optional[str]:
        """
        Repair malformed chapter wrapper entries by JSON decoder feedback.

        Targets parse errors where parser expects an object property key but sees
        the next array item `{`, which often means one `}` is missing before a comma:
          "chapter_18": { ... },   <-- should be "chapter_18": { ... }},
          {
        """
        candidate = text
        for _ in range(max_attempts):
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError as e:
                if "Expecting property name enclosed in double quotes" not in str(e.msg):
                    return None

                pos = int(e.pos)
                if pos <= 0 or pos >= len(candidate):
                    return None

                # Typical symptom: parser sees next array item '{' while still in object context.
                if candidate[pos] != "{":
                    return None

                # Scope guard: the offending token should start a chapter wrapper item:
                #   { "chapter_19": { ... } }
                # If not, skip this targeted repair.
                next_chunk = candidate[pos : pos + 120]
                if not re.match(r'\{\s*"chapter_\d{1,3}"\s*:\s*\{', next_chunk):
                    return None

                prev_close_comma = candidate.rfind("},", 0, pos)
                if prev_close_comma < 0:
                    return None

                between = candidate[prev_close_comma + 2 : pos]
                if between.strip():
                    return None

                if candidate[prev_close_comma : prev_close_comma + 3] == "}},":
                    return None

                candidate = (
                    candidate[:prev_close_comma]
                    + "}},"
                    + candidate[prev_close_comma + 2 :]
                )
                continue
            except Exception:
                return None
        return None

    def _repair_missing_comma_with_decoder_feedback(
        self,
        text: str,
        *,
        max_attempts: int = 10,
    ) -> Optional[str]:
        """
        Repair JSON that is syntactically valid except for missing commas.

        Uses JSON decoder feedback to insert a comma at the reported error offset
        when the decoder specifically asks for a comma delimiter.
        """
        candidate = text
        for _ in range(max_attempts):
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError as e:
                if "Expecting ',' delimiter" not in str(e.msg):
                    return None

                insert_at = int(e.pos)
                if insert_at <= 0 or insert_at > len(candidate):
                    return None

                # Insert before the current token, skipping leading whitespace.
                while insert_at > 0 and candidate[insert_at - 1].isspace():
                    insert_at -= 1

                prev = insert_at - 1
                while prev >= 0 and candidate[prev].isspace():
                    prev -= 1
                if prev < 0 or candidate[prev] in "{[,:":  # no valid value before insertion
                    return None
                if candidate[prev] == ",":
                    return None

                candidate = candidate[:insert_at] + "," + candidate[insert_at:]
                candidate = re.sub(r",\s*,+", ",", candidate)
                candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
                continue
            except Exception:
                return None
        return None

    def _repair_missing_colon_with_decoder_feedback(
        self,
        text: str,
        *,
        max_attempts: int = 10,
    ) -> Optional[str]:
        """
        Repair JSON that is syntactically valid except for missing ':' delimiters.

        Uses JSON decoder feedback to insert a colon at the reported error offset
        when the decoder specifically requests a colon delimiter.
        """
        candidate = text
        for _ in range(max_attempts):
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError as e:
                if "Expecting ':' delimiter" not in str(e.msg):
                    return None

                insert_at = int(e.pos)
                if insert_at <= 0 or insert_at > len(candidate):
                    return None

                # Move insertion point to first non-space character.
                while insert_at < len(candidate) and candidate[insert_at].isspace():
                    insert_at += 1
                if insert_at >= len(candidate):
                    return None

                if candidate[insert_at] == ":":
                    return None

                prev = insert_at - 1
                while prev >= 0 and candidate[prev].isspace():
                    prev -= 1
                if prev < 0:
                    return None

                # Most valid recoveries happen after quoted keys.
                if candidate[prev] != '"':
                    return None

                candidate = candidate[:insert_at] + ": " + candidate[insert_at:]
                candidate = re.sub(r":\s*:", ": ", candidate)
                candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
                continue
            except Exception:
                return None
        return None

    def _repair_truncated_json_candidate(self, text: str) -> Optional[str]:
        """
        Attempt recovery for truncated model JSON.

        Strategy:
        1. Close an unterminated string if needed.
        2. Replace a dangling key/value delimiter with null.
        3. Close remaining unbalanced objects/arrays.
        """
        candidate = text.strip()
        if not candidate or not candidate.startswith("{"):
            return None

        stack: List[str] = []
        in_string = False
        escaped = False
        for ch in candidate:
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch in "{[":
                stack.append(ch)
            elif ch in "}]":
                if stack and ((stack[-1] == "{" and ch == "}") or (stack[-1] == "[" and ch == "]")):
                    stack.pop()

        repaired = candidate
        if in_string:
            repaired += '"'

        # If output is cut at a dangling key/value marker, coerce to null.
        repaired = re.sub(r'("([^"\\]|\\.)*"\s*:\s*)$', r"\1null", repaired)
        # If output is cut right after a key token (e.g., {"context": {"scene"),
        # coerce dangling key into null so object can be closed safely.
        repaired = re.sub(r'([,{]\s*"([^"\\]|\\.)*")\s*$', r"\1: null", repaired)
        repaired = re.sub(r",\s*$", "", repaired)

        while stack:
            opener = stack.pop()
            repaired += "}" if opener == "{" else "]"

        repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
        try:
            json.loads(repaired)
            return repaired
        except Exception:
            return None

    def _extract_midstream_fence_segments(self, text: str) -> List[str]:
        """
        Split content around markdown-fence JSON restarts injected mid-response.

        Some model responses restart with ```json {...} inside an unfinished
        object/string. We keep both prefix and suffix segments as recovery
        candidates.
        """
        segments: List[str] = []
        seen = set()

        for marker in re.finditer(r"```(?:json)?\s*\{", text, flags=re.IGNORECASE):
            if marker.start() == 0:
                continue

            # Prefix: trim the partial line containing the fence marker.
            line_start = text.rfind("\n", 0, marker.start())
            prefix_end = line_start if line_start >= 0 else marker.start()
            prefix = text[:prefix_end].strip()
            if prefix and prefix not in seen:
                segments.append(prefix)
                seen.add(prefix)

            # Suffix: remove the fence token and keep the restarted JSON body.
            suffix = text[marker.start():]
            suffix = re.sub(
                r"^```(?:json)?\s*",
                "",
                suffix,
                count=1,
                flags=re.IGNORECASE,
            ).strip()
            if suffix and suffix not in seen:
                segments.append(suffix)
                seen.add(suffix)

        return segments

    @staticmethod
    def _looks_english_text(text: str) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        # Vietnamese diacritics -> treat as localized, not English.
        if re.search(r"[ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]", value, re.IGNORECASE):
            return False
        lower = value.lower()
        english_markers = (
            " the ", " and ", " with ", " from ", " to ", " of ",
            "friend", "classmate", "protagonist", "voice", "register",
            "relationship", "status", "romantic", "professional", "family",
            "neutral", "developing", "acquaintance", "teacher", "student",
        )
        if any(tok in f" {lower} " for tok in english_markers):
            return True
        # ASCII-heavy sentence chunks are likely English in this context.
        ascii_letters = len(re.findall(r"[A-Za-z]", value))
        non_ascii_letters = len(re.findall(r"[^ -~]", value))
        return ascii_letters >= 8 and non_ascii_letters == 0

    def _character_registry_needs_vn_retry(self, payload: Dict[str, Any]) -> bool:
        if self.target_language != "vn" or not isinstance(payload, dict):
            return False
        chars = payload.get("characters", [])
        if not isinstance(chars, list) or not chars:
            return False

        samples = 0
        english_hits = 0
        for char in chars[:16]:
            if not isinstance(char, dict):
                continue
            for key in ("role", "voice_register"):
                text = char.get(key)
                if isinstance(text, str) and text.strip():
                    samples += 1
                    if self._looks_english_text(text):
                        english_hits += 1
            edges = char.get("relationship_edges", [])
            if isinstance(edges, list):
                for edge in edges[:8]:
                    if not isinstance(edge, dict):
                        continue
                    for key in ("type", "status"):
                        text = edge.get(key)
                        if isinstance(text, str) and text.strip():
                            samples += 1
                            if self._looks_english_text(text):
                                english_hits += 1
            if samples >= 48:
                break

        if samples == 0:
            return False
        # Trigger retry when EN dominates descriptive fields.
        return english_hits >= max(6, int(samples * 0.45))

    def _parse_json_response(self, content: str) -> Dict[str, Any]:
        text = content.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        candidates: List[str] = [text]

        balanced = self._extract_balanced_json_object(text)
        if balanced and balanced not in candidates:
            candidates.append(balanced)

        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            regex_candidate = match.group(0)
            if regex_candidate not in candidates:
                candidates.append(regex_candidate)

        # Recovery: model may restart JSON mid-response. Prefer any block that
        # looks like a top-level schema root with "volume_id".
        for marker in re.finditer(r'\{\s*"volume_id"\s*:', text):
            sub = text[marker.start():]
            rooted = self._extract_balanced_json_object(sub)
            if rooted and rooted not in candidates:
                candidates.append(rooted)

        # Recovery: midstream markdown fence restart (```json) can corrupt a
        # string/key in the first object. Add split segments as candidates.
        for segment in self._extract_midstream_fence_segments(text):
            if segment not in candidates:
                candidates.append(segment)
            balanced_segment = self._extract_balanced_json_object(segment)
            if balanced_segment and balanced_segment not in candidates:
                candidates.append(balanced_segment)

        last_error: Optional[Exception] = None
        for candidate in candidates:
            try:
                return json.loads(candidate)
            except Exception as e:
                last_error = e

        # Repair pass for common model mistakes.
        for candidate in candidates:
            cleaned = self._normalize_json_candidate(candidate)
            try:
                return json.loads(cleaned)
            except Exception as e:
                last_error = e

            repaired_wrappers = self._repair_chapter_wrapper_missing_outer_brace_with_decoder_feedback(
                cleaned
            )
            if repaired_wrappers:
                try:
                    return json.loads(repaired_wrappers)
                except Exception as e:
                    last_error = e

            balanced_cleaned = self._extract_balanced_json_object(cleaned)
            if balanced_cleaned:
                try:
                    return json.loads(balanced_cleaned)
                except Exception as e:
                    last_error = e

            repaired_missing_colons = self._repair_missing_colon_with_decoder_feedback(cleaned)
            if repaired_missing_colons:
                try:
                    return json.loads(repaired_missing_colons)
                except Exception as e:
                    last_error = e

                balanced_colon = self._extract_balanced_json_object(repaired_missing_colons)
                if balanced_colon:
                    try:
                        return json.loads(balanced_colon)
                    except Exception as e:
                        last_error = e

            repaired_missing_commas = self._repair_missing_comma_with_decoder_feedback(cleaned)
            if repaired_missing_commas:
                try:
                    return json.loads(repaired_missing_commas)
                except Exception as e:
                    last_error = e

            if repaired_missing_colons:
                repaired_colon_then_comma = self._repair_missing_comma_with_decoder_feedback(
                    repaired_missing_colons
                )
                if repaired_colon_then_comma:
                    try:
                        return json.loads(repaired_colon_then_comma)
                    except Exception as e:
                        last_error = e

            repaired_truncated = self._repair_truncated_json_candidate(
                repaired_missing_commas or repaired_missing_colons or cleaned
            )
            if repaired_truncated:
                try:
                    return json.loads(repaired_truncated)
                except Exception as e:
                    last_error = e

        if last_error:
            raise last_error
        raise ValueError("Unable to parse JSON response")

    def _save_parse_failure_payload(self, stage: str, content: str, error: Exception) -> None:
        """Persist raw malformed payload for debugging parse failures."""
        try:
            debug_dir = self._context_dir_path() / "_debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            volume_id = self.manifest.get("volume_id", self.work_dir.name)
            safe_volume = re.sub(r"[^\w\-]+", "_", str(volume_id)).strip("_")[:80] or "volume"
            safe_stage = re.sub(r"[^\w\-]+", "_", str(stage)).strip("_") or "stage"
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            debug_path = debug_dir / f"{timestamp}_{safe_volume}_{safe_stage}_raw_response.txt"
            error_header = f"# Parse failure: {type(error).__name__}: {error}\n\n"
            debug_path.write_text(error_header + (content or ""), encoding="utf-8")
            logger.warning(f"[P1.55] Saved malformed payload for debugging: {debug_path}")
        except Exception as save_err:
            logger.debug(f"[P1.55] Could not persist parse failure payload: {save_err}")

    def _extract_event_metadata(self, profile_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract only current-volume event/relationship metadata from character profile."""
        event_fields = {}
        for key in (
            "relationship_to_protagonist",
            "relationship_to_others",
            "rtas_relationships",
            "how_character_refers_to_others",
            "keigo_switch",
            "contraction_rate",
            "character_arc",
        ):
            value = profile_data.get(key)
            if value and not self._is_blank_or_placeholder(value):
                event_fields[key] = value

        # Preserve volume-scoped dynamics (e.g., volume_2_development)
        for key, value in profile_data.items():
            if key.lower().startswith("volume_") and value and not self._is_blank_or_placeholder(value):
                event_fields[key] = value

        return event_fields

    def _push_volume_event_metadata_only(
        self,
        bible_sync: Any,
        metadata_block: Dict[str, Any],
    ) -> Dict[str, int]:
        """Push only volume-scoped event metadata; never touch canonical naming fields."""
        bible = getattr(bible_sync, "bible", None)
        if not bible:
            return {"updated": 0, "skipped": 0, "missing_in_bible": 0}

        profiles = metadata_block.get("character_profiles", {})
        if not isinstance(profiles, dict):
            return {"updated": 0, "skipped": 0, "missing_in_bible": 0}

        volume_id = self.manifest.get("volume_id", "")
        short_id = bible_sync.bible_ctrl._extract_short_id(volume_id) or volume_id

        updated = 0
        skipped = 0
        missing_in_bible = 0

        for profile_key, profile_data in profiles.items():
            if not isinstance(profile_data, dict):
                skipped += 1
                continue

            jp_key = None
            try:
                jp_key = bible_sync._resolve_profile_key(profile_key, profile_data)
            except Exception:
                jp_key = profile_key if re.search(r'[\u3040-\u9fff]', profile_key) else None

            if not jp_key:
                skipped += 1
                continue

            char_entry = bible.data.get("characters", {}).get(jp_key)
            if not isinstance(char_entry, dict):
                missing_in_bible += 1
                continue

            event_payload = self._extract_event_metadata(profile_data)
            if not event_payload:
                skipped += 1
                continue

            volume_events = char_entry.setdefault("volume_events", {})
            if not isinstance(volume_events, dict):
                volume_events = {}
                char_entry["volume_events"] = volume_events

            existing = volume_events.get(short_id, {})
            if not isinstance(existing, dict):
                existing = {}
            merged = self._deep_merge_dict(existing, event_payload)

            if merged != existing:
                volume_events[short_id] = merged
                updated += 1
            else:
                skipped += 1

        # Keep volume registration current without altering canonical naming metadata.
        title = self.manifest.get("metadata", {}).get("title", "")
        try:
            from pipeline.metadata_processor.agent import extract_volume_number
            idx = extract_volume_number(title) or len(bible.volumes_registered) + 1
        except Exception:
            idx = len(bible.volumes_registered) + 1
        bible.register_volume(volume_id=short_id, title=title, index=idx)
        if short_id:
            try:
                bible_sync.bible_ctrl.link_volume(volume_id, bible.series_id)
            except Exception:
                pass

        if updated > 0:
            bible.save()
            entry = bible_sync.bible_ctrl.index.get("series", {}).get(bible.series_id, {})
            entry["entry_count"] = bible.entry_count()
            bible_sync.bible_ctrl._save_index()

        return {"updated": updated, "skipped": skipped, "missing_in_bible": missing_in_bible}

    def _context_dir_path(self) -> Path:
        context_dir = self.work_dir / self.CONTEXT_DIR
        context_dir.mkdir(parents=True, exist_ok=True)
        return context_dir

    def _context_output_path(self, processor_id: str) -> Path:
        filename = self.CONTEXT_PROCESSOR_FILES.get(processor_id, f"{processor_id}.json")
        path = Path(filename)
        scoped_name = f"{path.stem}_{self.target_language}{path.suffix or '.json'}"
        return self._context_dir_path() / scoped_name

    def _normalize_chapter_key(self, value: Any) -> str:
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

    def _load_scene_plan_index(self) -> Dict[str, Dict[str, Any]]:
        plans_dir = self.work_dir / "PLANS"
        index: Dict[str, Dict[str, Any]] = {}
        if not plans_dir.exists():
            return index

        for path in sorted(plans_dir.glob("*_scene_plan.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue

            chapter_key = self._normalize_chapter_key(payload.get("chapter_id") or path.stem)
            if not chapter_key:
                continue

            scenes: List[Dict[str, Any]] = []
            raw_scenes = payload.get("scenes", [])
            if isinstance(raw_scenes, list):
                for scene in raw_scenes:
                    if not isinstance(scene, dict):
                        continue
                    scenes.append(
                        {
                            "id": str(scene.get("id") or "").strip(),
                            "beat_type": str(scene.get("beat_type") or "").strip(),
                            "emotional_arc": str(scene.get("emotional_arc") or "").strip(),
                            "dialogue_register": str(scene.get("dialogue_register") or "").strip(),
                            "target_rhythm": str(scene.get("target_rhythm") or "").strip(),
                            "start_paragraph": scene.get("start_paragraph"),
                            "end_paragraph": scene.get("end_paragraph"),
                            "illustration_anchor": bool(scene.get("illustration_anchor")),
                        }
                    )

            index[chapter_key] = {
                "chapter_id": chapter_key,
                "overall_tone": str(payload.get("overall_tone") or "").strip(),
                "pacing_strategy": str(payload.get("pacing_strategy") or "").strip(),
                "pov_tracking": payload.get("pov_tracking") if isinstance(payload.get("pov_tracking"), dict) else {},
                "scenes": scenes,
            }

        return index

    def _build_processor_context_payload(
        self,
        metadata_en: Dict[str, Any],
        cache_stats: Dict[str, Any],
        scene_plan_index: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        metadata = self.manifest.get("metadata", {})
        char_names = metadata_en.get("character_names", {})
        profiles = metadata_en.get("character_profiles", {})

        profile_summary: Dict[str, Dict[str, Any]] = {}
        if isinstance(profiles, dict):
            for key, value in list(profiles.items())[:40]:
                if not isinstance(value, dict):
                    continue
                profile_summary[key] = {
                    "name_en": value.get("name_en", ""),
                    "role": value.get("role", ""),
                    "archetype": value.get("archetype", ""),
                    "speech_pattern": value.get("speech_pattern", ""),
                    "personality": value.get("personality", ""),
                }

        scene_summary: Dict[str, Dict[str, Any]] = {}
        for chapter_key, plan in scene_plan_index.items():
            scenes = plan.get("scenes", [])
            compact_scenes = []
            if isinstance(scenes, list):
                for scene in scenes[:24]:
                    if not isinstance(scene, dict):
                        continue
                    compact_scenes.append(
                        {
                            "id": scene.get("id"),
                            "beat_type": scene.get("beat_type"),
                            "dialogue_register": scene.get("dialogue_register"),
                            "target_rhythm": scene.get("target_rhythm"),
                            "start_paragraph": scene.get("start_paragraph"),
                            "end_paragraph": scene.get("end_paragraph"),
                        }
                    )
            scene_summary[chapter_key] = {
                "overall_tone": plan.get("overall_tone", ""),
                "pacing_strategy": plan.get("pacing_strategy", ""),
                "scene_count": len(scenes) if isinstance(scenes, list) else 0,
                "scenes": compact_scenes,
            }

        return {
            "volume_id": self.manifest.get("volume_id", self.work_dir.name),
            "book_title_jp": metadata.get("title", ""),
            "book_author_jp": metadata.get("author", ""),
            "book_genre": metadata.get("genre", ""),
            "target_language": self.target_language,
            "cache_stats": cache_stats,
            "motif_source_context": self._build_afterword_motif_context(max_chars=6000),
            "character_names": char_names if isinstance(char_names, dict) else {},
            "character_profiles_summary": profile_summary,
            "scene_plan_summary": scene_summary,
            "existing_cultural_terms": metadata_en.get("cultural_terms", {}),
            "existing_localization_notes": metadata_en.get("localization_notes", {}),
            # Furigana authority: ruby_names from Librarian phase are the canonical readings
            # Format: [{"kanji": "藤崎徹", "ruby": "とうざきとおる", "name_type": "person", ...}]
            "ruby_names_furigana": [
                {"kanji": n.get("kanji", ""), "ruby": n.get("ruby", ""), "name_type": n.get("name_type", "")}
                for n in self.manifest.get("ruby_names", [])
                if n.get("kanji") and n.get("ruby")
            ],
        }

    def _generate_with_optional_cache(
        self,
        *,
        prompt: str,
        system_instruction: str,
        full_volume_text: str,
        display_name: str,
        tools: Optional[List[Any]] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
        response = None
        cache_name = None
        try:
            cache_name = self.client.create_cache(
                model=self.MODEL_NAME,
                system_instruction=system_instruction,
                contents=[full_volume_text],
                ttl_seconds=self.CACHE_TTL_SECONDS,
                display_name=display_name,
                tools=tools,
            )
            if cache_name:
                response = self.client.generate(
                    prompt=prompt,
                    temperature=self.TEMPERATURE,
                    max_output_tokens=self.PROCESSOR_MAX_OUTPUT_TOKENS,
                    generation_config=self._phase_generation,
                    model=self.MODEL_NAME,
                    cached_content=cache_name,
                )
            else:
                response = self.client.generate(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    temperature=self.TEMPERATURE,
                    max_output_tokens=self.PROCESSOR_MAX_OUTPUT_TOKENS,
                    generation_config=self._phase_generation,
                    model=self.MODEL_NAME,
                    tools=tools,
                )
        except Exception as e:
            logger.warning(f"[P1.55] Processor call failed ({display_name}): {e}")
            return None, f"call_failed: {str(e)[:240]}", None
        finally:
            if cache_name:
                self.client.delete_cache(cache_name)

        if not response or not response.content:
            return None, "empty_response", None
        try:
            payload = self._parse_json_response(response.content)
        except Exception as e:
            logger.warning(f"[P1.55] Processor JSON parse failed ({display_name}): {e}")
            debug_dir = self._context_dir_path() / "_debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", display_name).strip("._-") or "processor"
            debug_path = debug_dir / f"{safe_name}_raw_response.txt"
            try:
                debug_path.write_text(response.content, encoding="utf-8")
            except Exception:
                debug_path = None
            return None, f"json_parse_failed: {str(e)[:240]}", (
                str(debug_path.relative_to(self.work_dir)) if debug_path else None
            )
        if not isinstance(payload, dict):
            return None, "non_dict_payload", None
        return payload, None, None

    def _fallback_character_registry(self, metadata_en: Dict[str, Any]) -> Dict[str, Any]:
        characters: List[Dict[str, Any]] = []
        profiles = metadata_en.get("character_profiles", {})
        if isinstance(profiles, dict):
            for idx, (key, value) in enumerate(profiles.items(), start=1):
                if not isinstance(value, dict):
                    continue
                characters.append(
                    {
                        "id": f"char_{idx:03d}",
                        "key": key,
                        "canonical_name": value.get("name_en") or key,
                        "full_name": value.get("full_name", ""),
                        "ruby_base_full": value.get("ruby_base_full", ""),
                        "ruby_reading_full": value.get("ruby_reading_full", ""),
                        "kira_kira_name_canonical": value.get("kira_kira_name_canonical", ""),
                        "kira_kira_name_nicknames": value.get("kira_kira_name_nicknames", []),
                        "sns_handles": value.get("sns_handles", []),
                        "japanese_name": value.get("name_jp") or key,
                        "role": value.get("role", ""),
                        "archetype": value.get("archetype", ""),
                    }
                )

        payload = {
            "volume_id": self.manifest.get("volume_id", self.work_dir.name),
            "generated_at": datetime.datetime.now().isoformat(),
            "processor_version": "1.0",
            "characters": characters,
            "relationship_graph": {},
            "pronoun_resolution_hints": [],
            "summary": {
                "total_characters": len(characters),
                "total_relationship_edges": 0,
            },
        }
        return self._enhance_character_registry_payload(payload)

    def _fallback_cultural_glossary(self, metadata_en: Dict[str, Any]) -> Dict[str, Any]:
        terms: List[Dict[str, Any]] = []
        source_terms = metadata_en.get("cultural_terms", {})
        preferred_key = self._preferred_term_key()
        if isinstance(source_terms, dict):
            for key, value in list(source_terms.items())[:60]:
                if isinstance(value, dict):
                    meaning = (
                        value.get(preferred_key)
                        or value.get(f"canonical_{self.target_language}")
                        or value.get(f"meaning_{self.target_language}")
                        or value.get("preferred_en")
                        or value.get("canonical_en")
                        or value.get("meaning_en")
                        or value.get("translation")
                        or ""
                    )
                    notes = value.get("notes") or value.get("context") or ""
                else:
                    meaning = str(value)
                    notes = ""
                terms.append(
                    {
                        "term_jp": key,
                        preferred_key: meaning,
                        "notes": notes,
                    }
                )

        payload = {
            "volume_id": self.manifest.get("volume_id", self.work_dir.name),
            "generated_at": datetime.datetime.now().isoformat(),
            "processor_version": "1.0",
            "terms": terms,
            "idioms": [],
            "honorific_policies": [],
            "location_terms": [],
            "summary": {
                "total_terms": len(terms),
                "total_idioms": 0,
            },
        }
        return self._enhance_cultural_glossary_payload(payload, metadata_en, {})

    def _fallback_timeline_map(self, scene_plan_index: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        timeline: List[Dict[str, Any]] = []
        if scene_plan_index:
            for chapter_key in sorted(scene_plan_index.keys()):
                plan = scene_plan_index.get(chapter_key, {})
                scenes = plan.get("scenes", [])
                timeline.append(
                    {
                        "chapter_id": chapter_key,
                        "sequence_index": int(chapter_key.split("_")[-1]) if "_" in chapter_key else 0,
                        "scene_count": len(scenes) if isinstance(scenes, list) else 0,
                        "scenes": scenes if isinstance(scenes, list) else [],
                        "temporal_markers": [],
                        "continuity_constraints": [],
                    }
                )
        else:
            # Stage 1 plans may be missing for older/partial runs. Build a
            # minimal chapter-level timeline from JP source so Stage 2 still
            # receives continuity scaffolding instead of an empty map.
            chapter_map = self._load_chapter_text_map()
            for chapter_key in sorted(chapter_map.keys()):
                lines = chapter_map.get(chapter_key, [])
                excerpt = ""
                for raw in lines:
                    text = str(raw).strip()
                    if not text:
                        continue
                    if text.startswith("#"):
                        continue
                    excerpt = text
                    break
                if not excerpt:
                    excerpt = self._lang_value(
                        "Scene progression inferred from chapter source text.",
                        "Diễn tiến cảnh được suy từ văn bản chương gốc.",
                    )

                scene_summary = self._lang_value(
                    f"Inferred timeline from source: {excerpt[:140]}",
                    f"Mốc diễn tiến suy từ nguồn: {excerpt[:140]}",
                )
                sequence_index = int(chapter_key.split("_")[-1]) if "_" in chapter_key else 0
                beat = "setup" if sequence_index <= 1 else "event"
                fallback_scene = {
                    "id": "S01",
                    "beat_type": beat,
                    "summary": scene_summary,
                    "start_paragraph": 1,
                    "end_paragraph": max(1, len(lines)),
                }
                timeline.append(
                    {
                        "chapter_id": chapter_key,
                        "sequence_index": sequence_index,
                        "scene_count": 1,
                        "scenes": [fallback_scene],
                        "temporal_markers": [],
                        "continuity_constraints": [],
                    }
                )

        payload = {
            "volume_id": self.manifest.get("volume_id", self.work_dir.name),
            "generated_at": datetime.datetime.now().isoformat(),
            "processor_version": "1.0",
            "chapter_timeline": timeline,
            "global_continuity_rules": [],
            "summary": {
                "chapter_count": len(timeline),
                "event_count": sum(item.get("scene_count", 0) for item in timeline),
            },
        }
        return self._enhance_timeline_payload(payload)

    def _fallback_idiom_transcreation(self) -> Dict[str, Any]:
        scene_plan_index = self._load_scene_plan_index()
        return self._get_or_build_idiom_fallback(scene_plan_index)

    def _fallback_dialect_fingerprint(
        self,
        metadata_en: Dict[str, Any],
        *,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        effective_reason = reason
        if not effective_reason and not self._is_contemporary_japan_setting(metadata_en):
            effective_reason = "disabled_non_contemporary_setting"

        assessment = (
            "Dialect fingerprint disabled for non-contemporary setting."
            if effective_reason == "disabled_non_contemporary_setting"
            else "Fallback dialect fingerprint applied due to unavailable model output."
        )

        payload: Dict[str, Any] = {
            "volume_id": self.manifest.get("volume_id", self.work_dir.name),
            "generated_at": datetime.datetime.now().isoformat(),
            "processor_version": "1.0",
            "volume_dialect_summary": {
                "primary_dialect": "none",
                "assessment": assessment,
                "confidence": 0.7 if effective_reason == "disabled_non_contemporary_setting" else 0.5,
            },
            "chapter_profiles": [],
            "character_dialect_map": {},
            "false_positive_exclusions": [],
            "translation_guidance": "Apply no dialect-specific English accenting unless explicitly evidenced in source.",
            "summary": {
                "total_chapters_scanned": 0,
                "chapters_with_dialect": 0,
                "false_positives_suppressed": 0,
            },
        }
        if effective_reason:
            payload["reason"] = effective_reason
        return payload

    def _build_pronoun_shift_context_payload(
        self,
        metadata_en: Dict[str, Any],
        scene_plan_index: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        emotional = metadata_en.get("emotional_pronoun_shifts", {}) if isinstance(metadata_en, dict) else {}
        events_by_chapter = {}
        if isinstance(emotional, dict):
            candidate = emotional.get("events_by_chapter", {})
            if isinstance(candidate, dict):
                for chapter_key, events in candidate.items():
                    if isinstance(events, list):
                        events_by_chapter[str(chapter_key)] = [e for e in events if isinstance(e, dict)]

        if not events_by_chapter:
            events_by_chapter = self._detect_pronoun_shift_events(metadata_en, scene_plan_index)

        event_count = sum(len(v) for v in events_by_chapter.values())
        active_directives = {}
        for chapter_key, events in events_by_chapter.items():
            directives: List[str] = []
            for event in events:
                for directive in event.get("active_directives", []):
                    text = str(directive or "").strip()
                    if text and text not in directives:
                        directives.append(text)
            if directives:
                active_directives[chapter_key] = directives

        return {
            "volume_id": self.manifest.get("volume_id", self.work_dir.name),
            "generated_at": datetime.datetime.now().isoformat(),
            "processor_version": "1.0",
            "events_by_chapter": events_by_chapter,
            "active_directives_by_chapter": active_directives,
            "summary": {
                "event_chapters": len(events_by_chapter),
                "event_count": event_count,
            },
        }

    def _fallback_pronoun_shift_events(
        self,
        metadata_en: Dict[str, Any],
        scene_plan_index: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        return self._build_pronoun_shift_context_payload(metadata_en, scene_plan_index)

    def _estimate_processor_items(self, processor_id: str, payload: Dict[str, Any]) -> int:
        if processor_id == "character_context":
            return len(payload.get("characters", []))
        if processor_id == "cultural_context":
            return len(payload.get("terms", [])) + len(payload.get("idioms", []))
        if processor_id == "temporal_context":
            return len(payload.get("chapter_timeline", []))
        if processor_id == "idiom_transcreation":
            return len(payload.get("transcreation_opportunities", [])) + len(payload.get("wordplay_transcreations", []))
        if processor_id == "dialect_fingerprint":
            return len(payload.get("chapter_profiles", []))
        if processor_id == "pronoun_shift_events":
            events = payload.get("events_by_chapter", {})
            if isinstance(events, dict):
                return sum(len(v) for v in events.values() if isinstance(v, list))
            return 0
        return 0

    def _run_context_processors(
        self,
        *,
        full_volume_text: str,
        metadata_en: Dict[str, Any],
        cache_stats: Dict[str, Any],
        scene_plan_index: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        context_payload = self._build_processor_context_payload(
            metadata_en=metadata_en,
            cache_stats=cache_stats,
            scene_plan_index=scene_plan_index,
        )
        if types is None:
            logger.warning(
                "[P1.55] google.genai.types unavailable; idiom transcreation processor "
                "will run without Google Search grounding."
            )
        volume_id = self.manifest.get("volume_id", self.work_dir.name)
        target_label = self._target_language_name()
        preferred_key = self._preferred_term_key()
        location_key = self._location_term_key()
        pronoun_hints_key = f"pronoun_hints_{self.target_language}"
        is_contemporary_japan = self._is_contemporary_japan_setting(metadata_en)
        self._context_dir_path()

        processor_specs: List[Dict[str, Any]] = [
            {
                "id": "character_context",
                "display_name": f"{volume_id}_p155_character_ctx",
                "system_instruction": (
                    "You are Processor 1: Character Context Processor.\n"
                    "CRITICAL: Output ONLY valid JSON. No markdown, no explanations, no prose. Start with { and end with }.\n"
                    "Task: Use full cached LN text + input context payload to build a chapter-agnostic character registry.\n"
                    "Do not invent characters not in source.\n"
                    f"Language directive: all human-readable descriptive fields must be in {target_label}.\n"
                    "Do NOT translate/stylize id keys, canonical_name, japanese_name, or aliases.\n"
                    "Name extraction target (mandatory): identify and separate for each character:\n"
                    "- full_name (legal/canonical full name when evidenced),\n"
                    "- ruby_base_full (the FULL ruby-bearing base name; do not output surname-only or given-only if full name exists),\n"
                    "- ruby_reading_full (the FULL furigana reading for ruby_base_full; must align 1:1 with full base name),\n"
                    "- kira_kira_name_canonical (stylized canonical display/readings),\n"
                    "- kira_kira_name_nicknames (nickname variants of stylized names),\n"
                    "- sns_handles (SNS/app IDs, @handles, display account names).\n"
                    "Do NOT conflate these categories and do NOT store handles as legal names.\n"
                    "CRITICAL: For Japanese character names, you MUST use the FURIGANA (ruby) reading as the authoritative pronunciation.\n"
                    "Follow the 3-style ruby convention:\n"
                    "  1. NAROU style: 名前《なまえ》→ Name (most common, for standard readings)\n"
                    "  2. INTERWEAVE style: 名前《な》ま《え》→ Na-may (split ruby for compound words)\n"
                    "  3. LN/KIRA-KIRA style: 名前《ナマエ》→ Namae (katakana for stylized/glamorous characters)\n"
                    "When source text contains ruby annotations like 藤崎{とうざき}徹{とおる}, you MUST use the furigana reading 'Touzaki' not 'Fujisaki'.\n"
                    "The author's specified ruby reading is the absolute authoritative pronunciation - never override it with standard kanji readings.\n"
                    "FULL-NAME ENFORCEMENT: if ruby evidence exists for a full name, output the full pair in ruby_base_full + ruby_reading_full.\n"
                    "Do not degrade to surname-only or given-name-only ruby entries unless the source itself contains only that fragment.\n"
                    "Output schema:\n"
                    "{\n"
                    '  "volume_id": "...",\n'
                    '  "generated_at": "...",\n'
                    '  "processor_version": "1.0",\n'
                    '  "characters": [\n'
                    "    {\n"
                    '      "id": "char_001",\n'
                    '      "canonical_name": "string",\n'
                    '      "full_name": "string",\n'
                    '      "ruby_base_full": "string",\n'
                    '      "ruby_reading_full": "string",\n'
                    '      "kira_kira_name_canonical": "string",\n'
                    '      "kira_kira_name_nicknames": ["..."],\n'
                    '      "sns_handles": ["..."],\n'
                    '      "japanese_name": "string",\n'
                    '      "aliases": ["..."],\n'
                    '      "role": "string",\n'
                    '      "voice_register": "string",\n'
                    '      "relationship_edges": [{"with":"char_002","type":"string","status":"string"}],\n'
                    f'      "{pronoun_hints_key}": ["..."]\n'
                    "    }\n"
                    "  ],\n"
                    '  "relationship_graph": {"char_001_char_002":{"type":"string","status":"string"}},\n'
                    '  "pronoun_resolution_hints": [{"pattern":"string","likely_character":"char_001"}],\n'
                    '  "summary": {"total_characters": 0, "total_relationship_edges": 0}\n'
                    "}\n"
                ),
                "prompt": (
                    "Generate character context registry for Phase 1.55.\n"
                    "Use robust canonical naming, aliases, relationships, and pronoun disambiguation hints.\n"
                    "Explicitly extract full names, full ruby base+reading pairs, kira-kira canonical/nickname forms, and SNS handles per character.\n"
                    "If full-name ruby evidence exists, do not output partial surname/given-name fragments.\n"
                    "Prefer source-grounded evidence from full cached LN.\n"
                    f"Write descriptive fields (role, voice_register, relationship edge type/status, hints) in {target_label}.\n"
                    f"INPUT:\n{json.dumps(context_payload, ensure_ascii=False, indent=2)}"
                ),
                "fallback_builder": self._fallback_character_registry,
                "tools": None,
            },
            {
                "id": "cultural_context",
                "display_name": f"{volume_id}_p155_cultural_ctx",
                "system_instruction": (
                    "You are Processor 2: Cultural Context Processor.\n"
                    "CRITICAL: Output ONLY valid JSON. No markdown, no explanations, no prose. Start with { and end with }.\n"
                    "Task: Pre-resolve cultural terms, honorific handling, idioms, and location-specific context.\n"
                    "Setting policy matrix (mandatory):\n"
                    "A) Contemporary Japan setting:\n"
                    "   - retain all Japanese honorifics in target-language output.\n"
                    "   - retain suffix/title forms: -san, -chan, -kun, -sama, -senpai, -sensei.\n"
                    "   - do not translate senpai/sensei to senior/teacher and do not omit these honorifics.\n"
                    "   - modern-world exception: if text mentions parallel-world/isekai/reincarnation but\n"
                    "     the society remains modern/contemporary Japan, STILL apply A (do not switch to fantasy policy).\n"
                    "   - retain Japanese cultural terms by default in contemporary contexts; do not noble-transcreate them.\n"
                    "B) Fantasy or non-contemporary world setting:\n"
                    "   - use given-name-first order and convert names to natural target-language equivalents.\n"
                    "   - do not retain JP honorific suffixes verbatim by default; transcreate naturally.\n"
                    "C) Noble/aristocratic setting (takes priority inside B):\n"
                    "   - transcreate all JP honorifics to noble target-language equivalents by register/context.\n"
                    "Do not force transcreation; preserve clarity and narrative flow.\n"
                    "Output schema:\n"
                    "{\n"
                    '  "volume_id": "...",\n'
                    '  "generated_at": "...",\n'
                    '  "processor_version": "1.0",\n'
                    f'  "terms": [{{"term_jp":"string","{preferred_key}":"string","notes":"string","confidence":0.0}}],\n'
                    '  "idioms": [{"japanese":"string","meaning":"string","preferred_rendering":"string","confidence":0.0}],\n'
                    '  "honorific_policies": [{"pattern":"-san","strategy":"retain_in_english|retain_or_adapt|transcreate_to_english_equivalent|transcreate_to_noble_english_equivalent|given_name_first_convert_to_english_equivalent","rule":"string"}],\n'
                    f'  "location_terms": [{{"jp":"string","{location_key}":"string","notes":"string"}}],\n'
                    '  "summary": {"total_terms":0,"total_idioms":0}\n'
                    "}\n"
                ),
                "prompt": (
                    "Generate cultural context glossary for Phase 1.55.\n"
                    "Capture terms that Stage 2 repeatedly needs.\n"
                    "Apply the setting policy matrix strictly:\n"
                    "- Contemporary Japan => retain JP honorifics.\n"
                    "- Contemporary Japan + isekai/reincarnation/parallel-world framing => STILL retain JP honorifics/terms.\n"
                    "- Fantasy/non-contemporary => given-name-first + target-language-equivalent naming.\n"
                    "- Noble setting => transcreate all JP honorifics to noble target-language titles.\n"
                    f"- Output human-readable values in {target_label}.\n"
                    f"INPUT:\n{json.dumps(context_payload, ensure_ascii=False, indent=2)}"
                ),
                "fallback_builder": self._fallback_cultural_glossary,
                "tools": None,
            },
            {
                "id": "temporal_context",
                "display_name": f"{volume_id}_p155_temporal_ctx",
                "system_instruction": (
                    "You are Processor 3: Temporal Context Processor.\n"
                    "CRITICAL: Output ONLY valid JSON. No markdown, no explanations, no prose. Start with { and end with }.\n"
                    "Task: Build chapter/scenes timeline map and continuity constraints from cached LN + scene plans.\n"
                    f"Language directive: all human-readable values (summary, temporal_markers, continuity_constraints, global_continuity_rules) must be in {target_label}.\n"
                    "Keep machine tags/id fields stable and compact.\n"
                    "Output schema:\n"
                    "{\n"
                    '  "volume_id": "...",\n'
                    '  "generated_at": "...",\n'
                    '  "processor_version": "1.0",\n'
                    '  "chapter_timeline": [\n'
                    "    {\n"
                    '      "chapter_id":"chapter_01",\n'
                    '      "sequence_index":1,\n'
                    '      "scenes":[{"id":"S01","beat_type":"setup","summary":"string","start_paragraph":0,"end_paragraph":0}],\n'
                    '      "temporal_markers":["string"],\n'
                    '      "continuity_constraints":["string"]\n'
                    "    }\n"
                    "  ],\n"
                    '  "global_continuity_rules": ["string"],\n'
                    '  "summary": {"chapter_count":0,"event_count":0}\n'
                    "}\n"
                ),
                "prompt": (
                    "Generate temporal continuity map for Phase 1.55.\n"
                    "Align with chapter scene plans when available.\n"
                    f"Write descriptive content in {target_label}.\n"
                    f"INPUT:\n{json.dumps(context_payload, ensure_ascii=False, indent=2)}"
                ),
                "fallback_builder": lambda data: self._fallback_timeline_map(scene_plan_index),
                "tools": None,
            },
            {
                "id": "idiom_transcreation",
                "display_name": f"{volume_id}_p155_idiom_transcreation",
                "system_instruction": (
                    "You are Processor 4: Opportunistic Idiom Transcreation Processor.\n"
                    "CRITICAL: Output ONLY valid JSON. No markdown, no explanations, no prose. Start with { and end with }.\n"
                    f"Goal: detect high-impact JP idiom/subtext/wordplay opportunities where literal {target_label} may lose literary impact.\n"
                    "Opportunistic means: suggest options, do NOT force transcreation when literal works.\n"
                    f"Grounding directive: use Google Search for idiom/proverb/cultural-subtext verification and {target_label} equivalence checks.\n"
                    "Source priority for grounding: Official Localization -> AniDB -> MyAnimeList -> Ranobe-Mori -> Fan Translation -> Heuristic Inference.\n"
                    f"Language directive: all human-readable values (meaning, options.text, options.reasoning, stage_2_guidance) must be in {target_label}.\n"
                    "Output schema:\n"
                    "{\n"
                    '  "volume_id":"...",\n'
                    '  "generated_at":"...",\n'
                    '  "processor_version":"1.0",\n'
                    '  "transcreation_opportunities":[\n'
                    "    {\n"
                    '      "id":"trans_001",\n'
                    '      "location":"CHAPTER_01_LINE_123",\n'
                    '      "japanese":"string",\n'
                    '      "literal":"string",\n'
                    '      "meaning":"string",\n'
                    '      "category":"proverb|onomatopoeia|cultural_subtext|wordplay|metaphorical_imagery|body_part_idiom|set_phrase",\n'
                    '      "context":{"scene":"CH01_SC01","character_speaking":"string","emotional_tone":"string","beat_type":"string"},\n'
                    '      "transcreation_priority":"critical|high|medium|low",\n'
                    '      "confidence":0.0,\n'
                    '      "options":[\n'
                    '        {"rank":1,"text":"string","type":"english_equivalent|creative_transcreation|literal|hybrid","confidence":0.0,"reasoning":"string","register":"string","preserves_imagery":true,"preserves_meaning":true,"literary_impact":"high|medium|low"}\n'
                    "      ],\n"
                    '      "stage_2_guidance":"string"\n'
                    "    }\n"
                    "  ],\n"
                    '  "wordplay_transcreations":[\n'
                    '    {"id":"wordplay_001","location":"CHAPTER_02_LINE_210","japanese":"string","meaning":"string","transcreation_priority":"critical|high|medium|low","confidence":0.0,"options":[{"rank":1,"text":"string","confidence":0.0}]}\n'
                    "  ],\n"
                    '  "summary":{"total_opportunities":0,"by_priority":{"critical":0,"high":0,"medium":0,"low":0},"avg_confidence":0.0}\n'
                    "}\n"
                    "Constraints:\n"
                    "- Max 140 opportunities total.\n"
                    "- Keep options concise, stage-usable, and voice-aware.\n"
                    "- For low priority opportunities, literal can be rank 1.\n"
                ),
                "prompt": (
                    "Generate idiom transcreation cache for Stage 2.\n"
                    "Include confidence-ranked options and guidance, filtered for literary impact.\n"
                    "Do not over-transcreate low-priority items.\n"
                    f"All descriptive fields must be in {target_label}.\n"
                    f"INPUT:\n{json.dumps(context_payload, ensure_ascii=False, indent=2)}"
                ),
                "fallback_builder": lambda data: self._fallback_idiom_transcreation(),
                "tools": [types.Tool(google_search=types.GoogleSearch())] if types else None,
            },
        ]

        if is_contemporary_japan:
            processor_specs.append(
                {
                    "id": "dialect_fingerprint",
                    "display_name": f"{volume_id}_p155_dialect_fingerprint",
                    "system_instruction": (
                        "You are Processor 5: Dialect Fingerprint Processor.\n"
                        "CRITICAL: Output ONLY valid JSON. No markdown, no explanations, no prose. Start with { and end with }.\n"
                        "Task: Analyze full cached LN corpus for genuine regional Japanese dialect evidence.\n"
                        "Do NOT misclassify standard colloquial contractions (e.g., ちゃう/っちゃ from てしまう, めっちゃ as widespread slang) as regional dialect by default.\n"
                        "Provide chapter-level and character-level dialect fingerprints with confidence and translation guidance.\n"
                        "Output schema:\n"
                        "{\n"
                        '  "volume_id": "...",\n'
                        '  "generated_at": "...",\n'
                        '  "processor_version": "1.0",\n'
                        '  "volume_dialect_summary": {"primary_dialect":"none|kansai|kyushu|tohoku|...","assessment":"string","confidence":0.0},\n'
                        '  "chapter_profiles": [{"chapter_id":"chapter_01","has_dialect":false,"dialect_type":"none","markers":[],"translation_guidance":"string"}],\n'
                        '  "character_dialect_map": {"Character":{"primary_speech":"string","occasional_features":["..."]}},\n'
                        '  "false_positive_exclusions": [{"pattern":"string","misclassification":"string","actual":"string","affected_chapters":["chapter_01"]}],\n'
                        '  "translation_guidance": "string",\n'
                        '  "summary": {"total_chapters_scanned":0,"chapters_with_dialect":0,"false_positives_suppressed":0}\n'
                        "}\n"
                    ),
                    "prompt": (
                        "Generate dialect_fingerprint cache for Phase 1.55.\n"
                        "Analyze the full volume and distinguish genuine regional dialect from nationwide colloquial Japanese.\n"
                        "When uncertain, prefer conservative classification (no dialect).\n"
                        f"All descriptive values must be in {target_label}.\n"
                        f"INPUT:\n{json.dumps(context_payload, ensure_ascii=False, indent=2)}"
                    ),
                    "fallback_builder": lambda data: self._fallback_dialect_fingerprint(data),
                    "tools": None,
                }
            )
        else:
            logger.info(
                "[P1.55] Skipping dialect_fingerprint processor: non-contemporary setting detected."
            )
            processor_specs.append(
                {
                    "id": "dialect_fingerprint",
                    "display_name": f"{volume_id}_p155_dialect_fingerprint_skipped",
                    "skip_model_call": True,
                    "fallback_builder": lambda data: self._fallback_dialect_fingerprint(
                        data,
                        reason="disabled_non_contemporary_setting",
                    ),
                    "tools": None,
                }
            )

        processor_specs.append(
            {
                "id": "pronoun_shift_events",
                "display_name": f"{volume_id}_p155_pronoun_shift_events",
                "skip_model_call": True,
                "fallback_builder": lambda data: self._fallback_pronoun_shift_events(
                    data,
                    scene_plan_index,
                ),
                "tools": None,
            }
        )

        results: Dict[str, Any] = {
            "status": "completed",
            "processors": {},
            "output_files": [],
        }

        for spec in processor_specs:
            processor_id = spec["id"]
            output_path = self._context_output_path(processor_id)
            language_retry_applied = False
            if spec.get("skip_model_call"):
                payload = spec["fallback_builder"](metadata_en)
                fallback_reason = None
                debug_artifact = None
                status = "skipped"
            else:
                payload, fallback_reason, debug_artifact = self._generate_with_optional_cache(
                    prompt=spec["prompt"],
                    system_instruction=spec["system_instruction"],
                    full_volume_text=full_volume_text,
                    display_name=spec["display_name"],
                    tools=spec.get("tools"),
                )
                if (
                    processor_id == "character_context"
                    and self.target_language == "vn"
                    and isinstance(payload, dict)
                    and self._character_registry_needs_vn_retry(payload)
                ):
                    logger.warning(
                        "[P1.55] character_context output appears English-heavy for VN target; retrying with strict VN directive."
                    )
                    retry_prompt = (
                        f"{spec['prompt']}\n\n"
                        "CRITICAL RETRY RULES:\n"
                        "- Rewrite all descriptive fields in Vietnamese.\n"
                        "- Keep JSON shape unchanged.\n"
                        "- Keep canonical_name, japanese_name, aliases, and IDs unchanged.\n"
                        "- CRITICAL: Output ONLY valid JSON. No markdown, no explanations, no prose. Start with { and end with }.\n"
                    )
                    retry_payload, retry_reason, retry_debug = self._generate_with_optional_cache(
                        prompt=retry_prompt,
                        system_instruction=spec["system_instruction"],
                        full_volume_text=full_volume_text,
                        display_name=f"{spec['display_name']}_vn_retry",
                        tools=spec.get("tools"),
                    )
                    if isinstance(retry_payload, dict):
                        payload = retry_payload
                        language_retry_applied = True
                        fallback_reason = None
                        debug_artifact = None
                    else:
                        logger.warning(
                            f"[P1.55] VN retry for character_context did not return valid JSON ({retry_reason}); keeping initial payload."
                        )
                if not isinstance(payload, dict):
                    payload = spec["fallback_builder"](metadata_en)
                    status = "fallback"
                else:
                    status = "completed"

            payload = self._postprocess_context_processor_payload(
                processor_id=processor_id,
                payload=payload,
                metadata_en=metadata_en,
                scene_plan_index=scene_plan_index,
            )

            if "volume_id" not in payload:
                payload["volume_id"] = self.manifest.get("volume_id", self.work_dir.name)
            if "generated_at" not in payload:
                payload["generated_at"] = datetime.datetime.now().isoformat()
            if "processor_version" not in payload:
                payload["processor_version"] = "1.0"

            try:
                output_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                item_count = self._estimate_processor_items(processor_id, payload)
                results["processors"][processor_id] = {
                    "status": status,
                    "file": str(output_path.relative_to(self.work_dir)),
                    "items": item_count,
                    "used_grounding": bool(spec.get("tools")),
                }
                if language_retry_applied:
                    results["processors"][processor_id]["language_retry"] = "vn_strict"
                if status == "fallback" and fallback_reason:
                    results["processors"][processor_id]["fallback_reason"] = fallback_reason
                if status == "fallback" and debug_artifact:
                    results["processors"][processor_id]["debug_artifact"] = debug_artifact
                results["output_files"].append(str(output_path.relative_to(self.work_dir)))
                logger.info(
                    f"[P1.55] {processor_id}: {status} -> {output_path.name} ({item_count} items)"
                )
            except Exception as e:
                results["processors"][processor_id] = {
                    "status": "failed",
                    "error": str(e)[:240],
                    "file": str(output_path.relative_to(self.work_dir)),
                }
                results["status"] = "partial"
                logger.warning(f"[P1.55] Failed writing {output_path.name}: {e}")

        has_failure = any(v.get("status") == "failed" for v in results["processors"].values())
        has_fallback = any(v.get("status") == "fallback" for v in results["processors"].values())
        if has_failure:
            results["status"] = "partial"
        elif has_fallback:
            results["status"] = "fallback"
        return results

    def _mark_pipeline_state(
        self,
        *,
        status: str,
        cache_stats: Optional[Dict[str, Any]] = None,
        used_external_cache: bool = False,
        output_tokens: int = 0,
        patch_keys: Optional[List[str]] = None,
        error: Optional[str] = None,
        mode: str = "full",
        context_processor_stats: Optional[Dict[str, Any]] = None,
    ) -> None:
        pipeline_state = self.manifest.setdefault("pipeline_state", {})
        state = {
            "status": status,
            "timestamp": datetime.datetime.now().isoformat(),
            "model": self.MODEL_NAME,
            "temperature": self.TEMPERATURE,
            "target_language": self.target_language,
            "used_external_cache": used_external_cache,
            "output_tokens": output_tokens,
            "cache_stats": cache_stats or {},
            "patch_keys": patch_keys or [],
            "mode": mode,
        }
        if context_processor_stats:
            state["context_processors"] = context_processor_stats
        if error:
            state["error"] = error
        pipeline_state["rich_metadata_cache"] = state


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phase 1.55 rich metadata cache updater")
    parser.add_argument("--volume", type=str, required=True, help="Volume ID in WORK/")
    parser.add_argument(
        "--target-language",
        type=str,
        default="",
        help="Target language code override for metadata/context output (default: config target language)",
    )
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Build/verify full-LN cache path only (skip metadata enrichment merge).",
    )
    args = parser.parse_args()

    work_dir = WORK_DIR / args.volume
    if not work_dir.exists():
        logger.error(f"Volume directory not found: {work_dir}")
        sys.exit(1)

    updater = RichMetadataCacheUpdater(
        work_dir,
        target_language=(args.target_language or None),
        cache_only=args.cache_only,
    )
    success = updater.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

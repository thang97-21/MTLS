"""
Schema auto-update step for Phase 1.5.

This module fills Librarian-generated metadata_en schema placeholders
through a dedicated Gemini API call, then merges the patch into manifest.json.
"""

from __future__ import annotations

import datetime
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from google.genai import types

from pipeline.common.phase_llm_router import PhaseLLMRouter
from pipeline.config import PIPELINE_ROOT, get_phase_model, get_phase_generation_config

logger = logging.getLogger("SchemaAutoUpdate")


class SchemaAutoUpdater:
    """Auto-fill metadata_en schema fields using Gemini."""

    # Fallback model — real value resolved from translation.phase_models.1_5 in config.yaml
    MODEL_NAME = "gemini-2.5-flash"
    TEMPERATURE = 0.5
    MAX_OUTPUT_TOKENS = 32768

    # Keep context bounded for very large books.
    MAX_CONTEXT_CHAPTERS = 20
    MAX_CONTEXT_CHARS = 120000
    PER_CHAPTER_EXCERPT_CHARS = 6500
    EXCERPT_HEAD_CHARS = 4300
    EXCERPT_TAIL_CHARS = 1900

    # Translation fields are handled later by metadata processor.
    PROTECTED_TOP_LEVEL_FIELDS = {
        "title_en",
        "author_en",
        "illustrator_en",
        "publisher_en",
        "series_en",
        "character_names",
        "target_language",
        "language_code",
    }
    PROTECTED_CHAPTER_FIELDS = {"title_en", "title_vn"}
    # v4.0 unified schema contract: bible continuity + rich metadata.
    ALLOWED_PATCH_FIELDS = {
        "character_profiles",
        "localization_notes",
        "official_localization",
        "world_setting",
        "geography",
        "weapons_artifacts",
        "organizations",
        "cultural_terms",
        "culturally_loaded_terms",
        "mythology",
        "translation_rules",
        "dialogue_patterns",
        "scene_contexts",
        "emotional_pronoun_shifts",
        "translation_guidelines",
        "chapters",
        "schema_version",
        "author_signature_patterns",
        "signature_phrases",
        "character_voice_fingerprints",
    }

    def __init__(self, work_dir: Path):
        self.work_dir = work_dir
        self.manifest_path = work_dir / "manifest.json"
        self.schema_spec_path = PIPELINE_ROOT / "SCHEMA_V3.9_AGENT.md"
        # Resolve model from config.yaml (translation.phase_models.1_5) with class constant as fallback
        self.MODEL_NAME = get_phase_model("1.5", self.MODEL_NAME)
        self._phase_generation = get_phase_generation_config("1.5")
        self.TEMPERATURE = float(self._phase_generation.get("temperature", self.TEMPERATURE))
        self.MAX_OUTPUT_TOKENS = int(self._phase_generation.get("max_output_tokens", self.MAX_OUTPUT_TOKENS))
        self.client = PhaseLLMRouter().get_client(
            "1.5",
            model=self.MODEL_NAME,
            enable_caching=False,
        )

    def apply(self, manifest: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply schema auto-update patch to manifest in-memory.

        Returns:
            Dict with metadata about update process.
        """
        metadata = manifest.get("metadata", {})
        metadata_en = manifest.get("metadata_en", {})
        search_hint = self._detect_localized_series_hint(metadata)
        prompt = self._build_prompt(manifest, search_hint)
        system_instruction = self._build_system_instruction()
        # Always enable Google Search grounding — prioritize existing
        # media (anime/manga/publisher) canon over heuristic inference.
        tools = [types.Tool(google_search=types.GoogleSearch())]
        if search_hint.get("use_online_search"):
            logger.info(
                "Localized series hint detected (%s). Online search grounding active.",
                search_hint.get("localized_series_name", ""),
            )
        else:
            logger.info("Online search grounding active (always-on for media canon lookup).")

        response = self.client.generate(
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=self.TEMPERATURE,
            max_output_tokens=self.MAX_OUTPUT_TOKENS,
            generation_config=self._phase_generation,
            model=self.MODEL_NAME,
            tools=tools,
        )
        payload = self._parse_json_response(response.content)
        patch = payload.get("metadata_en_patch", payload)

        if not isinstance(patch, dict):
            raise ValueError("Schema auto-update response did not include a valid metadata_en patch object")

        patch = self._sanitize_patch(patch)
        manifest["metadata_en"] = self._deep_merge_dict(metadata_en, patch)

        # ── Provenance extraction ────────────────────────────────
        # Capture official_localization.sources from the LLM response
        # so we have a pipeline-level record of WHERE each canonical
        # term came from, independent of LLM compliance.
        provenance = self._extract_provenance(patch)

        self._mark_pipeline_state(
            manifest=manifest,
            status="completed",
            updated_keys=sorted(patch.keys()),
            output_tokens=response.output_tokens,
            online_search_used=bool(tools),
            localized_series_name=search_hint.get("localized_series_name"),
            provenance=provenance,
        )
        return {
            "status": "completed",
            "updated_keys": sorted(patch.keys()),
            "output_tokens": response.output_tokens,
            "online_search_used": bool(tools),
        }

    def mark_failed(self, manifest: Dict[str, Any], error: Exception) -> None:
        """Record failed schema update state without throwing away phase 1.5."""
        self._mark_pipeline_state(
            manifest=manifest,
            status="failed",
            error=str(error)[:500],
        )

    def _build_system_instruction(self) -> str:
        base = (
            "You are the Schema v4.0 Metadata Agent for an MTL light novel pipeline.\n"
            "Your job is to enrich metadata_en fields using extracted source data.\n"
            "Return JSON only. Do not output markdown or commentary.\n"
            "Use this output shape:\n"
            "{\n"
            '  "metadata_en_patch": {\n'
            '    "character_profiles": {...},\n'
            '    "localization_notes": {...},\n'
            '    "world_setting": {...},\n'
            '    "geography": {...},\n'
            '    "weapons_artifacts": {...},\n'
            '    "organizations": {...},\n'
            '    "cultural_terms": {...},\n'
            '    "culturally_loaded_terms": {...},\n'
            '    "mythology": {...},\n'
            '    "translation_rules": {...},\n'
            '    "dialogue_patterns": {...},\n'
            '    "scene_contexts": {...},\n'
            '    "emotional_pronoun_shifts": {...},\n'
            '    "translation_guidelines": {...},\n'
            '    "chapters": {...},\n'
            '    "schema_version": "v4.0",\n'
            '    "author_signature_patterns": {...},\n'
            '    "official_localization": {\n'
            '      "should_use_official": true,\n'
            '      "series_title_en": "string",\n'
            '      "volume_title_en": "string",\n'
            '      "author_en": "string",\n'
            '      "publisher_en": "string",\n'
            '      "confidence": "high|medium|low",\n'
            '      "sources": [{"title": "string", "url": "https://..."}]\n'
            "    }\n"
            "  }\n"
            "}\n"
            "Do not write translation fields such as title_en, author_en, chapter title_en, or character_names.\n"
            "Respect existing chapter ids and character profile keys when patching.\n\n"
            "BIBLE CONTINUITY REQUIREMENT:\n"
            "- Maintain schema-compatible continuity blocks when data is inferable:\n"
            "  world_setting, geography, weapons_artifacts, organizations, cultural_terms, mythology, translation_rules.\n"
            "- Preserve existing canon terms and avoid conflicting renames.\n\n"
            "PHASE 1.55 RICH METADATA COMPATIBILITY:\n"
            "- Support dialogue_patterns, scene_contexts, emotional_pronoun_shifts, and translation_guidelines.\n"
            "- Keep these structures JSON-safe and prompt-friendly.\n\n"
            "CHARACTER VISUAL IDENTITY REQUIREMENT:\n"
            "- For each character_profiles entry, include/maintain `visual_identity_non_color`.\n"
            "- Use non-color traits only: hairstyle, clothing silhouette/signature, expression baseline,\n"
            "  posture/gesture signature, accessories, and concise identity summary.\n"
            "- Include `visual_identity_non_color.habitual_gestures` as structured entries when evidence exists.\n"
            "  Entry schema: {gesture, trigger, intensity, narrative_effect, evidence_chapters, confidence}.\n"
            "- Do NOT infer or invent habitual gestures without source evidence.\n"
            "- Do NOT rely on hair/eye/clothing color as primary identity markers.\n\n"
            "CRITICAL: JAPANESE NAME FURIGANA AUTHORITY (TIER 0 - ABSOLUTE):\n"
            "- When the source text contains ruby/furigana annotations like 名前《なまえ》, 藤崎{とうざき}徹{とおる}, or 伊達{いだち}一夏{いちか}, the furigana reading is the ABSOLUTE AUTHORITATIVE pronunciation.\n"
            "- The furigana reading ALWAYS takes priority over external grounding sources (official localization, AniDB, MyAnimeList, fan translations).\n"
            "- Example: If JP source has 藤崎{とうざき}徹{とおる}, you MUST output 'Touzaki Toru' even if AniDB says 'Fujisaki Toru'.\n"
            "- Example: If JP source has 伊達{いだち}, you MUST output 'Idachi' even if the kanji 伊達 normally reads as 'Date'.\n"
            "- This applies to ALL 3 ruby styles:\n"
            "    1. NAROU style: 名前《なまえ》→ Name\n"
            "    2. INTERWEAVE style: 名前《な》ま《え》→ Na-may (compound words)\n"
            "    3. LN/KIRA-KIRA style: 名前《ナマエ》→ Namae (katakana for stylized characters)\n"
            "- The author's ruby annotation in the source text is the canonical pronunciation - never override with standard dictionary readings.\n"
            "- Only use external grounding when NO furigana exists in the source.\n\n"
            "GROUNDING DIRECTIVE (ALWAYS ACTIVE):\n"
            "- ALWAYS use Google Search to ground your metadata enrichment.\n"
            "- Apply BOTH priority hierarchies below when sources conflict.\n"
            "- HIERARCHY A (Series/Volume localization grounding):\n"
            "  1) Official Localization (licensed publisher / official release metadata)\n"
            "  2) AniDB (public API-backed catalog entries)\n"
            "  3) MyAnimeList\n"
            "  4) Ranobe-Mori (https://ranobe-mori.net/, Japanese source)\n"
            "  5) Fan Translation consensus\n"
            "  6) Heuristic Inference (LAST RESORT)\n"
            "- HIERARCHY B (Character/Term canonical grounding):\n"
            "  1) Official Localization (licensed character/term spellings)\n"
            "  2) AniDB (public API-backed canonical names)\n"
            "  3) MyAnimeList\n"
            "  4) Ranobe-Mori (https://ranobe-mori.net/, Japanese source)\n"
            "  5) Fan Translation consensus\n"
            "  6) Heuristic Inference (LAST RESORT)\n"
            "- Official localization data from licensed publishers ALWAYS overrides romanization/inference.\n"
            "- For character names: prefer the official English release spelling over Hepburn or phonetic guesses.\n"
            "- NAME ORDER ENFORCEMENT (MANDATORY): apply `name_order_grounding_policy` from INPUT.\n"
            "- Keep canonical spelling from sources, but normalize display order to policy (do not mirror source order blindly).\n"
            "- For setting/place names: prefer canon from anime subtitles or official manga translations.\n"
            "- If no official localization exists, fall back to established fan-translation consensus before heuristic methods.\n"
            "- Populate official_localization block with sources and confidence when official data is found.\n"
            "- Set official_localization.should_use_official=true when confidence is medium or high."
        )

        # ── ECR: Culturally Loaded Terms block ──────────────────────────────
        base += (
            "\n\nCULTURALLY LOADED TERMS (ECR — COMPONENT 1):\n"
            "Populate metadata_en_patch.culturally_loaded_terms when EITHER:\n"
            "  (a) world_setting.type contains 'japan' (case-insensitive), OR\n"
            "  (b) the series is isekai/fantasy but characters or cultural elements originate from\n"
            "      modern Japan (e.g. 'isekai_fantasy_with_modern_japan_elements', isekai yandere,\n"
            "      transferred high school student, shrine maiden summoner, etc.)\n"
            "Otherwise leave the field absent or empty.\n\n"
            "Output ECR terms ONLY in 'culturally_loaded_terms'. NEVER add retention_policy to\n"
            "the 'cultural_terms' glossary — that field is for world-building entries only.\n\n"
            "Scan source text for JP cultural concepts recognized in the EN LN/anime community:\n"
            "  personality_archetype: \u5927\u548c\u6491\u5b50, \u30c4\u30f3\u30c7\u30ec, \u30af\u30fc\u30c7\u30ec, \u30e4\u30f3\u30c7\u30ec, \u30c0\u30f3\u30c7\u30ec\n"
            "  social_archetype: \u30ae\u30e3\u30eb, \u30e4\u30f3\u30ad\u30fc, \u30aa\u30bf\u30af, \u4e2d\u4e8c\u75c5, \u30ea\u30a2\u5145, \u5f15\u304d\u3053\u3082\u308a\n"
            "  beauty_descriptor: \u7f8e\u5c11\u5973, \u7f8e\u4eba, \u30a4\u30b1\u30e1\u30f3, \u30e1\u30ac\u30cd\n"
            "  food_culture: \u3044\u305f\u3060\u304d\u307e\u3059, \u3054\u3061\u305d\u3046\u3055\u307e, \u5f01\u5f53, \u304a\u306b\u304e\u308a\n"
            "  location_type: \u65c5\u9928, \u9322\u6e6f, \u5c45\u9152\u5c4b, \u30b3\u30f3\u30d3\u30cb\n"
            "  social_protocol: \u6566\u8a9e (as concept), \u5efa\u524d/\u672c\u97f3, \u5148\u8f29/\u5f8c\u8f29 (as relationship dynamics)\n\n"
            "For each term, set retention_policy:\n"
            "  'preserve_jp'           → widely known in EN LN/anime community; NEVER substitute\n"
            "  'preserve_jp_first_use' → semi-known; JP on first use with inline gloss, then short form\n"
            "  'context_dependent'     → obscure; JP when used as label/archetype, EN when descriptive\n"
            "  'transcreate'           → always EN; JP informational only\n\n"
            "Output schema per term:\n"
            '  {\n'
            '    "canonical_jp": "\u5927\u548c\u6491\u5b50",\n'
            '    "romaji": "Yamato Nadeshiko",\n'
            '    "retention_policy": "preserve_jp",\n'
            '    "category": "personality_archetype",\n'
            '    "usage_context": "ideal of Japanese femininity",\n'
            '    "notes": ""\n'
            '  }\n'
        )

        # ── Component 2: Author Signature Patterns block ─────────────────────
        base += (
            "\n\nAUTHOR SIGNATURE PATTERNS (COMPONENT 2 — JP-NATIVE GROUNDING):\n"
            "Populate metadata_en_patch.author_signature_patterns using the opf_metadata fields\n"
            "provided in the INPUT payload (author_jp, imprint_jp, publisher_jp, dc_title_jp).\n\n"
            "Grounding steps:\n"
            "  Step 1: Search '[author_jp] [imprint_jp] \u4f5c\u54c1\u4e00\u89a7' (JP query) for bibliography\n"
            "  Step 2: Search '[author_jp] \u6587\u4f53 \u7279\u5fb4 \u4f5c\u98a8 [imprint_jp]' for style documentation\n"
            "  Step 3: Search '[author_jp] [dc_title_jp] \u30ec\u30d3\u30e5\u30fc \u611f\u60f3' for reader reviews\n"
            "  Step 4: Analyze source text for structural prose patterns\n"
            "  Step 5: For literary references: search '[reference_jp] \u672c \u8457\u8005' in JP form\n\n"
            "Output schema:\n"
            '  {\n'
            '    "author_name_jp": "string (from opf_metadata.author_jp)",\n'
            '    "author_name_en": "string (romanized)",\n'
            '    "grounding_sources": ["url1", "url2"],\n'
            '    "detected_patterns": [\n'
            '      {\n'
            '        "pattern_id": "reversal_NO",\n'
            '        "jp_structure": "[\u8a69\u7684\u6bd4\u55a9]\u3002\u3044\u3084\u3002[\u8d77\u843d\u3068\u3057]",\n'
            '        "en_structure": "[Poetic metaphor]? NO. [Comedic deflation].",\n'
            '        "preservation_rule": "NO. MUST be standalone paragraph. Never soften.",\n'
            '        "frequency": "high|medium|low",\n'
            '        "evidence_excerpts": ["string"]\n'
            '      }\n'
            '    ],\n'
            '    "literary_references": [\n'
            '      {\n'
            '        "ref_jp": "string",\n'
            '        "ref_en": "string",\n'
            '        "author_en": "string",\n'
            '        "handling": "preserve exact name | contextualize | localize"\n'
            '      }\n'
            '    ]\n'
            '  }\n'
            "ALL field values in author_signature_patterns MUST be in English, "
            "except author_name_jp, jp_structure, ref_jp which keep Japanese.\n"
            "Leave author_signature_patterns empty ({}) if source does not have enough evidence.\n"
        )
        if not self.schema_spec_path.exists():
            return base

        try:
            schema_spec = self.schema_spec_path.read_text(encoding="utf-8")
            return f"{base}\n\nReference spec:\n{schema_spec}"
        except Exception as e:
            logger.warning(f"Could not read schema spec file: {e}")
            return base

    def _build_prompt(self, manifest: Dict[str, Any], search_hint: Dict[str, Any]) -> str:
        metadata = manifest.get("metadata", {})
        metadata_en = manifest.get("metadata_en", {})
        chapter_entries = manifest.get("chapters", [])
        name_order_policy = self._resolve_name_order_policy(manifest)

        chapter_outline = [
            {
                "id": ch.get("id", ""),
                "title": ch.get("title", ""),
                "source_file": ch.get("source_file", ""),
                "word_count": ch.get("word_count", 0),
            }
            for ch in chapter_entries
        ]

        snippets = self._collect_chapter_snippets(chapter_entries)
        payload = {
            "metadata": metadata,
            "metadata_en_seed": metadata_en,
            "ruby_names": manifest.get("ruby_names", []),
            "chapter_outline": chapter_outline,
            "chapter_snippets": snippets,
            "localized_series_hint": search_hint,
            "name_order_grounding_policy": name_order_policy,
            "opf_metadata": manifest.get("opf_metadata", {}),
        }

        prompt = (
            "Generate metadata_en_patch for schema auto-update.\n"
            "Requirements:\n"
            "- Fill [TO BE FILLED] and weak placeholder values with concrete data where possible.\n"
            "- Add PAIR_ID-compatible relationship structures when inferable.\n"
            "- Keep metadata compatible with Bible categories: world_setting, geography, weapons_artifacts, organizations, cultural_terms, mythology, translation_rules.\n"
            "- Keep metadata compatible with rich semantic categories: dialogue_patterns, scene_contexts, emotional_pronoun_shifts, translation_guidelines.\n"
            "- Keep unknown values empty rather than hallucinating.\n"
            "- Keep chapter ids unchanged.\n"
            "- Add `character_profiles.*.visual_identity_non_color` using non-color descriptors "
            "(hairstyle, outfit silhouette, expression signature, posture, accessories).\n"
            "- Add `character_profiles.*.visual_identity_non_color.habitual_gestures` when recurring gestures are evidenced.\n"
            "- Use habitual_gestures entry shape: {gesture, trigger, intensity, narrative_effect, evidence_chapters, confidence}.\n"
            "- Never add habitual gestures unless supported by explicit source evidence.\n"
            "- If localized_series_hint.use_online_search=true, use online search and adopt official localization metadata.\n"
            "- Enforce name_order_grounding_policy for all grounded person names (official or fan sources).\n"
            "- If world_setting.type contains 'japan' or world signals are contemporary Japan, "
            "populate culturally_loaded_terms with retention_policy per term (see system instruction).\n"
            "  Also populate culturally_loaded_terms when the series has isekai elements where characters "
            "or cultural artifacts originate from Japan (e.g. isekai_fantasy_with_modern_japan_elements, "
            "isekai_romcom, modern_jp_high_school_isekai) — archetype terms like ヤンデレ, 巫女, 幼馴染 "
            "must appear in culturally_loaded_terms even when the primary world is fantasy.\n"
            "  CRITICAL: Output ECR terms ONLY in the 'culturally_loaded_terms' key. "
            "Do NOT add 'retention_policy' to entries inside 'cultural_terms' — that field is for "
            "world-building glossary only and has no ECR keys.\n"
            "- Use opf_metadata.author_jp and opf_metadata.imprint_jp for JP-native author grounding "
            "(search in Japanese). Populate author_signature_patterns when evidence is found.\n"
            "- Output valid JSON only.\n\n"
            f"INPUT:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )
        # Always append search grounding block — use detected hint or build from metadata
        query = search_hint.get("search_query", "")
        if not query:
            title = metadata.get("title", "")
            author = metadata.get("author", "")
            query = f"{title} {author} light novel official English".strip()
        prompt += (
            "\n\nGrounding & media canon lookup (ALWAYS ACTIVE):\n"
            f"- Search query: {query}\n"
            "- Also search: <series_name> anime, <series_name> manga, <series_name> light novel English\n"
            "- MEDIA PRIORITY (CRITICAL): Light Novel official localization must take precedence over manga/anime localizations.\n"
            "  Different publishers may localize different media; for this pipeline, treat LN as canonical target medium.\n"
            "- Source priority HIERARCHY A (Series/Volume): Official Localization -> AniDB (public API) -> MyAnimeList -> Ranobe-Mori (JP) -> Fan Translation -> Heuristic Inference.\n"
            "- Source priority HIERARCHY B (Character/Term): Official Localization -> AniDB (public API) -> MyAnimeList -> Ranobe-Mori (JP) -> Fan Translation -> Heuristic Inference.\n"
            "- Prefer publisher listings (Yen Press, Seven Seas, J-Novel Club), official license pages,\n"
            "  then AniDB, MyAnimeList, and Ranobe-Mori before fan translation references.\n"
            f"- NAME ORDER LOCK: {name_order_policy['default']} ({name_order_policy['label']}).\n"
            f"- Name-order policy: {name_order_policy['policy']}.\n"
            "- Regardless of source style, preserve canonical spelling but normalize person-name order to this policy.\n"
            "- Adopt official character name spellings, place names, and terminology from existing media canon.\n"
            "- Populate metadata_en_patch.official_localization from official sources.\n"
            "- Set should_use_official=true when confidence is medium/high.\n"
            "- In official_localization.sources[], include source-level media_type when inferable: light_novel | manga | anime | unknown.\n"
        )
        return prompt

    def _resolve_name_order_policy(self, manifest: Dict[str, Any]) -> Dict[str, str]:
        """
        Resolve the canonical name-order policy used to normalize grounded metadata.

        Priority:
        1) metadata_en.world_setting.name_order.default
        2) world-setting inference (Japan -> family_given)
        3) fallback given_family
        """
        metadata = manifest.get("metadata", {}) if isinstance(manifest, dict) else {}
        metadata_en = manifest.get("metadata_en", {}) if isinstance(manifest, dict) else {}

        world_setting = metadata_en.get("world_setting", {})
        if not isinstance(world_setting, dict):
            world_setting = {}

        name_order = world_setting.get("name_order", {})
        if not isinstance(name_order, dict):
            name_order = {}

        default_order = str(name_order.get("default", "")).strip().lower()
        policy_text = str(name_order.get("policy", "")).strip()
        policy_source = "metadata_en.world_setting.name_order.default"

        if default_order not in {"family_given", "given_family"}:
            ws_type = str(world_setting.get("type", "")).lower()
            ws_label = str(world_setting.get("label", "")).lower()
            source_lang = str(metadata.get("source_language", "")).lower()
            japan_like = (
                "japan" in ws_type
                or "japan" in ws_label
                or "japanese" in ws_type
                or "japanese" in ws_label
                or source_lang == "ja"
            )
            if japan_like:
                default_order = "family_given"
                policy_source = "world_setting_inference:japan"
            else:
                default_order = "given_family"
                policy_source = "fallback_default"

        if not policy_text:
            if default_order == "family_given":
                policy_text = (
                    "Use Family Given order for Japanese names by default; preserve canonical spelling. "
                    "Use Given Family only for explicit non-Japanese exceptions."
                )
            else:
                policy_text = (
                    "Use Given Family order by default; preserve canonical spelling. "
                    "Use Family Given only for explicit Japanese-style exceptions."
                )

        label = (
            "Family-Given (Japanese surname-first order)"
            if default_order == "family_given"
            else "Given-Family (Western first-name order)"
        )

        return {
            "default": default_order,
            "label": label,
            "policy": policy_text,
            "source": policy_source,
        }

    def _detect_localized_series_hint(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Detect whether metadata indicates an existing localized series name.

        Examples:
        - "Madan no Ou to Vanadis (Lord Marksman and Vanadis)"
        - Series/title fields containing both JP and Latin-script aliases.
        """
        series = str(metadata.get("series", "") or "").strip()
        title = str(metadata.get("title", "") or "").strip()
        author = str(metadata.get("author", "") or "").strip()

        candidates = [series, title]
        localized = ""
        for candidate in candidates:
            if not candidate:
                continue
            m = re.search(r"\(([^)]*[A-Za-z][^)]*)\)", candidate)
            if m:
                localized = m.group(1).strip()
                break
            # Fallback: any Latin-script heavy segment without parentheses.
            latin_chunks = re.findall(r"[A-Za-z][A-Za-z0-9 '&:,-]{3,}", candidate)
            if latin_chunks:
                localized = max(latin_chunks, key=len).strip()
                break

        use_online_search = bool(localized)
        search_title = localized or series or title
        query = " ".join(part for part in [search_title, author, "official English localization"] if part).strip()

        return {
            "use_online_search": use_online_search,
            "localized_series_name": localized,
            "search_query": query,
        }

    def _collect_chapter_snippets(self, chapter_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        snippets: List[Dict[str, Any]] = []
        if not chapter_entries:
            return snippets

        total_chars = 0
        for idx in self._select_spread_indices(len(chapter_entries), self.MAX_CONTEXT_CHAPTERS):
            chapter = chapter_entries[idx]
            source_file = chapter.get("source_file", "")
            if not source_file:
                continue

            chapter_path = self.work_dir / "JP" / source_file
            if not chapter_path.exists():
                continue

            try:
                text = chapter_path.read_text(encoding="utf-8", errors="ignore").strip()
            except Exception:
                continue

            excerpt = self._make_excerpt(text)
            if not excerpt:
                continue

            remaining = self.MAX_CONTEXT_CHARS - total_chars
            if remaining <= 512:
                break
            if len(excerpt) > remaining:
                excerpt = excerpt[: max(0, remaining - 24)] + "\n[...truncated...]"

            snippets.append(
                {
                    "id": chapter.get("id", ""),
                    "title": chapter.get("title", ""),
                    "source_file": source_file,
                    "excerpt": excerpt,
                    "full_length_chars": len(text),
                }
            )
            total_chars += len(excerpt)

        return snippets

    def _make_excerpt(self, text: str) -> str:
        if len(text) <= self.PER_CHAPTER_EXCERPT_CHARS:
            return text
        head = text[: self.EXCERPT_HEAD_CHARS]
        tail = text[-self.EXCERPT_TAIL_CHARS :]
        omitted = max(0, len(text) - len(head) - len(tail))
        return f"{head}\n\n[... {omitted} chars omitted ...]\n\n{tail}"

    def _select_spread_indices(self, total: int, limit: int) -> List[int]:
        if total <= limit:
            return list(range(total))
        if limit <= 1:
            return [0]
        return sorted({round(i * (total - 1) / (limit - 1)) for i in range(limit)})

    def _parse_json_response(self, content: str) -> Dict[str, Any]:
        text = content.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(text[start : end + 1])
            raise

    def _sanitize_patch(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        cleaned = {
            key: value
            for key, value in patch.items()
            if key in self.ALLOWED_PATCH_FIELDS
        }
        for field in self.PROTECTED_TOP_LEVEL_FIELDS:
            cleaned.pop(field, None)

        chapters = cleaned.get("chapters")
        if isinstance(chapters, dict):
            for chapter_id, chapter_data in chapters.items():
                if not isinstance(chapter_data, dict):
                    continue
                for protected in self.PROTECTED_CHAPTER_FIELDS:
                    chapter_data.pop(protected, None)
                chapters[chapter_id] = chapter_data

        return cleaned

    def _deep_merge_dict(self, base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(base)
        for key, patch_value in patch.items():
            base_value = merged.get(key)
            if isinstance(base_value, dict) and isinstance(patch_value, dict):
                merged[key] = self._deep_merge_dict(base_value, patch_value)
            else:
                merged[key] = patch_value
        return merged

    def _extract_provenance(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        """Extract provenance metadata from the schema patch.

        Captures official_localization.sources and per-field attribution
        so we have a pipeline-level audit trail of WHERE each canonical
        value came from (publisher site, anime DB, wiki, etc.).
        """
        provenance: Dict[str, Any] = {
            "has_official_localization": False,
            "confidence": None,
            "sources": [],
            "field_origins": {},
        }

        official = patch.get("official_localization", {})
        if not isinstance(official, dict):
            return provenance

        provenance["has_official_localization"] = official.get(
            "should_use_official", False
        )
        provenance["confidence"] = official.get("confidence")

        sources = official.get("sources", [])
        if isinstance(sources, list):
            provenance["sources"] = [
                {"title": s.get("title", ""), "url": s.get("url", "")}
                for s in sources
                if isinstance(s, dict)
            ]

        # Map which top-level fields the LLM populated
        for key in ["series_title_en", "volume_title_en", "author_en", "publisher_en"]:
            val = official.get(key)
            if val and isinstance(val, str) and val.strip():
                provenance["field_origins"][key] = {
                    "value": val,
                    "source": "official_localization",
                    "confidence": provenance["confidence"],
                }

        if provenance["sources"]:
            logger.info(
                f"\u2713 Provenance captured: {len(provenance['sources'])} source(s), "
                f"confidence={provenance['confidence']}"
            )
        else:
            logger.info("\u26a0 No grounding sources returned by LLM — provenance not available")

        return provenance

    def _mark_pipeline_state(
        self,
        manifest: Dict[str, Any],
        status: str,
        updated_keys: List[str] | None = None,
        output_tokens: int | None = None,
        error: str | None = None,
        online_search_used: bool = False,
        localized_series_name: str | None = None,
        provenance: Dict[str, Any] | None = None,
    ) -> None:
        pipeline_state = manifest.setdefault("pipeline_state", {})
        schema_state: Dict[str, Any] = {
            "status": status,
            "timestamp": datetime.datetime.now().isoformat(),
            "model": self.MODEL_NAME,
            "temperature": self.TEMPERATURE,
            "max_output_tokens": self.MAX_OUTPUT_TOKENS,
            "online_search_used": online_search_used,
        }
        if localized_series_name:
            schema_state["localized_series_name"] = localized_series_name
        if updated_keys:
            schema_state["updated_keys"] = updated_keys
        if output_tokens is not None:
            schema_state["output_tokens"] = output_tokens
        if error:
            schema_state["error"] = error
        if provenance:
            schema_state["provenance"] = provenance
        pipeline_state["schema_agent"] = schema_state

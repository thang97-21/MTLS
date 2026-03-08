"""
Scene Planning Agent (v1.6 Stage 1).

Generates a structured scene plan from Japanese chapter text before translation.
"""

from __future__ import annotations

import json
import logging
import re
import time
from difflib import SequenceMatcher
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from pipeline.common.gemini_client import GeminiClient
from pipeline.common.phase_llm_router import PhaseLLMRouter
from pipeline.common.name_order_normalizer import normalize_payload_names
from pipeline.config import PIPELINE_ROOT, get_phase_generation_config

logger = logging.getLogger(__name__)
_PHASE_1_7_GEN = get_phase_generation_config("1.7")


class ScenePlanningError(Exception):
    """Base exception for scene planning failures."""


@dataclass
class SceneBeat:
    """A narrative beat identified by Stage 1."""

    id: str
    beat_type: str
    emotional_arc: str
    dialogue_register: str
    target_rhythm: str
    illustration_anchor: bool = False
    start_paragraph: Optional[int] = None
    end_paragraph: Optional[int] = None
    # Culture bleed risk annotation (optional — populated by planner when JP-specific
    # phrases are detected that LLMs commonly mistranslate by scene-feel substitution)
    culture_bleed_risk: Optional[str] = None          # "high" | "medium" | "low" | None
    culture_bleed_category: Optional[str] = None      # see CULTURE_BLEED_CATEGORIES
    culture_bleed_source_phrase: Optional[str] = None # the JP phrase triggering the flag
    culture_bleed_warning: Optional[str] = None       # inline warning injected into Stage 2
    culture_bleed_forbidden: Optional[List[str]] = None  # forbidden EN substitutions
    # Scene-level Emotional Pronoun Shift (EPS) tension band
    eps_band: Optional[str] = None                    # "HOT" | "WARM" | "NEUTRAL" | "COOL" | "COLD"


@dataclass
class CharacterProfile:
    """Chapter-local profile for character speech and emotion."""

    name: str
    emotional_state: str
    sentence_bias: str
    victory_patterns: List[str]
    denial_patterns: List[str]
    relationship_dynamic: str


@dataclass
class POVSegment:
    """Narrator ownership metadata for a contiguous POV span."""

    character: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    description: str = ""


@dataclass
class ScenePlan:
    """Narrative scaffold output for a chapter."""

    chapter_id: str
    scenes: List[SceneBeat]
    pov_tracking: List[POVSegment]
    character_profiles: Dict[str, CharacterProfile]
    overall_tone: str
    pacing_strategy: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert dataclass plan to JSON-serializable dict."""
        def _scene_to_dict(scene: "SceneBeat") -> Dict[str, Any]:
            d = asdict(scene)
            # Omit None culture bleed fields to keep JSON compact for unaffected scenes
            for key in (
                "culture_bleed_risk", "culture_bleed_category",
                "culture_bleed_source_phrase", "culture_bleed_warning",
                "culture_bleed_forbidden", "eps_band",
            ):
                if d.get(key) is None:
                    d.pop(key, None)
            return d

        return {
            "chapter_id": self.chapter_id,
            "scenes": [_scene_to_dict(scene) for scene in self.scenes],
            "pov_tracking": [asdict(segment) for segment in self.pov_tracking],
            "character_profiles": {
                name: asdict(profile)
                for name, profile in self.character_profiles.items()
            },
            "overall_tone": self.overall_tone,
            "pacing_strategy": self.pacing_strategy,
        }


class ScenePlanningAgent:
    """
    Stage 1 planner that creates scene/character rhythm scaffolds.

    Input:
      - chapter_id
      - Japanese chapter text
    Output:
      - ScenePlan dataclass
    """

    def __init__(
        self,
        gemini_client: Optional[GeminiClient] = None,
        config_path: Optional[Path] = None,
        model: str = "gemini-2.5-flash",
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
    ):
        self.config_path = config_path or (PIPELINE_ROOT / "config" / "planning_config.json")
        self.config = self._load_config(self.config_path)
        self.allowed_beat_types = self._extract_allowed_beat_types(self.config)
        self.allowed_registers = self._extract_allowed_registers(self.config)
        self.rhythm_targets = self._extract_rhythm_targets(self.config)
        self.default_rhythm = self._extract_default_rhythm(self.config)
        self._rhythm_levels = self._build_rhythm_levels()

        self.model = model
        self.temperature = float(_PHASE_1_7_GEN.get("temperature", 0.3) if temperature is None else temperature)
        self.max_output_tokens = int(
            _PHASE_1_7_GEN.get("max_output_tokens", 65535) if max_output_tokens is None else max_output_tokens
        )
        self.empty_response_retries = max(0, int(self.config.get("empty_response_retries", 2)))
        self.empty_retry_backoff_seconds = max(0.0, float(self.config.get("empty_retry_backoff_seconds", 1.5)))
        self.enable_safety_sanitized_retry = bool(self.config.get("enable_safety_sanitized_retry", True))
        self.gemini = gemini_client or PhaseLLMRouter().get_client(
            "1.7",
            model=model,
            enable_caching=False,
        )
        self.planning_prompt = self._build_planning_prompt()

    @staticmethod
    def _extract_allowed_beat_types(config: Dict[str, Any]) -> List[str]:
        beat_types = config.get("beat_types", {})
        if isinstance(beat_types, dict):
            return [str(k) for k in beat_types.keys()]
        if isinstance(beat_types, list):
            return [str(v) for v in beat_types]
        return ["setup", "escalation", "punchline", "pivot", "illustration_anchor"]

    @staticmethod
    def _extract_allowed_registers(config: Dict[str, Any]) -> List[str]:
        registers = config.get("dialogue_registers", {})
        if isinstance(registers, dict):
            return [str(k) for k in registers.keys()]
        if isinstance(registers, list):
            return [str(v) for v in registers]
        return []

    @staticmethod
    def _extract_rhythm_targets(config: Dict[str, Any]) -> Dict[str, str]:
        rhythm_targets = config.get("rhythm_targets", {})
        if not isinstance(rhythm_targets, dict):
            return {}
        extracted: Dict[str, str] = {}
        for raw_key, raw_val in rhythm_targets.items():
            key = str(raw_key).strip()
            if not key:
                continue
            if isinstance(raw_val, dict):
                extracted[key] = str(raw_val.get("word_range", "")).strip()
            elif isinstance(raw_val, str):
                extracted[key] = raw_val.strip()
        return extracted

    @staticmethod
    def _extract_default_rhythm(config: Dict[str, Any]) -> str:
        rhythm_targets = config.get("rhythm_targets", {})
        if isinstance(rhythm_targets, dict) and rhythm_targets:
            first_key = str(next(iter(rhythm_targets.keys()))).strip()
            if first_key:
                return first_key
        return "medium_casual"

    @staticmethod
    def _load_config(config_path: Path) -> Dict[str, Any]:
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        logger.warning(f"Planning config not found at {config_path}; using defaults.")
        return {
            "beat_types": ["setup", "escalation", "punchline", "pivot", "illustration_anchor"],
            "dialogue_registers": {},
            "rhythm_targets": {},
        }

    def _build_planning_prompt(self) -> str:
        beat_types = ", ".join(self.allowed_beat_types) if self.allowed_beat_types else "setup, escalation, punchline, pivot"
        if self.allowed_registers:
            register_hint = ", ".join(self.allowed_registers[:12])
        else:
            register_hint = "casual_teen, flustered_defense, smug_teasing, formal_request"
        if self.rhythm_targets:
            rhythm_hint = ", ".join(list(self.rhythm_targets.keys())[:12])
        else:
            rhythm_hint = "short_fragments, medium_casual, long_confession"
        return (
            "# SCENE PLANNING DIRECTIVE\n\n"
            "You are a narrative structure analyst for Japanese light novels.\n"
            "DO NOT translate text.\n"
            "Output one JSON object only.\n\n"
            "Required top-level keys:\n"
            "- chapter_id (string)\n"
            "- scenes (array)\n"
            "- pov_tracking (array)\n"
            "- character_profiles (object)\n"
            "- overall_tone (string)\n"
            "- pacing_strategy (string)\n\n"
            "POV tracking keys:\n"
            "- character (string — ALWAYS use the EXACT canonical name from the CHARACTER NAME CANONICAL REFERENCE block above; never generic labels like \"Narrator\" or \"Protagonist\"; never append family/last names)\n"
            "- start_line (integer)\n"
            "- end_line (integer or null)\n"
            "- description (string)\n"
            "- ALWAYS include pov_tracking even for single-narrator chapters\n"
            "- For single-narrator chapters, emit one entry covering the whole chapter\n"
            "- For multi-narrator chapters, emit one entry per narrator segment in reading order\n"
            "- Infer POV from narrative ownership and surrounding context first: whose internal thoughts, perceptions, interpretations, blind spots, and emotional filtering control the prose\n"
            "- Use JP pronouns only as a weak supporting clue, never the sole criterion\n"
            "- Stronger POV evidence includes interior monologue, knowledge asymmetry, private reactions, remembered motives, and narration that stays inside one character's sensory/cognitive frame across nearby paragraphs\n"
            "- If the chapter opens before the POV character is explicitly named, still infer the most likely POV from surrounding context and use that canonical name\n"
            "- In description, use neutral labels such as \"POV character for chapter opening\" or \"POV shifts after confrontation\"; do not label someone \"the protagonist\" unless the source explicitly establishes that role\n\n"
            "Scene item keys:\n"
            "- id (string)\n"
            f"- beat_type (one of: {beat_types})\n"
            "- emotional_arc (string)\n"
            f"- dialogue_register (suggested set: {register_hint})\n"
            f"- target_rhythm (one of: {rhythm_hint})\n"
            "- illustration_anchor (boolean)\n"
            "- consistency rule: if beat_type is 'illustration_anchor', illustration_anchor must be true\n"
            "- start_paragraph (integer or null)\n"
            "- end_paragraph (integer or null)\n"
            "- eps_band (string: \"HOT\" | \"WARM\" | \"NEUTRAL\" | \"COOL\" | \"COLD\") — the scene's emotional proximity/tension band.\n"
            "  * HOT = anger, panic, high-tension confrontation, active flustered tsundere, comedy climax\n"
            "  * WARM = tenderness, intimacy, growing connection, vulnerability\n"
            "  * NEUTRAL = standard narrative, exposition, casual conversation\n"
            "  * COOL = detachment, observation, analytical, formal distance\n"
            "  * COLD = trauma, dissociation, comedic rock-bottom despair, complete disconnect\n"
            "- culture_bleed_risk (string: \"high\" | \"medium\" | \"low\" | omit if none)\n"
            "- culture_bleed_category (string: one of farewell_greeting_formula | school_hierarchy_vocab | gendered_speech_register | otaku_attribute_vocab | emotional_beat_substitution | omit if none)\n"
            "- culture_bleed_source_phrase (string: the exact JP phrase triggering the flag, omit if none)\n"
            "- culture_bleed_warning (string: concise EN warning for the Stage 2 translator, omit if none)\n"
            "- culture_bleed_forbidden (array of strings: EN phrasings the translator must NOT use, omit if none)\n\n"
            "Culture bleed annotation rules:\n"
            "Flag a scene if it contains JP-specific phrases that English LLMs commonly mistranslate\n"
            "by substituting emotional scene-feel instead of the phrase's actual meaning.\n"
            "Categories and examples:\n"
            "  farewell_greeting_formula: よろしくね (mutual welcome, NOT 'welcome home'), お邪魔します\n"
            "    (polite entry greeting, NOT 'sorry to intrude'), おかえり/ただいま (homecoming pair),\n"
            "    お疲れ様 (effort acknowledgment, NOT generic 'thank you')\n"
            "  school_hierarchy_vocab: 一軍/二軍 (first/second squad social rank, NOT 'A-list'),\n"
            "    陽キャ (outgoing type, NOT 'popular kid'), 陰キャ (introverted type, NOT 'nerd/loser'),\n"
            "    一軍女子 (top-tier social rank, NOT 'queen bee' or 'A-list girl')\n"
            "  gendered_speech_register: gruff older male patterns (だかなんだか知らんが, 〜せんぞ, 知らんが)\n"
            "    where Anglo slang injection (rhyming dismissals, Yiddish-origin expressions) would be wrong\n"
            "  otaku_attribute_vocab: 属性 in social context (character attribute tag, NOT 'label'/'backstory'),\n"
            "    キャラ, ポジション used as social role descriptors\n"
            "  emotional_beat_substitution: any high-stakes closing exchange where the scene feel strongly\n"
            "    pulls toward a different phrase than the source (e.g. よろしく in a homecoming-feeling scene)\n"
            "Only flag when the risk is genuine. Omit all culture_bleed_* keys for clean scenes.\n"
            "culture_bleed_warning must be a single concise sentence for the translator, not an essay.\n\n"
            "Character profile keys:\n"
            "- name, emotional_state, sentence_bias, relationship_dynamic (string)\n"
            "- victory_patterns, denial_patterns (array of strings)\n\n"
            "Safety style constraints (MANDATORY):\n"
            "- Describe scenes in neutral narrative terms.\n"
            "- Do NOT mention character ages or age-like labels.\n"
            "- Do NOT use strong sexualized descriptors or explicit sexual wording.\n"
            "- If intimacy is relevant, describe emotional tension and proximity non-explicitly.\n\n"
            "Keep output compact and actionable."
        )

    @staticmethod
    def _split_paragraphs(text: str) -> List[str]:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        return paragraphs if paragraphs else [text.strip()] if text.strip() else []

    @staticmethod
    def _normalize_character_key(value: str) -> str:
        text = re.sub(r"\([^)]*\)|\[[^\]]*\]|\{[^}]*\}", " ", str(value or ""))
        text = re.sub(r"[^a-z0-9]+", " ", text.lower())
        return " ".join(text.split())

    @classmethod
    def _register_alias(
        cls,
        aliases: Dict[str, str],
        alias: Any,
        canonical: str,
    ) -> None:
        alias_key = cls._normalize_character_key(str(alias or ""))
        canonical_name = str(canonical or "").strip()
        if alias_key and canonical_name and alias_key not in aliases:
            aliases[alias_key] = canonical_name

    @classmethod
    def build_canonical_name_reference(cls, manifest: Dict[str, Any]) -> Dict[str, Any]:
        """Build manifest-backed canon names for Stage 1 planning."""
        metadata_en = manifest.get("metadata_en", {}) if isinstance(manifest, dict) else {}
        canonical_names: List[str] = []
        aliases: Dict[str, str] = {}

        def add_canonical(raw_name: Any) -> str:
            name = str(raw_name or "").strip()
            if not name:
                return ""
            if name not in canonical_names:
                canonical_names.append(name)
            cls._register_alias(aliases, name, name)
            return name

        for fp in metadata_en.get("character_voice_fingerprints", []) or []:
            if isinstance(fp, dict):
                canonical = add_canonical(fp.get("canonical_name_en"))
                if canonical:
                    for alias_key in (
                        fp.get("full_name"),
                        fp.get("nickname"),
                        fp.get("display_name"),
                    ):
                        cls._register_alias(aliases, alias_key, canonical)
                    raw_aliases = fp.get("name_aliases", [])
                    if isinstance(raw_aliases, list):
                        for alias_key in raw_aliases:
                            cls._register_alias(aliases, alias_key, canonical)

        character_names = metadata_en.get("character_names", {})
        if isinstance(character_names, dict):
            for _, en_name in character_names.items():
                add_canonical(en_name)

        profiles = metadata_en.get("character_profiles", {})
        if isinstance(profiles, dict):
            for key, profile in profiles.items():
                canonical = add_canonical(key)
                if not isinstance(profile, dict):
                    continue
                resolved = canonical or add_canonical(profile.get("name")) or add_canonical(profile.get("full_name"))
                if not resolved:
                    continue
                for alias_key in (
                    profile.get("name"),
                    profile.get("full_name"),
                    profile.get("nickname"),
                    profile.get("ruby_reading"),
                    profile.get("ruby_base"),
                ):
                    cls._register_alias(aliases, alias_key, resolved)

        token_buckets: Dict[str, List[str]] = {}
        for canonical in canonical_names:
            for token in cls._normalize_character_key(canonical).split():
                if token and len(token) >= 3:
                    token_buckets.setdefault(token, []).append(canonical)

        for token, mapped in token_buckets.items():
            unique = []
            for canonical in mapped:
                if canonical not in unique:
                    unique.append(canonical)
            if len(unique) == 1:
                aliases[token] = unique[0]

        return {
            "canonical_names": canonical_names,
            "aliases": aliases,
        }

    @classmethod
    def _match_canonical_name(
        cls,
        raw_name: Any,
        canonical_name_reference: Optional[Dict[str, Any]],
    ) -> str:
        name = str(raw_name or "").strip()
        if not name:
            return ""
        if not canonical_name_reference:
            return name

        canonical_names = canonical_name_reference.get("canonical_names") or []
        aliases = canonical_name_reference.get("aliases") or {}
        normalized = cls._normalize_character_key(name)
        if not normalized:
            return name
        if normalized in aliases:
            return aliases[normalized]

        raw_tokens = [token for token in normalized.split() if token]
        best_name = ""
        best_score = 0.0

        for canonical in canonical_names:
            canonical_text = str(canonical or "").strip()
            if not canonical_text:
                continue
            canonical_norm = cls._normalize_character_key(canonical_text)
            if not canonical_norm:
                continue

            score = SequenceMatcher(None, normalized, canonical_norm).ratio()
            canonical_tokens = [token for token in canonical_norm.split() if token]
            for raw_token in raw_tokens:
                score = max(score, SequenceMatcher(None, raw_token, canonical_norm).ratio())
                for canonical_token in canonical_tokens:
                    score = max(score, SequenceMatcher(None, raw_token, canonical_token).ratio())
            if score > best_score:
                best_score = score
                best_name = canonical_text

        if best_name and best_score >= 0.72:
            logger.debug(
                "[SCENE-PLAN] Canonicalized character label '%s' -> '%s' (score=%.3f)",
                name,
                best_name,
                best_score,
            )
            return best_name
        return name

    def _build_canonical_name_block(self, canonical_name_reference: Optional[Dict[str, Any]]) -> str:
        if not canonical_name_reference:
            return ""
        canonical_names = [
            str(name).strip()
            for name in canonical_name_reference.get("canonical_names", [])
            if str(name).strip()
        ]
        if not canonical_names:
            return ""
        lines = [
            "## ⚠ CHARACTER NAME CANONICAL REFERENCE — MANDATORY",
            "The names below are the ONLY permitted values for pov_tracking.character and character_profiles keys.",
            "STRICT RULES:",
            "1. Copy the name EXACTLY as written — do NOT alter spelling, capitalisation, or romanisation.",
            "2. Do NOT append family names, last names, or surnames (e.g. write 'Klael', never 'Klael Burn').",
            "3. Do NOT invent alternative romanisations of a JP name that already appears in this list.",
            "4. If a character in the JP text does not appear in this list, use the closest matching name below.",
            "Canonical names:",
        ]
        lines.extend(f"  - {name}" for name in canonical_names[:80])
        return "\n".join(lines) + "\n\n"

    def _build_planning_input(
        self,
        chapter_id: str,
        japanese_text: str,
        canonical_name_reference: Optional[Dict[str, Any]] = None,
    ) -> str:
        paragraphs = self._split_paragraphs(japanese_text)
        numbered = []
        for idx, paragraph in enumerate(paragraphs, 1):
            numbered.append(f"[P{idx}] {paragraph}")
        numbered_text = "\n\n".join(numbered)
        return (
            f"CHAPTER_ID: {chapter_id}\n\n"
            f"{self._build_canonical_name_block(canonical_name_reference)}"
            "JAPANESE_TEXT:\n"
            f"{numbered_text}\n"
        )

    @staticmethod
    def _sanitize_planner_text(japanese_text: str) -> str:
        """
        Reduce prompt-block risk for Stage 1 planning by neutralizing explicit tokens.
        Keeps narrative structure intact; this planner does not require explicit wording.

        Two tiers:
        - Tier 1: Phrase-level replacements (preserve meaning, swap surface form)
        - Tier 2: Drop lines whose density cannot be neutralized by substitution
          (ロリコン commentary, body-description narration, minor-framing labels)
        """
        # --- Tier 1: phrase substitutions ---
        text = japanese_text
        replacements = {
            # Body / underwear / explicit
            "パンツ一枚": "ラフな部屋着",
            "パンツ": "部屋着",
            "下着": "服装",
            "裸": "無防備な姿",
            "脱い": "着替え",
            "お腹": "服装",
            "胸": "上半身",
            "キス": "親密な接触",
            "マッサージ": "ケア",
            "痴態": "失態",
            "だらしない声": "気の抜けた反応",
            "性的": "親密",
            "エッチな": "親密な",
            "エッチ": "親密",
            "いやらし": "過剰な",
            # Minor-framing / age commentary
            "ロリコン": "特殊な好み",
            "ロリ": "小柄な",
            "小学生": "幼く見える",
            "幼女": "小さな子",
            "児童": "子供",
            # Physical contact / positioning
            "むにゅ": "ぶつかり",
            "ぷにぷに": "柔らかい",
            "むにっ": "ぶつかり",
            "柔らか": "やわらかい",
        }
        for src, dst in replacements.items():
            text = text.replace(src, dst)

        # --- Tier 2: drop lines that remain high-density after substitution ---
        # Lines with these patterns cannot be meaningfully neutralized and are
        # irrelevant to beat/rhythm analysis (planner only needs structure, not content).
        DROP_LINE = re.compile(
            r'股間|太もも|下半身|肌色|裸身'   # body parts not covered above
            r'|痴漢|盗撮|淫ら'               # criminal/explicit framing
            r'|特殊な好み.*特殊な好み'         # double-density after substitution
        )
        kept = []
        for line in text.splitlines():
            if DROP_LINE.search(line):
                kept.append("")  # blank line — preserves paragraph structure
            else:
                kept.append(line)
        text = "\n".join(kept)

        # --- Tier 3: regex softening for specific age/context patterns ---
        text = re.sub(r"十七年ほど生きてきて", "これまで生きてきて", text)
        text = re.sub(r"(小学|中学)(生|校)", "年下の子", text)

        return text

    @staticmethod
    def _contains_high_risk_terms(japanese_text: str) -> bool:
        """Detect terms that frequently trigger Gemini prompt-side safety blocks."""
        high_risk = re.compile(
            r"ロリコン|ロリ|小学生|幼女|児童|痴漢|下着|パンツ|股間|太もも|下半身|"
            r"エッチ|性的|いやらし|裸|裸身"
        )
        return bool(high_risk.search(japanese_text or ""))

    @staticmethod
    def _is_prohibited_content_error(error: Exception) -> bool:
        """Best-effort detection of Gemini PROHIBITED_CONTENT / safety block errors."""
        text = str(error or "").upper()
        return (
            "PROHIBITED_CONTENT" in text
            or "FINISHREASON.PROHIBITED_CONTENT" in text
            or ("FAILED_PRECONDITION" in text and "400" in text)
            or ("SAFETY" in text and "BLOCK" in text)
        )

    @staticmethod
    def _build_ultra_safe_planner_text(japanese_text: str) -> str:
        """
        Build a structure-only fallback input when sanitized text still blocks.
        Keeps paragraph count while removing narrative content entirely.
        """
        paragraphs = ScenePlanningAgent._split_paragraphs(japanese_text or "")
        if not paragraphs:
            return "Scene content omitted for safety. Focus on neutral pacing scaffold only."
        return "\n\n".join(
            f"Paragraph {idx}: content omitted for safety; infer neutral transition beat."
            for idx, _ in enumerate(paragraphs, 1)
        )

    def generate_plan(
        self,
        chapter_id: str,
        japanese_text: str,
        *,
        model: Optional[str] = None,
        canonical_name_reference: Optional[Dict[str, Any]] = None,
    ) -> ScenePlan:
        if not japanese_text or not japanese_text.strip():
            raise ScenePlanningError(f"Empty Japanese text for chapter {chapter_id}")

        paragraph_count = len(self._split_paragraphs(japanese_text))
        sanitized_text = self._sanitize_planner_text(japanese_text)
        high_risk = self._contains_high_risk_terms(japanese_text)
        pre_sanitize = (
            self.enable_safety_sanitized_retry
            and (high_risk or sanitized_text != japanese_text)
        )

        planning_input_primary = self._build_planning_input(
            chapter_id,
            japanese_text,
            canonical_name_reference=canonical_name_reference,
        )
        planning_input_sanitized = self._build_planning_input(
            chapter_id,
            sanitized_text,
            canonical_name_reference=canonical_name_reference,
        )
        planning_input_ultra_safe = self._build_planning_input(
            chapter_id,
            self._build_ultra_safe_planner_text(japanese_text),
            canonical_name_reference=canonical_name_reference,
        )

        using_sanitized = pre_sanitize
        using_ultra_safe = False
        if pre_sanitize:
            logger.warning(
                "[SCENE-PLAN] Pre-sanitizing %s (high_risk=%s, text_changed=%s)",
                chapter_id,
                high_risk,
                sanitized_text != japanese_text,
            )
        max_attempts = self.empty_response_retries + 1
        response = None
        raw = ""
        finish_reason = "UNKNOWN"
        for attempt in range(1, max_attempts + 1):
            if using_ultra_safe:
                current_input = planning_input_ultra_safe
            elif using_sanitized:
                current_input = planning_input_sanitized
            else:
                current_input = planning_input_primary

            try:
                response = self.gemini.generate(
                    prompt=current_input,
                    system_instruction=self.planning_prompt,
                    model=model or self.model,
                    temperature=self.temperature,
                    max_output_tokens=self.max_output_tokens,
                    generation_config=_PHASE_1_7_GEN,
                )
            except Exception as e:
                if self._is_prohibited_content_error(e) and attempt < max_attempts:
                    if not using_sanitized and self.enable_safety_sanitized_retry:
                        using_sanitized = True
                        logger.warning(
                            "[SCENE-PLAN] PROHIBITED_CONTENT for %s (attempt %d/%d) -> retrying with safety-sanitized input",
                            chapter_id,
                            attempt,
                            max_attempts,
                        )
                        if self.empty_retry_backoff_seconds > 0:
                            time.sleep(self.empty_retry_backoff_seconds * attempt)
                        continue
                    if not using_ultra_safe:
                        using_ultra_safe = True
                        logger.warning(
                            "[SCENE-PLAN] PROHIBITED_CONTENT persists for %s (attempt %d/%d) -> retrying with ultra-safe structure-only input",
                            chapter_id,
                            attempt,
                            max_attempts,
                        )
                        if self.empty_retry_backoff_seconds > 0:
                            time.sleep(self.empty_retry_backoff_seconds * attempt)
                        continue
                    logger.warning(
                        "[SCENE-PLAN] PROHIBITED_CONTENT persists for %s (attempt %d/%d) -> retrying in ultra-safe mode",
                        chapter_id,
                        attempt,
                        max_attempts,
                    )
                    if self.empty_retry_backoff_seconds > 0:
                        time.sleep(self.empty_retry_backoff_seconds * attempt)
                    continue
                raise

            raw = getattr(response, "content", None) or ""
            finish_reason = str(getattr(response, "finish_reason", "") or "UNKNOWN")
            if raw.strip():
                break

            logger.warning(
                "[SCENE-PLAN] Empty Gemini response for %s (attempt %d/%d, finish_reason=%s)",
                chapter_id,
                attempt,
                max_attempts,
                finish_reason,
            )
            blocked_empty = "PROHIBITED_CONTENT" in finish_reason.upper()
            if blocked_empty and attempt < max_attempts:
                if not using_sanitized and self.enable_safety_sanitized_retry:
                    using_sanitized = True
                    logger.warning(
                        "[SCENE-PLAN] Empty response was prompt-blocked for %s (attempt %d/%d) -> retrying with safety-sanitized input",
                        chapter_id,
                        attempt,
                        max_attempts,
                    )
                elif not using_ultra_safe:
                    using_ultra_safe = True
                    logger.warning(
                        "[SCENE-PLAN] Empty response still prompt-blocked for %s (attempt %d/%d) -> retrying with ultra-safe structure-only input",
                        chapter_id,
                        attempt,
                        max_attempts,
                    )
                else:
                    logger.warning(
                        "[SCENE-PLAN] Prompt-block persists for %s (attempt %d/%d) -> retrying in ultra-safe mode",
                        chapter_id,
                        attempt,
                        max_attempts,
                    )
                if self.empty_retry_backoff_seconds > 0:
                    time.sleep(self.empty_retry_backoff_seconds * attempt)
                continue
            if (
                not using_sanitized
                and self.enable_safety_sanitized_retry
                and attempt < max_attempts
            ):
                sanitized_text = self._sanitize_planner_text(japanese_text)
                if sanitized_text != japanese_text:
                    using_sanitized = True
                    planning_input_sanitized = self._build_planning_input(chapter_id, sanitized_text)
                    logger.warning(
                        "[SCENE-PLAN] Retrying %s with safety-sanitized planning input",
                        chapter_id,
                    )
            if attempt < max_attempts and self.empty_retry_backoff_seconds > 0:
                time.sleep(self.empty_retry_backoff_seconds * attempt)

        if not raw.strip():
            raise ScenePlanningError(
                f"Planner returned empty response for {chapter_id} "
                f"after {max_attempts} attempt(s) (finish_reason={finish_reason})"
            )

        plan_dict = self._parse_response_json(raw)
        if "chapter_id" not in plan_dict or not str(plan_dict.get("chapter_id", "")).strip():
            plan_dict["chapter_id"] = chapter_id

        normalized = self._normalize_plan_dict(
            plan_dict,
            total_paragraphs=paragraph_count,
            canonical_name_reference=canonical_name_reference,
        )
        return self._build_scene_plan(normalized)

    @staticmethod
    def _extract_json_from_text(text: str) -> str:
        candidate = text.strip()
        fenced = re.findall(r"```(?:json)?\s*(.*?)```", candidate, re.DOTALL | re.IGNORECASE)
        if fenced:
            return fenced[0].strip()

        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            return candidate[start : end + 1]
        return candidate

    @staticmethod
    def _strip_invalid_control_chars(text: str) -> str:
        """Remove JSON-invalid control chars while preserving common whitespace."""
        if not text:
            return text
        return "".join(
            ch for ch in text
            if ch in ("\n", "\r", "\t") or ord(ch) >= 0x20
        )

    @staticmethod
    def _remove_trailing_commas(text: str) -> str:
        """Remove trailing commas before object/array close."""
        return re.sub(r",\s*([}\]])", r"\1", text)

    @staticmethod
    def _insert_missing_object_commas(text: str) -> str:
        """
        Heuristic fixer for common LLM JSON mistakes:
        - Missing comma between object fields on adjacent lines.
        - Missing comma between array/object elements on adjacent lines.
        """
        repaired = text
        repaired = re.sub(
            r'((?:"(?:\\.|[^"\\])*"|true|false|null|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\]|\}))(\s*\n\s*")',
            r"\1,\2",
            repaired,
        )
        repaired = re.sub(
            r'((?:\}|\]))(\s*\n\s*(?:\{|\[|"))',
            r"\1,\2",
            repaired,
        )
        return repaired

    @staticmethod
    def _fix_json_quotes(text: str) -> str:
        """Heuristic fixer for unquoted or single-quoted property names."""
        repaired = text
        # 1. Single quoted keys:  'key': "value"
        repaired = re.sub(r'(?m)^(\s*)\'([a-zA-Z0-9_]+)\'\s*:', r'\1"\2":', repaired)
        repaired = re.sub(r'([\{,]\s*)\'([a-zA-Z0-9_]+)\'\s*:', r'\1"\2":', repaired)
        # 2. Unquoted keys:       key: "value"
        repaired = re.sub(r'(?m)^(\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', repaired)
        repaired = re.sub(r'([\{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', repaired)
        return repaired

    def _build_json_repair_candidates(self, json_text: str) -> List[str]:
        """
        Build a small set of progressively repaired JSON candidates.
        Order matters: least-invasive first.
        """
        candidates: List[str] = []

        def add(value: str) -> None:
            value = value.strip()
            if value and value not in candidates:
                candidates.append(value)

        add(json_text)

        sanitized = self._strip_invalid_control_chars(json_text)
        add(sanitized)

        trailing = self._remove_trailing_commas(sanitized)
        add(trailing)
        
        fixed_quotes = self._fix_json_quotes(trailing)
        add(fixed_quotes)

        missing_commas = self._insert_missing_object_commas(fixed_quotes)
        add(missing_commas)

        add(self._remove_trailing_commas(missing_commas))
        return candidates

    def _parse_response_json(self, text: str) -> Dict[str, Any]:
        json_text = self._extract_json_from_text(text)
        parse_errors: List[str] = []
        parsed: Any = None
        for candidate in self._build_json_repair_candidates(json_text):
            try:
                parsed = json.loads(candidate)
                break
            except json.JSONDecodeError as e:
                parse_errors.append(str(e))
                continue

        if parsed is None:
            detail = parse_errors[0] if parse_errors else "unknown parse failure"
            raise ScenePlanningError(
                f"Failed parsing planner JSON: {detail}"
            )

        if not isinstance(parsed, dict):
            raise ScenePlanningError("Planner response must be a JSON object")
        return parsed

    @staticmethod
    def _coerce_text(value: Any, fallback: str = "") -> str:
        if value is None:
            return fallback
        if isinstance(value, str):
            out = value.strip()
            return out if out else fallback
        if isinstance(value, (int, float, bool)):
            return str(value)
        return fallback

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            if value.isdigit():
                return int(value)
        return None

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y"}
        if isinstance(value, (int, float)):
            return bool(value)
        return False

    def _resolve_illustration_anchor(self, raw_scene: Dict[str, Any], beat_type: str) -> bool:
        """
        Resolve illustration anchor with resilient key lookup.

        Models sometimes emit alternate fields (e.g., scene_anchor, visual_anchor)
        or only signal this through beat_type. We preserve that intent here.
        """
        anchor_keys = (
            "illustration_anchor",
            "scene_anchor",
            "visual_anchor",
            "is_illustration_anchor",
            "has_illustration_anchor",
            "anchor_illustration",
        )
        for key in anchor_keys:
            if key in raw_scene:
                return self._coerce_bool(raw_scene.get(key))

        # Preserve explicit beat semantics when planner omits the boolean field.
        return beat_type == "illustration_anchor"

    @staticmethod
    def _coerce_string_list(values: Any) -> List[str]:
        if not isinstance(values, list):
            return []
        out: List[str] = []
        for item in values:
            text = ScenePlanningAgent._coerce_text(item, "")
            if text:
                out.append(text)
        return out

    @staticmethod
    def _normalize_token(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")

    @staticmethod
    def _parse_word_range(value: str) -> Optional[tuple]:
        if not value:
            return None
        match = re.search(r"(\d+)\s*[-–]\s*(\d+)", value)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            if start > end:
                start, end = end, start
            return (start, end)
        single = re.search(r"\b(\d+)\s*words?\b", value.lower())
        if single:
            num = int(single.group(1))
            return (num, num)
        return None

    def _build_rhythm_levels(self) -> List[tuple]:
        levels: List[tuple] = []
        for key, word_range in self.rhythm_targets.items():
            parsed = self._parse_word_range(word_range)
            if not parsed:
                continue
            min_words, max_words = parsed
            midpoint = (min_words + max_words) / 2.0
            levels.append((key, min_words, max_words, midpoint))
        levels.sort(key=lambda item: item[3])
        return levels

    def _map_dialogue_register(self, raw_value: Any) -> str:
        if not self.allowed_registers:
            return self._coerce_text(raw_value, "casual_teen")

        fallback = "casual_teen" if "casual_teen" in self.allowed_registers else self.allowed_registers[0]
        raw_text = self._coerce_text(raw_value, fallback)
        raw_norm = self._normalize_token(raw_text)

        norm_to_register = {
            self._normalize_token(register): register
            for register in self.allowed_registers
        }
        if raw_norm in norm_to_register:
            return norm_to_register[raw_norm]

        for norm_key, register in norm_to_register.items():
            if norm_key and norm_key in raw_norm:
                return register

        def pick(candidates: Sequence[str], default: str) -> str:
            for candidate in candidates:
                if candidate in self.allowed_registers:
                    return candidate
            return default

        tokens = set(raw_norm.split("_")) if raw_norm else set()
        if tokens.intersection({"formal", "polite", "request", "strategic", "assertive"}):
            return pick(["formal_request", "casual_teen"], fallback)
        if tokens.intersection({"teasing", "smug", "playful", "banter", "competitive", "provocative"}):
            return pick(["smug_teasing", "casual_teen"], fallback)
        if tokens.intersection({"flustered", "defense", "defensive", "denial", "embarrassed", "shy", "panic"}):
            return pick(["flustered_defense", "breathless_shock", "casual_teen"], fallback)
        if tokens.intersection({"shock", "shocked", "breathless", "surprised"}):
            return pick(["breathless_shock", "flustered_defense", "casual_teen"], fallback)
        if tokens.intersection({"internal", "monologue", "narration", "reflective", "introspective"}):
            return pick(["casual_teen", "formal_request"], fallback)

        return fallback

    def _map_target_rhythm(self, raw_value: Any) -> str:
        if not self.rhythm_targets:
            return self._coerce_text(raw_value, self.default_rhythm)

        raw_text = self._coerce_text(raw_value, self.default_rhythm)
        raw_norm = self._normalize_token(raw_text)

        norm_to_key = {
            self._normalize_token(key): key
            for key in self.rhythm_targets.keys()
        }
        if raw_norm in norm_to_key:
            return norm_to_key[raw_norm]

        for norm_key, key in norm_to_key.items():
            if norm_key and norm_key in raw_norm:
                return key

        for key, word_range in self.rhythm_targets.items():
            if self._normalize_token(word_range) == raw_norm:
                return key

        parsed_range = self._parse_word_range(raw_text)
        if parsed_range and self._rhythm_levels:
            midpoint = (parsed_range[0] + parsed_range[1]) / 2.0
            return min(self._rhythm_levels, key=lambda item: abs(item[3] - midpoint))[0]

        if self._rhythm_levels:
            ordered_keys = [item[0] for item in self._rhythm_levels]
            short_keywords = {"quick", "fast", "rapid", "brief", "short", "snappy", "witty", "punchline", "reveal"}
            long_keywords = {"slow", "deliberate", "reflective", "strategic", "tender", "confession", "sensual", "climactic"}
            tokens = set(raw_norm.split("_")) if raw_norm else set()

            if tokens.intersection(short_keywords):
                return ordered_keys[0]
            if tokens.intersection(long_keywords):
                return ordered_keys[-1]

            return ordered_keys[len(ordered_keys) // 2]

        return self.default_rhythm

    def _heal_tiny_coverage_gaps(
        self,
        scenes: List[Dict[str, Any]],
        *,
        total_paragraphs: Optional[int] = None,
        max_gap: int = 2,
    ) -> None:
        if len(scenes) < 2:
            return

        healed = 0
        for idx in range(len(scenes) - 1):
            current = scenes[idx]
            nxt = scenes[idx + 1]
            current_end = current.get("end_paragraph")
            next_start = nxt.get("start_paragraph")

            if not isinstance(current_end, int) or not isinstance(next_start, int):
                continue

            gap_size = next_start - current_end - 1
            if gap_size > 0 and gap_size <= max_gap:
                current["end_paragraph"] = next_start - 1
                healed += 1

        if isinstance(total_paragraphs, int) and total_paragraphs > 0:
            last_end = scenes[-1].get("end_paragraph")
            if isinstance(last_end, int):
                tail_gap = total_paragraphs - last_end
                if tail_gap > 0 and tail_gap <= max_gap:
                    scenes[-1]["end_paragraph"] = total_paragraphs
                    healed += 1

        if healed:
            logger.debug(f"Healed {healed} tiny scene coverage gap(s) (<= {max_gap} paragraph(s)).")

    def _normalize_scene(self, raw_scene: Dict[str, Any], idx: int) -> Dict[str, Any]:
        beat_type = self._coerce_text(raw_scene.get("beat_type"), "setup").lower()
        if beat_type not in self.allowed_beat_types:
            logger.debug(f"Unknown beat_type '{beat_type}' in scene {idx}; fallback to setup.")
            beat_type = "setup"

        start_paragraph = self._coerce_int(raw_scene.get("start_paragraph"))
        end_paragraph = self._coerce_int(raw_scene.get("end_paragraph"))
        if start_paragraph is not None and end_paragraph is not None and end_paragraph < start_paragraph:
            end_paragraph = start_paragraph

        normalized: Dict[str, Any] = {
            "id": self._coerce_text(raw_scene.get("id"), f"scene_{idx:02d}"),
            "beat_type": beat_type,
            "emotional_arc": self._coerce_text(raw_scene.get("emotional_arc"), "neutral_progression"),
            "dialogue_register": self._map_dialogue_register(raw_scene.get("dialogue_register")),
            "target_rhythm": self._map_target_rhythm(raw_scene.get("target_rhythm")),
            "illustration_anchor": self._resolve_illustration_anchor(raw_scene, beat_type),
            "start_paragraph": start_paragraph,
            "end_paragraph": end_paragraph,
        }

        # Pass through culture bleed annotations emitted by the planner LLM.
        # These are optional — absent when Gemini found no JP-specific risk in the scene.
        for bleed_key in (
            "culture_bleed_risk",
            "culture_bleed_category",
            "culture_bleed_source_phrase",
            "culture_bleed_warning",
            "culture_bleed_forbidden",
            "eps_band",
        ):
            raw_val = raw_scene.get(bleed_key)
            if raw_val is not None:
                normalized[bleed_key] = raw_val
                if bleed_key == "culture_bleed_risk":
                    logger.debug(
                        "[CULTURE-BLEED] Planner flagged scene %s: risk=%s phrase='%s'",
                        normalized["id"],
                        raw_val,
                        raw_scene.get("culture_bleed_source_phrase", "?"),
                    )

        return normalized

    def _merge_profile_dicts(
        self,
        existing: Dict[str, Any],
        incoming: Dict[str, Any],
    ) -> Dict[str, Any]:
        merged = dict(existing)
        for key in (
            "name",
            "emotional_state",
            "sentence_bias",
            "relationship_dynamic",
        ):
            if not merged.get(key) and incoming.get(key):
                merged[key] = incoming[key]
        for key in ("victory_patterns", "denial_patterns"):
            current = merged.get(key, []) or []
            extra = incoming.get(key, []) or []
            deduped: List[str] = []
            for item in [*current, *extra]:
                text = self._coerce_text(item, "")
                if text and text not in deduped:
                    deduped.append(text)
            merged[key] = deduped
        return merged

    def _normalize_profiles(
        self,
        raw_profiles: Any,
        canonical_name_reference: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        if not isinstance(raw_profiles, dict):
            return {}

        profiles: Dict[str, Dict[str, Any]] = {}
        for raw_name, raw_profile in raw_profiles.items():
            key_name = self._coerce_text(raw_name, "")
            if not key_name or not isinstance(raw_profile, dict):
                continue

            canonical_key = self._match_canonical_name(key_name, canonical_name_reference) or key_name
            name = self._coerce_text(raw_profile.get("name"), canonical_key)
            name = self._match_canonical_name(name, canonical_name_reference) or canonical_key
            normalized_profile = {
                "name": name,
                "emotional_state": self._coerce_text(raw_profile.get("emotional_state"), "neutral"),
                "sentence_bias": self._coerce_text(raw_profile.get("sentence_bias"), "8-10w medium"),
                "victory_patterns": self._coerce_string_list(raw_profile.get("victory_patterns")),
                "denial_patterns": self._coerce_string_list(raw_profile.get("denial_patterns")),
                "relationship_dynamic": self._coerce_text(raw_profile.get("relationship_dynamic"), "unspecified"),
            }
            if canonical_key in profiles:
                profiles[canonical_key] = self._merge_profile_dicts(profiles[canonical_key], normalized_profile)
            else:
                profiles[canonical_key] = normalized_profile
        return profiles

    def _normalize_pov_tracking(
        self,
        raw_pov_tracking: Any,
        profiles: Dict[str, Dict[str, Any]],
        canonical_name_reference: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        pov_tracking: List[Dict[str, Any]] = []

        if isinstance(raw_pov_tracking, list):
            for raw_segment in raw_pov_tracking:
                if not isinstance(raw_segment, dict):
                    continue
                character = self._coerce_text(raw_segment.get("character"), "")
                if not character:
                    continue
                character = self._match_canonical_name(character, canonical_name_reference) or character
                start_line = self._coerce_int(raw_segment.get("start_line"))
                end_line = self._coerce_int(raw_segment.get("end_line"))
                if start_line is not None and end_line is not None and end_line < start_line:
                    end_line = start_line
                description = self._coerce_text(
                    raw_segment.get("description") or raw_segment.get("context"),
                    "POV character",
                )
                pov_tracking.append(
                    {
                        "character": character,
                        "start_line": start_line,
                        "end_line": end_line,
                        "description": description,
                    }
                )

        if not pov_tracking:
            # Prefer the first non-generic profile key so fingerprint lookup succeeds.
            # Generic labels ("Narrator", "Protagonist", etc.) are skipped because
            # voice_rag.get_fingerprint() returns None for them, leaving Gap 8.2 dormant.
            # This was the root cause of 0e48 Ch08 KF failure (interlude narrator mislabeled).
            _GENERIC_LABELS = frozenset(
                {"narrator", "protagonist", "pov character", "pov", "unknown", "hero", "heroine"}
            )
            fallback_name = ""
            for _candidate in profiles:
                if str(_candidate or "").strip().lower() not in _GENERIC_LABELS:
                    fallback_name = str(_candidate).strip()
                    break
            if not fallback_name:
                # All profile keys are generic — use the first one as last resort
                fallback_name = next(iter(profiles), "") if profiles else ""
            if fallback_name:
                pov_tracking = [
                    {
                        "character": fallback_name,
                        "start_line": 1,
                        "end_line": None,
                        "description": "POV character (synthesized fallback — non-generic key)",
                    }
                ]
            else:
                logger.warning(
                    "_normalize_pov_tracking: no pov_tracking from LLM and profiles is empty; "
                    "Gap 8.2 injection will be skipped for this chapter."
                )

        if len(pov_tracking) == 1 and pov_tracking[0].get("start_line") is None:
            pov_tracking[0]["start_line"] = 1

        return pov_tracking

    def _normalize_plan_dict(
        self,
        plan_dict: Dict[str, Any],
        *,
        total_paragraphs: Optional[int] = None,
        canonical_name_reference: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        chapter_id = self._coerce_text(plan_dict.get("chapter_id"), "chapter_unknown")
        raw_scenes = plan_dict.get("scenes", [])
        scenes: List[Dict[str, Any]] = []

        if isinstance(raw_scenes, list):
            for idx, raw_scene in enumerate(raw_scenes, 1):
                if isinstance(raw_scene, dict):
                    scenes.append(self._normalize_scene(raw_scene, idx))

        if not scenes:
            scenes = [
                {
                    "id": "scene_01",
                    "beat_type": "setup",
                    "emotional_arc": "neutral_progression",
                    "dialogue_register": "casual_teen",
                    "target_rhythm": self.default_rhythm,
                    "illustration_anchor": False,
                    "start_paragraph": 1,
                    "end_paragraph": None,
                }
            ]

        self._heal_tiny_coverage_gaps(scenes, total_paragraphs=total_paragraphs)
        profiles = self._normalize_profiles(
            plan_dict.get("character_profiles", {}),
            canonical_name_reference=canonical_name_reference,
        )
        pov_tracking = self._normalize_pov_tracking(
            plan_dict.get("pov_tracking"),
            profiles,
            canonical_name_reference=canonical_name_reference,
        )

        return {
            "chapter_id": chapter_id,
            "scenes": scenes,
            "pov_tracking": pov_tracking,
            "character_profiles": profiles,
            "overall_tone": self._coerce_text(plan_dict.get("overall_tone"), "neutral"),
            "pacing_strategy": self._coerce_text(plan_dict.get("pacing_strategy"), "standard"),
        }

    @staticmethod
    def _build_scene_plan(plan_dict: Dict[str, Any]) -> ScenePlan:
        _SCENE_BEAT_FIELDS = {f.name for f in SceneBeat.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        _POV_SEGMENT_FIELDS = {f.name for f in POVSegment.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        scenes = [
            SceneBeat(**{k: v for k, v in scene.items() if k in _SCENE_BEAT_FIELDS})
            for scene in plan_dict.get("scenes", [])
        ]
        pov_tracking = [
            POVSegment(**{k: v for k, v in segment.items() if k in _POV_SEGMENT_FIELDS})
            for segment in plan_dict.get("pov_tracking", [])
            if isinstance(segment, dict)
        ]
        character_profiles = {
            name: CharacterProfile(**profile)
            for name, profile in plan_dict.get("character_profiles", {}).items()
        }
        return ScenePlan(
            chapter_id=plan_dict.get("chapter_id", "chapter_unknown"),
            scenes=scenes,
            pov_tracking=pov_tracking,
            character_profiles=character_profiles,
            overall_tone=plan_dict.get("overall_tone", "neutral"),
            pacing_strategy=plan_dict.get("pacing_strategy", "standard"),
        )

    @staticmethod
    def save_plan(plan: ScenePlan, output_path: Path, manifest: Optional[Dict[str, Any]] = None) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = plan.to_dict()
        if isinstance(manifest, dict) and manifest:
            payload = normalize_payload_names(payload, manifest)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved scene plan: {output_path}")

    @staticmethod
    def load_plan(path: Path) -> ScenePlan:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ScenePlanningError(f"Invalid scene plan file: {path}")
        return ScenePlanningAgent._build_scene_plan(data)

    @staticmethod
    def filter_requested_chapters(
        chapters: Sequence[Dict[str, Any]],
        requested: Optional[Sequence[str]],
    ) -> List[Dict[str, Any]]:
        """Filter chapter dicts by requested IDs, source files, or chapter numbers."""
        chapter_list = [ch for ch in chapters if isinstance(ch, dict)]
        if not requested:
            return chapter_list

        normalized = {str(v).strip().lower() for v in requested if str(v).strip()}
        selected: List[Dict[str, Any]] = []
        for chapter in chapter_list:
            chapter_id = str(chapter.get("id", "")).strip()
            source_file = str(chapter.get("source_file", "")).strip()
            source_stem = Path(source_file).stem if source_file else ""
            candidates = {
                chapter_id.lower(),
                source_file.lower(),
                source_stem.lower(),
            }

            match = re.search(r"(\d+)", chapter_id) or re.search(r"(\d+)", source_stem)
            if match:
                number = str(int(match.group(1)))
                candidates.add(number)
                candidates.add(f"chapter_{int(number):02d}")

            if normalized.intersection(candidates):
                selected.append(chapter)
        return selected

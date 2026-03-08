"""
Prompt Injector for Multimodal Translation.

Builds visual context blocks that get injected into the translation prompt,
allowing Gemini 2.5 Pro to translate with awareness of illustration context
even without seeing the images directly.

This is the "Context Handoff" mechanism: Gemini 3 Pro's visual analysis
becomes Gemini 2.5 Pro's "Art Director's Notes".

Canon Name Enforcement:
- CanonNameEnforcer is instantiated locally (no global state)
- build_chapter_visual_guidance(manifest=...) creates enforcer on demand
- Canon names from manifest.json character_profiles are applied to visual context
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class CanonNameEnforcer:
    """
    Enforces canonical character names from manifest.json.
    
    Ensures the Multimodal Processor uses consistent names that match
    the Librarian's ruby text extraction.
    """
    
    def __init__(self, manifest: Optional[Dict[str, Any]] = None):
        self.manifest = manifest or {}
        self.canon_map: Dict[str, str] = {}  # Japanese → English
        self.nickname_map: Dict[str, str] = {}  # Japanese → Nickname
        self.visual_identity_map: Dict[str, Dict[str, Any]] = {}  # Japanese → non-color visual identity
        self.biological_arrays_map: Dict[str, Dict[str, Any]] = {}  # Japanese → sibling/biology disambiguation
        self._load_canon_names()

    @staticmethod
    def _first_nickname(nickname: str) -> str:
        """Return first nickname token from a comma-separated nickname field."""
        if not isinstance(nickname, str):
            return ""
        primary = nickname.split(",", 1)[0].strip()
        return primary

    @staticmethod
    def _profile_canonical_name(profile: Dict[str, Any]) -> str:
        """
        Resolve canonical EN name across schema variants.

        Priority keeps backward compatibility with existing `full_name`, while
        accepting newer metadata payloads that only populate `character_name_en`.
        """
        if not isinstance(profile, dict):
            return ""
        for key in ("full_name", "canonical_en", "character_name_en", "name_en", "english_name"):
            value = str(profile.get(key, "")).strip()
            if value:
                return value
        return ""

    @staticmethod
    def _extract_relation_label(
        japanese_name: str,
        relationship_to_protagonist: str,
    ) -> str:
        """
        Infer familial relation label from JP key and/or relationship text.

        Returns values like "Mother", "Father", "Older Sister", etc.
        """
        jp = japanese_name or ""
        rel = relationship_to_protagonist or ""
        rel_l = rel.lower()

        suffix_map = [
            ("母親", "Mother"),
            ("父親", "Father"),
            ("祖母", "Grandmother"),
            ("祖父", "Grandfather"),
            ("姉", "Older Sister"),
            ("兄", "Older Brother"),
            ("妹", "Younger Sister"),
            ("弟", "Younger Brother"),
            ("先生", "Teacher"),
        ]
        for suffix, label in suffix_map:
            if jp.endswith(f"の{suffix}") or jp.endswith(suffix):
                return label

        text_map = [
            ("mother", "Mother"),
            ("father", "Father"),
            ("grandmother", "Grandmother"),
            ("grandfather", "Grandfather"),
            ("older sister", "Older Sister"),
            ("older brother", "Older Brother"),
            ("younger sister", "Younger Sister"),
            ("younger brother", "Younger Brother"),
            ("sister", "Sister"),
            ("brother", "Brother"),
            ("teacher", "Teacher"),
        ]
        for token, label in text_map:
            if token in rel_l:
                return label
        return ""

    @staticmethod
    def _key_has_relation_suffix(japanese_name: str) -> bool:
        """
        Detect role-like keys (e.g., 玉置の母親, 〇〇の姉, etc.).

        Prevents accidental relabeling of proper names such as "Emma" based on
        relationship text that contains phrases like "older brother figure".
        """
        if not isinstance(japanese_name, str):
            return False
        jp = japanese_name.strip()
        if not jp:
            return False
        relation_suffixes = ("母親", "父親", "祖母", "祖父", "姉", "兄", "妹", "弟", "先生")
        if any(jp.endswith(f"の{sfx}") for sfx in relation_suffixes):
            return True
        if any(jp.endswith(sfx) for sfx in relation_suffixes):
            return True
        return False

    @staticmethod
    def _normalize_biological_arrays(
        biological_arrays: Any,
        relationship_to_others: str = "",
    ) -> Dict[str, Any]:
        """
        Normalize biology-focused sibling disambiguation payload.

        Expected shape:
          {
            "blood_related_siblings": [{"canonical_name": "...", "relation": "...", ...}],
            "family_role_markers": ["older_sister", ...],
            "anti_confusion_directives": ["...", ...]
          }
        """
        result: Dict[str, Any] = {
            "blood_related_siblings": [],
            "family_role_markers": [],
            "anti_confusion_directives": [],
        }

        if isinstance(biological_arrays, dict):
            sibling_rows = biological_arrays.get("blood_related_siblings", [])
            if isinstance(sibling_rows, list):
                for row in sibling_rows:
                    if isinstance(row, dict):
                        canonical_name = str(row.get("canonical_name", "")).strip()
                        relation = str(row.get("relation", "")).strip()
                        if canonical_name:
                            cleaned = {
                                "canonical_name": canonical_name,
                                "relation": relation,
                            }
                            japanese_name = str(row.get("japanese_name", "")).strip()
                            if japanese_name:
                                cleaned["japanese_name"] = japanese_name
                            family_name_shared = str(row.get("family_name_shared", "")).strip()
                            if family_name_shared:
                                cleaned["family_name_shared"] = family_name_shared
                            evidence_jp = row.get("evidence_jp", [])
                            if isinstance(evidence_jp, list):
                                evidence_clean = [str(v).strip() for v in evidence_jp if str(v).strip()]
                                if evidence_clean:
                                    cleaned["evidence_jp"] = evidence_clean[:6]
                            result["blood_related_siblings"].append(cleaned)
                    elif isinstance(row, str) and row.strip():
                        result["blood_related_siblings"].append(
                            {"canonical_name": row.strip(), "relation": ""}
                        )

            for key in ("family_role_markers", "anti_confusion_directives"):
                values = biological_arrays.get(key, [])
                if isinstance(values, list):
                    result[key] = [str(v).strip() for v in values if str(v).strip()][:10]

        # Infer sibling links from existing profile text when explicit arrays are absent.
        rel_text = str(relationship_to_others or "").strip()
        if rel_text:
            patterns = [
                (r"older sister to ([^;,.]+)", "older_sister"),
                (r"younger sister to ([^;,.]+)", "younger_sister"),
                (r"older brother to ([^;,.]+)", "older_brother"),
                (r"younger brother to ([^;,.]+)", "younger_brother"),
            ]
            existing_pairs = {
                (
                    str(item.get("canonical_name", "")).strip().lower(),
                    str(item.get("relation", "")).strip().lower(),
                )
                for item in result["blood_related_siblings"]
                if isinstance(item, dict)
            }
            rel_lower = rel_text.lower()
            for pattern, relation in patterns:
                for m in re.finditer(pattern, rel_lower):
                    raw_name = rel_text[m.start(1):m.end(1)].strip()
                    pair_key = (raw_name.lower(), relation.lower())
                    if raw_name and pair_key not in existing_pairs:
                        result["blood_related_siblings"].append(
                            {"canonical_name": raw_name, "relation": relation}
                        )
                        existing_pairs.add(pair_key)
                    if relation not in result["family_role_markers"]:
                        result["family_role_markers"].append(relation)

        # Remove empty collections for compact prompt rendering.
        compact = {k: v for k, v in result.items() if v}
        return compact

    @staticmethod
    def _format_biological_short(bio: Dict[str, Any]) -> str:
        """Render compact biology/sibling disambiguation hint."""
        if not isinstance(bio, dict) or not bio:
            return ""
        chunks: List[str] = []
        siblings = bio.get("blood_related_siblings", [])
        if isinstance(siblings, list) and siblings:
            rendered = []
            for row in siblings[:3]:
                if isinstance(row, dict):
                    name = str(row.get("canonical_name", "")).strip()
                    rel = str(row.get("relation", "")).strip()
                    if name and rel:
                        rendered.append(f"{rel}:{name}")
                    elif name:
                        rendered.append(name)
                elif isinstance(row, str) and row.strip():
                    rendered.append(row.strip())
            if rendered:
                chunks.append("blood-sibling=" + ", ".join(rendered))
        roles = bio.get("family_role_markers", [])
        if isinstance(roles, list) and roles:
            role_vals = [str(v).strip() for v in roles if str(v).strip()]
            if role_vals:
                chunks.append("roles=" + ", ".join(role_vals[:4]))
        anti = bio.get("anti_confusion_directives", [])
        if isinstance(anti, list) and anti:
            anti_vals = [str(v).strip() for v in anti if str(v).strip()]
            if anti_vals:
                chunks.append("guard=" + anti_vals[0])
        return " | ".join(chunks)[:260]

    @classmethod
    def build_canonical_label(
        cls,
        japanese_name: str,
        profile: Dict[str, Any],
    ) -> str:
        """
        Build a stable canonical label for prompt/cache use.

        Improves ambiguous one-token names for relation roles, e.g.:
        - "玉置の母親" + "Tamaki" + "Ako's mother" -> "Ako's Mother"
        """
        if not isinstance(profile, dict):
            return ""

        canonical_name = cls._profile_canonical_name(profile)
        nickname = cls._first_nickname(str(profile.get("nickname", "")))
        rel_to_protag = str(profile.get("relationship_to_protagonist", "")).strip()
        rel_to_others = str(profile.get("relationship_to_others", "")).strip()

        relation_label = cls._extract_relation_label(japanese_name, rel_to_protag)
        if not relation_label:
            relation_label = cls._extract_relation_label(japanese_name, rel_to_others)

        # Proper named characters should keep explicit canonical names.
        # Relation relabeling is reserved for role-like keys (e.g. "Xの母親").
        if canonical_name and not cls._key_has_relation_suffix(japanese_name):
            return canonical_name

        if relation_label:
            # Preferred: explicit "<Name>'s <Relation>" from relationship text.
            # Example: "Ako's mother" -> "Ako's Mother"
            rel_match = re.search(
                r"([A-Za-z][A-Za-z -]{0,40})'s\s+(mother|father|sister|brother|grandmother|grandfather|teacher)",
                rel_to_protag,
                flags=re.IGNORECASE,
            )
            if rel_match:
                owner = rel_match.group(1).strip()
                return f"{owner}'s {relation_label}"

            if canonical_name:
                suffix = "'" if canonical_name.endswith("s") else "'s"
                return f"{canonical_name}{suffix} {relation_label}"
            if nickname:
                suffix = "'" if nickname.endswith("s") else "'s"
                return f"{nickname}{suffix} {relation_label}"
            return relation_label

        if canonical_name:
            return canonical_name
        return nickname
    
    def _load_canon_names(self) -> None:
        """Load canon names from manifest character_profiles."""
        metadata_en = self.manifest.get("metadata_en", {})
        if not isinstance(metadata_en, dict):
            metadata_en = {}
        profiles = metadata_en.get("character_profiles", {})
        if not isinstance(profiles, dict):
            profiles = {}
        
        for kanji_name, profile in profiles.items():
            if not isinstance(profile, dict):
                continue
            jp_key = str(profile.get("character_name_jp", "")).strip() or str(kanji_name).strip()
            if not jp_key:
                continue

            full_name = self.build_canonical_label(jp_key, profile)
            nickname = profile.get("nickname", "")
            
            if full_name:
                self.canon_map[jp_key] = full_name
            if nickname:
                self.nickname_map[jp_key] = nickname
            visual_identity = self._normalize_visual_identity(
                profile.get("visual_identity_non_color"),
                profile.get("appearance", "")
            )
            if visual_identity:
                self.visual_identity_map[jp_key] = visual_identity
            biological_arrays = self._normalize_biological_arrays(
                profile.get("biological_arrays"),
                str(profile.get("relationship_to_others", "")),
            )
            if biological_arrays:
                self.biological_arrays_map[jp_key] = biological_arrays

        if self.canon_map:
            logger.debug(f"[CANON] Loaded {len(self.canon_map)} character names")

    @staticmethod
    def _normalize_habitual_gestures(raw_value: Any) -> List[Dict[str, Any]]:
        """Normalize habitual gesture payload into a compact structured list."""
        normalized: List[Dict[str, Any]] = []

        if isinstance(raw_value, str) and raw_value.strip():
            return [{"gesture": raw_value.strip()}]

        if not isinstance(raw_value, list):
            return normalized

        for item in raw_value:
            if isinstance(item, dict):
                gesture = str(item.get("gesture", "")).strip()
                if not gesture:
                    continue
                entry: Dict[str, Any] = {"gesture": gesture}
                for key in ("trigger", "intensity", "narrative_effect"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        entry[key] = value.strip()
                chapters = item.get("evidence_chapters")
                if isinstance(chapters, list):
                    cleaned_chapters = [str(v).strip() for v in chapters if str(v).strip()]
                    if cleaned_chapters:
                        entry["evidence_chapters"] = cleaned_chapters[:6]
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

    @staticmethod
    def _normalize_visual_identity(identity: Any, appearance: str = "") -> Dict[str, Any]:
        """Normalize visual identity payload to a stable non-color dict shape."""
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
                    values = [str(v).strip() for v in value if str(v).strip()]
                    if values:
                        cleaned[key] = values[:8]
            habitual_gestures = CanonNameEnforcer._normalize_habitual_gestures(
                identity.get("habitual_gestures")
            )
            if habitual_gestures:
                cleaned["habitual_gestures"] = habitual_gestures
            if cleaned:
                return cleaned
        if isinstance(appearance, str) and appearance.strip():
            return {"identity_summary": appearance.strip(), "habitual_gestures": []}
        return {}

    @staticmethod
    def _format_visual_identity_short(identity: Dict[str, Any]) -> str:
        """Format non-color identity to one compact line for prompts."""
        if not identity:
            return ""
        mapping = [
            ("hair", "hairstyle"),
            ("outfit", "clothing_signature"),
            ("expr", "expression_signature"),
            ("pose", "posture_signature"),
            ("acc", "accessory_signature"),
            ("habit", "habitual_gestures"),
            ("id", "identity_summary"),
        ]
        chunks: List[str] = []
        for label, key in mapping:
            value = identity.get(key)
            if isinstance(value, str) and value.strip():
                chunks.append(f"{label}:{value.strip()}")
            elif key == "habitual_gestures" and isinstance(value, list):
                gestures: List[str] = []
                for item in value:
                    if isinstance(item, dict):
                        g = str(item.get("gesture", "")).strip()
                        if g:
                            gestures.append(g)
                    else:
                        text = str(item).strip()
                        if text:
                            gestures.append(text)
                if gestures:
                    chunks.append(f"habit:{', '.join(gestures[:2])}")
            elif isinstance(value, list):
                items = [str(v).strip() for v in value if str(v).strip()]
                if items:
                    chunks.append(f"{label}:{', '.join(items[:3])}")
        if not chunks:
            markers = identity.get("non_color_markers", [])
            if isinstance(markers, list):
                items = [str(v).strip() for v in markers if str(v).strip()]
                if items:
                    chunks.append("markers:" + ", ".join(items[:4]))
        return " | ".join(chunks)[:220]
    
    def enforce_in_text(self, text: str) -> str:
        """Replace any Japanese character names with their English canon names."""
        result = text
        for jp_name, en_name in self.canon_map.items():
            result = result.replace(jp_name, en_name)
        return result
    
    def enforce_in_visual_context(self, visual_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively enforce canon names in visual context dict.
        
        This ensures Art Director's Notes use consistent character names.
        """
        if not self.canon_map:
            return visual_context
        
        def process_value(value: Any) -> Any:
            if isinstance(value, str):
                return self.enforce_in_text(value)
            elif isinstance(value, dict):
                return {k: process_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [process_value(item) for item in value]
            return value
        
        return process_value(visual_context)
    
    def get_character_reference(self) -> str:
        """Build a character name reference block for prompt injection."""
        if not self.canon_map:
            return ""
        
        lines = ["=== CHARACTER NAME REFERENCE (Canon from Ruby Text) ==="]
        for jp_name, en_name in self.canon_map.items():
            nickname = self.nickname_map.get(jp_name, "")
            visual_identity = self.visual_identity_map.get(jp_name, {})
            visual_hint = self._format_visual_identity_short(visual_identity)
            biology = self.biological_arrays_map.get(jp_name, {})
            biology_hint = self._format_biological_short(biology)
            if nickname and nickname != en_name:
                lines.append(f"  {jp_name} → {en_name} (nickname: {nickname})")
            else:
                lines.append(f"  {jp_name} → {en_name}")
            if visual_hint:
                lines.append(f"    non-color-id: {visual_hint}")
            if biology_hint:
                lines.append(f"    biology: {biology_hint}")
        lines.append("Use these canonical names consistently in all translations.")
        lines.append("=== END CHARACTER REFERENCE ===\n")
        
        return "\n".join(lines)


def build_multimodal_identity_lock(
    manifest: Optional[Dict[str, Any]],
    max_characters: int = 24,
    bible_characters: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Build identity lock block for multimodal analysis prompts.

    Includes canonical real names and non-color visual markers to reduce
    identity guessing in scene analysis.
    """
    if not manifest:
        return ""

    enforcer = CanonNameEnforcer(manifest)
    identity_records: Dict[str, Dict[str, Any]] = {}

    for jp_name, en_name in enforcer.canon_map.items():
        identity_records[jp_name] = {
            "canonical_name": en_name,
            "nickname": enforcer.nickname_map.get(jp_name, ""),
            "visual_identity": enforcer.visual_identity_map.get(jp_name, {}),
            "biological_arrays": enforcer.biological_arrays_map.get(jp_name, {}),
        }

    if isinstance(bible_characters, dict):
        for jp_name, char_data in bible_characters.items():
            if not isinstance(char_data, dict):
                continue
            canonical_name = str(char_data.get("canonical_en", "")).strip()
            if not canonical_name:
                continue
            existing = identity_records.get(jp_name, {})
            if not existing:
                identity_records[jp_name] = {
                    "canonical_name": canonical_name,
                    "nickname": str(char_data.get("short_name", "")).strip(),
                    "visual_identity": CanonNameEnforcer._normalize_visual_identity(
                        char_data.get("visual_identity_non_color"), ""
                    ),
                    "biological_arrays": CanonNameEnforcer._normalize_biological_arrays(
                        char_data.get("biological_arrays"),
                        "",
                    ),
                }
            else:
                if not existing.get("nickname"):
                    existing["nickname"] = str(char_data.get("short_name", "")).strip()
                if not existing.get("visual_identity"):
                    existing["visual_identity"] = CanonNameEnforcer._normalize_visual_identity(
                        char_data.get("visual_identity_non_color"), ""
                    )
                if not existing.get("biological_arrays"):
                    existing["biological_arrays"] = CanonNameEnforcer._normalize_biological_arrays(
                        char_data.get("biological_arrays"),
                        "",
                    )

    if not identity_records:
        return ""

    lines = [
        "=== CHARACTER IDENTITY LOCK (NON-COLOR) ===",
        "Use this registry before any scene analysis.",
        "If a visible character matches markers below, use canonical_en immediately.",
        "Do NOT guess alternate names when a canonical match exists.",
        "Variation Tolerance: attire, hairstyle, and expression can vary by scene/time/cosplay/pose.",
        "Treat visual markers as soft evidence; do not reject a candidate for one mismatching trait.",
        "When raw-text scene candidates are provided, prioritize those names over visual priors.",
    ]

    for i, (jp_name, record) in enumerate(identity_records.items()):
        if i >= max_characters:
            lines.append(f"... ({len(identity_records) - max_characters} more omitted)")
            break
        en_name = str(record.get("canonical_name", "")).strip()
        if not en_name:
            continue
        nickname = str(record.get("nickname", "")).strip()
        display = f"{en_name} [{jp_name}]"
        if nickname and nickname != en_name:
            display += f" / nickname={nickname}"
        lines.append(f"- {display}")
        visual_identity = record.get("visual_identity", {})
        visual_hint = CanonNameEnforcer._format_visual_identity_short(visual_identity)
        if visual_hint:
            lines.append(f"  non-color-id: {visual_hint}")
        biological_arrays = record.get("biological_arrays", {})
        biology_hint = CanonNameEnforcer._format_biological_short(biological_arrays)
        if biology_hint:
            lines.append(f"  biology: {biology_hint}")

    sibling_disambiguation_rules: List[str] = []
    for record in identity_records.values():
        if not isinstance(record, dict):
            continue
        source_name = str(record.get("canonical_name", "")).strip()
        bio = record.get("biological_arrays", {})
        if not source_name or not isinstance(bio, dict):
            continue
        siblings = bio.get("blood_related_siblings", [])
        if not isinstance(siblings, list):
            continue
        for row in siblings:
            if not isinstance(row, dict):
                continue
            target_name = str(row.get("canonical_name", "")).strip()
            relation = str(row.get("relation", "")).strip().replace("_", " ")
            if not target_name:
                continue
            if relation:
                sibling_disambiguation_rules.append(
                    f"{source_name} is {relation} of {target_name}; never swap their identities."
                )
            else:
                sibling_disambiguation_rules.append(
                    f"{source_name} is blood-related to {target_name}; never swap their identities."
                )

    if sibling_disambiguation_rules:
        lines.append("Sibling Disambiguation Rules (Blood-related):")
        deduped = []
        seen = set()
        for rule in sibling_disambiguation_rules:
            if rule in seen:
                continue
            seen.add(rule)
            deduped.append(rule)
        for rule in deduped[:8]:
            lines.append(f"  - {rule}")

    lines.extend([
        "If markers conflict or remain ambiguous, output unresolved_character (do not invent names).",
        "If uncertain, mark as unresolved_character and continue scene analysis.",
        "=== END IDENTITY LOCK ===",
    ])
    return "\n".join(lines)


# Removed: Global _canon_enforcer state (hygiene pass)
# Canon enforcement is now handled via explicit parameter passing:
#   - build_chapter_visual_guidance(manifest=...) creates a local enforcer
#   - cache_manager passes manifest to prompt_injector directly


# Strict output requirement to prevent analysis leaks
MULTIMODAL_STRICT_SUFFIX = """

CRITICAL OUTPUT REQUIREMENT:
Your response MUST be ONLY the translated text.
DO NOT output any analysis, planning, thinking process, or commentary.
DO NOT describe what you're going to do or what you observed.
DO NOT explain your translation choices.
ONLY output the final translated text, maintaining all formatting
including all illustration markers (e.g. [ILLUSTRATION: xxx] or ![illustration](xxx)) in their original positions.
Begin your response with the translated text immediately.
"""

# Canon Event Fidelity constraint for visual context integration
CANON_EVENT_FIDELITY_DIRECTIVE = """
=== CANON EVENT FIDELITY v2 (ABSOLUTE PRIORITY) ===

Rule 1 — JP source text is canonical truth for events, dialogue, and plot facts.
Rule 2 — Translation is rendering, not authoring; no invention outside explicit exception.
Rule 3 — Preserve character voice fingerprints; EPS is guidance, not a hard overwrite.
Rule 4 — Dialogue register follows JP source; visual EPS informs nuance only.
Rule 5 — Atmospheric descriptors can be enhanced, but do not invent events.
Rule 6 — Illustration is descriptive context, not additional canon.
Rule 7 — Multimodal guidance governs style; source governs substance.
Rule 8 — bridge_prose allowed only when canon_fidelity_override=true and within word_budget.
Rule 9 — Every ADN directive must be acknowledged (WILL_APPLY/PARTIAL/BLOCKED).
Rule 10 — Post-marker EPS consistency scan required for constrained characters.

BLOCKED codes:
  BLOCKED:POV_MISMATCH | BLOCKED:CHARACTER_ABSENT | BLOCKED:SOURCE_CONTRADICTION |
  BLOCKED:CANON_FIDELITY | BLOCKED:WORD_BUDGET_EXCEEDED

SPOILER PREVENTION:
The do_not_reveal_before_text list contains visual spoilers.
Do NOT reveal those details until JP source text confirms them.

=== END CANON EVENT FIDELITY v2 ===
"""


def _coerce_typed_directives(entry: Dict[str, Any], visual_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return typed ADN directives, coercing legacy string directives when needed."""
    typed = entry.get("narrative_directives", []) if isinstance(entry, dict) else []
    out: List[Dict[str, Any]] = []
    if isinstance(typed, list):
        for idx, item in enumerate(typed, start=1):
            if isinstance(item, dict):
                did = str(item.get("id", "") or f"auto-d{idx}").strip()
                instruction = str(item.get("instruction", "") or "").strip()
                if not instruction:
                    continue
                out.append({
                    "id": did,
                    "type": str(item.get("type", "atmospheric_frame") or "atmospheric_frame"),
                    "priority": str(item.get("priority", "recommended") or "recommended"),
                    "scope": str(item.get("scope", "post_marker_scene") or "post_marker_scene"),
                    "canon_fidelity_override": bool(item.get("canon_fidelity_override", False)),
                    "word_budget": item.get("word_budget"),
                    "instruction": instruction,
                    "placement_scene_type": str(item.get("placement_scene_type", "") or ""),
                    "placement_rule": str(item.get("placement_rule", "") or ""),
                    "anchor_pattern": str(item.get("anchor_pattern", "") or ""),
                    "marker_offset": str(item.get("marker_offset", "") or ""),
                })
    if out:
        return out

    legacy = visual_context.get("narrative_directives", []) if isinstance(visual_context, dict) else []
    if not isinstance(legacy, list):
        return []
    for idx, text in enumerate(legacy, start=1):
        instruction = str(text or "").strip()
        if not instruction:
            continue
        out.append({
            "id": f"legacy-d{idx}",
            "type": "atmospheric_frame",
            "priority": "recommended",
            "scope": "post_marker_scene",
            "canon_fidelity_override": False,
            "word_budget": None,
            "instruction": instruction,
        })
    return out


def build_adn_directive_receipt(illustration_id: str, entry: Dict[str, Any]) -> str:
    """Build §0 ADN directive receipt markdown for THINKING logs."""
    if not isinstance(entry, dict):
        return ""
    visual_context = entry.get("visual_ground_truth", {})
    directives = _coerce_typed_directives(entry, visual_context if isinstance(visual_context, dict) else {})
    if not directives:
        return ""
    scene_type = str(entry.get("placement_scene_type", "unknown") or "unknown")
    pov = str(entry.get("pov_character", "unknown") or "unknown")
    verification = str(entry.get("character_verification_status", "inferred") or "inferred")
    lines = [
        "## § 0 · ADN DIRECTIVE RECEIPT",
        f"**Illustration**: {illustration_id} · **Scene type**: {scene_type}",
        f"**POV**: {pov} · **Verification**: {verification}",
        "",
        "| DID | Type | Priority | Scope | Canon Override | Word Budget | Summary |",
        "|-----|------|----------|-------|----------------|-------------|---------|",
    ]
    for directive in directives:
        summary = str(directive.get("instruction", "")).strip().replace("\n", " ")
        if len(summary) > 70:
            summary = summary[:67] + "..."
        lines.append(
            f"| {directive.get('id', '')} | {directive.get('type', '')} | {directive.get('priority', '')} | "
            f"{directive.get('scope', '')} | {str(directive.get('canon_fidelity_override', False)).upper()} | "
            f"{directive.get('word_budget', '—') if directive.get('word_budget') is not None else '—'} | {summary} |"
        )
    lines.append("")
    return "\n".join(lines)


def build_visual_context_block(
    illustration_id: str,
    visual_context: Dict[str, Any],
    entry: Optional[Dict[str, Any]] = None,
    spoiler_prevention: Optional[Dict[str, Any]] = None,
    identity_resolution: Optional[Dict[str, Any]] = None,
    validation: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Build a visual context block for injection into the translation prompt.

    This formats the cached Gemini 3 Pro analysis as "Art Director's Notes"
    that guide Gemini 2.5 Pro's prose decisions.

    Args:
        illustration_id: ID of the illustration (e.g., 'illust-001').
        visual_context: The visual_ground_truth dict from cache.
        spoiler_prevention: Optional spoiler prevention rules.

    Returns:
        Formatted string block for prompt injection.
    """
    if not visual_context:
        return ""

    composition = visual_context.get("composition", "N/A")
    emotional_delta = visual_context.get("emotional_delta", "N/A")
    key_details = visual_context.get("key_details", {})
    entry = entry if isinstance(entry, dict) else {}
    directives = _coerce_typed_directives(entry, visual_context)

    lines = [
        f"--- ART DIRECTOR'S NOTES [{illustration_id}] ---",
        "Policy: Multimodal notes are descriptive only. Raw chapter text is canonical truth.",
        f"Scene Composition: {composition}",
        f"Emotional Context: {emotional_delta}",
    ]

    if key_details:
        lines.append("Key Visual Details:")
        for key, value in key_details.items():
            lines.append(f"  - {key}: {value}")

    if directives:
        lines.append("Translation Directives:")
        for d in directives:
            if isinstance(d, dict):
                did = str(d.get("id", "")).strip() or "directive"
                dtype = str(d.get("type", "")).strip() or "atmospheric_frame"
                instruction = str(d.get("instruction", "")).strip()
                if dtype == "placement_hint":
                    anchor_pattern = str(d.get("anchor_pattern", "")).strip()
                    placement_rule = str(d.get("placement_rule", "")).strip() or "before"
                    marker_offset = str(d.get("marker_offset", "")).strip() or "before_anchor"
                    scene_type = str(d.get("placement_scene_type", "")).strip()
                    details = []
                    if scene_type:
                        details.append(f"scene_type={scene_type}")
                    if anchor_pattern:
                        details.append(f"anchor={anchor_pattern}")
                    details.append(f"rule={placement_rule}")
                    details.append(f"offset={marker_offset}")
                    lines.append(
                        f"  - [{did} | {dtype}] {instruction}"
                        f" ({', '.join(details)})"
                    )
                else:
                    lines.append(f"  - [{did} | {dtype}] {instruction}")
            else:
                lines.append(f"  - {d}")

    if identity_resolution:
        recognized = identity_resolution.get("recognized_characters", [])
        unresolved = identity_resolution.get("unresolved_characters", [])
        if recognized:
            lines.append("Identity Resolution (scene-local lock):")
            for rec in recognized[:6]:
                if not isinstance(rec, dict):
                    continue
                canonical = str(rec.get("canonical_name", "")).strip()
                japanese = str(rec.get("japanese_name", "")).strip()
                confidence = rec.get("confidence", "")
                evidence = rec.get("non_color_evidence", [])
                label = canonical
                if japanese:
                    label += f" [{japanese}]"
                if isinstance(confidence, (int, float)):
                    label += f" confidence={confidence:.2f}"
                lines.append(f"  - {label}")
                if isinstance(evidence, list) and evidence:
                    lines.append(f"    evidence: {', '.join(str(e) for e in evidence[:4])}")
        if unresolved:
            lines.append("Unresolved Characters:")
            for desc in unresolved[:6]:
                lines.append(f"  - {desc}")

    if validation:
        identity_consistency = validation.get("identity_consistency", {})
        if isinstance(identity_consistency, dict):
            status = str(identity_consistency.get("status", "")).strip().lower()
            reason = str(identity_consistency.get("reason", "")).strip()
            if status in {"fail", "warn"}:
                lines.append(
                    "IDENTITY LOCK WARNING: Use neutral descriptors if identity confidence is uncertain. "
                    "Raw source text remains canonical truth."
                )
                if reason:
                    lines.append(f"Identity QA: {status} ({reason})")

    if spoiler_prevention:
        do_not_reveal = spoiler_prevention.get("do_not_reveal_before_text", [])
        if do_not_reveal:
            lines.append(f"SPOILER PREVENTION: Do not mention: {', '.join(do_not_reveal)}")

    lines.append("--- END ART DIRECTOR'S NOTES ---")

    return "\n".join(lines)


def build_lookahead_block(
    illustration_id: str,
    visual_context: Dict[str, Any]
) -> str:
    """
    Build a lighter visual context block for upcoming illustrations.

    Used for segments that appear BEFORE an illustration to allow
    emotional momentum buildup without spoiling the visual.

    Args:
        illustration_id: ID of the upcoming illustration.
        visual_context: The visual_ground_truth dict from cache.

    Returns:
        Formatted string block for prompt injection (lighter than full).
    """
    if not visual_context:
        return ""

    composition = visual_context.get("composition", "N/A")
    emotional_delta = visual_context.get("emotional_delta", "N/A")

    return (
        f"--- UPCOMING VISUAL CONTEXT [{illustration_id}] ---\n"
        f"Composition: {composition}\n"
        f"Emotional Tone: {emotional_delta}\n"
        f"Build emotional momentum toward this visual. Set the tone without spoiling.\n"
        f"--- END UPCOMING CONTEXT ---"
    )


def build_chapter_visual_guidance(
    illustration_ids: List[str],
    cache_manager: Any,
    enable_lookahead: bool = True,
    manifest: Optional[Dict[str, Any]] = None
) -> str:
    """
    Build aggregated visual guidance for an entire chapter.

    Collects all visual context blocks for illustrations found in the chapter
    and returns a single formatted string for prompt injection.
    
    Now integrates with Librarian's ruby extraction to enforce canon names.

    Args:
        illustration_ids: List of illustration IDs found in the chapter.
        cache_manager: VisualCacheManager instance with loaded cache.
        enable_lookahead: Whether to include lookahead context.
        manifest: Optional manifest dict for canon name enforcement.

    Returns:
        Combined visual guidance string, or empty string if no context.
    """
    if not illustration_ids:
        return ""

    # Initialize canon enforcer if manifest provided
    enforcer = None
    if manifest:
        enforcer = CanonNameEnforcer(manifest)

    blocks = []
    found_count = 0

    for illust_id in illustration_ids:
        entry = cache_manager.get_entry(illust_id) if hasattr(cache_manager, "get_entry") else {}
        visual_ctx = cache_manager.get_visual_context(illust_id)
        spoiler = cache_manager.get_spoiler_prevention(illust_id)
        identity_resolution = cache_manager.get_identity_resolution(illust_id)
        validation = cache_manager.get_validation(illust_id)

        if visual_ctx:
            # Enforce canon names in visual context
            if enforcer:
                visual_ctx = enforcer.enforce_in_visual_context(visual_ctx)
                if spoiler:
                    spoiler = enforcer.enforce_in_visual_context(spoiler)
                if identity_resolution:
                    identity_resolution = enforcer.enforce_in_visual_context(identity_resolution)
            
            block = build_visual_context_block(
                illust_id,
                visual_ctx,
                entry=entry,
                spoiler_prevention=spoiler,
                identity_resolution=identity_resolution,
                validation=validation,
            )
            blocks.append(block)
            found_count += 1
        else:
            logger.debug(f"[MULTIMODAL] No cached context for {illust_id}")

    if not blocks:
        return ""

    # Build header with Canon Event Fidelity directive and optional character reference
    header_lines = [
        CANON_EVENT_FIDELITY_DIRECTIVE,  # Add fidelity rules FIRST
        f"\n=== VISUAL CONTEXT (Pre-Analyzed by Art Director) ===",
        f"Illustrations with cached analysis: {found_count}/{len(illustration_ids)}",
        f"Apply these insights to enhance prose quality for illustrated scenes.",
        f"REMINDER: Art Director's Notes are STYLISTIC guides only. Do NOT add events from illustrations.",
        f"REMINDER: Multimodal is descriptive support only; source text is the only truth.",
    ]
    
    # Add character reference if available
    if enforcer and enforcer.canon_map:
        header_lines.append("")
        header_lines.append(enforcer.get_character_reference())
    
    header = "\n".join(header_lines) + "\n\n"

    return header + "\n\n".join(blocks) + "\n=== END VISUAL CONTEXT ===\n"


def build_visual_thinking_log(
    illustration_ids: List[str],
    volume_path: Path,
    cache_manager: Any = None,
) -> str:
    """
    Build a visual thinking log section for THINKING markdown files.
    
    Retrieves the Gemini 3 Pro thought summaries from cache/thoughts/*.json
    and formats them for inclusion in translation THINKING logs.
    
    Args:
        illustration_ids: List of illustration IDs processed in the chapter.
        volume_path: Path to the volume directory.
        
    Returns:
        Formatted markdown section with Gemini 3 Pro visual reasoning.
    """
    from modules.multimodal.thought_logger import ThoughtLogger
    
    if not illustration_ids:
        return ""
    
    thought_logger = ThoughtLogger(volume_path)
    sections = []
    
    for illust_id in illustration_ids:
        if cache_manager is not None and hasattr(cache_manager, "get_entry"):
            try:
                receipt = build_adn_directive_receipt(illust_id, cache_manager.get_entry(illust_id))
                if receipt:
                    sections.append(receipt)
            except Exception:
                pass

        log_entry = thought_logger.get_log(illust_id)
        
        if log_entry and log_entry.thoughts:
            section_lines = [
                f"### 🖼️ {illust_id}",
                f"**Model**: {log_entry.model}",
                f"**Thinking Level**: {log_entry.thinking_level}",
                f"**Processing Time**: {log_entry.processing_time_seconds:.1f}s",
                "",
            ]
            
            for i, thought in enumerate(log_entry.thoughts):
                if i > 0:
                    section_lines.append("")
                section_lines.append("**Gemini 3 Pro Visual Reasoning:**")
                section_lines.append("```")
                # Truncate very long thoughts for readability
                if len(thought) > 3000:
                    section_lines.append(thought[:3000] + "...")
                else:
                    section_lines.append(thought)
                section_lines.append("```")
            
            sections.append("\n".join(section_lines))
    
    if not sections:
        return ""
    
    header = [
        "## 🧠 Gemini 3 Pro Visual Thinking Log",
        "",
        "The following captures Gemini 3 Pro's internal reasoning during Phase 1.6",
        "visual analysis. These thought summaries reveal how the model interpreted",
        "each illustration before generating Art Director's Notes.",
        "",
    ]
    
    return "\n".join(header) + "\n\n".join(sections)

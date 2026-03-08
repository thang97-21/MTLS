"""Glossary lookup helper for translator tool mode."""

from __future__ import annotations

from typing import Any, Dict


def _lookup_entry(term_jp: str, metadata_en: Dict[str, Any], rich_metadata: Dict[str, Any]) -> Dict[str, Any] | None:
    rich_rules = rich_metadata.get("translation_rules", {}) if isinstance(rich_metadata, dict) else {}
    rich_cultural = rich_metadata.get("cultural_terms", {}) if isinstance(rich_metadata, dict) else {}
    meta_profiles = metadata_en.get("character_profiles", {}) if isinstance(metadata_en, dict) else {}
    meta_names = metadata_en.get("character_names", {}) if isinstance(metadata_en, dict) else {}

    if isinstance(rich_rules, dict) and isinstance(rich_rules.get(term_jp), dict):
        return rich_rules[term_jp]
    if isinstance(rich_cultural, dict) and isinstance(rich_cultural.get(term_jp), dict):
        return rich_cultural[term_jp]
    if isinstance(meta_profiles, dict) and isinstance(meta_profiles.get(term_jp), dict):
        return meta_profiles[term_jp]
    if isinstance(meta_names, dict) and term_jp in meta_names:
        return {
            "first_occurrence_form": str(meta_names[term_jp]),
            "callback_form": str(meta_names[term_jp]),
        }
    return None


def handle_validate_glossary_term(
    tool_input: Dict[str, Any],
    metadata_en: Dict[str, Any],
    rich_metadata: Dict[str, Any],
    chapter_occurrence_tracker: Dict[str, bool],
) -> str:
    """Return the canonical glossary rendering guidance for one JP term."""

    term_jp = str(tool_input.get("term_jp") or "").strip()
    if not term_jp:
        return "No term provided. Use your best judgment."

    entry = _lookup_entry(term_jp, metadata_en, rich_metadata)
    if not entry:
        return f"No glossary entry found for '{term_jp}'. Use your best judgment."

    is_first_occurrence = term_jp not in chapter_occurrence_tracker
    chapter_occurrence_tracker[term_jp] = True

    first_form = str(
        entry.get("first_occurrence_form")
        or entry.get("rendered_as")
        or entry.get("localized_name")
        or entry.get("callback_form")
        or term_jp
    ).strip()
    callback_form = str(
        entry.get("callback_form")
        or entry.get("rendered_as")
        or entry.get("localized_name")
        or first_form
    ).strip()
    jit_explanation = str(entry.get("jit_explanation") or "").strip()

    if is_first_occurrence:
        if jit_explanation:
            return (
                f"FIRST OCCURRENCE. Use full form '{first_form}'. "
                f"Inline explanation: '{jit_explanation}'."
            )
        return f"FIRST OCCURRENCE. Use full form '{first_form}'."

    return f"CALLBACK OCCURRENCE. Use short form '{callback_form}'."

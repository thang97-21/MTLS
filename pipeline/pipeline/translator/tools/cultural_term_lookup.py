"""Demand-driven cultural term lookup helper."""

from __future__ import annotations

import json
from typing import Any, Dict


def handle_lookup_cultural_term(
    tool_input: Dict[str, Any],
    rich_metadata: Dict[str, Any],
    volume_metadata: Dict[str, Any],
) -> str:
    """Look up a cultural term in rich metadata or fall back to general handling.

    Priority chain:
      1. culturally_loaded_terms  (ECR retention-policy block — Component 1)
      2. cultural_terms           (legacy glossary)
      3. mythology, translation_rules
      4. volume glossary
    """

    term = str(tool_input.get("term") or "").strip()
    if not term:
        return "No term provided. Use general cultural retention policy."

    # ── 1. ECR: culturally_loaded_terms (highest priority) ──────────────────
    clt = rich_metadata.get("culturally_loaded_terms", {}) if isinstance(rich_metadata, dict) else {}
    if isinstance(clt, dict) and term in clt:
        entry = clt[term]
        if isinstance(entry, dict):
            policy = entry.get("retention_policy", "context_dependent")
            canonical_jp = entry.get("canonical_jp", term)
            romaji = entry.get("romaji", "")
            usage = entry.get("usage_context", "")
            notes = entry.get("notes", "")
            display = romaji if romaji else canonical_jp
            base_note = f" ({notes})" if notes else ""
            if policy == "preserve_jp":
                return (
                    f"ECR RETAIN JP: Use '{display}' directly in translation. "
                    f"Do NOT transcreate or substitute with English.{base_note} {usage}"
                ).strip()
            elif policy == "preserve_jp_first_use":
                return (
                    f"ECR RETAIN JP (first use): Use '{display}' on first occurrence "
                    f"with a brief inline gloss; use short form thereafter.{base_note} {usage}"
                ).strip()
            elif policy == "transcreate":
                return (
                    f"ECR TRANSCREATE: Always render '{canonical_jp}' in English. "
                    f"JP form is informational only.{base_note} {usage}"
                ).strip()
            else:  # context_dependent
                return (
                    f"ECR CONTEXT-DEPENDENT: '{display}' — "
                    f"keep JP form when used as label/archetype; use EN when purely descriptive.{base_note} {usage}"
                ).strip()

    # ── 2–4. Legacy fallback chain ───────────────────────────────────────────
    for section in ("cultural_terms", "mythology", "translation_rules"):
        section_data = rich_metadata.get(section, {}) if isinstance(rich_metadata, dict) else {}
        if isinstance(section_data, dict) and term in section_data:
            entry = section_data[term]
            return (
                f"Found '{term}' in {section}: "
                f"{json.dumps(entry, ensure_ascii=False)}"
            )

    glossary = volume_metadata.get("glossary", {}) if isinstance(volume_metadata, dict) else {}
    if isinstance(glossary, dict) and term in glossary:
        entry = glossary[term]
        return (
            f"Found '{term}' in volume glossary: "
            f"{json.dumps(entry, ensure_ascii=False)}"
        )

    return (
        f"No entry found for '{term}'. Apply general cultural retention policy: "
        "retain the source form on first use with a minimal inline gloss, then use "
        "the short callback form."
    )

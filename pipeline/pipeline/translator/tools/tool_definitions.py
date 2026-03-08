"""Anthropic tool definitions for translator tool mode."""

from __future__ import annotations

from typing import Any, Dict, List

TOOL_NAME_DECLARE_TRANSLATION_PARAMETERS = "declare_translation_parameters"
TOOL_NAME_VALIDATE_GLOSSARY_TERM = "validate_glossary_term"
TOOL_NAME_LOOKUP_CULTURAL_TERM = "lookup_cultural_term"
TOOL_NAME_REPORT_TRANSLATION_QC = "report_translation_qc"
TOOL_NAME_FLAG_STRUCTURAL_CONSTRAINT = "flag_structural_constraint"


TRANSLATION_TOOL_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    TOOL_NAME_DECLARE_TRANSLATION_PARAMETERS: {
        "name": TOOL_NAME_DECLARE_TRANSLATION_PARAMETERS,
        "description": (
            "Declare your chapter-level translation parameters before generating any "
            "output. Call this exactly once at the start of each chapter. Your "
            "declared parameters become the QC ground truth for this chapter."
        ),
        "input_schema": {
            "type": "object",
            "required": [
                "chapter_id",
                "eps_band",
                "contraction_targets",
                "voice_mode",
            ],
            "properties": {
                "chapter_id": {
                    "type": "string",
                    "description": "The chapter ID being translated.",
                },
                "eps_band": {
                    "type": "string",
                    "enum": ["COLD", "COOL", "WARM", "HOT"],
                    "description": "Dominant emotional register for this chapter.",
                },
                "contraction_targets": {
                    "type": "object",
                    "required": ["narration_rate", "protagonist_dialogue_rate"],
                    "properties": {
                        "narration_rate": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "protagonist_dialogue_rate": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                        "heroine_dialogue_rate": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                        "hot_band_override_rate": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                        "secondary_character_rate": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                    },
                },
                "voice_mode": {
                    "type": "string",
                    "enum": [
                        "physical_somatic_sdt",
                        "analytical_introspection",
                        "lyrical_memoir",
                        "comic_relief",
                        "expository_cool",
                        "fragmented_trauma",
                    ],
                },
                "motif_anchors": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "forbidden_vocab_overrides": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "structural_notes": {"type": "string"},
            },
        },
    },
    TOOL_NAME_VALIDATE_GLOSSARY_TERM: {
        "name": TOOL_NAME_VALIDATE_GLOSSARY_TERM,
        "description": (
            "Before rendering a glossary-controlled term, call this to confirm the "
            "correct translated form and whether this is a first occurrence or a callback."
        ),
        "input_schema": {
            "type": "object",
            "required": ["term_jp"],
            "properties": {
                "term_jp": {"type": "string"},
                "context_sentence": {"type": "string"},
            },
        },
    },
    TOOL_NAME_LOOKUP_CULTURAL_TERM: {
        "name": TOOL_NAME_LOOKUP_CULTURAL_TERM,
        "description": (
            "Look up a cultural term, institution, or proper noun not covered in "
            "current context."
        ),
        "input_schema": {
            "type": "object",
            "required": ["term"],
            "properties": {
                "term": {"type": "string"},
                "term_category": {
                    "type": "string",
                    "enum": [
                        "music_industry",
                        "internet_culture",
                        "publishing",
                        "geography",
                        "honorific",
                        "food",
                        "other",
                    ],
                },
                "handling_question": {"type": "string"},
            },
        },
    },
    TOOL_NAME_REPORT_TRANSLATION_QC: {
        "name": TOOL_NAME_REPORT_TRANSLATION_QC,
        "description": (
            "After completing the chapter translation, report QC observations and "
            "confidence assessments before finalizing output."
        ),
        "input_schema": {
            "type": "object",
            "required": [
                "chapter_id",
                "self_assessed_contraction_rate",
                "hot_band_passages_handled",
            ],
            "properties": {
                "chapter_id": {"type": "string"},
                "self_assessed_contraction_rate": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "hot_band_passages_handled": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "passage_description": {"type": "string"},
                            "technique_applied": {"type": "string"},
                            "confidence": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                        },
                    },
                },
                "filter_words_used": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "glossary_terms_rendered": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "term_jp": {"type": "string"},
                            "rendered_as": {"type": "string"},
                            "occurrence_type": {
                                "type": "string",
                                "enum": ["first", "callback"],
                            },
                        },
                    },
                },
                "structural_constraints_satisfied": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "issues_flagged": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "issue": {"type": "string"},
                            "severity": {
                                "type": "string",
                                "enum": ["critical", "minor", "cosmetic"],
                            },
                            "passage": {"type": "string"},
                        },
                    },
                },
            },
        },
    },
    TOOL_NAME_FLAG_STRUCTURAL_CONSTRAINT: {
        "name": TOOL_NAME_FLAG_STRUCTURAL_CONSTRAINT,
        "description": (
            "Register a cross-chapter structural requirement created in this chapter."
        ),
        "input_schema": {
            "type": "object",
            "required": [
                "constraint_type",
                "description",
                "source_chapter",
                "target_chapter_pattern",
            ],
            "properties": {
                "constraint_type": {
                    "type": "string",
                    "enum": [
                        "callback_phrase",
                        "pov_mirror",
                        "motif_payoff",
                        "character_arc_beat",
                        "structural_echo",
                    ],
                },
                "description": {"type": "string"},
                "source_chapter": {"type": "string"},
                "target_chapter_pattern": {"type": "string"},
                "exact_phrase": {"type": "string"},
                "severity": {
                    "type": "string",
                    "enum": ["MUST_FIX", "SHOULD_FIX"],
                },
            },
        },
    },
}


def build_translation_tools(
    tool_mode_config: Dict[str, Any] | None,
    *,
    include_declare: bool = True,
) -> List[Dict[str, Any]]:
    """Resolve enabled tool definitions from tool_mode config."""

    config = tool_mode_config or {}
    enabled_map = config.get("tools", {}) if isinstance(config, dict) else {}
    if not isinstance(enabled_map, dict):
        enabled_map = {}

    default_enabled = {
        TOOL_NAME_DECLARE_TRANSLATION_PARAMETERS: True,
        TOOL_NAME_VALIDATE_GLOSSARY_TERM: True,
        TOOL_NAME_LOOKUP_CULTURAL_TERM: True,
        TOOL_NAME_REPORT_TRANSLATION_QC: True,
        TOOL_NAME_FLAG_STRUCTURAL_CONSTRAINT: True,
    }

    tools: List[Dict[str, Any]] = []
    for name, definition in TRANSLATION_TOOL_DEFINITIONS.items():
        if name == TOOL_NAME_DECLARE_TRANSLATION_PARAMETERS and not include_declare:
            continue
        enabled = bool(enabled_map.get(name, default_enabled.get(name, False)))
        if enabled:
            tools.append(definition)
    return tools

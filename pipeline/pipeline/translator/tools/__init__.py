"""Tool-use scaffolding for the Anthropic translation path."""

from pipeline.translator.tools.cultural_term_lookup import handle_lookup_cultural_term
from pipeline.translator.tools.glossary_validator import handle_validate_glossary_term
from pipeline.translator.tools.qc_reporter import (
    TranslationQcSelfReport,
    handle_report_translation_qc,
)
from pipeline.translator.tools.structural_constraint_flagger import (
    StructuralConstraintFlag,
    handle_flag_structural_constraint,
)
from pipeline.translator.tools.tool_definitions import (
    TOOL_NAME_DECLARE_TRANSLATION_PARAMETERS,
    TOOL_NAME_FLAG_STRUCTURAL_CONSTRAINT,
    TOOL_NAME_LOOKUP_CULTURAL_TERM,
    TOOL_NAME_REPORT_TRANSLATION_QC,
    TOOL_NAME_VALIDATE_GLOSSARY_TERM,
    TRANSLATION_TOOL_DEFINITIONS,
    build_translation_tools,
)
from pipeline.translator.tools.translation_parameter_handler import (
    DeclaredTranslationParameters,
    handle_declare_translation_parameters,
)

__all__ = [
    "DeclaredTranslationParameters",
    "StructuralConstraintFlag",
    "TOOL_NAME_DECLARE_TRANSLATION_PARAMETERS",
    "TOOL_NAME_FLAG_STRUCTURAL_CONSTRAINT",
    "TOOL_NAME_LOOKUP_CULTURAL_TERM",
    "TOOL_NAME_REPORT_TRANSLATION_QC",
    "TOOL_NAME_VALIDATE_GLOSSARY_TERM",
    "TRANSLATION_TOOL_DEFINITIONS",
    "TranslationQcSelfReport",
    "build_translation_tools",
    "handle_declare_translation_parameters",
    "handle_flag_structural_constraint",
    "handle_lookup_cultural_term",
    "handle_report_translation_qc",
    "handle_validate_glossary_term",
]

"""Structured QC self-report normalization."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict


@dataclass
class TranslationQcSelfReport:
    chapter_id: str
    self_assessed_contraction_rate: float
    hot_band_passages_handled: list[Dict[str, Any]] = field(default_factory=list)
    filter_words_used: list[str] = field(default_factory=list)
    glossary_terms_rendered: list[Dict[str, Any]] = field(default_factory=list)
    structural_constraints_satisfied: list[str] = field(default_factory=list)
    issues_flagged: list[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def handle_report_translation_qc(tool_input: Dict[str, Any]) -> TranslationQcSelfReport:
    """Normalize the model's structured QC report."""

    chapter_id = str(tool_input.get("chapter_id") or "").strip()
    if not chapter_id:
        raise ValueError("chapter_id is required")

    try:
        contraction_rate = float(tool_input.get("self_assessed_contraction_rate", 0.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("self_assessed_contraction_rate must be numeric") from exc

    if not 0.0 <= contraction_rate <= 1.0:
        raise ValueError("self_assessed_contraction_rate must be between 0.0 and 1.0")

    def _list_of_strings(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _list_of_dicts(value: Any) -> list[Dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    return TranslationQcSelfReport(
        chapter_id=chapter_id,
        self_assessed_contraction_rate=contraction_rate,
        hot_band_passages_handled=_list_of_dicts(tool_input.get("hot_band_passages_handled")),
        filter_words_used=_list_of_strings(tool_input.get("filter_words_used")),
        glossary_terms_rendered=_list_of_dicts(tool_input.get("glossary_terms_rendered")),
        structural_constraints_satisfied=_list_of_strings(
            tool_input.get("structural_constraints_satisfied")
        ),
        issues_flagged=_list_of_dicts(tool_input.get("issues_flagged")),
    )

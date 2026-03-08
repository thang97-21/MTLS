"""Cross-chapter structural constraint normalization."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict


@dataclass
class StructuralConstraintFlag:
    constraint_type: str
    description: str
    source_chapter: str
    target_chapter_pattern: str
    exact_phrase: str = ""
    severity: str = "SHOULD_FIX"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def handle_flag_structural_constraint(tool_input: Dict[str, Any]) -> StructuralConstraintFlag:
    """Normalize one model-emitted structural constraint record."""

    return StructuralConstraintFlag(
        constraint_type=str(tool_input.get("constraint_type") or "").strip(),
        description=str(tool_input.get("description") or "").strip(),
        source_chapter=str(tool_input.get("source_chapter") or "").strip(),
        target_chapter_pattern=str(tool_input.get("target_chapter_pattern") or "").strip(),
        exact_phrase=str(tool_input.get("exact_phrase") or "").strip(),
        severity=str(tool_input.get("severity") or "SHOULD_FIX").strip() or "SHOULD_FIX",
    )

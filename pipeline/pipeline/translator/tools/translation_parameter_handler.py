"""Chapter-level translation parameter commit handler."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Tuple


_EPS_BANDS = {"COLD", "COOL", "WARM", "HOT"}
_VOICE_MODES = {
    "physical_somatic_sdt",
    "analytical_introspection",
    "lyrical_memoir",
    "comic_relief",
    "expository_cool",
    "fragmented_trauma",
}
_RATE_KEYS = {
    "narration_rate",
    "protagonist_dialogue_rate",
    "heroine_dialogue_rate",
    "hot_band_override_rate",
    "secondary_character_rate",
}


@dataclass
class DeclaredTranslationParameters:
    chapter_id: str
    eps_band: str
    contraction_targets: Dict[str, float]
    voice_mode: str
    motif_anchors: list[str] = field(default_factory=list)
    forbidden_vocab_overrides: list[str] = field(default_factory=list)
    structural_notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _coerce_rate(value: Any, key: str) -> float:
    try:
        rate = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be numeric") from exc
    if not 0.0 <= rate <= 1.0:
        raise ValueError(f"{key} must be between 0.0 and 1.0")
    return rate


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("expected a list of strings")
    cleaned: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            cleaned.append(text)
    return cleaned


def handle_declare_translation_parameters(
    tool_input: Dict[str, Any],
) -> Tuple[str, DeclaredTranslationParameters]:
    """Validate and normalize the model's chapter-level parameter declaration."""

    chapter_id = str(tool_input.get("chapter_id") or "").strip()
    if not chapter_id:
        raise ValueError("chapter_id is required")

    eps_band = str(tool_input.get("eps_band") or "").strip().upper()
    if eps_band not in _EPS_BANDS:
        raise ValueError(f"eps_band must be one of {sorted(_EPS_BANDS)}")

    voice_mode = str(tool_input.get("voice_mode") or "").strip()
    if voice_mode not in _VOICE_MODES:
        raise ValueError(f"voice_mode must be one of {sorted(_VOICE_MODES)}")

    raw_targets = tool_input.get("contraction_targets") or {}
    if not isinstance(raw_targets, dict):
        raise ValueError("contraction_targets must be an object")

    contraction_targets: Dict[str, float] = {}
    for key, value in raw_targets.items():
        if key in _RATE_KEYS:
            contraction_targets[key] = _coerce_rate(value, key)

    for required_key in ("narration_rate", "protagonist_dialogue_rate"):
        if required_key not in contraction_targets:
            raise ValueError(f"contraction_targets.{required_key} is required")

    params = DeclaredTranslationParameters(
        chapter_id=chapter_id,
        eps_band=eps_band,
        contraction_targets=contraction_targets,
        voice_mode=voice_mode,
        motif_anchors=_coerce_string_list(tool_input.get("motif_anchors")),
        forbidden_vocab_overrides=_coerce_string_list(
            tool_input.get("forbidden_vocab_overrides")
        ),
        structural_notes=str(tool_input.get("structural_notes") or "").strip(),
    )

    result_msg = (
        f"Parameters committed for {params.chapter_id}. "
        f"EPS band={params.eps_band}. "
        f"Narration contraction target={params.contraction_targets.get('narration_rate', 'N/A')}. "
        f"Voice mode={params.voice_mode}. Proceed with translation."
    )
    return result_msg, params

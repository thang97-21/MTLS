from __future__ import annotations

from typing import Any, Dict, List, Optional

EPS_SIGNAL_WEIGHTS: Dict[str, float] = {
    "keigo_shift": 0.30,
    "sentence_length_delta": 0.20,
    "particle_signature": 0.15,
    "pronoun_shift": 0.15,
    "dialogue_volume": 0.10,
    "direct_address": 0.10,
}

EPS_SIGNAL_KEYS = tuple(EPS_SIGNAL_WEIGHTS.keys())

DEFAULT_CALIBRATION: Dict[str, Any] = {
    "enabled": True,
    "weak_evidence": {
        "threshold": 0.22,
        "shrink": 0.35,
    },
    "continuity": {
        "max_jump_per_chapter": 0.65,
    },
    "trope_bias": {
        "enabled": True,
        "cool_beauty": {
            "raw_score_gate": 0.45,
            "min_intimacy": 0.20,
            "penalty": -0.12,
        },
        "tsundere": {
            "raw_score_gate": 0.35,
            "keigo_conflict_penalty": -0.08,
        },
        "gyaru": {
            "dialogue_volume_gate": 0.25,
            "particle_gate": 0.15,
            "bonus": 0.05,
        },
    },
}


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _deep_merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _resolve_calibration(calibration: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(calibration, dict):
        return DEFAULT_CALIBRATION
    return _deep_merge_dict(DEFAULT_CALIBRATION, calibration)


def _eps_to_band(eps: float) -> str:
    if eps <= -0.5:
        return "COLD"
    if eps <= -0.1:
        return "COOL"
    if eps < 0.1:
        return "NEUTRAL"
    if eps < 0.5:
        return "WARM"
    return "HOT"


def _normalize_signals(signals: Any) -> Dict[str, float]:
    src = signals if isinstance(signals, dict) else {}
    return {
        key: _clamp(_to_float(src.get(key, 0.0)), -1.0, 1.0)
        for key in EPS_SIGNAL_KEYS
    }


def _weighted_eps(signals: Dict[str, float]) -> float:
    denom = sum(EPS_SIGNAL_WEIGHTS.values())
    if denom <= 0:
        return 0.0
    weighted = sum(signals[k] * EPS_SIGNAL_WEIGHTS[k] for k in EPS_SIGNAL_KEYS)
    return _clamp(weighted / denom, -1.0, 1.0)


def _evidence_strength(signals: Dict[str, float]) -> float:
    return sum(abs(signals[k]) * EPS_SIGNAL_WEIGHTS[k] for k in EPS_SIGNAL_KEYS)


def _trope_bias(archetype: str, signals: Dict[str, float], raw_score: float, cfg: Dict[str, Any]) -> float:
    name = str(archetype or "").lower()
    trope_cfg = cfg.get("trope_bias", {}) if isinstance(cfg.get("trope_bias"), dict) else {}
    if not bool(trope_cfg.get("enabled", True)):
        return 0.0
    cool_cfg = trope_cfg.get("cool_beauty", {}) if isinstance(trope_cfg.get("cool_beauty"), dict) else {}
    tsu_cfg = trope_cfg.get("tsundere", {}) if isinstance(trope_cfg.get("tsundere"), dict) else {}
    gyaru_cfg = trope_cfg.get("gyaru", {}) if isinstance(trope_cfg.get("gyaru"), dict) else {}

    # Cool-beauty / kuudere style characters should not jump to HOT
    # without direct intimacy markers (pronoun + direct address + particles).
    if any(tag in name for tag in ("kuudere", "cool beauty", "ice queen", "stoic")):
        intimacy = (
            0.45 * max(0.0, signals["pronoun_shift"])
            + 0.35 * max(0.0, signals["direct_address"])
            + 0.20 * max(0.0, signals["particle_signature"])
        )
        raw_score_gate = _to_float(cool_cfg.get("raw_score_gate", 0.45), 0.45)
        min_intimacy = _to_float(cool_cfg.get("min_intimacy", 0.20), 0.20)
        penalty = _to_float(cool_cfg.get("penalty", -0.12), -0.12)
        if raw_score > raw_score_gate and intimacy < min_intimacy:
            return penalty

    # Tsundere often oscillates; avoid over-optimistic warmth when keigo still high.
    if "tsundere" in name:
        raw_score_gate = _to_float(tsu_cfg.get("raw_score_gate", 0.35), 0.35)
        penalty = _to_float(tsu_cfg.get("keigo_conflict_penalty", -0.08), -0.08)
        if raw_score > raw_score_gate and signals["keigo_shift"] < 0.0:
            return penalty

    # Gyaru/genki types can be naturally warm in dialogue-heavy scenes.
    if any(tag in name for tag in ("gyaru", "genki", "teasing")):
        dialogue_gate = _to_float(gyaru_cfg.get("dialogue_volume_gate", 0.25), 0.25)
        particle_gate = _to_float(gyaru_cfg.get("particle_gate", 0.15), 0.15)
        bonus = _to_float(gyaru_cfg.get("bonus", 0.05), 0.05)
        if signals["dialogue_volume"] > dialogue_gate and signals["particle_signature"] > particle_gate:
            return bonus

    return 0.0


def _build_archetype_map(voice_fingerprints: Any) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    if not isinstance(voice_fingerprints, list):
        return mapping
    for fp in voice_fingerprints:
        if not isinstance(fp, dict):
            continue
        name = str(fp.get("canonical_name_en", "")).strip().lower()
        if not name:
            continue
        mapping[name] = str(fp.get("archetype", "")).strip()
    return mapping


def calibrate_eps_chapters(
    chapters: Any,
    voice_fingerprints: Any,
    calibration: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Deterministically calibrate chapter EPS payload for LN-style stability.

    - Recomputes eps_score from the canonical 6 weighted signals.
    - Applies conservative trope-aware adjustments by archetype.
    - Damps implausible chapter-to-chapter jumps to reduce noise.
    - Pulls weak-evidence estimates toward NEUTRAL.
    """
    if not isinstance(chapters, list):
        return chapters

    cfg = _resolve_calibration(calibration)
    if not bool(cfg.get("enabled", True)):
        return chapters

    weak_cfg = cfg.get("weak_evidence", {}) if isinstance(cfg.get("weak_evidence"), dict) else {}
    cont_cfg = cfg.get("continuity", {}) if isinstance(cfg.get("continuity"), dict) else {}
    weak_threshold = _clamp(_to_float(weak_cfg.get("threshold", 0.22), 0.22), 0.0, 1.0)
    weak_shrink = _clamp(_to_float(weak_cfg.get("shrink", 0.35), 0.35), 0.0, 1.0)
    max_jump = _clamp(_to_float(cont_cfg.get("max_jump_per_chapter", 0.65), 0.65), 0.0, 2.0)

    archetype_by_name = _build_archetype_map(voice_fingerprints)
    previous_eps: Dict[str, float] = {}

    for chapter_payload in chapters:
        if not isinstance(chapter_payload, dict):
            continue

        eps_data = chapter_payload.get("emotional_proximity_signals")
        if not isinstance(eps_data, dict):
            continue

        for character_name, signal_data in eps_data.items():
            if not isinstance(signal_data, dict):
                continue

            canonical = str(character_name or "").strip().lower()
            archetype = archetype_by_name.get(canonical, "")
            signals = _normalize_signals(signal_data.get("signals", {}))
            raw_score = _weighted_eps(signals)
            score = raw_score + _trope_bias(archetype, signals, raw_score, cfg)

            strength = _evidence_strength(signals)
            if strength < weak_threshold:
                score *= weak_shrink

            prev = previous_eps.get(canonical)
            if prev is not None:
                delta = score - prev
                if abs(delta) > max_jump:
                    score = prev + (max_jump if delta > 0 else -max_jump)

            score = _clamp(score, -1.0, 1.0)
            signal_data["signals"] = signals
            signal_data["eps_score"] = round(score, 3)
            signal_data["voice_band"] = _eps_to_band(score)
            previous_eps[canonical] = score

    return chapters

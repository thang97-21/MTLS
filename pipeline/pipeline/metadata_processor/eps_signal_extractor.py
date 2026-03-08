from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple


POLITE_MARKERS = ("です", "ます", "でした", "ません", "ございます", "ください", "ませんか")
CASUAL_MARKERS = ("だよ", "だね", "だな", "じゃん", "かな", "かも", "ぞ", "ぜ", "だ")
CASUAL_PARTICLES = ("ね", "よ", "ぞ", "ぜ", "さ", "な", "わ", "かしら")
FORMAL_PRONOUNS = ("私", "わたくし")
CASUAL_PRONOUNS = ("俺", "あたし", "うち", "僕", "ぼく")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _normalize_score(value: float, scale: float = 1.0) -> float:
    if scale <= 0:
        return 0.0
    return _clamp(value / scale, -1.0, 1.0)


def _read_chapter_text(work_dir: Path, manifest: Dict[str, Any], chapter_id: str) -> str:
    chapters = manifest.get("chapters", [])
    if not isinstance(chapters, list):
        return ""
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        if str(chapter.get("id", "")).strip() != chapter_id:
            continue
        jp_file = chapter.get("jp_file") or chapter.get("source_file")
        if not jp_file:
            return ""
        path = work_dir / "JP" / str(jp_file)
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return ""
    return ""


def _dialogue_segments(text: str) -> List[str]:
    return re.findall(r"「([^」]+)」", text)


def _sentence_chunks(text: str) -> List[str]:
    chunks = [x.strip() for x in re.split(r"[。！？!?\n]+", text) if x.strip()]
    return chunks


def _find_context_windows(text: str, needle: str, window_chars: int) -> List[str]:
    windows: List[str] = []
    if not needle:
        return windows
    start = 0
    while True:
        idx = text.find(needle, start)
        if idx < 0:
            break
        lo = max(0, idx - window_chars)
        hi = min(len(text), idx + len(needle) + window_chars)
        windows.append(text[lo:hi])
        start = idx + len(needle)
    return windows


def _count_any(text: str, needles: Tuple[str, ...]) -> int:
    return sum(text.count(token) for token in needles)


def _compute_signals(chapter_text: str, contexts: List[str], mention_count: int) -> Dict[str, float]:
    if not chapter_text:
        return {
            "keigo_shift": 0.0,
            "sentence_length_delta": 0.0,
            "particle_signature": 0.0,
            "pronoun_shift": 0.0,
            "dialogue_volume": 0.0,
            "direct_address": 0.0,
        }

    chapter_dialogue = _dialogue_segments(chapter_text)
    chapter_dialogue_text = "\n".join(chapter_dialogue)

    context_text = "\n".join(contexts) if contexts else ""
    context_dialogue = _dialogue_segments(context_text)
    context_dialogue_text = "\n".join(context_dialogue)

    polite = _count_any(context_text or chapter_text, POLITE_MARKERS)
    casual = _count_any(context_text or chapter_text, CASUAL_MARKERS)
    keigo_shift = _normalize_score(casual - polite, scale=8.0)

    chapter_sentences = _sentence_chunks(chapter_text)
    context_sentences = _sentence_chunks(context_text) if context_text else []
    chapter_avg = (
        sum(len(s) for s in chapter_sentences) / max(1, len(chapter_sentences))
        if chapter_sentences
        else 0.0
    )
    context_avg = (
        sum(len(s) for s in context_sentences) / max(1, len(context_sentences))
        if context_sentences
        else chapter_avg
    )
    sentence_length_delta = 0.0
    if chapter_avg > 0:
        sentence_length_delta = _normalize_score((context_avg - chapter_avg) / chapter_avg, scale=0.6)

    casual_particles = _count_any(context_dialogue_text or chapter_dialogue_text, CASUAL_PARTICLES)
    particle_signature = _normalize_score(casual_particles, scale=12.0)

    formal_pronouns = _count_any(context_dialogue_text or chapter_dialogue_text, FORMAL_PRONOUNS)
    casual_pronouns = _count_any(context_dialogue_text or chapter_dialogue_text, CASUAL_PRONOUNS)
    pronoun_shift = _normalize_score(casual_pronouns - formal_pronouns, scale=6.0)

    dialogue_ratio = len(chapter_dialogue_text) / max(1, len(chapter_text))
    dialogue_volume = _normalize_score((dialogue_ratio * 2.0) - 0.5, scale=1.0)

    direct_address = _normalize_score(float(mention_count), scale=4.0)

    return {
        "keigo_shift": round(keigo_shift, 3),
        "sentence_length_delta": round(sentence_length_delta, 3),
        "particle_signature": round(particle_signature, 3),
        "pronoun_shift": round(pronoun_shift, 3),
        "dialogue_volume": round(dialogue_volume, 3),
        "direct_address": round(direct_address, 3),
    }


def _build_alias_map(character_names: Dict[str, Any]) -> Dict[str, str]:
    alias_to_en: Dict[str, str] = {}
    if not isinstance(character_names, dict):
        return alias_to_en
    for jp_name, en_name in character_names.items():
        jp = str(jp_name or "").strip()
        en = str(en_name or "").strip()
        if not jp or not en:
            continue
        alias_to_en[jp] = en
    return alias_to_en


def extract_deterministic_eps_signals(
    work_dir: Path,
    manifest: Dict[str, Any],
    character_names: Dict[str, Any],
    chapter_ids: List[str],
    config: Dict[str, Any] | None = None,
) -> Dict[str, Dict[str, Dict[str, float]]]:
    """
    Deterministically compute raw EPS signals from JP text for each chapter.

    Returns mapping:
      chapter_id -> canonical_name_en -> signals dict
    """
    cfg = config if isinstance(config, dict) else {}
    enabled = bool(cfg.get("enabled", False))
    if not enabled:
        return {}

    min_mentions = int(max(1, cfg.get("min_name_mentions", 1) or 1))
    window_chars = int(max(40, cfg.get("window_chars", 120) or 120))
    include_unknown_pov = bool(cfg.get("include_unknown_pov", True))

    alias_map = _build_alias_map(character_names)

    extracted: Dict[str, Dict[str, Dict[str, float]]] = {}
    for chapter_id in chapter_ids:
        chapter_text = _read_chapter_text(work_dir, manifest, chapter_id)
        if not chapter_text:
            continue

        chapter_result: Dict[str, Dict[str, float]] = {}
        for jp_alias, canonical_en in alias_map.items():
            contexts = _find_context_windows(chapter_text, jp_alias, window_chars)
            mention_count = len(contexts)
            if mention_count < min_mentions:
                continue
            signals = _compute_signals(chapter_text, contexts, mention_count)
            chapter_result[canonical_en] = signals

        if include_unknown_pov and "Unknown" not in chapter_result:
            chapter_result["Unknown"] = _compute_signals(
                chapter_text=chapter_text,
                contexts=[],
                mention_count=0,
            )

        if chapter_result:
            extracted[str(chapter_id)] = chapter_result

    return extracted

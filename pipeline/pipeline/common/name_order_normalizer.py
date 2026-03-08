"""
Name-order normalization helpers.

Normalizes persisted metadata and downstream artifacts to match the volume's
declared world_setting.name_order policy.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


def resolve_name_order_policy(manifest: Dict[str, Any]) -> str:
    metadata_en = manifest.get("metadata_en", {}) if isinstance(manifest, dict) else {}
    if not isinstance(metadata_en, dict):
        metadata_en = {}
    world_setting = metadata_en.get("world_setting", {})
    if not isinstance(world_setting, dict):
        world_setting = {}
    name_order = world_setting.get("name_order", {})
    if not isinstance(name_order, dict):
        name_order = {}
    default_order = str(name_order.get("default", "") or "").strip().lower()
    if default_order in {"family_given", "given_family"}:
        return default_order

    ws_type = str(world_setting.get("type", "") or "").lower()
    ws_label = str(world_setting.get("label", "") or "").lower()
    if any(token in f"{ws_type} {ws_label}" for token in ("japan", "japanese")):
        return "family_given"
    return "given_family"


def build_name_order_replacement_map(manifest: Dict[str, Any]) -> Dict[str, str]:
    policy = resolve_name_order_policy(manifest)
    if policy not in {"family_given", "given_family"}:
        return {}

    canonical_pairs: Dict[Tuple[str, ...], str] = {}
    for candidate in _iter_authoritative_names(manifest, policy):
        parts = _split_name(candidate)
        if len(parts) < 2:
            continue
        key = tuple(sorted(part.lower() for part in parts))
        canonical_pairs.setdefault(key, candidate)

    replacements: Dict[str, str] = {}
    for canonical in canonical_pairs.values():
        parts = _split_name(canonical)
        if len(parts) < 2:
            continue
        reversed_name = " ".join(reversed(parts))
        if reversed_name != canonical:
            replacements[reversed_name] = canonical
    return replacements


def normalize_payload_names(payload: Any, manifest: Dict[str, Any]) -> Any:
    replacements = build_name_order_replacement_map(manifest)
    if not replacements:
        return payload
    return _normalize_value(payload, replacements)


def detect_name_order_conflicts(
    work_dir: Path,
    manifest: Dict[str, Any],
    *,
    include_outputs: bool = False,
) -> List[Dict[str, Any]]:
    replacements = build_name_order_replacement_map(manifest)
    if not replacements:
        return []

    conflicts: List[Dict[str, Any]] = []
    for path in _iter_volume_artifact_paths(work_dir, include_outputs=include_outputs):
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        counts = {
            wrong: text.count(wrong)
            for wrong in replacements
            if text.count(wrong) > 0
        }
        if counts:
            conflicts.append(
                {
                    "path": str(path),
                    "counts": counts,
                    "total": sum(counts.values()),
                }
            )
    conflicts.sort(key=lambda item: (-int(item["total"]), item["path"]))
    return conflicts


def normalize_volume_artifacts(
    work_dir: Path,
    manifest: Dict[str, Any],
    *,
    include_outputs: bool = True,
) -> Dict[str, Any]:
    replacements = build_name_order_replacement_map(manifest)
    summary = {
        "files_touched": 0,
        "json_files": 0,
        "text_files": 0,
        "replacements": 0,
        "paths": [],
    }
    if not replacements:
        return summary

    for path in _iter_volume_artifact_paths(work_dir, include_outputs=include_outputs):
        if not path.exists() or not path.is_file():
            continue
        if path.suffix.lower() == ".json":
            changed, replacements_made = _normalize_json_file(path, manifest)
            if changed:
                summary["files_touched"] += 1
                summary["json_files"] += 1
                summary["replacements"] += replacements_made
                summary["paths"].append(str(path))
        elif path.suffix.lower() in {".md", ".txt"}:
            changed, replacements_made = _normalize_text_file(path, replacements)
            if changed:
                summary["files_touched"] += 1
                summary["text_files"] += 1
                summary["replacements"] += replacements_made
                summary["paths"].append(str(path))
    return summary


def _iter_authoritative_names(manifest: Dict[str, Any], policy: str) -> Iterable[str]:
    metadata_en = manifest.get("metadata_en", {}) if isinstance(manifest, dict) else {}
    if not isinstance(metadata_en, dict):
        metadata_en = {}

    localization_notes = metadata_en.get("localization_notes", {})
    if isinstance(localization_notes, dict):
        name_order = localization_notes.get("name_order", {})
        if isinstance(name_order, dict):
            if policy == "family_given":
                jp_chars = name_order.get("japanese_characters", {})
                if isinstance(jp_chars, dict):
                    for name in jp_chars.get("characters", []) or []:
                        text = str(name or "").strip()
                        if text:
                            yield text
            elif policy == "given_family":
                western_chars = name_order.get("western_characters", {})
                if isinstance(western_chars, dict):
                    for name in western_chars.get("characters", []) or []:
                        text = str(name or "").strip()
                        if text:
                            yield text

    character_profiles = metadata_en.get("character_profiles", {})
    if isinstance(character_profiles, dict):
        for name in character_profiles.keys():
            text = str(name or "").strip()
            if text:
                yield text

    for fp in metadata_en.get("character_voice_fingerprints", []) or []:
        if not isinstance(fp, dict):
            continue
        text = str(fp.get("canonical_name_en", "") or "").strip()
        if text:
            yield text

    for name in manifest.get("character_names", {}).values() if isinstance(manifest.get("character_names"), dict) else []:
        text = _strip_parenthetical_name(name)
        if text:
            yield text


def _iter_volume_artifact_paths(work_dir: Path, *, include_outputs: bool) -> Iterable[Path]:
    base_patterns = [
        "manifest.json",
        "metadata_*.json",
        "rich_metadata_cache_patch_*.json",
        "visual_cache.json",
        "translation_log.json",
        "continuity_diff_report.json",
        "cost_audit_last_run.json",
        "PLANS/*.json",
        ".context/*.json",
    ]
    if include_outputs:
        base_patterns.extend(
            [
                ".context/TRANSLATION_BRIEF.md",
                "EN/*.md",
            ]
        )

    seen = set()
    for pattern in base_patterns:
        for path in sorted(work_dir.glob(pattern)):
            if str(path) in seen:
                continue
            seen.add(str(path))
            yield path


def _normalize_json_file(path: Path, manifest: Dict[str, Any]) -> tuple[bool, int]:
    try:
        original_text = path.read_text(encoding="utf-8")
        data = json.loads(original_text)
    except Exception:
        return False, 0

    replacements = build_name_order_replacement_map(manifest)
    normalized = _normalize_value(data, replacements)
    normalized_text = json.dumps(normalized, indent=2, ensure_ascii=False) + "\n"
    if normalized_text == original_text:
        return False, 0

    path.write_text(normalized_text, encoding="utf-8")
    return True, _count_replacements(original_text, replacements)


def _normalize_text_file(path: Path, replacements: Dict[str, str]) -> tuple[bool, int]:
    try:
        original_text = path.read_text(encoding="utf-8")
    except Exception:
        return False, 0
    normalized_text = _replace_in_text(original_text, replacements)
    if normalized_text == original_text:
        return False, 0
    path.write_text(normalized_text, encoding="utf-8")
    return True, _count_replacements(original_text, replacements)


def _normalize_value(value: Any, replacements: Dict[str, str]) -> Any:
    if isinstance(value, dict):
        normalized: Dict[str, Any] = {}
        for key, item in value.items():
            new_key = _replace_in_text(str(key), replacements)
            normalized[new_key] = _normalize_value(item, replacements)
        return normalized
    if isinstance(value, list):
        return [_normalize_value(item, replacements) for item in value]
    if isinstance(value, str):
        return _replace_in_text(value, replacements)
    return value


def _replace_in_text(text: str, replacements: Dict[str, str]) -> str:
    updated = text
    for wrong, canonical in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        updated = updated.replace(wrong, canonical)
    return updated


def _count_replacements(text: str, replacements: Dict[str, str]) -> int:
    return sum(text.count(wrong) for wrong in replacements)


def _strip_parenthetical_name(value: Any) -> str:
    text = str(value or "").strip()
    if " (" in text:
        text = text.split(" (", 1)[0].strip()
    return text


def _split_name(name: str) -> List[str]:
    return [part for part in str(name or "").strip().split() if part]


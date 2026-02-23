"""
Reference Context Compiler
==========================

Compile per-chapter `.references.json` validation reports into a single
deduplicated `.context/reference_registry.json` artifact for Translator injection.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _norm_token(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return re.sub(r"\s+", " ", text)


def _norm_key(value: Any) -> str:
    text = _norm_token(value)
    if not text:
        return ""
    return re.sub(r"[^a-z0-9]+", "", text)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _pick_better_name(current: str, candidate: str) -> str:
    """
    Prefer the more descriptive canonical label.
    """
    cur = str(current or "").strip()
    cand = str(candidate or "").strip()
    if not cur:
        return cand
    if not cand:
        return cur
    # Favor longer canonical names (e.g. "Mike Tyson" over "Tyson").
    if len(cand) > len(cur):
        return cand
    return cur


def _entity_key(entity_type: str, canonical_name: str) -> str:
    return f"{_norm_token(entity_type)}::{_norm_key(canonical_name)}"


def compile_reference_payloads(
    source_reports: List[Tuple[str, Dict[str, Any]]],
    *,
    output_path: Optional[Path] = None,
    min_confidence: float = 0.70,
) -> Dict[str, Any]:
    """
    Compile reference payloads into a deduplicated registry.

    Args:
        source_reports:
            List of `(source_name, payload_dict)` tuples.
            `payload_dict` is expected to follow `ValidationReport.to_dict()`.
        output_path: Optional destination path to write compiled JSON.
        min_confidence: Minimum confidence threshold for inclusion.

    Returns:
        Compiled registry payload.
    """
    aggregates: Dict[str, Dict[str, Any]] = {}
    raw_count = 0
    parse_errors = 0

    # Track strongest mapping for detected obfuscation terms.
    detected_term_map: Dict[str, Dict[str, Any]] = {}
    conflicts: List[Dict[str, Any]] = []

    for source_name, payload in source_reports:
        if not isinstance(payload, dict):
            parse_errors += 1
            continue
        entities = payload.get("entities", [])
        if not isinstance(entities, list):
            continue

        for row in entities:
            if not isinstance(row, dict):
                continue
            raw_count += 1

            confidence = _safe_float(row.get("confidence", 0.0), 0.0)
            if confidence < float(min_confidence):
                continue

            detected_term = str(row.get("detected_term", "")).strip()
            canonical_name = str(row.get("real_name", "")).strip() or detected_term
            entity_type = str(row.get("entity_type", "brand")).strip().lower() or "brand"
            is_obfuscated = bool(row.get("is_obfuscated", False))
            wikipedia_verified = bool(row.get("wikipedia_verified", False))
            reasoning = str(row.get("reasoning", "")).strip()
            context_snippet = str(row.get("context", "")).strip()

            key = _entity_key(entity_type, canonical_name)
            if not key:
                continue

            bucket = aggregates.get(key)
            if not bucket:
                bucket = {
                    "canonical_name": canonical_name,
                    "entity_type": entity_type,
                    "is_obfuscated": is_obfuscated,
                    "wikipedia_verified": wikipedia_verified,
                    "max_confidence": confidence,
                    "avg_confidence": confidence,
                    "occurrence_count": 1,
                    "detected_terms": [detected_term] if detected_term else [],
                    "source_reports": [source_name],
                    "reasoning_samples": [reasoning] if reasoning else [],
                    "context_samples": [context_snippet] if context_snippet else [],
                }
                aggregates[key] = bucket
            else:
                bucket["canonical_name"] = _pick_better_name(
                    str(bucket.get("canonical_name", "")),
                    canonical_name,
                )
                bucket["is_obfuscated"] = bool(bucket.get("is_obfuscated", False) or is_obfuscated)
                bucket["wikipedia_verified"] = bool(
                    bucket.get("wikipedia_verified", False) or wikipedia_verified
                )
                bucket["max_confidence"] = max(_safe_float(bucket.get("max_confidence", 0.0)), confidence)
                count = int(bucket.get("occurrence_count", 0)) + 1
                prev_avg = _safe_float(bucket.get("avg_confidence", 0.0))
                bucket["avg_confidence"] = ((prev_avg * (count - 1)) + confidence) / count
                bucket["occurrence_count"] = count
                if detected_term and detected_term not in bucket["detected_terms"]:
                    bucket["detected_terms"].append(detected_term)
                if source_name not in bucket["source_reports"]:
                    bucket["source_reports"].append(source_name)
                if reasoning and reasoning not in bucket["reasoning_samples"] and len(bucket["reasoning_samples"]) < 3:
                    bucket["reasoning_samples"].append(reasoning)
                if context_snippet and context_snippet not in bucket["context_samples"] and len(bucket["context_samples"]) < 3:
                    bucket["context_samples"].append(context_snippet)

            # Build obfuscation resolution map keyed by detected term.
            if detected_term and canonical_name and _norm_key(detected_term) != _norm_key(canonical_name):
                detected_key = _norm_key(detected_term)
                candidate = {
                    "detected_term": detected_term,
                    "canonical_name": canonical_name,
                    "entity_type": entity_type,
                    "confidence": confidence,
                    "wikipedia_verified": wikipedia_verified,
                    "source_report": source_name,
                }
                previous = detected_term_map.get(detected_key)
                if not previous:
                    detected_term_map[detected_key] = candidate
                else:
                    prev_conf = _safe_float(previous.get("confidence", 0.0))
                    prev_verified = bool(previous.get("wikipedia_verified", False))
                    if (
                        confidence > prev_conf
                        or (confidence == prev_conf and wikipedia_verified and not prev_verified)
                    ):
                        conflicts.append({
                            "detected_term": detected_term,
                            "previous_canonical": previous.get("canonical_name", ""),
                            "new_canonical": canonical_name,
                            "chosen": canonical_name,
                        })
                        detected_term_map[detected_key] = candidate
                    elif _norm_key(str(previous.get("canonical_name", ""))) != _norm_key(canonical_name):
                        conflicts.append({
                            "detected_term": detected_term,
                            "previous_canonical": previous.get("canonical_name", ""),
                            "new_canonical": canonical_name,
                            "chosen": previous.get("canonical_name", ""),
                        })

    entities: List[Dict[str, Any]] = []
    for item in aggregates.values():
        entities.append({
            "canonical_name": item["canonical_name"],
            "entity_type": item["entity_type"],
            "is_obfuscated": bool(item["is_obfuscated"]),
            "wikipedia_verified": bool(item["wikipedia_verified"]),
            "max_confidence": round(_safe_float(item["max_confidence"]), 4),
            "avg_confidence": round(_safe_float(item["avg_confidence"]), 4),
            "occurrence_count": int(item["occurrence_count"]),
            "detected_terms": sorted(
                [str(v).strip() for v in item.get("detected_terms", []) if str(v).strip()],
                key=lambda v: (len(v), v),
            ),
            "source_reports": sorted(set(item.get("source_reports", []))),
            "reasoning_samples": item.get("reasoning_samples", []),
            "context_samples": item.get("context_samples", []),
        })

    entities.sort(
        key=lambda r: (
            not bool(r.get("is_obfuscated", False)),
            -_safe_float(r.get("max_confidence", 0.0)),
            str(r.get("entity_type", "")),
            str(r.get("canonical_name", "")),
        )
    )

    deobfuscation_map = sorted(
        detected_term_map.values(),
        key=lambda r: (-_safe_float(r.get("confidence", 0.0)), str(r.get("detected_term", ""))),
    )

    compiled: Dict[str, Any] = {
        "schema": "reference_registry.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_report_count": len(source_reports),
        "source_reports": [name for name, _ in source_reports],
        "parse_errors": parse_errors,
        "min_confidence": float(min_confidence),
        "total_entities_raw": raw_count,
        "unique_entities": len(entities),
        "unique_deobfuscation_terms": len(deobfuscation_map),
        "entities": entities,
        "deobfuscation_map": deobfuscation_map,
        "conflicts": conflicts[:50],
    }

    if output_path is not None:
        output_path.write_text(
            json.dumps(compiled, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return compiled


def compile_reference_reports(
    context_dir: Path,
    *,
    output_filename: str = "reference_registry.json",
    min_confidence: float = 0.70,
    force: bool = False,
) -> Optional[Path]:
    """
    Compile chapter reference reports in `.context` into one deduplicated registry.

    Supports both naming conventions:
    - `CHAPTER_XX.references.json` (new)
    - `CHAPTER_XX.json` payloads generated by validator's json-only output (legacy)
    """
    if not context_dir.exists() or not context_dir.is_dir():
        return None

    candidate_files: List[Path] = []
    candidate_files.extend(sorted(context_dir.glob("*.references.json")))
    candidate_files.extend(sorted(context_dir.glob("CHAPTER_*.json")))

    report_files: List[Path] = []
    source_reports: List[Tuple[str, Dict[str, Any]]] = []
    for report_file in candidate_files:
        name = report_file.name
        # Skip known non-reference chapter artifacts.
        if "_SUMMARY.json" in name or "_VOLUME_CONTEXT.json" in name:
            continue
        try:
            payload = json.loads(report_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        if not {"file_path", "total_entities_detected", "entities"}.issubset(payload.keys()):
            continue
        report_files.append(report_file)
        source_reports.append((name, payload))

    if not report_files:
        return None

    output_path = context_dir / output_filename
    if output_path.exists() and not force:
        latest_input_mtime = max((p.stat().st_mtime for p in report_files), default=0.0)
        if output_path.stat().st_mtime >= latest_input_mtime:
            return output_path

    compile_reference_payloads(
        source_reports,
        output_path=output_path,
        min_confidence=min_confidence,
    )
    return output_path

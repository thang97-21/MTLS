"""
Structured cost audit utilities for Phase 2 translation runs.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _empty_totals() -> Dict[str, Any]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
        "cache_creation_tokens": 0,
        "input_cost_usd": 0.0,
        "output_cost_usd": 0.0,
        "cache_read_cost_usd": 0.0,
        "cache_creation_cost_usd": 0.0,
        "total_cost_usd": 0.0,
    }


def _add_totals(target: Dict[str, Any], source: Dict[str, Any]) -> None:
    target["input_tokens"] += _to_int(source.get("input_tokens", 0))
    target["output_tokens"] += _to_int(source.get("output_tokens", 0))
    target["cached_tokens"] += _to_int(source.get("cached_tokens", 0))
    target["cache_creation_tokens"] += _to_int(source.get("cache_creation_tokens", 0))
    target["input_cost_usd"] += _to_float(source.get("input_cost_usd", 0.0))
    target["output_cost_usd"] += _to_float(source.get("output_cost_usd", 0.0))
    target["cache_read_cost_usd"] += _to_float(source.get("cache_read_cost_usd", 0.0))
    target["cache_creation_cost_usd"] += _to_float(source.get("cache_creation_cost_usd", 0.0))
    target["total_cost_usd"] += _to_float(source.get("total_cost_usd", 0.0))


def merge_chapter_cost_audits(
    primary: Optional[Dict[str, Any]],
    secondary: Optional[Dict[str, Any]],
    *,
    merge_reason: str = "",
) -> Dict[str, Any]:
    primary = primary if isinstance(primary, dict) else {}
    secondary = secondary if isinstance(secondary, dict) else {}

    primary_attempts = list(primary.get("attempts", []) or [])
    secondary_attempts = list(secondary.get("attempts", []) or [])
    attempts = [*primary_attempts, *secondary_attempts]

    merged = {
        "schema_version": "1.0",
        "chapter_id": primary.get("chapter_id") or secondary.get("chapter_id") or "",
        "request_mode": secondary.get("request_mode") or primary.get("request_mode") or "streaming",
        "attempts": attempts,
        "attempt_count": len(attempts),
        "retry_count": max(0, len(attempts) - 1),
    }
    if merge_reason:
        merged["merge_reason"] = merge_reason

    actual_totals = _empty_totals()
    attempt_type_totals: Dict[str, Dict[str, Any]] = {}
    for attempt in attempts:
        _add_totals(actual_totals, attempt)
        attempt_type = str(attempt.get("attempt_type", "unknown") or "unknown")
        bucket = attempt_type_totals.setdefault(attempt_type, _empty_totals())
        _add_totals(bucket, attempt)

    merged["actual_totals"] = actual_totals
    merged["attempt_type_totals"] = attempt_type_totals

    for extra_key in (
        "chunk_count",
        "chunk_audits",
        "cache_bleed_retry_count",
        "hallucination_retry_count",
        "tool_mode_active",
    ):
        if extra_key in primary or extra_key in secondary:
            merged[extra_key] = secondary.get(extra_key, primary.get(extra_key))

    return merged


def build_run_cost_audit(
    *,
    volume_id: str,
    provider: str,
    run_entries: List[Dict[str, Any]],
    logged_summary: Optional[Dict[str, Any]] = None,
    batch_mode: bool = False,
    batch_provider_audit: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    logged_summary = logged_summary if isinstance(logged_summary, dict) else {}

    actual_summary = _empty_totals()
    request_mode_breakdown: Dict[str, Dict[str, Any]] = {}
    attempt_type_breakdown: Dict[str, Dict[str, Any]] = {}
    chapter_rows: List[Dict[str, Any]] = []

    chapters_with_retries = 0
    total_retry_attempts = 0
    fallback_retry_count = 0
    hallucination_retry_count = 0
    cache_bleed_retry_count = 0
    cache_hit_chapters = 0
    tool_call_chapters = 0
    total_tool_calls = 0

    for entry in run_entries:
        cost_audit = entry.get("cost_audit", {})
        if not isinstance(cost_audit, dict):
            cost_audit = {}

        actual_totals = cost_audit.get("actual_totals", {})
        if not isinstance(actual_totals, dict) or not actual_totals:
            actual_totals = {
                "input_tokens": _to_int(entry.get("input_tokens", 0)),
                "output_tokens": _to_int(entry.get("output_tokens", 0)),
                "cached_tokens": _to_int(entry.get("cached_tokens", 0)),
                "cache_creation_tokens": _to_int(entry.get("cache_creation_tokens", 0)),
                "input_cost_usd": _to_float(entry.get("input_cost_usd", 0.0)),
                "output_cost_usd": _to_float(entry.get("output_cost_usd", 0.0)),
                "cache_read_cost_usd": _to_float(entry.get("cache_read_cost_usd", 0.0)),
                "cache_creation_cost_usd": _to_float(entry.get("cache_creation_cost_usd", 0.0)),
                "total_cost_usd": _to_float(entry.get("total_cost_usd", 0.0)),
            }

        _add_totals(actual_summary, actual_totals)

        request_mode = str(cost_audit.get("request_mode") or ("batch" if entry.get("batch_mode") else "streaming"))
        request_bucket = request_mode_breakdown.setdefault(request_mode, _empty_totals())
        _add_totals(request_bucket, actual_totals)

        retry_count = max(0, _to_int(cost_audit.get("retry_count", 0)))
        if retry_count > 0:
            chapters_with_retries += 1
            total_retry_attempts += retry_count

        attempt_type_totals = cost_audit.get("attempt_type_totals", {})
        if isinstance(attempt_type_totals, dict):
            for attempt_type, attempt_totals in attempt_type_totals.items():
                bucket = attempt_type_breakdown.setdefault(str(attempt_type), _empty_totals())
                if isinstance(attempt_totals, dict):
                    _add_totals(bucket, attempt_totals)

        attempts = cost_audit.get("attempts", [])
        if isinstance(attempts, list):
            for attempt in attempts:
                attempt_type = str((attempt or {}).get("attempt_type", "") or "")
                if attempt_type == "fallback_model_retry":
                    fallback_retry_count += 1
                elif attempt_type in {"hallucination_retry", "batch_hallucination_retry"}:
                    hallucination_retry_count += 1
                elif attempt_type == "cache_bleed_retry":
                    cache_bleed_retry_count += 1

        total_tool_calls += _to_int(entry.get("tool_call_count", 0))
        if _to_int(entry.get("tool_call_count", 0)) > 0:
            tool_call_chapters += 1
        if _to_int(actual_totals.get("cached_tokens", 0)) > 0:
            cache_hit_chapters += 1

        logged_cost = _to_float(entry.get("total_cost_usd", 0.0))
        actual_cost = _to_float(actual_totals.get("total_cost_usd", 0.0))
        chapter_rows.append(
            {
                "chapter_id": str(entry.get("chapter_id", "") or ""),
                "model": str(entry.get("model", "") or ""),
                "request_mode": request_mode,
                "success": bool(entry.get("success")),
                "logged_total_cost_usd": logged_cost,
                "actual_total_cost_usd": actual_cost,
                "retry_cost_delta_usd": max(0.0, actual_cost - logged_cost),
                "retry_count": retry_count,
                "input_tokens": _to_int(actual_totals.get("input_tokens", 0)),
                "output_tokens": _to_int(actual_totals.get("output_tokens", 0)),
                "cached_tokens": _to_int(actual_totals.get("cached_tokens", 0)),
            }
        )

    chapter_rows.sort(key=lambda row: row["actual_total_cost_usd"], reverse=True)

    logged_total_cost = _to_float(logged_summary.get("total_cost_usd", 0.0))
    actual_total_cost = _to_float(actual_summary.get("total_cost_usd", 0.0))

    return {
        "schema_version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "volume_id": volume_id,
        "provider": provider,
        "batch_mode": batch_mode,
        "chapter_count": len(run_entries),
        "logged_summary": logged_summary,
        "actual_summary": actual_summary,
        "delta_vs_logged": {
            "extra_input_tokens": actual_summary["input_tokens"] - _to_int(logged_summary.get("total_input_tokens", 0)),
            "extra_output_tokens": actual_summary["output_tokens"] - _to_int(logged_summary.get("total_output_tokens", 0)),
            "extra_total_cost_usd": actual_total_cost - logged_total_cost,
        },
        "retry_summary": {
            "chapters_with_retries": chapters_with_retries,
            "total_retry_attempts": total_retry_attempts,
            "fallback_model_retries": fallback_retry_count,
            "hallucination_retries": hallucination_retry_count,
            "cache_bleed_retries": cache_bleed_retry_count,
        },
        "cache_summary": {
            "cache_hit_chapters": cache_hit_chapters,
            "cache_hit_ratio": (cache_hit_chapters / max(1, len(run_entries))),
            "cache_read_tokens": actual_summary["cached_tokens"],
            "cache_creation_tokens": actual_summary["cache_creation_tokens"],
        },
        "tool_summary": {
            "chapters_with_tool_calls": tool_call_chapters,
            "total_tool_calls": total_tool_calls,
        },
        "request_mode_breakdown": request_mode_breakdown,
        "attempt_type_breakdown": attempt_type_breakdown,
        "top_chapters_by_cost": chapter_rows[:10],
        "chapters": chapter_rows,
        "batch_provider_audit": batch_provider_audit or {},
    }


def render_cost_audit_markdown(audit: Dict[str, Any]) -> str:
    actual = audit.get("actual_summary", {}) if isinstance(audit.get("actual_summary"), dict) else {}
    delta = audit.get("delta_vs_logged", {}) if isinstance(audit.get("delta_vs_logged"), dict) else {}
    retry_summary = audit.get("retry_summary", {}) if isinstance(audit.get("retry_summary"), dict) else {}
    cache_summary = audit.get("cache_summary", {}) if isinstance(audit.get("cache_summary"), dict) else {}
    top_chapters = audit.get("top_chapters_by_cost", []) if isinstance(audit.get("top_chapters_by_cost"), list) else []

    lines = [
        f"# Cost Audit - {audit.get('volume_id', '')}",
        "",
        f"- Provider: {audit.get('provider', '')}",
        f"- Batch mode: {bool(audit.get('batch_mode', False))}",
        f"- Chapters audited: {_to_int(audit.get('chapter_count', 0))}",
        f"- Actual total cost: ${_to_float(actual.get('total_cost_usd', 0.0)):.6f}",
        f"- Extra cost vs logged totals: ${_to_float(delta.get('extra_total_cost_usd', 0.0)):.6f}",
        f"- Retry attempts: {_to_int(retry_summary.get('total_retry_attempts', 0))}",
        f"- Cache hit ratio: {_to_float(cache_summary.get('cache_hit_ratio', 0.0)) * 100:.1f}%",
        "",
        "## Top Cost Chapters",
        "",
    ]

    if not top_chapters:
        lines.append("- No chapter cost data available.")
    else:
        for row in top_chapters:
            lines.append(
                f"- {row.get('chapter_id', '')}: actual=${_to_float(row.get('actual_total_cost_usd', 0.0)):.6f} "
                f"(logged=${_to_float(row.get('logged_total_cost_usd', 0.0)):.6f}, "
                f"retry_delta=${_to_float(row.get('retry_cost_delta_usd', 0.0)):.6f}, "
                f"retries={_to_int(row.get('retry_count', 0))})"
            )

    return "\n".join(lines) + "\n"


def write_cost_audit_artifacts(
    *,
    work_dir: Path,
    audit: Dict[str, Any],
) -> Dict[str, str]:
    json_path = work_dir / "cost_audit_last_run.json"
    md_path = work_dir / "cost_audit_last_run.md"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, ensure_ascii=False)
        f.write("\n")

    with md_path.open("w", encoding="utf-8") as f:
        f.write(render_cost_audit_markdown(audit))

    return {
        "json_path": str(json_path),
        "markdown_path": str(md_path),
    }


def _load_translation_log(work_dir: Path) -> Dict[str, Any]:
    path = work_dir / "translation_log.json"
    if not path.exists():
        raise FileNotFoundError(f"translation_log.json not found in {work_dir}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build translator cost audit artifacts")
    parser.add_argument("--work-dir", type=str, required=True, help="Volume work directory")
    parser.add_argument("--provider", type=str, default="unknown", help="Translator provider label")
    args = parser.parse_args()

    work_dir = Path(args.work_dir)
    try:
        payload = _load_translation_log(work_dir)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc))
    run_entries = payload.get("chapters", [])
    audit = build_run_cost_audit(
        volume_id=str(work_dir.name),
        provider=args.provider,
        run_entries=run_entries if isinstance(run_entries, list) else [],
        logged_summary=payload.get("last_run_summary", {}),
        batch_mode=bool((payload.get("last_run_summary", {}) or {}).get("tool_mode", {}).get("status") == "disabled_for_batch"),
    )
    paths = write_cost_audit_artifacts(work_dir=work_dir, audit=audit)
    print(json.dumps(paths, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""QC and audit MCP tools."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, List

from pipeline.audit import audit_translation
from pipeline.post_processor.multi_script_detector import MultiScriptDetector
from pipeline.translator.quality_metrics import QualityMetrics

from ..config import MCPConfig
from ..runtime import (
    resolve_chapter_markdown,
    resolve_volume_dir,
    run_module,
)


def register_qc_tools(mcp: object, cfg: MCPConfig) -> None:
    """Register Phase 3 QC/audit tools."""

    @mcp.tool()  # type: ignore[attr-defined]
    def run_translation_audit(volume_id: str, target_language: str = "en") -> dict:
        volume_dir = resolve_volume_dir(volume_id, cfg)
        manifest_path = volume_dir / "manifest.json"
        if not manifest_path.exists():
            return {"ok": False, "error": f"manifest not found: {manifest_path}"}

        manifest = _read_json(manifest_path)
        chapters = manifest.get("chapters", []) if isinstance(manifest, dict) else []
        metadata_key = "metadata_vn" if str(target_language).lower() in {"vn", "vi"} else "metadata_en"
        metadata = manifest.get(metadata_key, {}) if isinstance(manifest, dict) else {}
        glossary = metadata.get("glossary", {}) if isinstance(metadata, dict) else {}
        character_profiles = metadata.get("character_profiles", {}) if isinstance(metadata, dict) else {}

        chapter_reports: List[dict] = []
        for idx, chapter in enumerate(chapters, start=1):
            if not isinstance(chapter, dict):
                continue
            chapter_id = str(chapter.get("id", f"chapter_{idx:02d}"))
            try:
                target_path = resolve_chapter_markdown(volume_dir, target_language, chapter_id, cfg)
                target_text = target_path.read_text(encoding="utf-8")
            except Exception:
                continue

            source_text = ""
            source_file = str(chapter.get("source_file", "")).strip()
            if source_file:
                source_path = volume_dir / "JP" / source_file
                if source_path.exists():
                    source_text = source_path.read_text(encoding="utf-8")
            if not source_text:
                try:
                    source_path = resolve_chapter_markdown(volume_dir, "jp", chapter_id, cfg)
                    source_text = source_path.read_text(encoding="utf-8")
                except Exception:
                    source_text = ""

            report = audit_translation(
                content=target_text,
                chapter_id=chapter_id,
                target_language=target_language,
                source_content=source_text or None,
                glossary=glossary if isinstance(glossary, dict) else {},
                character_profiles=character_profiles if isinstance(character_profiles, dict) else {},
            )
            chapter_reports.append(
                {
                    "chapter_id": chapter_id,
                    "summary": report.summary(),
                    "issues": [_serialize(issue) for issue in report.issues],
                }
            )

        failing = [item for item in chapter_reports if not bool(item.get("summary", {}).get("passed", False))]
        return {
            "schema": "AuditReport",
            "ok": True,
            "volume_id": volume_id,
            "target_language": target_language,
            "chapter_count": len(chapter_reports),
            "failing_count": len(failing),
            "reports": chapter_reports,
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def run_structural_geometry_scan(volume_id: str) -> dict:
        execution = run_module(
            "pipeline.audit.structural_geometry_scanner",
            ["--volume", volume_id, "--work-dir", str(cfg.work_dir)],
            cfg,
        )
        return {
            "schema": "GeometryReport",
            "ok": bool(execution.get("ok", False)),
            "volume_id": volume_id,
            "execution": execution,
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def detect_multi_script(text: str) -> dict:
        detector = MultiScriptDetector(use_cjk_detector=True)
        artifacts = detector.detect_all_foreign_scripts(text or "")
        return {
            "schema": "MultiScriptReport",
            "artifact_count": len(artifacts),
            "artifacts": [_serialize_script_artifact(item) for item in artifacts],
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def detect_ai_isms(text: str) -> dict:
        count, found = QualityMetrics.count_ai_isms(text or "")
        return {
            "schema": "AIismReport",
            "count": count,
            "patterns_found": sorted(found),
        }


def _read_json(path: Path) -> Dict[str, Any]:
    import json

    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return value


def _serialize_script_artifact(value: Any) -> Dict[str, Any]:
    """Serialize multi-script artifacts with enum fields."""
    script = getattr(value, "script", None)
    return {
        "char": getattr(value, "char", ""),
        "codepoint": getattr(value, "codepoint", 0),
        "unicode_name": getattr(value, "unicode_name", ""),
        "script": getattr(script, "script_name", str(script)),
        "script_family": getattr(script, "family", ""),
        "line_number": getattr(value, "line_number", 0),
        "sentence": getattr(value, "sentence", ""),
        "position_in_sentence": getattr(value, "position_in_sentence", 0),
        "suspicion_score": getattr(value, "suspicion_score", 0.0),
        "reason": getattr(value, "reason", ""),
        "llm_hallucination_likely": bool(getattr(value, "llm_hallucination_likely", False)),
    }

"""Post-processing MCP tools (Phase 2.5 + validators)."""

from __future__ import annotations

import tempfile
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from pipeline.post_processor.cjk_cleaner import CJKArtifactCleaner
from pipeline.post_processor.cjk_cleaner_v2 import EnhancedCJKCleaner
from pipeline.post_processor.copyedit_post_pass import CopyeditPostPass
from pipeline.post_processor.format_normalizer import FormatNormalizer
from pipeline.post_processor.grammar_validator import GrammarValidator
from pipeline.post_processor.phase2_5_ai_ism_fixer import Phase25AIismFixer
from pipeline.post_processor.pov_validator import POVValidator
from pipeline.post_processor.reference_validator import ReferenceValidator
from pipeline.post_processor.tense_validator import TenseConsistencyValidator
from pipeline.post_processor.truncation_validator import TruncationValidator

from ..config import MCPConfig
from ..runtime import resolve_volume_dir, run_module


def register_postprocessor_tools(mcp: object, cfg: MCPConfig) -> None:
    """Register post-processing tools."""

    @mcp.tool()  # type: ignore[attr-defined]
    def run_volume_bible_update(
        volume_id: str,
        qc_cleared: bool = False,
        force: bool = False,
        target_language: str = "",
    ) -> dict:
        args = ["--volume", volume_id]
        if qc_cleared:
            args.append("--qc-cleared")
        if force:
            args.append("--force")
        if target_language:
            args.extend(["--target-language", target_language])
        execution = run_module("pipeline.post_processor.volume_bible_update_agent", args, cfg)
        return {
            "schema": "BibleUpdateResult",
            "ok": bool(execution.get("ok", False)),
            "volume_id": volume_id,
            "execution": execution,
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def clean_cjk(text: str, version: str = "v1", strict_mode: bool = False, confidence: float = 0.7) -> dict:
        if str(version).lower() == "v2":
            cleaner = EnhancedCJKCleaner(
                min_confidence=float(confidence),
                use_kanji_api=False,
                use_llm_correction=False,
            )
            artifacts = cleaner.detect_artifacts(text or "")
            return {
                "schema": "CleanedText",
                "version": "v2",
                "artifact_count": len(artifacts),
                "artifacts": [_serialize(item) for item in artifacts],
            }

        cleaner_v1 = CJKArtifactCleaner(
            strict_mode=bool(strict_mode),
            min_confidence=float(confidence),
        )
        artifacts_v1 = cleaner_v1.detect_artifacts(text or "")
        return {
            "schema": "CleanedText",
            "version": "v1",
            "artifact_count": len(artifacts_v1),
            "artifacts": [_serialize(item) for item in artifacts_v1],
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def validate_grammar(text: str, target_lang: str = "en") -> dict:
        if str(target_lang).lower() in {"vn", "vi"}:
            return {
                "schema": "GrammarReport",
                "target_language": target_lang,
                "supported": False,
                "message": "grammar_validator currently supports EN only",
                "report": {},
            }
        with _temp_markdown_file(text or "") as temp_path:
            report = GrammarValidator(auto_fix=False).validate_file(temp_path)
        payload = report.to_dict()
        payload["schema"] = "GrammarReport"
        payload["target_language"] = target_lang
        payload["supported"] = True
        return payload

    @mcp.tool()  # type: ignore[attr-defined]
    def validate_tense(text: str) -> dict:
        with _temp_markdown_file(text or "") as temp_path:
            report = TenseConsistencyValidator(auto_fix=False).validate_file(temp_path)
        payload = report.to_dict()
        payload["schema"] = "TenseReport"
        return payload

    @mcp.tool()  # type: ignore[attr-defined]
    def validate_pov(text: str, declared_pov: str = "third") -> dict:
        report = POVValidator(declared_pov=declared_pov).validate_text(text or "")
        return {
            "schema": "POVReport",
            "declared_pov": report.declared_pov,
            "issue_count": report.issue_count,
            "issues": [_serialize(item) for item in report.issues],
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def validate_references(text: str, manifest: Optional[Dict[str, Any]] = None) -> dict:
        context = ""
        if isinstance(manifest, dict):
            metadata = manifest.get("metadata", {})
            if isinstance(metadata, dict):
                context = str(metadata.get("title", "") or "")
        try:
            validator = ReferenceValidator(enable_wikipedia=False)
            entities = validator.detect_real_world_references(text or "", context or None)
            return {
                "schema": "ReferenceReport",
                "entity_count": len(entities),
                "entities": [_serialize(item) for item in entities],
            }
        except Exception as exc:
            return {
                "schema": "ReferenceReport",
                "entity_count": 0,
                "entities": [],
                "error": str(exc),
            }

    @mcp.tool()  # type: ignore[attr-defined]
    def validate_truncation(text: str) -> dict:
        report = TruncationValidator().validate_text(text or "")
        return {
            "schema": "TruncationReport",
            "issue_count": len(report.all_issues),
            "critical_count": len(report.critical),
            "high_count": len(report.high),
            "medium_count": len(report.medium),
            "should_block": report.should_block(),
            "issues": [_serialize(item) for item in report.all_issues],
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def fix_ai_isms(text: str, dry_run: bool = False) -> dict:
        with _temp_markdown_file(text or "") as temp_path:
            report = Phase25AIismFixer(dry_run=bool(dry_run)).process_chapter(temp_path)
            updated = temp_path.read_text(encoding="utf-8")
        return {
            "schema": "FixedText",
            "report": report.to_dict(),
            "updated_text": updated,
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def normalize_format(text: str, aggressive: bool = False) -> dict:
        with _temp_markdown_file(text or "") as temp_path:
            changed, stats = FormatNormalizer(aggressive=bool(aggressive)).normalize_file(temp_path)
            normalized = temp_path.read_text(encoding="utf-8")
        return {
            "schema": "NormalizedText",
            "changed": changed,
            "stats": stats,
            "normalized_text": normalized,
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def run_copyedit(text: str, target_language: str = "en") -> dict:
        with tempfile.TemporaryDirectory(prefix="mcp_copyedit_") as tmp:
            root = Path(tmp)
            lang = "VN" if str(target_language).lower() in {"vn", "vi"} else "EN"
            lang_dir = root / lang
            lang_dir.mkdir(parents=True, exist_ok=True)
            chapter_path = lang_dir / "CHAPTER_01.md"
            chapter_path.write_text(text or "", encoding="utf-8")
            report = CopyeditPostPass(root, target_language=target_language).run()
            normalized = chapter_path.read_text(encoding="utf-8")
        return {
            "schema": "CopyeditResult",
            "report": report.to_dict(),
            "normalized_text": normalized,
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def run_stage3_refinement(volume_id: str, chapter_id: str = "", dry_run: bool = False) -> dict:
        volume_dir = resolve_volume_dir(volume_id, cfg)
        input_dir = volume_dir / "EN"
        work_input_dir = input_dir
        temp_dir: tempfile.TemporaryDirectory[str] | None = None
        if chapter_id:
            temp_dir = tempfile.TemporaryDirectory(prefix="mcp_stage3_")
            work_input_dir = Path(temp_dir.name)
            work_input_dir.mkdir(parents=True, exist_ok=True)
            chapter_path = (input_dir / str(chapter_id))
            if chapter_path.suffix.lower() != ".md":
                chapter_path = input_dir / f"{chapter_id}.md"
            if not chapter_path.exists():
                # Try chapter number canonical naming.
                import re as _re
                m = _re.search(r"(\d+)", str(chapter_id))
                if m:
                    num = int(m.group(1))
                    for candidate in (
                        input_dir / f"CHAPTER_{num:02d}_EN.md",
                        input_dir / f"CHAPTER_{num:02d}.md",
                    ):
                        if candidate.exists():
                            chapter_path = candidate
                            break
            if not chapter_path.exists():
                if temp_dir is not None:
                    temp_dir.cleanup()
                return {
                    "schema": "RefinementResult",
                    "ok": False,
                    "error": f"Chapter not found for refinement: {chapter_id}",
                }
            copied = work_input_dir / chapter_path.name
            copied.write_text(chapter_path.read_text(encoding="utf-8"), encoding="utf-8")

        args = ["--input-dir", str(input_dir)]
        if chapter_id:
            args = ["--input-dir", str(work_input_dir)]
        if dry_run:
            args.append("--dry-run")
        execution = run_module("pipeline.post_processor.stage3_refinement_agent", args, cfg)
        if chapter_id and temp_dir is not None:
            temp_dir.cleanup()
        return {
            "schema": "RefinementResult",
            "ok": bool(execution.get("ok", False)),
            "volume_id": volume_id,
            "chapter_id": chapter_id,
            "execution": execution,
        }


class _temp_markdown_file:
    """Context manager creating a temporary markdown file."""

    def __init__(self, text: str):
        self.text = text
        self._dir: tempfile.TemporaryDirectory[str] | None = None
        self.path: Path | None = None

    def __enter__(self) -> Path:
        self._dir = tempfile.TemporaryDirectory(prefix="mcp_validator_")
        self.path = Path(self._dir.name) / "chapter.md"
        self.path.write_text(self.text, encoding="utf-8")
        return self.path

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._dir is not None:
            self._dir.cleanup()


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return value

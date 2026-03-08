"""Translator phase MCP tools."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from pipeline.translator.koji_fox_validator import KojiFoxValidator
from pipeline.translator.quality_metrics import QualityMetrics
from pipeline.translator.series_bible_rag import SeriesBibleRAG
from pipeline.translator.vn_voice_validator import VNVoiceConsistencyValidator
from pipeline.translator.volume_context_aggregator import VolumeContextAggregator

from ..config import MCPConfig
from ..runtime import (
    MCPRuntimeError,
    load_manifest,
    resolve_chapter_markdown,
    resolve_volume_dir,
    run_module,
)


def register_translator_tools(mcp: object, cfg: MCPConfig) -> None:
    """Register Phase 2 tools."""

    @mcp.tool()  # type: ignore[attr-defined]
    def translate_chapter(
        volume_id: str,
        chapter_id: str,
        provider: str = "",
        model: str = "",
        force: bool = False,
        batch: bool = False,
        use_env_key: bool = True,
        tool_mode: bool = False,
        enable_multimodal: bool = False,
    ) -> dict:
        args = ["--volume", volume_id, "--chapters", chapter_id]
        if force:
            args.append("--force")
        if batch:
            args.append("--batch")
        if use_env_key:
            args.append("--use-env-key")
        if tool_mode:
            args.append("--tool-mode")
        if enable_multimodal:
            args.append("--enable-multimodal")
        execution = run_module("pipeline.translator.agent", args, cfg)
        return {
            "schema": "TranslatedChapter",
            "ok": bool(execution.get("ok", False)),
            "volume_id": volume_id,
            "chapter_id": chapter_id,
            "provider_requested": provider,
            "model_requested": model,
            "provider_model_note": "Provider/model are controlled via config; set with config tools before execution.",
            "execution": execution,
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def run_translator(
        volume_id: str,
        chapters: Optional[List[str]] = None,
        provider: str = "",
        model: str = "",
        force: bool = False,
        batch: bool = False,
        use_env_key: bool = True,
        tool_mode: bool = False,
        enable_multimodal: bool = False,
    ) -> dict:
        args = ["--volume", volume_id]
        if chapters:
            args.extend(["--chapters", *[str(c) for c in chapters]])
        if force:
            args.append("--force")
        if batch:
            args.append("--batch")
        if use_env_key:
            args.append("--use-env-key")
        if tool_mode:
            args.append("--tool-mode")
        if enable_multimodal:
            args.append("--enable-multimodal")
        execution = run_module("pipeline.translator.agent", args, cfg)
        manifest = {}
        try:
            manifest = load_manifest(volume_id, cfg)
        except Exception:
            manifest = {}
        chapter_total = len(manifest.get("chapters", [])) if isinstance(manifest, dict) else 0
        return {
            "schema": "TranslationReport",
            "ok": bool(execution.get("ok", False)),
            "volume_id": volume_id,
            "chapter_count": chapter_total,
            "provider_requested": provider,
            "model_requested": model,
            "provider_model_note": "Provider/model are controlled via config; set with config tools before execution.",
            "execution": execution,
            "pipeline_state": manifest.get("pipeline_state", {}) if isinstance(manifest, dict) else {},
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def get_volume_context(volume_id: str, target_language: str = "en") -> dict:
        volume_dir = resolve_volume_dir(volume_id, cfg)
        manifest = load_manifest(volume_id, cfg)
        chapter_count = len(manifest.get("chapters", [])) if isinstance(manifest, dict) else 0
        aggregator = VolumeContextAggregator(work_dir=volume_dir)
        lang_dir = "VN" if str(target_language).lower() in {"vn", "vi"} else "EN"
        context = aggregator.aggregate_volume_context(
            current_chapter_num=max(1, chapter_count + 1),
            source_dir=volume_dir / "JP",
            en_dir=volume_dir / lang_dir,
        )
        return {
            "schema": "VolumeContext",
            "volume_id": volume_id,
            "chapter_count": chapter_count,
            "character_count": len(context.character_registry),
            "terminology_count": len(context.established_terminology),
            "translator_notes_count": len(context.translator_notes),
            "overall_tone": context.overall_tone,
            "prompt_section": context.to_prompt_section(),
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def validate_koji_fox(text: str, fingerprints: Optional[List[Dict[str, Any]]] = None) -> dict:
        report = KojiFoxValidator().validate_chapter(
            chapter_text=text or "",
            character_fingerprints=fingerprints or None,
        )
        payload = report.to_dict()
        payload["schema"] = "KojiFoxReport"
        return payload

    @mcp.tool()  # type: ignore[attr-defined]
    def validate_vn_voice(
        text: str,
        fingerprints: Optional[List[Dict[str, Any]]] = None,
        eps_data: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> dict:
        results = VNVoiceConsistencyValidator().validate_chapter(
            translated_text=text or "",
            fingerprints=fingerprints or [],
            eps_data=eps_data or {},
        )
        return {
            "schema": "VNVoiceReport",
            "count": len(results),
            "results": [_serialize(item) for item in results],
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def retrieve_bible_passages(
        volume_id: str,
        chapter_jp: str,
        bible_glossary: Optional[Dict[str, str]] = None,
        max_passages: int = 24,
    ) -> dict:
        manifest = load_manifest(volume_id, cfg)
        series_id = str(
            manifest.get("bible_id")
            or manifest.get("series_id")
            or manifest.get("metadata", {}).get("series_id")
            or ""
        ).strip()
        if not series_id:
            raise MCPRuntimeError("No bible_id/series_id resolved from manifest for this volume")

        rag = SeriesBibleRAG(series_id=series_id, pipeline_root=cfg.pipeline_root)
        passages = rag.retrieve_for_chapter(
            jp_source=chapter_jp or "",
            bible_glossary=bible_glossary or {},
            max_passages=max(1, int(max_passages)),
            volume_id_exclude=volume_id,
        )
        return {
            "schema": "BiblePassage[]",
            "volume_id": volume_id,
            "series_id": series_id,
            "available": rag.is_available,
            "count": len(passages),
            "passages": [_serialize(item) for item in passages],
            "prompt_block": rag.format_for_prompt(passages),
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def score_translation_quality(translated: str, source: str = "") -> dict:
        result = QualityMetrics.quick_audit(translated or "", source_text=source or "")
        payload = result.to_dict()
        payload["schema"] = "QualityMetrics"
        return payload

    @mcp.tool()  # type: ignore[attr-defined]
    def translate_chapter_file(
        volume_id: str,
        chapter_id: str,
        target_language: str = "en",
    ) -> dict:
        volume_dir = resolve_volume_dir(volume_id, cfg)
        source_path = resolve_chapter_markdown(volume_dir, "jp", chapter_id, cfg)
        target_path = resolve_chapter_markdown(volume_dir, target_language, chapter_id, cfg)
        source_text = source_path.read_text(encoding="utf-8")
        translated_text = target_path.read_text(encoding="utf-8")
        return {
            "volume_id": volume_id,
            "chapter_id": chapter_id,
            "source_path": str(source_path),
            "target_path": str(target_path),
            "quality": score_translation_quality(translated_text, source_text),
            "koji_fox": validate_koji_fox(translated_text),
        }


def _serialize(value: Any) -> Any:
    """Serialize dataclass instances for JSON-safe MCP output."""
    if is_dataclass(value):
        return asdict(value)
    return value

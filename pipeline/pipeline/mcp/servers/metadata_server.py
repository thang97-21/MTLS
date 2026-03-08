"""Metadata processor phase MCP tools."""

from __future__ import annotations

from pathlib import Path

from pipeline.metadata_processor.bible_sync import BibleSyncAgent

from ..config import MCPConfig
from ..runtime import (
    MCPRuntimeError,
    load_manifest,
    read_json_file,
    resolve_volume_dir,
    run_module,
    run_script,
)


def register_metadata_tools(mcp: object, cfg: MCPConfig) -> None:
    """Register Phase 1.15-1.7 tools."""

    @mcp.tool()  # type: ignore[attr-defined]
    def run_title_philosophy(volume_id: str) -> dict:
        execution = run_module(
            "pipeline.metadata_processor.title_philosophy_analyzer",
            ["--volume", volume_id, "--work-dir", str(cfg.work_dir)],
            cfg,
        )
        return {
            "schema": "TitlePhilosophyResult",
            "ok": bool(execution.get("ok", False)),
            "volume_id": volume_id,
            "execution": execution,
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def run_schema_autoupdate(
        volume_id: str,
        strict_canonical: bool = False,
        canonical_source: str = "bible",
    ) -> dict:
        args = ["--volume", volume_id, "--canonical-source", canonical_source]
        if strict_canonical:
            args.append("--strict-canonical")
        execution = run_module("pipeline.metadata_processor.agent", args, cfg)
        return {
            "schema": "SchemaUpdateResult",
            "ok": bool(execution.get("ok", False)),
            "volume_id": volume_id,
            "execution": execution,
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def run_bible_sync(
        volume_id: str,
        target_language: str = "en",
        mode: str = "both",
        canonical_source: str = "bible",
    ) -> dict:
        mode_normalized = str(mode or "both").strip().lower()
        if mode_normalized not in {"pull", "push", "both"}:
            raise MCPRuntimeError("mode must be one of: pull, push, both")

        work_dir = resolve_volume_dir(volume_id, cfg)
        manifest = read_json_file(work_dir / "manifest.json", cfg)
        sync = BibleSyncAgent(work_dir=work_dir, pipeline_root=cfg.pipeline_root)
        resolved = sync.resolve(manifest)
        if not resolved:
            return {
                "schema": "BibleSyncResult",
                "ok": False,
                "resolved": False,
                "message": "No bible linked to this volume",
            }

        payload: dict = {
            "schema": "BibleSyncResult",
            "ok": True,
            "resolved": True,
            "series_id": sync.series_id,
            "mode": mode_normalized,
        }
        if mode_normalized in {"pull", "both"}:
            pull = sync.pull(manifest=manifest, target_language=target_language)
            payload["pull"] = {
                "known_terms": len(pull.known_terms),
                "characters_inherited": pull.characters_inherited,
                "geography_inherited": pull.geography_inherited,
                "weapons_inherited": pull.weapons_inherited,
                "other_inherited": pull.other_inherited,
                "eps_states_inherited": pull.eps_states_inherited,
            }
        if mode_normalized in {"push", "both"}:
            push = sync.push(manifest=manifest, canonical_source=canonical_source)
            payload["push"] = {
                "characters_added": push.characters_added,
                "characters_enriched": push.characters_enriched,
                "characters_skipped": push.characters_skipped,
                "terms_added": push.terms_added,
                "terms_updated": push.terms_updated,
                "eps_states_updated": push.eps_states_updated,
                "conflicts": len(push.conflicts),
                "volume_registered": push.volume_registered,
            }
        return payload

    @mcp.tool()  # type: ignore[attr-defined]
    def run_voice_rag_expansion(volume_id: str) -> dict:
        execution = run_module(
            "pipeline.metadata_processor.agent",
            ["--volume", volume_id, "--voice-rag-only"],
            cfg,
        )
        return {
            "schema": "VoiceRAGResult",
            "ok": bool(execution.get("ok", False)),
            "volume_id": volume_id,
            "execution": execution,
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def run_eps_backfill(volume_id: str) -> dict:
        execution = run_module(
            "pipeline.metadata_processor.agent",
            ["--volume", volume_id, "--eps-only"],
            cfg,
        )
        return {
            "schema": "EPSBackfillResult",
            "ok": bool(execution.get("ok", False)),
            "volume_id": volume_id,
            "execution": execution,
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def run_rich_metadata_cache(volume_id: str, cache_only: bool = False, target_language: str = "") -> dict:
        args = ["--volume", volume_id]
        if cache_only:
            args.append("--cache-only")
        if target_language:
            args.extend(["--target-language", target_language])
        execution = run_module("pipeline.metadata_processor.rich_metadata_cache", args, cfg)
        return {
            "schema": "RichMetadataResult",
            "ok": bool(execution.get("ok", False)),
            "volume_id": volume_id,
            "execution": execution,
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def run_translation_brief(volume_id: str, force: bool = False) -> dict:
        args = ["--volume", volume_id]
        if force:
            args.append("--force")
        execution = run_module("pipeline.post_processor.translation_brief_agent", args, cfg)
        return {
            "schema": "TranslationBrief",
            "ok": bool(execution.get("ok", False)),
            "volume_id": volume_id,
            "execution": execution,
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def run_multimodal_processor(
        volume_id: str,
        full_ln_cache: str = "on",
    ) -> dict:
        args = ["phase1.6", volume_id, "--full-ln-cache", full_ln_cache]
        execution = run_script("mtl.py", args, cfg)
        return {
            "schema": "MultimodalResult",
            "ok": bool(execution.get("ok", False)),
            "volume_id": volume_id,
            "execution": execution,
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def run_scene_planner(volume_id: str, force: bool = False) -> dict:
        args = ["--volume", volume_id]
        if force:
            args.append("--force")
        execution = run_module("pipeline.planner.agent", args, cfg)
        return {
            "schema": "ScenePlan",
            "ok": bool(execution.get("ok", False)),
            "volume_id": volume_id,
            "execution": execution,
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def run_full_metadata(
        volume_id: str,
        include_title_philosophy: bool = True,
        include_voice_rag: bool = True,
        include_eps_backfill: bool = True,
        include_rich_cache: bool = True,
        include_translation_brief: bool = True,
        include_multimodal: bool = True,
        include_scene_planner: bool = True,
    ) -> dict:
        steps: list[dict] = []
        if include_title_philosophy:
            steps.append({"step": "1.15_title_philosophy", "result": run_title_philosophy(volume_id)})
        steps.append({"step": "1.5_schema_autoupdate", "result": run_schema_autoupdate(volume_id)})
        if include_voice_rag:
            steps.append({"step": "1.51_voice_rag", "result": run_voice_rag_expansion(volume_id)})
        if include_eps_backfill:
            steps.append({"step": "1.52_eps_backfill", "result": run_eps_backfill(volume_id)})
        if include_rich_cache:
            steps.append({"step": "1.55_rich_metadata_cache", "result": run_rich_metadata_cache(volume_id)})
        if include_translation_brief:
            steps.append({"step": "1.56_translation_brief", "result": run_translation_brief(volume_id)})
        if include_multimodal:
            steps.append({"step": "1.6_multimodal", "result": run_multimodal_processor(volume_id)})
        if include_scene_planner:
            steps.append({"step": "1.7_scene_planner", "result": run_scene_planner(volume_id)})

        failures = [
            item["step"]
            for item in steps
            if not bool(item.get("result", {}).get("ok", True))
        ]
        manifest_state = {}
        try:
            manifest = load_manifest(volume_id, cfg)
            manifest_state = manifest.get("pipeline_state", {})
        except Exception:
            manifest_state = {}
        return {
            "schema": "MetadataProcessorResult",
            "ok": len(failures) == 0,
            "volume_id": volume_id,
            "steps": steps,
            "failed_steps": failures,
            "pipeline_state": manifest_state,
        }

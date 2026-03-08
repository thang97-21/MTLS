"""Series bible MCP tools."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Optional

from pipeline.metadata_processor.bible_sync import BibleSyncAgent
from pipeline.translator.series_bible_rag import SeriesBibleRAG

from ..config import MCPConfig
from ..runtime import (
    load_manifest,
    read_json_file,
    resolve_bible_file,
    resolve_volume_dir,
)


def register_bible_tools(mcp: object, cfg: MCPConfig) -> None:
    """Register bible management tools."""

    @mcp.tool()  # type: ignore[attr-defined]
    def resolve_bible(volume_id: str) -> dict:
        volume_dir = resolve_volume_dir(volume_id, cfg)
        manifest = load_manifest(volume_id, cfg)
        sync = BibleSyncAgent(work_dir=volume_dir, pipeline_root=cfg.pipeline_root)
        resolved = sync.resolve(manifest)
        bible_path = str((cfg.bibles_dir / f"{sync.series_id}.json")) if sync.series_id else ""
        match_patterns = []
        if sync.series_id:
            try:
                bible_payload = read_json_file(cfg.bibles_dir / f"{sync.series_id}.json", cfg)
                match_patterns = list(bible_payload.get("match_patterns", []))
            except Exception:
                match_patterns = []
        return {
            "schema": "BibleResolution",
            "resolved": bool(resolved),
            "series_id": sync.series_id,
            "path": bible_path,
            "match_patterns": match_patterns,
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def pull_bible(volume_id: str, target_lang: str = "en", import_mode: str = "canon_safe") -> dict:
        volume_dir = resolve_volume_dir(volume_id, cfg)
        manifest = load_manifest(volume_id, cfg)
        sync = BibleSyncAgent(work_dir=volume_dir, pipeline_root=cfg.pipeline_root)
        if not sync.resolve(manifest):
            return {"schema": "BiblePullResult", "ok": False, "resolved": False}
        result = sync.pull(manifest=manifest, target_language=target_lang, import_mode=import_mode)
        return {
            "schema": "BiblePullResult",
            "ok": True,
            "resolved": True,
            "series_id": sync.series_id,
            "known_terms": len(result.known_terms),
            "characters_inherited": result.characters_inherited,
            "geography_inherited": result.geography_inherited,
            "weapons_inherited": result.weapons_inherited,
            "other_inherited": result.other_inherited,
            "eps_states_inherited": result.eps_states_inherited,
            "context_block_preview": (result.context_block or "")[:1500],
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def push_bible(volume_id: str, canonical_source: str = "bible") -> dict:
        volume_dir = resolve_volume_dir(volume_id, cfg)
        manifest = load_manifest(volume_id, cfg)
        sync = BibleSyncAgent(work_dir=volume_dir, pipeline_root=cfg.pipeline_root)
        if not sync.resolve(manifest):
            return {"schema": "BiblePushResult", "ok": False, "resolved": False}
        result = sync.push(manifest=manifest, canonical_source=canonical_source)
        return {
            "schema": "BiblePushResult",
            "ok": True,
            "resolved": True,
            "series_id": sync.series_id,
            "summary": result.summary(),
            "characters_added": result.characters_added,
            "characters_enriched": result.characters_enriched,
            "characters_skipped": result.characters_skipped,
            "terms_added": result.terms_added,
            "terms_updated": result.terms_updated,
            "eps_states_updated": result.eps_states_updated,
            "conflicts": result.conflicts,
            "volume_registered": result.volume_registered,
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def list_bibles() -> dict:
        index = {}
        index_path = cfg.bibles_dir / "index.json"
        if index_path.exists():
            index = read_json_file(index_path, cfg)
        entries = []
        for path in sorted(cfg.bibles_dir.glob("*.json")):
            if path.name.startswith(".") or path.name == "index.json":
                continue
            try:
                payload = read_json_file(path, cfg)
            except Exception:
                payload = {}
            series_index = (
                (index.get("series", {}) or {}).get(path.stem, {})
                if isinstance(index, dict)
                else {}
            )
            entries.append(
                {
                    "series_id": path.stem,
                    "file": path.name,
                    "characters": len(payload.get("characters", {})) if isinstance(payload, dict) else 0,
                    "terms": len(payload.get("terminology", {})) if isinstance(payload, dict) else 0,
                    "volumes_indexed": list(series_index.get("volumes", [])) if isinstance(series_index, dict) else [],
                    "world_setting": payload.get("world_setting", {}) if isinstance(payload, dict) else {},
                }
            )
        return {"schema": "BibleList[]", "count": len(entries), "bibles": entries}

    @mcp.tool()  # type: ignore[attr-defined]
    def get_bible_characters(series_id: str) -> dict:
        path = resolve_bible_file(series_id, cfg)
        payload = read_json_file(path, cfg)
        return {
            "schema": "Characters",
            "series_id": series_id,
            "characters": payload.get("characters", {}) if isinstance(payload, dict) else {},
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def query_bible_rag(
        series_id: str,
        jp_source: str,
        bible_glossary: Optional[Dict[str, str]] = None,
        volume_id_exclude: str = "",
        max_passages: int = 24,
    ) -> dict:
        rag = SeriesBibleRAG(series_id=series_id, pipeline_root=cfg.pipeline_root)
        passages = rag.retrieve_for_chapter(
            jp_source=jp_source or "",
            bible_glossary=bible_glossary or {},
            max_passages=max(1, int(max_passages)),
            volume_id_exclude=volume_id_exclude or None,
        )
        return {
            "schema": "BiblePassage[]",
            "available": rag.is_available,
            "count": len(passages),
            "passages": [_serialize(item) for item in passages],
            "prompt_block": rag.format_for_prompt(passages),
        }


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return value

"""Volume context cache resources."""

from __future__ import annotations

from pathlib import Path

from ..config import MCPConfig
from ..runtime import MCPRuntimeError, read_json_file, read_text_file, resolve_volume_dir


def register_context_resources(mcp: object, cfg: MCPConfig) -> None:
    """Register `.context` cache resources."""

    @mcp.resource("context://{volume_id}/{cache_name}")  # type: ignore[attr-defined]
    def get_context_cache(volume_id: str, cache_name: str) -> dict:
        volume_dir = resolve_volume_dir(volume_id, cfg)
        context_dir = volume_dir / ".context"
        stem = str(cache_name or "").strip()
        if not stem:
            raise MCPRuntimeError("cache_name is required")
        json_path = context_dir / f"{stem}.json"
        if not json_path.exists():
            return {}
        return read_json_file(json_path, cfg)

    @mcp.resource("context://{volume_id}/{cache_name}.md")  # type: ignore[attr-defined]
    def get_context_cache_markdown(volume_id: str, cache_name: str) -> str:
        volume_dir = resolve_volume_dir(volume_id, cfg)
        context_dir = volume_dir / ".context"
        stem = str(cache_name or "").strip()
        if not stem:
            raise MCPRuntimeError("cache_name is required")
        md_path = context_dir / f"{stem}.md"
        if not md_path.exists():
            return ""
        return read_text_file(md_path, cfg)

    @mcp.resource("context://{volume_id}")  # type: ignore[attr-defined]
    def list_context_caches(volume_id: str) -> dict:
        volume_dir = resolve_volume_dir(volume_id, cfg)
        context_dir = volume_dir / ".context"
        if not context_dir.exists():
            return {"volume_id": volume_id, "files": []}
        files = sorted([p.name for p in context_dir.iterdir() if p.is_file()])
        return {"volume_id": volume_id, "files": files}


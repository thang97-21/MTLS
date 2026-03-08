"""Chroma vector store resources."""

from __future__ import annotations

from pathlib import Path

from ..config import MCPConfig
from ..runtime import MCPRuntimeError, ensure_allowed_path


def register_chroma_resources(mcp: object, cfg: MCPConfig) -> None:
    """Register `chroma://` resources."""

    @mcp.resource("chroma://{store_name}")  # type: ignore[attr-defined]
    def get_chroma_store_meta(store_name: str) -> dict:
        name = str(store_name or "").strip()
        if not name:
            raise MCPRuntimeError("store_name is required")
        path = cfg.pipeline_root / f"chroma_{name}"
        safe = ensure_allowed_path(path, cfg)
        return _describe_store(safe, name)

    @mcp.resource("chroma://series_bible/{series_id}")  # type: ignore[attr-defined]
    def get_series_bible_store(series_id: str) -> dict:
        sid = str(series_id or "").strip()
        if not sid:
            raise MCPRuntimeError("series_id is required")
        path = cfg.pipeline_root / "chroma_series_bible" / sid
        safe = ensure_allowed_path(path, cfg)
        return _describe_store(safe, f"series_bible/{sid}")


def _describe_store(path: Path, store_name: str) -> dict:
    """Return basic metadata for a Chroma store directory."""
    if not path.exists():
        return {
            "store": store_name,
            "path": str(path),
            "exists": False,
            "file_count": 0,
            "total_size_bytes": 0,
        }
    files = [p for p in path.rglob("*") if p.is_file()]
    size = sum(p.stat().st_size for p in files)
    return {
        "store": store_name,
        "path": str(path),
        "exists": True,
        "file_count": len(files),
        "total_size_bytes": size,
    }


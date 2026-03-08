"""RAG resources for modules/config JSONs."""

from __future__ import annotations

from ..config import MCPConfig
from ..runtime import read_json_file, read_text_file


def register_rag_resources(mcp: object, cfg: MCPConfig) -> None:
    """Register `rag://` resources."""

    @mcp.resource("rag://modules/{module_name}")  # type: ignore[attr-defined]
    def get_rag_module(module_name: str) -> str:
        name = str(module_name or "").strip()
        if not name.endswith(".md"):
            name = f"{name}.md"
        path = cfg.modules_dir / name
        return read_text_file(path, cfg)

    @mcp.resource("rag://config/{config_name}")  # type: ignore[attr-defined]
    def get_rag_config(config_name: str) -> dict:
        name = str(config_name or "").strip()
        if not name.endswith(".json"):
            name = f"{name}.json"
        path = cfg.config_dir / name
        return read_json_file(path, cfg)


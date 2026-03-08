"""Main MCP server entry point for MTL Studio."""

from __future__ import annotations

import os
import sys
from typing import Any

from .config import default_mcp_config
from .prompts import register_prompt_templates
from .resources import (
    register_bible_resources,
    register_chroma_resources,
    register_config_resources,
    register_context_resources,
    register_epub_resources,
    register_manifest_resources,
    register_prompt_resources,
    register_rag_resources,
)
from .servers import (
    register_bible_tools,
    register_builder_tools,
    register_config_tools,
    register_librarian_tools,
    register_metadata_tools,
    register_postprocessor_tools,
    register_qc_tools,
    register_translator_tools,
)


MCP_INSTRUCTIONS = (
    "MTL Studio pipeline tools by phase: "
    "Phase 1 librarian extraction, "
    "Phase 1.15-1.7 metadata processing, "
    "Phase 2 translation, "
    "Phase 2.5 post-processing and bible updates, "
    "Phase 3 audit/QC, "
    "Phase 4 builder packaging, "
    "plus config/bible resources and prompt templates."
)


def create_mcp_server() -> Any:
    """Build and register the MTL Studio FastMCP server."""
    cfg = default_mcp_config()

    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:
        raise RuntimeError(
            "Missing MCP dependency. Install with: "
            f"`{sys.executable} -m pip install -r requirements-mcp.txt`"
        ) from exc

    try:
        mcp = FastMCP(cfg.server_name, instructions=MCP_INSTRUCTIONS)
    except TypeError:
        mcp = FastMCP(cfg.server_name)

    # Resources
    register_epub_resources(mcp, cfg)
    register_manifest_resources(mcp, cfg)
    register_bible_resources(mcp, cfg)
    register_context_resources(mcp, cfg)
    register_config_resources(mcp, cfg)
    register_rag_resources(mcp, cfg)
    register_prompt_resources(mcp, cfg)
    register_chroma_resources(mcp, cfg)

    # Prompts
    register_prompt_templates(mcp, cfg)

    # Tools
    register_librarian_tools(mcp, cfg)
    register_metadata_tools(mcp, cfg)
    register_translator_tools(mcp, cfg)
    register_postprocessor_tools(mcp, cfg)
    register_builder_tools(mcp, cfg)
    register_bible_tools(mcp, cfg)
    register_qc_tools(mcp, cfg)
    register_config_tools(mcp, cfg)

    return mcp


def main() -> None:
    """Entrypoint used by `python -m pipeline.mcp.server`."""
    try:
        mcp = create_mcp_server()
    except Exception as exc:
        print(f"[MCP] Failed to initialize server: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    transport = str(os.getenv("MCP_TRANSPORT", "stdio")).strip().lower()
    if transport in {"", "stdio"}:
        mcp.run()
        return

    # Optional transport override for development.
    if transport in {"http", "streamable-http"}:
        host = os.getenv("MCP_HTTP_HOST", "127.0.0.1")
        port = int(os.getenv("MCP_HTTP_PORT", "8765"))
        try:
            mcp.run(transport="streamable-http", host=host, port=port)
            return
        except TypeError:
            mcp.run(transport="streamable-http")
            return

    if transport == "sse":
        mcp.run(transport="sse")
        return

    mcp.run()


if __name__ == "__main__":
    main()


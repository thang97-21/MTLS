"""Prompt file resources."""

from __future__ import annotations

from ..config import MCPConfig
from ..runtime import read_text_file


def register_prompt_resources(mcp: object, cfg: MCPConfig) -> None:
    """Register `prompt://` resources."""

    @mcp.resource("prompt://master_prompt/{lang}")  # type: ignore[attr-defined]
    def get_master_prompt(lang: str) -> str:
        language = str(lang or "").strip().lower()
        if language in {"vn", "vi"}:
            path = cfg.pipeline_root / "VN" / "master_prompt_vn_pipeline.xml"
        else:
            path = cfg.prompts_dir / "master_prompt_en_compressed.xml"
        return read_text_file(path, cfg)

    @mcp.resource("prompt://metadata_processor/{lang}")  # type: ignore[attr-defined]
    def get_metadata_prompt(lang: str) -> str:
        language = str(lang or "").strip().lower()
        if language in {"vn", "vi"}:
            path = cfg.prompts_dir / "metadata_processor_prompt_vn.xml"
        else:
            path = cfg.prompts_dir / "metadata_processor_prompt.xml"
        return read_text_file(path, cfg)


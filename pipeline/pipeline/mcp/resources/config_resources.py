"""Config resources."""

from __future__ import annotations

from ..config import MCPConfig, redact_config
from ..runtime import load_yaml, read_json_file


def register_config_resources(mcp: object, cfg: MCPConfig) -> None:
    """Register config and style resources."""

    @mcp.resource("config://pipeline")  # type: ignore[attr-defined]
    def get_pipeline_config() -> dict:
        return redact_config(load_yaml(cfg.config_path, cfg))

    @mcp.resource("config://{section}")  # type: ignore[attr-defined]
    def get_pipeline_config_section(section: str) -> dict:
        payload = load_yaml(cfg.config_path, cfg)
        key = str(section or "").strip()
        if not key:
            return {}
        value = payload.get(key, {})
        if isinstance(value, dict):
            return redact_config(value)
        return {"value": value}

    @mcp.resource("config://anthropic")  # type: ignore[attr-defined]
    def get_anthropic_config() -> dict:
        payload = load_yaml(cfg.config_path, cfg)
        value = payload.get("anthropic", {})
        return redact_config(value) if isinstance(value, dict) else {}

    @mcp.resource("config://gemini")  # type: ignore[attr-defined]
    def get_gemini_config() -> dict:
        payload = load_yaml(cfg.config_path, cfg)
        value = payload.get("gemini", {})
        return redact_config(value) if isinstance(value, dict) else {}

    @mcp.resource("style://base/{lang}")  # type: ignore[attr-defined]
    def get_base_style(lang: str) -> dict:
        language = str(lang or "").strip().lower()
        if language == "vn":
            language = "vi"
        path = cfg.style_guides_dir / f"base_style_{language}.json"
        return read_json_file(path, cfg)

    @mcp.resource("style://genre/{genre}")  # type: ignore[attr-defined]
    def get_genre_style(genre: str) -> dict:
        normalized = str(genre or "").strip().lower().replace(" ", "_")
        path = cfg.style_guides_dir / "genres" / f"{normalized}_en.json"
        if not path.exists():
            path = cfg.style_guides_dir / "genres" / f"{normalized}_vi.json"
        return read_json_file(path, cfg)

    @mcp.resource("filter://base")  # type: ignore[attr-defined]
    def get_base_name_filter() -> dict:
        path = cfg.pipeline_root / "pipeline" / "librarian" / "name_filters" / "base_filters.json"
        return read_json_file(path, cfg)

    @mcp.resource("filter://genre/{genre}")  # type: ignore[attr-defined]
    def get_genre_name_filter(genre: str) -> dict:
        normalized = str(genre or "").strip().lower().replace(" ", "_")
        path = (
            cfg.pipeline_root
            / "pipeline"
            / "librarian"
            / "name_filters"
            / "genre_filters"
            / f"{normalized}.json"
        )
        return read_json_file(path, cfg)

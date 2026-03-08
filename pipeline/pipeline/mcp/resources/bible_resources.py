"""Series bible resources."""

from __future__ import annotations

from ..config import MCPConfig
from ..runtime import read_json_file, resolve_bible_file


def register_bible_resources(mcp: object, cfg: MCPConfig) -> None:
    """Register bible resources."""

    @mcp.resource("bible://{series_id}")  # type: ignore[attr-defined]
    def get_bible(series_id: str) -> dict:
        path = resolve_bible_file(series_id, cfg)
        return read_json_file(path, cfg)

    @mcp.resource("bible://{series_id}/characters")  # type: ignore[attr-defined]
    def get_bible_characters(series_id: str) -> dict:
        payload = get_bible(series_id)
        return payload.get("characters", {}) if isinstance(payload, dict) else {}

    @mcp.resource("bible://{series_id}/culturally_loaded_terms")  # type: ignore[attr-defined]
    def get_bible_cultural_terms(series_id: str) -> dict:
        payload = get_bible(series_id)
        return payload.get("culturally_loaded_terms", {}) if isinstance(payload, dict) else {}


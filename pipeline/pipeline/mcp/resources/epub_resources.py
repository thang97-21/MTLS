"""EPUB chapter resources."""

from __future__ import annotations

from ..config import MCPConfig
from ..runtime import read_text_file, resolve_chapter_markdown, resolve_volume_dir


def register_epub_resources(mcp: object, cfg: MCPConfig) -> None:
    """Register EPUB chapter content resources."""

    @mcp.resource("epub://{volume_id}/jp/{chapter_id}")  # type: ignore[attr-defined]
    def get_jp_chapter(volume_id: str, chapter_id: str) -> str:
        volume_dir = resolve_volume_dir(volume_id, cfg)
        path = resolve_chapter_markdown(volume_dir, "jp", chapter_id, cfg)
        return read_text_file(path, cfg)

    @mcp.resource("epub://{volume_id}/en/{chapter_id}")  # type: ignore[attr-defined]
    def get_en_chapter(volume_id: str, chapter_id: str) -> str:
        volume_dir = resolve_volume_dir(volume_id, cfg)
        path = resolve_chapter_markdown(volume_dir, "en", chapter_id, cfg)
        return read_text_file(path, cfg)

    @mcp.resource("epub://{volume_id}/vn/{chapter_id}")  # type: ignore[attr-defined]
    def get_vn_chapter(volume_id: str, chapter_id: str) -> str:
        volume_dir = resolve_volume_dir(volume_id, cfg)
        path = resolve_chapter_markdown(volume_dir, "vn", chapter_id, cfg)
        return read_text_file(path, cfg)


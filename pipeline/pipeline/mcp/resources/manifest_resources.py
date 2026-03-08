"""Manifest resources."""

from __future__ import annotations

from ..config import MCPConfig
from ..runtime import load_manifest


def register_manifest_resources(mcp: object, cfg: MCPConfig) -> None:
    """Register manifest resources."""

    @mcp.resource("manifest://{volume_id}")  # type: ignore[attr-defined]
    def get_manifest(volume_id: str) -> dict:
        return load_manifest(volume_id, cfg)

    @mcp.resource("manifest://{volume_id}/metadata_en")  # type: ignore[attr-defined]
    def get_manifest_metadata_en(volume_id: str) -> dict:
        manifest = load_manifest(volume_id, cfg)
        return manifest.get("metadata_en", {}) if isinstance(manifest, dict) else {}

    @mcp.resource("manifest://{volume_id}/metadata_vn")  # type: ignore[attr-defined]
    def get_manifest_metadata_vn(volume_id: str) -> dict:
        manifest = load_manifest(volume_id, cfg)
        return manifest.get("metadata_vn", {}) if isinstance(manifest, dict) else {}


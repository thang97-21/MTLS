"""Configuration management MCP tools."""

from __future__ import annotations

from typing import Any, Dict

from ..config import MCPConfig, redact_config
from ..runtime import (
    MCPRuntimeError,
    list_volume_ids,
    load_manifest,
    load_yaml,
    write_yaml,
)


def register_config_tools(mcp: object, cfg: MCPConfig) -> None:
    """Register config MCP tools."""

    @mcp.tool()  # type: ignore[attr-defined]
    def get_config() -> dict:
        payload = load_yaml(cfg.config_path, cfg)
        result = redact_config(payload)
        result["schema"] = "Config"
        return result

    @mcp.tool()  # type: ignore[attr-defined]
    def set_target_language(language: str) -> dict:
        lang = str(language or "").strip().lower()
        if lang not in {"en", "vn", "vi"}:
            raise MCPRuntimeError("language must be one of: en, vn, vi")
        if lang == "vi":
            lang = "vn"
        config_data = load_yaml(cfg.config_path, cfg)
        project = config_data.setdefault("project", {})
        if not isinstance(project, dict):
            project = {}
            config_data["project"] = project
        project["target_language"] = lang
        write_yaml(cfg.config_path, config_data, cfg)
        return {"schema": "bool", "ok": True, "target_language": lang}

    @mcp.tool()  # type: ignore[attr-defined]
    def set_provider(provider: str) -> dict:
        selected = str(provider or "").strip().lower()
        if selected not in {"anthropic", "gemini"}:
            raise MCPRuntimeError("provider must be 'anthropic' or 'gemini'")
        config_data = load_yaml(cfg.config_path, cfg)
        config_data["translator_provider"] = selected
        write_yaml(cfg.config_path, config_data, cfg)
        return {"schema": "bool", "ok": True, "translator_provider": selected}

    @mcp.tool()  # type: ignore[attr-defined]
    def set_model(model: str, provider: str = "") -> dict:
        name = str(model or "").strip()
        if not name:
            raise MCPRuntimeError("model is required")
        config_data = load_yaml(cfg.config_path, cfg)
        selected_provider = str(provider or config_data.get("translator_provider", "anthropic")).lower().strip()
        if selected_provider not in {"anthropic", "gemini"}:
            raise MCPRuntimeError("provider must be 'anthropic' or 'gemini'")
        provider_block = config_data.setdefault(selected_provider, {})
        if not isinstance(provider_block, dict):
            provider_block = {}
            config_data[selected_provider] = provider_block
        provider_block["model"] = name
        write_yaml(cfg.config_path, config_data, cfg)
        return {"schema": "bool", "ok": True, "provider": selected_provider, "model": name}

    @mcp.tool()  # type: ignore[attr-defined]
    def toggle_feature(feature: str, enabled: bool) -> dict:
        key = str(feature or "").strip().lower()
        config_data = load_yaml(cfg.config_path, cfg)
        updates = _feature_toggle_mapping(config_data, key, bool(enabled))
        if not updates:
            raise MCPRuntimeError(
                "Unsupported feature. Supported: caching, multimodal, tool_mode, thinking, phase_2_5"
            )
        write_yaml(cfg.config_path, config_data, cfg)
        return {"schema": "bool", "ok": True, "feature": key, "enabled": bool(enabled), "updated_keys": updates}

    @mcp.tool()  # type: ignore[attr-defined]
    def list_volumes() -> dict:
        volumes = list_volume_ids(cfg)
        return {"schema": "VolumeList[]", "count": len(volumes), "volumes": volumes}

    @mcp.tool()  # type: ignore[attr-defined]
    def get_volume_status(volume_id: str) -> dict:
        manifest = load_manifest(volume_id, cfg)
        chapter_total = len(manifest.get("chapters", [])) if isinstance(manifest, dict) else 0
        pipeline_state = manifest.get("pipeline_state", {}) if isinstance(manifest, dict) else {}
        return {
            "schema": "VolumeStatus",
            "volume_id": volume_id,
            "chapter_count": chapter_total,
            "pipeline_state": pipeline_state,
        }


def _feature_toggle_mapping(config_data: Dict[str, Any], feature: str, enabled: bool) -> list[str]:
    """Apply feature toggle updates in config data and return updated keys."""
    updates: list[str] = []
    if feature == "caching":
        for provider in ("anthropic", "gemini"):
            block = config_data.get(provider, {})
            if not isinstance(block, dict):
                continue
            caching = block.setdefault("caching", {})
            if isinstance(caching, dict):
                caching["enabled"] = enabled
                updates.append(f"{provider}.caching.enabled")
        return updates

    if feature == "multimodal":
        translation = config_data.setdefault("translation", {})
        if isinstance(translation, dict):
            translation["enable_multimodal"] = enabled
            updates.append("translation.enable_multimodal")
        multimodal = config_data.setdefault("multimodal", {})
        if isinstance(multimodal, dict):
            multimodal["enabled"] = enabled
            updates.append("multimodal.enabled")
        return updates

    if feature == "tool_mode":
        translation = config_data.setdefault("translation", {})
        if isinstance(translation, dict):
            tool_mode = translation.setdefault("tool_mode", {})
            if isinstance(tool_mode, dict):
                tool_mode["enabled"] = enabled
                updates.append("translation.tool_mode.enabled")
        return updates

    if feature == "thinking":
        for provider in ("anthropic", "gemini"):
            block = config_data.get(provider, {})
            if not isinstance(block, dict):
                continue
            thinking = block.setdefault("thinking_mode", {})
            if isinstance(thinking, dict):
                thinking["enabled"] = enabled
                updates.append(f"{provider}.thinking_mode.enabled")
        return updates

    if feature == "phase_2_5":
        translation = config_data.setdefault("translation", {})
        if isinstance(translation, dict):
            phase_2_5 = translation.setdefault("phase_2_5", {})
            if isinstance(phase_2_5, dict):
                phase_2_5["run_bible_update"] = enabled
                updates.append("translation.phase_2_5.run_bible_update")
        return updates

    return []

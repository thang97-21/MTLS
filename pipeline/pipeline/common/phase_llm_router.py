"""Phase-aware LLM client router.

Selects `GeminiClient` or `ProxyLLMClient` from `config.yaml` proxy settings.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from pipeline.common.gemini_client import GeminiClient
from pipeline.common.openrouter_client import OpenRouterLLMClient
from pipeline.common.proxy_client import ProxyLLMClient
from pipeline.config import get_config_section


class PhaseLLMRouter:
    """Factory router for phase-specific LLM client selection."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._proxy_config = config if config is not None else (get_config_section("proxy") or {})
        self._inference_cfg = self._proxy_config.get("inference", {}) if isinstance(self._proxy_config, dict) else {}
        self._phase_overrides = self._proxy_config.get("phase_overrides", {}) if isinstance(self._proxy_config, dict) else {}

    def _provider(self) -> str:
        provider = str(self._inference_cfg.get("provider") or "yescale").strip().lower()
        return provider or "yescale"

    def _proxy_env_available(self) -> bool:
        default_env = "OPENROUTER_API_KEY" if self._provider() == "openrouter" else "YESCALE_API_KEY"
        api_env = str(self._inference_cfg.get("api_key_env") or default_env).strip() or default_env
        return bool(os.getenv(api_env))

    def _resolve_mode(self, phase: str) -> str:
        phase_key = str(phase)
        forced_mode = (self._phase_overrides or {}).get(phase_key)
        if isinstance(forced_mode, str) and forced_mode.strip():
            return forced_mode.strip().lower()

        enabled_default = bool(self._proxy_config.get("enabled_default", False)) if isinstance(self._proxy_config, dict) else False
        return "proxy" if enabled_default else "direct"

    def get_client(
        self,
        phase: str,
        model: str = "gemini-2.5-pro",
        enable_caching: bool = True,
        **kwargs: Any,
    ):
        mode = self._resolve_mode(phase)

        if mode == "proxy" and self._proxy_env_available():
            provider = self._provider()
            if provider == "openrouter":
                target_model = str(self._inference_cfg.get("default_model") or model).strip() or model
                return OpenRouterLLMClient(
                    api_key=kwargs.get("api_key"),
                    model=target_model,
                    enable_caching=enable_caching,
                    timeout_seconds=kwargs.get("timeout_seconds"),
                    base_url=kwargs.get("base_url"),
                )

            return ProxyLLMClient(
                api_key=kwargs.get("api_key"),
                model=model,
                enable_caching=enable_caching,
                timeout_seconds=kwargs.get("timeout_seconds"),
                base_url=kwargs.get("base_url"),
            )

        return GeminiClient(
            api_key=kwargs.get("api_key"),
            model=model,
            enable_caching=enable_caching,
            backend=kwargs.get("backend"),
            project=kwargs.get("project"),
            location=kwargs.get("location"),
        )

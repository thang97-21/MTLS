"""YEScale control-plane REST client."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

from pipeline.config import get_config_section


class ProxyControlPlaneClient:
    """Client wrapper for YEScale web API control-plane endpoints."""

    def __init__(
        self,
        access_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_seconds: float = 30.0,
    ):
        proxy_cfg = get_config_section("proxy") or {}
        control_cfg = proxy_cfg.get("control_plane", {}) if isinstance(proxy_cfg, dict) else {}

        self.base_url = (base_url or control_cfg.get("base_url") or "https://web-api.yescale.vip").rstrip("/")
        access_env = str(control_cfg.get("access_key_env") or "YESCALE_ACCESS_KEY").strip() or "YESCALE_ACCESS_KEY"
        self.access_key = access_key or os.getenv(access_env)
        if not self.access_key:
            raise ValueError(f"YEScale access key missing. Set {access_env} or pass access_key.")

        self.timeout_seconds = float(timeout_seconds)

    @property
    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.access_key}"}

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        response = httpx.get(url, headers=self._headers, params=params or {}, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response.json()

    def get_user(self) -> Dict[str, Any]:
        return self._get("/yescale/user")

    def list_models(self) -> Dict[str, Any]:
        return self._get("/yescale/models")

    def get_logs(
        self,
        *,
        page: int = 1,
        page_size: int = 200,
        log_type: Optional[int] = None,
        token_name: Optional[str] = None,
        model_name: Optional[str] = None,
        username: Optional[str] = None,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"p": page, "page_size": page_size}
        if log_type is not None:
            params["type"] = int(log_type)
        if token_name:
            params["token_name"] = token_name
        if model_name:
            params["model_name"] = model_name
        if username:
            params["username"] = username
        if start_timestamp is not None:
            params["start_timestamp"] = int(start_timestamp)
        if end_timestamp is not None:
            params["end_timestamp"] = int(end_timestamp)
        return self._get("/yescale/logs", params=params)

    def list_tasks(self, start_timestamp: int, end_timestamp: int) -> Dict[str, Any]:
        return self._get(
            "/yescale/task",
            params={
                "start_timestamp": int(start_timestamp),
                "end_timestamp": int(end_timestamp),
            },
        )

    def get_balance_usd(self) -> float:
        payload = self.get_user()
        data = payload.get("data") if isinstance(payload, dict) else {}
        quota = float((data or {}).get("quota") or 0.0)
        return quota / 500000.0

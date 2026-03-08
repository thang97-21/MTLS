"""OpenRouter OpenAI-compatible client adapter.

Provides a GeminiClient-compatible surface (`generate`, cache helpers,
token counting, rate limit controls) while routing inference to OpenRouter.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import backoff
import httpx

try:
    import tiktoken
except Exception:
    tiktoken = None

from pipeline.common.gemini_client import GeminiResponse
from pipeline.config import get_config_section

logger = logging.getLogger(__name__)


def _normalize_base_url(raw_url: str) -> str:
    url = (raw_url or "https://openrouter.ai/api/v1").rstrip("/")
    if url.endswith("/chat/completions"):
        return url[: -len("/chat/completions")]
    return url


@dataclass
class _EmulatedCache:
    name: str
    model: str
    system_instruction: str
    created_at: float
    contents_count: int = 0


class OpenRouterLLMClient:
    """OpenRouter adapter compatible with Gemini-style callsites."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "google/gemini-2.5-flash",
        enable_caching: bool = True,
        timeout_seconds: Optional[float] = None,
        base_url: Optional[str] = None,
    ):
        proxy_cfg = get_config_section("proxy") or {}
        inference_cfg = proxy_cfg.get("inference", {}) if isinstance(proxy_cfg, dict) else {}

        self.base_url = _normalize_base_url(base_url or inference_cfg.get("base_url") or "https://openrouter.ai/api/v1")
        api_key_env = str(inference_cfg.get("api_key_env") or "OPENROUTER_API_KEY").strip() or "OPENROUTER_API_KEY"
        self.api_key = api_key or os.getenv(api_key_env)
        if not self.api_key:
            raise ValueError(f"OpenRouter API key not found. Set {api_key_env} or pass api_key.")

        self.model = self._normalize_model_name(model or str(inference_cfg.get("default_model") or "google/gemini-2.5-flash"))
        self.enable_caching = bool(enable_caching)
        self._timeout = float(timeout_seconds or inference_cfg.get("timeout_seconds") or 600)
        self._rate_limit_delay = 6.0
        self._last_request_time = 0.0
        self._cache_ttl_minutes = 120

        self._cached_system_instruction: Optional[str] = None
        self._cached_model: Optional[str] = None
        self._cache_created_at: Optional[float] = None
        self._emulated_caches: Dict[str, _EmulatedCache] = {}

        self.thinking_mode_config: Dict[str, Any] = {"enabled": False}
        self._safety_settings: List[Any] = []

        self._tokenizer = tiktoken.get_encoding("cl100k_base") if tiktoken else None

    @staticmethod
    def _normalize_model_name(model_name: str) -> str:
        name = str(model_name or "").strip()
        if not name:
            return "google/gemini-2.5-flash"
        if "/" in name:
            return name
        if name.startswith("gemini-"):
            return f"google/{name}"
        if name.startswith("claude-"):
            return f"anthropic/{name}"
        return name

    def set_rate_limit(self, requests_per_minute: int):
        if requests_per_minute > 0:
            self._rate_limit_delay = 60.0 / requests_per_minute

    def set_cache_ttl(self, minutes: int):
        self._cache_ttl_minutes = max(1, int(minutes))

    def _build_cache_name(self, model: str, system_instruction: str) -> str:
        digest = hashlib.sha1(f"{model}|{system_instruction}".encode("utf-8")).hexdigest()[:12]
        return f"openrouter-cache-{digest}"

    def create_cache(
        self,
        *,
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
        contents: Optional[List[str]] = None,
        ttl_seconds: Optional[int] = None,
        display_name: Optional[str] = None,
        tools: Optional[List[Any]] = None,
        tool_config: Optional[Any] = None,
    ) -> Optional[str]:
        if not self.enable_caching:
            return None
        _ = (ttl_seconds, display_name, tools, tool_config)
        if not system_instruction:
            return None
        target_model = self._normalize_model_name(model or self.model)
        name = self._build_cache_name(target_model, system_instruction)
        content_items = len(contents) if isinstance(contents, list) else 0
        if content_items:
            logger.info(
                "[CACHE] OpenRouter adapter uses emulated cache metadata only: "
                "contents=%s item(s) accepted for compatibility, but not persisted server-side.",
                content_items,
            )
        now = time.time()
        self._emulated_caches[name] = _EmulatedCache(
            name=name,
            model=target_model,
            system_instruction=system_instruction,
            created_at=now,
            contents_count=content_items,
        )
        self._cached_system_instruction = system_instruction
        self._cached_model = target_model
        self._cache_created_at = now
        return name

    def delete_cache(self, cache_name: str) -> bool:
        if not cache_name:
            return False
        removed = self._emulated_caches.pop(cache_name, None)
        if removed and self._cached_system_instruction == removed.system_instruction:
            self.clear_cache()
        return removed is not None

    def clear_cache(self):
        self._cached_system_instruction = None
        self._cached_model = None
        self._cache_created_at = None

    def warm_cache(self, system_instruction: str, model: str = None) -> bool:
        return bool(self.create_cache(model=model, system_instruction=system_instruction))

    def get_token_count(self, text: str) -> int:
        if not text:
            return 0
        if self._tokenizer is not None:
            return len(self._tokenizer.encode(text))
        return max(1, len(text) // 4)

    def _is_cache_valid(self, target_model: str) -> bool:
        if not self._cached_system_instruction or not self._cache_created_at:
            return False
        if self._cached_model and target_model != self._cached_model:
            return False
        age_minutes = (time.time() - self._cache_created_at) / 60.0
        return age_minutes < self._cache_ttl_minutes

    def _resolve_cached_instruction(
        self,
        target_model: str,
        system_instruction: Optional[str],
        cached_content: Optional[str],
        force_new_session: bool,
    ) -> Optional[str]:
        if force_new_session:
            return None

        if cached_content:
            cache_entry = self._emulated_caches.get(cached_content)
            if cache_entry and cache_entry.model == target_model:
                return cache_entry.system_instruction

        if system_instruction:
            if self.enable_caching:
                self.create_cache(model=target_model, system_instruction=system_instruction)
            return system_instruction

        if self.enable_caching and self._is_cache_valid(target_model):
            return self._cached_system_instruction

        return None

    @staticmethod
    def _normalize_tools(tools: Optional[List[Any]]) -> Optional[List[Dict[str, Any]]]:
        if not tools:
            return None
        normalized: List[Dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
                normalized.append({"type": "function", "function": dict(tool["function"])})
                continue
            if isinstance(tool.get("function"), dict):
                normalized.append({"type": "function", "function": dict(tool["function"])})
        return normalized or None

    @staticmethod
    def _extract_text_from_message(message: Dict[str, Any]) -> str:
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: List[str] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") in ("text", "output_text"):
                    text_val = part.get("text")
                    if isinstance(text_val, str):
                        chunks.append(text_val)
            return "".join(chunks)
        return ""

    @backoff.on_exception(
        backoff.expo,
        (httpx.HTTPError, httpx.TimeoutException),
        max_tries=5,
        giveup=lambda e: isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500,
    )
    def generate(
        self,
        prompt: str,
        system_instruction: str = None,
        temperature: float = 0.7,
        max_output_tokens: int = 65536,
        safety_settings: Dict[str, str] = None,
        model: str = None,
        cached_content: str = None,
        force_new_session: bool = False,
        generation_config: Dict[str, Any] = None,
        tools: Optional[List[Any]] = None,
        use_tool_mode: bool = False,
        tool_handlers: Optional[Dict[str, Any]] = None,
        retrospective_anchor: Optional[str] = None,
        **kwargs: Any,
    ) -> GeminiResponse:
        _ = (safety_settings, use_tool_mode, tool_handlers, retrospective_anchor, kwargs)

        target_model = self._normalize_model_name(model or self.model)
        elapsed = time.time() - self._last_request_time
        if elapsed < self._rate_limit_delay:
            time.sleep(self._rate_limit_delay - elapsed)

        gen_cfg = generation_config or {}
        req_temperature = float(gen_cfg.get("temperature", temperature))
        req_top_p = float(gen_cfg.get("top_p", 0.95))
        req_max_output_tokens = int(gen_cfg.get("max_output_tokens", max_output_tokens))

        messages: List[Dict[str, Any]] = []
        cached_instruction = self._resolve_cached_instruction(
            target_model=target_model,
            system_instruction=system_instruction,
            cached_content=cached_content,
            force_new_session=force_new_session,
        )
        if cached_instruction:
            messages.append({"role": "system", "content": str(cached_instruction)})
        messages.append({"role": "user", "content": prompt})

        body: Dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "temperature": req_temperature,
            "top_p": req_top_p,
            "max_tokens": req_max_output_tokens,
        }

        response_mime_type = gen_cfg.get("response_mime_type")
        response_schema = gen_cfg.get("response_schema")
        if response_mime_type == "application/json" and response_schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_output",
                    "strict": True,
                    "schema": response_schema,
                },
            }

        normalized_tools = self._normalize_tools(tools)
        if normalized_tools:
            body["tools"] = normalized_tools

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        inference_cfg = (get_config_section("proxy") or {}).get("inference", {})
        if isinstance(inference_cfg, dict):
            app_headers = inference_cfg.get("app_headers", {})
            if isinstance(app_headers, dict):
                referer_env = str(app_headers.get("referer_env") or "OPENROUTER_HTTP_REFERER").strip()
                title_env = str(app_headers.get("title_env") or "OPENROUTER_APP_TITLE").strip()
                referer = os.getenv(referer_env, "").strip() if referer_env else ""
                title = os.getenv(title_env, "").strip() if title_env else ""
                if referer:
                    headers["HTTP-Referer"] = referer
                if title:
                    headers["X-OpenRouter-Title"] = title

        endpoint = f"{self.base_url}/chat/completions"
        started = time.time()
        response = httpx.post(endpoint, headers=headers, json=body, timeout=self._timeout)
        self._last_request_time = time.time()
        response.raise_for_status()
        data = response.json()
        duration = time.time() - started

        choices = data.get("choices") or []
        if not choices:
            raise ValueError("OpenRouter response missing choices")

        choice = choices[0] or {}
        message = choice.get("message") or {}
        text_content = self._extract_text_from_message(message)

        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens) or 0)

        logger.info(
            "OpenRouter generate complete (model=%s, in=%s, out=%s, total=%s, %.2fs)",
            target_model,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            duration,
        )

        return GeminiResponse(
            content=text_content,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            finish_reason=str(choice.get("finish_reason", "STOP") or "STOP"),
            model=str(data.get("model") or target_model),
            cached_tokens=0,
            thinking_content=None,
            input_cost_usd=0.0,
            output_cost_usd=0.0,
            cache_read_cost_usd=0.0,
            cache_creation_cost_usd=0.0,
            total_cost_usd=0.0,
            cost_audit={
                "schema_version": "1.0",
                "provider": "openrouter",
                "request_type": "generate",
                "totals": {
                    "input_tokens": prompt_tokens,
                    "output_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "cached_tokens": 0,
                    "total_cost_usd": 0.0,
                },
                "response_id": data.get("id"),
            },
        )

"""Config-driven embedding client with OpenRouter/Gemini support."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Sequence, Union

import httpx

from pipeline.common.genai_factory import create_genai_client, resolve_api_key
from pipeline.config import get_config_section

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """Embedding client routed by config.yaml.

    Provider resolution:
    - `proxy.inference.provider == openrouter` -> OpenRouter `/embeddings`
    - otherwise -> Gemini `models.embed_content`
    """

    def __init__(self, api_key: Optional[str] = None):
        proxy_cfg = get_config_section("proxy") or {}
        inference_cfg = proxy_cfg.get("inference", {}) if isinstance(proxy_cfg, dict) else {}
        gemini_cfg = get_config_section("gemini") or {}

        provider = str(inference_cfg.get("provider") or "direct").strip().lower()
        self.provider = "openrouter" if provider == "openrouter" else "gemini"

        if self.provider == "openrouter":
            self.model = str(
                inference_cfg.get("embedding_model")
                or inference_cfg.get("default_embedding_model")
                or "openai/text-embedding-3-large"
            ).strip()
            self.base_url = str(inference_cfg.get("base_url") or "https://openrouter.ai/api/v1").rstrip("/")
            api_key_env = str(inference_cfg.get("api_key_env") or "OPENROUTER_API_KEY").strip() or "OPENROUTER_API_KEY"
            self.api_key = api_key or os.getenv(api_key_env)
            self.timeout = float(inference_cfg.get("timeout_seconds") or 600)
            self.max_input_chars = int(inference_cfg.get("embedding_max_input_chars") or 12000)
            self.app_headers = inference_cfg.get("app_headers", {}) if isinstance(inference_cfg, dict) else {}
            if not self.api_key:
                raise ValueError(f"OpenRouter embedding key not found. Set {api_key_env} or pass api_key.")
            self._gemini_client = None
        else:
            self.model = str(gemini_cfg.get("embedding_model") or "text-embedding-004").strip()
            self.api_key = resolve_api_key(api_key=api_key, required=False)
            self.base_url = ""
            self.timeout = 0.0
            self.max_input_chars = int(gemini_cfg.get("embedding_max_input_chars") or 12000)
            self.app_headers = {}
            self._gemini_client = create_genai_client(api_key=self.api_key) if self.api_key else None
            if self._gemini_client is None:
                raise ValueError("Gemini embedding key not found. Set GOOGLE_API_KEY or GEMINI_API_KEY.")

    def _openrouter_headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        referer_env = str(self.app_headers.get("referer_env") or "OPENROUTER_HTTP_REFERER").strip()
        title_env = str(self.app_headers.get("title_env") or "OPENROUTER_APP_TITLE").strip()
        referer = os.getenv(referer_env, "").strip() if referer_env else ""
        title = os.getenv(title_env, "").strip() if title_env else ""
        if referer:
            headers["HTTP-Referer"] = referer
        if title:
            headers["X-OpenRouter-Title"] = title
        return headers

    @staticmethod
    def _normalize_texts(texts: Sequence[Union[str, Any]]) -> List[str]:
        normalized: List[str] = []
        for item in texts:
            if isinstance(item, str):
                normalized.append(item)
            elif item is None:
                normalized.append("")
            else:
                normalized.append(str(item))
        return normalized

    def _embed_openrouter(self, texts: List[str]) -> List[List[float]]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "input": texts if len(texts) != 1 else texts[0],
        }
        url = f"{self.base_url}/embeddings"
        response = httpx.post(
            url,
            headers=self._openrouter_headers(),
            json=payload,
            timeout=self.timeout,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body_preview = (exc.response.text or "").strip().replace("\n", " ")
            if len(body_preview) > 320:
                body_preview = body_preview[:320] + " … [truncated]"
            raise RuntimeError(
                f"OpenRouter embeddings HTTP {exc.response.status_code} for model '{self.model}'. "
                f"Response: {body_preview}"
            ) from exc

        data = response.json().get("data", [])
        if not isinstance(data, list) or not data:
            raise ValueError("OpenRouter embeddings response missing data")

        data_sorted = sorted(data, key=lambda item: int(item.get("index", 0)))
        vectors: List[List[float]] = []
        for item in data_sorted:
            embedding = item.get("embedding")
            if not isinstance(embedding, list):
                raise ValueError("OpenRouter embeddings response missing embedding vector")
            vectors.append([float(v) for v in embedding])
        return vectors

    def _embed_gemini(self, texts: List[str]) -> List[List[float]]:
        if self._gemini_client is None:
            raise RuntimeError("Gemini embedding client is not initialized")
        result = self._gemini_client.models.embed_content(
            model=self.model,
            contents=texts if len(texts) != 1 else texts[0],
        )
        embeddings = getattr(result, "embeddings", None)
        if not embeddings:
            raise ValueError("Gemini embedding response missing embeddings")
        return [[float(v) for v in emb.values] for emb in embeddings]

    def embed_texts(self, texts: Sequence[Union[str, Any]]) -> List[List[float]]:
        normalized = self._normalize_texts(texts)
        if not normalized:
            return []

        max_chars = max(1, int(self.max_input_chars or 12000))
        truncated = 0
        for idx, value in enumerate(normalized):
            if len(value) > max_chars:
                normalized[idx] = value[:max_chars]
                truncated += 1
        if truncated:
            logger.warning(
                "[EMBED] Truncated %s input(s) to %s chars before embedding (provider=%s, model=%s).",
                truncated,
                max_chars,
                self.provider,
                self.model,
            )

        if self.provider == "openrouter":
            return self._embed_openrouter(normalized)
        return self._embed_gemini(normalized)

    def embed_text(self, text: Union[str, Any]) -> List[float]:
        vectors = self.embed_texts([text])
        if not vectors:
            raise ValueError("No embedding returned")
        return vectors[0]

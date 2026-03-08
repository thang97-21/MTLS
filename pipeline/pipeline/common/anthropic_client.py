"""
Anthropic Claude client for MTL Studio — Translator path only.

Mirrors the GeminiClient public interface so ChapterProcessor and all
downstream call sites require zero modification.

Sub-agents (planner, summarizer, metadata, rich_metadata_cache) remain
Gemini-only and never instantiate this class.

=== HOW ANTHROPIC CACHING MAPS TO THE GEMINI INTERFACE ===

Gemini uses named server-side CachedContent resources:
  - create_cache(system_instruction, contents=[full_jp_corpus]) → "cachedContents/abc123"
  - generate(cached_content="cachedContents/abc123") → model uses cache

Anthropic uses inline cache_control blocks on the request itself:
  - The system array carries BOTH the system instruction AND the full JP corpus
  - The last (corpus) block gets cache_control: {type: "ephemeral"}
  - On subsequent calls with identical prefix bytes → cache hit, 0.10x read cost
  - No named resource, no server-side object to delete

Translation of the interface:
  create_cache(system_instruction, contents)  → stores both in memory as self._cached_system_blocks
  delete_cache(cache_name)                    → clears self._cached_system_blocks
  warm_cache(system_instruction)              → stores system_instruction-only blocks
  generate(cached_content="<any non-empty>") → uses self._cached_system_blocks if available
  generate(cached_content=None)              → sends system_instruction plain (no cache blocks)

Minimum cache threshold for Sonnet 4.6: 1,024 tokens.
Our system prompt alone is ~10,487 tokens — well above the limit.
With full JP corpus the total is typically 35,000–60,000 tokens.

TTL options: "5m" (default, free refresh) | "1h" (2x write cost, configurable).
For our inter-chapter cadence (~30–120s between chapters), "5m" is sufficient.
The config key anthropic.caching.ttl controls this.
"""

import os
import time
import logging
import importlib
import backoff
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from pipeline.common.gemini_client import GeminiResponse  # reuse same dataclass
from pipeline.translator.tools import (
    TOOL_NAME_DECLARE_TRANSLATION_PARAMETERS,
    TOOL_NAME_FLAG_STRUCTURAL_CONSTRAINT,
    TOOL_NAME_REPORT_TRANSLATION_QC,
    handle_declare_translation_parameters,
)

logger = logging.getLogger(__name__)

# Sentinel string returned by create_cache() so the caller can detect success
# (GeminiClient returns a real resource name; we return this constant instead)
_ANTHROPIC_CACHE_SENTINEL = "__anthropic_inline_cache__"


def _summarize_api_exception(exc: Exception) -> str:
    """Return a compact, safe API error summary without dumping raw bodies."""
    message = str(exc or "").strip()
    if not message:
        return exc.__class__.__name__

    lowered = message.lower()
    if "<!doctype html" in lowered or "<html" in lowered:
        if "openrouter" in lowered and "not found" in lowered:
            return (
                "OpenRouter returned HTML 404 (Not Found). "
                "Check proxy endpoint/base URL and anthropic-compatible route configuration."
            )
        return "Upstream returned HTML (non-JSON) error response; raw body suppressed."

    if len(message) > 280:
        return message[:280].rstrip() + " … [truncated]"
    return message


def _normalize_anthropic_base_url(raw_base_url: Optional[str]) -> Optional[str]:
    """
    Normalize provider proxy base URLs for Anthropic SDK compatibility.

    Anthropic SDK appends `/v1/messages` to `base_url`. For OpenRouter,
    the valid messages endpoint is `https://openrouter.ai/api/v1/messages`,
    so the SDK base URL must be `https://openrouter.ai/api`.
    """
    if not isinstance(raw_base_url, str):
        return raw_base_url

    base_url = raw_base_url.strip().rstrip("/")
    if not base_url:
        return base_url

    lowered = base_url.lower()
    if "openrouter.ai" not in lowered:
        return base_url

    # Normalize common misconfigurations introduced by mixing OpenRouter's
    # OpenAI-compatible base (`/api/v1`) with Anthropic SDK routing.
    openrouter_bad_suffixes = (
        "/api/v1/anthropic",
        "/api/v1",
        "/api/anthropic/v1",
        "/api/anthropic",
    )
    for suffix in openrouter_bad_suffixes:
        if lowered.endswith(suffix):
            return f"{base_url[:-len(suffix)]}/api"

    return base_url


class AnthropicClient:
    """
    Anthropic Claude client with the same public interface as GeminiClient.

    Implements the full caching surface used by the translator path:
      create_cache()  — stores system+corpus blocks for inline cache injection
      delete_cache()  — clears stored blocks
      warm_cache()    — stores system-instruction-only blocks
      generate()      — injects stored blocks as the system array when caching is active
      get_token_count()

    Gemini-specific internals (google.genai types, Vertex backend, etc.) are
    intentionally absent.
    """

    _DEFAULT_HTTP_TIMEOUT_SECONDS = 600.0
    # Anthropic Sonnet 4.6 minimum cacheable prefix: 1,024 tokens
    _MIN_CACHE_TOKENS = 1024
    # Fast mode beta header (research preview)
    _FAST_MODE_BETA = "fast-mode-2026-02-01"
    # Anthropic API pricing (USD per 1M tokens, 2026 official docs).
    _MODEL_BASE_RATES_PER_MTOK: Dict[str, Tuple[float, float]] = {
        "claude-opus-4-6": (5.00, 25.00),
        "claude-opus-4-5": (5.00, 25.00),
        "claude-opus-4-1": (15.00, 75.00),
        "claude-opus-4": (15.00, 75.00),
        "claude-sonnet-4-6": (3.00, 15.00),
        "claude-sonnet-4-5": (3.00, 15.00),
        "claude-sonnet-4": (3.00, 15.00),
        "claude-sonnet-3-7": (3.00, 15.00),
        "claude-haiku-4-5": (1.00, 5.00),
        "claude-haiku-3-5": (0.80, 4.00),
        "claude-haiku-3": (0.25, 1.25),
    }
    _PROMPT_CACHE_WRITE_MULTIPLIER_5M = 1.25
    _PROMPT_CACHE_WRITE_MULTIPLIER_1H = 2.00
    _PROMPT_CACHE_READ_MULTIPLIER = 0.10
    _BATCH_DISCOUNT_MULTIPLIER = 0.50
    _FAST_MODE_MULTIPLIER = 6.00
    _BATCH_CACHE_PROMOTION_THRESHOLD = 2
    _MAX_BATCH_PAYLOAD_BYTES = 9 * 1024 * 1024  # 9 MB — nginx proxy safe limit
    _MAX_BATCH_CHUNK_SIZE = 3                   # requests per sub-batch when over limit
    _BATCH_CREATE_RETRY_ATTEMPTS = 3

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-opus-4-6",
        enable_caching: bool = True,
        fast_mode: bool = False,
        fast_mode_fallback: bool = True,
        use_env_key: bool = False,
        api_key_env: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        try:
            self._anthropic_mod = importlib.import_module("anthropic")
        except ImportError:
            raise ImportError(
                "anthropic package is not installed. Run: pip install anthropic"
            )

        self.model = model
        self.enable_caching = enable_caching
        self.fast_mode = fast_mode
        self.fast_mode_fallback = fast_mode_fallback

        resolved_key = api_key
        resolved_base_url = str(base_url).strip() if isinstance(base_url, str) else None
        key_env_name = str(api_key_env or "ANTHROPIC_API_KEY").strip() or "ANTHROPIC_API_KEY"

        # 1. Try to load from ~/.claude/settings.json
        if (not resolved_key or not resolved_base_url) and not use_env_key:
            try:
                import json
                settings_path = os.path.expanduser("~/.claude/settings.json")
                if os.path.exists(settings_path):
                    with open(settings_path, 'r', encoding='utf-8') as f:
                        settings = json.load(f)
                        env_settings = settings.get("env", {})
                        settings_key = env_settings.get("ANTHROPIC_AUTH_TOKEN")
                        settings_base_url = env_settings.get("ANTHROPIC_BASE_URL")

                        if settings_key and not resolved_key:
                            resolved_key = settings_key
                        if settings_base_url and not resolved_base_url:
                            # The Claude Code CLI settings often contain the full endpoint path.
                            # The Python SDK expects the root base URL.
                            if settings_base_url.endswith("/v1/messages"):
                                settings_base_url = settings_base_url[:-len("/v1/messages")]
                            elif settings_base_url.endswith("/v1/messages/"):
                                settings_base_url = settings_base_url[:-len("/v1/messages/")]
                            resolved_base_url = settings_base_url
            except Exception as e:
                import logging
                logging.getLogger(__name__).debug("Failed to parse ~/.claude/settings.json; ignoring local settings override.")

        # 2. Fallback to env var
        if not resolved_key:
            resolved_key = os.environ.get(key_env_name) or os.environ.get("ANTHROPIC_API_KEY")

        # 2b. Optional base URL fallback from env var
        if not resolved_base_url:
            env_base_url = os.environ.get("ANTHROPIC_BASE_URL")
            if isinstance(env_base_url, str) and env_base_url.strip():
                resolved_base_url = env_base_url.strip()

        # 3. When use_env_key=True, force the real Anthropic API base URL to override
        #    any ANTHROPIC_BASE_URL env var that may point to a proxy (which typically
        #    does not support /v1/messages/batches).
        if use_env_key:
            resolved_base_url = "https://api.anthropic.com"

        resolved_base_url = _normalize_anthropic_base_url(resolved_base_url)

        if not resolved_key:
            raise ValueError(
                "Anthropic API key not found. "
                "Set ANTHROPIC_AUTH_TOKEN in ~/.claude/settings.json, "
                "ANTHROPIC_API_KEY env var, or pass api_key= explicitly."
            )

        # Beta headers: NONE intentionally.
        #
        # context-1m-2025-08-07 (1M context window):
        #   REMOVED — activates a separate "long context" rate limit pool that is
        #   restricted to Tier 4+ accounts only (per Anthropic docs). Any request
        #   exceeding 200K tokens (system+corpus+user) is routed to this pool and
        #   returns 429 "0 input tokens per minute" on Tier 2. Our full-LN cache
        #   payload is ~235K tokens total, which crosses the 200K threshold.
        #   Sonnet 4.6's native context is 200K — sufficient for our use case when
        #   the corpus is structured correctly (system ~100K + user ~7K = 107K,
        #   well within the standard pool limit).
        #
        # output-128k-2025-02-19 (64K output):
        #   REMOVED — routes to a separate inference pool with independent quota,
        #   causing the same "0 input tokens per minute" 429 pattern under load.
        #   Standard Sonnet 4.6 supports 16K output tokens natively; one LN chapter
        #   is ~8-12K words (~10-14K tokens), within the standard limit.
        
        client_kwargs = {
            "api_key": resolved_key,
            "timeout": self._DEFAULT_HTTP_TIMEOUT_SECONDS,
            "max_retries": 0,  # disable SDK built-in retries; @backoff owns all retry logic
        }
        if resolved_base_url:
            client_kwargs["base_url"] = resolved_base_url

        self._client = self._anthropic_mod.Anthropic(**client_kwargs)
        # Maximum output tokens:
        #   Opus 4.6   — 128K natively (no beta header required as of Opus 4.6 release).
        #   Sonnet 4.6 — 64K natively.
        # The model-specific cap is enforced at call time in generate() via is_opus check.
        self._max_output_tokens = 128000 if self._is_opus_46_model(model) else 64000

        # Rate limiting — mirrors GeminiClient.set_rate_limit()
        self._last_request_time: float = 0.0
        self._rate_limit_delay: float = 6.0  # default ~10 req/min

        # Inline cache state
        # When create_cache() or warm_cache() is called, we store the
        # pre-built system array here. generate() injects it when active.
        self._cached_system_blocks: Optional[List[Dict]] = None
        self._cache_ttl: str = "5m"  # "5m" | "1h"
        self._cache_created_at: Optional[float] = None
        self._batch_config = self._load_batch_config()
        self._batch_cache_promote_ttl_1h = bool(
            self._batch_config.get("promote_cache_ttl_1h", True)
        )
        self._batch_cache_shared_brief = bool(
            self._batch_config.get("cache_shared_brief", True)
        )
        self._batch_token_preflight = bool(
            self._batch_config.get("token_preflight", True)
        )
        self._batch_log_payload_preview = bool(
            self._batch_config.get("log_payload_preview", False)
        )
        self._last_batch_audit: Dict[str, Any] = {}

        logger.info(
            f"AnthropicClient initialized "
            f"(model={self.model}, caching={enable_caching}, "
            f"fast_mode={fast_mode}, endpoint={resolved_base_url or 'https://api.anthropic.com'})"
        )

    def _promote_cache_ttl_for_batch(self, request_count: int) -> None:
        """
        Promote 5m cache TTL to 1h for medium/large batch runs.

        Anthropic recommends 1h caching for async batches because processing can
        exceed 5 minutes and cache hit rates drop when the shared prefix expires.
        """
        if (
            not self.enable_caching
            or not self._batch_cache_promote_ttl_1h
            or request_count < self._BATCH_CACHE_PROMOTION_THRESHOLD
            or self._cache_ttl == "1h"
        ):
            return

        self._cache_ttl = "1h"
        if isinstance(self._cached_system_blocks, list):
            for block in self._cached_system_blocks:
                if not isinstance(block, dict):
                    continue
                cache_control = block.get("cache_control")
                if isinstance(cache_control, dict) and cache_control.get("type") == "ephemeral":
                    cache_control["ttl"] = "1h"

        logger.info(
            "[BATCH][CACHE] Promoted prompt cache TTL to 1h for this batch run "
            "(better hit-rate for async processing)."
        )

    def _cache_ttl_log_label(self) -> str:
        """
        Human-readable TTL label for logs.

        If config starts at 5m and batch auto-promotion is enabled, surface that
        up front so pre-warm logs don't look inconsistent with later 1h behavior.
        """
        ttl = str(self._cache_ttl)
        if ttl == "5m" and self._batch_cache_promote_ttl_1h:
            return "5m -> 1h(batch)"
        return ttl

    # ──────────────────────────────────────────────────────
    # Public interface — matches GeminiClient
    # ──────────────────────────────────────────────────────

    def set_rate_limit(self, requests_per_minute: int):
        """Update rate limit delay."""
        if requests_per_minute > 0:
            self._rate_limit_delay = 60.0 / requests_per_minute

    def set_cache_ttl(self, minutes: int):
        """
        Map GeminiClient TTL minutes to Anthropic TTL string.
        ≤5 min → "5m" (default, free refresh)
        >5 min → "1h" (closest Anthropic option, 2x write cost)
        """
        self._cache_ttl = "5m" if minutes <= 5 else "1h"
        logger.debug(f"AnthropicClient cache TTL set to: {self._cache_ttl}")

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
        """
        Mirror of GeminiClient.create_cache().

        Builds and stores the Anthropic system array in memory:
          Block 0: system instruction text (no cache_control — prefix to corpus)
          Block 1: full JP corpus text     (cache_control: ephemeral — breakpoint)

        If no corpus is provided (contents=None), only the system instruction
        is stored as a single cached block (equivalent to warm_cache behaviour).

        Returns _ANTHROPIC_CACHE_SENTINEL on success, None on failure.
        The caller treats any non-None return as "cache is active".
        """
        if not self.enable_caching:
            return None
        if not system_instruction:
            logger.warning("create_cache: no system_instruction provided, skipping")
            return None

        # Resolve TTL from seconds → Anthropic string
        if ttl_seconds is not None:
            self._cache_ttl = "5m" if ttl_seconds <= 300 else "1h"

        blocks: List[Dict] = []

        if contents:
            # Two-block layout: instruction (no breakpoint) + corpus (breakpoint)
            blocks.append({
                "type": "text",
                "text": system_instruction,
            })
            corpus_text = "\n\n".join(contents) if len(contents) > 1 else contents[0]
            blocks.append({
                "type": "text",
                "text": corpus_text,
                "cache_control": {"type": "ephemeral", "ttl": self._cache_ttl},
            })
            logger.info(
                f"[CACHE] Anthropic inline cache built: "
                f"system={len(system_instruction):,}c + "
                f"corpus={len(corpus_text):,}c "
                f"(TTL={self._cache_ttl_log_label()})"
            )
        else:
            # System-instruction-only cache (prewarm fallback)
            blocks.append({
                "type": "text",
                "text": system_instruction,
                "cache_control": {"type": "ephemeral", "ttl": self._cache_ttl},
            })
            logger.info(
                f"[CACHE] Anthropic inline cache built (system only): "
                f"{len(system_instruction):,}c (TTL={self._cache_ttl_log_label()})"
            )

        self._cached_system_blocks = blocks
        self._cache_created_at = time.time()
        return _ANTHROPIC_CACHE_SENTINEL

    def delete_cache(self, cache_name: str) -> bool:
        """
        Mirror of GeminiClient.delete_cache().
        Clears the stored inline cache blocks.
        """
        if cache_name == _ANTHROPIC_CACHE_SENTINEL or cache_name:
            self._cached_system_blocks = None
            self._cache_created_at = None
            logger.info("[CACHE] Anthropic inline cache cleared")
            return True
        return False

    def clear_cache(self):
        """Mirror of GeminiClient.clear_cache()."""
        self._cached_system_blocks = None
        self._cache_created_at = None
        logger.info("[CACHE] Anthropic inline cache cleared")

    def warm_cache(self, system_instruction: str, model: str = None) -> bool: # type: ignore
        """
        Mirror of GeminiClient.warm_cache().

        Stores a system-instruction-only cache block. Used when full volume
        cache creation fails (fallback path in translate_volume).
        """
        if not self.enable_caching:
            logger.debug("warm_cache: caching disabled, skipping")
            return False

        result = self.create_cache(
            system_instruction=system_instruction,
            contents=None,  # system-only; no corpus
        )
        if result:
            logger.info("✓ Anthropic cache pre-warmed (system instruction only)")
            return True
        return False

    def get_token_count(self, text: str) -> int:
        """Estimate token count via Anthropic's count_tokens endpoint."""
        try:
            response = self._client.messages.count_tokens(
                model=self.model,
                messages=[{"role": "user", "content": text}],
            )
            return response.input_tokens
        except Exception as e:
            logger.warning(
                f"AnthropicClient.get_token_count failed: {e}. "
                "Using char/4 estimate."
            )
            return len(text) // 4

    @classmethod
    def _resolve_base_rates_per_mtok(cls, model_name: Optional[str]) -> Tuple[float, float]:
        """Resolve base input/output rates (USD per 1M tokens) for a model name."""
        normalized = (model_name or "").strip().lower()
        if normalized:
            for prefix, rates in cls._MODEL_BASE_RATES_PER_MTOK.items():
                if normalized.startswith(prefix):
                    return rates
        # Default to Sonnet-family rates for unknown IDs to preserve prior behavior.
        logger.warning(
            f"[COST] Unknown Anthropic model '{model_name}'. "
            "Falling back to Sonnet 4.6 rates for estimation."
        )
        return cls._MODEL_BASE_RATES_PER_MTOK["claude-sonnet-4-6"]

    @classmethod
    def estimate_usage_cost_usd(
        cls,
        *,
        model_name: Optional[str],
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
        cache_creation_tokens_5m: int = 0,
        cache_creation_tokens_1h: int = 0,
        cache_ttl: str = "5m",
        batch_mode: bool = False,
        fast_mode: bool = False,
    ) -> Dict[str, float]:
        """
        Estimate Anthropic usage cost from token counters.

        Returns a dict with per-component costs and combined total:
        input, output, cache_read, cache_creation, cache_total, total.
        """
        input_rate, output_rate = cls._resolve_base_rates_per_mtok(model_name)

        normalized_model = cls._normalize_model_name(model_name)
        is_fast = fast_mode and cls._is_opus_46_model(normalized_model)
        if is_fast:
            input_rate *= cls._FAST_MODE_MULTIPLIER
            output_rate *= cls._FAST_MODE_MULTIPLIER

        write_multiplier = (
            cls._PROMPT_CACHE_WRITE_MULTIPLIER_1H
            if str(cache_ttl).lower() == "1h"
            else cls._PROMPT_CACHE_WRITE_MULTIPLIER_5M
        )

        discount_multiplier = cls._BATCH_DISCOUNT_MULTIPLIER if batch_mode else 1.0

        input_cost = (max(0, int(input_tokens)) / 1_000_000.0) * input_rate
        output_cost = (max(0, int(output_tokens)) / 1_000_000.0) * output_rate
        cache_read_cost = (
            (max(0, int(cache_read_tokens)) / 1_000_000.0)
            * input_rate
            * cls._PROMPT_CACHE_READ_MULTIPLIER
        )
        cache_creation_tokens_5m = max(0, int(cache_creation_tokens_5m))
        cache_creation_tokens_1h = max(0, int(cache_creation_tokens_1h))
        explicit_bucket_total = cache_creation_tokens_5m + cache_creation_tokens_1h
        fallback_cache_creation_tokens = (
            max(0, int(cache_creation_tokens)) if explicit_bucket_total == 0 else 0
        )
        cache_creation_cost_5m = (
            (cache_creation_tokens_5m / 1_000_000.0)
            * input_rate
            * cls._PROMPT_CACHE_WRITE_MULTIPLIER_5M
        )
        cache_creation_cost_1h = (
            (cache_creation_tokens_1h / 1_000_000.0)
            * input_rate
            * cls._PROMPT_CACHE_WRITE_MULTIPLIER_1H
        )
        cache_creation_cost_fallback = (
            (fallback_cache_creation_tokens / 1_000_000.0)
            * input_rate
            * write_multiplier
        )
        cache_creation_cost = (
            cache_creation_cost_5m
            + cache_creation_cost_1h
            + cache_creation_cost_fallback
        )

        input_cost *= discount_multiplier
        output_cost *= discount_multiplier
        cache_read_cost *= discount_multiplier
        cache_creation_cost_5m *= discount_multiplier
        cache_creation_cost_1h *= discount_multiplier
        cache_creation_cost_fallback *= discount_multiplier
        cache_creation_cost *= discount_multiplier

        cache_total = cache_read_cost + cache_creation_cost
        total_cost = input_cost + output_cost + cache_total

        return {
            "input_cost_usd": input_cost,
            "output_cost_usd": output_cost,
            "cache_read_cost_usd": cache_read_cost,
            "cache_creation_cost_usd": cache_creation_cost,
            "cache_creation_cost_5m_usd": cache_creation_cost_5m,
            "cache_creation_cost_1h_usd": cache_creation_cost_1h,
            "cache_creation_cost_fallback_usd": cache_creation_cost_fallback,
            "cache_total_cost_usd": cache_total,
            "total_cost_usd": total_cost,
            "input_rate_per_mtok": input_rate,
            "output_rate_per_mtok": output_rate,
            "batch_discount_multiplier": discount_multiplier,
            "fast_mode_multiplier": cls._FAST_MODE_MULTIPLIER if is_fast else 1.0,
            "cache_creation_tokens_5m": cache_creation_tokens_5m,
            "cache_creation_tokens_1h": cache_creation_tokens_1h,
            "cache_creation_tokens_fallback": fallback_cache_creation_tokens,
        }

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            if value is None:
                return 0
            return int(value)
        except Exception:
            return 0

    @staticmethod
    def _normalize_model_name(model_name: Optional[str]) -> str:
        """Normalize model name for robust feature gating."""
        return str(model_name or "").strip().lower()

    @classmethod
    def _is_opus_46_model(cls, model_name: Optional[str]) -> bool:
        """Return True for Opus 4.6 variants (case/whitespace resilient)."""
        return "claude-opus-4-6" in cls._normalize_model_name(model_name)

    def _extract_usage_cache_tokens(
        self,
        usage: Any,
        *,
        cache_ttl_hint: str = "5m",
    ) -> Tuple[int, int, int, int]:
        """
        Extract cache read/write token counters from Anthropic usage payload.

        Supports both aggregate counters and the newer per-TTL cache_creation
        structure (ephemeral_5m_input_tokens / ephemeral_1h_input_tokens).
        """
        cache_read_tokens = self._safe_int(
            getattr(usage, "cache_read_input_tokens", 0)
        )
        cache_creation_total = self._safe_int(
            getattr(usage, "cache_creation_input_tokens", 0)
        )

        cache_creation_5m = 0
        cache_creation_1h = 0
        cache_creation_obj = getattr(usage, "cache_creation", None)
        if cache_creation_obj is not None:
            if isinstance(cache_creation_obj, dict):
                cache_creation_5m = self._safe_int(
                    cache_creation_obj.get("ephemeral_5m_input_tokens", 0)
                )
                cache_creation_1h = self._safe_int(
                    cache_creation_obj.get("ephemeral_1h_input_tokens", 0)
                )
            else:
                cache_creation_5m = self._safe_int(
                    getattr(cache_creation_obj, "ephemeral_5m_input_tokens", 0)
                )
                cache_creation_1h = self._safe_int(
                    getattr(cache_creation_obj, "ephemeral_1h_input_tokens", 0)
                )

        if (cache_creation_5m + cache_creation_1h) == 0 and cache_creation_total > 0:
            # Older usage schema only exposes aggregate cache_creation_input_tokens.
            # Bucket it by request TTL for best-effort cost attribution.
            if str(cache_ttl_hint).lower() == "1h":
                cache_creation_1h = cache_creation_total
            else:
                cache_creation_5m = cache_creation_total

        cache_creation_total = max(
            cache_creation_total,
            cache_creation_5m + cache_creation_1h,
        )

        return (
            cache_read_tokens,
            cache_creation_total,
            cache_creation_5m,
            cache_creation_1h,
        )

    @staticmethod
    def _extract_translation_brief_prefix(prompt: str) -> Tuple[Optional[str], str]:
        """
        Split prompt into:
        1) shared Translator's Guidance brief block (if present at top)
        2) chapter-specific remainder

        This enables a stable cache breakpoint across all chapter requests.
        """
        import re as _re

        if not prompt:
            return None, ""

        pattern = (
            r"\A("
            r"<!-- TRANSLATOR'S GUIDANCE BRIEF \(FULL VOLUME\) -->"
            r"[\s\S]*?"
            r"<!-- END TRANSLATOR'S GUIDANCE BRIEF -->"
            r"(?:\n\n---\n\n)?"
            r")([\s\S]*)\Z"
        )
        match = _re.match(pattern, prompt, flags=_re.DOTALL)
        if not match:
            return None, prompt

        shared_prefix = match.group(1) or ""
        remainder = match.group(2) or ""
        return shared_prefix, remainder

    @staticmethod
    def _backoff_giveup(e: Exception) -> bool:
        """Give up on unrecoverable errors; retry on transient rate limits and overload."""
        msg = str(e)
        # Hard 400 bad-request (malformed payload) — not worth retrying
        if "400" in msg and "overload" not in msg.lower() and "rate" not in msg.lower():
            return True
        # 404 model-not-found — retrying won't help
        if "404" in msg:
            return True
        # SDK streaming requirement violation — structural, retrying won't change it
        if "streaming is required" in msg.lower():
            return True
        return False

    @staticmethod
    def _backoff_on_retry(details: dict) -> None:
        """
        Log the wait duration. If the 429 response carried a Retry-After header,
        override the backoff sleep with that value instead.
        """
        exc = details.get("exception")
        wait = details.get("wait", 0.0)  # seconds computed by backoff.expo

        # Try to read Retry-After from the SDK exception's attached response
        retry_after: Optional[float] = None
        if exc is not None:
            response = getattr(exc, "response", None)
            if response is not None:
                raw = (
                    response.headers.get("retry-after")
                    or response.headers.get("Retry-After")
                )
                if raw:
                    try:
                        retry_after = float(raw)
                    except ValueError:
                        pass

        if retry_after is not None and retry_after > wait:
            logger.warning(
                f"[BACKOFF] Rate-limited — Retry-After header says {retry_after:.1f}s; "
                f"sleeping extra {retry_after - wait:.1f}s on top of backoff "
                f"(attempt {details['tries']})"
            )
            # backoff already sleeps `wait` seconds; we add the remainder
            time.sleep(max(0.0, retry_after - wait))
        else:
            logger.warning(
                f"[BACKOFF] Transient error — backing off {wait:.1f}s "
                f"(attempt {details['tries']}): {exc}"
            )

    @staticmethod
    def _serialize_assistant_content_block(block: Any) -> Optional[Dict[str, Any]]:
        """Convert Anthropic SDK content blocks into request-safe dicts."""
        block_type = getattr(block, "type", None)
        if block_type == "text":
            return {
                "type": "text",
                "text": getattr(block, "text", ""),
            }
        if block_type == "tool_use":
            return {
                "type": "tool_use",
                "id": getattr(block, "id", ""),
                "name": getattr(block, "name", ""),
                "input": getattr(block, "input", {}) or {},
            }
        if isinstance(block, dict):
            if block.get("type") in {"text", "tool_use"}:
                return block
        return None

    def _consume_stream_context(self, stream_ctx: Any) -> Dict[str, Any]:
        """Read one streaming response into text/thinking buffers plus final metadata."""
        text_parts: List[str] = []
        thinking_parts: List[str] = []

        with stream_ctx as stream:
            for event in stream:
                event_type = getattr(event, "type", None)
                if event_type != "content_block_delta":
                    continue
                delta = getattr(event, "delta", None)
                if not delta:
                    continue
                delta_type = getattr(delta, "type", None)
                if delta_type == "text_delta":
                    text_parts.append(getattr(delta, "text", ""))
                elif delta_type == "thinking_delta":
                    thinking_parts.append(getattr(delta, "thinking", ""))
                elif delta_type == "redacted_thinking_delta":
                    thinking_parts.append("\n\n[REDACTED_THINKING_BLOCK_BY_ANTHROPIC]\n\n")

            final = stream.get_final_message()

        usage = final.usage
        (
            cache_read_tokens,
            cache_creation_tokens,
            cache_creation_tokens_5m,
            cache_creation_tokens_1h,
        ) = self._extract_usage_cache_tokens(
            usage,
            cache_ttl_hint=self._cache_ttl,
        )

        return {
            "final": final,
            "text_parts": text_parts,
            "thinking_parts": thinking_parts,
            "finish_reason": final.stop_reason or "end_turn",
            "input_tokens": getattr(usage, "input_tokens", 0),
            "output_tokens": getattr(usage, "output_tokens", 0),
            "cache_read_tokens": cache_read_tokens,
            "cache_creation_tokens": cache_creation_tokens,
            "cache_creation_tokens_5m": cache_creation_tokens_5m,
            "cache_creation_tokens_1h": cache_creation_tokens_1h,
        }

    def _run_stream_turn(
        self,
        *,
        stream_kwargs: Dict[str, Any],
        use_fast_mode: bool,
    ) -> Dict[str, Any]:
        """Execute one Anthropic stream turn with optional fast-mode fallback."""
        effective_fast_mode = use_fast_mode
        prepared_kwargs = dict(stream_kwargs)
        if use_fast_mode:
            prepared_kwargs["speed"] = "fast"
            prepared_kwargs["betas"] = [self._FAST_MODE_BETA]

        try:
            stream_ctx = (
                self._client.beta.messages.stream(**prepared_kwargs)
                if use_fast_mode
                else self._client.messages.stream(**prepared_kwargs)
            )
            result = self._consume_stream_context(stream_ctx)
            result["effective_fast_mode"] = effective_fast_mode
            return result
        except self._anthropic_mod.RateLimitError as rl_err:
            if not (use_fast_mode and self.fast_mode_fallback):
                raise rl_err

            logger.warning(
                "[FAST-MODE] Rate limit on fast mode — falling back to standard speed. "
                "Note: prompt cache miss (fast/standard prefixes are separate)."
            )
            standard_kwargs = {
                key: value
                for key, value in prepared_kwargs.items()
                if key not in ("speed", "betas")
            }
            result = self._consume_stream_context(
                self._client.messages.stream(**standard_kwargs)
            )
            result["effective_fast_mode"] = False
            return result

    @backoff.on_exception(
        backoff.expo,           # standard exponential backoff: 1s, 2s, 4s, 8s …
        Exception,
        max_tries=8,
        factor=2,
        base=2,
        max_value=60,           # cap at 60s per wait
        giveup=_backoff_giveup.__func__,    # type: ignore[attr-defined]
        on_backoff=_backoff_on_retry.__func__,  # type: ignore[attr-defined]
        raise_on_giveup=True,
    )
    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_output_tokens: int = 16000,
        safety_settings: Optional[Dict[str, str]] = None,    # ignored — no Anthropic equivalent
        model: Optional[str] = None,
        cached_content: Optional[str] = None,                # non-empty → use stored cache blocks
        force_new_session: bool = False,            # True → Amnesia Protocol, bypass cache
        generation_config: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Any]] = None,
        use_tool_mode: bool = False,
        tool_handlers: Optional[Dict[str, Any]] = None,
        retrospective_anchor: Optional[str] = None,          # Arc-closing prose anchor (Phase B)
    ) -> GeminiResponse:
        """
        Generate content via Anthropic Messages API.

        Returns GeminiResponse so every ChapterProcessor call site works
        without modification.

        Caching decision:
          - cached_content is non-empty AND self._cached_system_blocks is set
            AND force_new_session is False
            → inject self._cached_system_blocks as system= (cache hit on 2nd+ call)
          - Otherwise → send system_instruction as plain string

        retrospective_anchor:
          When provided, appended as an additional system block with cache_control:
          ephemeral so it is processed before the user prompt (higher influence on
          generation) and is eligible for 1-hour TTL cache reuse.

        use_tool_mode:
          Translator-only Anthropic tool-use path. When True and the declare tool is
          supplied, the first turn is forced into a pre-commit tool call before the
          actual translation turn.

        tool_handlers:
          Optional tool callback map used by the second-pass loop. Keys are tool
          names; values are callables that accept tool_input and return either a
          tool_result string or a (tool_result, artifact) tuple.
        """
        target_model = model or self.model
        thinking_cfg = self._load_thinking_config()

        # Apply generation_config overrides (same keys as Gemini path)
        if generation_config:
            temperature = generation_config.get("temperature", temperature)
            max_output_tokens = generation_config.get("max_output_tokens", max_output_tokens)

        # Hard cap: respect per-model token limits (Opus=128K, Sonnet=64K)
        # This allows multi-turn streaming to use full output capacity without
        # being artificially capped.
        model_output_cap = 128_000 if self._is_opus_46_model(target_model) else 64_000
        max_output_tokens = min(max_output_tokens, model_output_cap)

        # Rate limit
        elapsed = time.time() - self._last_request_time
        if elapsed < self._rate_limit_delay:
            time.sleep(self._rate_limit_delay - elapsed)

        # Decide whether to inject stored cache blocks
        use_cached_blocks = (
            self.enable_caching
            and not force_new_session
            and bool(cached_content)           # caller signals cache is active
            and self._cached_system_blocks is not None
        )

        # Build system value
        if use_cached_blocks:
            system_value = self._cached_system_blocks
            logger.debug(
                f"[CACHE] Injecting {len(self._cached_system_blocks)}-block " # type: ignore
                f"cached system array (TTL={self._cache_ttl_log_label()})"
            )
        elif system_instruction:
            system_value = system_instruction   # plain string — Anthropic accepts both
        else:
            system_value = None

        # Phase B: Append retrospective anchor as a separately-cached system block.
        # Placed after the main system instruction so it is processed last in the
        # system turn — immediately before the user prompt — giving it maximum
        # influence on generation. The ephemeral cache_control makes it eligible
        # for 1-hour TTL reuse within a volume translation session.
        if retrospective_anchor and retrospective_anchor.strip():
            anchor_block = {
                "type": "text",
                "text": retrospective_anchor.strip(),
                "cache_control": {"type": "ephemeral", "ttl": self._cache_ttl},
            }
            if isinstance(system_value, list):
                system_value = list(system_value) + [anchor_block]
            elif isinstance(system_value, str):
                # Convert plain string to block list, then append anchor
                system_value = [
                    {"type": "text", "text": system_value},
                    anchor_block,
                ]
            else:
                # No existing system — anchor becomes the sole system block
                system_value = [anchor_block]
            logger.debug(
                f"[RETRO-ANCHOR] Appended retrospective anchor as system block "
                f"({len(retrospective_anchor)} chars, TTL={self._cache_ttl_log_label()})"
            )

        messages = [{"role": "user", "content": prompt}]

        # Build API kwargs
        kwargs: Dict[str, Any] = dict(
            model=target_model,
            max_tokens=max_output_tokens,
            temperature=temperature,
            messages=messages,
        )
        if system_value is not None:
            kwargs["system"] = system_value

        # Extended thinking (opt-in via config)
        #
        # Opus 4.6 API (current):
        #   - thinking: {type: "adaptive"} OR {type: "enabled", budget_tokens: N}
        #   - effort controlled via output_config: {effort: "max"} (Opus-only)
        #   - 128K output tokens native (no beta header needed)
        #
        # Sonnet 4.6 API (current):
        #   - thinking: {type: "adaptive"} OR {type: "enabled", budget_tokens: N}
        #   - effort: "max" NOT supported (returns 400); defaults to "high"
        #   - 64K output tokens native
        #
        is_opus = self._is_opus_46_model(target_model)

        # Raise the per-call output cap to 128K for Opus (native, no beta header).
        if is_opus:
            kwargs["max_tokens"] = min(max_output_tokens, 128_000)

        thinking_type = thinking_cfg.get("thinking_type", "adaptive")
        thinking_allowed = is_opus or thinking_type == "enabled"
        if thinking_allowed and thinking_cfg.get("enabled", False) and not force_new_session:
            budget = self._resolve_thinking_budget(thinking_cfg, is_opus=is_opus)
            if is_opus:
                if thinking_type != "adaptive":
                    logger.info(
                        "[THINKING] Opus 4.6 override: forcing thinking.type=adaptive "
                        "(ignoring deprecated thinking.type=enabled)."
                    )
                # Opus 4.6: adaptive thinking + effort=max.
                # thinking.type="enabled" is deprecated for claude-opus-4-6;
                # "adaptive" with effort=max lets the model allocate its own budget
                # up to the effort ceiling — better performance per Anthropic testing.
                kwargs["thinking"] = {"type": "adaptive"}
                kwargs["output_config"] = {"effort": "max"}
                logger.info(
                    "[THINKING] Opus 4.6: adaptive thinking + effort=max (128K output)"
                )
            else:
                # Sonnet 4.6: adaptive or enabled (budget_tokens), effort stays at default "high".
                if thinking_type == "adaptive":
                    kwargs["thinking"] = {"type": "adaptive"}
                    logger.info("[THINKING] Sonnet 4.6: adaptive thinking enabled")
                else:
                    # "enabled" with explicit budget cap — for Sonnet interleaved mode.
                    kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
                    logger.info(f"[THINKING] Sonnet 4.6: hard budget cap {budget} tokens")
            kwargs["temperature"] = 1.0   # required when thinking is active (any model)

        # Fast mode: use beta endpoint + speed="fast" for up to 2.5x OTPS on Opus 4.6.
        # Note: fast and standard speed do NOT share prompt cache prefixes — falling back
        # from fast to standard invalidates the cache for that request.
        use_fast_mode = self.fast_mode and self._is_opus_46_model(target_model)
        enabled_tools = [
            tool
            for tool in (tools or [])
            if isinstance(tool, dict) and str(tool.get("name", "")).strip()
        ]
        post_turn_tools = [
            tool
            for tool in enabled_tools
            if tool.get("name") != TOOL_NAME_DECLARE_TRANSLATION_PARAMETERS
        ]
        declare_tool = next(
            (
                tool
                for tool in enabled_tools
                if tool.get("name") == TOOL_NAME_DECLARE_TRANSLATION_PARAMETERS
            ),
            None,
        )
        tool_mode_active = bool(use_tool_mode and declare_tool)
        if use_tool_mode and not tool_mode_active:
            logger.warning(
                "[TOOL-MODE] Requested but declare_translation_parameters tool is unavailable. "
                "Continuing with standard single-turn generation."
            )
        if enabled_tools:
            logger.info(
                "[TOOL-MODE] Enabled tools for this request: %s",
                ", ".join(str(tool.get("name")) for tool in enabled_tools),
            )

        logger.info(
            f"Calling Anthropic API "
            f"(model={target_model}, cached_blocks={use_cached_blocks}, "
            f"fast_mode={use_fast_mode}, tool_mode={tool_mode_active})..."
        )
        start_time = time.time()

        # Use streaming to avoid the SDK's 10-minute non-streaming timeout guard.
        # The stream context manager collects the full response before returning.
        try:
            text_parts: List[str] = []
            thinking_parts: List[str] = []
            finish_reason = "end_turn"
            turn_records: List[Dict[str, Any]] = []
            tool_calls_made: List[str] = []
            declared_params = None
            qc_self_report = None
            structural_constraints: List[Any] = []
            current_messages: List[Dict[str, Any]] = list(messages)

            def _record_turn(turn_result: Dict[str, Any]) -> None:
                cost = self.estimate_usage_cost_usd(
                    model_name=target_model,
                    input_tokens=turn_result["input_tokens"],
                    output_tokens=turn_result["output_tokens"],
                    cache_read_tokens=turn_result["cache_read_tokens"],
                    cache_creation_tokens=turn_result["cache_creation_tokens"],
                    cache_creation_tokens_5m=turn_result["cache_creation_tokens_5m"],
                    cache_creation_tokens_1h=turn_result["cache_creation_tokens_1h"],
                    cache_ttl=self._cache_ttl,
                    batch_mode=False,
                    fast_mode=bool(turn_result.get("effective_fast_mode", False)),
                )
                turn_result["cost_breakdown"] = cost
                turn_records.append(turn_result)

            runtime_handlers = tool_handlers if isinstance(tool_handlers, dict) else {}

            def _resolve_tool_handler_result(tool_name: str, tool_input: Dict[str, Any]) -> Tuple[str, Any]:
                handler = runtime_handlers.get(tool_name)
                if not callable(handler):
                    return (
                        f"Tool '{tool_name}' is unavailable in this runtime. Continue without it using your best judgment.",
                        None,
                    )
                result = handler(tool_input)
                if isinstance(result, tuple) and len(result) == 2:
                    return str(result[0]), result[1]
                return str(result), None

            continue_after_precommit = False

            if tool_mode_active:
                first_kwargs = dict(kwargs)
                first_kwargs["tools"] = [declare_tool]
                first_kwargs["tool_choice"] = {
                    "type": "tool",
                    "name": TOOL_NAME_DECLARE_TRANSLATION_PARAMETERS,
                }
                if "thinking" in first_kwargs or "output_config" in first_kwargs:
                    # Anthropic rejects forced tool_choice when thinking is enabled.
                    first_kwargs.pop("thinking", None)
                    first_kwargs.pop("output_config", None)
                    first_kwargs["temperature"] = temperature
                    logger.info(
                        "[TOOL-MODE] Disabling thinking for forced declare_translation_parameters turn."
                    )

                first_turn = self._run_stream_turn(
                    stream_kwargs=first_kwargs,
                    use_fast_mode=use_fast_mode,
                )
                first_turn["audit_phase"] = "declare_translation_parameters"
                _record_turn(first_turn)
                thinking_parts.extend(first_turn["thinking_parts"])

                if first_turn["finish_reason"] == "tool_use":
                    final = first_turn["final"]
                    declare_block = next(
                        (
                            block
                            for block in getattr(final, "content", [])
                            if getattr(block, "type", None) == "tool_use"
                            and getattr(block, "name", None)
                            == TOOL_NAME_DECLARE_TRANSLATION_PARAMETERS
                        ),
                        None,
                    )
                    if declare_block is not None:
                        tool_calls_made.append(TOOL_NAME_DECLARE_TRANSLATION_PARAMETERS)
                        try:
                            tool_result, declared_params = handle_declare_translation_parameters(
                                getattr(declare_block, "input", {}) or {}
                            )
                        except Exception as tool_exc:
                            logger.warning(
                                "[TOOL-MODE] Invalid declare_translation_parameters payload: %s",
                                tool_exc,
                            )
                            tool_result = (
                                "Your declare_translation_parameters payload was invalid. "
                                f"Validation error: {tool_exc}. Proceed with translation using "
                                "the corrected chapter-level parameters you intended."
                            )

                        assistant_content = [
                            serialized
                            for serialized in (
                                self._serialize_assistant_content_block(block)
                                for block in getattr(final, "content", [])
                            )
                            if serialized is not None
                        ]
                        if assistant_content:
                            current_messages.append(
                                {"role": "assistant", "content": assistant_content}
                            )
                        current_messages.append(
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "tool_result",
                                        "tool_use_id": getattr(declare_block, "id", ""),
                                        "content": tool_result,
                                    }
                                ],
                            }
                        )
                        continue_after_precommit = True
                    else:
                        logger.warning(
                            "[TOOL-MODE] First turn ended with tool_use but no "
                            "declare_translation_parameters block was found."
                        )
                        text_parts.extend(first_turn["text_parts"])
                        finish_reason = first_turn["finish_reason"]
                else:
                    text_parts.extend(first_turn["text_parts"])
                    finish_reason = first_turn["finish_reason"]
            else:
                continue_after_precommit = True

            if continue_after_precommit:
                max_tool_turns = 12
                turn_index = 0
                current_turn_tools = post_turn_tools if tool_mode_active else enabled_tools

                while turn_index < max_tool_turns:
                    turn_index += 1
                    turn_kwargs = dict(kwargs)
                    turn_kwargs["messages"] = current_messages
                    if current_turn_tools:
                        turn_kwargs["tools"] = current_turn_tools
                        turn_kwargs["tool_choice"] = {"type": "auto"}

                    turn_result = self._run_stream_turn(
                        stream_kwargs=turn_kwargs,
                        use_fast_mode=use_fast_mode,
                    )
                    turn_result["audit_phase"] = (
                        "tool_round" if turn_result["finish_reason"] == "tool_use" else "translation_turn"
                    )
                    _record_turn(turn_result)
                    text_parts.extend(turn_result["text_parts"])
                    thinking_parts.extend(turn_result["thinking_parts"])
                    finish_reason = turn_result["finish_reason"]

                    if turn_result["finish_reason"] != "tool_use":
                        break

                    final = turn_result["final"]
                    assistant_content = [
                        serialized
                        for serialized in (
                            self._serialize_assistant_content_block(block)
                            for block in getattr(final, "content", [])
                        )
                        if serialized is not None
                    ]
                    tool_result_blocks = []
                    for block in getattr(final, "content", []):
                        if getattr(block, "type", None) != "tool_use":
                            continue
                        tool_name = str(getattr(block, "name", "") or "").strip()
                        tool_calls_made.append(tool_name)
                        tool_result, artifact = _resolve_tool_handler_result(
                            tool_name,
                            getattr(block, "input", {}) or {},
                        )
                        if artifact is not None:
                            if tool_name == TOOL_NAME_REPORT_TRANSLATION_QC:
                                qc_self_report = artifact
                            elif tool_name == TOOL_NAME_FLAG_STRUCTURAL_CONSTRAINT:
                                structural_constraints.append(artifact)
                        tool_result_blocks.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": getattr(block, "id", ""),
                                "content": tool_result,
                            }
                        )

                    if not tool_result_blocks:
                        logger.warning(
                            "[TOOL-MODE] Response requested tool use but contained no tool_result-capable blocks."
                        )
                        break

                    if assistant_content:
                        current_messages.append(
                            {"role": "assistant", "content": assistant_content}
                        )
                    current_messages.append(
                        {"role": "user", "content": tool_result_blocks}
                    )

                if turn_index >= max_tool_turns and finish_reason == "tool_use":
                    logger.warning(
                        "[TOOL-MODE] Max tool-use turns reached (%d). Returning partial response.",
                        max_tool_turns,
                    )

        except Exception as e:
            logger.error(
                "Anthropic API error (%s): %s",
                e.__class__.__name__,
                _summarize_api_exception(e),
            )
            raise

        input_tokens = sum(int(turn.get("input_tokens", 0) or 0) for turn in turn_records)
        output_tokens = sum(int(turn.get("output_tokens", 0) or 0) for turn in turn_records)
        cache_read_tokens = sum(
            int(turn.get("cache_read_tokens", 0) or 0) for turn in turn_records
        )
        cache_creation_tokens = sum(
            int(turn.get("cache_creation_tokens", 0) or 0) for turn in turn_records
        )
        cache_creation_tokens_5m = sum(
            int(turn.get("cache_creation_tokens_5m", 0) or 0) for turn in turn_records
        )
        cache_creation_tokens_1h = sum(
            int(turn.get("cache_creation_tokens_1h", 0) or 0) for turn in turn_records
        )
        cost_breakdown = {
            "input_cost_usd": sum(
                float(turn["cost_breakdown"]["input_cost_usd"]) for turn in turn_records
            ),
            "output_cost_usd": sum(
                float(turn["cost_breakdown"]["output_cost_usd"]) for turn in turn_records
            ),
            "cache_read_cost_usd": sum(
                float(turn["cost_breakdown"]["cache_read_cost_usd"]) for turn in turn_records
            ),
            "cache_creation_cost_usd": sum(
                float(turn["cost_breakdown"]["cache_creation_cost_usd"]) for turn in turn_records
            ),
            "total_cost_usd": sum(
                float(turn["cost_breakdown"]["total_cost_usd"]) for turn in turn_records
            ),
        }
        effective_fast_mode = any(
            bool(turn.get("effective_fast_mode", False)) for turn in turn_records
        )
        turn_audit_records = [
            {
                "index": idx + 1,
                "phase": str(turn.get("audit_phase", "translation_turn") or "translation_turn"),
                "finish_reason": str(turn.get("finish_reason", "") or ""),
                "input_tokens": int(turn.get("input_tokens", 0) or 0),
                "output_tokens": int(turn.get("output_tokens", 0) or 0),
                "cache_read_tokens": int(turn.get("cache_read_tokens", 0) or 0),
                "cache_creation_tokens": int(turn.get("cache_creation_tokens", 0) or 0),
                "effective_fast_mode": bool(turn.get("effective_fast_mode", False)),
                "cost_breakdown": dict(turn.get("cost_breakdown", {}) or {}),
            }
            for idx, turn in enumerate(turn_records)
        ]
        response_cost_audit = {
            "schema_version": "1.0",
            "provider": "anthropic",
            "request_type": "stream",
            "turn_count": len(turn_audit_records),
            "turns": turn_audit_records,
            "tool_calls_made": list(tool_calls_made),
            "tool_call_count": len(tool_calls_made),
            "totals": {
                "input_tokens": int(input_tokens or 0),
                "output_tokens": int(output_tokens or 0),
                "cached_tokens": int(cache_read_tokens or 0),
                "cache_creation_tokens": int(cache_creation_tokens or 0),
                "input_cost_usd": float(cost_breakdown["input_cost_usd"]),
                "output_cost_usd": float(cost_breakdown["output_cost_usd"]),
                "cache_read_cost_usd": float(cost_breakdown["cache_read_cost_usd"]),
                "cache_creation_cost_usd": float(cost_breakdown["cache_creation_cost_usd"]),
                "total_cost_usd": float(cost_breakdown["total_cost_usd"]),
            },
            "fast_mode_pricing": bool(effective_fast_mode),
        }

        duration = time.time() - start_time
        logger.info(
            f"Anthropic response received in {duration:.2f}s "
            f"(stop_reason={finish_reason}, turns={len(turn_records)})"
        )
        self._last_request_time = time.time()
        logger.info(
            "[COST] LLM request usage: "
            f"in={input_tokens:,} (${cost_breakdown['input_cost_usd']:.6f}) | "
            f"out={output_tokens:,} (${cost_breakdown['output_cost_usd']:.6f}) | "
            f"cache_read={cache_read_tokens:,} (${cost_breakdown['cache_read_cost_usd']:.6f}) | "
            f"cache_write={cache_creation_tokens:,} "
            f"(5m={cache_creation_tokens_5m:,}, 1h={cache_creation_tokens_1h:,}) "
            f"(${cost_breakdown['cache_creation_cost_usd']:.6f}) | "
            f"total=${cost_breakdown['total_cost_usd']:.6f}"
        )
        if cache_read_tokens > 0:
            logger.info(
                f"✓ Anthropic cache hit: {cache_read_tokens:,} tokens "
                f"(${cost_breakdown['cache_read_cost_usd']:.6f})"
            )
        if cache_creation_tokens > 0:
            logger.info(
                f"[CACHE] Cache write: {cache_creation_tokens:,} tokens "
                f"(${cost_breakdown['cache_creation_cost_usd']:.6f})"
            )
        # Log thinking vs translation token split when thinking is active
        if thinking_cfg.get("enabled", False) and thinking_parts:
            thinking_tok_estimate = sum(len(p.split()) * 4 // 3 for p in thinking_parts)
            translation_tok_estimate = max(0, output_tokens - thinking_tok_estimate)
            logger.info(
                f"[THINKING] Token split: ~{thinking_tok_estimate:,} thinking + "
                f"~{translation_tok_estimate:,} translation = {output_tokens:,} total output "
                f"(budget cap: {self._resolve_thinking_budget(thinking_cfg, is_opus=self._is_opus_46_model(target_model))})"
            )

        # GeminiResponse.cached_tokens ← Anthropic cache_read_input_tokens
        cached_tokens = cache_read_tokens

        # ── Content assembly ─────────────────────────────────────────
        raw_content = "".join(text_parts).strip()

        # Strip any <thinking>...</thinking> blocks that Claude may emit inline
        # in the text stream when extended thinking is OFF. Extract them into
        # thinking_content so the caller can save them to a THINKING file
        # (mirroring how Gemini's native thinking stream is handled).
        import re as _re
        inline_thinking_blocks = _re.findall(
            r"<thinking>(.*?)</thinking>", raw_content, flags=_re.DOTALL
        )
        if inline_thinking_blocks:
            logger.info(
                f"[THINKING] Extracted {len(inline_thinking_blocks)} inline <thinking> "
                f"block(s) from Anthropic text response — saving to THINKING file."
            )
            # Remove the <thinking> blocks from the translation output
            content = _re.sub(
                r"\s*<thinking>.*?</thinking>\s*", "\n", raw_content, flags=_re.DOTALL
            ).strip()
        else:
            content = raw_content

        # NOTE:
        # Anthropic streaming emits many fine-grained thinking_delta chunks.
        # Joining with "\n\n" turns one sentence into one-token-per-line output.
        # We must stitch deltas contiguously.
        stream_thinking = "".join(thinking_parts).strip() if thinking_parts else ""
        thinking_sections: List[str] = []
        if stream_thinking:
            thinking_sections.append(stream_thinking)
        if inline_thinking_blocks:
            extracted_thinking = "\n\n---\n\n".join(
                block.strip() for block in inline_thinking_blocks if block.strip()
            )
            if extracted_thinking:
                thinking_sections.append(extracted_thinking)
        raw_thinking = "\n\n---\n\n".join(thinking_sections) if thinking_sections else None

        # ── Strip line-by-line translation scratchpad from thinking log ──────
        # Even with the prompt discipline, Claude may still emit translation lines
        # in the pattern  「Japanese source」= "English translation"  or sequential
        # paragraph translations inside <thinking>. These are token waste and make
        # the thinking log unreadable. Strip them while keeping genuine reasoning.
        if raw_thinking:
            lines = raw_thinking.splitlines()
            filtered = []
            for line in lines:
                stripped = line.strip()
                # Drop lines that are pure source→translation pairs
                # Pattern: starts with 「...」 or = "..." or = '...'
                if _re.match(r'^「.*」\s*$', stripped):
                    continue
                if _re.match(r'^= ["\']', stripped):
                    continue
                # Drop lines that look like sequential translated output
                # (lines starting with open-quote immediately after a JP line)
                # Keep everything else — analysis, decisions, cultural notes
                filtered.append(line)
            thinking_content = "\n".join(filtered).strip() or None
            if raw_thinking and thinking_content != raw_thinking:
                original_words = len(raw_thinking.split())
                filtered_words = len(thinking_content.split()) if thinking_content else 0
                logger.info(
                    f"[THINKING] Stripped line-by-line translation from thinking log: "
                    f"{original_words}w → {filtered_words}w"
                )
        else:
            thinking_content = None

        if not content:
            logger.warning(
                f"Empty Anthropic response. stop_reason={finish_reason}"
            )
            return GeminiResponse(
                content="",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=finish_reason,
                model=target_model,
                cached_tokens=cached_tokens,
                thinking_content=None,
                cache_creation_tokens=cache_creation_tokens,
                input_cost_usd=cost_breakdown["input_cost_usd"],
                output_cost_usd=cost_breakdown["output_cost_usd"],
                cache_read_cost_usd=cost_breakdown["cache_read_cost_usd"],
                cache_creation_cost_usd=cost_breakdown["cache_creation_cost_usd"],
                total_cost_usd=cost_breakdown["total_cost_usd"],
                batch_pricing=False,
                fast_mode_pricing=bool(effective_fast_mode),
                declared_params=declared_params,
                tool_calls_made=tool_calls_made,
                tool_call_count=len(tool_calls_made),
                qc_self_report=qc_self_report,
                structural_constraints=structural_constraints,
                cost_audit=response_cost_audit,
            )

        return GeminiResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason=finish_reason,
            model=target_model,
            cached_tokens=cached_tokens,
            thinking_content=thinking_content,
            cache_creation_tokens=cache_creation_tokens,
            input_cost_usd=cost_breakdown["input_cost_usd"],
            output_cost_usd=cost_breakdown["output_cost_usd"],
            cache_read_cost_usd=cost_breakdown["cache_read_cost_usd"],
            cache_creation_cost_usd=cost_breakdown["cache_creation_cost_usd"],
            total_cost_usd=cost_breakdown["total_cost_usd"],
            batch_pricing=False,
            fast_mode_pricing=bool(effective_fast_mode),
            declared_params=declared_params,
            tool_calls_made=tool_calls_made,
            tool_call_count=len(tool_calls_made),
            qc_self_report=qc_self_report,
            structural_constraints=structural_constraints,
            cost_audit=response_cost_audit,
        )

    # ──────────────────────────────────────────────────────
    # Batch API — 50% cost reduction for non-realtime runs
    # ──────────────────────────────────────────────────────

    def get_batch_status_snapshot(self, batch_ids: List[str]) -> Dict[str, Any]:
        """
        Fetch a compact status snapshot for one or more Anthropic batch IDs.

        Args:
            batch_ids: List of Anthropic batch IDs (e.g., msgbatch_...).

        Returns:
            Dict with:
              - status: "in_progress" | "ended" | "unknown"
              - totals: succeeded/errored/expired/processing/total
              - batches: per-batch status rows
              - errors: retrieval failures
        """
        cleaned_ids = [str(v).strip() for v in (batch_ids or []) if str(v).strip()]
        if not cleaned_ids:
            return {
                "status": "unknown",
                "totals": {
                    "succeeded": 0,
                    "errored": 0,
                    "expired": 0,
                    "processing": 0,
                    "total": 0,
                },
                "batches": [],
                "errors": ["no_batch_ids"],
            }

        totals = {
            "succeeded": 0,
            "errored": 0,
            "expired": 0,
            "processing": 0,
            "total": 0,
        }
        rows: List[Dict[str, Any]] = []
        errors: List[str] = []
        all_ended = True

        for b_id in cleaned_ids:
            try:
                status_obj = self._client.messages.batches.retrieve(b_id)
                processing_status = str(getattr(status_obj, "processing_status", "unknown"))
                counts = getattr(status_obj, "request_counts", None)
                succeeded = int(getattr(counts, "succeeded", 0) or 0)
                errored = int(getattr(counts, "errored", 0) or 0)
                expired = int(getattr(counts, "expired", 0) or 0)
                processing = int(getattr(counts, "processing", 0) or 0)
                total = int(getattr(counts, "total", 0) or 0)

                if processing_status != "ended":
                    all_ended = False

                totals["succeeded"] += succeeded
                totals["errored"] += errored
                totals["expired"] += expired
                totals["processing"] += processing
                totals["total"] += total

                rows.append({
                    "batch_id": b_id,
                    "processing_status": processing_status,
                    "succeeded": succeeded,
                    "errored": errored,
                    "expired": expired,
                    "processing": processing,
                    "total": total,
                })
            except Exception as e:
                all_ended = False
                err_text = f"{b_id}: {e}"
                errors.append(err_text)
                rows.append({
                    "batch_id": b_id,
                    "processing_status": "error",
                    "succeeded": 0,
                    "errored": 0,
                    "expired": 0,
                    "processing": 0,
                    "total": 0,
                    "error": str(e),
                })

        overall_status = "ended" if rows and all_ended else "in_progress"
        if not rows:
            overall_status = "unknown"

        return {
            "status": overall_status,
            "totals": totals,
            "batches": rows,
            "errors": errors,
        }

    def batch_generate(
        self,
        requests: List[Dict[str, Any]],
        poll_interval_seconds: int = 60,
        batch_state_path: Optional[Path] = None,
    ) -> Dict[str, "GeminiResponse"]:
        """
        Submit a list of chapter translation requests as one Anthropic Message Batch.

        Offers 50% cost reduction vs streaming at the cost of ~1-hour latency.
        Only valid for the Anthropic provider; Gemini has no equivalent batch API.

        Args:
            requests: List of dicts, each with keys:
                - custom_id (str)          — unique chapter identifier
                - prompt    (str)          — fully-built user prompt
                - system_instruction (str|None) — None when cached system is active
                - model_name (str|None)    — model override
                - max_output_tokens (int)  — defaults to self._max_output_tokens
                - temperature (float)      — defaults to 0.7 (overridden to 1.0 by thinking)
                - cached_content (str|None) — truthy: use cached system blocks
            poll_interval_seconds: How often to poll for batch completion (default 60s).
            batch_state_path: Optional Path to a .json file for storing the batch ID
                              so a crashed run can be resumed on restart.

        Returns:
            Dict mapping custom_id → GeminiResponse. Errored/expired requests
            return GeminiResponse(content="", finish_reason="batch_error").
        """
        import json as _json
        import time as _time
        import re as _re
        self._last_batch_audit = {}

        if not requests:
            logger.warning("[BATCH] batch_generate() called with empty request list")
            return {}

        thinking_cfg = self._load_thinking_config()
        expected_custom_ids = [
            str(req.get("custom_id", "")).strip()
            for req in requests
            if str(req.get("custom_id", "")).strip()
        ]
        expected_custom_id_set = set(expected_custom_ids)
        request_by_custom_id: Dict[str, Dict[str, Any]] = {
            str(req.get("custom_id", "")).strip(): req
            for req in requests
            if str(req.get("custom_id", "")).strip()
        }
        serial_fallback_requests: List[Dict[str, Any]] = []
        chunk_retry_counts: Dict[Tuple[str, ...], int] = {}
        retrieve_retry_count = 0

        # ── Check for a resumable batch ID ─────────────────────────────
        batch_ids: List[str] = []
        resumed_from_state = False
        if batch_state_path and batch_state_path.exists():
            try:
                state = _json.loads(batch_state_path.read_text())
                state_request_ids = state.get("request_custom_ids")
                if isinstance(state_request_ids, list):
                    state_request_ids = [str(v).strip() for v in state_request_ids if str(v).strip()]
                    if set(state_request_ids) != expected_custom_id_set:
                        logger.warning(
                            "[BATCH] Ignoring stale batch state file: request ID set mismatch "
                            f"(state={len(state_request_ids)} ids, current={len(expected_custom_id_set)} ids)."
                        )
                        batch_ids = []
                    else:
                        if "batch_ids" in state:
                            batch_ids = state["batch_ids"]
                        elif "batch_id" in state:
                            batch_ids = [state["batch_id"]]
                else:
                    # Legacy state format (no request IDs) is unsafe to auto-resume:
                    # it can bind the current run to an unrelated historical batch.
                    logger.warning(
                        "[BATCH] Ignoring legacy batch state file without request_custom_ids "
                        "to prevent cross-run result mismatches."
                    )
                    batch_ids = []

                if isinstance(batch_ids, str):
                    batch_ids = [batch_ids]
                if isinstance(batch_ids, list):
                    batch_ids = [str(v).strip() for v in batch_ids if str(v).strip()]
                else:
                    batch_ids = []

                if batch_ids:
                    logger.info(f"[BATCH] Resuming existing batches: {batch_ids}")
                    resumed_from_state = True
            except Exception as _e:
                logger.warning(f"[BATCH] Could not read batch state file: {_e}")

        # ── Build request objects ───────────────────────────────────────
        if not batch_ids:
            self._promote_cache_ttl_for_batch(len(requests))
            anthropic_requests = []
            # Anthropic SDK request type changed across versions.
            # Newer SDKs use `types.messages.batch_create_params.Request`.
            req_ctor = None
            try:
                req_ctor = self._anthropic_mod.types.messages.batch_create_params.Request
            except Exception:
                try:
                    # Backward-compat path for older installs.
                    req_ctor = self._anthropic_mod.types.message_create_params.Request
                except Exception:
                    req_ctor = None

            # Optional shared-brief cache breakpoint: extract an identical
            # Translator's Guidance block from every chapter prompt and mark it
            # cacheable once per request. This keeps chapter source text dynamic
            # while caching the shared volume guidance.
            shared_brief_prefix: Optional[str] = None
            prompt_remainders: Dict[str, str] = {}
            if self.enable_caching and self._batch_cache_shared_brief:
                mismatch_detected = False
                for req in requests:
                    cid = str(req.get("custom_id", "")).strip()
                    prompt_value = str(req.get("prompt", "") or "")
                    brief_prefix, remainder = self._extract_translation_brief_prefix(prompt_value)
                    if not cid:
                        continue
                    prompt_remainders[cid] = remainder
                    if not brief_prefix:
                        mismatch_detected = True
                        break
                    if shared_brief_prefix is None:
                        shared_brief_prefix = brief_prefix
                    elif brief_prefix != shared_brief_prefix:
                        mismatch_detected = True
                        break
                if mismatch_detected:
                    shared_brief_prefix = None
                    prompt_remainders = {}
                elif shared_brief_prefix:
                    logger.info(
                        "[BATCH][CACHE] Shared Translator's Guidance prefix detected "
                        f"({len(shared_brief_prefix):,} chars) — enabling user-level cache breakpoint."
                    )

            preflight_warnings = 0
            preflight_max_tokens = 0
            for req in requests:
                custom_id    = req["custom_id"]
                prompt       = req["prompt"]
                sys_instr    = req.get("system_instruction")
                cached_token = req.get("cached_content")
                target_model = req.get("model_name") or self.model
                max_tok      = min(
                    req.get("max_output_tokens") or self._max_output_tokens,
                    128_000 if self._is_opus_46_model(target_model) else 64_000
                )
                temp = req.get("temperature", 0.7)

                # System value — cached blocks when active, plain string otherwise
                use_cached = (
                    self.enable_caching
                    and bool(cached_token)
                    and self._cached_system_blocks is not None
                )
                if use_cached:
                    system_value = self._cached_system_blocks
                elif sys_instr:
                    system_value = sys_instr
                else:
                    system_value = None

                # Best-effort token preflight for long-context risk visibility.
                if self._batch_token_preflight:
                    system_chars = 0
                    if isinstance(system_value, list):
                        for block in system_value:
                            if isinstance(block, dict):
                                system_chars += len(str(block.get("text", "") or ""))
                    elif isinstance(system_value, str):
                        system_chars = len(system_value)
                    prompt_chars = len(str(prompt or ""))
                    # Use 0.43 tokens/char — conservative upper bound for JP/EN mixed prompts.
                    # Validated range is 0.41–0.43; using 0.43 avoids false-green preflight
                    # when chapters have dense Japanese text (each CJK char = 1-2 tokens but
                    # only 1 Python char after UTF-8 decode). Previous value 0.41 predicted
                    # 201,526 when actual was 204,645 (ratio 0.4249 for that run).
                    approx_input_tokens = int((system_chars + prompt_chars) * 0.43)
                    preflight_max_tokens = max(preflight_max_tokens, approx_input_tokens)
                    if approx_input_tokens >= 160_000:
                        preflight_warnings += 1
                        logger.warning(
                            f"[BATCH][PREFLIGHT] {custom_id}: estimated input ~{approx_input_tokens:,} tokens "
                            "(approaching 200K context boundary; ICL auto-cap may activate)."
                        )

                message_content: Any = prompt
                if shared_brief_prefix:
                    remainder = prompt_remainders.get(custom_id, prompt)
                    message_blocks: List[Dict[str, Any]] = [
                        {
                            "type": "text",
                            "text": shared_brief_prefix,
                            "cache_control": {"type": "ephemeral", "ttl": self._cache_ttl},
                        }
                    ]
                    if remainder:
                        message_blocks.append({"type": "text", "text": remainder})
                    message_content = message_blocks

                params: Dict[str, Any] = dict(
                    model=target_model,
                    max_tokens=max_tok,
                    temperature=temp,
                    messages=[{"role": "user", "content": message_content}],
                )
                if system_value is not None:
                    params["system"] = system_value

                # Thinking + effort for Opus 4.6 (mirrors generate())
                is_opus = self._is_opus_46_model(target_model)
                thinking_type = thinking_cfg.get("thinking_type", "adaptive")
                thinking_allowed = is_opus or thinking_type == "enabled"
                if thinking_allowed and thinking_cfg.get("enabled", False):
                    budget = self._resolve_thinking_budget(thinking_cfg, is_opus=is_opus)
                    if is_opus:
                        if thinking_type != "adaptive":
                            logger.info(
                                "[THINKING] Opus 4.6 override in batch: forcing "
                                "thinking.type=adaptive (deprecated enabled ignored)."
                            )
                        # Same fix as generate(): adaptive + effort=max, not deprecated enabled.
                        params["thinking"] = {"type": "adaptive"}
                        params["output_config"] = {"effort": "max"}
                    else:
                        if thinking_type == "adaptive":
                            params["thinking"] = {"type": "adaptive"}
                        else:
                            params["thinking"] = {"type": "enabled", "budget_tokens": budget}
                    params["temperature"] = 1.0

                if req_ctor is not None:
                    try:
                        anthropic_req = req_ctor(custom_id=custom_id, params=params)
                    except Exception:
                        anthropic_req = {"custom_id": custom_id, "params": params}
                else:
                    anthropic_req = {"custom_id": custom_id, "params": params}

                anthropic_requests.append(anthropic_req)

            if self._batch_token_preflight:
                logger.info(
                    f"[BATCH][PREFLIGHT] max_estimated_input={preflight_max_tokens:,} tokens; "
                    f"near_limit_warnings={preflight_warnings}"
                )

            # ── Proactive payload size check and chunking ───────────────────
            # nginx proxies typically enforce a 10 MB client_max_body_size.
            # With 9 chapters × large cached prompt the raw batch JSON can
            # exceed this limit.  Estimate the serialised size and split into
            # sub-batches of _MAX_BATCH_CHUNK_SIZE before submission so we
            # stay well under the proxy limit and preserve the 50% discount
            # (rather than falling back to expensive serial generation).
            try:
                _payload_bytes = len(
                    _json.dumps(
                        [r if isinstance(r, dict) else r.__dict__ for r in anthropic_requests],
                        default=str,
                    ).encode("utf-8")
                )
            except Exception:
                _payload_bytes = 0  # estimation failed — attempt full submission

            if _payload_bytes > self._MAX_BATCH_PAYLOAD_BYTES and len(anthropic_requests) > 1:
                logger.info(
                    f"[BATCH] Payload ~{_payload_bytes // 1024:,} KB exceeds proxy limit "
                    f"({self._MAX_BATCH_PAYLOAD_BYTES // 1024 // 1024} MB); splitting "
                    f"{len(anthropic_requests)} requests into chunks of "
                    f"{self._MAX_BATCH_CHUNK_SIZE}."
                )
                _chunks = [
                    anthropic_requests[i : i + self._MAX_BATCH_CHUNK_SIZE]
                    for i in range(0, len(anthropic_requests), self._MAX_BATCH_CHUNK_SIZE)
                ]
            else:
                _chunks = [anthropic_requests]

            def _extract_chunk_custom_ids(chunk_items: List[Any]) -> List[str]:
                ids: List[str] = []
                for item in chunk_items:
                    if isinstance(item, dict):
                        cid = item.get("custom_id")
                    else:
                        cid = getattr(item, "custom_id", None)
                    cid_s = str(cid).strip() if cid is not None else ""
                    if cid_s:
                        ids.append(cid_s)
                return ids

            fallback_to_serial = False
            submitted_custom_ids: set[str] = set()
            submission_queue: List[List[Any]] = list(_chunks)
            submission_attempt = 0
            chunk_retry_counts: Dict[Tuple[str, ...], int] = {}

            def _is_retryable_submit_error(message: str) -> bool:
                lowered = str(message or "").lower()
                retryable_markers = (
                    "internal server error",
                    "api_error",
                    "service unavailable",
                    "overloaded",
                    "temporarily unavailable",
                    "gateway timeout",
                    "bad gateway",
                    "request timeout",
                    "timed out",
                    "502",
                    "503",
                    "504",
                    "500",
                )
                return any(marker in lowered for marker in retryable_markers)

            while submission_queue:
                _chunk = submission_queue.pop(0)
                submission_attempt += 1
                _chunk_ids = _extract_chunk_custom_ids(_chunk)
                _chunk_label = (
                    f"attempt {submission_attempt}, size={len(_chunk)}"
                )
                logger.info(
                    f"[BATCH] Submitting {len(_chunk)} chapter requests to Anthropic "
                    f"Batch API ({_chunk_label})..."
                )
                if _chunk_ids:
                    logger.debug(
                        f"[BATCH] Request IDs in chunk: first={_chunk_ids[0]}, total={len(_chunk_ids)}"
                    )
                if self._batch_log_payload_preview:
                    try:
                        import json as _json_debug
                        first_req = _chunk[0] if _chunk else None
                        if first_req:
                            req_str = _json_debug.dumps(first_req, default=str, indent=2)[:1500]
                            logger.debug(f"[BATCH] First request (truncated): {req_str}...")
                    except Exception:
                        pass
                try:
                    batch = self._client.messages.batches.create(requests=_chunk)
                    batch_ids.append(batch.id)
                    submitted_custom_ids.update(_chunk_ids)
                    logger.info(f"[BATCH] Batch created: {batch.id} ({_chunk_label})")
                except Exception as e:
                    err_str = str(e)
                    # Log first request for debugging Pydantic validation errors
                    if "Extra inputs" in err_str or "extra_forbidden" in err_str:
                        try:
                            first_req = _chunk[0] if _chunk else None
                            if first_req:
                                import json
                                logger.error(f"[BATCH] Pydantic error - first request: {json.dumps(first_req, default=str)[:2000]}")
                        except:
                            pass
                    is_413 = any(x in err_str for x in ["413", "Too Large", "Request Entity Too Large"])
                    is_endpoint_error = any(x in err_str for x in ["405", "Method Not Allowed", "404", "Invalid URL"])
                    is_retryable_error = _is_retryable_submit_error(err_str)

                    if is_413:
                        if len(_chunk) > 1:
                            split_idx = max(1, len(_chunk) // 2)
                            left = _chunk[:split_idx]
                            right = _chunk[split_idx:]
                            logger.warning(
                                "[BATCH] Proxy rejected chunk as too large (413). "
                                f"Splitting {len(_chunk)} -> {len(left)} + {len(right)} and retrying."
                            )
                            # Queue split chunks immediately (depth-first style)
                            submission_queue.insert(0, right)
                            submission_queue.insert(0, left)
                            continue

                        # Single-request chunk still too large for proxy -> serial fallback for this request only.
                        if _chunk_ids:
                            cid = _chunk_ids[0]
                            req = request_by_custom_id.get(cid)
                            if req is not None:
                                logger.warning(
                                    f"[BATCH] Single-request payload still rejected by proxy for {cid}; "
                                    "using serial generation for this chapter only."
                                )
                                serial_fallback_requests.append(req)
                                continue

                        logger.warning(
                            f"[BATCH] Proxy rejected Batch API chunk ({e}). "
                            "Falling back to serial generation."
                        )
                        fallback_to_serial = True
                        break

                    if is_endpoint_error:
                        logger.warning(
                            f"[BATCH] Proxy rejected Batch API endpoint ({e}). "
                            "Falling back to serial generation."
                        )
                        fallback_to_serial = True
                        break

                    if is_retryable_error:
                        retry_key = tuple(_chunk_ids) if _chunk_ids else (f"__chunk_{submission_attempt}",)
                        retry_count = chunk_retry_counts.get(retry_key, 0) + 1
                        chunk_retry_counts[retry_key] = retry_count

                        if retry_count <= self._BATCH_CREATE_RETRY_ATTEMPTS:
                            delay_seconds = min(30, 2 ** (retry_count - 1))
                            logger.warning(
                                f"[BATCH] Transient Anthropic batch submission failure "
                                f"(attempt {retry_count}/{self._BATCH_CREATE_RETRY_ATTEMPTS}) "
                                f"for {len(_chunk)} request(s): {e}. "
                                f"Retrying in {delay_seconds}s."
                            )
                            _time.sleep(delay_seconds)
                            submission_queue.insert(0, _chunk)
                            continue

                        if len(_chunk) > 1:
                            split_idx = max(1, len(_chunk) // 2)
                            left = _chunk[:split_idx]
                            right = _chunk[split_idx:]
                            logger.warning(
                                "[BATCH] Anthropic batch submission kept failing after retries. "
                                f"Splitting {len(_chunk)} request(s) into {len(left)} + {len(right)}."
                            )
                            submission_queue.insert(0, right)
                            submission_queue.insert(0, left)
                            continue

                        if _chunk_ids:
                            cid = _chunk_ids[0]
                            req = request_by_custom_id.get(cid)
                            if req is not None:
                                logger.warning(
                                    f"[BATCH] Anthropic batch submission failed repeatedly for {cid}; "
                                    "falling back to serial generation for this chapter."
                                )
                                serial_fallback_requests.append(req)
                                continue

                        logger.warning(
                            "[BATCH] Anthropic batch submission failed repeatedly with no recoverable "
                            "custom_id; falling back to serial generation for remaining chapters."
                        )
                        fallback_to_serial = True
                        break

                    logger.error(f"[BATCH] Failed to create batch chunk: {e}")
                    raise

            if fallback_to_serial:
                if not batch_ids:
                    return self._fallback_serial_generate(requests)
                # Rare mixed mode: keep submitted batches, serialize only unsent chapters.
                remaining_reqs = [
                    req for req in requests
                    if str(req.get("custom_id", "")).strip() not in submitted_custom_ids
                ]
                serial_fallback_requests.extend(remaining_reqs)

            # Persist batch IDs for crash-resume
            if batch_state_path:
                try:
                    batch_state_path.write_text(
                        _json.dumps(
                            {
                                "batch_ids": batch_ids,
                                "request_custom_ids": expected_custom_ids,
                            }
                        )
                    )
                except Exception as _e:
                    logger.warning(f"[BATCH] Could not write batch state: {_e}")

        # ── Poll until complete (static wait mode) ──────────────────────
        if batch_ids:
            wait_logged = False
            last_errored = 0
            retrieve_retry_count = 0
            max_retrieve_retries = 5
            while True:
                all_ended = True
                total_succeeded = 0
                total_errored = 0
                total_processing = 0
                
                try:
                    for b_id in batch_ids:
                        status_obj = self._client.messages.batches.retrieve(b_id)
                        if status_obj.processing_status != "ended":
                            all_ended = False
                        
                        counts = status_obj.request_counts
                        total_succeeded += getattr(counts, "succeeded", 0)
                        total_errored += getattr(counts, "errored", 0) + getattr(counts, "expired", 0)
                        total_processing += getattr(counts, "processing", 0)
                    retrieve_retry_count = 0  # Reset on success
                except Exception as retrieve_err:
                    err_str = str(retrieve_err)
                    if any(x in err_str for x in ["500", "Internal Server", "Service Unavailable"]):
                        retrieve_retry_count += 1
                        if retrieve_retry_count <= max_retrieve_retries:
                            delay = min(30, 2 ** (retrieve_retry_count - 1))
                            logger.warning(
                                f"[BATCH] Transient error retrieving batch status "
                                f"(attempt {retrieve_retry_count}/{max_retrieve_retries}): {retrieve_err}. "
                                f"Retrying in {delay}s..."
                            )
                            _time.sleep(delay)
                            continue
                        else:
                            logger.error(
                                f"[BATCH] Batch retrieval failed after {max_retrieve_retries} retries: {retrieve_err}"
                            )
                            raise

                if not wait_logged:
                    logger.info(
                        f"[BATCH] Waiting for {len(batch_ids)} batch(es) to complete "
                        f"(poll interval={poll_interval_seconds}s). "
                        "Progress logs suppressed; will notify on failure or completion."
                    )
                    wait_logged = True

                if total_errored > last_errored:
                    logger.warning(
                        f"[BATCH] Failure detected while waiting: "
                        f"succeeded={total_succeeded}, errored={total_errored}, processing={total_processing}"
                    )
                    last_errored = total_errored

                if all_ended:
                    logger.info(
                        f"[BATCH] Polling complete: ended | "
                        f"succeeded={total_succeeded}, errored={total_errored}, processing={total_processing}"
                    )
                    break
                _time.sleep(poll_interval_seconds)
        else:
            logger.warning("[BATCH] No batches submitted; using serial fallback requests only.")

        # ── Collect results ─────────────────────────────────────────────
        results: Dict[str, GeminiResponse] = {}
        totals = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_creation_tokens_5m": 0,
            "cache_creation_tokens_1h": 0,
            "input_cost_usd": 0.0,
            "output_cost_usd": 0.0,
            "cache_read_cost_usd": 0.0,
            "cache_creation_cost_usd": 0.0,
            "cache_creation_cost_5m_usd": 0.0,
            "cache_creation_cost_1h_usd": 0.0,
            "total_cost_usd": 0.0,
        }
        expected_id_lower_map = {cid.lower(): cid for cid in expected_custom_ids}

        for b_id in batch_ids:
            for result in self._client.messages.batches.results(b_id):
                cid_raw = getattr(result, "custom_id", None)
                if not cid_raw and isinstance(result, dict):
                    cid_raw = result.get("custom_id")
                if not cid_raw:
                    req_obj = getattr(result, "request", None)
                    cid_raw = getattr(req_obj, "custom_id", None) if req_obj is not None else None
                if not cid_raw:
                    input_obj = getattr(result, "input", None)
                    cid_raw = getattr(input_obj, "custom_id", None) if input_obj is not None else None

                cid = str(cid_raw).strip() if cid_raw is not None else ""
                if cid and cid not in expected_custom_id_set:
                    cid = expected_id_lower_map.get(cid.lower(), cid)
                if cid and cid not in expected_custom_id_set:
                    # Normalize common variants (e.g., chapter-1, chapter 01) to chapter_01
                    m = _re.search(r"chapter[_\-\s]?(\d+)", cid, flags=_re.IGNORECASE)
                    if m:
                        cid_candidate = f"chapter_{int(m.group(1)):02d}"
                        if cid_candidate in expected_custom_id_set:
                            cid = cid_candidate

                if not cid:
                    cid = f"__missing_custom_id_{len(results) + 1}"
                    logger.warning(
                        "[BATCH] Received batch result without custom_id; "
                        f"using placeholder key {cid}"
                    )
                # Handle result.result as either object or dict
                result_obj = getattr(result, "result", None)
                if result_obj is None and isinstance(result, dict):
                    result_obj = result.get("result")
                
                if isinstance(result_obj, dict):
                    result_type = result_obj.get("type")
                else:
                    result_type = getattr(result_obj, "type", None) if result_obj else None

                if result_type == "succeeded":
                    if isinstance(result_obj, dict):
                        msg = result_obj.get("message")
                    else:
                        msg = getattr(result_obj, "message", None) if result_obj else None
                    # Extract text and thinking blocks (support object/dict/string variants)
                    text_parts_b: List[str] = []
                    thinking_parts_b: List[str] = []
                    tool_blocks_b = 0
                    raw_content_blocks = getattr(msg, "content", None)
                    if raw_content_blocks is None and isinstance(msg, dict):
                        raw_content_blocks = msg.get("content")

                    if isinstance(raw_content_blocks, str):
                        text_parts_b.append(raw_content_blocks)
                    elif isinstance(raw_content_blocks, list):
                        for block in raw_content_blocks:
                            if isinstance(block, dict):
                                btype = block.get("type")
                                if btype in {"text", "output_text"}:
                                    text_parts_b.append(str(block.get("text", "") or ""))
                                elif btype == "thinking":
                                    thinking_parts_b.append(str(block.get("thinking", "") or ""))
                                elif btype == "redacted_thinking":
                                    thinking_parts_b.append("\n\n[REDACTED_THINKING_BLOCK_BY_ANTHROPIC]\n\n")
                                elif btype == "tool_use":
                                    tool_blocks_b += 1
                            else:
                                btype = getattr(block, "type", None)
                                if btype in {"text", "output_text"}:
                                    text_parts_b.append(str(getattr(block, "text", "") or ""))
                                elif btype == "thinking":
                                    thinking_parts_b.append(str(getattr(block, "thinking", "") or ""))
                                elif btype == "redacted_thinking":
                                    thinking_parts_b.append("\n\n[REDACTED_THINKING_BLOCK_BY_ANTHROPIC]\n\n")
                                elif btype == "tool_use":
                                    tool_blocks_b += 1
                    elif raw_content_blocks is not None:
                        text_parts_b.append(str(raw_content_blocks))

                    raw_text = "".join(text_parts_b).strip()

                    # Strip inline <thinking> tags (same logic as generate())
                    inline_thinking = _re.findall(r"<thinking>(.*?)</thinking>", raw_text, flags=_re.DOTALL)
                    if inline_thinking:
                        clean_text = _re.sub(r"\s*<thinking>.*?</thinking>\s*", "\n", raw_text, flags=_re.DOTALL).strip()
                        thinking_parts_b.extend(inline_thinking)
                    else:
                        clean_text = raw_text

                    raw_thinking = "".join(thinking_parts_b).strip() or None

                    usage = getattr(msg, "usage", None)
                    if usage is None and isinstance(msg, dict):
                        usage = msg.get("usage")
                    if isinstance(usage, dict):
                        input_tokens = usage.get("input_tokens", 0)
                        output_tokens = usage.get("output_tokens", 0)
                    else:
                        input_tokens = getattr(usage, "input_tokens", 0)
                        output_tokens = getattr(usage, "output_tokens", 0)
                    (
                        cache_read_tokens,
                        cache_creation_tokens,
                        cache_creation_tokens_5m,
                        cache_creation_tokens_1h,
                    ) = self._extract_usage_cache_tokens(
                        usage,
                        cache_ttl_hint=self._cache_ttl,
                    )
                    msg_model = getattr(msg, "model", None)
                    if msg_model is None and isinstance(msg, dict):
                        msg_model = msg.get("model")
                    msg_model = msg_model or self.model

                    cost_breakdown = self.estimate_usage_cost_usd(
                        model_name=msg_model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cache_read_tokens=cache_read_tokens,
                        cache_creation_tokens=cache_creation_tokens,
                        cache_creation_tokens_5m=cache_creation_tokens_5m,
                        cache_creation_tokens_1h=cache_creation_tokens_1h,
                        cache_ttl=self._cache_ttl,
                        batch_mode=True,
                        fast_mode=False,
                    )

                    totals["input_tokens"] += int(input_tokens)
                    totals["output_tokens"] += int(output_tokens)
                    totals["cache_read_tokens"] += int(cache_read_tokens)
                    totals["cache_creation_tokens"] += int(cache_creation_tokens)
                    totals["cache_creation_tokens_5m"] += int(cache_creation_tokens_5m)
                    totals["cache_creation_tokens_1h"] += int(cache_creation_tokens_1h)
                    totals["input_cost_usd"] += cost_breakdown["input_cost_usd"]
                    totals["output_cost_usd"] += cost_breakdown["output_cost_usd"]
                    totals["cache_read_cost_usd"] += cost_breakdown["cache_read_cost_usd"]
                    totals["cache_creation_cost_usd"] += cost_breakdown["cache_creation_cost_usd"]
                    totals["cache_creation_cost_5m_usd"] += cost_breakdown["cache_creation_cost_5m_usd"]
                    totals["cache_creation_cost_1h_usd"] += cost_breakdown["cache_creation_cost_1h_usd"]
                    totals["total_cost_usd"] += cost_breakdown["total_cost_usd"]

                    stop_reason = getattr(msg, "stop_reason", None)
                    if stop_reason is None and isinstance(msg, dict):
                        stop_reason = msg.get("stop_reason")

                    if not clean_text and tool_blocks_b > 0:
                        logger.warning(
                            f"[BATCH] {cid} ended with empty text but {tool_blocks_b} tool_use block(s) "
                            f"(stop_reason={stop_reason or 'end_turn'})."
                        )

                    if cid in results:
                        logger.warning(
                            f"[BATCH] Duplicate result key '{cid}' detected; "
                            "preserving first result and skipping duplicate."
                        )
                        continue
                    results[cid] = GeminiResponse(
                        content=clean_text,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        finish_reason=stop_reason or "end_turn",
                        model=msg_model,
                        cached_tokens=cache_read_tokens,
                        thinking_content=raw_thinking,
                        cache_creation_tokens=cache_creation_tokens,
                        input_cost_usd=cost_breakdown["input_cost_usd"],
                        output_cost_usd=cost_breakdown["output_cost_usd"],
                        cache_read_cost_usd=cost_breakdown["cache_read_cost_usd"],
                        cache_creation_cost_usd=cost_breakdown["cache_creation_cost_usd"],
                        total_cost_usd=cost_breakdown["total_cost_usd"],
                        batch_pricing=True,
                        fast_mode_pricing=False,
                        cost_audit={
                            "schema_version": "1.0",
                            "provider": "anthropic",
                            "request_type": "batch",
                            "totals": {
                                "input_tokens": int(input_tokens or 0),
                                "output_tokens": int(output_tokens or 0),
                                "cached_tokens": int(cache_read_tokens or 0),
                                "cache_creation_tokens": int(cache_creation_tokens or 0),
                                "input_cost_usd": float(cost_breakdown["input_cost_usd"]),
                                "output_cost_usd": float(cost_breakdown["output_cost_usd"]),
                                "cache_read_cost_usd": float(cost_breakdown["cache_read_cost_usd"]),
                                "cache_creation_cost_usd": float(cost_breakdown["cache_creation_cost_usd"]),
                                "total_cost_usd": float(cost_breakdown["total_cost_usd"]),
                            },
                            "result_type": "batch_result",
                        },
                    )
                else:
                    # errored or expired
                    if isinstance(result_obj, dict):
                        error_detail = result_obj.get("error")
                    else:
                        error_detail = getattr(result_obj, "error", None) if result_obj else None
                    logger.error(f"[BATCH] Chapter {cid} {result_type}: {error_detail}")
                    # Try to log the original request for debugging
                    try:
                        orig_req = request_by_custom_id.get(cid)
                        if orig_req:
                            import json as _json_err
                            req_summary = {
                                "custom_id": orig_req.get("custom_id"),
                                "model": orig_req.get("model_name", "default"),
                                "prompt_chars": len(str(orig_req.get("prompt", ""))),
                                "system_chars": len(str(orig_req.get("system_instruction", "") or "")),
                                "has_cached_content": bool(orig_req.get("cached_content")),
                            }
                            logger.error(f"[BATCH] Original request for {cid}: {_json_err.dumps(req_summary)}")
                    except Exception as _e:
                        logger.debug(f"[BATCH] Could not log request summary: {_e}")
                    if cid in results:
                        logger.warning(
                            f"[BATCH] Duplicate error result key '{cid}' detected; "
                            "preserving first result and skipping duplicate."
                        )
                        continue
                    results[cid] = GeminiResponse(
                        content="",
                        input_tokens=0,
                        output_tokens=0,
                        finish_reason="batch_error",
                        model=self.model,
                        cached_tokens=0,
                        thinking_content=None,
                        cache_creation_tokens=0,
                        batch_pricing=True,
                        cost_audit={
                            "schema_version": "1.0",
                            "provider": "anthropic",
                            "request_type": "batch",
                            "totals": {
                                "input_tokens": 0,
                                "output_tokens": 0,
                                "cached_tokens": 0,
                                "cache_creation_tokens": 0,
                                "input_cost_usd": 0.0,
                                "output_cost_usd": 0.0,
                                "cache_read_cost_usd": 0.0,
                                "cache_creation_cost_usd": 0.0,
                                "total_cost_usd": 0.0,
                            },
                            "result_type": "batch_error",
                        },
                )

        # Merge per-chapter serial fallbacks (e.g., single-request 413 cases)
        if serial_fallback_requests:
            # Deduplicate by custom_id while preserving order.
            seen_serial_ids: set[str] = set()
            unique_serial_requests: List[Dict[str, Any]] = []
            for req in serial_fallback_requests:
                cid = str(req.get("custom_id", "")).strip()
                if not cid or cid in seen_serial_ids:
                    continue
                seen_serial_ids.add(cid)
                unique_serial_requests.append(req)

            logger.warning(
                f"[BATCH] Running serial fallback for {len(unique_serial_requests)} request(s) "
                "that could not be submitted via Batch API."
            )
            serial_results = self._fallback_serial_generate(unique_serial_requests)
            for cid, response in serial_results.items():
                if cid in results:
                    logger.warning(
                        f"[BATCH] Serial fallback result for {cid} ignored because batch result already exists."
                    )
                    continue
                results[cid] = response

        received_ids = set(results.keys())
        overlap = len(received_ids.intersection(expected_custom_id_set))
        if results and overlap == 0:
            logger.error(
                "[BATCH] Result ID mismatch: none of the returned result keys match requested chapter IDs. "
                f"requested_sample={expected_custom_ids[:5]} received_sample={list(received_ids)[:5]}"
            )
            if resumed_from_state:
                logger.error(
                    "[BATCH] Mismatch happened while resuming from state. "
                    "Deleting stale state file so the next run creates a fresh batch."
                )
                if batch_state_path and batch_state_path.exists():
                    try:
                        batch_state_path.unlink()
                    except Exception:
                        pass

        logger.info(
            f"[BATCH] Complete: {sum(1 for r in results.values() if r.content)} succeeded, "
            f"{sum(1 for r in results.values() if not r.content)} failed"
        )
        logger.info(
            "[BATCH][COST] usage summary: "
            f"in={totals['input_tokens']:,} (${totals['input_cost_usd']:.6f}) | "
            f"out={totals['output_tokens']:,} (${totals['output_cost_usd']:.6f}) | "
            f"cache_read={totals['cache_read_tokens']:,} (${totals['cache_read_cost_usd']:.6f}) | "
            f"cache_write={totals['cache_creation_tokens']:,} "
            f"(5m={totals['cache_creation_tokens_5m']:,}, 1h={totals['cache_creation_tokens_1h']:,}) "
            f"(${totals['cache_creation_cost_usd']:.6f}) | "
            f"total=${totals['total_cost_usd']:.6f}"
        )
        self._last_batch_audit = {
            "schema_version": "1.0",
            "provider": "anthropic",
            "request_type": "batch",
            "submitted_request_count": len(expected_custom_id_set),
            "result_count": len(results),
            "matched_result_count": overlap,
            "serial_fallback_request_count": len(serial_fallback_requests),
            "submission_retry_events": sum(int(v or 0) for v in chunk_retry_counts.values()),
            "retrieve_retry_count": int(retrieve_retry_count or 0),
            "totals": dict(totals),
        }

        # Clean up state file on success
        if batch_state_path and batch_state_path.exists():
            try:
                batch_state_path.unlink()
            except Exception:
                pass

        return results

    def _fallback_serial_generate(self, requests: List[Dict[str, Any]]) -> Dict[str, GeminiResponse]:
        """Fallback to serial generation when proxy rejects Batch API."""
        import time as _time
        logger.warning(f"[BATCH-FALLBACK] Starting serial generation for {len(requests)} requests due to proxy limitations...")
        results: Dict[str, GeminiResponse] = {}
        for req in requests:
            custom_id = req["custom_id"]
            logger.info(f"[BATCH-FALLBACK] Processing {custom_id}...")
            
            original_model = self.model
            if req.get("model_name"):
                self.model = req["model_name"]
                
            try:
                response = self.generate(
                    system_instruction=req.get("system_instruction"),
                    prompt=req["prompt"],
                    max_output_tokens=req.get("max_output_tokens") or self._max_output_tokens,
                    temperature=req.get("temperature", 0.7),
                    cached_content=req.get("cached_content"),
                )
                results[custom_id] = response
            except Exception as e:
                logger.error(f"[BATCH-FALLBACK] Failed to generate for {custom_id}: {e}")
                results[custom_id] = GeminiResponse(
                    content="",
                    input_tokens=0,
                    output_tokens=0,
                    finish_reason="fallback_error",
                    model=self.model,
                    cached_tokens=0,
                    thinking_content=None,
                    cache_creation_tokens=0,
                    batch_pricing=True,
                )
            finally:
                self.model = original_model
                
            _time.sleep(self._rate_limit_delay)
            
        return results

    # ──────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────

    def _load_thinking_config(self) -> Dict[str, Any]:
        """Load thinking config from config.yaml anthropic section."""
        try:
            from pipeline.config import get_config_section
            anthropic_cfg = get_config_section("anthropic") or {}
            return anthropic_cfg.get("thinking_mode", {"enabled": False})
        except Exception:
            return {"enabled": False}

    def _resolve_thinking_budget(self, thinking_cfg: Dict[str, Any], *, is_opus: bool) -> int:
        """
        Resolve hard thinking budget from config with safe defaults.

        Opus default is intentionally higher to avoid clipping deep reasoning.
        """
        default_budget = 8000 if is_opus else 1024
        try:
            budget = int(thinking_cfg.get("thinking_budget", default_budget))
        except Exception:
            budget = default_budget
        return max(1024, budget)

    def _load_batch_config(self) -> Dict[str, Any]:
        """Load Anthropic batch optimization config from config.yaml."""
        defaults = {
            "promote_cache_ttl_1h": True,
            "cache_shared_brief": True,
            "token_preflight": True,
            "log_payload_preview": False,
        }
        try:
            from pipeline.config import get_config_section

            anthropic_cfg = get_config_section("anthropic") or {}
            batch_cfg = anthropic_cfg.get("batch", {}) if isinstance(anthropic_cfg, dict) else {}
            if not isinstance(batch_cfg, dict):
                return defaults
            merged = dict(defaults)
            # Backward compatibility: legacy top-level key
            if isinstance(anthropic_cfg, dict) and "batch_log_payload_preview" in anthropic_cfg:
                merged["log_payload_preview"] = bool(
                    anthropic_cfg.get("batch_log_payload_preview", False)
                )
            # Preferred: nested anthropic.batch.log_payload_preview
            if "log_payload_preview" in batch_cfg:
                merged["log_payload_preview"] = bool(batch_cfg.get("log_payload_preview", False))
            merged.update(batch_cfg)
            return merged
        except Exception:
            return defaults

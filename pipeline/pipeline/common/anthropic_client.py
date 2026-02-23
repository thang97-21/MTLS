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
import backoff
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from pipeline.common.gemini_client import GeminiResponse  # reuse same dataclass

logger = logging.getLogger(__name__)

# Sentinel string returned by create_cache() so the caller can detect success
# (GeminiClient returns a real resource name; we return this constant instead)
_ANTHROPIC_CACHE_SENTINEL = "__anthropic_inline_cache__"


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

    def __init__(
        self,
        api_key: str = None,
        model: str = "claude-sonnet-4-6",
        enable_caching: bool = True,
        fast_mode: bool = False,
        fast_mode_fallback: bool = True,
    ):
        try:
            import anthropic as _anthropic
            self._anthropic_mod = _anthropic
        except ImportError:
            raise ImportError(
                "anthropic package is not installed. Run: pip install anthropic"
            )

        self.model = model
        self.enable_caching = enable_caching
        self.fast_mode = fast_mode
        self.fast_mode_fallback = fast_mode_fallback

        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise ValueError(
                "Anthropic API key not found. "
                "Set ANTHROPIC_API_KEY env var or pass api_key= explicitly."
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
        self._client = _anthropic.Anthropic(
            api_key=resolved_key,
            timeout=self._DEFAULT_HTTP_TIMEOUT_SECONDS,
            max_retries=0,  # disable SDK built-in retries; @backoff owns all retry logic
        )
        # Maximum output tokens:
        #   Opus 4.6   — 128K natively (no beta header required as of Opus 4.6 release).
        #   Sonnet 4.6 — 64K natively.
        # The model-specific cap is enforced at call time in generate() via is_opus check.
        self._max_output_tokens = 64000   # default for Sonnet; Opus overrides to 128K below

        # Rate limiting — mirrors GeminiClient.set_rate_limit()
        self._last_request_time: float = 0.0
        self._rate_limit_delay: float = 6.0  # default ~10 req/min

        # Inline cache state
        # When create_cache() or warm_cache() is called, we store the
        # pre-built system array here. generate() injects it when active.
        self._cached_system_blocks: Optional[List[Dict]] = None
        self._cache_ttl: str = "5m"  # "5m" | "1h"
        self._cache_created_at: Optional[float] = None

        logger.info(
            f"AnthropicClient initialized "
            f"(model={self.model}, caching={enable_caching}, "
            f"fast_mode={fast_mode})"
        )

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
                f"(TTL={self._cache_ttl})"
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
                f"{len(system_instruction):,}c (TTL={self._cache_ttl})"
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

    def warm_cache(self, system_instruction: str, model: str = None) -> bool:
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

        normalized_model = (model_name or "").strip().lower()
        is_fast = fast_mode and normalized_model.startswith("claude-opus-4-6")
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
        cache_creation_cost = (
            (max(0, int(cache_creation_tokens)) / 1_000_000.0)
            * input_rate
            * write_multiplier
        )

        input_cost *= discount_multiplier
        output_cost *= discount_multiplier
        cache_read_cost *= discount_multiplier
        cache_creation_cost *= discount_multiplier

        cache_total = cache_read_cost + cache_creation_cost
        total_cost = input_cost + output_cost + cache_total

        return {
            "input_cost_usd": input_cost,
            "output_cost_usd": output_cost,
            "cache_read_cost_usd": cache_read_cost,
            "cache_creation_cost_usd": cache_creation_cost,
            "cache_total_cost_usd": cache_total,
            "total_cost_usd": total_cost,
            "input_rate_per_mtok": input_rate,
            "output_rate_per_mtok": output_rate,
            "batch_discount_multiplier": discount_multiplier,
            "fast_mode_multiplier": cls._FAST_MODE_MULTIPLIER if is_fast else 1.0,
        }

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
        system_instruction: str = None,
        temperature: float = 0.7,
        max_output_tokens: int = 16000,
        safety_settings: Dict[str, str] = None,    # ignored — no Anthropic equivalent
        model: str = None,
        cached_content: str = None,                # non-empty → use stored cache blocks
        force_new_session: bool = False,            # True → Amnesia Protocol, bypass cache
        generation_config: Dict[str, Any] = None,
        tools: Optional[List[Any]] = None,         # not wired for translator path
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
        """
        target_model = model or self.model
        thinking_cfg = self._load_thinking_config()

        # Apply generation_config overrides (same keys as Gemini path)
        if generation_config:
            temperature = generation_config.get("temperature", temperature)
            max_output_tokens = generation_config.get("max_output_tokens", max_output_tokens)

        # Hard cap: use beta-unlocked limit (64K with output-128k header)
        max_output_tokens = min(max_output_tokens, self._max_output_tokens)

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
                f"[CACHE] Injecting {len(self._cached_system_blocks)}-block "
                f"cached system array (TTL={self._cache_ttl})"
            )
        elif system_instruction:
            system_value = system_instruction   # plain string — Anthropic accepts both
        else:
            system_value = None

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
        #   - thinking: {type: "adaptive"}  — recommended, self-manages depth
        #   - effort controlled via output_config: {effort: "max"} (Opus-only)
        #   - budget_tokens DEPRECATED on Opus 4.6; still functional but will be removed
        #   - 128K output tokens native (no beta header needed)
        #
        # Sonnet 4.6 API (current):
        #   - thinking: {type: "adaptive"} OR {type: "enabled", budget_tokens: N}
        #   - effort: "max" NOT supported (returns 400); defaults to "high"
        #   - 64K output tokens native
        #
        is_opus = target_model.startswith("claude-opus-4-6")

        # Raise the per-call output cap to 128K for Opus (native, no beta header).
        if is_opus:
            kwargs["max_tokens"] = min(max_output_tokens, 128_000)

        thinking_type = thinking_cfg.get("thinking_type", "adaptive")
        thinking_allowed = is_opus or thinking_type == "enabled"
        if thinking_allowed and thinking_cfg.get("enabled", False) and not force_new_session:
            budget = thinking_cfg.get("thinking_budget", 1024)
            if is_opus:
                # Opus 4.6: adaptive thinking + effort="max" via output_config.
                # budget_tokens is deprecated on Opus — do NOT pass it.
                kwargs["thinking"] = {"type": "adaptive"}
                kwargs["output_config"] = {"effort": "max"}
                logger.info("[THINKING] Opus 4.6: adaptive thinking + effort=max (128K output)")
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
        use_fast_mode = self.fast_mode and target_model.startswith("claude-opus-4-6")
        effective_fast_mode = use_fast_mode

        logger.info(
            f"Calling Anthropic API "
            f"(model={target_model}, cached_blocks={use_cached_blocks}, "
            f"fast_mode={use_fast_mode})..."
        )
        start_time = time.time()

        # Use streaming to avoid the SDK's 10-minute non-streaming timeout guard.
        # The stream context manager collects the full response before returning.
        try:
            text_parts: List[str] = []
            thinking_parts: List[str] = []
            finish_reason = "end_turn"
            input_tokens = output_tokens = cache_creation_tokens = cache_read_tokens = 0

            stream_kwargs = dict(**kwargs)
            if use_fast_mode:
                stream_kwargs["speed"] = "fast"
                stream_kwargs["betas"] = [self._FAST_MODE_BETA]

            try:
                stream_ctx = (
                    self._client.beta.messages.stream(**stream_kwargs)
                    if use_fast_mode
                    else self._client.messages.stream(**stream_kwargs)
                )
                with stream_ctx as stream:
                    for event in stream:
                        event_type = getattr(event, "type", None)
                        if event_type == "content_block_delta":
                            delta = getattr(event, "delta", None)
                            if delta:
                                if getattr(delta, "type", None) == "text_delta":
                                    text_parts.append(getattr(delta, "text", ""))
                                elif getattr(delta, "type", None) == "thinking_delta":
                                    thinking_parts.append(getattr(delta, "thinking", ""))
                    final = stream.get_final_message()
                    usage = final.usage
                    input_tokens = getattr(usage, "input_tokens", 0)
                    output_tokens = getattr(usage, "output_tokens", 0)
                    cache_creation_tokens = getattr(usage, "cache_creation_input_tokens", 0) or 0
                    cache_read_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0
                    finish_reason = final.stop_reason or "end_turn"

            except self._anthropic_mod.RateLimitError as rl_err:
                if use_fast_mode and self.fast_mode_fallback:
                    # Fast mode rate limit hit — fall back to standard speed.
                    # Cache prefix will NOT be shared (cache miss for this request).
                    logger.warning(
                        "[FAST-MODE] Rate limit on fast mode — falling back to standard speed. "
                        "Note: prompt cache miss (fast/standard prefixes are separate)."
                    )
                    standard_kwargs = {k: v for k, v in stream_kwargs.items()
                                       if k not in ("speed", "betas")}
                    effective_fast_mode = False
                    with self._client.messages.stream(**standard_kwargs) as stream:
                        for event in stream:
                            event_type = getattr(event, "type", None)
                            if event_type == "content_block_delta":
                                delta = getattr(event, "delta", None)
                                if delta:
                                    if getattr(delta, "type", None) == "text_delta":
                                        text_parts.append(getattr(delta, "text", ""))
                                    elif getattr(delta, "type", None) == "thinking_delta":
                                        thinking_parts.append(getattr(delta, "thinking", ""))
                        final = stream.get_final_message()
                        usage = final.usage
                        input_tokens = getattr(usage, "input_tokens", 0)
                        output_tokens = getattr(usage, "output_tokens", 0)
                        cache_creation_tokens = getattr(usage, "cache_creation_input_tokens", 0) or 0
                        cache_read_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0
                        finish_reason = final.stop_reason or "end_turn"
                else:
                    raise rl_err

        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            raise

        duration = time.time() - start_time
        logger.info(
            f"Anthropic response received in {duration:.2f}s "
            f"(stop_reason={finish_reason})"
        )
        self._last_request_time = time.time()

        cost_breakdown = self.estimate_usage_cost_usd(
            model_name=target_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cache_ttl=self._cache_ttl,
            batch_mode=False,
            fast_mode=effective_fast_mode,
        )
        logger.info(
            "[COST] LLM request usage: "
            f"in={input_tokens:,} (${cost_breakdown['input_cost_usd']:.6f}) | "
            f"out={output_tokens:,} (${cost_breakdown['output_cost_usd']:.6f}) | "
            f"cache_read={cache_read_tokens:,} (${cost_breakdown['cache_read_cost_usd']:.6f}) | "
            f"cache_write={cache_creation_tokens:,} (${cost_breakdown['cache_creation_cost_usd']:.6f}) | "
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
                f"(budget cap: {thinking_cfg.get('thinking_budget', 1024)})"
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
        )

    # ──────────────────────────────────────────────────────
    # Batch API — 50% cost reduction for non-realtime runs
    # ──────────────────────────────────────────────────────

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

        if not requests:
            logger.warning("[BATCH] batch_generate() called with empty request list")
            return {}

        thinking_cfg = self._load_thinking_config()

        # ── Check for a resumable batch ID ─────────────────────────────
        batch_id: Optional[str] = None
        if batch_state_path and batch_state_path.exists():
            try:
                state = _json.loads(batch_state_path.read_text())
                batch_id = state.get("batch_id")
                if batch_id:
                    logger.info(f"[BATCH] Resuming existing batch: {batch_id}")
            except Exception as _e:
                logger.warning(f"[BATCH] Could not read batch state file: {_e}")

        # ── Build request objects ───────────────────────────────────────
        if batch_id is None:
            anthropic_requests = []
            for req in requests:
                custom_id    = req["custom_id"]
                prompt       = req["prompt"]
                sys_instr    = req.get("system_instruction")
                cached_token = req.get("cached_content")
                target_model = req.get("model_name") or self.model
                max_tok      = min(
                    req.get("max_output_tokens") or self._max_output_tokens,
                    128_000 if target_model.startswith("claude-opus-4-6") else 64_000
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

                params: Dict[str, Any] = dict(
                    model=target_model,
                    max_tokens=max_tok,
                    temperature=temp,
                    messages=[{"role": "user", "content": prompt}],
                )
                if system_value is not None:
                    params["system"] = system_value

                # Thinking + effort for Opus 4.6 (mirrors generate())
                is_opus = target_model.startswith("claude-opus-4-6")
                thinking_type = thinking_cfg.get("thinking_type", "adaptive")
                thinking_allowed = is_opus or thinking_type == "enabled"
                if thinking_allowed and thinking_cfg.get("enabled", False):
                    budget = thinking_cfg.get("thinking_budget", 1024)
                    if is_opus:
                        params["thinking"] = {"type": "adaptive"}
                        params["output_config"] = {"effort": "max"}
                    else:
                        if thinking_type == "adaptive":
                            params["thinking"] = {"type": "adaptive"}
                        else:
                            params["thinking"] = {"type": "enabled", "budget_tokens": budget}
                    params["temperature"] = 1.0

                anthropic_requests.append(
                    self._anthropic_mod.types.message_create_params.Request(
                        custom_id=custom_id,
                        params=params,
                    )
                )

            logger.info(f"[BATCH] Submitting {len(anthropic_requests)} chapter requests to Anthropic Batch API...")
            batch = self._client.messages.batches.create(requests=anthropic_requests)
            batch_id = batch.id
            logger.info(f"[BATCH] Batch created: {batch_id}")

            # Persist batch ID for crash-resume
            if batch_state_path:
                try:
                    batch_state_path.write_text(_json.dumps({"batch_id": batch_id}))
                except Exception as _e:
                    logger.warning(f"[BATCH] Could not write batch state: {_e}")

        # ── Poll until complete ─────────────────────────────────────────
        while True:
            status_obj = self._client.messages.batches.retrieve(batch_id)
            processing_status = status_obj.processing_status
            counts = status_obj.request_counts
            completed = getattr(counts, "succeeded", 0) + getattr(counts, "errored", 0) + getattr(counts, "expired", 0)
            total = getattr(counts, "processing", 0) + completed
            logger.info(
                f"[BATCH] Status={processing_status} | "
                f"succeeded={getattr(counts, 'succeeded', '?')}, "
                f"errored={getattr(counts, 'errored', '?')}, "
                f"processing={getattr(counts, 'processing', '?')}"
            )
            if processing_status == "ended":
                break
            _time.sleep(poll_interval_seconds)

        # ── Collect results ─────────────────────────────────────────────
        results: Dict[str, GeminiResponse] = {}
        totals = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "input_cost_usd": 0.0,
            "output_cost_usd": 0.0,
            "cache_read_cost_usd": 0.0,
            "cache_creation_cost_usd": 0.0,
            "total_cost_usd": 0.0,
        }
        for result in self._client.messages.batches.results(batch_id):
            cid = result.custom_id
            result_type = result.result.type

            if result_type == "succeeded":
                msg = result.result.message
                # Extract text and thinking blocks
                text_parts_b: List[str] = []
                thinking_parts_b: List[str] = []
                for block in msg.content:
                    btype = getattr(block, "type", None)
                    if btype == "text":
                        text_parts_b.append(getattr(block, "text", ""))
                    elif btype == "thinking":
                        thinking_parts_b.append(getattr(block, "thinking", ""))

                raw_text = "".join(text_parts_b).strip()

                # Strip inline <thinking> tags (same logic as generate())
                inline_thinking = _re.findall(r"<thinking>(.*?)</thinking>", raw_text, flags=_re.DOTALL)
                if inline_thinking:
                    clean_text = _re.sub(r"\s*<thinking>.*?</thinking>\s*", "\n", raw_text, flags=_re.DOTALL).strip()
                    thinking_parts_b.extend(inline_thinking)
                else:
                    clean_text = raw_text

                raw_thinking = "".join(thinking_parts_b).strip() or None

                usage = msg.usage
                input_tokens = getattr(usage, "input_tokens", 0)
                output_tokens = getattr(usage, "output_tokens", 0)
                cache_read_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0
                cache_creation_tokens = getattr(usage, "cache_creation_input_tokens", 0) or 0
                cost_breakdown = self.estimate_usage_cost_usd(
                    model_name=msg.model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_creation_tokens=cache_creation_tokens,
                    cache_ttl=self._cache_ttl,
                    batch_mode=True,
                    fast_mode=False,
                )

                totals["input_tokens"] += int(input_tokens)
                totals["output_tokens"] += int(output_tokens)
                totals["cache_read_tokens"] += int(cache_read_tokens)
                totals["cache_creation_tokens"] += int(cache_creation_tokens)
                totals["input_cost_usd"] += cost_breakdown["input_cost_usd"]
                totals["output_cost_usd"] += cost_breakdown["output_cost_usd"]
                totals["cache_read_cost_usd"] += cost_breakdown["cache_read_cost_usd"]
                totals["cache_creation_cost_usd"] += cost_breakdown["cache_creation_cost_usd"]
                totals["total_cost_usd"] += cost_breakdown["total_cost_usd"]

                results[cid] = GeminiResponse(
                    content=clean_text,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    finish_reason=msg.stop_reason or "end_turn",
                    model=msg.model,
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
                )
            else:
                # errored or expired
                error_detail = getattr(result.result, "error", None)
                logger.error(f"[BATCH] Chapter {cid} {result_type}: {error_detail}")
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
                )

        logger.info(
            f"[BATCH] Complete: {sum(1 for r in results.values() if r.content)} succeeded, "
            f"{sum(1 for r in results.values() if not r.content)} failed"
        )
        logger.info(
            "[BATCH][COST] usage summary: "
            f"in={totals['input_tokens']:,} (${totals['input_cost_usd']:.6f}) | "
            f"out={totals['output_tokens']:,} (${totals['output_cost_usd']:.6f}) | "
            f"cache_read={totals['cache_read_tokens']:,} (${totals['cache_read_cost_usd']:.6f}) | "
            f"cache_write={totals['cache_creation_tokens']:,} (${totals['cache_creation_cost_usd']:.6f}) | "
            f"total=${totals['total_cost_usd']:.6f}"
        )

        # Clean up state file on success
        if batch_state_path and batch_state_path.exists():
            try:
                batch_state_path.unlink()
            except Exception:
                pass

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

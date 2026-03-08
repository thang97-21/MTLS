"""
Translator Configuration Loader.
Loads settings from the global config.yaml and provides typed accessors.
Supports multi-language configuration (EN, VN, etc.)
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional
from pipeline.config import (
    get_config_section, get_target_language, get_language_config,
    get_phase_generation_config,
    PIPELINE_ROOT
)

# Module constants
MODULE_NAME = "translator"


FULL_PREQUEL_CACHE_REASON_CODES = {
    "default_rag_mode": "FULL_PREQUEL_DEFAULT_RAG_MODE",
    "enabled": "FULL_PREQUEL_CACHE_ENABLED",
    "disabled_by_config": "FULL_PREQUEL_DISABLED_BY_CONFIG",
    "provider_mismatch": "FULL_PREQUEL_PROVIDER_MISMATCH",
    "route_not_openrouter": "FULL_PREQUEL_ROUTE_NOT_OPENROUTER",
    "adn_v2_required": "FULL_PREQUEL_ADN_V2_REQUIRED",
    "name_order_guard_failed": "FULL_PREQUEL_NAME_ORDER_GUARD_FAILED",
    "context_budget_exceeded": "FULL_PREQUEL_CONTEXT_BUDGET_EXCEEDED",
    "cache_warm_failed": "FULL_PREQUEL_CACHE_WARM_FAILED",
    "fallback_auth_401": "FULL_PREQUEL_FALLBACK_AUTH_401",
    "fallback_transport_5xx": "FULL_PREQUEL_FALLBACK_TRANSPORT_5XX",
    "fallback_adn_hard_fail": "FULL_PREQUEL_FALLBACK_ADN_HARD_FAIL",
}


def get_translator_provider() -> str:
    """
    Return the active LLM provider for the translator path.

    Values: "google" (default) | "anthropic"
    Sub-agents (planner, summarizer, metadata) always use Gemini regardless.
    """
    cfg = get_config_section("translator_provider")
    # get_config_section returns the raw value when the key maps to a scalar
    if isinstance(cfg, str):
        return cfg.strip().lower()
    # Fallback: read directly from the top-level config dict
    try:
        from pipeline.config import load_config
        return load_config().get("translator_provider", "google").strip().lower()
    except Exception:
        return "google"


def get_anthropic_config() -> Dict[str, Any]:
    """Get Anthropic API configuration (only used when translator_provider=anthropic)."""
    return get_config_section("anthropic") or {}


def get_phase2_openrouter_route() -> Dict[str, Any]:
    """
    Resolve Phase 2 translator routing for OpenRouter transport.

    Policy:
        - If translation.phase2_anthropic_endpoint == "official", Phase 2 always uses
            direct Anthropic endpoint (regardless of proxy.inference.provider).
        - Otherwise, if proxy.inference.provider == "openrouter", Phase 2 uses
            OpenRouter Anthropic route.
        - If provider is anything else, Phase 2 stays on legacy direct Anthropic route.

    Returns:
        {
            "enabled": bool,
            "base_url": str,
            "api_key_env": str,
            "has_api_key": bool,
        }
    """
    translation_cfg = get_translation_config() or {}
    endpoint_pref = str(
        translation_cfg.get("phase2_anthropic_endpoint") or "openrouter"
    ).strip().lower()
    if endpoint_pref in {"official", "anthropic", "direct"}:
        return {
            "enabled": False,
            "base_url": "",
            "api_key_env": "",
            "has_api_key": False,
        }

    proxy_cfg = get_config_section("proxy") or {}
    inference_cfg = proxy_cfg.get("inference", {}) if isinstance(proxy_cfg, dict) else {}

    provider = str(inference_cfg.get("provider") or "").strip().lower()
    if provider != "openrouter":
        return {
            "enabled": False,
            "base_url": "",
            "api_key_env": "",
            "has_api_key": False,
        }

    api_key_env = str(inference_cfg.get("api_key_env") or "OPENROUTER_API_KEY").strip() or "OPENROUTER_API_KEY"
    has_api_key = bool(os.getenv(api_key_env))

    raw_base = str(inference_cfg.get("base_url") or "https://openrouter.ai/api/v1").strip().rstrip("/")

    return {
        "enabled": True,
        "base_url": raw_base,
        "api_key_env": api_key_env,
        "has_api_key": has_api_key,
    }


def is_openrouter_opus_1m_confirmed() -> bool:
    """
    Return True when OpenRouter route is selected and Opus 1M support is confirmed.

    Confirmation source:
      proxy.capability_gates.claude_opus_1m_confirmed (preferred)
      proxy.capability_gates.claude_opus_1m_support (legacy alias)
    """
    route = get_phase2_openrouter_route()
    if not bool(route.get("enabled", False)):
        return False

    proxy_cfg = get_config_section("proxy") or {}

    anthropic_cfg = get_anthropic_config()
    model_name = str((anthropic_cfg or {}).get("model") or "").strip().lower()
    if "opus" not in model_name:
        return False

    capability_gates = proxy_cfg.get("capability_gates", {}) if isinstance(proxy_cfg, dict) else {}
    if not isinstance(capability_gates, dict):
        capability_gates = {}

    confirmed = capability_gates.get("claude_opus_1m_confirmed", None)
    if confirmed is None:
        confirmed = capability_gates.get("claude_opus_1m_support", False)
    return bool(confirmed)


def get_gemini_config() -> Dict[str, Any]:
    """Get Gemini API configuration."""
    return get_config_section("gemini")


def get_translation_config() -> Dict[str, Any]:
    """Get translation-specific settings."""
    return get_config_section("translation")


def get_full_prequel_cache_gate_config() -> Dict[str, Any]:
    """Get normalized runtime gate config for full-prequel cache mode."""
    translation_cfg = get_translation_config() or {}
    gate_cfg = translation_cfg.get("full_prequel_cache_gate", {})
    if not isinstance(gate_cfg, dict):
        gate_cfg = {}

    enabled = bool(gate_cfg.get("enabled", False))
    fallback_mode = str(gate_cfg.get("fallback_mode", "series_bible_rag") or "series_bible_rag").strip() or "series_bible_rag"
    context_safety_ratio = float(gate_cfg.get("context_safety_ratio", 0.85) or 0.85)
    if context_safety_ratio <= 0.0:
        context_safety_ratio = 0.85
    if context_safety_ratio > 1.0:
        context_safety_ratio = 1.0

    target_context_window_tokens = int(gate_cfg.get("target_context_window_tokens", 200000) or 200000)
    if target_context_window_tokens <= 0:
        target_context_window_tokens = 200000

    estimated_system_tokens = int(gate_cfg.get("estimated_system_tokens", 18000) or 18000)
    estimated_prequel_bundle_tokens = int(gate_cfg.get("estimated_prequel_bundle_tokens", 120000) or 120000)
    estimated_chapter_prompt_tokens = int(gate_cfg.get("estimated_chapter_prompt_tokens", 24000) or 24000)
    max_transport_5xx_before_fallback = int(gate_cfg.get("max_transport_5xx_before_fallback", 2) or 2)
    if max_transport_5xx_before_fallback < 1:
        max_transport_5xx_before_fallback = 1

    return {
        "enabled": enabled,
        "fallback_mode": fallback_mode,
        "require_anthropic_provider": bool(gate_cfg.get("require_anthropic_provider", True)),
        "require_openrouter_route": bool(gate_cfg.get("require_openrouter_route", True)),
        "require_adn_v2_enforcement": bool(gate_cfg.get("require_adn_v2_enforcement", True)),
        "require_name_order_preflight": bool(gate_cfg.get("require_name_order_preflight", True)),
        "require_cache_warm_success": bool(gate_cfg.get("require_cache_warm_success", True)),
        "context_safety_ratio": context_safety_ratio,
        "target_context_window_tokens": target_context_window_tokens,
        "estimated_system_tokens": max(0, estimated_system_tokens),
        "estimated_prequel_bundle_tokens": max(0, estimated_prequel_bundle_tokens),
        "estimated_chapter_prompt_tokens": max(0, estimated_chapter_prompt_tokens),
        "max_transport_5xx_before_fallback": max_transport_5xx_before_fallback,
        "reason_codes": dict(FULL_PREQUEL_CACHE_REASON_CODES),
    }


def evaluate_full_prequel_cache_gate(
    *,
    provider: str,
    route_enabled: bool,
    adn_v2_enabled: bool,
    name_order_preflight_passed: bool,
    context_tokens_estimate: int,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate hard gate conditions and return decision with reason code."""
    cfg = config if isinstance(config, dict) else get_full_prequel_cache_gate_config()
    fallback_mode = str(cfg.get("fallback_mode", "series_bible_rag") or "series_bible_rag")

    decision = {
        "requested": bool(cfg.get("enabled", False)),
        "allowed": False,
        "active_mode": fallback_mode,
        "fallback_mode": fallback_mode,
        "reason_code": FULL_PREQUEL_CACHE_REASON_CODES["default_rag_mode"],
        "reason": "Default route remains SeriesBibleRAG mode.",
        "context_tokens_estimate": int(context_tokens_estimate or 0),
        "context_tokens_ceiling": int(
            float(cfg.get("target_context_window_tokens", 200000) or 200000)
            * float(cfg.get("context_safety_ratio", 0.85) or 0.85)
        ),
    }

    if not decision["requested"]:
        decision["reason_code"] = FULL_PREQUEL_CACHE_REASON_CODES["disabled_by_config"]
        decision["reason"] = "Full-prequel cache is disabled in config; using fallback continuity mode."
        return decision

    normalized_provider = str(provider or "").strip().lower()
    if bool(cfg.get("require_anthropic_provider", True)) and normalized_provider != "anthropic":
        decision["reason_code"] = FULL_PREQUEL_CACHE_REASON_CODES["provider_mismatch"]
        decision["reason"] = (
            f"Provider '{normalized_provider or 'unknown'}' does not satisfy require_anthropic_provider."
        )
        return decision

    if bool(cfg.get("require_openrouter_route", True)) and not route_enabled:
        decision["reason_code"] = FULL_PREQUEL_CACHE_REASON_CODES["route_not_openrouter"]
        decision["reason"] = "OpenRouter route precondition failed for full-prequel cache mode."
        return decision

    if bool(cfg.get("require_adn_v2_enforcement", True)) and not adn_v2_enabled:
        decision["reason_code"] = FULL_PREQUEL_CACHE_REASON_CODES["adn_v2_required"]
        decision["reason"] = "ADN v2 enforcement must be enabled before full-prequel cache can activate."
        return decision

    if bool(cfg.get("require_name_order_preflight", True)) and not name_order_preflight_passed:
        decision["reason_code"] = FULL_PREQUEL_CACHE_REASON_CODES["name_order_guard_failed"]
        decision["reason"] = "Name-order/canon preflight gate failed."
        return decision

    ceiling = decision["context_tokens_ceiling"]
    estimate = decision["context_tokens_estimate"]
    if estimate > ceiling:
        decision["reason_code"] = FULL_PREQUEL_CACHE_REASON_CODES["context_budget_exceeded"]
        decision["reason"] = (
            f"Estimated context tokens {estimate} exceed safety ceiling {ceiling}."
        )
        return decision

    decision["allowed"] = True
    decision["active_mode"] = "full_prequel_cache"
    decision["reason_code"] = FULL_PREQUEL_CACHE_REASON_CODES["enabled"]
    decision["reason"] = "All hard preconditions passed; full-prequel cache mode enabled."
    return decision


def get_tool_mode_config() -> Dict[str, Any]:
    """Get translation tool-mode settings with stable defaults."""
    config = get_translation_config() or {}
    tool_mode = config.get("tool_mode", {}) if isinstance(config, dict) else {}
    if not isinstance(tool_mode, dict):
        tool_mode = {}

    tools = tool_mode.get("tools", {})
    if not isinstance(tools, dict):
        tools = {}

    configured_enabled = bool(tool_mode.get("enabled", True))
    auto_disable_switch = bool(
        tool_mode.get("auto_disable_for_batch_adaptive_thinking", True)
    )
    auto_disabled_reason = None

    provider = get_translator_provider()
    phase2_or_route = get_phase2_openrouter_route()
    anthropic_cfg = get_anthropic_config() if provider == "anthropic" else {}
    batch_cfg = anthropic_cfg.get("batch", {}) if isinstance(anthropic_cfg, dict) else {}
    thinking_cfg = (
        anthropic_cfg.get("thinking_mode", {}) if isinstance(anthropic_cfg, dict) else {}
    )
    batch_configured = isinstance(batch_cfg, dict) and bool(batch_cfg)
    adaptive_thinking = bool(thinking_cfg.get("enabled", False)) and (
        str(thinking_cfg.get("thinking_type", "adaptive")).strip().lower() == "adaptive"
    )

    enabled = configured_enabled
    if (
        configured_enabled
        and auto_disable_switch
        and provider == "anthropic"
        and not bool(phase2_or_route.get("enabled", False))
        and batch_configured
        and adaptive_thinking
    ):
        enabled = False
        auto_disabled_reason = (
            "Auto-disabled because Anthropic batch processing is configured and "
            "adaptive thinking is enabled. The current translator path treats "
            "batch and multi-turn tool mode as mutually exclusive."
        )

    return {
        "enabled": enabled,
        "configured_enabled": configured_enabled,
        "auto_disable_for_batch_adaptive_thinking": auto_disable_switch,
        "auto_disabled_reason": auto_disabled_reason,
        "force_pre_commit": bool(tool_mode.get("force_pre_commit", True)),
        "log_tool_calls": bool(tool_mode.get("log_tool_calls", True)),
        "tools": {
            "declare_translation_parameters": bool(
                tools.get("declare_translation_parameters", True)
            ),
            "validate_glossary_term": bool(
                tools.get("validate_glossary_term", True)
            ),
            "lookup_cultural_term": bool(
                tools.get("lookup_cultural_term", True)
            ),
            "report_translation_qc": bool(
                tools.get("report_translation_qc", True)
            ),
            "flag_structural_constraint": bool(
                tools.get("flag_structural_constraint", True)
            ),
        },
    }


def get_master_prompt_path(target_language: str = None) -> Path:
    """
    Get absolute path to master prompt file.

    Args:
        target_language: Language code (e.g., 'en', 'vn').
                        If None, uses current target language from config.

    Returns:
        Absolute path to the master prompt file.
    """
    if target_language is None:
        target_language = get_target_language()

    lang_config = get_language_config(target_language)
    relative_path = lang_config.get("master_prompt")

    if not relative_path:
        raise ValueError(f"Master prompt not configured for language: {target_language}")

    return PIPELINE_ROOT / relative_path


def get_modules_directory(target_language: str = None) -> Path:
    """
    Get absolute path to RAG modules directory.

    Args:
        target_language: Language code (e.g., 'en', 'vn').
                        If None, uses current target language from config.

    Returns:
        Absolute path to the modules directory.
    """
    if target_language is None:
        target_language = get_target_language()

    lang_config = get_language_config(target_language)
    relative_path = lang_config.get("modules_dir", "modules/")

    return PIPELINE_ROOT / relative_path


def get_genre_prompt_path(genre: str, target_language: str = None) -> Path:
    """
    Get path to genre-specific prompt.

    Args:
        genre: Genre key (e.g., 'romcom', 'fantasy')
        target_language: Language code. If None, uses current target language.

    Returns:
        Absolute path to the genre-specific prompt file.
    """
    if target_language is None:
        target_language = get_target_language()

    lang_config = get_language_config(target_language)
    prompts = lang_config.get("prompts", {})

    if genre not in prompts:
        # Fall back to master prompt
        return get_master_prompt_path(target_language)

    return PIPELINE_ROOT / prompts[genre]

def get_lookback_chapters() -> int:
    """Get number of chapters to include for context continuity."""
    config = get_translation_config()
    return config.get("context", {}).get("lookback_chapters", 2)

def get_quality_threshold() -> float:
    """Get minimum contraction rate threshold."""
    config = get_translation_config()
    return config.get("quality", {}).get("contraction_rate_min", 0.80)

def get_safety_settings() -> Dict[str, str]:
    """Get safety settings for Gemini."""
    gemini_conf = get_gemini_config()
    return gemini_conf.get("safety", {})

def get_model_name() -> str:
    """Get configured model name."""
    return get_gemini_config().get("model", "gemini-2.5-pro")

def get_fallback_model_name() -> str:
    """Get configured fallback model name."""
    return get_gemini_config().get("fallback_model", "gemini-2.5-flash")

def get_generation_params(phase: Optional[str] = None) -> Dict[str, Any]:
    """Get generation parameters (temperature, tokens, etc)."""
    if phase:
        return get_phase_generation_config(phase)
    return get_phase_generation_config("2.5")


def get_rate_limit_config() -> Dict[str, Any]:
    """Get rate limiting configuration."""
    gemini_conf = get_gemini_config()
    rate_limit = gemini_conf.get("rate_limit", {})
    return {
        "requests_per_minute": rate_limit.get("requests_per_minute", 10),
        "retry_attempts": rate_limit.get("retry_attempts", 3),
        "retry_delay_seconds": rate_limit.get("retry_delay_seconds", 5),
    }


def get_caching_config() -> Dict[str, Any]:
    """Get caching configuration."""
    gemini_conf = get_gemini_config()
    caching = gemini_conf.get("caching", {})
    return {
        "enabled": caching.get("enabled", True),
        "ttl_minutes": caching.get("ttl_minutes", 120),
    }


def is_name_consistency_enabled() -> bool:
    """Check if character name consistency is enforced."""
    config = get_translation_config()
    return config.get("context", {}).get("enforce_name_consistency", True)


def is_volume_context_legacy_mode() -> bool:
    """
    Return whether deprecated rolling volume context is enabled.

    When False (default), Phase 2 uses Bible pull context blocks instead of
    per-chapter summary aggregation/caching.
    """
    config = get_translation_config()
    return bool(config.get("context", {}).get("volume_context_legacy_mode", False))


def get_quality_thresholds() -> Dict[str, Any]:
    """Get quality threshold settings."""
    config = get_translation_config()
    quality = config.get("quality", {})
    return {
        "contraction_rate_min": quality.get("contraction_rate_min", 0.80),
        "max_ai_isms_per_chapter": quality.get("max_ai_isms_per_chapter", 5),
    }


def get_ai_ism_patterns() -> list:
    """Get list of AI-ism patterns to detect."""
    critics_config = get_config_section("critics")
    return critics_config.get("ai_ism_patterns", [
        "indeed", "quite", "rather", "I shall",
        "most certainly", "if you will", "as it were",
        "one might say"
    ])

"""
Configuration bridge between CLI and pipeline config.
"""

from pathlib import Path
from typing import Dict, Any, Optional, List
import yaml


class ConfigBridge:
    """Bridge between CLI settings and pipeline configuration."""

    def __init__(self, config_path: Optional[Path] = None):
        """Initialize config bridge."""
        if config_path is None:
            # Default to pipeline root config.yaml
            self.config_path = Path(__file__).parent.parent.parent.parent / "config.yaml"
        else:
            self.config_path = config_path

        self._config: Optional[Dict[str, Any]] = None

    def load(self) -> Dict[str, Any]:
        """Load configuration from file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        with open(self.config_path, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f)

        return self._config

    def save(self) -> None:
        """Save configuration to file."""
        if self._config is None:
            raise ValueError("No configuration loaded")

        with open(self.config_path, 'w', encoding='utf-8') as f:
            yaml.dump(self._config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get a configuration value using dot notation.

        Args:
            key_path: Dot-separated path (e.g., 'gemini.model')
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        if self._config is None:
            self.load()

        keys = key_path.split('.')
        value = self._config

        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default

        return value

    def set(self, key_path: str, value: Any) -> None:
        """
        Set a configuration value using dot notation.

        Args:
            key_path: Dot-separated path (e.g., 'gemini.model')
            value: Value to set
        """
        if self._config is None:
            self.load()

        keys = key_path.split('.')
        target = self._config

        for key in keys[:-1]:
            if key not in target:
                target[key] = {}
            target = target[key]

        target[keys[-1]] = value

    # Convenience properties
    @property
    def target_language(self) -> str:
        """Get current target language."""
        return self.get('project.target_language', 'en')

    @target_language.setter
    def target_language(self, value: str) -> None:
        """Set target language."""
        self.set('project.target_language', value)

    @property
    def translator_provider(self) -> str:
        """Get active translator provider."""
        return str(self.get('translator_provider', 'anthropic')).strip().lower()

    @translator_provider.setter
    def translator_provider(self, value: str) -> None:
        """Set active translator provider."""
        self.set('translator_provider', str(value).strip().lower())

    @property
    def gemini_model(self) -> str:
        """Get configured Gemini model."""
        return self.get('gemini.model', 'gemini-2.5-flash')

    @gemini_model.setter
    def gemini_model(self, value: str) -> None:
        """Set Gemini model."""
        self.set('gemini.model', value)

    @property
    def anthropic_model(self) -> str:
        """Get configured Anthropic model."""
        return self.get('anthropic.model', 'claude-sonnet-4-6')

    @anthropic_model.setter
    def anthropic_model(self, value: str) -> None:
        """Set Anthropic model."""
        self.set('anthropic.model', value)

    @property
    def active_model(self) -> str:
        """Get active model by provider."""
        if self.translator_provider == 'anthropic':
            return self.anthropic_model
        return self.gemini_model

    @property
    def model(self) -> str:
        """Backward-compatible active model accessor."""
        return self.active_model

    @model.setter
    def model(self, value: str) -> None:
        """Set active provider model."""
        if self.translator_provider == 'anthropic':
            self.anthropic_model = value
        else:
            self.gemini_model = value

    @property
    def caching_enabled(self) -> bool:
        """Check if context caching is enabled for active provider."""
        if self.translator_provider == 'anthropic':
            return bool(self.get('anthropic.caching.enabled', True))
        return bool(self.get('gemini.caching.enabled', True))

    @caching_enabled.setter
    def caching_enabled(self, value: bool) -> None:
        """Set caching enabled status for active provider."""
        if self.translator_provider == 'anthropic':
            self.set('anthropic.caching.enabled', bool(value))
        else:
            self.set('gemini.caching.enabled', bool(value))

    @property
    def cache_ttl(self) -> int:
        """Get cache TTL in minutes for active provider."""
        if self.translator_provider == 'anthropic':
            return int(self.get('anthropic.caching.ttl_minutes', 5))
        return int(self.get('gemini.caching.ttl_minutes', 120))

    @cache_ttl.setter
    def cache_ttl(self, value: int) -> None:
        """Set cache TTL for active provider."""
        if self.translator_provider == 'anthropic':
            self.set('anthropic.caching.ttl_minutes', int(value))
        else:
            self.set('gemini.caching.ttl_minutes', int(value))

    @property
    def temperature(self) -> float:
        """Get generation temperature for active provider."""
        if self.translator_provider == 'anthropic':
            return float(self.get('anthropic.generation.temperature', 1.0))
        return float(self.get('gemini.generation.temperature', 0.6))

    @temperature.setter
    def temperature(self, value: float) -> None:
        """Set generation temperature for active provider."""
        if self.translator_provider == 'anthropic':
            self.set('anthropic.generation.temperature', float(value))
        else:
            self.set('gemini.generation.temperature', float(value))

    @property
    def top_p(self) -> float:
        """Get top-p value (Gemini only)."""
        return float(self.get('gemini.generation.top_p', 0.95))

    @top_p.setter
    def top_p(self, value: float) -> None:
        """Set top-p value (Gemini only)."""
        self.set('gemini.generation.top_p', float(value))

    @property
    def top_k(self) -> int:
        """Get top-k value (Gemini only)."""
        return int(self.get('gemini.generation.top_k', 40))

    @top_k.setter
    def top_k(self, value: int) -> None:
        """Set top-k value (Gemini only)."""
        self.set('gemini.generation.top_k', int(value))

    @property
    def max_output_tokens(self) -> int:
        """Get max output tokens for active provider."""
        if self.translator_provider == 'anthropic':
            return int(self.get('anthropic.generation.max_output_tokens', 128000))
        return int(self.get('gemini.generation.max_output_tokens', 65535))

    @max_output_tokens.setter
    def max_output_tokens(self, value: int) -> None:
        """Set max output tokens for active provider."""
        if self.translator_provider == 'anthropic':
            self.set('anthropic.generation.max_output_tokens', int(value))
        else:
            self.set('gemini.generation.max_output_tokens', int(value))

    @property
    def anthropic_thinking_enabled(self) -> bool:
        """Get Anthropic thinking mode enabled state."""
        return bool(self.get('anthropic.thinking_mode.enabled', True))

    @anthropic_thinking_enabled.setter
    def anthropic_thinking_enabled(self, value: bool) -> None:
        """Set Anthropic thinking mode enabled state."""
        self.set('anthropic.thinking_mode.enabled', bool(value))

    @property
    def anthropic_thinking_type(self) -> str:
        """Get Anthropic thinking type."""
        return str(self.get('anthropic.thinking_mode.thinking_type', 'adaptive'))

    @anthropic_thinking_type.setter
    def anthropic_thinking_type(self, value: str) -> None:
        """Set Anthropic thinking type."""
        self.set('anthropic.thinking_mode.thinking_type', str(value))

    @property
    def anthropic_batch_promote_ttl_1h(self) -> bool:
        """Get Anthropic batch cache promotion toggle."""
        return bool(self.get('anthropic.batch.promote_cache_ttl_1h', True))

    @anthropic_batch_promote_ttl_1h.setter
    def anthropic_batch_promote_ttl_1h(self, value: bool) -> None:
        """Set Anthropic batch cache promotion toggle."""
        self.set('anthropic.batch.promote_cache_ttl_1h', bool(value))

    @property
    def anthropic_cache_shared_brief(self) -> bool:
        """Get Anthropic shared brief cache toggle."""
        return bool(self.get('anthropic.batch.cache_shared_brief', True))

    @anthropic_cache_shared_brief.setter
    def anthropic_cache_shared_brief(self, value: bool) -> None:
        """Set Anthropic shared brief cache toggle."""
        self.set('anthropic.batch.cache_shared_brief', bool(value))

    @property
    def pre_toc_enabled(self) -> bool:
        """Check if pre-TOC detection is enabled."""
        return bool(self.get('pre_toc_detection.enabled', False))

    @pre_toc_enabled.setter
    def pre_toc_enabled(self, value: bool) -> None:
        """Set pre-TOC detection enabled status."""
        self.set('pre_toc_detection.enabled', bool(value))

    @property
    def verbose_mode(self) -> bool:
        """Check if verbose mode is enabled by default."""
        return bool(self.get('cli.verbose_mode', True))

    @verbose_mode.setter
    def verbose_mode(self, value: bool) -> None:
        """Set default verbose mode."""
        self.set('cli.verbose_mode', bool(value))

    @property
    def debug_mode(self) -> bool:
        """Check if debug mode is enabled."""
        return bool(self.get('debug.verbose_api', False))

    @debug_mode.setter
    def debug_mode(self, value: bool) -> None:
        """Set debug mode."""
        self.set('debug.verbose_api', bool(value))

    @property
    def translator_project_debug_log(self) -> bool:
        """Check if translator debug logs should be saved in project folder."""
        return bool(self.get('translation.debug_log_to_project', True))

    @translator_project_debug_log.setter
    def translator_project_debug_log(self, value: bool) -> None:
        """Set translator debug project logging toggle."""
        self.set('translation.debug_log_to_project', bool(value))

    @property
    def phase25_auto_update_enabled(self) -> bool:
        """Check if Phase 2.5 auto-run is enabled after successful Phase 2."""
        return bool(self.get('translation.phase_2_5.run_bible_update', False))

    @phase25_auto_update_enabled.setter
    def phase25_auto_update_enabled(self, value: bool) -> None:
        """Enable/disable automatic Phase 2.5 runs."""
        self.set('translation.phase_2_5.run_bible_update', bool(value))

    @property
    def phase25_qc_cleared(self) -> bool:
        """Check default QC gate for Phase 2.5."""
        return bool(self.get('translation.phase_2_5.qc_cleared', False))

    @phase25_qc_cleared.setter
    def phase25_qc_cleared(self, value: bool) -> None:
        """Set default QC gate for Phase 2.5."""
        self.set('translation.phase_2_5.qc_cleared', bool(value))

    @property
    def multimodal_processor_enabled(self) -> bool:
        """
        Check if multimodal processing is enabled by default.

        Uses both the global multimodal gate and translation default.
        """
        translation_enabled = bool(self.get('translation.enable_multimodal', False))
        multimodal_enabled = bool(self.get('multimodal.enabled', True))
        return translation_enabled and multimodal_enabled

    @multimodal_processor_enabled.setter
    def multimodal_processor_enabled(self, value: bool) -> None:
        """Enable/disable multimodal processor defaults in config."""
        self.set('translation.enable_multimodal', bool(value))
        self.set('multimodal.enabled', bool(value))

    @property
    def smart_chunking_enabled(self) -> bool:
        """Check if smart chunking for massive chapters is enabled."""
        return bool(self.get('translation.massive_chapter.enable_smart_chunking', True))

    @smart_chunking_enabled.setter
    def smart_chunking_enabled(self, value: bool) -> None:
        """Enable/disable smart chunking for massive chapters."""
        self.set('translation.massive_chapter.enable_smart_chunking', bool(value))

    def get_available_languages(self) -> List[str]:
        """Get list of available target languages."""
        languages = self.get('project.languages', {})
        return list(languages.keys())

    def get_language_config(self, lang_code: str) -> Dict[str, Any]:
        """Get configuration for a specific language."""
        return self.get(f'project.languages.{lang_code}', {})

    def get_available_models(self) -> List[Dict[str, str]]:
        """Get list of available models for the active provider."""
        if self.translator_provider == 'anthropic':
            return [
                {'value': 'claude-opus-4-6', 'label': 'claude-opus-4-6', 'desc': 'Highest quality, adaptive thinking'},
                {'value': 'claude-sonnet-4-6', 'label': 'claude-sonnet-4-6', 'desc': 'Fast, cost-efficient'},
                {'value': 'claude-haiku-4-5-20251001', 'label': 'claude-haiku-4-5', 'desc': 'Lightweight fallback'},
            ]
        return [
            {'value': 'gemini-3.1-pro-preview', 'label': 'gemini-3.1-pro-preview', 'desc': 'High quality, newer stack'},
            {'value': 'gemini-2.5-pro', 'label': 'gemini-2.5-pro', 'desc': 'Best quality, slower'},
            {'value': 'gemini-2.5-flash', 'label': 'gemini-2.5-flash', 'desc': 'Balanced, recommended'},
            {'value': 'gemini-2.0-flash', 'label': 'gemini-2.0-flash', 'desc': 'Legacy, no caching'},
        ]

    def get_runtime_summary(self) -> Dict[str, Any]:
        """Get compact runtime summary for dashboard cards."""
        proxy_provider = str(self.get('proxy.inference.provider', '') or '').strip().lower()
        openrouter_selected = proxy_provider == 'openrouter'
        openrouter_base = str(self.get('proxy.inference.base_url', 'https://openrouter.ai/api/v1') or '').strip().rstrip('/')
        openrouter_endpoint = openrouter_base if openrouter_selected else "https://api.anthropic.com"
        openrouter_api_key_env = str(
            self.get('proxy.inference.api_key_env', 'OPENROUTER_API_KEY')
            if openrouter_selected
            else self.get('anthropic.api_key_env', 'ANTHROPIC_API_KEY')
        )

        model_name = str(self.active_model or '').strip().lower()
        is_opus = 'opus' in model_name
        opus_1m_confirmed = bool(self.get('proxy.capability_gates.claude_opus_1m_confirmed', False))
        if not opus_1m_confirmed:
            opus_1m_confirmed = bool(self.get('proxy.capability_gates.claude_opus_1m_support', False))
        phase156_hard_disabled = bool(openrouter_selected and is_opus and opus_1m_confirmed)

        full_prequel_enabled = bool(self.get('translation.full_prequel_cache_gate.enabled', False))
        full_prequel_ratio = float(self.get('translation.full_prequel_cache_gate.context_safety_ratio', 0.85) or 0.85)
        full_prequel_window = int(self.get('translation.full_prequel_cache_gate.target_context_window_tokens', 200000) or 200000)
        full_prequel_budget = int(full_prequel_ratio * full_prequel_window)

        return {
            'provider': self.translator_provider,
            'model': self.active_model,
            'cache_enabled': self.caching_enabled,
            'cache_ttl': self.cache_ttl,
            'thinking': self.anthropic_thinking_enabled if self.translator_provider == 'anthropic' else bool(self.get('gemini.thinking_mode.enabled', True)),
            'thinking_type': self.anthropic_thinking_type if self.translator_provider == 'anthropic' else str(self.get('gemini.thinking_mode.thinking_level', 'medium')),
            'max_output_tokens': self.max_output_tokens,
            'multimodal': self.multimodal_processor_enabled,
            'smart_chunking': self.smart_chunking_enabled,
            'project_debug_log': self.translator_project_debug_log,
            'batch_promote_ttl_1h': self.anthropic_batch_promote_ttl_1h,
            'phase25_auto_update': self.phase25_auto_update_enabled,
            'phase25_qc_cleared': self.phase25_qc_cleared,
            'openrouter_selected': openrouter_selected,
            'openrouter_endpoint': openrouter_endpoint,
            'openrouter_api_key_env': openrouter_api_key_env,
            'opus_1m_confirmed': opus_1m_confirmed,
            'phase156_hard_disabled': phase156_hard_disabled,
            'full_prequel_gate_enabled': full_prequel_enabled,
            'full_prequel_budget_tokens': full_prequel_budget,
            'full_prequel_window_tokens': full_prequel_window,
            'full_prequel_ratio': full_prequel_ratio,
        }

"""
Pipeline Base Configuration - Language-Agnostic Core Settings.

This module provides core configuration that is shared across all pipeline agents.
Language-specific settings should be loaded from config.yaml or manifest.json.
"""

from pathlib import Path
from typing import Dict, Any, Optional
import yaml

# Load environment variables from .env file at module import time
from dotenv import load_dotenv

# ============================================================================
# BASE PATHS
# ============================================================================

PIPELINE_ROOT = Path(__file__).parent.parent.resolve()

# Load .env file from pipeline root (if it exists)
_env_path = PIPELINE_ROOT / ".env"
load_dotenv(_env_path)
PIPELINE_DIR = Path(__file__).parent.resolve()

# Standard directories
INPUT_DIR = PIPELINE_ROOT / "INPUT"
WORK_DIR = PIPELINE_ROOT / "WORK"
OUTPUT_DIR = PIPELINE_ROOT / "OUTPUT"
PROMPTS_DIR = PIPELINE_ROOT / "prompts"
MODULES_DIR = PIPELINE_ROOT / "modules"
TEMPLATES_DIR = PIPELINE_ROOT / "templates"

# Ensure directories exist
for dir_path in [INPUT_DIR, WORK_DIR, OUTPUT_DIR]:
    dir_path.mkdir(exist_ok=True)


# ============================================================================
# CONFIGURATION LOADER
# ============================================================================

_config_cache: Optional[Dict[str, Any]] = None


def load_config() -> Dict[str, Any]:
    """
    Load configuration from config.yaml.

    Returns:
        Dictionary containing all configuration settings.
    """
    global _config_cache

    if _config_cache is not None:
        return _config_cache

    config_path = PIPELINE_ROOT / "config.yaml"

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, 'r', encoding='utf-8') as f:
        _config_cache = yaml.safe_load(f)

    return _config_cache


def get_config_section(section: str) -> Dict[str, Any]:
    """
    Get a specific section from the configuration.

    Args:
        section: Configuration section name (e.g., 'gemini', 'translation', 'builder')

    Returns:
        Dictionary containing section configuration.
    """
    config = load_config()
    return config.get(section, {})


def get_phase_model(phase: str, fallback: str) -> str:
    """
    Get the Gemini model configured for a specific pipeline phase.

    Reads from ``translation.phase_models.<phase_key>`` in config.yaml, where
    phase_key is the phase string with dots replaced by underscores
    (e.g. "1.55" → "1_55").  Falls back to *fallback* if the config is missing
    or the key is not set.

    Args:
        phase:    Pipeline phase identifier (e.g. "1", "1.5", "1.55", "1.7").
        fallback: Default model name used when the config key is absent.

    Returns:
        Model name string.
    """
    try:
        phase_key = phase.replace(".", "_")
        translation_cfg = get_config_section("translation")
        phase_models = translation_cfg.get("phase_models", {})
        entry = phase_models.get(phase_key) or phase_models.get(phase)
        if isinstance(entry, dict):
            model = entry.get("model")
        else:
            model = entry
        return str(model).strip() if model else fallback
    except Exception:
        return fallback


def get_phase_generation_config(phase: str) -> Dict[str, Any]:
    """
    Get generation settings for a specific pipeline phase.

    Resolution order:
    1) translation.phase_models.<phase>.{temperature, top_p, top_k, max_output_tokens, thinking_budget}
    2) translation.phase_generation_defaults
    3) gemini.generation + gemini.thinking_mode.thinking_budget
    4) anthropic.generation + anthropic.thinking_mode.thinking_budget
    5) hard-safe defaults
    """
    phase_key = phase.replace(".", "_")
    translation_cfg = get_config_section("translation") or {}
    phase_models = translation_cfg.get("phase_models", {}) if isinstance(translation_cfg, dict) else {}
    phase_entry = phase_models.get(phase_key) or phase_models.get(phase)
    if not isinstance(phase_entry, dict):
        phase_entry = {}

    phase_defaults = translation_cfg.get("phase_generation_defaults", {}) if isinstance(translation_cfg, dict) else {}
    if not isinstance(phase_defaults, dict):
        phase_defaults = {}

    gemini_cfg = get_config_section("gemini") or {}
    anthropic_cfg = get_config_section("anthropic") or {}
    gemini_gen = gemini_cfg.get("generation", {}) if isinstance(gemini_cfg, dict) else {}
    anthropic_gen = anthropic_cfg.get("generation", {}) if isinstance(anthropic_cfg, dict) else {}
    gemini_thinking = gemini_cfg.get("thinking_mode", {}) if isinstance(gemini_cfg, dict) else {}
    anthropic_thinking = anthropic_cfg.get("thinking_mode", {}) if isinstance(anthropic_cfg, dict) else {}

    def _pick(name: str, fallback: Any) -> Any:
        if name in phase_entry and phase_entry.get(name) is not None:
            return phase_entry.get(name)
        if name in phase_defaults and phase_defaults.get(name) is not None:
            return phase_defaults.get(name)
        if name in gemini_gen and gemini_gen.get(name) is not None:
            return gemini_gen.get(name)
        if name in anthropic_gen and anthropic_gen.get(name) is not None:
            return anthropic_gen.get(name)
        if name == "thinking_budget":
            if isinstance(gemini_thinking, dict) and gemini_thinking.get("thinking_budget") is not None:
                return gemini_thinking.get("thinking_budget")
            if isinstance(anthropic_thinking, dict) and anthropic_thinking.get("thinking_budget") is not None:
                return anthropic_thinking.get("thinking_budget")
        return fallback

    return {
        "temperature": float(_pick("temperature", 1.0)),
        "top_p": float(_pick("top_p", 0.95)),
        "top_k": int(_pick("top_k", 40)),
        "max_output_tokens": int(_pick("max_output_tokens", 65535)),
        "thinking_budget": int(_pick("thinking_budget", -1)),
    }


def _deep_merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Return a deep-merged copy where override keys replace base keys."""
    merged = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def get_eps_calibration_config(series_id: str | None = None) -> Dict[str, Any]:
    """
    Resolve EPS calibration config with optional per-series overrides.

    Reads from:
      translation.eps_calibration

    Structure:
      translation:
        eps_calibration:
          ...default settings...
          series_overrides:
            <series_id>:
              ...override settings...
    """
    translation_cfg = get_config_section("translation")
    eps_cfg = translation_cfg.get("eps_calibration", {}) if isinstance(translation_cfg, dict) else {}
    if not isinstance(eps_cfg, dict):
        return {}

    base_cfg = {k: v for k, v in eps_cfg.items() if k != "series_overrides"}
    series_overrides = eps_cfg.get("series_overrides", {})
    if not isinstance(series_overrides, dict):
        return base_cfg

    sid = str(series_id or "").strip()
    if not sid:
        return base_cfg

    override = series_overrides.get(sid, {})
    if not isinstance(override, dict):
        return base_cfg

    return _deep_merge_dict(base_cfg, override)


def get_eps_signal_extraction_config(series_id: str | None = None) -> Dict[str, Any]:
    """
    Resolve deterministic EPS signal extraction config with per-series overrides.

    Reads from:
      translation.eps_signal_extraction
    """
    translation_cfg = get_config_section("translation")
    extraction_cfg = translation_cfg.get("eps_signal_extraction", {}) if isinstance(translation_cfg, dict) else {}
    if not isinstance(extraction_cfg, dict):
        return {}

    base_cfg = {k: v for k, v in extraction_cfg.items() if k != "series_overrides"}
    series_overrides = extraction_cfg.get("series_overrides", {})
    if not isinstance(series_overrides, dict):
        return base_cfg

    sid = str(series_id or "").strip()
    if not sid:
        return base_cfg

    override = series_overrides.get(sid, {})
    if not isinstance(override, dict):
        return base_cfg

    return _deep_merge_dict(base_cfg, override)


# ============================================================================
# EPUB FORMAT CONSTANTS (Language-Agnostic)
# ============================================================================

# EPUB structure constants
EPUB_MIMETYPE = "application/epub+zip"
EPUB_CONTAINER_PATH = "META-INF/container.xml"

# Common content directories in EPUBs
EPUB_CONTENT_DIRS = ["OEBPS", "OPS", "EPUB", "item", "content"]

# Image file extensions
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg'}

# XHTML file extension
XHTML_EXTENSION = '.xhtml'


# ============================================================================
# CONTENT PROCESSING CONSTANTS
# ============================================================================

# Scene break marker (universal)
SCENE_BREAK_MARKER = "* * *"

# Illustration placeholder patterns
# Legacy format: [ILLUSTRATION: filename]
ILLUSTRATION_PLACEHOLDER_PATTERN = r'\[ILLUSTRATION:?\s*"?([^"\]]+)"?\]'
# Standard markdown format: ![alt](filename) where alt can be 'illustration', 'gaiji', or empty
MARKDOWN_IMAGE_PATTERN = r'!\[(illustration|gaiji|)\]\(([^)]+)\)'

# Ruby tag removal (for CJK languages)
REMOVE_RUBY_TAGS = True


# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

def get_log_level() -> str:
    """Get logging level from configuration."""
    config = load_config()
    return config.get('logging', {}).get('level', 'INFO')


def get_log_format() -> str:
    """Get logging format from configuration."""
    config = load_config()
    return config.get('logging', {}).get(
        'format',
        '[%(levelname)s] %(asctime)s - %(name)s - %(message)s'
    )


# ============================================================================
# DEBUG FLAGS
# ============================================================================

def is_debug_mode() -> bool:
    """Check if debug mode is enabled."""
    config = load_config()
    return config.get('debug', {}).get('verbose_api', False)


def is_dry_run() -> bool:
    """Check if dry run mode is enabled."""
    config = load_config()
    return config.get('debug', {}).get('dry_run', False)


# ============================================================================
# PROJECT / LANGUAGE CONFIGURATION
# ============================================================================

def get_project_config() -> Dict[str, Any]:
    """
    Get project-level configuration including language settings.

    Returns:
        Dictionary containing project configuration with target_language and languages.
    """
    config = load_config()
    return config.get('project', {
        'target_language': 'en',
        'languages': {
            'en': {
                'master_prompt': 'prompts/master_prompt_en_compressed.xml',
                'modules_dir': 'modules/',
                'output_suffix': '_EN',
                'language_code': 'en',
                'language_name': 'English'
            }
        }
    })


def get_target_language() -> str:
    """
    Get the current target language from configuration.

    Returns:
        Language code (e.g., 'en', 'vn')
    """
    project = get_project_config()
    return project.get('target_language', 'en')


def get_language_config(target_language: str = None) -> Dict[str, Any]:
    """
    Get language-specific configuration.

    Args:
        target_language: Language code (e.g., 'en', 'vn').
                        If None, uses current target language from config.

    Returns:
        Dictionary containing language-specific settings.

    Raises:
        ValueError: If the specified language is not configured.
    """
    if target_language is None:
        target_language = get_target_language()

    project = get_project_config()
    languages = project.get('languages', {})

    if target_language not in languages:
        available = list(languages.keys())
        raise ValueError(
            f"Language '{target_language}' not configured. "
            f"Available languages: {available}"
        )

    return languages[target_language]


def get_available_languages() -> list:
    """
    Get list of available target languages.

    Returns:
        List of language codes (e.g., ['en', 'vn'])
    """
    project = get_project_config()
    return list(project.get('languages', {}).keys())


def set_target_language(language: str) -> None:
    """
    Set the target language in config.yaml.

    Args:
        language: Language code to set (e.g., 'en', 'vn')

    Raises:
        ValueError: If the language is not available.
    """
    available = get_available_languages()
    if language not in available:
        raise ValueError(
            f"Language '{language}' not available. "
            f"Available languages: {available}"
        )

    config_path = PIPELINE_ROOT / "config.yaml"

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    config['project']['target_language'] = language

    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # Clear cache so next load picks up new value
    global _config_cache
    _config_cache = None


def validate_language_setup(target_language: str = None) -> tuple:
    """
    Validate that language resources exist.

    Args:
        target_language: Language to validate. If None, uses current target.

    Returns:
        Tuple of (is_valid: bool, issues: list[str])
    """
    if target_language is None:
        target_language = get_target_language()

    try:
        lang_config = get_language_config(target_language)
    except ValueError as e:
        return False, [str(e)]

    issues = []

    # Check master prompt
    master_prompt_path = PIPELINE_ROOT / lang_config.get('master_prompt', '')
    if not master_prompt_path.exists():
        issues.append(f"Master prompt not found: {master_prompt_path}")

    # Check modules directory
    modules_dir = PIPELINE_ROOT / lang_config.get('modules_dir', '')
    if not modules_dir.exists():
        issues.append(f"Modules directory not found: {modules_dir}")
    elif not any(modules_dir.glob('*.md')):
        issues.append(f"No .md modules found in: {modules_dir}")

    # Check genre-specific prompts
    prompts = lang_config.get('prompts', {})
    for genre, prompt_path in prompts.items():
        full_path = PIPELINE_ROOT / prompt_path
        if not full_path.exists():
            issues.append(f"Genre prompt '{genre}' not found: {full_path}")

    return len(issues) == 0, issues

"""
Settings panel component for the CLI TUI.
"""

from typing import Dict, Any, Optional, List
from pathlib import Path
import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from ..components.styles import custom_style
from ..utils.config_bridge import ConfigBridge
from ..utils.cache_manager import purge_all_caches

console = Console()


def settings_panel(config: ConfigBridge) -> Optional[Dict[str, Any]]:
    """
    Display interactive settings panel.

    Args:
        config: Configuration bridge instance

    Returns:
        Dictionary of updated settings, or None if cancelled
    """
    console.print()
    console.print(Panel(
        "[bold]Settings[/bold]\n"
        "[dim]Use arrow keys to navigate, Space to toggle, Enter to confirm[/dim]",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()

    while True:
        action = questionary.select(
            "Settings category:",
            choices=[
                questionary.Choice("Translation Settings", value="translation"),
                questionary.Choice("Model & Parameters", value="model"),
                questionary.Choice("Performance", value="performance"),
                questionary.Choice("Advanced", value="advanced"),
                questionary.Separator(),
                questionary.Choice("Clear All Caches", value="clear_cache"),
                questionary.Separator(),
                questionary.Choice("Save & Exit", value="save"),
                questionary.Choice("Discard Changes", value="cancel"),
            ],
            style=custom_style,
        ).ask()

        if action == "translation":
            _translation_settings(config)
        elif action == "model":
            _model_settings(config)
        elif action == "performance":
            _performance_settings(config)
        elif action == "advanced":
            _advanced_settings(config)
        elif action == "clear_cache":
            _clear_cache_menu(config)
        elif action == "save":
            config.save()
            console.print("[green]✓ Settings saved[/green]")
            return {"saved": True}
        elif action == "cancel" or action is None:
            return None


def _translation_settings(config: ConfigBridge) -> None:
    """Handle translation settings submenu."""
    console.print("\n[bold cyan]Translation Settings[/bold cyan]\n")

    # Language selection
    available_langs = config.get_available_languages()
    lang_choices = []

    for lang in available_langs:
        lang_config = config.get_language_config(lang)
        lang_name = lang_config.get('language_name', lang.upper())
        is_current = lang == config.target_language
        label = f"{lang_name} ({lang.upper()})"
        if is_current:
            label += " (Current)"
        lang_choices.append(questionary.Choice(label, value=lang))

    selected_lang = questionary.select(
        "Target Language:",
        choices=lang_choices,
        default=config.target_language,
        style=custom_style,
    ).ask()

    if selected_lang and selected_lang != config.target_language:
        config.target_language = selected_lang
        lang_config = config.get_language_config(selected_lang)
        console.print(f"[green]✓ Language changed to {lang_config.get('language_name', selected_lang)}[/green]")

    # Multimodal processor default switch
    toggle_multimodal = questionary.confirm(
        f"Enable Multimodal Processor by default? (currently {'ON' if config.multimodal_processor_enabled else 'OFF'})",
        default=config.multimodal_processor_enabled,
        style=custom_style,
    ).ask()

    if toggle_multimodal != config.multimodal_processor_enabled:
        config.multimodal_processor_enabled = bool(toggle_multimodal)
        status = "enabled" if toggle_multimodal else "disabled"
        console.print(f"[green]✓ Multimodal processor {status}[/green]")


def _model_settings(config: ConfigBridge) -> None:
    """Handle model and parameters settings submenu."""
    console.print("\n[bold cyan]Model & Parameters[/bold cyan]\n")

    # Model selection
    models = config.get_available_models()
    model_choices = []

    for m in models:
        is_current = m['value'] == config.model
        label = f"{m['label']} - {m['desc']}"
        if is_current:
            label += " (Current)"
        model_choices.append(questionary.Choice(label, value=m['value']))

    selected_model = questionary.select(
        "Translation Model:",
        choices=model_choices,
        default=config.model,
        style=custom_style,
    ).ask()

    if selected_model and selected_model != config.model:
        config.model = selected_model
        console.print(f"[green]✓ Model changed to {selected_model}[/green]")

    # Generation parameters
    console.print("\n[bold]Generation Parameters:[/bold]")

    # Temperature
    current_temp = config.temperature
    new_temp = questionary.text(
        f"Temperature (current: {current_temp}, range: 0.0-2.0):",
        default=str(current_temp),
        validate=lambda x: _validate_float(x, 0.0, 2.0),
        style=custom_style,
    ).ask()

    if new_temp:
        config.temperature = float(new_temp)

    # Top-P
    current_top_p = config.top_p
    new_top_p = questionary.text(
        f"Top-P (current: {current_top_p}, range: 0.0-1.0):",
        default=str(current_top_p),
        validate=lambda x: _validate_float(x, 0.0, 1.0),
        style=custom_style,
    ).ask()

    if new_top_p:
        config.top_p = float(new_top_p)

    # Top-K
    current_top_k = config.top_k
    new_top_k = questionary.text(
        f"Top-K (current: {current_top_k}, range: 1-100):",
        default=str(current_top_k),
        validate=lambda x: _validate_int(x, 1, 100),
        style=custom_style,
    ).ask()

    if new_top_k:
        config.top_k = int(new_top_k)


def _performance_settings(config: ConfigBridge) -> None:
    """Handle performance settings submenu."""
    console.print("\n[bold cyan]Performance Settings[/bold cyan]\n")

    # Build current options list
    options = [
        questionary.Choice(
            f"Context Caching {'[ON]' if config.caching_enabled else '[OFF]'}",
            value="caching",
            checked=config.caching_enabled,
        ),
    ]

    # Show current cache TTL
    if config.caching_enabled:
        console.print(f"  [dim]Cache TTL: {config.cache_ttl} minutes[/dim]")

    # Toggle caching
    toggle_caching = questionary.confirm(
        f"Enable Context Caching? (currently {'ON' if config.caching_enabled else 'OFF'})",
        default=config.caching_enabled,
        style=custom_style,
    ).ask()

    if toggle_caching != config.caching_enabled:
        config.caching_enabled = toggle_caching
        status = "enabled" if toggle_caching else "disabled"
        console.print(f"[green]✓ Context caching {status}[/green]")

    # Cache TTL (only if caching is enabled)
    if config.caching_enabled:
        current_ttl = config.cache_ttl
        new_ttl = questionary.text(
            f"Cache TTL in minutes (current: {current_ttl}):",
            default=str(current_ttl),
            validate=lambda x: _validate_int(x, 1, 120),
            style=custom_style,
        ).ask()

        if new_ttl:
            config.cache_ttl = int(new_ttl)

    # Smart Chunking toggle
    toggle_chunking = questionary.confirm(
        f"Enable Smart Chunking for massive chapters? (currently {'ON' if config.smart_chunking_enabled else 'OFF'})",
        default=config.smart_chunking_enabled,
        style=custom_style,
    ).ask()

    if toggle_chunking != config.smart_chunking_enabled:
        config.smart_chunking_enabled = bool(toggle_chunking)
        status = "enabled" if toggle_chunking else "disabled"
        console.print(f"[green]✓ Smart chunking {status}[/green]")


def _advanced_settings(config: ConfigBridge) -> None:
    """Handle advanced settings submenu."""
    console.print("\n[bold cyan]Advanced Settings[/bold cyan]\n")

    # Pre-TOC Detection
    toggle_pre_toc = questionary.confirm(
        f"Enable Pre-TOC Detection? (currently {'ON' if config.pre_toc_enabled else 'OFF'})",
        default=config.pre_toc_enabled,
        style=custom_style,
    ).ask()

    if toggle_pre_toc != config.pre_toc_enabled:
        config.pre_toc_enabled = toggle_pre_toc
        status = "enabled" if toggle_pre_toc else "disabled"
        console.print(f"[green]✓ Pre-TOC detection {status}[/green]")

    # Debug Mode
    toggle_debug = questionary.confirm(
        f"Enable Debug Mode? (currently {'ON' if config.debug_mode else 'OFF'})",
        default=config.debug_mode,
        style=custom_style,
    ).ask()

    if toggle_debug != config.debug_mode:
        config.debug_mode = toggle_debug
        status = "enabled" if toggle_debug else "disabled"
        console.print(f"[green]✓ Debug mode {status}[/green]")

    # Verbose Mode Default
    toggle_verbose = questionary.confirm(
        f"Default to Verbose Mode? (currently {'ON' if config.verbose_mode else 'OFF'})",
        default=config.verbose_mode,
        style=custom_style,
    ).ask()

    if toggle_verbose != config.verbose_mode:
        config.verbose_mode = toggle_verbose
        status = "enabled" if toggle_verbose else "disabled"
        console.print(f"[green]✓ Default verbose mode {status}[/green]")



def runtime_profile_panel(config: ConfigBridge) -> bool:
    """Interactive runtime profile editor (Phase A)."""
    changed = False

    while True:
        summary = config.get_runtime_summary()
        provider = str(summary.get('provider', 'anthropic')).upper()

        console.print()
        console.print(Panel(
            "[bold]Runtime Profile (Phase A)[/bold]\n"
            f"[dim]Provider:[/dim] {provider}  |  "
            f"[dim]Model:[/dim] {summary.get('model')}  |  "
            f"[dim]Cache:[/dim] {'ON' if summary.get('cache_enabled') else 'OFF'} ({summary.get('cache_ttl')}m)\n"
            f"[dim]Thinking:[/dim] {summary.get('thinking_type')} ({'ON' if summary.get('thinking') else 'OFF'})  |  "
            f"[dim]Max Out:[/dim] {summary.get('max_output_tokens')}  |  "
            f"[dim]Project Debug Log:[/dim] {'ON' if summary.get('project_debug_log') else 'OFF'}\n"
            f"[dim]OpenRouter Route:[/dim] {'RUN' if summary.get('openrouter_selected') else 'OFF'}  |  "
            f"[dim]Endpoint:[/dim] {summary.get('openrouter_endpoint')}  |  "
            f"[dim]ApiKeyEnv:[/dim] {summary.get('openrouter_api_key_env')}\n"
            f"[dim]OpenRouter Gates:[/dim] Opus1MConfirmed={'ON' if summary.get('opus_1m_confirmed') else 'OFF'}  |  "
            f"[dim]Phase1.56:[/dim] {'HARD-DISABLED' if summary.get('phase156_hard_disabled') else 'ENABLED'}\n"
            f"[dim]Full Prequel Gate:[/dim] {'ON' if summary.get('full_prequel_gate_enabled') else 'OFF'}  |  "
            f"[dim]Budget:[/dim] {summary.get('full_prequel_budget_tokens')}/{summary.get('full_prequel_window_tokens')} ({int(float(summary.get('full_prequel_ratio', 0.85) or 0.85) * 100)}%)",
            border_style='magenta',
            padding=(1, 2),
        ))

        action = questionary.select(
            'Runtime profile action:',
            choices=[
                questionary.Choice('Switch Provider', value='provider'),
                questionary.Choice('Set Active Model', value='model'),
                questionary.Choice('Toggle Caching', value='cache_toggle'),
                questionary.Choice('Set Cache TTL', value='cache_ttl'),
                questionary.Choice('Set Max Output Tokens', value='max_out'),
                questionary.Choice('Toggle Thinking', value='thinking_toggle'),
                questionary.Choice('Set Thinking Type', value='thinking_type'),
                questionary.Choice('Toggle Multimodal Default', value='multimodal'),
                questionary.Choice('Toggle Smart Chunking', value='chunking'),
                questionary.Choice('Toggle Project Debug Log', value='project_debug_log'),
                questionary.Choice('Toggle Batch TTL 1h Promotion (Anthropic)', value='batch_ttl_1h'),
                questionary.Separator(),
                questionary.Choice('Back', value='back'),
            ],
            style=custom_style,
        ).ask()

        if action in (None, 'back'):
            return changed

        if action == 'provider':
            selected = questionary.select(
                'Translator provider:',
                choices=[
                    questionary.Choice('Anthropic', value='anthropic'),
                    questionary.Choice('Gemini', value='gemini'),
                ],
                default=config.translator_provider,
                style=custom_style,
            ).ask()
            if selected and selected != config.translator_provider:
                config.translator_provider = selected
                changed = True

        elif action == 'model':
            model_choices = [questionary.Choice(m['label'] + ' - ' + m['desc'], value=m['value']) for m in config.get_available_models()]
            selected = questionary.select(
                'Active model:',
                choices=model_choices,
                default=config.active_model,
                style=custom_style,
            ).ask()
            if selected and selected != config.active_model:
                config.model = selected
                changed = True

        elif action == 'cache_toggle':
            value = questionary.confirm(
                f"Enable caching? (currently {'ON' if config.caching_enabled else 'OFF'})",
                default=config.caching_enabled,
                style=custom_style,
            ).ask()
            if value != config.caching_enabled:
                config.caching_enabled = bool(value)
                changed = True

        elif action == 'cache_ttl':
            value = questionary.text(
                f'Cache TTL minutes (current: {config.cache_ttl}):',
                default=str(config.cache_ttl),
                validate=lambda x: _validate_int(x, 1, 240),
                style=custom_style,
            ).ask()
            if value:
                new_ttl = int(value)
                if new_ttl != config.cache_ttl:
                    config.cache_ttl = new_ttl
                    changed = True

        elif action == 'max_out':
            max_cap = 128000 if config.translator_provider == 'anthropic' else 65535
            value = questionary.text(
                f'Max output tokens (current: {config.max_output_tokens}, cap: {max_cap}):',
                default=str(config.max_output_tokens),
                validate=lambda x: _validate_int(x, 256, max_cap),
                style=custom_style,
            ).ask()
            if value:
                new_val = int(value)
                if new_val != config.max_output_tokens:
                    config.max_output_tokens = new_val
                    changed = True

        elif action == 'thinking_toggle':
            if config.translator_provider == 'anthropic':
                current = config.anthropic_thinking_enabled
                value = questionary.confirm(
                    f"Enable Anthropic thinking? (currently {'ON' if current else 'OFF'})",
                    default=current,
                    style=custom_style,
                ).ask()
                if value != current:
                    config.anthropic_thinking_enabled = bool(value)
                    changed = True
            else:
                current = bool(config.get('gemini.thinking_mode.enabled', True))
                value = questionary.confirm(
                    f"Enable Gemini thinking? (currently {'ON' if current else 'OFF'})",
                    default=current,
                    style=custom_style,
                ).ask()
                if value != current:
                    config.set('gemini.thinking_mode.enabled', bool(value))
                    changed = True

        elif action == 'thinking_type':
            if config.translator_provider == 'anthropic':
                current = config.anthropic_thinking_type
                selected = questionary.select(
                    'Anthropic thinking type:',
                    choices=[
                        questionary.Choice('adaptive', value='adaptive'),
                        questionary.Choice('enabled', value='enabled'),
                    ],
                    default=current if current in {'adaptive', 'enabled'} else 'adaptive',
                    style=custom_style,
                ).ask()
                if selected and selected != current:
                    config.anthropic_thinking_type = selected
                    changed = True
            else:
                current = str(config.get('gemini.thinking_mode.thinking_level', 'medium'))
                selected = questionary.select(
                    'Gemini thinking level:',
                    choices=['low', 'medium', 'high'],
                    default=current if current in {'low', 'medium', 'high'} else 'medium',
                    style=custom_style,
                ).ask()
                if selected and selected != current:
                    config.set('gemini.thinking_mode.thinking_level', selected)
                    changed = True

        elif action == 'multimodal':
            current = config.multimodal_processor_enabled
            value = questionary.confirm(
                f"Enable multimodal by default? (currently {'ON' if current else 'OFF'})",
                default=current,
                style=custom_style,
            ).ask()
            if value != current:
                config.multimodal_processor_enabled = bool(value)
                changed = True

        elif action == 'chunking':
            current = config.smart_chunking_enabled
            value = questionary.confirm(
                f"Enable smart chunking? (currently {'ON' if current else 'OFF'})",
                default=current,
                style=custom_style,
            ).ask()
            if value != current:
                config.smart_chunking_enabled = bool(value)
                changed = True

        elif action == 'project_debug_log':
            current = config.translator_project_debug_log
            value = questionary.confirm(
                f"Save translator debug logs to project folder? (currently {'ON' if current else 'OFF'})",
                default=current,
                style=custom_style,
            ).ask()
            if value != current:
                config.translator_project_debug_log = bool(value)
                changed = True

        elif action == 'batch_ttl_1h':
            if config.translator_provider != 'anthropic':
                console.print('[yellow]Batch TTL promotion applies to Anthropic only.[/yellow]')
                continue
            current = config.anthropic_batch_promote_ttl_1h
            value = questionary.confirm(
                f"Promote cache TTL to 1h in batch? (currently {'ON' if current else 'OFF'})",
                default=current,
                style=custom_style,
            ).ask()
            if value != current:
                config.anthropic_batch_promote_ttl_1h = bool(value)
                changed = True


def apply_runtime_preset(config: ConfigBridge) -> Optional[str]:
    """Apply predefined runtime presets (Phase A)."""
    selected = questionary.select(
        'Select runtime preset:',
        choices=[
            questionary.Choice('Quality Max (Opus 4.6, full quality)', value='quality_max'),
            questionary.Choice('Fast Iterate (low-latency loop)', value='fast_iterate'),
            questionary.Choice('Cost Saver (batch/cache heavy)', value='cost_saver'),
            questionary.Choice('Debug (max observability)', value='debug'),
            questionary.Separator(),
            questionary.Choice('Cancel', value='cancel'),
        ],
        style=custom_style,
    ).ask()

    if selected in (None, 'cancel'):
        return None

    if selected == 'quality_max':
        config.translator_provider = 'anthropic'
        config.anthropic_model = 'claude-opus-4-6'
        config.anthropic_thinking_enabled = True
        config.anthropic_thinking_type = 'adaptive'
        config.max_output_tokens = 128000
        config.caching_enabled = True
        config.cache_ttl = 5
        config.anthropic_batch_promote_ttl_1h = True
        config.anthropic_cache_shared_brief = True
        config.multimodal_processor_enabled = True
        config.smart_chunking_enabled = False

    elif selected == 'fast_iterate':
        config.translator_provider = 'anthropic'
        config.anthropic_model = 'claude-sonnet-4-6'
        config.anthropic_thinking_enabled = True
        config.anthropic_thinking_type = 'enabled'
        config.max_output_tokens = 64000
        config.caching_enabled = True
        config.cache_ttl = 5
        config.multimodal_processor_enabled = False
        config.smart_chunking_enabled = True

    elif selected == 'cost_saver':
        config.translator_provider = 'anthropic'
        config.anthropic_model = 'claude-sonnet-4-6'
        config.anthropic_thinking_enabled = True
        config.anthropic_thinking_type = 'adaptive'
        config.max_output_tokens = 64000
        config.caching_enabled = True
        config.cache_ttl = 5
        config.anthropic_batch_promote_ttl_1h = True
        config.anthropic_cache_shared_brief = True
        config.multimodal_processor_enabled = False
        config.smart_chunking_enabled = True

    elif selected == 'debug':
        config.verbose_mode = True
        config.debug_mode = True
        config.translator_project_debug_log = True
        config.caching_enabled = True
        config.multimodal_processor_enabled = True

    return selected

def show_current_settings(config: ConfigBridge) -> None:
    """
    Display current settings in a formatted table.

    Args:
        config: Configuration bridge instance
    """
    # Language info
    lang = config.target_language
    lang_config = config.get_language_config(lang)
    lang_name = lang_config.get('language_name', lang.upper())

    # Create settings table
    table = Table(title="Current Settings", box=box.ROUNDED)
    table.add_column("Category", style="cyan", width=20)
    table.add_column("Setting", style="white", width=20)
    table.add_column("Value", style="green", width=25)

    # Translation
    table.add_row("Translation", "Target Language", f"{lang_name} ({lang.upper()})")
    table.add_row("", "Model", config.model)
    table.add_row("", "Multimodal Processor", "Enabled" if config.multimodal_processor_enabled else "Disabled")

    # Parameters
    table.add_row("Parameters", "Temperature", str(config.temperature))
    table.add_row("", "Top-P", str(config.top_p))
    table.add_row("", "Top-K", str(config.top_k))

    # Performance
    cache_status = "Enabled" if config.caching_enabled else "Disabled"
    table.add_row("Performance", "Context Caching", cache_status)
    if config.caching_enabled:
        table.add_row("", "Cache TTL", f"{config.cache_ttl} minutes")
    table.add_row("", "Smart Chunking", "Enabled" if config.smart_chunking_enabled else "Disabled")

    runtime = config.get_runtime_summary()
    table.add_row("OpenRouter", "Route", "RUN" if runtime.get("openrouter_selected") else "OFF")
    table.add_row("", "Endpoint", str(runtime.get("openrouter_endpoint", "")))
    table.add_row("", "ApiKey Env", str(runtime.get("openrouter_api_key_env", "")))
    table.add_row("", "Opus 1M Confirmed", "ON" if runtime.get("opus_1m_confirmed") else "OFF")
    table.add_row("", "Phase 1.56", "HARD-DISABLED" if runtime.get("phase156_hard_disabled") else "ENABLED")
    table.add_row(
        "",
        "Full Prequel Gate",
        (
            f"{'ON' if runtime.get('full_prequel_gate_enabled') else 'OFF'} "
            f"({runtime.get('full_prequel_budget_tokens')}/{runtime.get('full_prequel_window_tokens')} "
            f"{int(float(runtime.get('full_prequel_ratio', 0.85) or 0.85) * 100)}%)"
        ),
    )

    # Advanced
    pre_toc_status = "Enabled" if config.pre_toc_enabled else "Disabled"
    debug_status = "Enabled" if config.debug_mode else "Disabled"
    verbose_status = "Enabled" if config.verbose_mode else "Disabled"

    table.add_row("Advanced", "Pre-TOC Detection", pre_toc_status)
    table.add_row("", "Debug Mode", debug_status)
    table.add_row("", "Default Verbose", verbose_status)

    console.print()
    console.print(table)
    console.print()


def _validate_float(value: str, min_val: float, max_val: float) -> bool:
    """Validate float input within range."""
    try:
        f = float(value)
        return min_val <= f <= max_val
    except ValueError:
        return False


def _validate_int(value: str, min_val: int, max_val: int) -> bool:
    """Validate integer input within range."""
    try:
        i = int(value)
        return min_val <= i <= max_val
    except ValueError:
        return False


def _clear_cache_menu(config: ConfigBridge) -> None:
    """Handle cache clearing submenu."""
    console.print("\n[bold cyan]Cache Management[/bold cyan]\n")
    console.print("[dim]This will remove:[/dim]")
    console.print("  • Python bytecode cache (__pycache__, .pyc files)")
    console.print("  • Gemini API context caches")
    console.print("\n[yellow]Note: A fresh Python process is needed to reload updated modules.[/yellow]\n")

    confirm = questionary.confirm(
        "Proceed with cache purge?",
        default=False,
        style=custom_style,
    ).ask()

    if not confirm:
        console.print("[dim]Cache purge cancelled[/dim]")
        return

    console.print("\n[cyan]Purging caches...[/cyan]")

    # Get pipeline root (parent of config file)
    pipeline_root = Path(config.config_path).parent

    # Purge all caches
    results = purge_all_caches(pipeline_root)

    # Display results
    console.print("\n[bold green]✓ Cache Purge Complete[/bold green]\n")

    # Python cache results
    py_results = results["python"]
    py_total = py_results["total_items"]
    if py_total > 0:
        console.print(
            f"[green]Python Cache:[/green] Removed {py_results['cache_dirs_removed']} "
            f"directories and {py_results['pyc_files_removed']} bytecode files"
        )
    else:
        console.print("[dim]Python Cache:[/dim] No cache files found")

    # Gemini cache results
    gemini_results = results["gemini"]
    if gemini_results["success"]:
        cache_count = gemini_results["caches_removed"]
        if cache_count > 0:
            console.print(f"[green]Gemini API:[/green] Removed {cache_count} context cache(s)")
        else:
            console.print("[dim]Gemini API:[/dim] No active caches found")
    else:
        console.print(f"[yellow]Gemini API:[/yellow] {gemini_results['error']}")

    console.print("\n[bold cyan]→ Restart required for Python module changes to take effect[/bold cyan]\n")

    questionary.press_any_key_to_continue("Press any key to continue...").ask()

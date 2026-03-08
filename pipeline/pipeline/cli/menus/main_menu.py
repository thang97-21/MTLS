"""
Main menu component for the CLI TUI.
"""

from typing import Optional
import questionary
from rich.console import Console
from rich.panel import Panel

from ..components.styles import custom_style
from ..utils.config_bridge import ConfigBridge

console = Console()


def show_header(config: ConfigBridge) -> None:
    """
    Display header with current settings.

    Args:
        config: Configuration bridge instance
    """
    verbose = config.verbose_mode
    lang = config.target_language.upper()

    lang_config = config.get_language_config(config.target_language)
    lang_name = lang_config.get('language_name', lang)

    mode_indicator = "[green]ON[/green]" if verbose else "[dim]OFF[/dim]"
    cache_indicator = "[green]ON[/green]" if config.caching_enabled else "[dim]OFF[/dim]"
    multimodal_indicator = "[green]ON[/green]" if config.multimodal_processor_enabled else "[dim]OFF[/dim]"
    chunking_indicator = "[green]ON[/green]" if config.smart_chunking_enabled else "[dim]OFF[/dim]"

    runtime = config.get_runtime_summary()
    provider = str(runtime.get("provider", "?")).upper()
    model = str(runtime.get("model", "?")).split("/")[-1]
    thinking = "[green]ON[/green]" if runtime.get("thinking") else "[dim]OFF[/dim]"
    max_out = runtime.get("max_output_tokens", "?")
    cache_ttl = runtime.get("cache_ttl", "?")
    phase25_auto = "[green]ON[/green]" if runtime.get("phase25_auto_update") else "[dim]OFF[/dim]"
    phase25_qc = "[green]ON[/green]" if runtime.get("phase25_qc_cleared") else "[yellow]OFF[/yellow]"
    openrouter_route = "[green]RUN[/green]" if runtime.get("openrouter_selected") else "[dim]OFF[/dim]"
    opus_1m_confirmed = "[green]ON[/green]" if runtime.get("opus_1m_confirmed") else "[dim]OFF[/dim]"
    phase156_gate = "[bold red]HARD-DISABLED[/bold red]" if runtime.get("phase156_hard_disabled") else "[green]ENABLED[/green]"
    full_prequel_gate = "[green]ON[/green]" if runtime.get("full_prequel_gate_enabled") else "[dim]OFF[/dim]"
    full_prequel_budget = runtime.get("full_prequel_budget_tokens", "?")
    full_prequel_window = runtime.get("full_prequel_window_tokens", "?")
    full_prequel_ratio = int(float(runtime.get("full_prequel_ratio", 0.85) or 0.85) * 100)

    header_content = (
        f"[bold cyan]MT PUBLISHING PIPELINE[/bold cyan] v2.1\n"
        f"[dim]Japanese Light Novel Translation[/dim]\n"
        f"\n"
        f"[bold]Verbose:[/bold] {mode_indicator}  |  "
        f"[bold]Language:[/bold] {lang_name} ({lang})  |  "
        f"[bold]Provider:[/bold] {provider}\n"
        f"[bold]Model:[/bold] {model}  |  "
        f"[bold]Thinking:[/bold] {thinking}  |  "
        f"[bold]Max Out:[/bold] {max_out}  |  "
        f"[bold]Cache TTL:[/bold] {cache_ttl}m\n"
        f"[bold]Caching:[/bold] {cache_indicator}  |  "
        f"[bold]Chunking:[/bold] {chunking_indicator}  |  "
        f"[bold]Multimodal:[/bold] {multimodal_indicator}\n"
        f"[bold]Phase 2.5 Auto:[/bold] {phase25_auto}  |  "
        f"[bold]QC Gate:[/bold] {phase25_qc}\n"
        f"[bold]OpenRouter Route:[/bold] {openrouter_route}  |  "
        f"[bold]Endpoint:[/bold] {runtime.get('openrouter_endpoint')}  |  "
        f"[bold]ApiKeyEnv:[/bold] {runtime.get('openrouter_api_key_env')}\n"
        f"[bold]OpenRouter Gates:[/bold] Opus1MConfirmed={opus_1m_confirmed}  |  "
        f"[bold]Phase1.56:[/bold] {phase156_gate}\n"
        f"[bold]Full Prequel Gate:[/bold] {full_prequel_gate}  |  "
        f"[bold]Budget:[/bold] {full_prequel_budget}/{full_prequel_window} ({full_prequel_ratio}%)"
    )

    console.print()
    console.print(Panel(
        header_content,
        border_style="blue",
        padding=(1, 2),
    ))
    console.print()


def main_menu() -> Optional[str]:
    """
    Display main menu and return selected action.

    Returns:
        Selected action string or None if cancelled
    """
    choices = [
        questionary.Choice(
            title="Start New Translation",
            value="new"
        ),
        questionary.Choice(
            title="Run Phase 1: Librarian (Standalone Extraction)",
            value="phase1"
        ),
        questionary.Choice(
            title="Run Phase 1.15 (Title Philosophy Injection)",
            value="phase1.15"
        ),
        questionary.Choice(
            title="Run Phase 1.51 (Voice RAG Expansion)",
            value="phase1.51"
        ),
        questionary.Choice(
            title="Run Phase 1.52 (EPS Backfill)",
            value="phase1.52"
        ),
        questionary.Choice(
            title="Resume Volume",
            value="resume"
        ),
        questionary.Choice(
            title="Run Phase 1.55 (Rich Metadata Cache)",
            value="phase1.55"
        ),
        questionary.Choice(
            title="Run Phase 1.56 (Translator's Guidance Brief)",
            value="phase1.56"
        ),
        questionary.Choice(
            title="Run Phase 2.5 (Volume Bible Update)",
            value="phase2.5"
        ),
        questionary.Choice(
            title="Toggle Phase 2.5 Auto-Run",
            value="phase2.5_toggle"
        ),
        questionary.Separator("[ Phase A ]"),
        questionary.Choice(
            title="Runtime Profile (Phase A)",
            value="runtime_profile"
        ),
        questionary.Choice(
            title="Apply Runtime Preset (Phase A)",
            value="runtime_preset"
        ),
        questionary.Separator("[ Phase B ]"),
        questionary.Choice(
            title="Pipeline Control (Phase B)",
            value="phase_b_control"
        ),
        questionary.Separator("[ Phase C ]"),
        questionary.Choice(
            title="Volume Workbench (Phase C)",
            value="phase_c_workbench"
        ),
        questionary.Separator(),
        questionary.Choice(
            title="Settings",
            value="settings"
        ),
        questionary.Choice(
            title="View Status",
            value="status"
        ),
        questionary.Choice(
            title="List Volumes",
            value="list"
        ),
        questionary.Separator(),
        questionary.Choice(
            title="Exit",
            value="exit"
        ),
    ]

    return questionary.select(
        "Select an action:",
        choices=choices,
        style=custom_style,
        use_shortcuts=True,
    ).ask()


def quick_action_menu() -> Optional[str]:
    """
    Display quick action menu (minimal choices).

    Returns:
        Selected action string or None if cancelled
    """
    choices = [
        questionary.Choice("Translate", value="translate"),
        questionary.Choice("Build EPUB", value="build"),
        questionary.Choice("Full Pipeline", value="run"),
        questionary.Separator(),
        questionary.Choice("Back", value="back"),
    ]

    return questionary.select(
        "Quick action:",
        choices=choices,
        style=custom_style,
    ).ask()


def phase_menu(volume_id: str) -> Optional[str]:
    """
    Display phase selection menu for a volume.

    Args:
        volume_id: Current volume ID

    Returns:
        Selected phase string or None if cancelled
    """
    console.print(f"\n[bold]Volume:[/bold] [cyan]{volume_id}[/cyan]\n")

    choices = [
        questionary.Choice("Phase 1: Librarian (EPUB Extraction)", value="phase1"),
        questionary.Choice("Phase 1.15: Title Philosophy Injection", value="phase1.15"),
        questionary.Choice("Phase 1.5: Metadata (Title/Author Translation)", value="phase1.5"),
        questionary.Choice("Phase 1.51: Voice RAG Expansion", value="phase1.51"),
        questionary.Choice("Phase 1.52: EPS Backfill", value="phase1.52"),
        questionary.Choice("Phase 1.55: Rich Metadata Cache (Full-LN Enrichment)", value="phase1.55"),
        questionary.Choice("Phase 1.56: Translator's Guidance Brief", value="phase1.56"),
        questionary.Choice("Phase 1.6: Multimodal Processor (Illustration Analysis)", value="phase1.6"),
        questionary.Choice("Phase 2: Translator", value="phase2"),
        questionary.Choice("Phase 2.5: Volume Bible Update", value="phase2.5"),
        questionary.Choice("Phase 3: Critics (Manual Review)", value="phase3"),
        questionary.Choice("Phase 4: Builder (EPUB Packaging)", value="phase4"),
        questionary.Separator(),
        questionary.Choice("Run Full Pipeline", value="run"),
        questionary.Choice("Back to Main Menu", value="back"),
    ]

    return questionary.select(
        "Select phase to run:",
        choices=choices,
        style=custom_style,
    ).ask()


def post_translation_menu(volume_id: str) -> Optional[str]:
    """
    Display menu after translation phase completes.

    Args:
        volume_id: Current volume ID

    Returns:
        Selected action string or None if cancelled
    """
    console.print(f"\n[green]✓[/green] [bold]Translation Complete[/bold]\n")
    console.print(f"Volume: [cyan]{volume_id}[/cyan]\n")

    choices = [
        questionary.Choice("Proceed to Phase 4 (Build EPUB)", value="build"),
        questionary.Choice("Review Translation Status", value="status"),
        questionary.Choice("Run Phase 3 (Manual Review) First", value="review"),
        questionary.Separator(),
        questionary.Choice("Return to Main Menu", value="menu"),
        questionary.Choice("Exit", value="exit"),
    ]

    return questionary.select(
        "What would you like to do next?",
        choices=choices,
        style=custom_style,
    ).ask()


def confirm_exit() -> bool:
    """
    Confirm exit from the application.

    Returns:
        True if user confirms exit
    """
    return questionary.confirm(
        "Exit MT Publishing Pipeline?",
        default=False,
        style=custom_style,
    ).ask()

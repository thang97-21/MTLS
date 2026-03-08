"""
MT Publishing Pipeline - Main TUI Application
Interactive terminal user interface for the translation pipeline.
"""

import sys
import os
import select
import json
import time
import readline  # Enable delete key, arrow keys, and input history
from pathlib import Path
from typing import Optional, Dict, Any
import logging
import questionary

try:
    import termios
except Exception:  # pragma: no cover - non-POSIX fallback
    termios = None

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .menus.main_menu import (
    main_menu,
    show_header,
    phase_menu,
    post_translation_menu,
    confirm_exit,
)
from .menus.settings import (
    settings_panel,
    show_current_settings,
    runtime_profile_panel,
    apply_runtime_preset,
)
from .menus.translation import (
    start_librarian_flow,
    start_translation_flow,
    resume_volume_flow,
    select_chapters_flow,
)
from .menus.workbench import (
    build_workbench_rows,
    render_workbench,
    select_repair_chapters,
    run_cjk_scan,
    render_cjk_scan_results,
)
from .menus.status import show_status_panel, list_volumes_panel
from .components.progress import TranslationProgress
from .components.styles import custom_style
from .utils.config_bridge import ConfigBridge
from .utils.display import (
    console,
    print_header,
    print_success,
    print_error,
    print_warning,
)

# Setup logging
logger = logging.getLogger(__name__)


class MTLApp:
    """
    Main TUI Application for the MT Publishing Pipeline.

    Provides an interactive menu-driven interface with:
    - Arrow key navigation
    - Toggle switches for settings
    - Context caching confirmations
    - Continuity pack management
    - Progress display during translation
    """

    def __init__(self, work_dir: Optional[Path] = None, input_dir: Optional[Path] = None):
        """
        Initialize the TUI application.

        Args:
            work_dir: Path to WORK directory (default: auto-detect from project root)
            input_dir: Path to INPUT directory (default: auto-detect from project root)
        """
        # Determine project root (parent of pipeline module)
        self.project_root = Path(__file__).parent.parent.parent.resolve()

        self.work_dir = work_dir or self.project_root / "WORK"
        self.input_dir = input_dir or self.project_root / "INPUT"
        self.output_dir = self.project_root / "OUTPUT"

        # Ensure directories exist
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Load configuration
        self.config = ConfigBridge(self.project_root / "config.yaml")
        self.config.load()

        # State
        self.current_volume: Optional[str] = None
        self.running = False

    def run(self) -> int:
        """
        Main entry point - run the TUI application.

        Returns:
            Exit code (0 for success, non-zero for error)
        """
        self.running = True

        try:
            # Clear task-launch keystrokes so the first menu does not auto-submit.
            self._flush_stdin_buffer()

            # Clear screen and show header
            self._clear_screen()
            show_header(self.config)

            # Main loop
            while self.running:
                self._flush_stdin_buffer()
                action = main_menu()

                if action is None or action == "exit":
                    if confirm_exit():
                        self.running = False
                    else:
                        self._clear_screen()
                        show_header(self.config)
                        continue

                elif action == "new":
                    self._handle_new_translation()

                elif action == "phase1":
                    self._handle_phase1()

                elif action == "phase1.15":
                    self._handle_phase1_15()

                elif action == "resume":
                    self._handle_resume_volume()

                elif action == "phase1.51":
                    self._handle_phase1_51()

                elif action == "phase1.52":
                    self._handle_phase1_52()

                elif action == "phase1.55":
                    self._handle_phase1_55()

                elif action == "phase1.56":
                    self._handle_phase1_56()

                elif action == "phase2.5":
                    self._handle_phase2_5()

                elif action == "phase2.5_toggle":
                    self._handle_phase2_5_toggle()

                elif action == "runtime_profile":
                    self._handle_runtime_profile()

                elif action == "runtime_preset":
                    self._handle_runtime_preset()

                elif action == "phase_b_control":
                    self._handle_phase_b_control()

                elif action == "phase_c_workbench":
                    self._handle_phase_c_workbench()

                elif action == "settings":
                    self._handle_settings()

                elif action == "status":
                    self._handle_view_status()

                elif action == "list":
                    self._handle_list_volumes()

                # Refresh header after each action
                if self.running:
                    self._clear_screen()
                    show_header(self.config)

            console.print("\n[dim]Goodbye![/dim]\n")
            return 0

        except KeyboardInterrupt:
            console.print("\n\n[yellow]Interrupted by user[/yellow]\n")
            return 130

        except Exception as e:
            print_error(f"Fatal error: {e}")
            logger.exception("Unhandled exception in TUI")
            return 1

    def _clear_screen(self) -> None:
        """Clear the terminal screen."""
        # Use ANSI escape codes (works on most terminals)
        console.print("\033[H\033[J", end="")

    def _flush_stdin_buffer(self) -> None:
        """Drain pending stdin so task-launch Enter keys do not auto-select menu items."""
        if not sys.stdin or not sys.stdin.isatty():
            return

        try:
            if termios is not None:
                termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
        except Exception:
            pass

        try:
            fd = sys.stdin.fileno()
            while True:
                ready, _, _ = select.select([fd], [], [], 0)
                if not ready:
                    break
                os.read(fd, 4096)
        except Exception:
            pass

    def _handle_new_translation(self) -> None:
        """Handle starting a new translation."""
        result = start_translation_flow(
            config=self.config,
            input_dir=self.input_dir,
            work_dir=self.work_dir,
        )

        if result is None:
            return

        # Extract options
        epub_path = result['epub_path']
        volume_id = result['volume_id']
        auto_inherit = result.get('auto_inherit', False)
        force = result.get('force', False)
        auto_build = result.get('auto_build', True)

        self.current_volume = volume_id

        # Run the pipeline
        success = self._run_full_pipeline(
            epub_path=epub_path,
            volume_id=volume_id,
            auto_inherit=auto_inherit,
            force=force,
            auto_build=auto_build,
        )

        if success:
            print_success(f"Pipeline completed for {volume_id}")
        else:
            print_error(f"Pipeline failed for {volume_id}")

        input("\nPress Enter to continue...")

    def _handle_phase1(self) -> None:
        """Handle standalone Phase 1 (Librarian extraction)."""
        import questionary

        result = start_librarian_flow(input_dir=self.input_dir)
        if result is None:
            return

        epub_path = result['epub_path']
        volume_id = result['volume_id']
        self.current_volume = volume_id

        success = self._run_phase1(epub_path, volume_id)
        if not success:
            print_error(f"Phase 1 failed for {volume_id}")
            input("\nPress Enter to continue...")
            return

        print_success(f"Phase 1 completed for {volume_id}")

        next_action = questionary.select(
            "Phase 1 completed. Continue to metadata phases?",
            choices=[
                questionary.Choice(
                    "Continue with Phase 1.5 + Phase 1.55",
                    value="continue",
                ),
                questionary.Choice(
                    "Skip and return to Main Menu",
                    value="skip",
                ),
            ],
            style=custom_style,
        ).ask()

        if next_action == "continue":
            success_15 = self._run_phase1_5(volume_id)
            if not success_15:
                print_error(f"Phase 1.5 failed for {volume_id}")
                input("\nPress Enter to continue...")
                return

            success_155 = self._run_phase1_55(volume_id)
            if not success_155:
                print_error(f"Phase 1.55 failed for {volume_id}")
                input("\nPress Enter to continue...")
                return

            print_success(f"Phase 1.5 and Phase 1.55 completed for {volume_id}")

        input("\nPress Enter to continue...")

    def _handle_resume_volume(self) -> None:
        """Handle resuming an existing volume."""
        result = resume_volume_flow(
            config=self.config,
            work_dir=self.work_dir,
        )

        if result is None:
            return

        volume_id = result['volume_id']
        action = result['action']
        self.current_volume = volume_id

        if action == "translate":
            # Ask for specific chapters or all
            chapters = select_chapters_flow(self.work_dir, volume_id)
            success = self._run_phase2(volume_id, chapters=chapters)

        elif action == "build":
            success = self._run_phase4(volume_id)

        elif action == "phase1.55":
            success = self._run_phase1_55(volume_id)

        elif action == "phase1.56":
            success = self._run_phase1_56(volume_id)

        elif action == "phase1.15":
            success = self._run_phase1_15(volume_id)

        elif action == "phase1.51":
            success = self._run_phase1_51(volume_id)

        elif action == "phase1.52":
            success = self._run_phase1_52(volume_id)

        elif action == "phase1.6":
            success = self._run_phase1_6(volume_id)

        elif action == "run":
            success = self._run_phases_2_to_4(volume_id)

        elif action == "status":
            show_status_panel(self.work_dir, volume_id)
            input("\nPress Enter to continue...")
            return

        if action != "status":
            if success:
                print_success(f"Operation completed for {volume_id}")
            else:
                print_error(f"Operation failed for {volume_id}")
            input("\nPress Enter to continue...")

    def _handle_settings(self) -> None:
        """Handle settings panel."""
        # Show current settings first
        show_current_settings(self.config)

        # Open settings panel
        result = settings_panel(self.config)

        if result and result.get('saved'):
            # Reload config to ensure changes are reflected
            self.config.load()

    def _handle_runtime_profile(self) -> None:
        """Handle Phase A runtime profile editor."""
        changed = runtime_profile_panel(self.config)
        if changed:
            self.config.save()
            self.config.load()
            print_success("Runtime profile updated")
        else:
            print_warning("No runtime profile changes applied")
        input("\nPress Enter to continue...")

    def _handle_runtime_preset(self) -> None:
        """Handle Phase A runtime preset application."""
        preset = apply_runtime_preset(self.config)
        if preset:
            self.config.save()
            self.config.load()
            print_success(f"Applied preset: {preset}")
        else:
            print_warning("Preset application cancelled")
        input("\nPress Enter to continue...")

    def _handle_phase_b_control(self) -> None:
        """Handle Phase B pipeline control center."""
        import questionary

        selected = list_volumes_panel(self.work_dir)
        if not selected:
            return

        self.current_volume = selected
        runtime = self.config.get_runtime_summary()
        provider = str(runtime.get("provider", "?")).upper()
        model = str(runtime.get("model", "?"))

        console.print()
        console.print(Panel(
            "[bold]Pipeline Control (Phase B)[/bold]\n"
            f"[dim]Volume:[/dim] {selected}\n"
            f"[dim]Runtime:[/dim] {provider} | {model} | "
            f"cache={'ON' if runtime.get('cache_enabled') else 'OFF'} ({runtime.get('cache_ttl')}m) | "
            f"thinking={'ON' if runtime.get('thinking') else 'OFF'}\n"
            "[dim]Run targeted phases without leaving main menu.[/dim]",
            border_style="blue",
            padding=(1, 2),
        ))

        action = questionary.select(
            "Phase B action:",
            choices=[
                questionary.Choice("Run Phase 1.56 (Translator Brief)", value="phase1.56"),
                questionary.Choice("Run Phase 1.6 (Multimodal Processor)", value="phase1.6"),
                questionary.Choice("Run Phase 2 (All Chapters)", value="phase2"),
                questionary.Choice("Run Phase 2.5 (Volume Bible Update)", value="phase2.5"),
                questionary.Choice("Run Phase 2 (Specific Chapters)", value="phase2_chapters"),
                questionary.Choice("Run Phase 2 (Force Retranslate)", value="phase2_force"),
                questionary.Choice("Batch Monitor (Phase B.1)", value="batch_monitor"),
                questionary.Choice("Run Phases 2 -> 4", value="phase2_4"),
                questionary.Choice("Run Phase 4 (Builder)", value="phase4"),
                questionary.Choice("View Status", value="status"),
                questionary.Separator(),
                questionary.Choice("Back", value="back"),
            ],
            style=custom_style,
        ).ask()

        if action in (None, "back"):
            return

        success = True
        if action == "phase1.56":
            success = self._run_phase1_56(selected)
        elif action == "phase1.6":
            success = self._run_phase1_6(selected)
        elif action == "phase2":
            success = self._run_phase2(selected)
        elif action == "phase2.5":
            success = self._run_phase2_5(selected, qc_cleared=self.config.phase25_qc_cleared)
        elif action == "phase2_chapters":
            chapters = select_chapters_flow(self.work_dir, selected)
            if chapters is None:
                return
            success = self._run_phase2(selected, chapters=chapters)
        elif action == "phase2_force":
            success = self._run_phase2(selected, force=True)
        elif action == "batch_monitor":
            self._handle_phase_b1_batch_monitor(selected)
            return
        elif action == "phase2_4":
            success = self._run_phases_2_to_4(selected)
        elif action == "phase4":
            success = self._run_phase4(selected)
        elif action == "status":
            show_status_panel(self.work_dir, selected)
            input("\nPress Enter to continue...")
            return

        if success:
            print_success(f"Phase B action completed for {selected}")
        else:
            print_error(f"Phase B action failed for {selected}")
        input("\nPress Enter to continue...")

    def _handle_phase_b1_batch_monitor(self, volume_id: str) -> None:
        """Phase B.1: monitor Anthropic batch state with static refresh/watch mode."""
        import questionary
        from pipeline.common.anthropic_client import AnthropicClient
        from pipeline.translator.config import get_translator_provider, get_anthropic_config

        if get_translator_provider() != "anthropic":
            print_warning("Batch monitor is available for Anthropic provider only.")
            input("\nPress Enter to continue...")
            return

        state_path = self.work_dir / volume_id / ".batch_state.json"
        if not state_path.exists():
            print_warning(f"No active batch state found: {state_path}")
            input("\nPress Enter to continue...")
            return

        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception as e:
            print_error(f"Failed to parse batch state: {e}")
            input("\nPress Enter to continue...")
            return

        batch_ids = state.get("batch_ids") or []
        if isinstance(batch_ids, str):
            batch_ids = [batch_ids]
        batch_ids = [str(v).strip() for v in batch_ids if str(v).strip()]
        expected_count = len(state.get("request_custom_ids") or [])

        if not batch_ids:
            print_warning("Batch state has no batch IDs.")
            input("\nPress Enter to continue...")
            return

        anthropic_cfg = get_anthropic_config()
        model = anthropic_cfg.get("model", "claude-sonnet-4-6")
        use_env_key = bool(anthropic_cfg.get("use_env_key", False))
        caching_cfg = anthropic_cfg.get("caching", {}) if isinstance(anthropic_cfg, dict) else {}
        enable_caching = bool(caching_cfg.get("enabled", True))

        try:
            monitor_client = AnthropicClient(
                model=model,
                enable_caching=enable_caching,
                fast_mode=False,
                fast_mode_fallback=True,
                use_env_key=use_env_key,
            )
        except Exception as e:
            print_error(f"Could not initialize Anthropic monitor client: {e}")
            input("\nPress Enter to continue...")
            return

        def _render_snapshot(snapshot: Dict[str, Any]) -> None:
            totals = snapshot.get("totals", {})
            status = str(snapshot.get("status", "unknown")).upper()
            succeeded = int(totals.get("succeeded", 0) or 0)
            errored = int(totals.get("errored", 0) or 0)
            expired = int(totals.get("expired", 0) or 0)
            processing = int(totals.get("processing", 0) or 0)
            total = int(totals.get("total", 0) or 0)

            console.print()
            console.print(Panel(
                "[bold]Batch Monitor (Phase B.1)[/bold]\n"
                f"[dim]Volume:[/dim] {volume_id}\n"
                f"[dim]State File:[/dim] {state_path}\n"
                f"[dim]Batches:[/dim] {len(batch_ids)} | [dim]Expected Requests:[/dim] {expected_count}\n"
                f"[dim]Status:[/dim] {status} | "
                f"[dim]Succeeded:[/dim] {succeeded} | "
                f"[dim]Errored:[/dim] {errored} | "
                f"[dim]Expired:[/dim] {expired} | "
                f"[dim]Processing:[/dim] {processing} | "
                f"[dim]Total:[/dim] {total}\n"
                "[dim]Static mode: no rapid polling logs; only failure/completion events in watch mode.[/dim]",
                border_style="cyan",
                padding=(1, 2),
            ))

            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("Batch ID", overflow="fold")
            table.add_column("Status")
            table.add_column("Succ", justify="right")
            table.add_column("Err", justify="right")
            table.add_column("Exp", justify="right")
            table.add_column("Proc", justify="right")
            table.add_column("Total", justify="right")

            for row in snapshot.get("batches", []):
                table.add_row(
                    str(row.get("batch_id", "")),
                    str(row.get("processing_status", "")),
                    str(row.get("succeeded", 0)),
                    str(row.get("errored", 0)),
                    str(row.get("expired", 0)),
                    str(row.get("processing", 0)),
                    str(row.get("total", 0)),
                )
            console.print(table)

            errors = snapshot.get("errors") or []
            for err in errors:
                console.print(f"[yellow]Warning:[/yellow] {err}")

        def _fetch_snapshot() -> Optional[Dict[str, Any]]:
            try:
                return monitor_client.get_batch_status_snapshot(batch_ids)
            except Exception as e:
                print_error(f"Batch status fetch failed: {e}")
                return None

        first_snapshot = _fetch_snapshot()
        if first_snapshot is None:
            input("\nPress Enter to continue...")
            return
        _render_snapshot(first_snapshot)

        while True:
            action = questionary.select(
                "Batch monitor action:",
                choices=[
                    questionary.Choice("Refresh now", value="refresh"),
                    questionary.Choice("Watch (static, 60s interval)", value="watch"),
                    questionary.Choice("Back", value="back"),
                ],
                style=custom_style,
            ).ask()

            if action in (None, "back"):
                return

            if action == "refresh":
                snap = _fetch_snapshot()
                if snap is not None:
                    _render_snapshot(snap)
                continue

            if action == "watch":
                console.print(
                    "[dim]Watching in static mode (60s). "
                    "Will notify when any request fails or all requests end.[/dim]"
                )
                last_errored = int(first_snapshot.get("totals", {}).get("errored", 0) or 0)
                while True:
                    snap = _fetch_snapshot()
                    if snap is None:
                        break
                    totals = snap.get("totals", {})
                    errored = int(totals.get("errored", 0) or 0) + int(totals.get("expired", 0) or 0)
                    ended = str(snap.get("status", "")) == "ended"
                    if errored > last_errored:
                        _render_snapshot(snap)
                        print_warning("Batch failure detected.")
                        break
                    if ended:
                        _render_snapshot(snap)
                        print_success("Batch completed.")
                        break
                    time.sleep(60)

    def _handle_view_status(self) -> None:
        """Handle viewing status."""
        if self.current_volume:
            # Show status for current volume
            show_status_panel(self.work_dir, self.current_volume)
        else:
            # Let user select a volume
            selected = list_volumes_panel(self.work_dir)
            if selected:
                show_status_panel(self.work_dir, selected)

        input("\nPress Enter to continue...")

    def _handle_phase_c_workbench(self) -> None:
        """Handle Phase C volume workbench + chapter repair workflows."""
        import questionary

        selected = list_volumes_panel(self.work_dir)
        if not selected:
            return

        self.current_volume = selected

        while True:
            snapshot = build_workbench_rows(self.work_dir, selected)
            if not snapshot:
                print_error(f"Could not load workbench data for {selected}")
                input("\nPress Enter to continue...")
                return

            rows = snapshot["rows"]
            target_lang = snapshot["target_lang"]
            summary = snapshot["summary"]
            render_workbench(selected, target_lang, rows, summary)

            action = questionary.select(
                "Phase C action:",
                choices=[
                    questionary.Choice("Refresh Workbench", value="refresh"),
                    questionary.Choice("Repair: Retranslate Selected Chapters", value="repair"),
                    questionary.Choice("Repair: Force Retranslate Selected Chapters", value="repair_force"),
                    questionary.Choice("Scan CJK Leaks: Selected Chapters", value="cjk_scan"),
                    questionary.Choice("View Detailed Volume Status", value="status"),
                    questionary.Separator(),
                    questionary.Choice("Back", value="back"),
                ],
                style=custom_style,
            ).ask()

            if action in (None, "back"):
                return

            if action == "refresh":
                continue

            if action == "status":
                show_status_panel(self.work_dir, selected)
                input("\nPress Enter to continue...")
                continue

            if action in {"repair", "repair_force"}:
                default_mode = "failed_pending" if action == "repair" else "completed"
                chapter_ids = select_repair_chapters(rows, default_mode=default_mode)
                if not chapter_ids:
                    print_warning("No chapters selected.")
                    input("\nPress Enter to continue...")
                    continue

                profile = self._prompt_phase_c_repair_profile(default_force=(action == "repair_force"))
                if profile is None:
                    print_warning("Repair profile cancelled.")
                    input("\nPress Enter to continue...")
                    continue

                success = self._run_phase2(
                    selected,
                    chapters=chapter_ids,
                    force=bool(profile.get("force", False)),
                    enable_multimodal=bool(profile.get("enable_multimodal", False)),
                    batch=bool(profile.get("batch", False)),
                    use_env_key=bool(profile.get("use_env_key", False)),
                    fallback_model_override=profile.get("fallback_model_override"),
                )
                if success:
                    print_success(f"Repair completed for {len(chapter_ids)} chapter(s).")
                else:
                    print_error("Repair workflow failed.")
                input("\nPress Enter to continue...")
                continue

            if action == "cjk_scan":
                chapter_ids = select_repair_chapters(rows, default_mode="failed_pending")
                if not chapter_ids:
                    print_warning("No chapters selected for CJK scan.")
                    input("\nPress Enter to continue...")
                    continue

                scan_results = run_cjk_scan(rows, chapter_ids, self.project_root)
                leaking_ids = render_cjk_scan_results(scan_results)

                if leaking_ids:
                    auto_repair = questionary.confirm(
                        f"Force retranslate leaking chapters now? ({len(leaking_ids)} chapter(s))",
                        default=False,
                        style=custom_style,
                    ).ask()
                    if auto_repair:
                        success = self._run_phase2(selected, chapters=leaking_ids, force=True)
                        if success:
                            print_success(f"Force repair submitted for {len(leaking_ids)} leaking chapter(s).")
                        else:
                            print_error("Force repair failed.")

                input("\nPress Enter to continue...")
                continue

    def _prompt_phase_c_repair_profile(self, default_force: bool = False) -> Optional[Dict[str, Any]]:
        """Prompt repair execution profile for Phase C.1 workflows."""
        import questionary

        runtime = self.config.get_runtime_summary()
        provider = str(runtime.get("provider", "anthropic")).lower()
        mm_default = bool(runtime.get("multimodal", False))

        force = questionary.confirm(
            f"Force retranslate selected chapters? (currently {'ON' if default_force else 'OFF'})",
            default=default_force,
            style=custom_style,
        ).ask()
        if force is None:
            return None

        enable_multimodal = questionary.confirm(
            f"Enable multimodal injection for this repair run? (default {'ON' if mm_default else 'OFF'})",
            default=mm_default,
            style=custom_style,
        ).ask()
        if enable_multimodal is None:
            return None

        batch_default = False
        if provider == "anthropic":
            batch = questionary.confirm(
                "Use batch mode for this repair run? (default OFF for immediate chapter output)",
                default=batch_default,
                style=custom_style,
            ).ask()
            if batch is None:
                return None
        else:
            batch = False

        use_env_key = False
        if provider == "anthropic":
            use_env_key = questionary.confirm(
                "Use direct .env Anthropic key (bypass proxy) for this run?",
                default=False,
                style=custom_style,
            ).ask()
            if use_env_key is None:
                return None

        fallback_model_override = questionary.text(
            "Retry model override (optional, used only when a chapter fails and retries):",
            default="",
            style=custom_style,
        ).ask()
        if fallback_model_override is None:
            return None

        fallback_model_override = str(fallback_model_override).strip() or None

        console.print()
        console.print(Panel(
            "[bold]Phase C.1 Repair Profile[/bold]\n"
            f"[dim]Provider:[/dim] {provider.upper()} | "
            f"[dim]Force:[/dim] {'ON' if force else 'OFF'} | "
            f"[dim]Multimodal:[/dim] {'ON' if enable_multimodal else 'OFF'} | "
            f"[dim]Batch:[/dim] {'ON' if batch else 'OFF'}\n"
            f"[dim]Retry Override:[/dim] {fallback_model_override or 'None'} | "
            f"[dim]Env Key:[/dim] {'ON' if use_env_key else 'OFF'}",
            border_style="magenta",
            padding=(1, 2),
        ))

        confirmed = questionary.confirm(
            "Run repair with this profile?",
            default=True,
            style=custom_style,
        ).ask()
        if not confirmed:
            return None

        return {
            "force": bool(force),
            "enable_multimodal": bool(enable_multimodal),
            "batch": bool(batch),
            "use_env_key": bool(use_env_key),
            "fallback_model_override": fallback_model_override,
        }

    def _handle_list_volumes(self) -> None:
        """Handle listing volumes."""
        selected = list_volumes_panel(self.work_dir)

        if selected:
            show_status_panel(self.work_dir, selected)
            input("\nPress Enter to continue...")

    def _handle_phase1_55(self) -> None:
        """Handle running Phase 1.55 from main menu."""
        selected = list_volumes_panel(self.work_dir)
        if not selected:
            return

        success = self._run_phase1_55(selected)
        if success:
            print_success(f"Phase 1.55 completed for {selected}")
        else:
            print_error(f"Phase 1.55 failed for {selected}")
        input("\nPress Enter to continue...")

    def _handle_phase1_15(self) -> None:
        """Handle running Phase 1.15 from main menu."""
        selected = list_volumes_panel(self.work_dir)
        if not selected:
            return

        success = self._run_phase1_15(selected)
        if success:
            print_success(f"Phase 1.15 completed for {selected}")
        else:
            print_error(f"Phase 1.15 failed for {selected}")
        input("\nPress Enter to continue...")

    def _handle_phase1_51(self) -> None:
        """Handle running Phase 1.51 from main menu."""
        selected = list_volumes_panel(self.work_dir)
        if not selected:
            return

        success = self._run_phase1_51(selected)
        if success:
            print_success(f"Phase 1.51 completed for {selected}")
        else:
            print_error(f"Phase 1.51 failed for {selected}")
        input("\nPress Enter to continue...")

    def _handle_phase1_52(self) -> None:
        """Handle running Phase 1.52 from main menu."""
        selected = list_volumes_panel(self.work_dir)
        if not selected:
            return

        success = self._run_phase1_52(selected)
        if success:
            print_success(f"Phase 1.52 completed for {selected}")
        else:
            print_error(f"Phase 1.52 failed for {selected}")
        input("\nPress Enter to continue...")

    def _handle_phase1_56(self) -> None:
        """Handle running Phase 1.56 from main menu."""
        selected = list_volumes_panel(self.work_dir)
        if not selected:
            return

        success = self._run_phase1_56(selected)
        if success:
            print_success(f"Phase 1.56 completed for {selected}")
        else:
            print_error(f"Phase 1.56 failed for {selected}")
        input("\nPress Enter to continue...")

    def _handle_phase2_5(self) -> None:
        """Handle running standalone Phase 2.5 from main menu."""
        import questionary

        selected = list_volumes_panel(self.work_dir)
        if not selected:
            return

        use_qc_gate = questionary.confirm(
            "QC-cleared output confirmed for this volume?",
            default=bool(self.config.phase25_qc_cleared),
            style=custom_style,
        ).ask()
        if use_qc_gate is None:
            return

        success = self._run_phase2_5(selected, qc_cleared=bool(use_qc_gate))
        if success:
            print_success(f"Phase 2.5 completed for {selected}")
        else:
            print_error(f"Phase 2.5 failed for {selected}")
        input("\nPress Enter to continue...")

    def _handle_phase2_5_toggle(self) -> None:
        """Toggle automatic Phase 2.5 execution after successful Phase 2."""
        current = bool(self.config.phase25_auto_update_enabled)
        self.config.phase25_auto_update_enabled = not current
        self.config.save()
        self.config.load()

        state = "enabled" if not current else "disabled"
        print_success(f"Phase 2.5 auto-run {state}")
        input("\nPress Enter to continue...")

    # Pipeline execution methods

    def _run_full_pipeline(
        self,
        epub_path: Path,
        volume_id: str,
        auto_inherit: bool = False,
        force: bool = False,
        auto_build: bool = True,
    ) -> bool:
        """
        Run the complete pipeline.

        Args:
            epub_path: Path to EPUB file
            volume_id: Volume identifier
            auto_inherit: Deprecated compatibility flag; sequel copy mode no longer exists
            force: Whether to force re-translation
            auto_build: Whether to auto-build EPUB after translation

        Returns:
            True if successful
        """
        from scripts.mtl import PipelineController

        controller = PipelineController(
            work_dir=self.work_dir,
            verbose=self.config.verbose_mode,
        )

        # Phase 1: Librarian
        console.print("\n[bold cyan]Phase 1: Librarian[/bold cyan]")
        if not controller.run_phase1(epub_path, volume_id):
            return False

        # Phase 1.5: Metadata
        console.print("\n[bold cyan]Phase 1.5: Metadata[/bold cyan]")
        if auto_inherit:
            logger.info(
                "Legacy sequel auto-inherit is deprecated. "
                "Phase 1.5 will use standard Bible continuity instead."
            )

        if not controller.run_phase1_5(volume_id):
            return False

        # Phase 1.55: Rich metadata cache enrichment
        console.print("\n[bold cyan]Phase 1.55: Rich Metadata Cache[/bold cyan]")
        if not controller.run_phase1_55(volume_id):
            return False

        # Phase 2: Translator
        console.print("\n[bold cyan]Phase 2: Translator[/bold cyan]")
        if not controller.run_phase2(volume_id, force=force):
            return False

        # Phase 4: Builder (optional)
        if auto_build:
            console.print("\n[bold cyan]Phase 4: Builder[/bold cyan]")
            return controller.run_phase4(volume_id)

        return True

    def _run_phase2(
        self,
        volume_id: str,
        chapters: Optional[list] = None,
        force: bool = False,
        enable_multimodal: bool = False,
        batch: bool = False,
        use_env_key: bool = False,
        fallback_model_override: Optional[str] = None,
    ) -> bool:
        """Run Phase 2 (Translation) only."""
        from scripts.mtl import PipelineController

        controller = PipelineController(
            work_dir=self.work_dir,
            verbose=self.config.verbose_mode,
        )

        console.print("\n[bold cyan]Phase 2: Translator[/bold cyan]")
        return controller.run_phase2(
            volume_id,
            chapters=chapters,
            force=force,
            enable_multimodal=enable_multimodal,
            standalone=True,
            use_env_key=use_env_key,
            batch=batch,
            fallback_model_override=fallback_model_override,
        )

    def _run_phase1(self, epub_path: Path, volume_id: str) -> bool:
        """Run Phase 1 (Librarian) only."""
        from scripts.mtl import PipelineController

        controller = PipelineController(
            work_dir=self.work_dir,
            verbose=self.config.verbose_mode,
        )

        console.print("\n[bold cyan]Phase 1: Librarian[/bold cyan]")
        return controller.run_phase1(epub_path, volume_id)

    def _run_phase1_5(self, volume_id: str) -> bool:
        """Run Phase 1.5 (Metadata) only."""
        from scripts.mtl import PipelineController

        controller = PipelineController(
            work_dir=self.work_dir,
            verbose=self.config.verbose_mode,
        )

        console.print("\n[bold cyan]Phase 1.5: Metadata[/bold cyan]")
        return controller.run_phase1_5(volume_id)

    def _run_phase1_15(self, volume_id: str) -> bool:
        """Run Phase 1.15 (Title Philosophy) only."""
        from scripts.mtl import PipelineController

        controller = PipelineController(
            work_dir=self.work_dir,
            verbose=self.config.verbose_mode,
        )

        console.print("\n[bold cyan]Phase 1.15: Title Philosophy Injection[/bold cyan]")
        return controller.run_phase1_15(volume_id)

    def _run_phase1_51(self, volume_id: str) -> bool:
        """Run Phase 1.51 (Voice RAG Expansion) only."""
        from scripts.mtl import PipelineController

        controller = PipelineController(
            work_dir=self.work_dir,
            verbose=self.config.verbose_mode,
        )

        console.print("\n[bold cyan]Phase 1.51: Voice RAG Expansion[/bold cyan]")
        console.print("[dim]Backfilling Koji Fox voice fingerprints and scene intent map...[/dim]")
        return controller.run_phase1_51(volume_id)

    def _run_phase1_52(self, volume_id: str) -> bool:
        """Run Phase 1.52 (EPS Backfill) only."""
        from scripts.mtl import PipelineController

        controller = PipelineController(
            work_dir=self.work_dir,
            verbose=self.config.verbose_mode,
        )

        console.print("\n[bold cyan]Phase 1.52: EPS Backfill[/bold cyan]")
        console.print("[dim]Backfilling chapter emotional_proximity_signals and scene intents...[/dim]")
        return controller.run_phase1_52(volume_id)

    def _run_phase1_55(self, volume_id: str) -> bool:
        """Run Phase 1.55 (Rich Metadata Cache) only."""
        from scripts.mtl import PipelineController

        controller = PipelineController(
            work_dir=self.work_dir,
            verbose=self.config.verbose_mode,
        )

        console.print("\n[bold cyan]Phase 1.55: Rich Metadata Cache[/bold cyan]")
        console.print("[dim]Caching full LN context + enriching rich metadata...[/dim]")
        return controller.run_phase1_55(volume_id)

    def _run_phase1_56(self, volume_id: str) -> bool:
        """Run Phase 1.56 (Translator's Guidance Brief) only."""
        from scripts.mtl import PipelineController

        controller = PipelineController(
            work_dir=self.work_dir,
            verbose=self.config.verbose_mode,
        )

        console.print("\n[bold cyan]Phase 1.56: Translator's Guidance Brief[/bold cyan]")
        console.print("[dim]Generating full-volume guidance brief for batch translation...[/dim]")
        return controller.run_phase1_56(volume_id)

    def _run_phase2_5(self, volume_id: str, qc_cleared: Optional[bool] = None) -> bool:
        """Run standalone Phase 2.5 (Volume Bible Update)."""
        from scripts.mtl import PipelineController

        controller = PipelineController(
            work_dir=self.work_dir,
            verbose=self.config.verbose_mode,
        )

        console.print("\n[bold cyan]Phase 2.5: Volume Bible Update[/bold cyan]")
        console.print("[dim]Post-translation continuity synthesis + bible enrichment...[/dim]")
        return controller.run_phase2_5(volume_id, qc_cleared=qc_cleared, standalone=True)

    def _run_phase1_6(self, volume_id: str) -> bool:
        """Run Phase 1.6 (Multimodal Processor) only."""
        from scripts.mtl import PipelineController

        controller = PipelineController(
            work_dir=self.work_dir,
            verbose=self.config.verbose_mode,
        )

        console.print("\n[bold cyan]Phase 1.6: Multimodal Processor[/bold cyan]")
        console.print("[dim]Pre-baking illustration analysis with Gemini 3 Pro Vision...[/dim]")
        return controller.run_phase1_6(volume_id, standalone=True)

    def _run_phase4(self, volume_id: str) -> bool:
        """Run Phase 4 (Builder) only."""
        from scripts.mtl import PipelineController
        from pipeline.builder.agent import BuilderAgent

        controller = PipelineController(
            work_dir=self.work_dir,
            verbose=self.config.verbose_mode,
        )

        include_header_illustrations = None
        try:
            builder = BuilderAgent(work_base=self.work_dir)
            detections = builder.detect_header_illustrations(volume_id)
        except Exception as exc:
            detections = []
            logger.warning(f"Phase 4 header illustration detection failed: {exc}")

        if detections:
            sample = ", ".join(d["chapter_id"] for d in detections[:6])
            if len(detections) > 6:
                sample += ", ..."
            console.print(
                f"[yellow]Header illustrations detected in {len(detections)} chapter(s):[/yellow] {sample}"
            )
            include_header_illustrations = questionary.confirm(
                "Override default skip and include header illustrations in the EPUB?",
                default=False,
                style=custom_style,
            ).ask()

        console.print("\n[bold cyan]Phase 4: Builder[/bold cyan]")
        return controller.run_phase4(
            volume_id,
            include_header_illustrations=include_header_illustrations,
        )

    def _run_phases_2_to_4(self, volume_id: str) -> bool:
        """Run Phases 2-4 for an existing volume."""
        if not self._run_phase2(volume_id):
            return False

        # Ask about building
        action = post_translation_menu(volume_id)

        if action == "build":
            return self._run_phase4(volume_id)
        elif action == "status":
            show_status_panel(self.work_dir, volume_id)
            return True

        return True

    def _check_for_sequel(self, volume_id: str) -> Optional[Dict[str, Any]]:
        """
        Deprecated legacy helper.

        Sequel continuity is now resolved in Phase 1.5 via the series bible.
        Previous-volume manifest scanning is intentionally disabled.
        """
        return None


def run_tui() -> int:
    """
    Convenience function to run the TUI application.

    Returns:
        Exit code
    """
    app = MTLApp()
    return app.run()


if __name__ == "__main__":
    sys.exit(run_tui())

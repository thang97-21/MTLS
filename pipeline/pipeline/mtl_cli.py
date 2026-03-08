"""Backward-compatible CLI entrypoint.

Historically, some tooling launched the TUI via:
  python -m pipeline.mtl_cli

The current TUI lives in pipeline.cli.app. Keep this thin shim so
existing VSCode tasks and scripts keep working.
"""

from __future__ import annotations

import sys

from pipeline.cli.app import run_tui


if __name__ == "__main__":
    sys.exit(run_tui())

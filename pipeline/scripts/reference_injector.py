#!/usr/bin/env python3
"""
Standalone Reference Injector Compiler
======================================

Compile chapter-level `.context/*.references.json` files into a deduplicated
`.context/reference_registry.json` artifact for Translator prompt injection.

Usage:
    python pipeline/scripts/reference_injector.py --volume <volume_id>
    python pipeline/scripts/reference_injector.py --volume <volume_id> --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.config import WORK_DIR
from pipeline.post_processor.reference_context_compiler import compile_reference_reports


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compile chapter reference reports into reference_registry.json"
    )
    parser.add_argument(
        "--volume",
        required=True,
        help="Volume ID (folder name under WORK/)",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.70,
        help="Minimum entity confidence threshold (default: 0.70)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even when output is up-to-date",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    volume_dir = Path(WORK_DIR) / args.volume
    context_dir = volume_dir / ".context"
    if not volume_dir.exists():
        print(f"[ERROR] Volume not found: {volume_dir}")
        return 1
    if not context_dir.exists():
        print(f"[ERROR] Context directory not found: {context_dir}")
        return 1

    output_path = compile_reference_reports(
        context_dir=context_dir,
        min_confidence=args.min_confidence,
        force=args.force,
    )
    if not output_path:
        print(f"[WARN] No '*.references.json' files found in: {context_dir}")
        return 2

    print(f"[OK] Compiled reference registry: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

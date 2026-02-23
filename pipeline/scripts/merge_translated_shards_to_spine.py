#!/usr/bin/env python3
"""
Standalone utility: merge fragmented translated shards into spine-canonical chapters.
"""

import argparse
import json
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
PIPELINE_ROOT = SCRIPT_PATH.parents[1]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from pipeline.builder.merge_translated_shards_to_spine import merge_translated_shards_to_spine  # noqa: E402
from pipeline.config import WORK_DIR, get_target_language  # noqa: E402


def _resolve_work_dir(volume: str) -> Path:
    as_path = Path(volume)
    if as_path.exists() and (as_path / "manifest.json").exists():
        return as_path
    return WORK_DIR / volume


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge translated shard chapters into canonical spine chapter groups."
    )
    parser.add_argument("--volume", required=True, help="Volume ID or absolute work directory path")
    parser.add_argument("--lang", default=None, help="Target language code (default from config)")
    parser.add_argument(
        "--apply-manifest",
        action="store_true",
        help="Persist merged chapter structure into manifest.json",
    )
    args = parser.parse_args()

    work_dir = _resolve_work_dir(args.volume)
    manifest_path = work_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"[ERROR] Manifest not found: {manifest_path}")
        return 1

    target_lang = (args.lang or get_target_language() or "en").lower()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    merged_manifest, diag = merge_translated_shards_to_spine(
        work_dir=work_dir,
        manifest=manifest,
        target_language=target_lang,
        apply_manifest=args.apply_manifest,
    )
    _ = merged_manifest

    if not diag.get("applied"):
        print(f"[INFO] Spine merge skipped: {diag.get('reason', 'unknown')}")
        return 0

    print("[OK] Spine canonical merge complete")
    print(f"     Source chapters: {diag.get('source_chapters')}")
    print(f"     Canonical chapters: {diag.get('canonical_chapters')}")
    print(f"     Merged dir: {diag.get('merged_dir')}")
    print(f"     Map file: {diag.get('map_path')}")
    if args.apply_manifest:
        print("     Manifest: updated")
    else:
        print("     Manifest: unchanged (builder preflight can use merged structure in-memory)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


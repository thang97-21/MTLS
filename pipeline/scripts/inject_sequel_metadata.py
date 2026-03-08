#!/usr/bin/env python3
"""
Deprecated legacy script.

Sequel continuity is now handled by the standard Phase 1.5 pipeline
through the series bible and Rich Metadata Cache. Directly copying
predecessor metadata JSON is intentionally disabled.

Usage:
    python inject_sequel_metadata.py <volume_id>
    
Example:
    python inject_sequel_metadata.py 貴族令嬢。俺にだけなつく2_20260120_2188
"""

import sys
from pathlib import Path

pipeline_dir = Path(__file__).parent

def inject_sequel_metadata(volume_id: str, work_dir: Path = None) -> bool:
    """
    Deprecated no-op kept for compatibility.
    
    Args:
        volume_id: Volume ID (directory name)
        work_dir: WORK directory (defaults to pipeline/WORK)
    
    Returns:
        True if metadata was injected, False otherwise
    """
    if work_dir is None:
        work_dir = pipeline_dir / "WORK"

    volume_dir = work_dir / volume_id
    print("=" * 70)
    print(f"SEQUEL METADATA INJECTION DEPRECATED: {volume_id}")
    print("=" * 70)

    if not volume_dir.exists():
        print(f"❌ Volume directory not found: {volume_dir}")
        return False

    print("\nNo files were modified.")
    print("Use the standard Phase 1.5 -> Phase 1.55 flow instead:")
    print("  - Phase 1.5 resolves sequel continuity from the series bible")
    print("  - Phase 1.55 enriches fresh metadata via Rich Metadata Cache")
    print("  - predecessor metadata_en.json copy is no longer supported")

    print("\n" + "=" * 70)
    print("✓ DEPRECATION NOTICE COMPLETE")
    print("=" * 70)

    return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python inject_sequel_metadata.py <volume_id>")
        print("\nExample:")
        print("  python inject_sequel_metadata.py 貴族令嬢。俺にだけなつく2_20260120_2188")
        sys.exit(1)
    
    volume_id = sys.argv[1]
    success = inject_sequel_metadata(volume_id)
    sys.exit(0 if success else 1)

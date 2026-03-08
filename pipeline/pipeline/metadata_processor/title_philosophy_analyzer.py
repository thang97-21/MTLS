"""
Title Philosophy Analyzer (Phase 1.15)
======================================

Analyzes chapter titles from toc.json to determine the author's naming philosophy
and applies appropriate title generation strategy.

Philosophy Classification:
- MINIMAL_NOUN: Single concept nouns (e.g., "恋", "もんじゃ") → use toc_direct
- DESCRIPTIVE_PHRASE: Modified noun phrases → use toc_transcreation
- NARRATIVE_SENTENCE: Full sentences → use toc_transcreation
- HYBRID: Minimal main story + character-named epilogue

Execution: After EPUB extraction (toc.json available), before Phase 1.5 schema_autoupdate.
"""

import argparse
import datetime
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s - %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("TitlePhilosophyAnalyzer")


# Pattern definitions for title signal extraction
VERB_PATTERNS = re.compile(
    r'[するしたしてしないできて]$|[でした|ました|ている|てる]'
)
DECLARATIVE_ENDINGS = re.compile(r'[だです。！？]$')
ADJECTIVE_PRIMARY = re.compile(r'[いなくて]$')
KATAKANA_PATTERN = re.compile(r'[\u30A0-\u30FF]')
CHAPTER_NUMBER_PREFIX = re.compile(r'^[\d１-９０-９]+[\s　]+')


# Classification thresholds
PHILOSOPHY_THRESHOLDS = {
    "MINIMAL_NOUN": {
        "avg_chars_max": 7,
        "verb_ratio_max": 0.10,
        "noun_only_ratio_min": 0.75,
    },
    "DESCRIPTIVE_PHRASE": {
        "avg_chars_min": 7,
        "avg_chars_max": 15,
    },
    "NARRATIVE_SENTENCE": {
        "avg_chars_min": 15,
        "declarative_ratio_min": 0.30,
    },
}


def load_story_labels(toc_path: Path) -> List[Dict[str, Any]]:
    """
    Load story-content nav_points from toc.json, excluding front/back matter.

    Handles two toc.json formats:
    1. Extended format: {"label_jp": "...", "label_en": "..."}
    2. Standard format: {"label": "..."} (JP only, no EN translation)

    Returns list of nav_points with: nav_id, label_jp, label_en, play_order, content_src
    """
    if not toc_path.exists():
        logger.error(f"toc.json not found: {toc_path}")
        return []

    with open(toc_path, encoding="utf-8") as f:
        toc = json.load(f)

    story_labels = []
    # Extended patterns to exclude (JP + common variations)
    excluded_patterns = [
        "目次", "奥付", "あとがき", "前書き", "序章", "結末", "参考文献", "著者略歴",
        "表紙", "Table of Contents", "Contents"
    ]

    for nav in toc.get("nav_points", []):
        # Handle both extended format (label_jp/label_en) and standard format (label)
        label_jp = nav.get("label_jp") or nav.get("label", "")
        label_en = nav.get("label_en") or ""  # May be empty for standard format
        content_src = nav.get("content_src", "")

        # Skip excluded front/back matter
        if any(pattern in label_jp for pattern in excluded_patterns):
            continue

        # Skip nav_points without chapter anchor (non-chapter pages)
        # This is a heuristic - actual chapter files typically have anchors
        if "#toc-" not in content_src and content_src:
            # Check if it's likely a chapter file (contains part number pattern)
            filename = content_src.split("#")[0]
            if not re.search(r'part\d+|chapter_\d+', filename, re.IGNORECASE):
                continue

        story_labels.append({
            "nav_id": nav.get("id") or nav.get("nav_id"),
            "label_jp": label_jp,
            "label_en": label_en,
            "play_order": nav.get("play_order", 0),
            "content_src": content_src,
        })

    logger.info(f"Loaded {len(story_labels)} story labels from toc.json")
    return story_labels


def extract_title_signals(label_jp: str) -> Dict[str, Any]:
    """
    Extract linguistic signals from a Japanese chapter label.

    Returns:
        - clean_label: label with chapter number prefix stripped
        - char_count: character count
        - has_verb: contains verb patterns
        - has_declarative: ends with declarative markers
        - is_noun_phrase: no verbs or declaratives
        - is_character_name: contains katakana or common honorifics
        - is_minimal: short noun-only title
    """
    # Strip chapter number prefix: "１　出会い" → "出会い"
    clean = CHAPTER_NUMBER_PREFIX.sub('', label_jp).strip()

    char_count = len(clean)
    has_verb = bool(VERB_PATTERNS.search(clean))
    has_declarative = bool(DECLARATIVE_ENDINGS.search(clean))
    is_noun_phrase = not has_verb and not has_declarative

    # Character name heuristic: contains katakana OR common surname patterns
    is_character_name = bool(KATAKANA_PATTERN.search(clean)) or \
                        any(suf in clean for suf in ['さん', 'くん', '君', '氏', '様', 'さま'])

    # Kawarasoba check: pure single concept (1-6 chars, no modifiers)
    is_minimal = char_count <= 6 and is_noun_phrase

    return {
        "clean_label": clean,
        "char_count": char_count,
        "has_verb": has_verb,
        "has_declarative": has_declarative,
        "is_noun_phrase": is_noun_phrase,
        "is_character_name": is_character_name,
        "is_minimal": is_minimal,
    }


def classify_title_philosophy(labels: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Classify the author's title philosophy based on all chapter labels.

    Returns classification, confidence, evidence, and recommended strategy.
    """
    if not labels:
        return {
            "classification": "UNKNOWN",
            "confidence": 0.0,
            "evidence": {},
            "strategy": "pipeline_generated",
            "epilogue_override": None,
            "motif_catchphrase_directive": "",
        }

    signals = [extract_title_signals(l["label_jp"]) for l in labels]

    avg_chars = sum(s["char_count"] for s in signals) / len(signals)
    verb_ratio = sum(1 for s in signals if s["has_verb"]) / len(signals)
    noun_only_ratio = sum(1 for s in signals if s["is_noun_phrase"]) / len(signals)
    declarative_ratio = sum(1 for s in signals if s["has_declarative"]) / len(signals)
    character_named_count = sum(1 for s in signals if s["is_character_name"])
    clean_labels = [s["clean_label"] for s in signals]

    motif_token_hits = {
        "ムリ": sum(1 for title in clean_labels if "ムリ" in title),
        "無理": sum(1 for title in clean_labels if "無理" in title),
        "ぜったい": sum(1 for title in clean_labels if "ぜったい" in title),
        "絶対": sum(1 for title in clean_labels if "絶対" in title),
    }
    recurring_motif_detected = any(count >= 2 for count in motif_token_hits.values())

    # Detect HYBRID: story chapters are minimal, epilogue chapters are character-named
    # Heuristic: last 4 chapters with character names, rest are not
    character_named_at_end = sum(
        1 for s in signals[-4:] if s["is_character_name"]
    )
    has_epilogue_character_names = character_named_at_end >= 2

    # Classification logic
    if (avg_chars <= PHILOSOPHY_THRESHOLDS["MINIMAL_NOUN"]["avg_chars_max"]
            and noun_only_ratio >= PHILOSOPHY_THRESHOLDS["MINIMAL_NOUN"]["noun_only_ratio_min"]
            and verb_ratio <= PHILOSOPHY_THRESHOLDS["MINIMAL_NOUN"]["verb_ratio_max"]):

        classification = "MINIMAL_NOUN"
        confidence = round(
            noun_only_ratio * 0.5 +
            (1 - min(avg_chars / 7, 1)) * 0.3 +
            (1 - verb_ratio) * 0.2,
            2
        )
        strategy = "toc_direct"

    elif declarative_ratio >= PHILOSOPHY_THRESHOLDS["NARRATIVE_SENTENCE"]["declarative_ratio_min"]:
        classification = "NARRATIVE_SENTENCE"
        confidence = round(declarative_ratio, 2)
        strategy = "toc_transcreation"

    elif avg_chars >= PHILOSOPHY_THRESHOLDS["DESCRIPTIVE_PHRASE"]["avg_chars_min"]:
        classification = "DESCRIPTIVE_PHRASE"
        confidence = 0.75
        strategy = "toc_transcreation"

    else:
        classification = "HYBRID"
        confidence = 0.65
        strategy = "toc_direct"

    motif_catchphrase_directive = (
        "TITLE MOTIF CATCHPHRASE DIRECTIVE: When rendering emotional spikes, prefer recurring "
        "catchphrase rhythm aligned with the series title motif. Keep lexical family and cadence "
        "consistent across chapters so readers feel the same signature pulse each time. "
        "17a8 reference style: motif-consistent staccato panic line like 'No. Freaking. Way.' "
        "(adapt wording to scene context, do not force exact repetition)."
        if classification in {"MINIMAL_NOUN", "HYBRID"} or recurring_motif_detected
        else ""
    )

    return {
        "classification": classification,
        "confidence": confidence,
        "evidence": {
            "avg_jp_title_chars": round(avg_chars, 1),
            "verb_bearing_titles": int(verb_ratio * len(signals)),
            "declarative_titles": int(declarative_ratio * len(signals)),
            "noun_only_ratio": round(noun_only_ratio, 3),
            "character_named_count": character_named_count,
            "motif_token_hits": motif_token_hits,
            "sample_labels": [s["clean_label"] for s in signals[:4]],
        },
        "strategy": strategy,
        "epilogue_override": "character_named" if has_epilogue_character_names else None,
        "motif_catchphrase_directive": motif_catchphrase_directive,
    }


def build_toc_chapter_map(manifest: Dict, toc_labels: List[Dict]) -> Dict[str, Dict[str, Any]]:
    """
    Build mapping from chapter_id to toc label data.

    Handles two manifest chapter formats:
    1. content_src field: {"content_src": "xhtml/p-001.xhtml"}
    2. source_files array: {"source_files": ["p-001.xhtml"]}

    Returns: { "chapter_05": {"label_jp": "１　出会い", "label_en": "1. First Meeting"}, ... }
    """
    # Build content_src → chapter_id mapping from manifest
    # Support both content_src and source_files formats
    src_to_id = {}
    for ch in manifest.get("chapters", []):
        chapter_id = ch.get("id", "")
        if not chapter_id:
            continue

        # Format 1: content_src field
        src = ch.get("content_src", "")
        if src:
            src_to_id[src] = chapter_id
            src_to_id[src.split("#")[0]] = chapter_id  # also map without anchor

        # Format 2: source_files array (e.g., ["p-001.xhtml"])
        for sf in ch.get("source_files", []):
            src_to_id[sf] = chapter_id
            # Also map with common xhtml/ prefix
            src_to_id[f"xhtml/{sf}"] = chapter_id

    result = {}
    for nav in toc_labels:
        raw_src = nav.get("content_src", "")
        src_no_anchor = raw_src.split("#")[0]  # strip anchor
        src_basename = src_no_anchor.split("/")[-1]  # strip path prefix

        # Try multiple lookup keys
        chapter_id = (
            src_to_id.get(raw_src)
            or src_to_id.get(src_no_anchor)
            or src_to_id.get(src_basename)
        )

        if chapter_id:
            result[chapter_id] = {
                "label_jp": nav.get("label_jp", ""),
                "label_en": nav.get("label_en", ""),
                "play_order": nav.get("play_order", 0),
            }

    logger.info(f"Built toc_chapter_map with {len(result)} entries")
    return result
    return result


def detect_epilogue_chapters(toc_chapter_map: Dict, title_philosophy: Dict) -> set:
    """
    Detect epilogue chapters based on position and character-name signal.

    Epilogue heuristic: character-named chapters in the final 25% of story.
    """
    if title_philosophy.get("epilogue_override") != "character_named":
        return set()

    sorted_chapters = sorted(
        toc_chapter_map.items(),
        key=lambda x: x[1]["play_order"]
    )
    story_count = len(sorted_chapters)
    tail_start = int(story_count * 0.75)

    epilogue_ids = set()
    for i, (chapter_id, nav_data) in enumerate(sorted_chapters):
        if i >= tail_start:
            signals = extract_title_signals(nav_data["label_jp"])
            if signals["is_character_name"]:
                epilogue_ids.add(chapter_id)

    logger.info(f"Detected {len(epilogue_ids)} epilogue chapters: {epilogue_ids}")
    return epilogue_ids


def strip_chapter_number_prefix(label_en: str) -> str:
    """Strip numeric prefix from English label (e.g., '3. Love' → 'Love')."""
    return re.sub(r'^[\d０-９]+\.?\s*', '', label_en).strip()


def apply_toc_direct_titles(
    toc_chapter_map: Dict[str, Dict],
    title_philosophy: Dict,
    metadata_en_path: Path,
) -> Dict[str, Any]:
    """
    Apply toc_direct strategy: write title_en directly from toc.json label_en.

    Updates metadata_en.json chapters with:
    - title_en: stripped toc label_en
    - title_pipeline: (placeholder, will be filled by Phase 1.55)
    - title_source: "toc_direct"
    """
    if not metadata_en_path.exists():
        logger.warning(f"metadata_en.json not found: {metadata_en_path}")
        return {}

    with open(metadata_en_path, encoding="utf-8") as f:
        metadata_en = json.load(f)

    epilogue_ids = detect_epilogue_chapters(toc_chapter_map, title_philosophy)
    updated_count = 0

    chapters = metadata_en.get("chapters", {})
    if isinstance(chapters, dict):
        for chapter_id, nav_data in toc_chapter_map.items():
            if chapter_id not in chapters:
                continue

            is_epilogue = chapter_id in epilogue_ids
            existing_title_en = chapters[chapter_id].get("title_en", "")

            # Try to get title from toc, fall back to existing
            label_en = nav_data.get("label_en", "")
            title_en = strip_chapter_number_prefix(label_en) if label_en else existing_title_en

            # For epilogue chapters with character names, use the character name
            if is_epilogue:
                signals = extract_title_signals(nav_data.get("label_jp", ""))
                if signals["is_character_name"]:
                    # Keep the full label for character names
                    title_en = signals["clean_label"]

            # Only update if we have a valid title
            if title_en:
                # Preserve existing title_pipeline if it exists
                existing_pipeline = chapters[chapter_id].get("title_pipeline", "")

                chapters[chapter_id]["title_en"] = title_en
                chapters[chapter_id]["title_source"] = "toc_direct"
                if existing_pipeline:
                    chapters[chapter_id]["title_pipeline"] = existing_pipeline

                updated_count += 1

    logger.info(f"Applied toc_direct titles to {updated_count} chapters")

    # Write back to metadata_en.json
    with open(metadata_en_path, "w", encoding="utf-8") as f:
        json.dump(metadata_en, f, indent=2, ensure_ascii=False)

    return metadata_en


def update_manifest_title_philosophy(
    manifest_path: Path,
    title_philosophy: Dict,
) -> None:
    """Update manifest.json with title_philosophy analysis result."""
    if not manifest_path.exists():
        logger.error(f"manifest.json not found: {manifest_path}")
        return

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    # Add title_philosophy to manifest
    title_philosophy["analyzed_at"] = datetime.datetime.now().isoformat()
    manifest["title_philosophy"] = title_philosophy

    # Write back
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    logger.info(f"Updated manifest.json with title_philosophy: {title_philosophy['classification']}")


def run_title_philosophy_analyzer(volume_dir: Path) -> bool:
    """
    Main entry point: Run title philosophy analysis on a volume.

    Steps:
    1. Load toc.json
    2. Load manifest.json
    3. Classify title philosophy
    4. Update manifest.json with title_philosophy
    5. Apply toc_direct titles to metadata_en.json (if strategy == toc_direct)
    """
    volume_id = volume_dir.name
    logger.info(f"=" * 60)
    logger.info(f"Title Philosophy Analyzer - Volume: {volume_id}")
    logger.info(f"=" * 60)

    toc_path = volume_dir / "toc.json"
    manifest_path = volume_dir / "manifest.json"
    metadata_en_path = volume_dir / "metadata_en.json"

    # Step 1: Load toc.json
    toc_labels = load_story_labels(toc_path)
    if not toc_labels:
        logger.warning("No story labels found in toc.json - skipping analysis")
        return True

    # Step 2: Load manifest.json
    if not manifest_path.exists():
        logger.error(f"manifest.json not found: {manifest_path}")
        return False

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    # Step 3: Classify title philosophy
    title_philosophy = classify_title_philosophy(toc_labels)
    logger.info(f"Classification: {title_philosophy['classification']} (confidence: {title_philosophy['confidence']})")
    logger.info(f"Strategy: {title_philosophy['strategy']}")
    logger.info(f"Evidence: {title_philosophy['evidence']}")

    # Step 4: Update manifest.json
    update_manifest_title_philosophy(manifest_path, title_philosophy)

    # Step 5: Apply toc_direct titles if applicable
    if title_philosophy["strategy"] == "toc_direct":
        toc_chapter_map = build_toc_chapter_map(manifest, toc_labels)
        apply_toc_direct_titles(toc_chapter_map, title_philosophy, metadata_en_path)

    logger.info("✓ Title Philosophy Analyzer completed successfully")
    return True


def main():
    parser = argparse.ArgumentParser(description="Title Philosophy Analyzer (Phase 1.15)")
    parser.add_argument("--volume", required=True, help="Volume ID (e.g., 116c)")
    parser.add_argument(
        "--work-dir",
        default=None,
        help="Working directory (default: ./work)",
    )
    args = parser.parse_args()

    # Resolve work directory
    if args.work_dir:
        work_dir = Path(args.work_dir)
    else:
        # Default: ./work in pipeline root
        pipeline_root = Path(__file__).parent.parent
        work_dir = pipeline_root / "work"

    volume_dir = work_dir / args.volume

    if not volume_dir.exists():
        logger.error(f"Volume directory not found: {volume_dir}")
        sys.exit(1)

    success = run_title_philosophy_analyzer(volume_dir)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

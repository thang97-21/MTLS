#!/usr/bin/env python3
"""
Extract sentence patterns from Official_Repo professional translations.

Usage:
    python scripts/extract_official_corpus.py

Output:
    - Official_Repo/extracted/*.txt (plain text from EPUBs)
    - pipeline/config/official_reference_patterns.json (pattern database)
"""

import json
import logging
import re
from collections import Counter
from pathlib import Path
from statistics import mean, stdev
from typing import Dict, List, Tuple

try:
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup
except ImportError:
    print("Error: Missing dependencies. Install with:")
    print("  pip install ebooklib beautifulsoup4")
    exit(1)

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def parse_epub_to_text(epub_path: Path) -> str:
    """Extract all text content from EPUB file."""
    try:
        book = epub.read_epub(str(epub_path))
    except Exception as e:
        logger.error(f"Failed to read {epub_path.name}: {e}")
        return ""

    text_parts = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        try:
            content = item.get_content()
            soup = BeautifulSoup(content, 'html.parser')
            # Remove script/style tags
            for script in soup(["script", "style"]):
                script.decompose()
            text = soup.get_text()
            # Clean up whitespace
            text = re.sub(r'\n\s*\n', '\n\n', text)
            text_parts.append(text.strip())
        except Exception as e:
            logger.warning(f"Failed to parse item in {epub_path.name}: {e}")
            continue

    return '\n\n'.join(text_parts)


def split_sentences(text: str) -> List[str]:
    """Split text into sentences (simple regex-based)."""
    # Split on period, exclamation, question mark followed by space + capital
    pattern = r'(?<=[.!?])\s+(?=[A-Z"])'
    sentences = re.split(pattern, text)
    return [s.strip() for s in sentences if s.strip()]


def is_dialogue(sentence: str) -> bool:
    """Check if sentence contains dialogue (quoted text)."""
    return '"' in sentence or '"' in sentence or '"' in sentence


def extract_dialogue(text: str) -> List[str]:
    """Extract all dialogue lines (content within quotes)."""
    # Match content within quotes
    pattern = r'[""][^"""]+[""]'
    dialogues = re.findall(pattern, text)
    # Clean quotes
    return [d.strip('"""') for d in dialogues]


def extract_narration(text: str) -> str:
    """Extract narration by removing dialogue."""
    # Remove quoted content
    narration = re.sub(r'[""][^"""]+[""]', '', text)
    # Clean up extra whitespace
    narration = re.sub(r'\s+', ' ', narration)
    return narration.strip()


def analyze_sentence_patterns(text: str) -> Dict:
    """Analyze sentence patterns in text."""
    sentences = split_sentences(text)
    dialogues = [s for s in sentences if is_dialogue(s)]
    narration_sentences = [s for s in sentences if not is_dialogue(s)]

    # Extract dialogue content
    dialogue_content = extract_dialogue(text)

    # Calculate metrics
    dialogue_lengths = [len(d.split()) for d in dialogue_content if d]
    narration_lengths = [len(s.split()) for s in narration_sentences if s]

    return {
        'total_sentences': len(sentences),
        'dialogue_count': len(dialogue_content),
        'narration_count': len(narration_sentences),
        'dialogue': {
            'avg_length': mean(dialogue_lengths) if dialogue_lengths else 0,
            'length_std': stdev(dialogue_lengths) if len(dialogue_lengths) > 1 else 0,
            'lengths': dialogue_lengths[:100],  # Sample
        },
        'narration': {
            'avg_length': mean(narration_lengths) if narration_lengths else 0,
            'length_std': stdev(narration_lengths) if len(narration_lengths) > 1 else 0,
            'lengths': narration_lengths[:100],  # Sample
        }
    }


def analyze_tense_usage(text: str) -> Dict:
    """Analyze past vs present tense usage."""
    narration = extract_narration(text)

    # Simple tense detection
    present_verbs = len(re.findall(r'\b(is|are|am|has|have|does|do)\b', narration, re.IGNORECASE))
    past_verbs = len(re.findall(r'\b(was|were|had|did|went|came|said|looked)\b', narration, re.IGNORECASE))

    total_verbs = present_verbs + past_verbs

    return {
        'present_count': present_verbs,
        'past_count': past_verbs,
        'past_ratio': past_verbs / total_verbs if total_verbs > 0 else 0,
        'present_ratio': present_verbs / total_verbs if total_verbs > 0 else 0,
    }


def verify_ai_isms(text: str) -> Dict:
    """Check for AI-ism patterns in professional translation."""
    patterns = {
        'couldnt_help_but': r"couldn't help but \w+",
        'a_sense_of': r'a sense of \w+',
        'heavy_with': r'heavy with \w+',
        'drilling_into': r'\w+-drilling into',
        'locked_in_volley': r'locked in a \w+ volley',
        'welled_up': r'\w+ welled up',
        'fleeting_swept_away': r'fleeting \w+ was swept away',
    }

    results = {}
    for pattern_id, regex in patterns.items():
        matches = re.findall(regex, text, re.IGNORECASE)
        results[pattern_id] = {
            'count': len(matches),
            'examples': matches[:3] if matches else []
        }

    return results


def main():
    """Main extraction workflow."""
    official_repo = Path('Official_Repo')
    output_dir = official_repo / 'extracted'
    output_dir.mkdir(exist_ok=True)

    # Find all EPUBs
    epub_files = sorted(official_repo.glob('*.epub'))
    logger.info(f"Found {len(epub_files)} EPUB files in Official_Repo")

    if not epub_files:
        logger.error("No EPUB files found. Check Official_Repo directory.")
        return

    # Extract text from each EPUB
    all_patterns = []
    all_tense_data = []
    all_ai_ism_checks = []

    for epub_path in epub_files:
        logger.info(f"Processing: {epub_path.name}")

        # Parse EPUB
        text = parse_epub_to_text(epub_path)
        if not text:
            logger.warning(f"  Skipped (no text extracted)")
            continue

        # Save plain text
        txt_path = output_dir / f"{epub_path.stem}.txt"
        txt_path.write_text(text, encoding='utf-8')
        logger.info(f"  Saved: {txt_path.name} ({len(text)} chars)")

        # Analyze patterns
        patterns = analyze_sentence_patterns(text)
        tense_data = analyze_tense_usage(text)
        ai_ism_check = verify_ai_isms(text)

        all_patterns.append(patterns)
        all_tense_data.append(tense_data)
        all_ai_ism_checks.append(ai_ism_check)

        logger.info(f"  Dialogue avg: {patterns['dialogue']['avg_length']:.1f}w")
        logger.info(f"  Narration avg: {patterns['narration']['avg_length']:.1f}w")
        logger.info(f"  Past tense ratio: {tense_data['past_ratio']:.2%}")

    # Aggregate results
    logger.info("\n" + "="*60)
    logger.info("Aggregating patterns from all volumes...")

    dialogue_avgs = [p['dialogue']['avg_length'] for p in all_patterns if p['dialogue']['avg_length'] > 0]
    narration_avgs = [p['narration']['avg_length'] for p in all_patterns if p['narration']['avg_length'] > 0]
    past_ratios = [t['past_ratio'] for t in all_tense_data]

    # AI-ism aggregation
    ai_ism_totals = {}
    for pattern_id in all_ai_ism_checks[0].keys():
        total_count = sum(check[pattern_id]['count'] for check in all_ai_ism_checks)
        ai_ism_totals[pattern_id] = {
            'total_count': total_count,
            'avg_per_volume': total_count / len(epub_files)
        }

    # Build reference database
    reference_patterns = {
        'metadata': {
            'total_volumes': len(epub_files),
            'extraction_date': '2026-02-18',
            'publishers': ['Seven Seas', 'Yen Press'],
            'source': 'Official_Repo professional translations'
        },
        'dialogue_patterns': {
            'avg_length': mean(dialogue_avgs),
            'length_std': stdev(dialogue_avgs) if len(dialogue_avgs) > 1 else 0,
            'sample_count': len(dialogue_avgs)
        },
        'narration_patterns': {
            'avg_length': mean(narration_avgs),
            'length_std': stdev(narration_avgs) if len(narration_avgs) > 1 else 0,
            'sample_count': len(narration_avgs)
        },
        'tense_benchmarks': {
            'narration_past_ratio': mean(past_ratios),
            'past_ratio_std': stdev(past_ratios) if len(past_ratios) > 1 else 0
        },
        'ai_ism_verification': ai_ism_totals
    }

    # Save reference database
    config_path = Path('pipeline/config/official_reference_patterns.json')
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(reference_patterns, f, indent=2, ensure_ascii=False)

    logger.info(f"\n✅ Reference database saved: {config_path}")
    logger.info("\nProfessional Translation Benchmarks:")
    logger.info(f"  Dialogue avg: {reference_patterns['dialogue_patterns']['avg_length']:.1f}w")
    logger.info(f"  Narration avg: {reference_patterns['narration_patterns']['avg_length']:.1f}w")
    logger.info(f"  Past tense ratio: {reference_patterns['tense_benchmarks']['narration_past_ratio']:.2%}")
    logger.info("\nAI-ism Verification (0 = safe to auto-fix):")
    for pattern_id, data in ai_ism_totals.items():
        logger.info(f"  {pattern_id}: {data['total_count']} instances ({data['avg_per_volume']:.2f}/vol)")

    logger.info("\n" + "="*60)
    logger.info(f"Extraction complete! Processed {len(epub_files)} volumes.")
    logger.info(f"Plain text files: {output_dir}")
    logger.info(f"Reference patterns: {config_path}")


if __name__ == '__main__':
    main()

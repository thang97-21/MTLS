#!/usr/bin/env python3
"""
Extract mood-tagged stylistic examples from Official_Repo professional translations.

This script identifies passages with specific moods (melancholy, romantic tension, comedy, etc.)
and extracts them as curated examples for literacy_techniques.json enrichment.

Usage:
    python scripts/extract_mood_tagged_examples.py

Output:
    pipeline/config/professional_style_examples.json
"""

import json
import re
from pathlib import Path
from typing import List, Dict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Mood detection patterns (keyword-based heuristics)
MOOD_PATTERNS = {
    "melancholic_introspection": [
        r'\b(miserable|lonely|empty|hollow|ache|longing|regret|sorrow)\b',
        r'\b(silence|quiet|stillness|void)\b.*\b(heavy|oppressive|suffocating)\b',
        r'\b(stared|gazed|watched)\b.*\b(distant|far|away|past)\b',
    ],
    "romantic_tension": [
        r'\b(heart|pulse|breath)\b.*\b(raced|pounded|caught|stopped|skipped)\b',
        r'\b(eyes? met|gaze held|locked eyes)\b',
        r'\b(closer|distance|gap|space between)\b.*\b(narrow|shrink|close|inch)\b',
        r'\b(touch|hand|fingers?)\b.*\b(brush|graze|linger|hover)\b',
    ],
    "comedic_timing": [
        r'—[A-Z]',  # Em-dash before capitalized word (punchline)
        r'\.\.\.[A-Z]',  # Ellipsis before capitalized word (beat before punchline)
        r'\b(seriously|honestly|wait|hold on|excuse me)\?+\b',  # Incredulous reactions
    ],
    "action_urgency": [
        r'\b(ran|sprinted|bolted|dashed|rushed)\b',
        r'\b(now|immediately|quickly|fast|hurry)\b',
        r'\b(slam|crash|burst|explode|shatter)\b',
    ],
    "literary_poetic": [
        r'\b(petals?|blossoms?|rain|mist|fog|dusk|dawn|twilight)\b.*\b(drifted?|fell|descended|settled)\b',
        r'\b(silver|golden|crimson|azure|emerald)\b.*\b(light|glow|shimmer|gleam)\b',
    ],
}


def detect_mood(paragraph: str) -> List[str]:
    """Detect moods in a paragraph based on keyword patterns."""
    moods = []
    para_lower = paragraph.lower()

    for mood, patterns in MOOD_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, para_lower, re.IGNORECASE):
                moods.append(mood)
                break  # One match per mood is enough

    return moods


def extract_mood_examples(text_path: Path) -> Dict[str, List[str]]:
    """Extract mood-tagged examples from a single text file."""
    text = text_path.read_text(encoding='utf-8')
    paragraphs = text.split('\n\n')

    mood_examples = {mood: [] for mood in MOOD_PATTERNS.keys()}

    for para in paragraphs:
        para = para.strip()
        if len(para) < 50:  # Skip very short paragraphs
            continue

        moods = detect_mood(para)
        for mood in moods:
            if len(mood_examples[mood]) < 5:  # Limit to 5 examples per mood per book
                # Clean up paragraph (remove page numbers, extra whitespace)
                clean_para = re.sub(r'\s+', ' ', para).strip()
                if len(clean_para) > 100 and len(clean_para) < 500:  # Reasonable length
                    mood_examples[mood].append(clean_para[:300])  # Truncate to 300 chars

    return mood_examples


def main():
    """Extract mood-tagged examples from all Official_Repo texts."""
    extracted_dir = Path('Official_Repo/extracted')
    if not extracted_dir.exists():
        logger.error("Official_Repo/extracted not found. Run extract_official_corpus.py first.")
        return

    # Aggregate examples from all texts
    all_mood_examples = {mood: [] for mood in MOOD_PATTERNS.keys()}

    text_files = sorted(extracted_dir.glob('*.txt'))
    logger.info(f"Processing {len(text_files)} text files...")

    for text_path in text_files:
        logger.info(f"  Processing: {text_path.name}")
        mood_examples = extract_mood_examples(text_path)

        for mood, examples in mood_examples.items():
            all_mood_examples[mood].extend(examples)

    # Limit to top 10 examples per mood (most representative)
    for mood in all_mood_examples:
        all_mood_examples[mood] = all_mood_examples[mood][:10]

    # Save to JSON
    output = {
        "metadata": {
            "source": "Official_Repo professional translations (50 volumes)",
            "extraction_date": "2026-02-18",
            "publishers": ["Seven Seas", "Yen Press"],
            "total_moods": len(MOOD_PATTERNS),
        },
        "mood_examples": all_mood_examples,
        "mood_counts": {
            mood: len(examples)
            for mood, examples in all_mood_examples.items()
        }
    }

    output_path = Path('pipeline/config/professional_style_examples.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    logger.info(f"\n✅ Mood-tagged examples saved: {output_path}")
    logger.info("\nMood Example Counts:")
    for mood, count in output['mood_counts'].items():
        logger.info(f"  {mood}: {count} examples")


if __name__ == '__main__':
    main()

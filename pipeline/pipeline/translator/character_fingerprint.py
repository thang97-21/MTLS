"""
Character Fingerprint Database — Phase 5 of Koji Fox Expansion

Tracks signature phrases and speech patterns per character across volumes.
Extracts quantitative voice metrics from translated dialogue and stores
them in .context/character_fingerprints/<character_id>.json.

Validation: After new translation, checks if fingerprint patterns appear.
If a character uses 0 signature patterns in a chapter → flag.
"""

import json
import re
import logging
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class CharacterFingerprint:
    """Unique speech signature for a character."""
    character_id: str
    canonical_name_en: str
    archetype: str = "unknown"

    # Qualitative signature
    signature_phrases: List[str] = field(default_factory=list)   # "Whatever!", "As if!"
    catchphrases: List[str] = field(default_factory=list)        # Recurring expressions
    verbal_tics: List[str] = field(default_factory=list)         # "like...", "um...", "well..."
    sentence_starters: List[str] = field(default_factory=list)   # How they begin sentences
    emotional_patterns: Dict[str, List[str]] = field(default_factory=dict)  # emotion → responses

    # Quantitative metrics
    avg_sentence_length: float = 0.0
    contraction_rate: float = 0.0
    question_frequency: float = 0.0   # Fraction of sentences that are questions
    fragment_rate: float = 0.0        # Fraction of sentences that are fragments (≤4 words)

    # Signature constructions
    signature_structures: List[str] = field(default_factory=list)  # e.g., "Statement + rhetorical question"

    # Metadata
    dialogue_sample_count: int = 0
    volumes_seen: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "CharacterFingerprint":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class CharacterFingerprintDB:
    """
    Extracts and persists character speech fingerprints from translated text.

    Usage:
        db = CharacterFingerprintDB(work_dir)
        db.extract_from_chapter(translated_text, character_names, volume_id)
        db.save()

        # Validate new translation
        missing = db.validate_chapter(translated_text, character_names)
        if missing:
            # flag for re-translation
    """

    def __init__(self, work_dir: Path):
        self.work_dir = work_dir
        self.fp_dir = work_dir / ".context" / "character_fingerprints"
        self.fp_dir.mkdir(parents=True, exist_ok=True)
        self._fingerprints: Dict[str, CharacterFingerprint] = {}

    # ─── Persistence ─────────────────────────────────────────────────────────

    def load(self, character_id: str) -> Optional[CharacterFingerprint]:
        """Load fingerprint for a character from disk."""
        path = self.fp_dir / f"{character_id.lower()}.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return CharacterFingerprint.from_dict(json.load(f))

    def save(self, fingerprint: CharacterFingerprint) -> None:
        """Save a fingerprint to disk."""
        path = self.fp_dir / f"{fingerprint.character_id.lower()}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fingerprint.to_dict(), f, indent=2, ensure_ascii=False)

    def load_all(self) -> Dict[str, CharacterFingerprint]:
        """Load all fingerprints from disk."""
        result = {}
        for path in self.fp_dir.glob("*.json"):
            try:
                with open(path, encoding="utf-8") as f:
                    fp = CharacterFingerprint.from_dict(json.load(f))
                result[fp.character_id.lower()] = fp
            except Exception as e:
                logger.warning(f"Failed to load fingerprint {path.name}: {e}")
        return result

    # ─── Extraction ──────────────────────────────────────────────────────────

    def extract_from_chapter(
        self,
        translated_text: str,
        character_names: List[str],
        volume_id: str,
        voice_fingerprints: Optional[List[Dict]] = None,
    ) -> List[CharacterFingerprint]:
        """
        Extract speech fingerprints from a translated chapter.

        Args:
            translated_text: Full translated chapter text
            character_names: List of canonical EN character names
            volume_id: Current volume ID for tracking
            voice_fingerprints: Optional pre-extracted fingerprints from metadata

        Returns:
            List of updated CharacterFingerprint objects
        """
        updated = []

        # Build archetype map from metadata fingerprints
        archetype_map: Dict[str, str] = {}
        if voice_fingerprints:
            for vfp in voice_fingerprints:
                name = vfp.get("canonical_name_en", "").lower()
                if name:
                    archetype_map[name] = vfp.get("archetype", "unknown")

        for name in character_names:
            char_id = name.lower().replace(" ", "_")
            dialogue_lines = self._extract_character_dialogue(translated_text, name)
            if not dialogue_lines:
                continue

            # Load existing or create new
            fp = self.load(char_id) or CharacterFingerprint(
                character_id=char_id,
                canonical_name_en=name,
                archetype=archetype_map.get(name.lower(), "unknown"),
            )

            # Update metrics
            fp = self._update_metrics(fp, dialogue_lines)

            # Track volume
            if volume_id and volume_id not in fp.volumes_seen:
                fp.volumes_seen.append(volume_id)

            self.save(fp)
            updated.append(fp)

        return updated

    def _update_metrics(
        self, fp: CharacterFingerprint, dialogue_lines: List[str]
    ) -> CharacterFingerprint:
        """Update quantitative metrics from new dialogue lines."""
        if not dialogue_lines:
            return fp

        all_text = " ".join(dialogue_lines)
        fp.dialogue_sample_count += len(dialogue_lines)

        # Sentence length
        words_per_line = [len(line.split()) for line in dialogue_lines]
        if words_per_line:
            new_avg = sum(words_per_line) / len(words_per_line)
            # Rolling average
            if fp.avg_sentence_length == 0:
                fp.avg_sentence_length = new_avg
            else:
                fp.avg_sentence_length = (fp.avg_sentence_length + new_avg) / 2

        # Contraction rate
        contraction_pattern = re.compile(
            r"\b(I'm|I've|I'd|I'll|you're|don't|doesn't|didn't|won't|can't|"
            r"couldn't|shouldn't|isn't|aren't|wasn't|weren't|haven't|hasn't|"
            r"hadn't|that's|there's|it's|he's|she's|we're|they're)\b",
            re.IGNORECASE
        )
        words = all_text.split()
        contractions = len(contraction_pattern.findall(all_text))
        if words:
            new_rate = contractions / len(words)
            fp.contraction_rate = (fp.contraction_rate + new_rate) / 2

        # Question frequency
        questions = sum(1 for line in dialogue_lines if line.strip().endswith("?"))
        fp.question_frequency = questions / len(dialogue_lines)

        # Fragment rate (≤4 words)
        fragments = sum(1 for line in dialogue_lines if len(line.split()) <= 4)
        fp.fragment_rate = fragments / len(dialogue_lines)

        # Sentence starters (first 1-2 words)
        starters = Counter()
        for line in dialogue_lines:
            words_in_line = line.split()
            if words_in_line:
                starter = " ".join(words_in_line[:2])
                starters[starter] += 1

        # Keep top 5 starters
        top_starters = [s for s, _ in starters.most_common(5)]
        fp.sentence_starters = list(dict.fromkeys(fp.sentence_starters + top_starters))[:10]

        # Signature phrases: frequent 3-5 word phrases
        phrase_counter = Counter()
        for line in dialogue_lines:
            words_in_line = line.split()
            for n in (3, 4, 5):
                for i in range(len(words_in_line) - n + 1):
                    phrase = " ".join(words_in_line[i:i+n])
                    if not re.search(r'\b(the|a|an|and|or|but|in|on|at|to|for|of|with|by)\b', phrase, re.IGNORECASE):
                        phrase_counter[phrase] += 1

        new_signatures = [p for p, c in phrase_counter.most_common(10) if c >= 2]
        fp.signature_phrases = list(dict.fromkeys(fp.signature_phrases + new_signatures))[:15]

        return fp

    def _extract_character_dialogue(self, text: str, character_name: str) -> List[str]:
        """Extract dialogue lines attributed to a character."""
        name_escaped = re.escape(character_name)
        pattern = re.compile(
            rf'(?:{name_escaped}[^"{{}}]*?"([^"]+)")|(?:"([^"]+)"[^"{{}}]*?{name_escaped})',
            re.IGNORECASE
        )
        lines = []
        for m in pattern.finditer(text):
            dialogue = m.group(1) or m.group(2)
            if dialogue:
                lines.append(dialogue.strip())
        return lines

    # ─── Validation ──────────────────────────────────────────────────────────

    def validate_chapter(
        self,
        translated_text: str,
        character_names: List[str],
        min_signature_matches: int = 1,
    ) -> List[str]:
        """
        Check if characters use their signature patterns in a chapter.

        Returns list of character names with 0 signature pattern matches (flagged).
        """
        flagged = []
        for name in character_names:
            char_id = name.lower().replace(" ", "_")
            fp = self.load(char_id)
            if not fp or not fp.signature_phrases:
                continue

            dialogue_lines = self._extract_character_dialogue(translated_text, name)
            if len(dialogue_lines) < 3:
                continue  # Not enough dialogue to validate

            all_dialogue = " ".join(dialogue_lines).lower()
            matches = sum(
                1 for phrase in fp.signature_phrases
                if phrase.lower() in all_dialogue
            )

            if matches < min_signature_matches:
                flagged.append(name)
                logger.warning(
                    f"Voice fingerprint: {name} used 0/{len(fp.signature_phrases)} "
                    f"signature patterns in this chapter"
                )

        return flagged

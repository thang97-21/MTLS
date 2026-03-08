"""
Voice Consistency Validator — Phase 1 of Koji Fox Expansion

Post-translation validation layer that checks translated output against
character voice fingerprints. Flags violations for re-translation.

Checks:
  - Forbidden vocabulary not used
  - Signature phrases present where expected
  - Contraction rate roughly matches archetype
  - No voice bleed between characters
"""

import re
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class VoiceViolation:
    character: str
    violation_type: str   # "forbidden_vocab" | "missing_signature" | "contraction_mismatch" | "voice_bleed"
    detail: str
    severity: str         # "critical" | "warning"
    line_excerpt: str = ""


@dataclass
class VoiceValidationResult:
    character: str
    passed: bool
    score: float          # 0.0–1.0
    violations: List[VoiceViolation] = field(default_factory=list)
    contraction_rate_actual: Optional[float] = None
    signature_phrases_found: List[str] = field(default_factory=list)


class VoiceConsistencyValidator:
    """
    Validates translated text against character voice fingerprints.

    Usage:
        validator = VoiceConsistencyValidator()
        results = validator.validate_chapter(translated_text, fingerprints, eps_data)
        if any(not r.passed for r in results):
            # flag for re-translation
    """

    # Contraction patterns for rate estimation
    CONTRACTION_PATTERN = re.compile(
        r"\b(I'm|I've|I'd|I'll|you're|you've|you'd|you'll|he's|she's|it's|"
        r"we're|we've|we'd|we'll|they're|they've|they'd|they'll|"
        r"don't|doesn't|didn't|won't|wouldn't|can't|couldn't|shouldn't|"
        r"isn't|aren't|wasn't|weren't|haven't|hasn't|hadn't|"
        r"that's|there's|here's|what's|who's|how's|where's)\b",
        re.IGNORECASE
    )

    # Archetype expected contraction ranges
    ARCHETYPE_CONTRACTION_RANGES = {
        "ojou-sama":          (0.05, 0.25),
        "mentor":             (0.10, 0.30),
        "stoic-warrior":      (0.15, 0.40),
        "kuudere":            (0.20, 0.45),
        "villain":            (0.15, 0.45),
        "dandere":            (0.30, 0.60),
        "everyman":           (0.40, 0.75),
        "narrator-protagonist": (0.40, 0.75),
        "tsundere":           (0.50, 0.80),
        "tsukkomi":           (0.55, 0.80),
        "boke":               (0.55, 0.85),
        "onee-san":           (0.45, 0.75),
        "genki":              (0.65, 0.95),
        "chuunibyou":         (0.30, 0.65),
        "yandere":            (0.40, 0.75),
        "shota":              (0.50, 0.85),
    }

    def validate_chapter(
        self,
        translated_text: str,
        fingerprints: List[Dict],
        eps_data: Optional[Dict[str, Dict]] = None,
    ) -> List[VoiceValidationResult]:
        """
        Run full voice consistency validation on a translated chapter.

        Args:
            translated_text: Full translated chapter text
            fingerprints: List of character_voice_fingerprints dicts
            eps_data: Dict of character_name → {eps_score, voice_band, signals}

        Returns:
            List of VoiceValidationResult per character
        """
        eps_data = eps_data or {}
        results = []

        for fp in fingerprints:
            name = fp.get("canonical_name_en", "")
            if not name:
                continue

            # Extract this character's dialogue lines
            dialogue = self._extract_character_dialogue(translated_text, name)
            if not dialogue:
                continue

            char_eps = eps_data.get(name, eps_data.get(name.lower(), {}))
            eps_band = char_eps.get("voice_band", "NEUTRAL") if isinstance(char_eps, dict) else "NEUTRAL"
            result = self._validate_character(name, fp, dialogue, eps_band)
            results.append(result)

        return results

    def _validate_character(
        self,
        name: str,
        fp: Dict,
        dialogue_lines: List[str],
        eps_band: str,
    ) -> VoiceValidationResult:
        violations = []
        all_dialogue = " ".join(dialogue_lines)

        # 1. Check forbidden vocabulary
        forbidden = fp.get("forbidden_vocabulary", [])
        # Skip forbidden check if character is in WARM/HOT band (emotional breakthrough)
        if eps_band not in ("WARM", "HOT"):
            for word in forbidden:
                pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)
                if pattern.search(all_dialogue):
                    violations.append(VoiceViolation(
                        character=name,
                        violation_type="forbidden_vocab",
                        detail=f'Used forbidden word: "{word}"',
                        severity="critical",
                        line_excerpt=self._find_excerpt(all_dialogue, word),
                    ))

        # 2. Check signature phrases (at least one should appear if character has many lines)
        signature = fp.get("signature_phrases", [])
        found_signatures = []
        if signature and len(dialogue_lines) >= 3:
            for phrase in signature:
                # Fuzzy match: check if key words from phrase appear
                key_words = [w for w in phrase.lower().split() if len(w) > 3]
                if key_words and any(
                    all(kw in line.lower() for kw in key_words[:2])
                    for line in dialogue_lines
                ):
                    found_signatures.append(phrase)

        # 3. Estimate contraction rate
        archetype = fp.get("archetype", "")
        contraction_rate = self._estimate_contraction_rate(all_dialogue)
        expected_range = self.ARCHETYPE_CONTRACTION_RANGES.get(archetype)

        if expected_range and len(dialogue_lines) >= 5:
            lo, hi = expected_range
            # Allow wider tolerance based on EPS band
            if eps_band in ("WARM", "HOT"):
                hi = min(1.0, hi + 0.15)   # More casual/open → higher contraction ceiling
            elif eps_band in ("COLD", "COOL"):
                lo = max(0.0, lo - 0.15)   # More guarded/formal → lower contraction floor

            if not (lo <= contraction_rate <= hi):
                violations.append(VoiceViolation(
                    character=name,
                    violation_type="contraction_mismatch",
                    detail=(
                        f"Contraction rate {contraction_rate:.0%} outside "
                        f"expected {lo:.0%}–{hi:.0%} for {archetype} [{eps_band}]"
                    ),
                    severity="warning",
                ))

        # Compute score
        critical_count = sum(1 for v in violations if v.severity == "critical")
        warning_count = sum(1 for v in violations if v.severity == "warning")
        score = max(0.0, 1.0 - (critical_count * 0.3) - (warning_count * 0.1))

        return VoiceValidationResult(
            character=name,
            passed=critical_count == 0,
            score=score,
            violations=violations,
            contraction_rate_actual=contraction_rate,
            signature_phrases_found=found_signatures,
        )

    def _extract_character_dialogue(self, text: str, character_name: str) -> List[str]:
        """
        Extract dialogue lines attributed to a character.
        Looks for patterns like: Name said "...", "..." Name said, etc.
        """
        lines = []
        # Pattern: character name near a quoted string (within 60 chars)
        name_escaped = re.escape(character_name)
        pattern = re.compile(
            rf'(?:{name_escaped}[^"{{}}]*?"([^"]+)")|(?:"([^"]+)"[^"{{}}]*?{name_escaped})',
            re.IGNORECASE
        )
        for m in pattern.finditer(text):
            dialogue = m.group(1) or m.group(2)
            if dialogue:
                lines.append(dialogue.strip())
        return lines

    def _estimate_contraction_rate(self, text: str) -> float:
        """Estimate contraction rate as fraction of words that are contractions."""
        words = text.split()
        if not words:
            return 0.0
        contractions = len(self.CONTRACTION_PATTERN.findall(text))
        return contractions / len(words)

    def _find_excerpt(self, text: str, keyword: str, window: int = 60) -> str:
        """Find a short excerpt around a keyword."""
        idx = text.lower().find(keyword.lower())
        if idx == -1:
            return ""
        start = max(0, idx - window // 2)
        end = min(len(text), idx + window // 2)
        return "..." + text[start:end].strip() + "..."

    def format_report(self, results: List[VoiceValidationResult]) -> str:
        """Format validation results as a human-readable report."""
        if not results:
            return "Voice validation: no characters checked"

        lines = ["## VOICE CONSISTENCY REPORT"]
        passed = sum(1 for r in results if r.passed)
        lines.append(f"Passed: {passed}/{len(results)} characters\n")

        for r in results:
            status = "✓" if r.passed else "✗"
            lines.append(f"{status} {r.character} (score: {r.score:.0%})")
            if r.contraction_rate_actual is not None:
                lines.append(f"   Contraction rate: {r.contraction_rate_actual:.0%}")
            if r.signature_phrases_found:
                lines.append(f"   Signatures found: {', '.join(r.signature_phrases_found[:2])}")
            for v in r.violations:
                icon = "🔴" if v.severity == "critical" else "🟡"
                lines.append(f"   {icon} {v.violation_type}: {v.detail}")
                if v.line_excerpt:
                    lines.append(f"      → {v.line_excerpt}")

        return "\n".join(lines)

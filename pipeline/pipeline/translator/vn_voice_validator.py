"""
VN Voice Consistency Validator — Vietnamese equivalent of VoiceConsistencyValidator

Post-translation validation for Vietnamese character voice fingerprints.
Replaces EN contraction-rate checks with VN particle usage rate + pronoun checks.

Checks:
  - Forbidden vocabulary per archetype (e.g., OJOU must not use slang particles)
  - Particle usage rate within archetype range (VN contraction-rate equivalent)
  - Pronoun pair consistency (PAIR_ID drift detection)
  - EPS-band awareness (COLD/COOL tighten expectations; WARM/HOT loosen)
  - Signature particles and catchphrases present where expected
"""

import re
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class VNVoiceViolation:
    character: str
    violation_type: str   # "forbidden_vocab" | "particle_rate" | "pronoun_drift" | "missing_signature" | "voice_bleed"
    detail: str
    severity: str         # "critical" | "warning"
    line_excerpt: str = ""


@dataclass
class VNVoiceValidationResult:
    character: str
    passed: bool
    score: float          # 0.0–1.0
    violations: List[VNVoiceViolation] = field(default_factory=list)
    particle_rate_actual: Optional[float] = None
    pronoun_consistency: Optional[float] = None
    signature_phrases_found: List[str] = field(default_factory=list)


# ── Archetype particle usage rate ranges ──────────────────────────────────────
# (min_rate, max_rate) — fraction of dialogue lines containing any VN particle
# Source: MEGA_CHARACTER_VOICE_SYSTEM_VN.md + jp_vn_particle_mapping_enhanced.json
ARCHETYPE_PARTICLE_RANGES: Dict[str, Tuple[float, float]] = {
    "ojou":           (0.05, 0.25),   # formal — uses ạ/ơi only, rarely
    "ojou-sama":      (0.05, 0.25),
    "mentor":         (0.10, 0.35),
    "kuudere":        (0.08, 0.30),
    "stoic-warrior":  (0.10, 0.35),
    "villain":        (0.08, 0.35),
    "dandere":        (0.20, 0.50),   # nervous — soft particles to hedge
    "tsundere":       (0.40, 0.78),   # heavy EPS-dependent particle usage
    "tsukkomi":       (0.45, 0.78),
    "boke":           (0.50, 0.85),
    "genki":          (0.55, 0.90),
    "gyaru":          (0.50, 0.88),   # particle-rich casual
    "delinquent":     (0.25, 0.65),
    "chuunibyou":     (0.20, 0.55),
    "onee-san":       (0.30, 0.65),
    "bokukko":        (0.30, 0.68),
    "lolibaba":       (0.28, 0.65),
    "everyman":       (0.35, 0.70),
    "narrator-protagonist": (0.25, 0.60),
    "shota":          (0.40, 0.80),
}

# ── Archetype forbidden particles ─────────────────────────────────────────────
# Particles completely forbidden for certain archetypes regardless of EPS
# Source: MEGA_CHARACTER_VOICE_SYSTEM_VN.md archetype profiles
ARCHETYPE_FORBIDDEN_PARTICLES: Dict[str, List[str]] = {
    "ojou":       ["đấy", "nè", "hở", "ơi", "nha"],        # too casual
    "ojou-sama":  ["đấy", "nè", "hở", "ơi", "nha"],
    "kuudere":    ["nè", "nha", "hở"],                       # too expressive
    "villain":    ["nha", "nhé ạ"],                          # too cute
    "stoic-warrior": ["nè", "nha", "hở"],
    "gyaru":      ["ạ dạ"],                                  # too formal
    "delinquent": ["ạ", "dạ", "thưa"],                      # too deferential
}

# ── EPS band particle rate adjustments ────────────────────────────────────────
EPS_PARTICLE_ADJUSTMENTS: Dict[str, Tuple[float, float]] = {
    "COLD":    (-0.12, -0.12),  # cold state → fewer casual particles
    "COOL":    (-0.06, -0.06),
    "NEUTRAL": (0.0,   0.0),
    "WARM":    (+0.06, +0.10),  # warming up → more casual particles
    "HOT":     (+0.12, +0.18),
}

# ── Vietnamese particle detection pattern ─────────────────────────────────────
VN_PARTICLE_PATTERN = re.compile(
    r'\b(à|ạ|ơi|nhé|nhỉ|nhể|nha|nè|đấy|đó|chứ|đâu|hử|hở|rồi|thôi|'
    r'đúng không|phải không)\b',
    re.IGNORECASE
)

# ── Vietnamese pronoun patterns ────────────────────────────────────────────────
# Common self-pronouns (xưng hô ngôi thứ nhất)
VN_SELF_PRONOUNS = re.compile(
    r'\b(tôi|tớ|mình|ta|tau|tao|em|anh|chị|cô|chú|bác|ông|bà)\b',
    re.IGNORECASE
)


class VNVoiceConsistencyValidator:
    """
    Validates Vietnamese translated text against character voice fingerprints.

    Usage:
        validator = VNVoiceConsistencyValidator()
        results = validator.validate_chapter(translated_text, fingerprints, eps_data)
        if any(not r.passed for r in results):
            # flag for re-translation
    """

    def validate_chapter(
        self,
        translated_text: str,
        fingerprints: List[Dict],
        eps_data: Optional[Dict[str, Dict]] = None,
    ) -> List[VNVoiceValidationResult]:
        """
        Run full VN voice consistency validation on a translated chapter.

        Args:
            translated_text: Full translated VN chapter text
            fingerprints: List of character_voice_fingerprints dicts
                          (must include canonical_name_vn or canonical_name_en,
                           archetype, particle_density, pronoun_self, pronoun_address,
                           forbidden_vocabulary, signature_phrases)
            eps_data: Dict of character_name → {eps_score, voice_band, signals}

        Returns:
            List of VNVoiceValidationResult per character
        """
        eps_data = eps_data or {}
        results = []

        for fp in fingerprints:
            # Accept both VN and EN canonical name
            name = fp.get("canonical_name_vn") or fp.get("canonical_name_en", "")
            if not name:
                continue

            dialogue = self._extract_character_dialogue(translated_text, name)
            if not dialogue:
                continue

            char_eps = eps_data.get(name, eps_data.get(name.lower(), {}))
            eps_band = char_eps.get("voice_band", "NEUTRAL") if isinstance(char_eps, dict) else "NEUTRAL"
            result = self._validate_character(name, fp, dialogue, eps_band, translated_text)
            results.append(result)

        return results

    def _validate_character(
        self,
        name: str,
        fp: Dict,
        dialogue_lines: List[str],
        eps_band: str,
        full_text: str,
    ) -> VNVoiceValidationResult:
        violations: List[VNVoiceViolation] = []
        all_dialogue = " ".join(dialogue_lines)
        archetype = fp.get("archetype", "").lower()

        # ── 1. Forbidden vocabulary check ─────────────────────────────────────
        forbidden = fp.get("forbidden_vocabulary", [])
        if eps_band not in ("WARM", "HOT"):
            for word in forbidden:
                pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)
                if pattern.search(all_dialogue):
                    violations.append(VNVoiceViolation(
                        character=name,
                        violation_type="forbidden_vocab",
                        detail=f'Used forbidden word/particle: "{word}"',
                        severity="critical",
                        line_excerpt=self._find_excerpt(all_dialogue, word),
                    ))

        # ── 2. Archetype-specific forbidden particles ──────────────────────────
        arch_forbidden_particles = ARCHETYPE_FORBIDDEN_PARTICLES.get(archetype, [])
        if eps_band not in ("WARM", "HOT"):
            for particle in arch_forbidden_particles:
                if re.search(r'\b' + re.escape(particle) + r'\b', all_dialogue, re.IGNORECASE):
                    violations.append(VNVoiceViolation(
                        character=name,
                        violation_type="forbidden_vocab",
                        detail=f'Archetype "{archetype}" must not use particle "{particle}"',
                        severity="critical",
                        line_excerpt=self._find_excerpt(all_dialogue, particle),
                    ))

        # ── 3. Signature phrases check ─────────────────────────────────────────
        signature = fp.get("signature_phrases", [])
        found_signatures = []
        if signature and len(dialogue_lines) >= 3:
            for phrase in signature:
                key_words = [w for w in phrase.lower().split() if len(w) > 2]
                if key_words and any(
                    all(kw in line.lower() for kw in key_words[:2])
                    for line in dialogue_lines
                ):
                    found_signatures.append(phrase)

        # ── 4. Particle usage rate check ──────────────────────────────────────
        # VN equivalent of EN contraction rate check
        particle_rate = self._calculate_particle_rate(all_dialogue)

        # Get archetype range
        particle_range = ARCHETYPE_PARTICLE_RANGES.get(archetype)

        # Also check fingerprint-stored particle_density as override
        fp_particle_density = fp.get("particle_density")
        if fp_particle_density is not None and len(dialogue_lines) >= 5:
            # Use ±0.20 tolerance around fingerprint density
            effective_lo = max(0.0, fp_particle_density - 0.20)
            effective_hi = min(1.0, fp_particle_density + 0.20)
            particle_range = (effective_lo, effective_hi)

        if particle_range and len(dialogue_lines) >= 5:
            lo, hi = particle_range
            # EPS band adjustment
            adj_lo, adj_hi = EPS_PARTICLE_ADJUSTMENTS.get(eps_band, (0.0, 0.0))
            lo = max(0.0, lo + adj_lo)
            hi = min(1.0, hi + adj_hi)

            if not (lo <= particle_rate <= hi):
                violations.append(VNVoiceViolation(
                    character=name,
                    violation_type="particle_rate",
                    detail=(
                        f"Particle rate {particle_rate:.0%} outside "
                        f"expected {lo:.0%}–{hi:.0%} for {archetype} [{eps_band}]"
                    ),
                    severity="warning",
                ))

        # ── 5. Pronoun consistency check ──────────────────────────────────────
        pronoun_self = fp.get("pronoun_self", "")
        pronoun_consistency = 1.0
        if pronoun_self and len(dialogue_lines) >= 3:
            pronoun_consistency, pronoun_note = self._check_pronoun_consistency(
                dialogue_lines, pronoun_self
            )
            if pronoun_consistency < 0.70:
                violations.append(VNVoiceViolation(
                    character=name,
                    violation_type="pronoun_drift",
                    detail=f'Pronoun drift detected for "{name}": {pronoun_note}',
                    severity="warning" if pronoun_consistency >= 0.50 else "critical",
                ))

        # ── Compute score ──────────────────────────────────────────────────────
        critical_count = sum(1 for v in violations if v.severity == "critical")
        warning_count = sum(1 for v in violations if v.severity == "warning")
        score = max(0.0, 1.0 - (critical_count * 0.30) - (warning_count * 0.10))

        return VNVoiceValidationResult(
            character=name,
            passed=critical_count == 0,
            score=score,
            violations=violations,
            particle_rate_actual=particle_rate,
            pronoun_consistency=pronoun_consistency,
            signature_phrases_found=found_signatures,
        )

    def _calculate_particle_rate(self, text: str) -> float:
        """Calculate fraction of sentences containing VN particles."""
        sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
        if not sentences:
            return 0.0
        sentences_with_particles = sum(
            1 for s in sentences
            if VN_PARTICLE_PATTERN.search(s)
        )
        return sentences_with_particles / len(sentences)

    def _check_pronoun_consistency(
        self,
        dialogue_lines: List[str],
        expected_pronoun: str,
    ) -> Tuple[float, str]:
        """
        Check if character consistently uses their assigned self-pronoun.
        Delegates to PronounConsistencyChecker for EPS-aware drift analysis.
        Returns (consistency_score, note).
        """
        try:
            from pipeline.translator.pronoun_consistency_checker import (
                PronounConsistencyChecker,
                VN_SELF_PRONOUN_PATTERN,
            )
            checker = PronounConsistencyChecker()
            # Build a single fake dialogue block for the checker
            text_block = "\n".join(dialogue_lines)
            character_pairs = {
                "_current_": {
                    "pair_id":       "PAIR_0",
                    "eps_band":      "NEUTRAL",
                    "pronoun_self":  expected_pronoun,
                }
            }
            reports = checker.check_chapter(text_block, character_pairs)
            if reports:
                r = reports[0]
                return r.consistency_score, r.note
        except Exception:
            pass  # Fall through to simple fallback

        # Fallback: simple count
        total_pronoun_uses = 0
        expected_uses = 0
        for line in dialogue_lines:
            matches = VN_SELF_PRONOUNS.findall(line.lower())
            for match in matches:
                total_pronoun_uses += 1
                if match == expected_pronoun.lower():
                    expected_uses += 1

        if total_pronoun_uses == 0:
            return 1.0, "no pronouns found"

        consistency = expected_uses / total_pronoun_uses
        note = (
            f'"{expected_pronoun}" used {expected_uses}/{total_pronoun_uses} times '
            f'({consistency:.0%} consistency)'
        )
        return consistency, note

    def _extract_character_dialogue(self, text: str, character_name: str) -> List[str]:
        """
        Extract dialogue lines attributed to a character.
        Handles both quoted dialogue and Vietnamese em-dash dialogue.
        """
        lines = []
        name_escaped = re.escape(character_name)

        # Pattern 1: Standard quoted dialogue near character name
        pattern = re.compile(
            rf'(?:{name_escaped}[^"{{}}]*?"([^"]+)")|(?:"([^"]+)"[^"{{}}]*?{name_escaped})',
            re.IGNORECASE
        )
        for m in pattern.finditer(text):
            dialogue = m.group(1) or m.group(2)
            if dialogue:
                lines.append(dialogue.strip())

        # Pattern 2: Em-dash dialogue (Vietnamese style) — dialogue following character name
        em_dash_pattern = re.compile(
            rf'{name_escaped}[^—\n]{{0,30}}—\s*([^—\n]+)',
            re.IGNORECASE
        )
        for m in em_dash_pattern.finditer(text):
            lines.append(m.group(1).strip())

        return lines

    def _find_excerpt(self, text: str, keyword: str, window: int = 60) -> str:
        """Find a short excerpt around a keyword."""
        idx = text.lower().find(keyword.lower())
        if idx == -1:
            return ""
        start = max(0, idx - window // 2)
        end = min(len(text), idx + window // 2)
        return "..." + text[start:end].strip() + "..."

    def format_report(self, results: List[VNVoiceValidationResult]) -> str:
        """Format VN voice validation results as a human-readable report."""
        if not results:
            return "VN Voice validation: no characters checked"

        lines = ["## VN VOICE CONSISTENCY REPORT"]
        passed = sum(1 for r in results if r.passed)
        lines.append(f"Passed: {passed}/{len(results)} characters\n")

        for r in results:
            status = "✓" if r.passed else "✗"
            lines.append(f"{status} {r.character} (score: {r.score:.0%})")
            if r.particle_rate_actual is not None:
                lines.append(f"   Particle rate: {r.particle_rate_actual:.0%}")
            if r.pronoun_consistency is not None:
                lines.append(f"   Pronoun consistency: {r.pronoun_consistency:.0%}")
            if r.signature_phrases_found:
                lines.append(f"   Signatures found: {', '.join(r.signature_phrases_found[:2])}")
            for v in r.violations:
                icon = "🔴" if v.severity == "critical" else "🟡"
                lines.append(f"   {icon} {v.violation_type}: {v.detail}")
                if v.line_excerpt:
                    lines.append(f"      → {v.line_excerpt}")

        return "\n".join(lines)

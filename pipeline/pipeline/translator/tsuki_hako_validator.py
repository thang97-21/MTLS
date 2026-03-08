"""
Tsuki/Hako Validator — VN equivalent of Koji Fox Validator

Automated naturalness scoring for Vietnamese translated dialogue.
Implements the "Test Tsuki/Hako" referenced in master_prompt_vn_pipeline.xml:
    "BẢN NHÁP NHỊP + TEST TSUKI/HAKO"

Checks:
  - Vietnamese AI-ism patterns (một cách, một cảm giác, sự nominalization)
  - Translationese structures (literal JP calques, wooden connectors)
  - Particle density (VN equivalent of EN contraction rate)
  - Rhythm violations per archetype (from ARCHETYPE_RHYTHM_IMPLEMENTATION.md)
  - CJK residue in output
  - Pronoun formality consistency (first-person passive ban)
"""

import re
import statistics
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

from pipeline.translator.quality_metrics import QualityMetrics

logger = logging.getLogger(__name__)


@dataclass
class VNDialogueViolation:
    line: str
    score: float
    issues: List[str]


@dataclass
class TsukiHakoReport:
    overall_score: float
    dialogue_lines_checked: int
    violations: List[VNDialogueViolation] = field(default_factory=list)
    passed: bool = True
    summary: str = ""
    particle_target_density: Optional[float] = None
    actual_particle_density: Optional[float] = None
    particle_delta: Optional[float] = None
    ai_ism_count: int = 0
    ai_isms_found: List[str] = field(default_factory=list)
    declared_voice_mode: str = ""
    missing_motif_anchors: List[str] = field(default_factory=list)
    forbidden_vocab_hits: List[str] = field(default_factory=list)

    def __post_init__(self):
        self.passed = self.overall_score >= 0.70

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_score": self.overall_score,
            "dialogue_lines_checked": self.dialogue_lines_checked,
            "passed": self.passed,
            "summary": self.summary,
            "particle_target_density": self.particle_target_density,
            "actual_particle_density": self.actual_particle_density,
            "particle_delta": self.particle_delta,
            "ai_ism_count": self.ai_ism_count,
            "ai_isms_found": self.ai_isms_found,
            "declared_voice_mode": self.declared_voice_mode,
            "missing_motif_anchors": self.missing_motif_anchors,
            "forbidden_vocab_hits": self.forbidden_vocab_hits,
            "violations": [
                {
                    "line": v.line,
                    "score": v.score,
                    "issues": list(v.issues),
                }
                for v in self.violations
            ],
        }


class TsukiHakoValidator:
    """
    Automated naturalness validation for Vietnamese translated dialogue.
    VN equivalent of KojiFoxValidator.

    Scores translated dialogue 0.0–1.0 on spoken naturalness.
    Chapters scoring below 0.70 are flagged for re-translation.

    Usage:
        validator = TsukiHakoValidator()
        report = validator.validate_chapter(translated_text)
        if not report.passed:
            # re-translate with VN voice adjustment
    """

    PASS_THRESHOLD = 0.70

    # ─── VN AI-ism anti-patterns ──────────────────────────────────────────────
    # Each entry: (compiled_pattern, penalty_per_match, description)
    VN_AI_ISM_PATTERNS: List[Tuple[re.Pattern, float, str]] = [
        # Critical: most common AI wrappers (0.15–0.20 penalty)
        (re.compile(r'một cảm giác', re.IGNORECASE),
         0.20, '"một cảm giác" — AI perception wrapper, show emotion directly'),
        (re.compile(r'cảm thấy một cảm giác', re.IGNORECASE),
         0.20, '"cảm thấy một cảm giác" — double AI wrapper'),
        (re.compile(r'một cách\s+\w+', re.IGNORECASE),
         0.15, '"một cách [adj]" — AI adverbial wrapper, use direct adverb'),
        (re.compile(r'việc\s+\w+\s+là', re.IGNORECASE),
         0.15, '"việc [verb] là" — nominalization, restructure'),
        # High: translationese structures (0.08–0.12 penalty)
        (re.compile(r'bắt đầu\s+\w+', re.IGNORECASE),
         0.08, '"bắt đầu [verb]" — "began to" construction, use direct verb'),
        (re.compile(r'tiến hành', re.IGNORECASE),
         0.08, '"tiến hành" — "proceeded to" construction'),
        (re.compile(r'sự\s+\w+\s+của', re.IGNORECASE),
         0.10, '"sự [noun] của" — over-formal nominalization'),
        (re.compile(r'đúng như mong đợi từ', re.IGNORECASE),
         0.10, '"đúng như mong đợi" — "as expected of" anime dub cliché'),
        (re.compile(r'tôi\s+(được|bị)\s+\w+\s+bởi', re.IGNORECASE),
         0.12, '"tôi được/bị [verb] bởi" — first-person passive (banned per VN RAG)'),
        (re.compile(r'thật ra thì', re.IGNORECASE),
         0.05, '"thật ra thì" — mechanical sentence opener'),
        (re.compile(r'\bcó thể cảm thấy\b', re.IGNORECASE),
         0.08, '"có thể cảm thấy" — "could sense" wrapper'),
        (re.compile(r'\bnhận ra rằng\b', re.IGNORECASE),
         0.08, '"nhận ra rằng" — "realized that" − just state it'),
        # CJK residue (critical)
        (re.compile(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]'),
         0.30, 'CJK characters in VN output — CRITICAL leak'),
    ]

    # ─── Particle patterns (VN equivalent of EN contractions) ─────────────────
    # Sentence-final particles that indicate natural VN dialogue
    VN_DIALOGUE_PARTICLES = re.compile(
        r'\b(à|ạ|ơi|nhé|nhỉ|nhể|nha|nè|đấy|đó|chứ|đâu|hử|hở|rồi|thôi|'
        r'đúng không|phải không|thế nào|sao)\b',
        re.IGNORECASE
    )

    # ─── Archetype particle density targets ───────────────────────────────────
    # (min_density, max_density) — ratio of dialogue lines containing particles
    # Based on MEGA_CHARACTER_VOICE_SYSTEM_VN.md archetype profiles
    ARCHETYPE_PARTICLE_TARGETS: Dict[str, Tuple[float, float]] = {
        "ojou":      (0.10, 0.30),   # formal, minimal casual particles
        "ojou-sama": (0.10, 0.30),
        "kuudere":   (0.10, 0.35),   # reserved, few particles
        "mentor":    (0.15, 0.40),
        "villain":   (0.10, 0.40),
        "dandere":   (0.20, 0.50),   # nervous, some softening particles
        "tsundere":  (0.40, 0.75),   # particle-heavy in emotional moments
        "genki":     (0.55, 0.90),   # high particle density
        "gyaru":     (0.55, 0.85),   # casual, particle-rich
        "delinquent": (0.30, 0.65),
        "everyman":  (0.35, 0.70),
        "narrator-protagonist": (0.25, 0.60),
        "chuunibyou": (0.20, 0.55),
        "onee-san":  (0.30, 0.65),
        "bokukko":   (0.35, 0.70),
        "lolibaba":  (0.30, 0.70),
    }

    # EPS band particle density adjustments
    EPS_PARTICLE_ADJUSTMENTS: Dict[str, Tuple[float, float]] = {
        "COLD":    (-0.10, -0.10),   # colder → fewer casual particles
        "COOL":    (-0.05, -0.05),
        "NEUTRAL": (0.0,   0.0),
        "WARM":    (+0.05, +0.10),   # warmer → more casual particles allowed
        "HOT":     (+0.10, +0.15),
    }

    def _calculate_particle_density(self, dialogue_lines: List[str]) -> float:
        """Calculate fraction of dialogue lines containing VN particles."""
        if not dialogue_lines:
            return 0.0
        lines_with_particles = sum(
            1 for line in dialogue_lines
            if self.VN_DIALOGUE_PARTICLES.search(line)
        )
        return lines_with_particles / len(dialogue_lines)

    def score_dialogue_naturalness(self, line: str) -> Tuple[float, List[str]]:
        """
        Score a single Vietnamese dialogue line 0.0–1.0 on naturalness.
        Returns (score, list_of_issues).
        """
        score = 1.0
        issues = []

        for pattern, penalty, description in self.VN_AI_ISM_PATTERNS:
            matches = pattern.findall(line)
            if matches:
                score -= penalty * len(matches)
                issues.append(description)

        return max(0.0, min(1.0, score)), issues

    def _check_sentence_length_variance(self, text: str) -> float:
        """
        Penalize mechanical uniformity in sentence lengths.
        Vietnamese natural prose has natural variance; AI tends to be uniform.
        """
        sentences = re.split(r'[.!?]+', text)
        lengths = [len(s.split()) for s in sentences if s.strip() and len(s.split()) > 1]
        if len(lengths) < 4:
            return 0.0

        std_dev = statistics.stdev(lengths)
        mean = statistics.mean(lengths)

        if mean > 0 and std_dev / mean < 0.25:
            return 0.08  # Penalty for mechanical uniformity
        return 0.0

    def _check_rhythm_profile(self, dialogue_lines: List[str]) -> float:
        """
        Check fragment ratio for VN dialogue.
        VN dialogue typically has some short (~2–6 word) fragments.
        """
        if not dialogue_lines:
            return 0.0

        fragments = sum(
            1 for line in dialogue_lines
            if len(line.split()) <= 5
        )
        ratio = fragments / len(dialogue_lines)

        # Ideal range: 8–45% fragments
        if ratio < 0.04:
            return 0.05  # Too formal
        if ratio > 0.65:
            return 0.08  # Too choppy
        return 0.0

    def validate_chapter(
        self,
        chapter_text: str,
        character_fingerprints: Optional[List[dict]] = None,
        chapter_pov: Optional[str] = None,
        pov_segments: Optional[List[dict]] = None,
    ) -> TsukiHakoReport:
        """
        Run full Tsuki/Hako validation on a translated VN chapter.

        Args:
            chapter_text: Full translated chapter text (Vietnamese)
            character_fingerprints: Optional list of character fingerprints from manifest
            chapter_pov: Canonical name of chapter POV character
            pov_segments: Multi-POV segment dicts (keys: character, fingerprint,
                          start_line, end_line, description)

        Returns:
            TsukiHakoReport with overall score and per-line violations
        """
        # Extract dialogue lines (text inside double or single quotes)
        dialogue_lines = re.findall(r'"([^"]{5,})"', chapter_text)
        if not dialogue_lines:
            # Also check Vietnamese-style dialogue (no quotes, em dash)
            dialogue_lines = re.findall(r'—\s*([^—\n]{5,})', chapter_text)

        violations: List[VNDialogueViolation] = []
        total_score = 0.0
        missing_motif_anchors: List[str] = []
        forbidden_vocab_hits: List[str] = []

        # ── VN AI-ism count on full chapter text ─────────────────────────────
        vn_metrics = QualityMetrics.calculate_vn_quality_metrics(chapter_text)
        ai_ism_count = vn_metrics.get("ai_ism_count", 0)
        ai_isms_found = vn_metrics.get("ai_isms_found", [])

        # ── Particle density baseline from fingerprint ────────────────────────
        _fingerprint_particle_density: Optional[float] = None
        particle_target = None

        if pov_segments:
            rates = []
            for seg in pov_segments:
                seg_fp = seg.get("fingerprint") or {}
                rate = seg_fp.get("particle_density")
                if rate is not None:
                    rates.append(rate)
            if rates:
                _fingerprint_particle_density = min(rates)
                logger.info(
                    f"[TSUKI-HAKO][Multi-POV] Using min particle density baseline "
                    f"across {len(rates)} segments: {_fingerprint_particle_density:.0%}"
                )
        elif chapter_pov and character_fingerprints:
            pov_fp = next(
                (fp for fp in character_fingerprints
                 if fp.get("canonical_name_en", "").lower() == chapter_pov.lower()
                 or fp.get("canonical_name_vn", "").lower() == chapter_pov.lower()),
                None,
            )
            if pov_fp is not None:
                _fingerprint_particle_density = pov_fp.get("particle_density")
                if _fingerprint_particle_density is not None:
                    logger.info(
                        f"[TSUKI-HAKO] Using fingerprint particle density baseline "
                        f"for POV '{chapter_pov}': {_fingerprint_particle_density:.0%}"
                    )

        particle_target = _fingerprint_particle_density

        actual_particle_density = self._calculate_particle_density(dialogue_lines) if dialogue_lines else 0.0

        if not dialogue_lines:
            overall_score = max(
                0.0,
                1.0 - (0.05 * ai_ism_count / max(1, vn_metrics.get("word_count", 1000) / 1000)),
            )
            particle_delta = (
                actual_particle_density - particle_target
                if particle_target is not None
                else None
            )
            return TsukiHakoReport(
                overall_score=min(1.0, overall_score),
                dialogue_lines_checked=0,
                summary="No dialogue lines found to validate",
                particle_target_density=particle_target,
                actual_particle_density=actual_particle_density,
                particle_delta=particle_delta,
                ai_ism_count=ai_ism_count,
                ai_isms_found=ai_isms_found,
            )

        # ── Score each dialogue line ──────────────────────────────────────────
        for line in dialogue_lines:
            score, issues = self.score_dialogue_naturalness(line)
            total_score += score
            if score < self.PASS_THRESHOLD:
                violations.append(VNDialogueViolation(
                    line=line[:100] + ("..." if len(line) > 100 else ""),
                    score=score,
                    issues=issues,
                ))

        # Apply prose-level penalties
        prose_penalty = self._check_sentence_length_variance(chapter_text)
        prose_penalty += self._check_rhythm_profile(dialogue_lines)

        # Apply AI-ism density penalty (per 1000 words)
        word_count = vn_metrics.get("word_count", 1)
        ai_ism_density = ai_ism_count / (word_count / 1000) if word_count > 0 else 0
        # Penalty: 0.02 per AI-ism per 1000 words above threshold of 2.0
        ai_ism_penalty = max(0.0, (ai_ism_density - 2.0) * 0.02)

        avg_score = (total_score / len(dialogue_lines)) - prose_penalty - ai_ism_penalty
        overall_score = max(0.0, min(1.0, avg_score))

        # ── Particle density delta ────────────────────────────────────────────
        particle_delta = (
            actual_particle_density - particle_target
            if particle_target is not None
            else None
        )

        # Add particle density warning to violations if significantly below target
        if particle_target is not None and particle_delta is not None and particle_delta < -0.20:
            violations.append(VNDialogueViolation(
                line=f"[Particle density too low: {actual_particle_density:.0%} vs target {particle_target:.0%}]",
                score=0.85,
                issues=[f"Particle density {actual_particle_density:.0%} is {abs(particle_delta):.0%} below target — dialogue may sound wooden"],
            ))
            overall_score = max(0.0, overall_score - 0.05)

        violation_rate = len(violations) / len(dialogue_lines)
        summary = (
            f"{len(dialogue_lines)} lines checked, "
            f"{len(violations)} violations ({violation_rate:.0%}), "
            f"score: {overall_score:.0%}, "
            f"AI-isms: {ai_ism_count}"
        )
        if particle_target is not None and particle_delta is not None:
            summary += (
                f", particles={actual_particle_density:.2f} "
                f"(target={particle_target:.2f}, delta={particle_delta:+.2f})"
            )

        return TsukiHakoReport(
            overall_score=overall_score,
            dialogue_lines_checked=len(dialogue_lines),
            violations=violations,
            summary=summary,
            particle_target_density=particle_target,
            actual_particle_density=actual_particle_density,
            particle_delta=particle_delta,
            ai_ism_count=ai_ism_count,
            ai_isms_found=ai_isms_found,
            missing_motif_anchors=missing_motif_anchors,
            forbidden_vocab_hits=forbidden_vocab_hits,
        )

    def format_report(self, report: TsukiHakoReport, max_violations: int = 5) -> str:
        """Format a TsukiHakoReport as a human-readable string."""
        status = "✓ PASSED" if report.passed else "✗ FAILED"
        lines = [
            f"## TSUKI/HAKO TEST — {status}",
            f"Score: {report.overall_score:.0%} | {report.summary}",
        ]

        if report.ai_isms_found:
            lines.append(f"AI-isms: {', '.join(report.ai_isms_found[:5])}")

        if report.violations:
            lines.append(f"\nTop violations (showing {min(max_violations, len(report.violations))}):")
            for v in report.violations[:max_violations]:
                lines.append(f"  [{v.score:.0%}] \"{v.line}\"")
                for issue in v.issues:
                    lines.append(f"    → {issue}")

        return "\n".join(lines)

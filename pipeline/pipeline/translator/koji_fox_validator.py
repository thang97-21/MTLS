"""
Koji Fox Validator — Phase 3 of Koji Fox Expansion

Automated "read-aloud" naturalness scoring for translated dialogue.
Implements the Koji Fox Test: would a native English speaker actually say this?

Checks:
  - Anime dub speech patterns (standalone "You!", excessive ellipsis)
  - Stilted formality (over-formal contractions)
  - Mechanical sentence length uniformity
  - Fragment ratio (too many or too few fragments)
  - CJK residue in output
"""

import re
import statistics
import logging
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING, Any
from dataclasses import dataclass, field

from pipeline.translator.quality_metrics import QualityMetrics

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pipeline.translator.tools.translation_parameter_handler import (
        DeclaredTranslationParameters,
    )


@dataclass
class DialogueViolation:
    line: str
    score: float
    issues: List[str]


@dataclass
class KojiFoxReport:
    overall_score: float
    dialogue_lines_checked: int
    violations: List[DialogueViolation] = field(default_factory=list)
    passed: bool = True
    summary: str = ""
    contraction_target_rate: Optional[float] = None
    actual_contraction_rate: Optional[float] = None
    narration_contraction_rate: Optional[float] = None
    dialogue_contraction_rate: Optional[float] = None
    contraction_measure_scope: str = ""
    contraction_delta: Optional[float] = None
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
            "contraction_target_rate": self.contraction_target_rate,
            "actual_contraction_rate": self.actual_contraction_rate,
            "narration_contraction_rate": self.narration_contraction_rate,
            "dialogue_contraction_rate": self.dialogue_contraction_rate,
            "contraction_measure_scope": self.contraction_measure_scope,
            "contraction_delta": self.contraction_delta,
            "declared_voice_mode": self.declared_voice_mode,
            "missing_motif_anchors": self.missing_motif_anchors,
            "forbidden_vocab_hits": self.forbidden_vocab_hits,
            "violations": [
                {
                    "line": violation.line,
                    "score": violation.score,
                    "issues": list(violation.issues),
                }
                for violation in self.violations
            ],
        }


class KojiFoxValidator:
    """
    Automated read-aloud naturalness validation.

    Scores translated dialogue 0.0–1.0 on spoken naturalness.
    Chapters scoring below 0.70 are flagged for voice adjustment.

    Usage:
        validator = KojiFoxValidator()
        report = validator.validate_chapter(translated_text)
        if not report.passed:
            # re-translate with voice adjustment
    """

    PASS_THRESHOLD = 0.70

    # ─── Anti-pattern definitions ─────────────────────────────────────────────

    ANTI_PATTERNS: Dict[str, List[Tuple[re.Pattern, float, str]]] = {
        "anime_dub_speech": [
            (re.compile(r'\bYou!\s*"', re.IGNORECASE), 0.15, 'Standalone "You!" address'),
            (re.compile(r'\.{4,}'), 0.10, "Excessive ellipsis (4+ dots)"),
            (re.compile(r'「[^」]+」'), 0.20, "Japanese-style 「」 quotes in EN output"),
            (re.compile(r'\bAs expected of\b', re.IGNORECASE), 0.10, '"As expected of" — anime dub cliché'),
            (re.compile(r'\bTo think that\b', re.IGNORECASE), 0.08, '"To think that" — stilted opener'),
            (re.compile(r'\bHow dare you\b', re.IGNORECASE), 0.08, '"How dare you" — melodramatic dub phrase'),
        ],
        "stilted_formality": [
            (re.compile(r'\bI am\b(?!\s+(?:not|going|trying|sorry|afraid|sure|glad|happy|sad|angry|tired|ready|done|here|there|aware|certain|confident|grateful|honored|pleased|relieved|worried|confused|surprised|shocked|embarrassed|nervous|excited|proud|ashamed|jealous|lonely|bored|frustrated|disappointed|devastated|heartbroken|overwhelmed|exhausted|terrified|horrified|disgusted|offended|insulted|humiliated|betrayed|abandoned|rejected|ignored|forgotten|misunderstood|underestimated|underappreciated|undervalued|underestimated|underrepresented|underpaid|underprivileged|underserved|underutilized|underemployed|underfunded|underinsured|underinsured|underinsured|underinsured))', re.IGNORECASE), 0.05, 'Over-formal "I am" in casual dialogue'),
            (re.compile(r'\bdoes not\b', re.IGNORECASE), 0.05, '"does not" instead of "doesn\'t"'),
            (re.compile(r'\bdo not\b(?!\s+(?:worry|hesitate|forget|be|let|try|want|need|have|get|go|come|make|take|give|put|set|run|keep|hold|turn|move|bring|show|tell|ask|know|think|feel|see|hear|say|speak|talk|write|read|work|play|live|die|fight|win|lose|stand|sit|walk|run|jump|fall|rise|grow|change|stop|start|begin|end|finish|continue|remain|stay|leave|return|arrive|depart|enter|exit|open|close|lock|unlock|break|fix|build|destroy|create|find|lose|search|discover|explore|investigate|analyze|evaluate|assess|measure|calculate|estimate|predict|plan|prepare|organize|manage|control|lead|follow|support|help|protect|defend|attack|escape|hide|reveal|expose|share|keep|save|spend|waste|use|need|want|like|love|hate|fear|trust|doubt|believe|know|understand|remember|forget|learn|teach|study|practice|improve|develop|grow|change|adapt|adjust|accept|reject|choose|decide|agree|disagree|approve|disapprove|allow|prevent|enable|disable|start|stop|continue|pause|resume|repeat|redo|undo|cancel|confirm|deny|admit|confess|apologize|forgive|thank|greet|welcome|invite|refuse|accept|offer|request|demand|suggest|recommend|advise|warn|threaten|promise|swear|lie|cheat|steal|betray|abandon|ignore|neglect|abuse|hurt|harm|heal|cure|save|rescue|protect|guard|watch|observe|notice|recognize|identify|distinguish|compare|contrast|combine|separate|connect|disconnect|attach|detach|include|exclude|add|remove|insert|delete|replace|substitute|exchange|trade|buy|sell|give|take|borrow|lend|rent|hire|fire|promote|demote|reward|punish|praise|criticize|judge|evaluate|rate|rank|score|grade|test|examine|check|verify|confirm|deny|prove|disprove|support|oppose|agree|disagree|accept|reject|approve|disapprove|allow|prevent|enable|disable))', re.IGNORECASE), 0.05, '"do not" instead of "don\'t"'),
        ],
        "cjk_residue": [
            (re.compile(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]'), 0.30, "CJK characters in EN output — CRITICAL"),
        ],
        "mechanical_prose": [
            (re.compile(r'\bsuddenly\b', re.IGNORECASE), 0.05, '"suddenly" — weak transition word'),
            (re.compile(r'\bvery\s+very\b', re.IGNORECASE), 0.05, 'Doubled "very very"'),
            (re.compile(r'\bsaid\s+with\s+a\s+smile\b', re.IGNORECASE), 0.05, '"said with a smile" — telling not showing'),
        ],
    }

    def score_dialogue_naturalness(self, line: str) -> Tuple[float, List[str]]:
        """
        Score a single dialogue line 0.0–1.0 on spoken naturalness.
        Returns (score, list_of_issues).
        """
        score = 1.0
        issues = []

        for category, patterns in self.ANTI_PATTERNS.items():
            for pattern, penalty, description in patterns:
                matches = pattern.findall(line)
                if matches:
                    score -= penalty * len(matches)
                    issues.append(description)

        return max(0.0, min(1.0, score)), issues

    def _check_sentence_length_variance(self, text: str) -> float:
        """
        Penalize mechanical uniformity in sentence lengths.
        Human speech has natural variance; machine translation tends to be uniform.
        """
        sentences = re.split(r'[.!?]+', text)
        lengths = [len(s.split()) for s in sentences if s.strip() and len(s.split()) > 1]
        if len(lengths) < 4:
            return 0.0

        std_dev = statistics.stdev(lengths)
        mean = statistics.mean(lengths)

        if mean > 0 and std_dev / mean < 0.25:
            return 0.10  # Penalty for mechanical uniformity
        return 0.0

    def _check_fragment_ratio(self, dialogue_lines: List[str]) -> float:
        """
        Check fragment ratio. Natural dialogue has some fragments.
        Too few fragments = overly formal. Too many = choppy.
        """
        if not dialogue_lines:
            return 0.0

        fragments = sum(
            1 for line in dialogue_lines
            if len(line.split()) <= 4 and not line.endswith("?")
        )
        ratio = fragments / len(dialogue_lines)

        # Ideal range: 10–40% fragments
        if ratio < 0.05:
            return 0.05  # Too formal, no fragments
        if ratio > 0.60:
            return 0.08  # Too choppy
        return 0.0

    @staticmethod
    def _extract_dialogue_lines(text: str) -> List[str]:
        return re.findall(r'"([^"]{5,})"', text or "")

    @staticmethod
    def _strip_dialogue_and_internal_monologue(text: str) -> str:
        stripped = re.sub(r'"[^"]*"', " ", text or "")
        stripped = re.sub(r'\*[^*\n]+\*', " ", stripped)
        return re.sub(r"\s+", " ", stripped).strip()

    def validate_chapter(
        self,
        chapter_text: str,
        declared_params: Optional["DeclaredTranslationParameters"] = None,
        character_fingerprints: Optional[List[dict]] = None,
        chapter_pov: Optional[str] = None,
        pov_segments: Optional[List[dict]] = None,
    ) -> "KojiFoxReport":
        """
        Run full Koji Fox validation on a translated chapter.

        Args:
            chapter_text: Full translated chapter text
            declared_params: Optional chapter-level tool declaration
            character_fingerprints: Optional list of character_voice_fingerprints dicts
                (from manifest metadata_en).  When provided alongside chapter_pov,
                the POV character's fingerprint contraction_rate is used as the
                authoritative baseline instead of declared_params.contraction_targets,
                preventing false-positive passes when the model self-declares the wrong
                EPS band (Gap 8.3 fix).
            chapter_pov: Canonical EN name of the chapter's POV character (e.g.
                "Sudou Ayami").  Only used when character_fingerprints is also provided.
                Mutually exclusive with pov_segments — if pov_segments is provided,
                chapter_pov is ignored for baseline computation.
            pov_segments: List of multi-POV hot-switch segment dicts (Gap 8.2 extension).
                Each entry has keys: character (str), fingerprint (dict), start_line,
                end_line, description.  When provided, the chapter-level contraction
                baseline is set to the **minimum contraction_rate across all segments**
                (most restrictive voice wins).  Per-segment validation is a future
                enhancement — this is the chapter-level conservative guard.

        Returns:
            KojiFoxReport with overall score and per-line violations
        """
        # Extract dialogue lines (quoted strings)
        dialogue_lines = self._extract_dialogue_lines(chapter_text)

        violations = []
        total_score = 0.0
        contraction_target = None
        missing_motif_anchors: List[str] = []
        forbidden_vocab_hits: List[str] = []
        narration_text = self._strip_dialogue_and_internal_monologue(chapter_text)
        narration_contraction_rate = (
            QualityMetrics.calculate_contraction_rate(narration_text)
            if narration_text
            else 1.0
        )
        dialogue_contraction_rate = (
            QualityMetrics.calculate_contraction_rate("\n".join(dialogue_lines))
            if dialogue_lines
            else None
        )
        actual_contraction_rate = QualityMetrics.calculate_contraction_rate(chapter_text)
        contraction_measure_scope = "document"

        # ── Gap 8.3: Fingerprint-aware contraction baseline ───────────────────
        # Prefer the POV character's fingerprint contraction_rate over the model's
        # self-declared narration_rate.  This prevents false-positive KF passes
        # when the model declares the wrong EPS band (e.g. HOT instead of COLD
        # for a kuudere character), which caused the rerun #1 false positive of
        # KF 0.83 for Ch13 (Ayami, actual KF ~0.28 vs fingerprint target 0.40).
        #
        # Sub-cases (mutually exclusive; pov_segments takes precedence):
        #   A) pov_segments provided → min contraction_rate across all segment
        #      fingerprints is the chapter-level baseline.  Per-segment scoring
        #      is a future enhancement.
        #   B) chapter_pov + character_fingerprints provided → look up that
        #      character's fingerprint rate (original Gap 8.3 logic).
        _fingerprint_rate: Optional[float] = None

        if pov_segments:
            # ── Case A: Multi-POV — use minimum (most restrictive) ceiling ───
            rates = []
            for seg in pov_segments:
                seg_fp = seg.get("fingerprint") or {}
                rate = seg_fp.get("contraction_rate")
                if rate is not None:
                    rates.append(rate)
            if rates:
                _fingerprint_rate = min(rates)
                seg_names = [s.get("character", "?") for s in pov_segments]
                logger.info(
                    f"[KF][Gap 8.3 ext.] Multi-POV chapter — using min contraction baseline "
                    f"across {len(rates)} segments ({' → '.join(seg_names)}): "
                    f"{_fingerprint_rate:.0%} (most restrictive ceiling)"
                )

        elif chapter_pov and character_fingerprints:
            # ── Case B: Single non-protagonist POV ───────────────────────────
            pov_fp = next(
                (fp for fp in character_fingerprints
                 if fp.get("canonical_name_en", "").lower() == chapter_pov.lower()),
                None,
            )
            if pov_fp is not None:
                _fingerprint_rate = pov_fp.get("contraction_rate")
                logger.info(
                    f"[KF][Gap 8.3] Using fingerprint contraction baseline "
                    f"for POV '{chapter_pov}': {_fingerprint_rate} "
                    f"(overrides declared target)"
                )

        if declared_params is not None:
            # Use fingerprint rate when available; fall back to declared target.
            _declared_rate = declared_params.contraction_targets.get("narration_rate")
            contraction_target = _fingerprint_rate if _fingerprint_rate is not None else _declared_rate
            if _fingerprint_rate is not None and _declared_rate is not None and _fingerprint_rate != _declared_rate:
                logger.warning(
                    f"[KF][Gap 8.3] Declared narration_rate={_declared_rate} overridden by "
                    f"fingerprint rate={_fingerprint_rate} for POV '{chapter_pov}'. "
                    f"Model self-declared wrong EPS band — fingerprint is authoritative."
                )
            text_lower = chapter_text.lower()

            for anchor in declared_params.motif_anchors:
                if anchor.lower() not in text_lower:
                    missing_motif_anchors.append(anchor)
                    violations.append(
                        DialogueViolation(
                            line=f"[Motif anchor missing: {anchor}]",
                            score=0.90,
                            issues=[f"Declared motif anchor '{anchor}' absent from output"],
                        )
                    )

            for forbidden in declared_params.forbidden_vocab_overrides:
                if forbidden.lower() in text_lower:
                    forbidden_vocab_hits.append(forbidden)
                    violations.append(
                        DialogueViolation(
                            line=f"[Forbidden vocabulary hit: {forbidden}]",
                            score=0.85,
                            issues=[f"Declared forbidden vocabulary '{forbidden}' appears in output"],
                        )
                    )
        elif _fingerprint_rate is not None:
            # No declared params but fingerprint is available: use fingerprint rate as baseline.
            # This handles validation of chapters translated in batch+thinking mode where
            # tool_use / declare_translation_parameters is never called.
            contraction_target = _fingerprint_rate

        if contraction_target is not None:
            actual_contraction_rate = narration_contraction_rate
            contraction_measure_scope = "narration"

        if not dialogue_lines:
            contraction_delta = (
                actual_contraction_rate - contraction_target
                if contraction_target is not None
                else None
            )
            overall_score = max(
                0.0,
                1.0 - (0.03 * len(missing_motif_anchors)) - (0.04 * len(forbidden_vocab_hits)),
            )
            summary = "No dialogue lines found to validate"
            if contraction_target is not None:
                summary += (
                    f"; contraction={actual_contraction_rate:.3f} vs target={contraction_target:.3f}"
                )
            return KojiFoxReport(
                overall_score=overall_score,
                dialogue_lines_checked=0,
                summary=summary,
                contraction_target_rate=contraction_target,
                actual_contraction_rate=actual_contraction_rate,
                narration_contraction_rate=narration_contraction_rate,
                dialogue_contraction_rate=dialogue_contraction_rate,
                contraction_measure_scope=contraction_measure_scope,
                contraction_delta=contraction_delta,
                declared_voice_mode=(declared_params.voice_mode if declared_params else ""),
                missing_motif_anchors=missing_motif_anchors,
                forbidden_vocab_hits=forbidden_vocab_hits,
                violations=violations,
            )

        for line in dialogue_lines:
            score, issues = self.score_dialogue_naturalness(line)
            total_score += score
            if score < self.PASS_THRESHOLD:
                violations.append(DialogueViolation(
                    line=line[:100] + ("..." if len(line) > 100 else ""),
                    score=score,
                    issues=issues,
                ))

        # Apply prose-level penalties
        prose_penalty = self._check_sentence_length_variance(chapter_text)
        prose_penalty += self._check_fragment_ratio(dialogue_lines)

        avg_score = (total_score / len(dialogue_lines)) - prose_penalty
        avg_score -= 0.03 * len(missing_motif_anchors)
        avg_score -= 0.04 * len(forbidden_vocab_hits)

        contraction_delta = (
            actual_contraction_rate - contraction_target
            if contraction_target is not None
            else None
        )
        overall_score = max(0.0, min(1.0, avg_score))

        violation_rate = len(violations) / len(dialogue_lines)
        summary = (
            f"{len(dialogue_lines)} lines checked, "
            f"{len(violations)} violations ({violation_rate:.0%}), "
            f"score: {overall_score:.0%}"
        )
        if contraction_target is not None and contraction_delta is not None:
            summary += (
                f", contraction={actual_contraction_rate:.3f} "
                f"(target={contraction_target:.3f}, delta={contraction_delta:+.3f})"
            )
            if dialogue_contraction_rate is not None:
                summary += f", dialogue={dialogue_contraction_rate:.3f}"

        return KojiFoxReport(
            overall_score=overall_score,
            dialogue_lines_checked=len(dialogue_lines),
            violations=violations,
            summary=summary,
            contraction_target_rate=contraction_target,
            actual_contraction_rate=actual_contraction_rate,
            narration_contraction_rate=narration_contraction_rate,
            dialogue_contraction_rate=dialogue_contraction_rate,
            contraction_measure_scope=contraction_measure_scope,
            contraction_delta=contraction_delta,
            declared_voice_mode=(declared_params.voice_mode if declared_params else ""),
            missing_motif_anchors=missing_motif_anchors,
            forbidden_vocab_hits=forbidden_vocab_hits,
        )

    def format_report(self, report: KojiFoxReport, max_violations: int = 5) -> str:
        """Format a KojiFoxReport as a human-readable string."""
        status = "✓ PASSED" if report.passed else "✗ FAILED"
        lines = [
            f"## KOJI FOX TEST — {status}",
            f"Score: {report.overall_score:.0%} | {report.summary}",
        ]

        if report.violations:
            lines.append(f"\nTop violations (showing {min(max_violations, len(report.violations))}):")
            for v in report.violations[:max_violations]:
                lines.append(f"  [{v.score:.0%}] \"{v.line}\"")
                for issue in v.issues:
                    lines.append(f"    → {issue}")

        return "\n".join(lines)

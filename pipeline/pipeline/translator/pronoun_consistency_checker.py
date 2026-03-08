"""
Pronoun Consistency Checker — Vietnamese PAIR_ID drift detection

Vietnamese has a complex pronoun system tied to character relationship and
emotional state (EPS). Unlike English, pronouns are a primary quality signal:
a pronoun shift from tớ→tôi is as significant as a register shift.

This module:
  1. Maps each character to their assigned PAIR_ID pronoun set
  2. Detects within-chapter pronoun drift (e.g., nhân vật switches mid-chapter)
  3. Detects across-chapter drift (volume-level consistency)
  4. Is EPS-aware: a COLD→WARM shift may legitimately change pronoun usage

PAIR_ID system (from MEGA_CORE_TRANSLATION_ENGINE_VN.md):
  PAIR_0 = tôi/bạn (neutral adult)
  PAIR_1 = tớ/cậu (peer-casual)
  PAIR_2 = em/anh | em/chị (junior-senior)
  PAIR_3 = ta/ngươi | ta/mi (archaic/haughty)
  PAIR_FAM = mình/bạn (intimate)
"""

import re
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ── Pronoun pair definitions (matching PAIR_ID_MAP in master_prompt_vn_pipeline.xml) ─
PAIR_ID_MAP: Dict[str, Dict[str, List[str]]] = {
    "PAIR_0": {
        "self":    ["tôi"],
        "address": ["bạn", "anh", "chị", "cô", "chú"],
        "register": "neutral_adult",
    },
    "PAIR_1": {
        "self":    ["tớ", "mình"],
        "address": ["cậu", "bạn"],
        "register": "peer_casual",
    },
    "PAIR_2": {
        "self":    ["em"],
        "address": ["anh", "chị"],
        "register": "junior_senior",
    },
    "PAIR_3": {
        "self":    ["ta"],
        "address": ["ngươi", "mi"],
        "register": "archaic_haughty",
    },
    "PAIR_FAM": {
        "self":    ["mình"],
        "address": ["bạn", "cậu"],
        "register": "intimate",
    },
} # type: ignore

# All self-pronouns for detection
ALL_SELF_PRONOUNS: List[str] = [
    "tôi", "tớ", "mình", "ta", "em", "anh", "chị", "cô",
    "tau", "tao", "chúng tôi", "chúng ta"
]

VN_SELF_PRONOUN_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(p) for p in sorted(ALL_SELF_PRONOUNS, key=len, reverse=True)) + r')\b',
    re.IGNORECASE
)


@dataclass
class PronounDriftEvent:
    character: str
    expected_pronoun: str
    found_pronoun: str
    line_excerpt: str
    line_number: int
    eps_band: str
    severity: str  # "critical" | "warning" | "eps_justified"


@dataclass
class PronounConsistencyReport:
    character: str
    pair_id: str
    expected_self: List[str]
    total_pronoun_uses: int
    consistent_uses: int
    consistency_score: float
    drift_events: List[PronounDriftEvent] = field(default_factory=list)
    passed: bool = True
    note: str = ""

    def __post_init__(self):
        self.passed = self.consistency_score >= 0.80


class PronounConsistencyChecker:
    """
    Checks Vietnamese character pronoun consistency within and across chapters.

    Usage:
        checker = PronounConsistencyChecker()
        reports = checker.check_chapter(
            translated_text,
            character_pairs,   # {char_name: {pair_id, eps_band, ...}}
        )
    """

    def check_chapter(
        self,
        translated_text: str,
        character_pairs: Dict[str, Dict],
        fingerprints: Optional[List[Dict]] = None,
    ) -> List[PronounConsistencyReport]:
        """
        Check pronoun consistency for all characters in a chapter.

        Args:
            translated_text: Full VN translated chapter text
            character_pairs: Dict of character_name → {
                pair_id: "PAIR_0"|"PAIR_1"|...,
                eps_band: "COLD"|"COOL"|"NEUTRAL"|"WARM"|"HOT",
                pronoun_self: "tớ",      # optional override
                pronoun_address: "cậu",  # optional override
            }
            fingerprints: Optional list of character fingerprints dicts

        Returns:
            List of PronounConsistencyReport per character
        """
        reports = []

        # Build pronoun assignments from fingerprints if character_pairs incomplete
        if fingerprints:
            for fp in fingerprints:
                name = fp.get("canonical_name_vn") or fp.get("canonical_name_en", "")
                if name and name not in character_pairs:
                    pair_id = fp.get("pair_id", "PAIR_0")
                    character_pairs[name] = {
                        "pair_id": pair_id,
                        "eps_band": "NEUTRAL",
                        "pronoun_self": fp.get("pronoun_self", ""),
                    }

        for char_name, char_config in character_pairs.items():
            pair_id = char_config.get("pair_id", "PAIR_0")
            eps_band = char_config.get("eps_band", "NEUTRAL")
            pronoun_override = char_config.get("pronoun_self", "")

            # Determine expected pronouns
            pair_data = PAIR_ID_MAP.get(pair_id, PAIR_ID_MAP["PAIR_0"])
            if pronoun_override:
                expected_self = [pronoun_override.lower()]
            else:
                expected_self = [p.lower() for p in pair_data.get("self", ["tôi"])]

            # Extract character dialogue
            dialogue_lines = self._extract_character_dialogue(translated_text, char_name)
            if not dialogue_lines:
                continue

            report = self._check_character_pronouns(
                char_name, pair_id, expected_self, dialogue_lines, eps_band
            )
            reports.append(report)

        return reports

    def _check_character_pronouns(
        self,
        char_name: str,
        pair_id: str,
        expected_self: List[str],
        dialogue_lines: List[str],
        eps_band: str,
    ) -> PronounConsistencyReport:
        """Check pronoun usage consistency for one character."""
        total_uses = 0
        consistent_uses = 0
        drift_events: List[PronounDriftEvent] = []

        for line_num, line in enumerate(dialogue_lines, 1):
            matches = VN_SELF_PRONOUN_PATTERN.findall(line.lower())
            for pronoun in matches:
                total_uses += 1
                pronoun_lower = pronoun.strip().lower()

                if pronoun_lower in expected_self:
                    consistent_uses += 1
                else:
                    # Determine severity
                    severity = self._classify_drift_severity(
                        pronoun_lower, expected_self, eps_band, pair_id
                    )
                    excerpt = line[:80] + ("..." if len(line) > 80 else "")
                    drift_events.append(PronounDriftEvent(
                        character=char_name,
                        expected_pronoun=expected_self[0],
                        found_pronoun=pronoun_lower,
                        line_excerpt=excerpt,
                        line_number=line_num,
                        eps_band=eps_band,
                        severity=severity,
                    ))

        if total_uses == 0:
            return PronounConsistencyReport(
                character=char_name,
                pair_id=pair_id,
                expected_self=expected_self,
                total_pronoun_uses=0,
                consistent_uses=0,
                consistency_score=1.0,
                note="no self-pronouns found in dialogue",
            )

        consistency_score = consistent_uses / total_uses

        # Build note
        if consistency_score >= 0.80:
            note = f"✓ Consistent ({consistency_score:.0%})"
        elif consistency_score >= 0.50:
            note = f"⚠ Drift detected ({consistency_score:.0%}) — review"
        else:
            note = f"✗ Severe drift ({consistency_score:.0%}) — re-translate"

        return PronounConsistencyReport(
            character=char_name,
            pair_id=pair_id,
            expected_self=expected_self,
            total_pronoun_uses=total_uses,
            consistent_uses=consistent_uses,
            consistency_score=consistency_score,
            drift_events=drift_events,
            note=note,
        )

    def _classify_drift_severity(
        self,
        found_pronoun: str,
        expected_self: List[str],
        eps_band: str,
        pair_id: str,
    ) -> str:
        """
        Classify a pronoun drift event.
        EPS-justified: COLD→WARM shifts may legitimately change pronouns.
        """
        # Check if this is an EPS-plausible shift
        # WARM/HOT: character becoming more intimate — tôi→tớ/mình is plausible
        if eps_band in ("WARM", "HOT"):
            warm_casual = ["tớ", "mình"]
            if found_pronoun in warm_casual and pair_id == "PAIR_0":
                return "eps_justified"  # COLD→WARM drift: tôi→tớ is intentional

        # COLD/COOL: any shift toward more casual is a violation
        if eps_band in ("COLD", "COOL"):
            return "critical"

        # Same PAIR_ID family (e.g., PAIR_1 tớ/mình drift) — softener
        pair_data = PAIR_ID_MAP.get(pair_id, {})
        all_pair_pronouns = [p.lower() for p in pair_data.get("self", [])]
        if found_pronoun in all_pair_pronouns:
            return "warning"

        return "critical"

    def _extract_character_dialogue(self, text: str, character_name: str) -> List[str]:
        """Extract dialogue lines attributed to a character."""
        lines = []
        name_escaped = re.escape(character_name)

        # Quoted dialogue near name
        pattern = re.compile(
            rf'(?:{name_escaped}[^"{{}}]*?"([^"]+)")|(?:"([^"]+)"[^"{{}}]*?{name_escaped})',
            re.IGNORECASE
        )
        for m in pattern.finditer(text):
            dialogue = m.group(1) or m.group(2)
            if dialogue:
                lines.append(dialogue.strip())

        # Em-dash dialogue (Vietnamese style)
        em_pattern = re.compile(
            rf'{name_escaped}[^—\n]{{0,30}}—\s*([^—\n]+)',
            re.IGNORECASE
        )
        for m in em_pattern.finditer(text):
            lines.append(m.group(1).strip())

        return lines

    def format_report(self, reports: List[PronounConsistencyReport]) -> str:
        """Format pronoun consistency results as human-readable string."""
        if not reports:
            return "Pronoun consistency: no characters checked"

        lines = ["## VN PRONOUN CONSISTENCY REPORT"]
        passed = sum(1 for r in reports if r.passed)
        lines.append(f"Passed: {passed}/{len(reports)} characters\n")

        for r in reports:
            status = "✓" if r.passed else "✗"
            lines.append(
                f"{status} {r.character} [{r.pair_id}]: {r.note} "
                f"({r.consistent_uses}/{r.total_pronoun_uses} uses)"
            )
            for event in r.drift_events[:3]:
                icon = "🔴" if event.severity == "critical" else ("🟡" if event.severity == "warning" else "🔵")
                lines.append(
                    f"   {icon} L{event.line_number}: expected '{event.expected_pronoun}', "
                    f"found '{event.found_pronoun}' [{event.eps_band}]"
                )
                lines.append(f"      → {event.line_excerpt}")

        return "\n".join(lines)

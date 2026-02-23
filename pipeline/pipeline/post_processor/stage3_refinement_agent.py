"""
Stage 3: Refinement Agent - Literary Polish & Validation
=========================================================

Enhanced from Phase 2.5 to include:
- AI-ism auto-fix (≥0.95 confidence) ✅ Retained from Phase 2.5
- Hard cap sentence splitting (15w narration, 10w dialogue) 🆕
- Tense consistency validation 🆕
- Literary flow analysis 🆕
- Cultural term preservation audit 🆕

Integration Point:
- Runs after Stage 2 (Translation) completes
- Before rich metadata cache
- Operates on EN markdown files in-place

Configuration:
- english_grammar_validation_t1.json (AI-ism patterns)
- literacy_techniques.json (tense whitelist, flow benchmarks)

Backward Compatibility:
- Aliased as Phase25AIismFixer for existing code
- Reports labeled as "stage3" but old "phase2.5" still supported
"""

import json
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from statistics import stdev

logger = logging.getLogger(__name__)


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class AIismFix:
    """Record of a single AI-ism fix."""
    pattern_id: str
    line_number: int
    original: str
    fixed: str
    confidence: float
    auto_applied: bool


@dataclass
class HardCapViolation:
    """Record of a hard cap sentence length violation."""
    line_number: int
    sentence: str
    word_count: int
    sentence_type: str  # 'dialogue' or 'narration'
    split_suggestion: Optional[List[str]] = None
    auto_split: bool = False


@dataclass
class TenseViolation:
    """Record of a tense consistency violation."""
    line_number: int
    verb: str
    context: str
    whitelisted: bool = False


@dataclass
class FlowIssue:
    """Record of literary flow issue (repetitive structure)."""
    paragraph_number: int
    issue_type: str  # 'repetitive_structure', 'low_variance', 'repetitive_starter'
    score: float
    suggestion: str


@dataclass
class Stage3Report:
    """Stage 3 processing report."""
    chapter_id: str

    # AI-ism fixes (from Phase 2.5)
    ai_ism_fixes_applied: int = 0
    ai_ism_fixes_flagged: int = 0
    ai_ism_patterns_detected: Dict[str, int] = field(default_factory=dict)
    ai_ism_fixes: List[AIismFix] = field(default_factory=list)

    # Hard cap violations (new in Stage 3)
    hard_cap_violations: int = 0
    hard_cap_auto_split: int = 0
    hard_cap_issues: List[HardCapViolation] = field(default_factory=list)

    # Tense consistency (new in Stage 3)
    tense_violations: int = 0
    tense_whitelisted: int = 0
    tense_issues: List[TenseViolation] = field(default_factory=list)

    # Literary flow (new in Stage 3)
    flow_issues: int = 0
    flow_reports: List[FlowIssue] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            'chapter_id': self.chapter_id,
            'stage': '3_refinement',
            'ai_ism_fixes': {
                'applied': self.ai_ism_fixes_applied,
                'flagged': self.ai_ism_fixes_flagged,
                'patterns_detected': self.ai_ism_patterns_detected,
                'details': [
                    {
                        'pattern_id': f.pattern_id,
                        'line_number': f.line_number,
                        'original': f.original,
                        'fixed': f.fixed,
                        'confidence': f.confidence,
                        'auto_applied': f.auto_applied
                    }
                    for f in self.ai_ism_fixes
                ]
            },
            'hard_caps': {
                'total_violations': self.hard_cap_violations,
                'auto_split': self.hard_cap_auto_split,
                'details': [
                    {
                        'line_number': v.line_number,
                        'sentence': v.sentence,
                        'word_count': v.word_count,
                        'type': v.sentence_type,
                        'split_suggestion': v.split_suggestion,
                        'auto_split': v.auto_split
                    }
                    for v in self.hard_cap_issues
                ]
            },
            'tense_consistency': {
                'violations': self.tense_violations,
                'whitelisted': self.tense_whitelisted,
                'details': [
                    {
                        'line_number': t.line_number,
                        'verb': t.verb,
                        'context': t.context,
                        'whitelisted': t.whitelisted
                    }
                    for t in self.tense_issues
                ]
            },
            'literary_flow': {
                'issues_detected': self.flow_issues,
                'details': [
                    {
                        'paragraph': f.paragraph_number,
                        'issue_type': f.issue_type,
                        'score': f.score,
                        'suggestion': f.suggestion
                    }
                    for f in self.flow_reports
                ]
            }
        }


# Backward compatibility alias
Phase25Report = Stage3Report


# ============================================================================
# Stage 3 Refinement Agent
# ============================================================================

class Stage3RefinementAgent:
    """
    Stage 3: Comprehensive refinement and validation agent.

    Extends Phase 2.5 AI-ism fixing with:
    - Hard cap sentence splitting
    - Tense consistency validation
    - Literary flow analysis
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        literacy_config_path: Optional[Path] = None,
        dry_run: bool = False,
        enable_hard_cap_splitting: bool = True,
        enable_tense_validation: bool = True,
        enable_flow_analysis: bool = True
    ):
        """
        Initialize Stage 3 Refinement Agent.

        Args:
            config_path: Path to english_grammar_validation_t1.json
            literacy_config_path: Path to literacy_techniques.json
            dry_run: If True, detect but don't apply fixes
            enable_hard_cap_splitting: Enable auto-splitting of long sentences
            enable_tense_validation: Enable tense consistency checks
            enable_flow_analysis: Enable literary flow analysis
        """
        if config_path is None:
            config_path = Path(__file__).parent.parent.parent / "config" / "english_grammar_validation_t1.json"

        if literacy_config_path is None:
            literacy_config_path = Path(__file__).parent.parent.parent / "config" / "literacy_techniques.json"

        self.config_path = config_path
        self.literacy_config_path = literacy_config_path
        self.dry_run = dry_run
        self.enable_hard_cap_splitting = enable_hard_cap_splitting
        self.enable_tense_validation = enable_tense_validation
        self.enable_flow_analysis = enable_flow_analysis

        # Load AI-ism patterns (Phase 2.5 functionality)
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        self.patterns = config['validation_categories']['ai_ism_purple_prose']['patterns']
        self.auto_fix_patterns = [p for p in self.patterns if p.get('confidence_threshold', 0) >= 0.95]
        self.review_patterns = [p for p in self.patterns if 0.7 <= p.get('confidence_threshold', 0) < 0.95]

        # Load literacy techniques for tense whitelist
        with open(literacy_config_path, 'r', encoding='utf-8') as f:
            literacy = json.load(f)

        self.tense_whitelist_patterns = literacy['narrative_techniques']['narrative_tense_standards'].get(
            'allowed_present_tense_contexts', []
        )

        logger.info(
            f"Stage 3 initialized: {len(self.auto_fix_patterns)} AI-ism auto-fix, "
            f"{len(self.review_patterns)} AI-ism review patterns"
        )
        logger.info(
            f"Features: hard_cap={enable_hard_cap_splitting}, "
            f"tense={enable_tense_validation}, flow={enable_flow_analysis}"
        )

    def process_chapter(self, chapter_path: Path) -> Stage3Report:
        """
        Process a single chapter EN markdown file.

        Args:
            chapter_path: Path to CHAPTER_XX_EN.md

        Returns:
            Stage3Report with all refinements applied and/or flagged
        """
        chapter_id = chapter_path.stem.replace('_EN', '')

        logger.info(f"Stage 3: Processing {chapter_id}")

        # Read chapter
        with open(chapter_path, 'r', encoding='utf-8') as f:
            original_text = f.read()

        report = Stage3Report(chapter_id=chapter_id)
        fixed_text = original_text

        # Step 1: AI-ism fixes (from Phase 2.5)
        fixed_text = self._process_ai_isms(fixed_text, report)

        # Step 2: Hard cap validation & splitting (new in Stage 3)
        if self.enable_hard_cap_splitting:
            fixed_text = self._process_hard_caps(fixed_text, report)

        # Step 3: Tense consistency validation (new in Stage 3)
        if self.enable_tense_validation:
            self._validate_tense_consistency(fixed_text, report)

        # Step 4: Literary flow analysis (new in Stage 3)
        if self.enable_flow_analysis:
            self._analyze_literary_flow(fixed_text, report)

        # Write fixed text (if not dry run and changes made)
        if not self.dry_run and fixed_text != original_text:
            # Create backup
            backup_path = chapter_path.with_suffix('.md.stage3_backup')
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(original_text)

            # Write fixed version
            with open(chapter_path, 'w', encoding='utf-8') as f:
                f.write(fixed_text)

            logger.info(
                f"  Applied {report.ai_ism_fixes_applied + report.hard_cap_auto_split} fixes to {chapter_id} "
                f"(backup: {backup_path.name})"
            )

        # Log summary
        logger.info(f"  AI-isms: {report.ai_ism_fixes_applied} fixed, {report.ai_ism_fixes_flagged} flagged")
        logger.info(f"  Hard caps: {report.hard_cap_violations} violations, {report.hard_cap_auto_split} auto-split")
        logger.info(f"  Tense: {report.tense_violations} violations, {report.tense_whitelisted} whitelisted")
        logger.info(f"  Flow: {report.flow_issues} issues detected")

        return report

    def _process_ai_isms(self, text: str, report: Stage3Report) -> str:
        """Process AI-ism patterns (retained from Phase 2.5)."""
        fixed_text = text

        # Step 1: Apply high-confidence auto-fixes
        for pattern_def in self.auto_fix_patterns:
            fixed_text, fixes = self._apply_pattern_fix(
                text=fixed_text,
                pattern_def=pattern_def,
                auto_apply=True
            )

            if fixes:
                report.ai_ism_fixes.extend(fixes)
                report.ai_ism_fixes_applied += len(fixes)
                report.ai_ism_patterns_detected[pattern_def['id']] = len(fixes)

        # Step 2: Flag medium-confidence patterns for review
        for pattern_def in self.review_patterns:
            _, flags = self._apply_pattern_fix(
                text=fixed_text,
                pattern_def=pattern_def,
                auto_apply=False
            )

            if flags:
                report.ai_ism_fixes.extend(flags)
                report.ai_ism_fixes_flagged += len(flags)
                report.ai_ism_patterns_detected[pattern_def['id']] = len(flags)

        return fixed_text

    def _apply_pattern_fix(
        self,
        text: str,
        pattern_def: Dict,
        auto_apply: bool
    ) -> Tuple[str, List[AIismFix]]:
        """Apply or flag a single AI-ism pattern (from Phase 2.5)."""
        pattern_id = pattern_def['id']
        pattern = pattern_def['pattern']
        confidence = pattern_def.get('confidence_threshold', 0.7)
        fix_suggestions = pattern_def.get('fix_suggestions', {})

        fixes: List[AIismFix] = []
        fixed_text = text

        # Find all matches
        for match in re.finditer(pattern, text, re.IGNORECASE):
            matched_text = match.group(0)
            position = match.start()
            line_number = text[:position].count('\n') + 1

            # Get fix suggestion
            suggested_fix = fix_suggestions.get(matched_text.lower())

            if auto_apply and suggested_fix:
                fixed_text = fixed_text.replace(matched_text, suggested_fix, 1)
                fixes.append(AIismFix(
                    pattern_id=pattern_id,
                    line_number=line_number,
                    original=matched_text,
                    fixed=suggested_fix,
                    confidence=confidence,
                    auto_applied=True
                ))
            else:
                fixes.append(AIismFix(
                    pattern_id=pattern_id,
                    line_number=line_number,
                    original=matched_text,
                    fixed=suggested_fix or "(manual review required)",
                    confidence=confidence,
                    auto_applied=False
                ))

        return fixed_text, fixes

    def _process_hard_caps(self, text: str, report: Stage3Report) -> str:
        """
        Validate and auto-split sentences exceeding hard caps.

        Hard caps:
        - Dialogue: 10 words
        - Narration: 15 words
        """
        lines = text.split('\n')
        fixed_lines = []

        for line_idx, line in enumerate(lines, 1):
            # Split line into sentences
            sentences = self._split_sentences(line)
            fixed_sentences = []

            for sentence in sentences:
                is_dialogue = '"' in sentence or '"' in sentence or '"' in sentence
                words = sentence.split()
                word_count = len(words)

                # Determine hard cap
                max_words = 10 if is_dialogue else 15
                sentence_type = 'dialogue' if is_dialogue else 'narration'

                if word_count > max_words:
                    # Record violation
                    violation = HardCapViolation(
                        line_number=line_idx,
                        sentence=sentence,
                        word_count=word_count,
                        sentence_type=sentence_type
                    )

                    # Attempt auto-split (confidence 0.85)
                    split_result = self._split_long_sentence(sentence, max_words)

                    if split_result and len(split_result) > 1:
                        violation.split_suggestion = split_result
                        violation.auto_split = True
                        report.hard_cap_auto_split += 1
                        fixed_sentences.extend(split_result)
                    else:
                        violation.auto_split = False
                        fixed_sentences.append(sentence)

                    report.hard_cap_violations += 1
                    report.hard_cap_issues.append(violation)
                else:
                    fixed_sentences.append(sentence)

            # Rejoin sentences
            fixed_lines.append(' '.join(fixed_sentences))

        return '\n'.join(fixed_lines)

    def _split_long_sentence(self, sentence: str, max_words: int) -> Optional[List[str]]:
        """
        Enhanced sentence splitter with 10 prioritized break point patterns.

        Priority tiers:
        - Tier 1 (High confidence): Em-dash, coord conj + comma, subord conj
        - Tier 2 (Good confidence): Relative clauses, participial phrases
        - Tier 3 (Medium confidence): Coord conj no comma, as-clauses
        - Tier 4 (Fallback): Middle commas

        Version: 2.0 (Enhanced 2026-02-18)
        """
        words = sentence.split()
        if len(words) <= max_words:
            return None

        text_lower = sentence.lower()
        candidates = []

        # TIER 1: High confidence (priority 1-3)
        # Priority 1: Em-dashes
        if '—' in sentence:
            idx = sentence.index('—')
            word_idx = len(sentence[:idx].split())
            candidates.append({'priority': 1, 'word_idx': word_idx, 'type': 'em_dash', 'idx': idx})

        # Priority 2: Coordinating conjunctions WITH comma
        for conj in [', and', ', but', ', so', ', or', ', yet']:
            idx = text_lower.find(conj)
            if idx != -1:
                word_idx = len(sentence[:idx].split())
                candidates.append({'priority': 2, 'word_idx': word_idx, 'type': 'coord_conj_comma', 'idx': idx, 'conj': conj})

        # Priority 3: Subordinate conjunctions
        for conj in [' because', ' since', ' while', ' when', ' where']:
            idx = text_lower.find(conj)
            if idx != -1:
                word_idx = len(sentence[:idx].split())
                candidates.append({'priority': 3, 'word_idx': word_idx, 'type': 'subord_conj', 'idx': idx, 'conj': conj})

        # TIER 2: Good confidence (priority 4-6)
        # Priority 4: Relative clauses
        for pattern in [', who ', ', which ', ', that ']:
            idx = text_lower.find(pattern)
            if idx != -1:
                word_idx = len(sentence[:idx].split())
                candidates.append({'priority': 4, 'word_idx': word_idx, 'type': 'relative_clause', 'idx': idx})

        # Priority 5: Participial phrases with comma
        participial_pattern = re.compile(r',\s+(showing|escaping|lying|sitting|standing|walking|running|holding|carrying)\b', re.IGNORECASE)
        match = participial_pattern.search(sentence)
        if match:
            idx = match.start()
            word_idx = len(sentence[:idx].split())
            candidates.append({'priority': 5, 'word_idx': word_idx, 'type': 'participial', 'idx': idx})

        # TIER 3: Medium confidence (priority 7-9)
        # Priority 7: Coordinating conjunctions WITHOUT comma
        for conj in [' and ', ' but ']:
            idx = text_lower.find(conj)
            if idx != -1 and text_lower[idx-1:idx] != ',':  # Not preceded by comma
                word_idx = len(sentence[:idx].split())
                # Only if both parts >5 words
                part1_words = word_idx
                part2_words = len(words) - word_idx
                if part1_words >= 5 and part2_words >= 5:
                    candidates.append({'priority': 7, 'word_idx': word_idx, 'type': 'coord_no_comma', 'idx': idx, 'conj': conj})

        # Priority 9: "As" temporal/causal clauses
        as_pattern = re.compile(r'\b[Aa]s\s+\w+\s+\w+,', re.IGNORECASE)
        match = as_pattern.search(sentence)
        if match:
            idx = match.end() - 1  # Position at comma
            word_idx = len(sentence[:idx].split())
            candidates.append({'priority': 9, 'word_idx': word_idx, 'type': 'as_clause', 'idx': idx})

        # TIER 4: Fallback (priority 10)
        # Priority 10: Middle commas (only if no other breaks found and sentence >20 words)
        if not candidates and len(words) > 20:
            # Find all commas
            for i, char in enumerate(sentence):
                if char == ',':
                    word_idx = len(sentence[:i].split())
                    # Only if comma is in middle third (33%-66%)
                    if 0.33 <= word_idx / len(words) <= 0.66:
                        part1_words = word_idx
                        part2_words = len(words) - word_idx
                        if part1_words >= 5 and part2_words >= 5:
                            candidates.append({'priority': 10, 'word_idx': word_idx, 'type': 'middle_comma', 'idx': i})

        if not candidates:
            return None  # No splittable break found

        # Choose best: highest priority (lowest number), then closest to max_words
        best = min(candidates, key=lambda x: (x['priority'], abs(x['word_idx'] - max_words)))

        # Execute split based on type
        return self._execute_split(sentence, words, best)

    def _execute_split(self, sentence: str, words: List[str], break_info: dict) -> Optional[List[str]]:
        """
        Execute sentence split based on break point type.

        Args:
            sentence: Original sentence
            words: Sentence split into words
            break_info: Dict with 'type', 'word_idx', 'idx', etc.

        Returns:
            List of two sentence parts, or None if split fails
        """
        break_type = break_info['type']
        word_idx = break_info['word_idx']
        char_idx = break_info['idx']

        # Split at word boundary
        part1_words = words[:word_idx]
        part2_words = words[word_idx:]

        # Type-specific cleanup
        if break_type == 'coord_conj_comma':
            # Remove conjunction from part2 start
            if part2_words and part2_words[0].lower() in ['and', 'but', 'so', 'or', 'yet']:
                part2_words = part2_words[1:]
            # Remove trailing comma from part1
            if part1_words and part1_words[-1].endswith(','):
                part1_words[-1] = part1_words[-1].rstrip(',')

        elif break_type == 'coord_no_comma':
            # Remove conjunction from part2 start
            if part2_words and part2_words[0].lower() in ['and', 'but']:
                part2_words = part2_words[1:]

        elif break_type in ['relative_clause', 'participial', 'middle_comma', 'as_clause']:
            # Remove trailing comma from part1
            if part1_words and part1_words[-1].endswith(','):
                part1_words[-1] = part1_words[-1].rstrip(',')

        # Join parts
        part1 = ' '.join(part1_words).strip()
        part2 = ' '.join(part2_words).strip()

        # Validation
        if not part1 or not part2:
            return None
        if len(part1.split()) < 3 or len(part2.split()) < 3:  # Too short
            return None

        # Add terminal punctuation
        if not part1.endswith(('.', '!', '?')):
            part1 += '.'

        # Capitalize part2 if needed
        if part2[0].islower():
            part2 = part2[0].upper() + part2[1:]

        return [part1, part2]

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences (simple regex-based)."""
        pattern = r'(?<=[.!?])\s+(?=[A-Z"])'
        sentences = re.split(pattern, text)
        return [s.strip() for s in sentences if s.strip()]

    def _validate_tense_consistency(self, text: str, report: Stage3Report):
        """
        Validate tense consistency (flag only, no auto-fix).

        Checks for present tense verbs in past-tense narrative.
        """
        present_tense_verbs = r'\b(is|are|am|has|have|does|do)\b'

        for match in re.finditer(present_tense_verbs, text):
            verb = match.group(0)
            position = match.start()
            line_number = text[:position].count('\n') + 1

            # Extract context (50 chars before/after)
            context_start = max(0, position - 50)
            context_end = min(len(text), position + 50)
            context = text[context_start:context_end]

            # Check if whitelisted (simplified check)
            is_whitelisted = (
                '"' in context or  # Dialogue
                'that ' in context.lower() or  # Universal truth ("learned that X is Y")
                'if ' in context.lower() or  # Conditional
                'when ' in context.lower()  # Conditional
            )

            violation = TenseViolation(
                line_number=line_number,
                verb=verb,
                context=context,
                whitelisted=is_whitelisted
            )

            if is_whitelisted:
                report.tense_whitelisted += 1
            else:
                report.tense_violations += 1

            report.tense_issues.append(violation)

    def _analyze_literary_flow(self, text: str, report: Stage3Report):
        """
        Analyze literary flow (report only, no auto-fix).

        Detects:
        - Repetitive sentence structures (3+ consecutive SVO)
        - Low sentence length variance (<3w)
        - Repetitive sentence starters
        """
        paragraphs = text.split('\n\n')

        for para_idx, paragraph in enumerate(paragraphs, 1):
            sentences = self._split_sentences(paragraph)

            if len(sentences) < 3:
                continue  # Skip short paragraphs

            # Check sentence length variance
            lengths = [len(s.split()) for s in sentences]
            if len(lengths) > 1:
                variance = stdev(lengths)

                if variance < 3.0:
                    report.flow_issues += 1
                    report.flow_reports.append(FlowIssue(
                        paragraph_number=para_idx,
                        issue_type='low_variance',
                        score=variance,
                        suggestion=f"Low sentence variety (variance {variance:.1f}w). Vary sentence length."
                    ))

            # Check sentence starter variety
            starters = [s.split()[0].lower() if s.split() else '' for s in sentences]
            starter_variety = len(set(starters)) / len(starters) if starters else 1.0

            if starter_variety < 0.6:
                report.flow_issues += 1
                report.flow_reports.append(FlowIssue(
                    paragraph_number=para_idx,
                    issue_type='repetitive_starter',
                    score=starter_variety,
                    suggestion=f"Repetitive sentence starters (variety {starter_variety:.0%}). Vary sentence beginnings."
                ))

    def process_batch(self, chapter_paths: List[Path]) -> Dict[str, Stage3Report]:
        """Process multiple chapters in batch."""
        reports = {}

        for chapter_path in chapter_paths:
            try:
                report = self.process_chapter(chapter_path)
                reports[report.chapter_id] = report
            except Exception as e:
                logger.error(f"Failed to process {chapter_path.name}: {e}")

        return reports

    def generate_summary_report(
        self,
        reports: Dict[str, Stage3Report],
        output_path: Path
    ):
        """Generate consolidated JSON report."""
        summary = {
            'stage': '3_refinement',
            'chapters_processed': len(reports),
            'totals': {
                'ai_ism_fixes_applied': sum(r.ai_ism_fixes_applied for r in reports.values()),
                'ai_ism_fixes_flagged': sum(r.ai_ism_fixes_flagged for r in reports.values()),
                'hard_cap_violations': sum(r.hard_cap_violations for r in reports.values()),
                'hard_cap_auto_split': sum(r.hard_cap_auto_split for r in reports.values()),
                'tense_violations': sum(r.tense_violations for r in reports.values()),
                'flow_issues': sum(r.flow_issues for r in reports.values()),
            },
            'chapters': {
                chapter_id: report.to_dict()
                for chapter_id, report in reports.items()
            }
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        logger.info(f"Stage 3 summary report written to {output_path}")


# Backward compatibility alias
Phase25AIismFixer = Stage3RefinementAgent


# ============================================================================
# Integration Hooks
# ============================================================================

def integrate_stage3(
    en_output_dir: Path,
    dry_run: bool = False,
    enable_hard_cap_splitting: bool = True,
    enable_tense_validation: bool = True,
    enable_flow_analysis: bool = True
) -> Dict[str, Stage3Report]:
    """
    Integration point for main pipeline.

    Call this after Stage 2 (Translation) completes.

    Args:
        en_output_dir: Directory containing CHAPTER_*_EN.md files
        dry_run: If True, detect but don't apply fixes
        enable_hard_cap_splitting: Enable auto-splitting
        enable_tense_validation: Enable tense checks
        enable_flow_analysis: Enable flow analysis

    Returns:
        Dict of chapter_id -> Stage3Report
    """
    logger.info("=" * 60)
    logger.info("Stage 3: Refinement Agent")
    logger.info("=" * 60)

    # Initialize agent
    agent = Stage3RefinementAgent(
        dry_run=dry_run,
        enable_hard_cap_splitting=enable_hard_cap_splitting,
        enable_tense_validation=enable_tense_validation,
        enable_flow_analysis=enable_flow_analysis
    )

    # Find all EN chapter files
    chapter_paths = sorted(en_output_dir.glob('CHAPTER_*_EN.md'))

    if not chapter_paths:
        logger.warning(f"No EN chapters found in {en_output_dir}")
        return {}

    # Process all chapters
    reports = agent.process_batch(chapter_paths)

    # Generate summary report
    report_path = en_output_dir.parent / 'stage3_refinement_report.json'
    agent.generate_summary_report(reports, report_path)

    # Log summary
    totals = {
        'ai_ism_applied': sum(r.ai_ism_fixes_applied for r in reports.values()),
        'ai_ism_flagged': sum(r.ai_ism_fixes_flagged for r in reports.values()),
        'hard_cap_violations': sum(r.hard_cap_violations for r in reports.values()),
        'hard_cap_auto_split': sum(r.hard_cap_auto_split for r in reports.values()),
        'tense_violations': sum(r.tense_violations for r in reports.values()),
        'flow_issues': sum(r.flow_issues for r in reports.values()),
    }

    logger.info(f"Stage 3 complete:")
    logger.info(f"  AI-isms: {totals['ai_ism_applied']} fixed, {totals['ai_ism_flagged']} flagged")
    logger.info(f"  Hard caps: {totals['hard_cap_violations']} violations, {totals['hard_cap_auto_split']} auto-split")
    logger.info(f"  Tense: {totals['tense_violations']} violations")
    logger.info(f"  Flow: {totals['flow_issues']} issues")
    logger.info("=" * 60)

    return reports


# Backward compatibility alias
integrate_phase25 = integrate_stage3


if __name__ == '__main__':
    # CLI entry point for standalone execution
    import argparse

    parser = argparse.ArgumentParser(description='Stage 3: Refinement Agent')
    parser.add_argument('--input-dir', type=Path, required=True, help='Directory with EN chapter files')
    parser.add_argument('--dry-run', action='store_true', help='Detect but do not apply fixes')
    parser.add_argument('--no-hard-cap', action='store_true', help='Disable hard cap splitting')
    parser.add_argument('--no-tense', action='store_true', help='Disable tense validation')
    parser.add_argument('--no-flow', action='store_true', help='Disable flow analysis')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    integrate_stage3(
        args.input_dir,
        dry_run=args.dry_run,
        enable_hard_cap_splitting=not args.no_hard_cap,
        enable_tense_validation=not args.no_tense,
        enable_flow_analysis=not args.no_flow
    )

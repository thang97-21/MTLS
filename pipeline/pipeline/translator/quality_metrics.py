"""
Translation Quality Metrics.
Calculates metrics for self-auditing translation quality.
"""

import re
import logging
from typing import List, Tuple, Dict, Any, Optional
from dataclasses import dataclass, field
from pipeline.translator.config import get_quality_threshold, get_translation_config

logger = logging.getLogger(__name__)

@dataclass
class AuditResult:
    contraction_rate: float
    ai_ism_count: int
    ai_isms_found: List[str]
    illustrations_preserved: bool
    missing_illustrations: List[str]
    warnings: List[str]
    passed: bool
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "contraction_rate": self.contraction_rate,
            "ai_ism_count": self.ai_ism_count,
            "ai_isms_found": self.ai_isms_found,
            "illustrations_preserved": self.illustrations_preserved,
            "missing_illustrations": self.missing_illustrations,
            "warnings": self.warnings,
            "passed": self.passed
        }

class QualityMetrics:
    # Critical contraction patterns (Yen Press/J-Novel Club Gold Standard)
    # Priority 1: MUST contract in casual contexts - "it is", "that is", "there is"
    CRITICAL_CONTRACTIBLE = [
        (r"\bit is\b", "it's"),
        (r"\bthat is\b", "that's"),
        (r"\bthere is\b", "there's"),
        (r"\bhere is\b", "here's"),
        (r"\bwhat is\b", "what's"),
        (r"\bwho is\b", "who's"),
        (r"\bdo not\b", "don't"),
        (r"\bdoes not\b", "doesn't"),
    ]
    
    # Priority 2: High priority - negative contractions
    HIGH_PRIORITY_CONTRACTIBLE = [
        (r"\bwas not\b", "wasn't"),
        (r"\bwere not\b", "weren't"),
        (r"\bcould not\b", "couldn't"),
        (r"\bshould not\b", "shouldn't"),
        (r"\bwould not\b", "wouldn't"),
        (r"\bdid not\b", "didn't"),
        (r"\bhad not\b", "hadn't"),
    ]
    
    # Priority 3: Standard contractions
    STANDARD_CONTRACTIBLE = [
        (r"\bis not\b", "isn't"),
        (r"\bare not\b", "aren't"),
        (r"\bhave not\b", "haven't"),
        (r"\bhas not\b", "hasn't"),
        (r"\bwill not\b", "won't"),
        (r"\bcannot\b", "can't"),
        (r"\bI am\b", "I'm"),
        (r"\byou are\b", "you're"),
        (r"\bwe are\b", "we're"),
        (r"\bthey are\b", "they're"),
        (r"\bI will\b", "I'll"),
        (r"\byou will\b", "you'll"),
        (r"\bI have\b", "I've"),
        (r"\byou have\b", "you've"),
        (r"\blet us\b", "let's"),
    ]
    
    # J-Novel Club perfect tense contractions (internal monologue)
    PERFECT_TENSE_CONTRACTIBLE = [
        (r"\bwould have\b", "would've"),
        (r"\bcould have\b", "could've"),
        (r"\bshould have\b", "should've"),
        (r"\bmight have\b", "might've"),
        (r"\bmust have\b", "must've"),
    ]
    
    # Combined pattern list (all priorities)
    CONTRACTIBLE_PATTERNS = (
        CRITICAL_CONTRACTIBLE + 
        HIGH_PRIORITY_CONTRACTIBLE + 
        STANDARD_CONTRACTIBLE + 
        PERFECT_TENSE_CONTRACTIBLE
    )
    
    # Default AI-isms if not in config
    DEFAULT_AI_ISMS = [
        "indeed", "quite", "rather", "I shall",
        "most certainly", "if you will", "as it were",
        "one might say", "it would seem", "I daresay",
        "it cannot be helped", "shikatanai"
    ]

    _APOSTROPHE_TRANSLATION = str.maketrans({
        "\u2019": "'",  # right single quotation mark
        "\u2018": "'",  # left single quotation mark
        "`": "'",       # grave accent used as apostrophe in some outputs
    })

    @staticmethod
    def _normalize_apostrophes(text: str) -> str:
        """Normalize common apostrophe variants for stable contraction matching."""
        if not text:
            return text
        return text.translate(QualityMetrics._APOSTROPHE_TRANSLATION)

    @staticmethod
    def calculate_contraction_rate(text: str) -> float:
        """
        Calculate contraction rate in dialogue.
        Rate = (contracted forms) / (contracted forms + uncontracted content words)
        
        This is a heuristic. A better approach is:
        Rate = (actual contractions) / (actual contractions + missed contraction opportunities)
        """
        if not text:
            return 0.0

        text = QualityMetrics._normalize_apostrophes(text)

        contracted_count = 0
        missed_count = 0
        
        # Simple tokenization for analysis
        # We focus on dialogue only if possible, but full text is okay for rough metric
        
        # Count actual contractions (apostrophe + s/t/re/ll/ve/m/d)
        contracted_count += len(re.findall(r"\w+'(?:t|s|re|ll|ve|m|d)\b", text, re.IGNORECASE))
        contracted_count += len(re.findall(r"\bwanna\b|\bgonna\b|\bgotta\b", text, re.IGNORECASE))

        # Count missed opportunities
        for pattern, _ in QualityMetrics.CONTRACTIBLE_PATTERNS:
            missed_count += len(re.findall(pattern, text, re.IGNORECASE))
            
        total_opportunities = contracted_count + missed_count
        if total_opportunities == 0:
            return 1.0 # No opportunities = good (avoid division by zero)
            
        return contracted_count / total_opportunities

    @staticmethod
    def count_ai_isms(text: str, patterns: List[str] = None) -> Tuple[int, List[str]]:
        """Count occurrences of known AI-ism patterns."""
        if not patterns:
            # Load from config or use defaults
            config = get_translation_config()
            # Try to get from critics config if available, else translation
            # For now use hardcoded defaults + generic list
            patterns = QualityMetrics.DEFAULT_AI_ISMS

        found = []
        count = 0
        
        for pattern in patterns:
            matches = re.findall(r"\b" + re.escape(pattern) + r"\b", text, re.IGNORECASE)
            if matches:
                count += len(matches)
                found.extend(matches)
                
        return count, list(set(found)) # Unique types found

    @staticmethod
    def check_illustration_preservation(source: str, translated: str) -> Tuple[bool, List[str]]:
        """
        Verify all [ILLUSTRATION: ...] tags in source appear in translation.
        Robust against whitespace differences.
        """
        # Extract tags: [ILLUSTRATION: filename.jpg]
        tag_pattern = r"\[ILLUSTRATION:\s*(.*?)\]"
        
        source_tags = re.findall(tag_pattern, source)
        translated_tags = re.findall(tag_pattern, translated)
        
        # Normalize for comparison (remove whitespace, lowercase)
        src_norm = [t.strip().lower() for t in source_tags]
        trans_norm = [t.strip().lower() for t in translated_tags]
        
        missing = []
        for tag, norm in zip(source_tags, src_norm):
            if norm not in trans_norm:
                missing.append(tag)
                
        return (len(missing) == 0), missing

    @staticmethod
    def quick_audit(translated_text: str, source_text: str = "") -> AuditResult:
        """Perform a quick quality audit on the translated text."""
        
        # 1. Contraction Rate
        contraction_rate = QualityMetrics.calculate_contraction_rate(translated_text)
        
        # 2. AI-isms
        ai_ism_count, ai_isms_found = QualityMetrics.count_ai_isms(translated_text)
        
        # 3. Illustration Check
        ills_preserved = True
        missing_ills = []
        if source_text:
            ills_preserved, missing_ills = QualityMetrics.check_illustration_preservation(
                source_text, translated_text
            )
            
        # 4. Determine warnings & pass/fail
        warnings = []
        threshold = get_quality_threshold()
        
        if contraction_rate < threshold:
            warnings.append(f"Low contraction rate: {contraction_rate:.2f} (Target: {threshold})")
            
        if ai_ism_count > 5:
            warnings.append(f"High AI-ism count: {ai_ism_count} found")
            
        if not ills_preserved:
            warnings.append(f"Missing illustrations: {len(missing_ills)}")
            
        # Logic for 'passed' - loose for translator phase (just warnings), strictest for Critics
        # For Translator: Fail only on missing illustrations or critical errors
        passed = ills_preserved
        
        return AuditResult(
            contraction_rate=contraction_rate,
            ai_ism_count=ai_ism_count,
            ai_isms_found=ai_isms_found,
            illustrations_preserved=ills_preserved,
            missing_illustrations=missing_ills,
            warnings=warnings,
            passed=passed
        )

    # =========================================================================
    # VIETNAMESE QUALITY METRICS (DEBUG LOGGING)
    # =========================================================================

    # Vietnamese AI-ism patterns - Organized by severity (matching EN structure)
    # CRITICAL: Must eliminate - these are the most obvious AI-isms
    VN_AI_ISM_CRITICAL = [
        r"một cảm giác",           # "a sense of" → direct emotion
        r"một cách",               # "in a [adj] way" → direct adverb
        r"cảm thấy một cảm giác", # "felt a sense of" → direct feeling
        r"việc \w+ là",            # "the fact that [verb]" → restructure
        r"sự \w+ là",              # "the [noun]ing is" → restructure
        r"phát \w+ pheromone",     # "release pheromones" → ooze allure
    ]

    # MAJOR: High priority - common translationese patterns
    VN_AI_ISM_MAJOR = [
        # Filter phrases (perception wrappers)
        r"cảm giác như",           # "felt like" → direct statement
        r"dường như",              # "seemed like" → direct verb
        r"có vẻ như",              # "appeared to be" → direct verb
        r"có vẻ là",               # "it seems that" → direct statement
        r"có thể cảm thấy",        # "could sense" → direct observation
        r"nhận thức được",         # "was aware that" → direct statement
        r"nhận ra rằng",           # "realized that" → just state it
        r"để ý thấy",              # "took note that" → direct observation

        # Process verbs (unnecessary "begin/start" wrappers)
        r"bắt đầu \w+",           # "began to [verb]" → direct verb
        r"bắt tay",               # "began to" → direct verb
        r"tiến hành",             # "proceeded to" → direct verb
        r"cố gắng",               # "tried to" → direct verb (unless difficulty matters)

        # Nominalizations (noun-heavy structures)
        r"thực tế là",             # "the fact is that" → "that" or restructure
        r"ý tưởng rằng",          # "the idea that" → "that" or direct
        r"lý do tại sao",         # "the reason why" → "why"
        r"cách mà",               # "the way that" → "how"

        # Wordy connectors
        r"để có thể",             # "in order to be able" → "to"
        r"với mục đích",          # "for the purpose of" → "to"
        r"trong quá trình",       # "during the process of" → -ing form

        # Hedge words (overuse dilutes meaning)
        r"hơi \w+",               # "somewhat [adj]" → use sparingly
        r"khá \w+",               # "quite [adj]" → use sparingly
        r"tương đối",            # "relatively [adj]" → use sparingly
        r"một chút",              # "a bit [adj]" → use sparingly

        # Japanese calques (literal translations from JP)
        r"không thể giúp được",   # "cannot be helped" → "nothing I can do"
        r"tôi sẽ cố gắng hết sức", # "I'll do my best" → "Here goes!"
        r"đúng như mong đợi từ", # "as expected from" → "classic [Name]"
        r"phải không \?",          # formal "is that so?" → casual alternatives
    ]

    # MINOR: Minor issues - polish when possible
    VN_AI_ISM_MINOR = [
        # Redundant expressions
        r"có một",                 # "there is a [noun]" → restructure
        r"một điều",             # "one thing" → restructure
        r"thực sự mà nói",       # "if I'm being honest" → too formal
        r"về mặt",               # "in terms of" → restructure

        # Over-formal constructions
        r"vị trí của",            # "the position of" → "the [noun]'s"
        r"sự hiện diện của",     # "the presence of" → restructure
        r"hành vi của",          # "the behavior of" → restructure
        r"bản chất của",         # "the nature of" → restructure
        r"nguyên nhân của",      # "the cause of" → restructure
        r"kết quả của",         # "the result of" → restructure
        r"hoàn cảnh của",       # "the circumstances of" → restructure
        r"nội dung của",        # "the content of" → restructure

        # Weak intensifiers (overuse)
        r"khá là",                # "it's quite [adj]" → use sparingly
        r"tương đối là",         # "it's relatively [adj]" → use sparingly
        r"hơi là",               # "it's a bit [adj]" → use sparingly

        # Passive voice (can be okay, but watch for overuse)
        r"được \w+ bởi",         # "is [verb]ed by" → restructure
        r"bị \w+ bởi",          # "is [verb]ed by" → restructure

        # Sentence starters (variety issues)
        r"thật ra",               # "actually" → vary sentence starts
        r"nói thật",             # "to be honest" → vary sentence starts
        r"nói chung",            # "generally speaking" → vary sentence starts
        r"trên thực tế",        # "in fact" → vary sentence starts

        # Time expressions (stiff)
        r"vào lúc",             # "at the time when" → "when"
        r"tại thời điểm",       # "at the point in time" → "when"
        r"trước đó",            # "before that" → "before"
        r"sau đó",               # "after that" → "then/after"
        r"ngay lập tức",        # "immediately" → vary

        # Additional formal phrases
        r"theo như",             # "according to" → vary
        r"như đã nói",          # "as previously mentioned" → vary
        r"điều đáng lưu ý",     # "notably" → vary
        r"ngoài ra",            # "furthermore" → vary
        r"tuy nhiên",           # "however" → use sparingly
        r"hơn nữa",             # "moreover" → vary
    ]

    # Combined list for convenience
    VN_AI_ISM_PATTERNS = VN_AI_ISM_CRITICAL + VN_AI_ISM_MAJOR + VN_AI_ISM_MINOR

    # Vietnamese particles (for density calculation)
    VN_PARTICLES = [
        r"rồi", r"đấy", r"đó", r"nè", r"nha", r"nhé",
        r"ạ", r"ơi", r"à", r"ờ", r"hử", r"đúng không",
        r"chứ", r"đâu", r"nhỉ", r"nhể", r"hở"
    ]

    # Vietnamese contraction patterns (casual dialogue)
    VN_CONTRACTION_PATTERNS = [
        r"tôi dạ", r"anh ấy -> nó", r"cô ấy -> cô",
        r"tôi tôi", r"anh anh", r"em em", r"mình mình",
        r"đã rồi", r"đang đây", r"vừa mới",
        r"thì thôi", r"rồi rồi", r"được rồi",
    ]

    @classmethod
    def calculate_vn_quality_metrics(cls, text: str) -> Dict[str, Any]:
        """
        Calculate Vietnamese-specific quality metrics for debug logging.
        This is NOT used for pass/fail - only for quality monitoring.

        Returns dict with:
        - ai_ism_count: Number of AI-ism patterns found
        - ai_isms_found: List of specific AI-isms detected
        - particle_density: Ratio of dialogue lines with particles
        - contraction_rate: Estimated contraction usage (simplified)
        - han_viet_ratio: Estimated Han-Viet word ratio
        """
        if not text:
            return {
                "ai_ism_count": 0,
                "ai_isms_found": [],
                "particle_density": 0.0,
                "contraction_rate": 0.0,
                "han_viet_ratio": 0.0,
                "word_count": 0,
            }

        word_count = len(text.split())

        # 1. Count Vietnamese AI-isms
        ai_isms_found = []
        for pattern in cls.VN_AI_ISM_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                ai_isms_found.append(match.strip())

        # 2. Calculate particle density
        # Simplified: count sentences with particles
        sentences = re.split(r'[.!?]+', text)
        sentences_with_particles = 0
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence:
                has_particle = any(
                    re.search(r'\b' + p + r'\b', sentence)
                    for p in cls.VN_PARTICLES
                )
                if has_particle:
                    sentences_with_particles += 1

        particle_density = (
            sentences_with_particles / len(sentences)
            if sentences else 0.0
        )

        # 3. Estimate contraction rate (simplified check)
        contraction_count = 0
        for pattern in cls.VN_CONTRACTION_PATTERNS:
            if "->" in pattern:
                # Handle mapping format
                original = pattern.split("->")[0].strip()
                contraction_count += len(re.findall(original, text))
            else:
                contraction_count += len(re.findall(pattern, text))

        contraction_rate = (
            contraction_count / word_count * 100
            if word_count > 0 else 0.0
        )

        # 4. Estimate Han-Viet ratio (simplified check for common patterns)
        han_viet_count = len(re.findall(
            r'\b(có thể|bởi vì|tuy nhiên|tuy vậy|nhân tiện|từ đó|nếu như|khi mà|tuy nhiên)\b',
            text, re.IGNORECASE
        ))
        han_viet_ratio = (
            han_viet_count / word_count * 100
            if word_count > 0 else 0.0
        )

        return {
            "ai_ism_count": len(ai_isms_found),
            "ai_isms_found": ai_isms_found[:10],  # Limit to first 10
            "particle_density": round(particle_density, 3),
            "contraction_rate": round(contraction_rate, 2),
            "han_viet_ratio": round(han_viet_ratio, 2),
            "word_count": word_count,
        }

    @classmethod
    def log_vn_quality_debug(cls, text: str, chapter_id: str = "unknown") -> None:
        """
        Log Vietnamese quality metrics as debug output.
        This is for monitoring only - does not affect translation pass/fail.
        """
        metrics = cls.calculate_vn_quality_metrics(text)

        logger.debug(f"[VN_QUALITY] Chapter: {chapter_id}")
        logger.debug(f"[VN_QUALITY]   Word count: {metrics['word_count']}")
        logger.debug(f"[VN_QUALITY]   AI-ism count: {metrics['ai_ism_count']}")
        if metrics['ai_isms_found']:
            logger.debug(f"[VN_QUALITY]   AI-isms found: {', '.join(metrics['ai_isms_found'][:5])}")
        logger.debug(f"[VN_QUALITY]   Particle density: {metrics['particle_density']:.1%} (target: 80%)")
        logger.debug(f"[VN_QUALITY]   Contraction rate: {metrics['contraction_rate']:.1f}/100 words")
        logger.debug(f"[VN_QUALITY]   Han-Viet ratio: {metrics['han_viet_ratio']:.1f}%")

        # Log warnings if below targets
        if metrics['ai_ism_count'] > 3:
            logger.warning(f"[VN_QUALITY] High AI-ism count: {metrics['ai_ism_count']} (target: <3)")
        if metrics['particle_density'] < 0.60:
            logger.warning(f"[VN_QUALITY] Low particle density: {metrics['particle_density']:.1%} (target: 80%)")

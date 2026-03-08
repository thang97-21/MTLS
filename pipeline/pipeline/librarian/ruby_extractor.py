"""
Ruby Text Extractor - Extract character names from ruby annotations.

Scans EPUB XHTML for ruby-annotated character names only.

Enhanced to handle:
- Standard ruby annotations (kanji + hiragana reading)
- Kira-kira names (kanji with unexpected katakana reading)
- Fragmented name annotations (surname and given name annotated separately)
- First-person introduction patterns (俺、[NAME]は...)
- 4-kanji full names (surname + given name)

Now uses JSON-based filter patterns for extensibility.
"""

import re
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, asdict, field
from bs4 import BeautifulSoup, Tag
from collections import Counter, defaultdict

from .name_filters import load_filters, LoadedFilters

logger = logging.getLogger(__name__)


@dataclass
class RubyEntry:
    """Single ruby-annotated character name with context."""
    kanji: str  # Base text (e.g., "東雲" or "レオン" for katakana)
    ruby: str   # Ruby reading (e.g., "しののめ" or "" for katakana-only)
    context: str  # Surrounding text snippet
    source_file: str  # Which chapter file
    confidence: float = 1.0  # Classification confidence
    name_type: str = "standard"  # standard, kirakira, fragmented, katakana
    notes: str = ""  # Additional notes (e.g., "unusual reading", "kira-kira name")
    ruby_style: str = "narou"  # narou, interweave, kirakira - how ruby annotation is structured

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FragmentedName:
    """Tracks potential fragmented name parts for assembly."""
    parts: List[Tuple[str, str]] = field(default_factory=list)  # (kanji, ruby) pairs
    contexts: List[str] = field(default_factory=list)
    source_files: Set[str] = field(default_factory=set)


class RubyExtractor:
    """Extract and classify ruby-annotated text from EPUB content."""

    # Patterns for classification (these are regex, not data - keep as class vars)
    KATAKANA_PATTERN = re.compile(r'[\u30A0-\u30FF]+')  # Katakana (often names)
    HIRAGANA_PATTERN = re.compile(r'[\u3040-\u309F]+')  # Hiragana (often terms)
    KANJI_PATTERN = re.compile(r'[\u4E00-\u9FFF]+')     # Kanji

    # Katakana name detection (for fantasy/isekai light novels)
    KATAKANA_NAME_PATTERN = re.compile(r'[\u30A0-\u30FF]{3,}')  # 3+ katakana chars

    def __init__(self, genres: Optional[List[str]] = None):
        """
        Initialize the ruby extractor.

        Args:
            genres: Optional list of genre names for filter loading.
                    E.g., ["isekai"], ["school_life"], or ["isekai", "school_life"]
        """
        self.entries: List[RubyEntry] = []
        self.seen_entries: set = set()  # Deduplicate
        self.katakana_candidates: Counter = Counter()  # Track katakana frequency
        self.fragmented_candidates: Dict[str, FragmentedName] = defaultdict(FragmentedName)
        self.kirakira_names: List[RubyEntry] = []  # Track kira-kira names separately

        # Load filters from JSON
        self._filters: LoadedFilters = load_filters(genres)
        self._genres = genres or []

        # Create convenient references to loaded filter data
        self._katakana_common_words = self._filters.katakana_common_words
        self._kanji_stylistic_ruby = self._filters.kanji_stylistic_ruby
        self._common_terms = self._filters.common_terms
        self._name_suffixes = self._filters.name_indicators.suffixes
        self._intro_patterns = self._filters.name_indicators.intro_patterns
        self._first_person_pronouns = self._filters.name_indicators.first_person_pronouns
        self._confidence_threshold = self._filters.confidence_modifiers.threshold

        logger.debug(f"Loaded filters: {self._filters.loaded_filters}")

    def extract_from_xhtml(self, xhtml_content: str, source_file: str) -> List[RubyEntry]:
        """
        Extract ruby entries from XHTML content.

        Args:
            xhtml_content: Raw XHTML string
            source_file: Filename for tracking

        Returns:
            List of RubyEntry objects
        """
        soup = BeautifulSoup(xhtml_content, 'xml')
        ruby_tags = soup.find_all('ruby')

        extracted = []

        # First pass: collect all ruby annotations
        all_ruby_entries = []
        for ruby_tag in ruby_tags:
            entry = self._parse_ruby_tag(ruby_tag, source_file)
            if entry:
                all_ruby_entries.append(entry)

        # Second pass: classify and filter
        for entry in all_ruby_entries:
            # Check for kira-kira name (kanji with katakana reading)
            is_kirakira = self._is_kirakira_name(entry.kanji, entry.ruby)

            if is_kirakira:
                entry.name_type = "kirakira"
                entry.ruby_style = "kirakira"
                entry.notes = f"Kira-kira name: {entry.kanji} read as {entry.ruby}"
                entry.confidence = 0.98

                key = (entry.kanji, entry.ruby)
                if key not in self.seen_entries:
                    self.seen_entries.add(key)
                    extracted.append(entry)
                    self.kirakira_names.append(entry)
                continue

            # Check if it's a standard character name
            confidence = self._is_character_name(entry.kanji, entry.ruby, entry.context)
            if confidence >= 0.70:  # Lowered threshold for better recall
                entry.confidence = confidence

                # Deduplicate (same kanji+ruby combo)
                key = (entry.kanji, entry.ruby)
                if key not in self.seen_entries:
                    self.seen_entries.add(key)
                    extracted.append(entry)
            else:
                # Track potential name fragments (2-char kanji with hiragana ruby)
                self._track_fragment(entry, source_file)

        # Also extract standalone katakana names (for fantasy LNs)
        katakana_entries = self._extract_katakana_names(xhtml_content, source_file)
        extracted.extend(katakana_entries)

        return extracted

    def _is_kirakira_name(self, kanji: str, ruby: str) -> bool:
        """
        Detect kira-kira names where kanji has unexpected katakana reading.

        Kira-kira names are modern Japanese names where:
        - The kanji looks normal (e.g., 愛梨, 心愛, 光宙)
        - But the reading is in katakana (e.g., ラブリ, ココア, ピカチュウ)

        Args:
            kanji: Base text
            ruby: Ruby reading

        Returns:
            True if this appears to be a kira-kira name
        """
        # Must have kanji in base and katakana in ruby
        has_kanji = bool(self.KANJI_PATTERN.search(kanji))
        has_katakana_ruby = bool(self.KATAKANA_PATTERN.fullmatch(ruby))

        if not (has_kanji and has_katakana_ruby):
            return False

        # Typical kira-kira name: 2-3 kanji, 3-6 katakana reading
        kanji_count = sum(1 for c in kanji if '\u4E00' <= c <= '\u9FFF')
        if not (1 <= kanji_count <= 4):
            return False

        if not (2 <= len(ruby) <= 8):
            return False

        # Exclude common katakana words as readings
        if ruby in self._katakana_common_words:
            return False

        # Exclude common kanji that often get stylistic katakana ruby
        if kanji in self._kanji_stylistic_ruby:
            return False

        # Single kanji with katakana ruby is usually stylistic, not a name
        if len(kanji) == 1:
            return False

        return True

    def _track_fragment(self, entry: RubyEntry, source_file: str) -> None:
        """Track potential name fragments for later assembly."""
        # Track 1-3 char entries with hiragana ruby.
        # Single-kanji entries are only kept when context-qualified to avoid noise.
        if not (1 <= len(entry.kanji) <= 3):
            return
        if not self.HIRAGANA_PATTERN.fullmatch(entry.ruby):
            return
        if entry.kanji in self._common_terms:
            return
        if len(entry.kanji) == 1 and not self._is_context_qualified_single_kanji_name(
            entry.kanji,
            entry.ruby,
            entry.context,
        ):
            return

        # Use ruby as key for grouping (same reading = possibly related)
        # Store for potential later assembly
        self.fragmented_candidates[entry.ruby].parts.append((entry.kanji, entry.ruby))
        self.fragmented_candidates[entry.ruby].contexts.append(entry.context)
        self.fragmented_candidates[entry.ruby].source_files.add(source_file)

    def _is_context_qualified_single_kanji_name(self, kanji: str, ruby: str, context: str) -> bool:
        """Return True when a single-kanji ruby token is likely a given name."""
        if not kanji or len(kanji) != 1:
            return False
        if kanji in self._common_terms:
            return False
        if not self.HIRAGANA_PATTERN.fullmatch(ruby or ""):
            return False

        honorific_patterns = [
            f"{kanji}ちゃん",
            f"{kanji}くん",
            f"{kanji}さん",
            f"{kanji}様",
            f"{kanji}先輩",
            f"{kanji}は",
            f"{kanji}が",
            f"{kanji}って",
            f"{kanji}の読み方",
        ]
        if any(p in context for p in honorific_patterns):
            return True

        # Strict fallback: only quoted direct address forms.
        dialogue_patterns = [
            f"「{kanji}ちゃん",
            f"「{kanji}くん",
            f"「{kanji}さん",
            f"『{kanji}ちゃん",
            f"『{kanji}くん",
            f"『{kanji}さん",
            f"「{kanji}」",
            f"『{kanji}』",
        ]
        return any(p in context for p in dialogue_patterns)

    def _extract_katakana_names(self, xhtml_content: str, source_file: str) -> List[RubyEntry]:
        """
        Extract standalone katakana character names (for fantasy/isekai light novels).

        Now more conservative to avoid false positives like イケメン, スマホ.
        """
        soup = BeautifulSoup(xhtml_content, 'xml')
        body = soup.find('body')

        if not body:
            return []

        text = body.get_text()

        # Find all katakana sequences (3+ characters)
        katakana_matches = self.KATAKANA_NAME_PATTERN.findall(text)

        # Count occurrences
        for match in katakana_matches:
            if match not in self._katakana_common_words:
                self.katakana_candidates[match] += 1

        extracted = []
        for katakana, count in self.katakana_candidates.items():
            key = (katakana, "")
            if key in self.seen_entries:
                continue

            confidence = self._is_katakana_name(katakana, text, count)
            if confidence >= 0.90:  # Higher threshold for standalone katakana
                context = self._extract_katakana_context(text, katakana)

                entry = RubyEntry(
                    kanji=katakana,
                    ruby="",
                    context=context,
                    source_file=source_file,
                    confidence=confidence,
                    name_type="katakana"
                )

                self.seen_entries.add(key)
                extracted.append(entry)

        return extracted

    def _is_katakana_name(self, katakana: str, full_text: str, occurrence_count: int) -> float:
        """
        Determine if a katakana sequence is a character name.
        More conservative to avoid common words.
        """
        if katakana in self._katakana_common_words:
            return 0.0

        if len(katakana) < 3 or len(katakana) > 8:
            return 0.0

        confidence = 0.0

        # 1. Frequency (names appear multiple times)
        if occurrence_count >= 15:
            confidence += 0.45
        elif occurrence_count >= 8:
            confidence += 0.30
        elif occurrence_count >= 5:
            confidence += 0.20
        else:
            return 0.0

        # 2. Name suffixes (REQUIRED for katakana names to pass)
        has_suffix = False
        for suffix in self._name_suffixes:
            if katakana + suffix in full_text:
                confidence += 0.50
                has_suffix = True
                break

        # Without suffix, need very high frequency
        if not has_suffix and occurrence_count < 15:
            return 0.0

        # 3. Typical name length
        if 3 <= len(katakana) <= 5:
            confidence += 0.10

        # 4. Subject particles
        for particle in ['は', 'が', 'の', 'と']:
            if katakana + particle in full_text:
                confidence += 0.10
                break

        return min(1.0, confidence)

    def _extract_katakana_context(self, text: str, katakana: str, window: int = 50) -> str:
        """Extract surrounding context for a katakana name."""
        pos = text.find(katakana)
        if pos >= 0:
            start = max(0, pos - window)
            end = min(len(text), pos + len(katakana) + window)
            return text[start:end].strip()
        return katakana

    def _parse_ruby_tag(self, ruby_tag: Tag, source_file: str) -> Optional[RubyEntry]:
        """
        Parse a single <ruby> tag.

        Handles 3 structural styles:
          NAROU:      <ruby><rb>名前</rb><rt>なまえ</rt></ruby>
                      → kanji="名前", ruby="なまえ", style="narou"

          INTERWEAVE: <ruby>名<rt>な</rt>前<rt>まえ</rt></ruby>
                      → kanji="名前", ruby="なまえ", style="interweave"
                      (raw copy-paste from web novels mixes kanji and rt inline)

          KIRA-KIRA:  <ruby><rb>愛梨</rb><rt>ラブリ</rt></ruby>
                      → kanji="愛梨", ruby="ラブリ", style="kirakira"
        """
        try:
            rb = ruby_tag.find('rb')
            rt_tags = ruby_tag.find_all('rt')

            if not rt_tags:
                return None

            # ── NAROU style: single <rb> + single <rt> ──
            if rb and len(rt_tags) == 1:
                kanji = rb.get_text(strip=True)
                ruby = rt_tags[0].get_text(strip=True)
                ruby_style = "narou"

            # ── INTERWEAVE style: kanji and <rt> nodes are siblings ──
            # Detected when there are multiple <rt> tags OR no <rb> tag at all.
            # Raw copy-paste from Narou/Kakuyomu produces:
            #   <ruby>名<rt>な</rt>前<rt>まえ</rt></ruby>
            # We reconstruct the full kanji and full reading by walking children in order.
            else:
                kanji_parts = []
                ruby_parts = []
                rt_count = 0

                for child in ruby_tag.children:
                    if child.name == 'rt':
                        ruby_parts.append(child.get_text(strip=True))
                        rt_count += 1
                    elif child.name in ('span', 'rb'):
                        text = child.get_text(strip=True)
                        if text:
                            kanji_parts.append(text)
                    elif isinstance(child, str):
                        text = child.strip()
                        if text:
                            kanji_parts.append(text)

                kanji = ''.join(kanji_parts)
                ruby = ''.join(ruby_parts)

                # Classify style: interweave when kanji chars and rt tags alternate
                # (multiple rt tags = interweave; single rt with no rb = also interweave)
                ruby_style = "interweave" if rt_count > 1 else "narou"

            if not kanji or not ruby:
                return None

            context = self._extract_context(ruby_tag, window=80)

            return RubyEntry(
                kanji=kanji,
                ruby=ruby,
                context=context,
                source_file=source_file,
                confidence=1.0,
                ruby_style=ruby_style,
            )

        except Exception as e:
            logger.warning(f"Failed to parse ruby tag: {e}")
            return None

    def _extract_context(self, ruby_tag: Tag, window: int = 80) -> str:
        """
        Extract surrounding text context with ruby text cleaned.

        The context needs to show the kanji without interleaved ruby readings
        so pattern matching works correctly.
        """
        parent = ruby_tag.find_parent(['p', 'div', 'section'])
        if parent:
            # Get text but strip ruby readings for cleaner context
            context_text = self._get_text_without_ruby_readings(parent)

            # Find the kanji we're looking for
            # Get kanji from our ruby tag
            kanji_parts = []
            for child in ruby_tag.children:
                if child.name != 'rt':
                    text = child.get_text(strip=True) if hasattr(child, 'get_text') else str(child).strip()
                    if text:
                        kanji_parts.append(text)
            kanji = ''.join(kanji_parts)

            pos = context_text.find(kanji)
            if pos >= 0:
                start = max(0, pos - window)
                end = min(len(context_text), pos + len(kanji) + window)
                return context_text[start:end].strip()

        return ruby_tag.get_text()

    def _get_text_without_ruby_readings(self, element: Tag) -> str:
        """
        Get text from element with ruby readings (rt tags) removed.
        This gives us cleaner context for pattern matching.
        """
        # Clone the element to avoid modifying original
        from copy import copy
        clone = copy(element)

        # Remove all rt tags
        for rt in clone.find_all('rt'):
            rt.decompose()

        return clone.get_text()

    def _is_character_name(self, kanji: str, ruby: str, context: str) -> float:
        """
        Determine if ruby entry is a character name.

        Enhanced to handle:
        - First-person introductions (俺、[NAME]は...)
        - Self-introductions ([NAME]といいます)
        - 4-kanji full names
        - Names without immediate suffixes
        """
        # Exclude common terms
        if kanji in self._common_terms:
            return 0.0

        # Exclude single character
        if len(kanji) == 1:
            return 0.92 if self._is_context_qualified_single_kanji_name(kanji, ruby, context) else 0.0

        confidence = 0.0

        # === VERY STRONG INDICATORS (return immediately) ===

        # 1. Katakana in base text (foreign names)
        if self.KATAKANA_PATTERN.search(kanji):
            return 0.98

        # 2. Name suffix directly after
        for suffix in self._name_suffixes:
            if kanji + suffix in context:
                return 0.98

        # 3. Self-introduction patterns
        for pattern in self._intro_patterns:
            if re.search(kanji + pattern, context):
                return 0.98

        # 4. First-person introduction pattern: 俺、[NAME] / 私、[NAME]
        for pronoun in self._first_person_pronouns:
            # Pattern: pronoun + comma/particle + name
            patterns = [
                f'{pronoun}、{kanji}',  # 俺、九条才斗
                f'{pronoun}は{kanji}',  # 俺は九条才斗
                f'{pronoun}の{kanji}',  # Not common but possible
            ]
            for p in patterns:
                if p in context:
                    return 0.95

        # 5. POV marker pattern: 【[NAME]──視点】
        if f'【{kanji}' in context or f'{kanji}──視点】' in context:
            return 0.98

        # === STRONG INDICATORS ===

        # 6. Inverted suffix patterns: 先輩は[NAME] / 後輩、[NAME]
        for suffix in ['先輩', '後輩', '先生', '様']:
            for sep in ['、', 'は', 'が', 'の', 'と', 'も']:
                if suffix + sep + kanji in context:
                    confidence = max(confidence, 0.90)

        # === MODERATE INDICATORS (accumulate) ===

        # 7. Subject particles
        has_particle = False
        for particle in ['は', 'が', 'を', 'の', 'と']:
            if kanji + particle in context:
                confidence += 0.30
                has_particle = True
                break

        # 8. Name length analysis
        kanji_count = sum(1 for c in kanji if '\u4E00' <= c <= '\u9FFF')
        has_typical_length = False

        if 2 <= kanji_count <= 3 and 2 <= len(kanji) <= 3:
            confidence += 0.30
            has_typical_length = True
        elif kanji_count == 4 and len(kanji) == 4:
            # 4-kanji full names - boost significantly
            confidence += 0.35
            has_typical_length = True

        # 9. Hiragana ruby (Japanese reading)
        has_hiragana_ruby = self.HIRAGANA_PATTERN.fullmatch(ruby)
        if has_hiragana_ruby:
            confidence += 0.15

        # 10. Combination boost for likely names
        if has_typical_length and has_hiragana_ruby:
            if has_particle:
                confidence += 0.20
            else:
                # Even without particle, 2-4 kanji + hiragana ruby is likely a name
                # Boost more for 2-char names (common given names like 凛奈, 伊緒)
                if kanji_count == 2:
                    confidence += 0.20  # Higher boost for 2-char (likely given names)
                else:
                    confidence += 0.10

        # 11. Appears at sentence/dialogue start
        if any(p in context for p in [f'。{kanji}', f'「{kanji}', f'　{kanji}']):
            confidence += 0.10

        # === PENALTIES ===

        # Long entries (5+ chars) - usually not names
        if len(kanji) >= 5:
            confidence -= 0.4

        # Verb patterns nearby
        verb_indicators = ['する', 'した', 'して', 'できる', 'いる', 'ある', 'なる']
        kanji_pos = context.find(kanji)
        if kanji_pos >= 0:
            after_context = context[kanji_pos:kanji_pos + len(kanji) + 15]
            for verb in verb_indicators:
                if verb in after_context:
                    confidence -= 0.25
                    break

        return max(0.0, min(1.0, confidence))

    def assemble_fragmented_names(self) -> List[RubyEntry]:
        """
        Attempt to assemble fragmented name annotations.

        Looks for patterns where surname and given name are annotated separately
        but appear together in context (e.g., 草鹿 + 伊緒 → 草鹿伊緒)
        """
        assembled = []

        # Keep legacy fragment capture behavior first.

        for _ruby_key, fragment in self.fragmented_candidates.items():
            if len(fragment.parts) >= 2:
                # Multiple occurrences of same reading - might be name part
                for kanji, ruby_text in fragment.parts:
                    key = (kanji, ruby_text)
                    if key not in self.seen_entries:
                        entry = RubyEntry(
                            kanji=kanji,
                            ruby=ruby_text,
                            context=fragment.contexts[0] if fragment.contexts else "",
                            source_file=list(fragment.source_files)[0] if fragment.source_files else "",
                            confidence=0.75,
                            name_type="fragmented",
                            notes="Possible name fragment"
                        )
                        self.seen_entries.add(key)
                        assembled.append(entry)

        # Conservative surname+given assembly:
        # merge likely surname (2-4 kanji) + given (1 kanji) within same source file.
        by_source: Dict[str, List[RubyEntry]] = defaultdict(list)
        for entry in self.entries:
            if not entry.source_file:
                continue
            if not self.HIRAGANA_PATTERN.fullmatch(entry.ruby or ""):
                continue
            if entry.name_type in {"kirakira", "katakana"}:
                continue
            by_source[entry.source_file].append(entry)

        for source_file, source_entries in by_source.items():
            surname_candidates = [
                e for e in source_entries
                if 2 <= len(e.kanji) <= 4 and e.confidence >= 0.9
            ]
            given_candidates = [
                e for e in source_entries
                if len(e.kanji) == 1 and self._is_context_qualified_single_kanji_name(e.kanji, e.ruby, e.context)
            ]

            for surname in surname_candidates:
                for given in given_candidates:
                    if surname.kanji == given.kanji:
                        continue
                    merged_kanji = f"{surname.kanji}{given.kanji}"
                    merged_ruby = f"{surname.ruby}{given.ruby}"
                    key = (merged_kanji, merged_ruby)
                    if key in self.seen_entries:
                        continue

                    # Require balanced local evidence from both surname and given cues.
                    surname_signal = any(
                        marker in (surname.context or "") or marker in (given.context or "")
                        for marker in (
                            f"{surname.kanji}くん",
                            f"{surname.kanji}さん",
                            f"{surname.kanji}様",
                            f"{surname.kanji}先輩",
                        )
                    )
                    given_signal = any(
                        marker in (given.context or "") or marker in (surname.context or "")
                        for marker in (
                            f"{given.kanji}ちゃん",
                            f"{given.kanji}くん",
                            f"{given.kanji}さん",
                        )
                    )
                    has_explicit_full = (
                        merged_kanji in (surname.context or "")
                        or merged_kanji in (given.context or "")
                    )
                    if not has_explicit_full and not (surname_signal and given_signal):
                        continue

                    entry = RubyEntry(
                        kanji=merged_kanji,
                        ruby=merged_ruby,
                        context=f"{surname.context} / {given.context}",
                        source_file=source_file,
                        confidence=0.86,
                        name_type="fragmented",
                        notes="Assembled surname+given from separate ruby hints",
                    )
                    self.seen_entries.add(key)
                    assembled.append(entry)

        return assembled

    def get_kirakira_names(self) -> List[RubyEntry]:
        """Return detected kira-kira names for special handling."""
        return self.kirakira_names

    def to_dict(self) -> Dict[str, List[Dict]]:
        """Export character names as dict for manifest."""
        return {
            "names": [e.to_dict() for e in self.entries],
            "kirakira_names": [e.to_dict() for e in self.kirakira_names]
        }


def extract_ruby_from_directory(xhtml_dir: Path) -> Dict[str, List[Dict]]:
    """
    Extract ruby entries from all XHTML files in directory.

    Args:
        xhtml_dir: Directory containing XHTML chapter files (searches recursively)

    Returns:
        Dict with 'names' list (deduplicated)
    """
    extractor = RubyExtractor()

    xhtml_files = sorted(xhtml_dir.rglob("*.xhtml"))

    if not xhtml_files:
        logger.warning(f"No XHTML files found in {xhtml_dir}")
        return {"names": [], "kirakira_names": []}

    logger.info(f"Found {len(xhtml_files)} XHTML files")

    total_before = 0

    for xhtml_file in xhtml_files:
        logger.debug(f"Extracting ruby from {xhtml_file.name}")

        try:
            content = xhtml_file.read_text(encoding='utf-8')
            entries = extractor.extract_from_xhtml(content, xhtml_file.name)

            total_before += len(entries)
            extractor.entries.extend(entries)

        except Exception as e:
            logger.error(f"Failed to process {xhtml_file.name}: {e}")

    # Try to assemble fragmented names
    assembled = extractor.assemble_fragmented_names()
    extractor.entries.extend(assembled)

    final_count = len(extractor.entries)
    kirakira_count = len(extractor.kirakira_names)

    logger.info(f"Extracted {final_count} character names ({kirakira_count} kira-kira names detected)")

    return extractor.to_dict()

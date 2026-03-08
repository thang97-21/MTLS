"""
Deterministic Phase 2 copyediting post-pass.

This pass is intentionally mechanical. It cleans typography, whitespace,
paragraph spacing, and markdown formatting artifacts without touching
voice/register decisions. Grammar validation may still run for reporting,
but automatic grammar rewrites are disabled to avoid content mutations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple

from .format_normalizer import FormatNormalizer
from .grammar_validator import GrammarValidator


@dataclass
class CopyeditPostPassReport:
    target_language: str
    files_processed: int = 0
    files_modified: int = 0
    typography_fixes: int = 0
    whitespace_fixes: int = 0
    paragraph_spacing_fixes: int = 0
    header_deduplications: int = 0
    grammar_auto_fixed: int = 0

    def to_dict(self) -> Dict[str, int | str]:
        return asdict(self)


class CopyeditPostPass:
    """Run deterministic copyediting cleanup on translated chapter output."""

    _ELLIPSIS_VARIANTS = (
        "……",
        "．．．",
        "。。。",
        "...",
        ". . .",
        ". . . .",
    )
    _QUOTE_MAP = {
        "「": '"',
        "」": '"',
        "『": '"',
        "』": '"',
        "《": '"',
        "》": '"',
        "〈": '"',
        "〉": '"',
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "’": "'",
        "‘": "'",
        "‚": "'",
        "‛": "'",
    }
    _FULLWIDTH_MAP = {
        "　": " ",
        "\u00a0": " ",
        "\u2007": " ",
        "\u202f": " ",
        "\ufeff": "",
        "\u200b": "",
        "\u200c": "",
        "\u200d": "",
        "\u2060": "",
        "！": "!",
        "？": "?",
        "，": ",",
        "．": ".",
        "：": ":",
        "；": ";",
        "（": "(",
        "）": ")",
        "［": "[",
        "］": "]",
    }

    def __init__(self, work_dir: Path, target_language: str = "en"):
        self.work_dir = work_dir
        self.target_language = (target_language or "en").lower()

    def run(self) -> CopyeditPostPassReport:
        report = CopyeditPostPassReport(target_language=self.target_language)
        lang_dir = self.work_dir / self.target_language.upper()
        if not lang_dir.exists():
            return report

        chapter_files = sorted(lang_dir.glob("CHAPTER_*.md"))
        report.files_processed = len(chapter_files)

        if not chapter_files:
            return report

        for file_path in chapter_files:
            changed, stats = self._normalize_file(file_path)
            if changed:
                report.files_modified += 1
            report.typography_fixes += stats["typography_fixes"]
            report.whitespace_fixes += stats["whitespace_fixes"]
            report.paragraph_spacing_fixes += stats["paragraph_spacing_fixes"]

        header_normalizer = FormatNormalizer(aggressive=False)
        report.header_deduplications = header_normalizer.deduplicate_headers_in_directory(
            lang_dir, pattern="CHAPTER_*.md"
        )
        if report.header_deduplications > 0:
            report.files_modified += 0

        if self.target_language == "en":
            grammar_validator = GrammarValidator(auto_fix=False)
            grammar_results = grammar_validator.validate_volume(self.work_dir)
            report.grammar_auto_fixed = sum(
                item.auto_fixed for item in grammar_results.values()
            )

        return report

    def _normalize_file(self, file_path: Path) -> Tuple[bool, Dict[str, int]]:
        original = file_path.read_text(encoding="utf-8")
        updated = original

        stats = {
            "typography_fixes": 0,
            "whitespace_fixes": 0,
            "paragraph_spacing_fixes": 0,
        }

        for source, target in self._QUOTE_MAP.items():
            count = updated.count(source)
            if count:
                updated = updated.replace(source, target)
                stats["typography_fixes"] += count

        for source, target in self._FULLWIDTH_MAP.items():
            count = updated.count(source)
            if count:
                updated = updated.replace(source, target)
                stats["whitespace_fixes"] += count

        updated, quote_style_fixes = self._normalize_dialogue_quote_style(updated)
        stats["typography_fixes"] += quote_style_fixes

        for variant in self._ELLIPSIS_VARIANTS:
            count = updated.count(variant)
            if count:
                updated = updated.replace(variant, "…")
                stats["typography_fixes"] += count

        dot_runs = re.findall(r"(?<!\.)\.{3,}(?!\.)", updated)
        if dot_runs:
            updated = re.sub(r"(?<!\.)\.{3,}(?!\.)", "…", updated)
            stats["typography_fixes"] += len(dot_runs)

        multi_ellipses = updated.count("……")
        if multi_ellipses:
            updated = updated.replace("……", "…")
            stats["typography_fixes"] += multi_ellipses

        spaced_ellipsis = re.findall(r"\s+…", updated)
        if spaced_ellipsis:
            updated = re.sub(r"[ \t]+…", "…", updated)
            stats["whitespace_fixes"] += len(spaced_ellipsis)

        punctuation_space = re.findall(r"[ \t]+([,.;:!?])", updated)
        if punctuation_space:
            updated = re.sub(r"[ \t]+([,.;:!?])", r"\1", updated)
            stats["whitespace_fixes"] += len(punctuation_space)

        trailing_ws = re.findall(r"[ \t]+$", updated, flags=re.MULTILINE)
        if trailing_ws:
            updated = re.sub(r"[ \t]+$", "", updated, flags=re.MULTILINE)
            stats["whitespace_fixes"] += len(trailing_ws)

        leading_blank = 1 if updated != updated.lstrip("\n") else 0
        if leading_blank:
            updated = updated.lstrip("\n")
            stats["paragraph_spacing_fixes"] += leading_blank

        blank_runs = re.findall(r"\n{3,}", updated)
        if blank_runs:
            updated = re.sub(r"\n{3,}", "\n\n", updated)
            stats["paragraph_spacing_fixes"] += len(blank_runs)

        line_space_runs = re.findall(r"(?m)^[ \t]+$", updated)
        if line_space_runs:
            updated = re.sub(r"(?m)^[ \t]+$", "", updated)
            stats["whitespace_fixes"] += len(line_space_runs)

        updated = updated.rstrip() + "\n"

        if updated == original:
            return False, stats

        file_path.write_text(updated, encoding="utf-8")
        return True, stats

    def _normalize_dialogue_quote_style(self, content: str) -> Tuple[str, int]:
        """
        Normalize straight/curly dialogue quotes with deterministic per-line rules.

        Rules:
        1) Straight quote pairs are converted to curly pairs, including multi-speaker
           lines like: "A" "B" -> “A” “B”.
        2) Triple-quote style lines (`\"\"\"...\"\"\"`) remain straight.
        """
        lines = content.splitlines(keepends=True)
        normalized_lines: List[str] = []
        fixes = 0
        in_fenced_code = False

        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith("```"):
                in_fenced_code = not in_fenced_code
                normalized_lines.append(line)
                continue
            if in_fenced_code:
                normalized_lines.append(line)
                continue

            # Preserve explicit triple-quote style as straight quotes.
            if '"""' in line:
                normalized_lines.append(line)
                continue

            quote_positions: List[int] = []
            for idx, ch in enumerate(line):
                if ch != '"':
                    continue
                if idx > 0 and line[idx - 1] == "\\":
                    continue
                quote_positions.append(idx)

            if len(quote_positions) >= 2 and len(quote_positions) % 2 == 0:
                chars = list(line)
                for pair_idx, quote_idx in enumerate(quote_positions):
                    chars[quote_idx] = "“" if pair_idx % 2 == 0 else "”"
                    fixes += 1
                line = "".join(chars)

            normalized_lines.append(line)

        return "".join(normalized_lines), fixes

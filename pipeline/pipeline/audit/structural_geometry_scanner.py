"""
StructuralGeometryScanner (Phase 5 QC)
=======================================

Verifies cross-chapter structural rules encoded in rich_metadata_cache_patch_en.json.
Catches POV mirrors, callback phrases, and symbolic bookmarks that per-chapter
evaluation cannot detect.

Execution: After Phase 4 EPUB build, before marking volume as QC-complete.

Rule types:
- pov_mirror:       Source text must appear verbatim in target chapter
- symbolic_callback: Keyword must appear in target chapter context
- regex:            Regex pattern must match in target chapter

Severity:
- MUST_FIX:  EXIT_CODE 1 if any violation found
- SHOULD_FIX: Advisory warning, does not fail the run
"""

import argparse
import datetime
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s - %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("StructuralGeometryScanner")


class StructuralGeometryScanner:
    """
    Verifies cross-chapter structural rules from rich_metadata_cache_patch_en.json.
    """

    def __init__(self, volume_dir: Path):
        self.volume_dir = volume_dir
        self.en_dir = volume_dir / "EN"
        self.qc_dir = volume_dir / "QC"
        self.patch_path = volume_dir / "rich_metadata_cache_patch_en.json"

    def load_rules(self) -> List[Dict[str, Any]]:
        """Load cross_chapter_rules from rich_metadata_cache_patch_en.json."""
        if not self.patch_path.exists():
            logger.warning(f"rich_metadata_cache_patch_en.json not found: {self.patch_path}")
            return []

        with open(self.patch_path, encoding="utf-8") as f:
            patch = json.load(f)

        rules = patch.get("cross_chapter_rules", [])
        logger.info(f"Loaded {len(rules)} cross-chapter rules from patch")
        return rules

    def load_chapters(self) -> Dict[str, str]:
        """
        Load all EN/CHAPTER_*.md files.

        Returns: {chapter_id: text}
        """
        if not self.en_dir.exists():
            logger.error(f"EN directory not found: {self.en_dir}")
            return {}

        chapters = {}
        for md_file in sorted(self.en_dir.glob("CHAPTER_*.md")):
            # Derive chapter_id from filename: CHAPTER_03_EN.md → chapter_03
            stem = md_file.stem.upper()
            # Strip _EN suffix if present
            if stem.endswith("_EN"):
                stem = stem[:-3]
            chapter_id = stem.lower()  # e.g., "chapter_03"

            with open(md_file, encoding="utf-8") as f:
                chapters[chapter_id] = f.read()

        logger.info(f"Loaded {len(chapters)} EN chapters")
        return chapters

    def check_rule(
        self,
        rule: Dict[str, Any],
        chapters: Dict[str, str],
    ) -> Dict[str, Any]:
        """
        Check a single cross-chapter rule.

        Returns: {rule_id, status: PASS|FAIL|WARN, evidence, detail}
        """
        rule_id = rule.get("rule_id", "unknown")
        severity = rule.get("severity", "SHOULD_FIX")
        target_chapter = rule.get("target_chapter", "")
        match_type = rule.get("match_type", "keyword")
        source_text = rule.get("source_text_en", "")

        target_text = chapters.get(target_chapter, "")
        if not target_text:
            return {
                "rule_id": rule_id,
                "status": "WARN",
                "severity": severity,
                "detail": f"Target chapter '{target_chapter}' not found in EN output",
                "evidence": None,
            }

        found = False
        evidence = None

        if match_type == "substring":
            found = source_text.lower() in target_text.lower()
            if found:
                # Find the matching line for evidence
                for i, line in enumerate(target_text.splitlines(), 1):
                    if source_text.lower() in line.lower():
                        evidence = f"Line {i}: {line.strip()[:120]}"
                        break

        elif match_type == "keyword":
            keywords = source_text.lower().split()
            matched_keywords = [kw for kw in keywords if kw in target_text.lower()]
            found = len(matched_keywords) >= max(1, len(keywords) // 2)
            if found:
                evidence = f"Keywords found: {matched_keywords}"

        elif match_type == "regex":
            m = re.search(source_text, target_text, re.IGNORECASE)
            found = bool(m)
            if found and m:
                evidence = f"Match: {m.group(0)[:120]}"

        if found:
            status = "PASS"
        elif severity == "MUST_FIX":
            status = "FAIL"
        else:
            status = "WARN"

        return {
            "rule_id": rule_id,
            "type": rule.get("type", "unknown"),
            "severity": severity,
            "status": status,
            "source_chapter": rule.get("source_chapter", ""),
            "target_chapter": target_chapter,
            "description": rule.get("description", ""),
            "expected": source_text[:200],
            "evidence": evidence,
        }

    def generate_report(
        self,
        results: List[Dict[str, Any]],
        volume_id: str,
        rules: List[Dict[str, Any]],
    ) -> str:
        """Generate QC/STRUCTURAL_GEOMETRY_REPORT_{volume_id}.md content."""
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        must_fix_fails = [r for r in results if r["status"] == "FAIL" and r["severity"] == "MUST_FIX"]
        should_fix_warns = [r for r in results if r["status"] == "WARN"]
        passes = [r for r in results if r["status"] == "PASS"]

        lines = [
            f"# Structural Geometry QC Report — {volume_id}",
            f"## Run date: {now}",
            "",
            "## Summary",
            "",
            "| Rule ID | Type | Severity | Status |",
            "|---|---|---|---|",
        ]

        for r in results:
            icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}.get(r["status"], "?")
            lines.append(
                f"| {r['rule_id']} | {r.get('type', '—')} | {r['severity']} | {icon} {r['status']} |"
            )

        lines += ["", f"**Total:** {len(results)} rules — {len(passes)} PASS, {len(must_fix_fails)} FAIL, {len(should_fix_warns)} WARN"]

        if must_fix_fails:
            lines += ["", "---", "", "## MUST_FIX Violations", ""]
            for r in must_fix_fails:
                lines += [
                    f"### {r['rule_id']}",
                    f"- **Type:** {r.get('type', '—')}",
                    f"- **Source chapter:** {r['source_chapter']}",
                    f"- **Target chapter:** {r['target_chapter']}",
                    f"- **Description:** {r['description']}",
                    f"- **Expected:** `{r['expected']}`",
                    f"- **Result:** Not found in target chapter",
                    "",
                ]
        else:
            lines += ["", "## MUST_FIX Violations", "", "*(none — all mandatory rules pass)*"]

        if should_fix_warns:
            lines += ["", "---", "", "## SHOULD_FIX Warnings", ""]
            for r in should_fix_warns:
                lines += [
                    f"### {r['rule_id']}",
                    f"- **Type:** {r.get('type', '—')}",
                    f"- **Target chapter:** {r['target_chapter']}",
                    f"- **Description:** {r['description']}",
                    f"- **Expected:** `{r['expected']}`",
                    f"- **Result:** {r.get('detail', 'Keyword/pattern not found — verify manually')}",
                    "",
                ]

        # Rule registry coverage
        auto_verifiable = sum(
            1 for r in rules if r.get("match_type") in ("substring", "keyword", "regex")
        )
        manual_review = len(rules) - auto_verifiable
        lines += [
            "",
            "---",
            "",
            "## Rule Registry Coverage",
            f"- Total cross-chapter rules: {len(rules)}",
            f"- Automatically verifiable (substring/keyword/regex): {auto_verifiable}",
            f"- Requires manual review (semantic): {manual_review}",
        ]

        return "\n".join(lines)

    def run(self) -> int:
        """
        Run the scanner.

        Returns: 0 if all MUST_FIX rules pass, 1 otherwise.
        """
        volume_id = self.volume_dir.name
        logger.info("=" * 60)
        logger.info(f"StructuralGeometryScanner — Volume: {volume_id}")
        logger.info("=" * 60)

        rules = self.load_rules()
        if not rules:
            logger.info("No cross_chapter_rules found — nothing to verify")
            logger.info("To populate rules, run Phase 1.55 with cross_chapter_rule_extractor enabled")
            return 0

        chapters = self.load_chapters()
        if not chapters:
            logger.error("No EN chapters found — cannot run structural geometry check")
            return 1

        results = []
        for rule in rules:
            result = self.check_rule(rule, chapters)
            icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}.get(result["status"], "?")
            logger.info(
                f"  {icon} [{result['severity']}] {result['rule_id']}: {result['status']}"
            )
            results.append(result)

        # Write report
        self.qc_dir.mkdir(exist_ok=True)
        report_path = self.qc_dir / f"STRUCTURAL_GEOMETRY_REPORT_{volume_id[:8]}.md"
        report_content = self.generate_report(results, volume_id, rules)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)
        logger.info(f"Report written: {report_path}")

        # Determine exit code
        must_fix_fails = [r for r in results if r["status"] == "FAIL"]
        if must_fix_fails:
            logger.error(f"❌ {len(must_fix_fails)} MUST_FIX violation(s) — QC FAILED")
            for r in must_fix_fails:
                logger.error(f"   → {r['rule_id']}: {r['description']}")
            return 1

        logger.info(f"✅ All {len(results)} structural geometry rules pass")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="StructuralGeometryScanner — Phase 5 QC (cross-chapter rule verification)"
    )
    parser.add_argument("--volume", required=True, help="Volume ID")
    parser.add_argument(
        "--work-dir",
        default=None,
        help="Working directory (default: ./WORK)",
    )
    args = parser.parse_args()

    if args.work_dir:
        work_dir = Path(args.work_dir)
    else:
        pipeline_root = Path(__file__).parent.parent.parent
        work_dir = pipeline_root / "WORK"

    volume_dir = work_dir / args.volume
    if not volume_dir.exists():
        logger.error(f"Volume directory not found: {volume_dir}")
        sys.exit(1)

    scanner = StructuralGeometryScanner(volume_dir)
    exit_code = scanner.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

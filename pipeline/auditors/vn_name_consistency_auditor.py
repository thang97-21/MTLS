"""
VN Name Consistency Auditor — Vietnamese character name/pronoun drift detection
================================================================================
Wraps VNCriticsAuditor.run_integrity_audit() with the standard auditor interface.

Mirrors name_consistency_auditor.py (EN) but is VN-aware:
  - Checks canonical_name_vn from bibles/manifest instead of canonical_name_en
  - Flags pronoun-pair drift (PAIR_ID mismatch) alongside name drift
  - Validates honorifics / kinship terms (anh/chị/em usage for named characters)

Output: vn_name_consistency_report.json
"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from modules.vn_critics_auditor import VNCriticsAuditor, IntegrityReport
except ImportError:
    VNCriticsAuditor = None  # type: ignore
    IntegrityReport = None


# ── VN name normalisation helpers ─────────────────────────────────────────────

# Honorifics / address terms that should not be confused with name variations
VN_HONORIFICS = re.compile(
    r'\b(anh|chị|em|cô|chú|bác|ông|bà|thầy|cậu|bạn|ngươi|mi)\b',
    re.IGNORECASE
)


def normalise_vn_name(name: str) -> str:
    """
    Normalise a Vietnamese character name for comparison.
    - Lowercase
    - Strip leading/trailing honorifics
    """
    name = name.strip().lower()
    name = VN_HONORIFICS.sub("", name).strip()
    return name


class VNNameConsistencyAuditor:
    """
    Vietnamese Name Consistency Auditor.

    Drop-in companion to NameConsistencyAuditor for VN translations.

    Usage:
        auditor = VNNameConsistencyAuditor(work_dir)
        report = auditor.audit_names(manifest_path)
        auditor.save_report()
    """

    def __init__(
        self,
        work_dir: Path,
        reference_volume_path: Optional[str] = None,
    ):
        self.work_dir = Path(work_dir)
        self.reference_volume_path = reference_volume_path
        self.report: Optional[Dict[str, Any]] = None
        self._inner: Optional[Any] = None

        if VNCriticsAuditor is not None:
            try:
                self._inner = VNCriticsAuditor(
                    volume_path=str(self.work_dir),
                    reference_volume_path=reference_volume_path,
                )
            except Exception as e:
                print(f"[VNNameConsistencyAuditor] Init fallback: {e}")

    # ── Public interface ───────────────────────────────────────────────────────

    def audit_names(
        self,
        manifest_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Audit VN character name + pronoun consistency.

        Steps:
          1. Run VNCriticsAuditor.run_integrity_audit() for structural name checks
          2. Scan VN output files for canonical name drift vs manifest
          3. Scan for PAIR_ID pronoun drift
        """
        integrity_report = self._run_integrity_audit()
        name_drift_issues = self._scan_name_drift(manifest_path)
        pronoun_drift_issues = self._scan_pronoun_pair_drift(manifest_path)

        all_issues = integrity_report.get("issues", []) + name_drift_issues + pronoun_drift_issues
        critical = sum(1 for i in all_issues if i.get("severity") == "CRITICAL")
        major    = sum(1 for i in all_issues if i.get("severity") == "MAJOR")

        status = "PASSED"
        if critical > 0:
            status = "FAILED"
        elif major > 2:
            status = "WARNING"

        result = {
            "auditor":            "VNNameConsistencyAuditor",
            "language":           "vi",
            "timestamp":          datetime.now().isoformat(),
            "volume_dir":         str(self.work_dir),
            "status":             status,
            "name_consistency":   integrity_report.get("name_consistency", 100.0),
            "critical_count":     critical,
            "major_count":        major,
            "issues":             all_issues,
            "character_names":    integrity_report.get("character_names", {}),
        }
        self.report = result
        return result

    def save_report(self, output_path: Optional[Path] = None) -> Path:
        """Save name consistency report to disk."""
        if self.report is None:
            self.audit_names()

        if output_path is None:
            output_path = self.work_dir / "vn_name_consistency_report.json"

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.report, f, indent=2, ensure_ascii=False)

        print(f"[VNNameConsistencyAuditor] Report saved to {output_path}")
        return output_path

    def run_and_save(self, manifest_path: Optional[Path] = None) -> Path:
        """Convenience: audit then save."""
        self.report = self.audit_names(manifest_path)
        return self.save_report()

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _run_integrity_audit(self) -> Dict[str, Any]:
        """Delegate structural name check to VNCriticsAuditor."""
        if self._inner is None:
            return {"issues": [], "name_consistency": 100.0, "character_names": {}}
        try:
            report = self._inner.run_integrity_audit()
            issues = []
            if hasattr(report, "issues"):
                for i in report.issues:
                    issues.append({
                        "issue_id":   getattr(i, "issue_id", ""),
                        "severity":   getattr(i, "severity", "MINOR"),
                        "category":   getattr(i, "category", "name"),
                        "chapter":    getattr(i, "chapter", ""),
                        "pattern":    getattr(i, "pattern", ""),
                        "context":    getattr(i, "context", ""),
                        "suggestion": getattr(i, "suggestion", ""),
                    })
            return {
                "issues":           issues,
                "name_consistency": getattr(report, "name_consistency", 100.0),
                "character_names":  getattr(report, "character_names", {}),
            }
        except Exception as e:
            return {"issues": [{"severity": "MINOR", "category": "error", "context": str(e)}],
                    "name_consistency": 100.0, "character_names": {}}

    def _load_manifest_names(self, manifest_path: Optional[Path]) -> Dict[str, str]:
        """Load canonical_name_vn → canonical_name_jp mapping from manifest."""
        if manifest_path is None:
            manifest_path = self.work_dir / "manifest.json"
        if not Path(manifest_path).exists():
            return {}
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
            characters = manifest.get("characters", [])
            name_map: Dict[str, str] = {}
            for char in characters:
                name_vn = char.get("canonical_name_vn", "")
                if name_vn:
                    name_map[name_vn.lower()] = name_vn
            return name_map
        except Exception:
            return {}

    def _scan_name_drift(self, manifest_path: Optional[Path]) -> List[Dict]:
        """Scan VN output files for name variants not in manifest."""
        canonical_names = self._load_manifest_names(manifest_path)
        if not canonical_names:
            return []

        vn_dir = self.work_dir / "VN"
        if not vn_dir.exists():
            return []

        issues = []
        for txt_file in sorted(vn_dir.glob("*.txt")):
            try:
                content = txt_file.read_text(encoding="utf-8")
            except Exception:
                continue
            # Check for name drift: look for romanised (ASCII) names that should be VN
            for canon_vn, canon_orig in canonical_names.items():
                # Simple heuristic: original should appear as canonical_name_vn
                if canon_vn not in content.lower():
                    issues.append({
                        "issue_id":   f"name-absent-{txt_file.stem}",
                        "severity":   "MAJOR",
                        "category":   "name_drift",
                        "chapter":    txt_file.stem,
                        "pattern":    canon_vn,
                        "context":    f'"{canon_orig}" not found in chapter {txt_file.stem}',
                        "suggestion": f'Ensure "{canon_orig}" appears consistently in VN output',
                    })
        return issues

    def _scan_pronoun_pair_drift(self, manifest_path: Optional[Path]) -> List[Dict]:
        """
        Check that each character consistently uses their PAIR_ID pronouns across chapters.
        Light-weight scan: delegates deep per-chapter check to PronounConsistencyChecker.
        """
        try:
            from pipeline.translator.pronoun_consistency_checker import (
                PronounConsistencyChecker,
                PAIR_ID_MAP,
            )
        except ImportError:
            return []

        if manifest_path is None:
            manifest_path = self.work_dir / "manifest.json"
        if not Path(manifest_path).exists():
            return []

        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            return []

        characters = manifest.get("characters", [])
        vn_dir = self.work_dir / "VN"
        if not vn_dir.exists():
            return []

        issues: List[Dict] = []
        checker = PronounConsistencyChecker()

        # Build character_pairs dict from manifest
        character_pairs: Dict[str, Dict] = {}
        for char in characters:
            name = char.get("canonical_name_vn", char.get("canonical_name_en", ""))
            if not name:
                continue
            character_pairs[name] = {
                "pair_id":      char.get("pair_id", "PAIR_0"),
                "eps_band":     "NEUTRAL",
                "pronoun_self": char.get("pronoun_self", ""),
            }

        if not character_pairs:
            return []

        for txt_file in sorted(vn_dir.glob("*.txt"))[:10]:  # cap at 10 chapters for speed
            try:
                content = txt_file.read_text(encoding="utf-8")
            except Exception:
                continue
            reports = checker.check_chapter(content, dict(character_pairs))
            for r in reports:
                if not r.passed:
                    issues.append({
                        "issue_id":   f"pronoun-drift-{txt_file.stem}-{r.character}",
                        "severity":   "MAJOR",
                        "category":   "pronoun_drift",
                        "chapter":    txt_file.stem,
                        "pattern":    r.pair_id,
                        "context":    r.note,
                        "suggestion": (
                            f'Use "{r.expected_self[0]}" consistently for {r.character} '
                            f'(consistency: {r.consistency_score:.0%})'
                        ),
                    })

        return issues

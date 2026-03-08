"""
VN Prose Auditor — Wrapper Subagent for Vietnamese Prose Quality
================================================================
Sits in auditors/ alongside prose_auditor.py (EN).

Wraps VNCriticsAuditor.run_prose_audit() and exposes the same interface as
ProseAuditor so callers can dispatch on target_language without branching.

Output: vn_prose_audit_report.json  (same layout as prose_audit_report.json)
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from modules.vn_critics_auditor import VNCriticsAuditor, ProseReport, AuditIssue
except ImportError:
    VNCriticsAuditor = None  # type: ignore
    ProseReport = None
    AuditIssue = None


class VNProseAuditor:
    """
    Vietnamese Prose Quality Auditor.

    Drop-in replacement for ProseAuditor when target_language == 'vn'/'vi'.
    Uses VNCriticsAuditor.run_prose_audit() under the hood.

    Usage:
        auditor = VNProseAuditor(work_dir)
        report = auditor.audit_prose()
        auditor.save_report()
    """

    def __init__(
        self,
        work_dir: Path,
        config_dir: Optional[Path] = None,
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
                print(f"[VNProseAuditor] Init fallback: {e}")

    # ── Public interface ───────────────────────────────────────────────────────

    def audit_prose(self) -> Dict[str, Any]:
        """
        Run Vietnamese prose quality audit.

        Returns a standardised report dict with:
          - status: "PASSED" | "WARNING" | "FAILED"
          - prose_score: 0.0–100.0
          - ai_ism_density: float
          - issues: list of issue dicts (severity, category, context, suggestion)
        """
        if self._inner is None:
            return self._empty_report("VNCriticsAuditor not available")

        try:
            prose_report = self._inner.run_prose_audit()
        except Exception as e:
            return self._empty_report(f"prose audit error: {e}")

        return self._serialize_prose_report(prose_report)

    def save_report(self, output_path: Optional[Path] = None) -> Path:
        """Save prose audit report to disk."""
        if self.report is None:
            self.audit_prose()

        if output_path is None:
            output_path = self.work_dir / "vn_prose_audit_report.json"

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.report, f, indent=2, ensure_ascii=False)

        print(f"[VNProseAuditor] Report saved to {output_path}")
        return output_path

    def run_and_save(self) -> Path:
        """Convenience: audit then save. Returns report path."""
        self.report = self.audit_prose()
        return self.save_report()

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _serialize_prose_report(self, report: Any) -> Dict[str, Any]:
        """Convert VNCriticsAuditor ProseReport to standard dict."""
        if report is None:
            return self._empty_report("null report")

        issues = []
        if hasattr(report, "issues"):
            for issue in report.issues:
                issues.append({
                    "issue_id":   getattr(issue, "issue_id", ""),
                    "chapter":    getattr(issue, "chapter", ""),
                    "line":       getattr(issue, "line", 0),
                    "severity":   getattr(issue, "severity", "MINOR"),
                    "category":   getattr(issue, "category", "prose"),
                    "pattern":    getattr(issue, "pattern", ""),
                    "context":    getattr(issue, "context", ""),
                    "suggestion": getattr(issue, "suggestion", ""),
                })

        ai_ism_density = getattr(report, "ai_ism_density", 0.0)
        prose_score    = getattr(report, "prose_score", 100.0)
        status         = getattr(report, "status", "NOT_RUN")

        # Normalise status
        if ai_ism_density > 0.05:
            status = "FAILED"
        elif ai_ism_density > 0.02:
            status = "WARNING"
        else:
            status = "PASSED"

        result = {
            "auditor":        "VNProseAuditor",
            "language":       "vi",
            "timestamp":      datetime.now().isoformat(),
            "volume_dir":     str(self.work_dir),
            "status":         status,
            "prose_score":    round(prose_score, 2),
            "ai_ism_count":   getattr(report, "ai_ism_count", 0),
            "ai_ism_density": round(ai_ism_density, 4),
            "total_words":    getattr(report, "total_words", 0),
            "categories":     getattr(report, "categories", {}),
            "issues":         issues,
        }
        self.report = result
        return result

    @staticmethod
    def _empty_report(reason: str) -> Dict[str, Any]:
        return {
            "auditor":        "VNProseAuditor",
            "language":       "vi",
            "timestamp":      datetime.now().isoformat(),
            "status":         "NOT_RUN",
            "reason":         reason,
            "prose_score":    0.0,
            "ai_ism_count":   0,
            "ai_ism_density": 0.0,
            "total_words":    0,
            "issues":         [],
        }

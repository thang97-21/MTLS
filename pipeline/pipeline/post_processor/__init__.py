"""
Post-Processor Module - Format Normalization and CJK Artifact Cleanup

Automatically cleans up Japanese formatting artifacts and stray CJK characters
that may leak through translation into any target language output.
"""

from .format_normalizer import FormatNormalizer
from .copyedit_post_pass import CopyeditPostPass, CopyeditPostPassReport
from .vn_cjk_cleaner import VietnameseCJKCleaner, format_cleaner_report
from .truncation_validator import TruncationValidator, TruncationIssue, TruncationReport
from .pov_validator import POVValidator, POVIssue, POVReport
from .tense_validator import TenseConsistencyValidator, TenseViolation, TenseReport
from .reference_validator import ReferenceValidator, DetectedEntity, ValidationReport
from .chapter_summarizer import ChapterSummarizationAgent, ChapterSummaryResult

# Keep package import resilient when legacy cjk_cleaner.py is absent.
try:
    from .cjk_cleaner import CJKArtifactCleaner
except ModuleNotFoundError:  # pragma: no cover - defensive fallback
    CJKArtifactCleaner = None

__all__ = [
    'FormatNormalizer',
    'CopyeditPostPass',
    'CopyeditPostPassReport',
    'CJKArtifactCleaner',
    'VietnameseCJKCleaner',
    'format_cleaner_report',
    'TruncationValidator',
    'TruncationIssue',
    'TruncationReport',
    'POVValidator',
    'POVIssue',
    'POVReport',
    'TenseConsistencyValidator',
    'TenseViolation',
    'TenseReport',
    'ReferenceValidator',
    'DetectedEntity',
    'ValidationReport',
    'ChapterSummarizationAgent',
    'ChapterSummaryResult',
    'VolumeBibleUpdateAgent',
    'VolumeBibleUpdateResult',
]


def __getattr__(name):
    """Lazy-export heavy/standalone modules to avoid runpy -m re-import warnings."""
    if name in {"VolumeBibleUpdateAgent", "VolumeBibleUpdateResult"}:
        from .volume_bible_update_agent import VolumeBibleUpdateAgent, VolumeBibleUpdateResult
        if name == "VolumeBibleUpdateAgent":
            return VolumeBibleUpdateAgent
        return VolumeBibleUpdateResult
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

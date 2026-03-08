"""Chapter kind helpers shared across pipeline phases."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional


_AFTERWORD_PATTERNS = (
    re.compile(r"^afterword$", re.IGNORECASE),
    re.compile(r"^author(?:'s)?\s+note$", re.IGNORECASE),
    re.compile(r"^postscript$", re.IGNORECASE),
    re.compile(r"^(あとがき|後書き)$"),
)


def _normalize_title(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^[#\s《\[\(\"'“”‘’]+", "", text)
    text = re.sub(r"[》\]\)\"'“”‘’\s]+$", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def is_afterword_title(title: Any) -> bool:
    """Return True when title looks like an afterword section."""
    normalized = _normalize_title(title)
    if not normalized:
        return False

    for pattern in _AFTERWORD_PATTERNS:
        if pattern.fullmatch(normalized):
            return True

    lowered = normalized.lower()
    return "afterword" in lowered or "author note" in lowered


def is_afterword_chapter(chapter: Dict[str, Any], *, source_path: Optional[Path] = None) -> bool:
    """Detect afterword chapters from manifest metadata and optional JP source heading."""
    if not isinstance(chapter, dict):
        return False

    for key in ("title", "title_jp", "title_en", "title_pipeline"):
        if is_afterword_title(chapter.get(key, "")):
            return True

    if source_path and source_path.exists():
        try:
            with source_path.open("r", encoding="utf-8") as f:
                for _ in range(4):
                    line = f.readline()
                    if not line:
                        break
                    heading = line.lstrip("# ").strip()
                    if is_afterword_title(heading):
                        return True
        except Exception:
            return False

    return False

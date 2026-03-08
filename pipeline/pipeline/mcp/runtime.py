"""Shared runtime helpers for MCP tools/resources."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

from .config import MCPConfig, validate_path


class MCPRuntimeError(RuntimeError):
    """Raised when an MCP operation fails."""


def ensure_allowed_path(path: Path, cfg: MCPConfig) -> Path:
    """Validate a path against MCP allowlist and return resolved path."""
    resolved = path.resolve()
    if not validate_path(resolved, cfg):
        raise MCPRuntimeError(f"Path outside MCP allowlist: {resolved}")
    return resolved


def read_json_file(path: Path, cfg: MCPConfig) -> Dict[str, Any]:
    """Read a JSON file within allowed directories."""
    safe = ensure_allowed_path(path, cfg)
    if not safe.exists():
        raise MCPRuntimeError(f"File not found: {safe}")
    with open(safe, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise MCPRuntimeError(f"Expected JSON object in {safe}")
    return data


def read_text_file(path: Path, cfg: MCPConfig, max_chars: int = 120_000) -> str:
    """Read UTF-8 text with output length cap."""
    safe = ensure_allowed_path(path, cfg)
    if not safe.exists():
        raise MCPRuntimeError(f"File not found: {safe}")
    text = safe.read_text(encoding="utf-8")
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars] + "\n\n...[truncated by MCP output limit]..."
    return text


def load_yaml(path: Path, cfg: MCPConfig) -> Dict[str, Any]:
    """Load YAML from allowed path."""
    safe = ensure_allowed_path(path, cfg)
    if not safe.exists():
        raise MCPRuntimeError(f"File not found: {safe}")
    data = yaml.safe_load(safe.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise MCPRuntimeError(f"Expected YAML mapping in {safe}")
    return data


def write_yaml(path: Path, payload: Dict[str, Any], cfg: MCPConfig) -> None:
    """Write YAML to allowed path."""
    safe = ensure_allowed_path(path, cfg)
    safe.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def run_module(
    module: str,
    args: Optional[Iterable[str]],
    cfg: MCPConfig,
    timeout_seconds: int = 7200,
) -> Dict[str, Any]:
    """Execute a Python module and return structured result."""
    command = [sys.executable, "-m", module]
    if args:
        command.extend([str(a) for a in args])

    start = time.perf_counter()
    proc = subprocess.run(
        command,
        cwd=str(cfg.pipeline_root),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    duration = round(time.perf_counter() - start, 3)
    return {
        "ok": proc.returncode == 0,
        "module": module,
        "args": [str(a) for a in (args or [])],
        "return_code": proc.returncode,
        "duration_seconds": duration,
        "stdout": _tail(proc.stdout),
        "stderr": _tail(proc.stderr),
    }


def run_script(
    script_relpath: str,
    args: Optional[Iterable[str]],
    cfg: MCPConfig,
    timeout_seconds: int = 7200,
) -> Dict[str, Any]:
    """Execute a Python script under pipeline root and return structured result."""
    command = [sys.executable, script_relpath]
    if args:
        command.extend([str(a) for a in args])
    start = time.perf_counter()
    proc = subprocess.run(
        command,
        cwd=str(cfg.pipeline_root),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    duration = round(time.perf_counter() - start, 3)
    return {
        "ok": proc.returncode == 0,
        "script": script_relpath,
        "args": [str(a) for a in (args or [])],
        "return_code": proc.returncode,
        "duration_seconds": duration,
        "stdout": _tail(proc.stdout),
        "stderr": _tail(proc.stderr),
    }


def list_volume_ids(cfg: MCPConfig) -> List[str]:
    """List volume directory names under WORK/."""
    if not cfg.work_dir.exists():
        return []
    return sorted([p.name for p in cfg.work_dir.iterdir() if p.is_dir()])


def resolve_volume_dir(volume_id: str, cfg: MCPConfig) -> Path:
    """Resolve and validate volume directory path."""
    if not volume_id or not str(volume_id).strip():
        raise MCPRuntimeError("volume_id is required")
    path = cfg.work_dir / str(volume_id).strip()
    safe = ensure_allowed_path(path, cfg)
    if not safe.exists() or not safe.is_dir():
        raise MCPRuntimeError(f"Volume not found: {safe}")
    return safe


def load_manifest(volume_id: str, cfg: MCPConfig) -> Dict[str, Any]:
    """Load manifest.json for a volume."""
    vol = resolve_volume_dir(volume_id, cfg)
    return read_json_file(vol / "manifest.json", cfg)


def get_language_dir(language: str) -> str:
    """Map language alias to directory name."""
    lang = str(language or "").strip().lower()
    if lang in {"jp", "ja"}:
        return "JP"
    if lang in {"en", "eng"}:
        return "EN"
    if lang in {"vn", "vi"}:
        return "VN"
    return lang.upper() if lang else "EN"


def resolve_chapter_markdown(
    volume_dir: Path,
    language: str,
    chapter_id: str,
    cfg: MCPConfig,
) -> Path:
    """Resolve chapter markdown file in JP/EN/VN directory."""
    lang_dir = volume_dir / get_language_dir(language)
    safe_lang_dir = ensure_allowed_path(lang_dir, cfg)
    if not safe_lang_dir.exists():
        raise MCPRuntimeError(f"Language directory not found: {safe_lang_dir}")

    raw = str(chapter_id or "").strip()
    if not raw:
        raise MCPRuntimeError("chapter_id is required")

    candidates: List[Path] = []
    stem = raw[:-3] if raw.lower().endswith(".md") else raw
    for name in (raw, f"{stem}.md", raw.upper(), f"{stem.upper()}.md", raw.lower(), f"{stem.lower()}.md"):
        candidates.append(safe_lang_dir / name)

    number = _extract_chapter_number(raw)
    if number is not None:
        candidates.extend(
            [
                safe_lang_dir / f"CHAPTER_{number:02d}.md",
                safe_lang_dir / f"CHAPTER_{number:02d}_EN.md",
                safe_lang_dir / f"chapter_{number:02d}.md",
                safe_lang_dir / f"chapter-{number:02d}.md",
            ]
        )

    for path in candidates:
        if path.exists():
            return ensure_allowed_path(path, cfg)

    # Fallback: fuzzy match by chapter number in filename.
    if number is not None:
        pattern = re.compile(rf"(?:chapter[_\-\s]*)0*{number}(?:\D|$)", re.IGNORECASE)
        for path in sorted(safe_lang_dir.glob("*.md")):
            if pattern.search(path.stem):
                return ensure_allowed_path(path, cfg)

    # Fallback: stem inclusion search.
    lowered = stem.lower()
    for path in sorted(safe_lang_dir.glob("*.md")):
        if lowered in path.stem.lower():
            return ensure_allowed_path(path, cfg)

    raise MCPRuntimeError(
        f"Chapter file not found: volume={volume_dir.name} language={language} chapter_id={chapter_id}"
    )


def resolve_bible_file(series_id: str, cfg: MCPConfig) -> Path:
    """Resolve series bible JSON path."""
    sid = str(series_id or "").strip()
    if not sid:
        raise MCPRuntimeError("series_id is required")
    direct = cfg.bibles_dir / f"{sid}.json"
    if direct.exists():
        return ensure_allowed_path(direct, cfg)

    alt = cfg.bibles_dir / sid
    if alt.exists() and alt.suffix.lower() == ".json":
        return ensure_allowed_path(alt, cfg)

    matches = list(cfg.bibles_dir.glob(f"{sid}*.json"))
    if matches:
        return ensure_allowed_path(sorted(matches)[0], cfg)
    raise MCPRuntimeError(f"Bible not found: {sid}")


def _extract_chapter_number(text: str) -> Optional[int]:
    match = re.search(r"(\d+)", str(text or ""))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _tail(text: str, max_chars: int = 30_000) -> str:
    """Keep the tail of long subprocess output for MCP responses."""
    value = str(text or "")
    if len(value) <= max_chars:
        return value
    return "...[truncated]...\n" + value[-max_chars:]


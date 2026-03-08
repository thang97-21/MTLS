"""
Volume Workbench (Phase C) menu helpers.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import questionary
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..components.styles import custom_style

console = Console()

_CJK_FALLBACK_PATTERN = re.compile(r"[\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]")


def get_manifest_chapters(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return normalized chapter list from manifest."""
    chapters = manifest.get("chapters", [])
    if not chapters:
        chapters = manifest.get("structure", {}).get("chapters", [])
    return [ch for ch in chapters if isinstance(ch, dict)]


def resolve_target_language(manifest: Dict[str, Any]) -> str:
    """Resolve target language folder code from manifest state."""
    translator_state = manifest.get("pipeline_state", {}).get("translator", {})
    target_lang = (
        str(translator_state.get("target_language", "")).strip()
        or str(manifest.get("metadata", {}).get("target_language", "")).strip()
        or "EN"
    )
    return target_lang.upper()


def _coerce_chapter_title(chapter: Dict[str, Any], target_lang: str) -> str:
    lower = target_lang.lower()
    if lower == "en":
        return str(chapter.get("title_en") or chapter.get("title") or "").strip()
    if lower == "vn":
        return str(chapter.get("title_vn") or chapter.get("title") or "").strip()
    return str(chapter.get("title") or "").strip()


def resolve_chapter_output_path(volume_dir: Path, chapter: Dict[str, Any], target_lang: str) -> Path:
    """Best-effort resolve translated chapter markdown path."""
    lower = target_lang.lower()
    candidate_keys = [
        f"translated_file_{lower}",
        "translated_file",
        f"{lower}_file",
        "output_file",
    ]
    for key in candidate_keys:
        rel = str(chapter.get(key, "")).strip()
        if not rel:
            continue
        p = Path(rel)
        return p if p.is_absolute() else (volume_dir / p)

    chapter_id = str(chapter.get("id", "")).strip()
    id_match = re.search(r"(\d+)", chapter_id)
    if id_match:
        idx = int(id_match.group(1))
        return volume_dir / target_lang / f"CHAPTER_{idx:02d}_{target_lang}.md"

    source_file = str(chapter.get("source_file") or chapter.get("jp_file") or chapter.get("filename") or "").strip()
    if source_file:
        source_stem = Path(source_file).stem
        return volume_dir / target_lang / f"{source_stem}_{target_lang}.md"

    return volume_dir / target_lang / f"{chapter_id or 'UNKNOWN'}_{target_lang}.md"


def build_workbench_rows(work_dir: Path, volume_id: str) -> Optional[Dict[str, Any]]:
    """Build per-chapter rows for workbench table/actions."""
    volume_dir = work_dir / volume_id
    manifest_path = volume_dir / "manifest.json"
    if not manifest_path.exists():
        return None

    import json

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chapters = get_manifest_chapters(manifest)
    target_lang = resolve_target_language(manifest)

    rows: List[Dict[str, Any]] = []
    for i, chapter in enumerate(chapters, 1):
        chapter_id = str(chapter.get("id", "")).strip() or f"chapter_{i:02d}"
        source_file = str(chapter.get("source_file") or chapter.get("jp_file") or chapter.get("filename") or "").strip()
        status = str(chapter.get("translation_status", "pending")).strip() or "pending"
        qc_status = str(chapter.get("qc_status", "pending")).strip() or "pending"
        title = _coerce_chapter_title(chapter, target_lang)
        out_path = resolve_chapter_output_path(volume_dir, chapter, target_lang)
        thinking_path = volume_dir / "THINKING" / f"{chapter_id}_THINKING.md"

        rows.append(
            {
                "id": chapter_id,
                "index": i,
                "title": title or "(No title)",
                "status": status,
                "qc_status": qc_status,
                "source_file": source_file,
                "output_path": out_path,
                "output_exists": out_path.exists(),
                "thinking_path": thinking_path,
                "thinking_exists": thinking_path.exists(),
            }
        )

    completed = sum(1 for r in rows if r["status"] == "completed")
    failed = sum(1 for r in rows if r["status"] == "failed")
    pending = sum(1 for r in rows if r["status"] not in {"completed", "failed"})

    return {
        "manifest": manifest,
        "target_lang": target_lang,
        "rows": rows,
        "summary": {
            "total": len(rows),
            "completed": completed,
            "failed": failed,
            "pending": pending,
        },
    }


def render_workbench(volume_id: str, target_lang: str, rows: List[Dict[str, Any]], summary: Dict[str, int]) -> None:
    """Render Volume Workbench panel and chapter table."""
    console.print()
    console.print(
        Panel(
            "[bold]Volume Workbench (Phase C)[/bold]\n"
            f"[dim]Volume:[/dim] {volume_id} | [dim]Language:[/dim] {target_lang}\n"
            f"[dim]Chapters:[/dim] {summary.get('total', 0)} | "
            f"[dim]Completed:[/dim] {summary.get('completed', 0)} | "
            f"[dim]Failed:[/dim] {summary.get('failed', 0)} | "
            f"[dim]Pending:[/dim] {summary.get('pending', 0)}",
            border_style="green",
            padding=(1, 2),
        )
    )

    table = Table(title="Chapter Workbench", box=box.ROUNDED)
    table.add_column("#", style="dim", width=4)
    table.add_column("Chapter ID", style="cyan", width=14)
    table.add_column("Status", width=10)
    table.add_column("QC", width=8)
    table.add_column("Output", width=8)
    table.add_column("Thinking", width=9)
    table.add_column("Title", style="white", width=42)

    for row in rows[:30]:
        status = row["status"]
        status_icon = {
            "completed": "[green]DONE[/green]",
            "failed": "[red]FAIL[/red]",
            "in_progress": "[yellow]RUN[/yellow]",
            "pending": "[dim]TODO[/dim]",
        }.get(status, f"[dim]{status[:8]}[/dim]")

        qc = row["qc_status"] or "pending"
        output_icon = "[green]YES[/green]" if row["output_exists"] else "[dim]NO[/dim]"
        thinking_icon = "[green]YES[/green]" if row["thinking_exists"] else "[dim]NO[/dim]"
        table.add_row(
            str(row["index"]),
            row["id"],
            status_icon,
            qc[:8],
            output_icon,
            thinking_icon,
            str(row["title"])[:42],
        )

    if len(rows) > 30:
        table.add_row("...", f"+{len(rows) - 30} more", "", "", "", "", "")

    console.print()
    console.print(table)
    console.print()


def select_repair_chapters(rows: List[Dict[str, Any]], default_mode: str = "failed_pending") -> Optional[List[str]]:
    """Prompt user to pick chapter IDs for repair actions."""
    choices: List[questionary.Choice] = []
    for row in rows:
        checked = False
        if default_mode == "failed_pending":
            checked = row["status"] in {"failed", "pending"}
        elif default_mode == "completed":
            checked = row["status"] == "completed"

        label = (
            f"{row['id']} | {row['status']:<10} | "
            f"{'OUT' if row['output_exists'] else 'NO-OUT':<6} | {row['title'][:48]}"
        )
        choices.append(questionary.Choice(label, value=row["id"], checked=checked))

    selected = questionary.checkbox(
        "Select chapter IDs:",
        choices=choices,
        style=custom_style,
    ).ask()
    return selected if selected else None


def _load_cjk_validator(project_root: Path) -> Optional[Any]:
    """Dynamically load scripts/cjk_validator.py if available."""
    validator_path = project_root / "scripts" / "cjk_validator.py"
    if not validator_path.exists():
        return None

    try:
        spec = importlib.util.spec_from_file_location("mtl_cjk_validator", validator_path)
        if not spec or not spec.loader:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        validator_cls = getattr(module, "CJKValidator", None)
        return validator_cls() if validator_cls else None
    except Exception:
        return None


def _fallback_cjk_issue_count(path: Path) -> int:
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8", errors="ignore")
    return len(_CJK_FALLBACK_PATTERN.findall(text))


def run_cjk_scan(rows: List[Dict[str, Any]], chapter_ids: List[str], project_root: Path) -> List[Dict[str, Any]]:
    """Run CJK scan for selected chapter output files and return result rows."""
    target_set = set(chapter_ids)
    validator = _load_cjk_validator(project_root)
    results: List[Dict[str, Any]] = []

    for row in rows:
        if row["id"] not in target_set:
            continue

        chapter_path = Path(row["output_path"])
        leak_count = 0
        missing = not chapter_path.exists()

        if not missing and validator is not None:
            try:
                issues = validator.validate_file(chapter_path)
                leak_count = len(issues)
            except Exception:
                leak_count = _fallback_cjk_issue_count(chapter_path)
        elif not missing:
            leak_count = _fallback_cjk_issue_count(chapter_path)

        results.append(
            {
                "id": row["id"],
                "path": chapter_path,
                "missing": missing,
                "leaks": leak_count,
            }
        )

    return results


def render_cjk_scan_results(results: List[Dict[str, Any]]) -> List[str]:
    """Render CJK scan table and return chapter IDs with leaks."""
    console.print()
    table = Table(title="Chapter CJK Scan", box=box.ROUNDED)
    table.add_column("Chapter ID", style="cyan", width=14)
    table.add_column("Status", width=10)
    table.add_column("Leak Count", justify="right", width=10)
    table.add_column("File", style="dim", width=50)

    leaking_ids: List[str] = []
    for row in results:
        if row["missing"]:
            status = "[yellow]MISSING[/yellow]"
            leak_str = "-"
        elif row["leaks"] > 0:
            status = "[red]LEAKS[/red]"
            leak_str = str(row["leaks"])
            leaking_ids.append(row["id"])
        else:
            status = "[green]CLEAN[/green]"
            leak_str = "0"
        table.add_row(
            row["id"],
            status,
            leak_str,
            str(row["path"]),
        )

    console.print(table)
    console.print(
        f"\n[bold]Summary:[/bold] scanned={len(results)} | "
        f"leaking={len(leaking_ids)} | clean={len(results) - len(leaking_ids)}"
    )
    return leaking_ids


"""
Merge translated shard chapters back into canonical spine chapter groups.

Use case:
- Librarian fallback split (`split_strategy=text_page_boundary`) creates many
  translation shards for operational throughput.
- Builder needs canonical chapter structure for final EPUB assembly.
"""

from __future__ import annotations

import copy
import datetime
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _coerce_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, str):
        text = value.strip()
        return text if text else fallback
    return str(value).strip() or fallback


def _is_fragmented_shard(chapter: Dict[str, Any]) -> bool:
    return (
        chapter.get("split_strategy") == "text_page_boundary"
        and chapter.get("raw_group_index") is not None
    )


def _flatten_source_files(chapter: Dict[str, Any]) -> List[str]:
    source_files = chapter.get("source_files")
    if isinstance(source_files, list):
        cleaned = [_coerce_text(v, "") for v in source_files]
        return [v for v in cleaned if v]
    single = _coerce_text(chapter.get("source_file"), "")
    return [single] if single else []


def _find_content_dir(work_dir: Path) -> Optional[Path]:
    candidates = sorted(work_dir.glob("_epub_extracted/**/standard.opf"))
    if not candidates:
        candidates = sorted(work_dir.glob("_epub_extracted/**/content.opf"))
    if not candidates:
        return None
    return candidates[0].parent


def _find_xhtml_file(content_dir: Path, filename: str) -> Optional[Path]:
    direct = content_dir / filename
    if direct.exists():
        return direct
    for sub in ("xhtml", "XHTML", "text", "Text", "OEBPS", "OPS"):
        p = content_dir / sub / filename
        if p.exists():
            return p
    matches = list(content_dir.rglob(filename))
    return matches[0] if matches else None


_CHAPTER_START_PATTERNS = [
    re.compile(r"^第[一二三四五六七八九十百千\d０-９]+章"),
    re.compile(r"^第[一二三四五六七八九十百千\d０-９]+話"),
    re.compile(r"^chapter\s*\d+", re.IGNORECASE),
    re.compile(r"^prologue$", re.IGNORECASE),
    re.compile(r"^epilogue$", re.IGNORECASE),
    re.compile(r"^interlude$", re.IGNORECASE),
    re.compile(r"^afterword$", re.IGNORECASE),
    re.compile(r"^(あとがき|後書き)$"),
    re.compile(r"^[（(]?\d{1,3}[)）]?$"),
    re.compile(r"^[（(]?[０-９]{1,3}[)）]?$"),
]


def _normalize_marker_title(text: str) -> str:
    raw = _coerce_text(text, "")
    if not raw:
        return ""
    normalized_digits = raw.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if re.fullmatch(r"[（(]?\d{1,3}[)）]?", normalized_digits):
        number = int(re.sub(r"\D", "", normalized_digits))
        return f"Chapter {number}"
    if re.fullmatch(r"(あとがき|後書き|afterword)", normalized_digits, flags=re.IGNORECASE):
        return "Afterword"
    return normalized_digits


def _detect_start_marker_title(xhtml_path: Path) -> Optional[str]:
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return None

    try:
        soup = BeautifulSoup(xhtml_path.read_text(encoding="utf-8", errors="ignore"), "xml")
        body = soup.find("body")
        if body is None:
            return None

        candidates: List[str] = []
        for tag in ("h1", "h2", "h3"):
            heading = body.find(tag)
            if heading:
                text = heading.get_text(strip=True)
                if text:
                    candidates.append(text)

        if not candidates:
            for p in body.find_all("p", limit=6):
                text = p.get_text(strip=True)
                if text:
                    candidates.append(text)

        for candidate in candidates:
            marker = _normalize_marker_title(candidate)
            if not marker:
                continue
            for pattern in _CHAPTER_START_PATTERNS:
                if pattern.search(marker):
                    return marker
    except Exception:
        return None

    return None


def _resolve_markdown_path(
    chapter: Dict[str, Any],
    translated_dir: Path,
    jp_dir: Path,
    target_language: str,
) -> Optional[Path]:
    source_file = _coerce_text(chapter.get("source_file"), "")
    lang_file_key = f"{target_language}_file"
    translated_name = _coerce_text(
        chapter.get(lang_file_key) or chapter.get("translated_file") or source_file,
        source_file,
    )
    translated_path = translated_dir / translated_name
    if translated_path.exists():
        return translated_path
    if source_file:
        jp_path = jp_dir / source_file
        if jp_path.exists():
            return jp_path
    return None


def _strip_leading_header(markdown: str) -> str:
    lines = markdown.splitlines()
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx < len(lines) and lines[idx].lstrip().startswith("#"):
        idx += 1
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    return "\n".join(lines[idx:]).strip()


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _split_fragmented_block(
    block: List[Dict[str, Any]],
    start_pages: Dict[str, str],
) -> List[List[Dict[str, Any]]]:
    groups: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []

    for chapter in block:
        source_files = _flatten_source_files(chapter)
        first_source = source_files[0] if source_files else ""
        starts_here = bool(first_source and first_source in start_pages)

        if not current:
            current = [chapter]
            continue

        if starts_here:
            groups.append(current)
            current = [chapter]
            continue

        current.append(chapter)

    if current:
        groups.append(current)
    return groups


def _get_fallback_title(metadata: Dict[str, Any], target_language: str) -> str:
    """
    Retrieve the fallback title from metadata.
    """
    return (
        metadata.get(f"title_{target_language}")
        or metadata.get("title_en")
        or metadata.get("official_localization", {}).get("volume_title_en")
        or "Untitled Volume"
    )


def merge_translated_shards_to_spine(
    work_dir: Path,
    manifest: Dict[str, Any],
    *,
    target_language: str = "en",
    apply_manifest: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Merge fragmented translated shards into canonical spine chapter groups.

    Returns:
        (manifest_override, diagnostics)
    """
    diagnostics: Dict[str, Any] = {
        "applied": False,
        "reason": "",
        "source_chapters": 0,
        "canonical_chapters": 0,
        "merged_groups": [],
        "map_path": "",
        "merged_dir": "",
    }

    chapters = manifest.get("chapters", [])
    if not chapters and isinstance(manifest.get("structure"), dict):
        chapters = manifest.get("structure", {}).get("chapters", [])
    if not isinstance(chapters, list) or not chapters:
        diagnostics["reason"] = "no_chapters"
        return manifest, diagnostics

    chapters_sorted = sorted(chapters, key=lambda ch: ch.get("toc_order", 999))
    diagnostics["source_chapters"] = len(chapters_sorted)

    fragmented = [ch for ch in chapters_sorted if _is_fragmented_shard(ch)]
    if len(fragmented) < 2:
        diagnostics["reason"] = "no_fragmented_shards"
        return manifest, diagnostics

    content_dir = _find_content_dir(work_dir)
    if content_dir is None:
        diagnostics["reason"] = "content_dir_not_found"
        return manifest, diagnostics

    start_pages: Dict[str, str] = {}
    for chapter in fragmented:
        source_files = _flatten_source_files(chapter)
        if not source_files:
            continue
        first_source = source_files[0]
        if first_source in start_pages:
            continue
        xhtml_path = _find_xhtml_file(content_dir, first_source)
        if xhtml_path is None:
            continue
        marker_title = _detect_start_marker_title(xhtml_path)
        if marker_title:
            start_pages[first_source] = marker_title

    if len(start_pages) < 2:
        diagnostics["reason"] = "insufficient_start_markers"
        return manifest, diagnostics

    grouped_batches: List[List[Dict[str, Any]]] = []
    pending_fragmented: List[Dict[str, Any]] = []

    for chapter in chapters_sorted:
        if _is_fragmented_shard(chapter):
            pending_fragmented.append(chapter)
            continue

        if pending_fragmented:
            grouped_batches.extend(_split_fragmented_block(pending_fragmented, start_pages))
            pending_fragmented = []
        grouped_batches.append([chapter])

    if pending_fragmented:
        grouped_batches.extend(_split_fragmented_block(pending_fragmented, start_pages))

    if len(grouped_batches) >= len(chapters_sorted):
        diagnostics["reason"] = "no_merge_opportunity"
        return manifest, diagnostics

    translated_dir = work_dir / target_language.upper()
    jp_dir = work_dir / "JP"
    merged_dir = translated_dir / "SPINE_MERGED"
    merged_dir.mkdir(parents=True, exist_ok=True)

    canonical_chapters: List[Dict[str, Any]] = []
    merge_map: Dict[str, Any] = {
        "created_at": datetime.datetime.now().isoformat(),
        "target_language": target_language,
        "source_chapter_count": len(chapters_sorted),
        "canonical_chapter_count": 0,
        "groups": [],
    }

    for idx, group in enumerate(grouped_batches, start=1):
        primary = group[0]
        merged_source_files: List[str] = []
        merged_ids: List[str] = []
        merged_illustrations: List[str] = []
        markdown_chunks: List[str] = []
        status_values: List[str] = []
        qc_values: List[str] = []
        merged_word_count = 0

        for chapter in group:
            merged_ids.append(_coerce_text(chapter.get("id"), ""))
            merged_source_files.extend(_flatten_source_files(chapter))
            merged_illustrations.extend(
                [_coerce_text(v, "") for v in (chapter.get("illustrations") or []) if _coerce_text(v, "")]
            )
            status_values.append(_coerce_text(chapter.get("translation_status"), "pending").lower())
            qc_values.append(_coerce_text(chapter.get("qc_status"), "pending").lower())
            try:
                merged_word_count += int(chapter.get("word_count") or 0)
            except Exception:
                pass
            md_path = _resolve_markdown_path(chapter, translated_dir, jp_dir, target_language)
            if md_path is None:
                continue
            content = md_path.read_text(encoding="utf-8")
            body = _strip_leading_header(content)
            if body:
                markdown_chunks.append(body)

        source_files_unique = _dedupe_preserve_order([f for f in merged_source_files if f])
        marker_title = ""
        if source_files_unique:
            marker_title = start_pages.get(source_files_unique[0], "")

        fallback_title = _get_fallback_title(primary, target_language)
        title = marker_title or fallback_title

        # Normalize chapter titles for non-fragmented entries
        if not _is_fragmented_shard(primary):
            title = _normalize_marker_title(title)

        merged_filename = f"CHAPTER_{idx:02d}_{target_language.upper()}_SPINE.md"
        merged_rel_path = f"SPINE_MERGED/{merged_filename}"
        merged_path = merged_dir / merged_filename

        merged_body = "\n\n".join(markdown_chunks).strip()
        merged_markdown = f"# {title}\n\n{merged_body}\n" if merged_body else f"# {title}\n"
        merged_path.write_text(merged_markdown, encoding="utf-8")

        new_chapter = copy.deepcopy(primary)
        new_chapter["id"] = f"chapter_{idx:02d}"
        new_chapter["title"] = title
        new_chapter["toc_order"] = idx - 1
        new_chapter["source_files"] = source_files_unique
        new_chapter["source_file"] = _coerce_text(primary.get("source_file"), "") or f"CHAPTER_{idx:02d}.md"
        new_chapter["translated_file"] = merged_rel_path
        new_chapter[f"{target_language}_file"] = merged_rel_path
        new_chapter["split_strategy"] = "spine_canonical_merge"
        new_chapter["illustrations"] = _dedupe_preserve_order(
            [v for v in merged_illustrations if v]
        )
        new_chapter["merged_from_chapter_ids"] = [cid for cid in merged_ids if cid]
        new_chapter["word_count"] = merged_word_count
        new_chapter["translation_status"] = (
            "completed" if status_values and all(v == "completed" for v in status_values) else "pending"
        )
        new_chapter["qc_status"] = (
            "completed" if qc_values and all(v == "completed" for v in qc_values) else "pending"
        )
        new_chapter.pop("scene_plan_file", None)
        new_chapter.pop("summary_file", None)

        canonical_chapters.append(new_chapter)
        merge_map["groups"].append({
            "canonical_chapter_index": idx,
            "canonical_title": title,
            "merged_file": merged_rel_path,
            "merged_from_chapter_ids": [cid for cid in merged_ids if cid],
            "source_files": source_files_unique,
        })

    merge_map["canonical_chapter_count"] = len(canonical_chapters)

    context_dir = work_dir / ".context"
    context_dir.mkdir(parents=True, exist_ok=True)
    map_path = context_dir / "spine_chapter_merge_map.json"
    map_path.write_text(json.dumps(merge_map, indent=2, ensure_ascii=False), encoding="utf-8")

    manifest_out = copy.deepcopy(manifest)
    manifest_out["chapters"] = canonical_chapters
    if isinstance(manifest_out.get("structure"), dict):
        manifest_out["structure"]["chapters"] = canonical_chapters

    pipeline_state = manifest_out.setdefault("pipeline_state", {})
    preflight = pipeline_state.setdefault("builder_preflight", {})
    preflight["spine_chapter_merge"] = {
        "status": "applied",
        "timestamp": datetime.datetime.now().isoformat(),
        "source_chapters": len(chapters_sorted),
        "canonical_chapters": len(canonical_chapters),
        "merged_dir": str(merged_dir),
        "map_file": str(map_path),
    }

    if apply_manifest:
        manifest_path = work_dir / "manifest.json"
        backup_path = context_dir / f"manifest_before_spine_merge_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        backup_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        manifest_path.write_text(json.dumps(manifest_out, indent=2, ensure_ascii=False), encoding="utf-8")

    diagnostics.update({
        "applied": True,
        "reason": "merged_to_spine_canonical",
        "canonical_chapters": len(canonical_chapters),
        "merged_groups": merge_map["groups"],
        "map_path": str(map_path),
        "merged_dir": str(merged_dir),
    })
    return manifest_out, diagnostics

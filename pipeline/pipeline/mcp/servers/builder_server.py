"""Builder phase MCP tools with plan-aligned contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from PIL import Image

from pipeline.builder.markdown_to_xhtml import convert_paragraphs_to_xhtml
from pipeline.builder.merge_translated_shards_to_spine import merge_translated_shards_to_spine

from ..config import MCPConfig
from ..runtime import ensure_allowed_path, load_manifest, resolve_volume_dir, run_module


def register_builder_tools(mcp: object, cfg: MCPConfig) -> None:
    """Register Phase 4 builder tools."""

    @mcp.tool()  # type: ignore[attr-defined]
    def markdown_to_xhtml(
        md_content: str,
        chapter_id: str = "",
        skip_illustrations: bool = False,
    ) -> dict:
        paragraphs = _split_markdown_paragraphs(md_content or "")
        xhtml = convert_paragraphs_to_xhtml(paragraphs, skip_illustrations=bool(skip_illustrations))
        return {
            "schema": "XHTMLContent",
            "chapter_id": chapter_id,
            "paragraph_count": len(paragraphs),
            "xhtml": xhtml,
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def generate_opf(manifest: Dict[str, Any] | None = None, volume_id: str = "") -> dict:
        resolved_manifest = manifest if isinstance(manifest, dict) else {}
        if not resolved_manifest:
            if not volume_id:
                return {"schema": "OPFDocument", "error": "Either manifest or volume_id is required"}
            resolved_manifest = load_manifest(volume_id, cfg)
        metadata = resolved_manifest.get("metadata", {}) if isinstance(resolved_manifest, dict) else {}
        chapters = resolved_manifest.get("chapters", []) if isinstance(resolved_manifest, dict) else []
        return {
            "schema": "OPFDocument",
            "mode": "manifest_preview",
            "volume_id": volume_id or resolved_manifest.get("volume_id", ""),
            "title": metadata.get("title", ""),
            "author": metadata.get("author", ""),
            "language": metadata.get("target_language", "en"),
            "chapter_count": len(chapters),
            "spine_items": [item.get("translated_file", "") for item in chapters if isinstance(item, dict)],
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def generate_nav(manifest: Dict[str, Any] | None = None, volume_id: str = "") -> dict:
        resolved_manifest = manifest if isinstance(manifest, dict) else {}
        if not resolved_manifest:
            if not volume_id:
                return {"schema": "NAVDocument", "error": "Either manifest or volume_id is required"}
            resolved_manifest = load_manifest(volume_id, cfg)
        manifest = resolved_manifest
        chapters = manifest.get("chapters", []) if isinstance(manifest, dict) else []
        entries = []
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            entries.append(
                {
                    "id": chapter.get("id", ""),
                    "title": chapter.get("title", ""),
                    "target": chapter.get("translated_file", ""),
                }
            )
        return {
            "schema": "NAVDocument",
            "mode": "manifest_preview",
            "volume_id": volume_id or manifest.get("volume_id", ""),
            "toc_entries": entries,
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def merge_translated_shards(volume_id: str, target_language: str = "en", apply_manifest: bool = False) -> dict:
        volume_dir = resolve_volume_dir(volume_id, cfg)
        manifest = load_manifest(volume_id, cfg)
        merged_manifest, diagnostics = merge_translated_shards_to_spine(
            work_dir=volume_dir,
            manifest=manifest,
            target_language=target_language,
            apply_manifest=apply_manifest,
        )
        return {
            "schema": "MergeResult",
            "diagnostics": diagnostics,
            "canonical_chapter_count": len(merged_manifest.get("chapters", [])),
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def optimize_image(image_path: str, max_width: int = 1600) -> dict:
        path = Path(image_path).expanduser()
        if not path.is_absolute():
            path = (cfg.pipeline_root / path).resolve()
        ensure_allowed_path(path, cfg)
        if not path.exists():
            return {
                "schema": "OptimizedImage",
                "ok": False,
                "error": f"Image not found: {path}",
            }

        original_size = path.stat().st_size
        with Image.open(path) as image:
            width, height = image.size
            if width > max_width > 0:
                ratio = max_width / float(width)
                new_size = (int(width * ratio), int(height * ratio))
                resized = image.resize(new_size, Image.Resampling.LANCZOS)
                resized.save(path, optimize=True)
                final_size = path.stat().st_size
                return {
                    "schema": "OptimizedImage",
                    "ok": True,
                    "path": str(path),
                    "original_size_bytes": original_size,
                    "optimized_size_bytes": final_size,
                    "width": new_size[0],
                    "height": new_size[1],
                }
            image.save(path, optimize=True)
            final_size = path.stat().st_size
            return {
                "schema": "OptimizedImage",
                "ok": True,
                "path": str(path),
                "original_size_bytes": original_size,
                "optimized_size_bytes": final_size,
                "width": width,
                "height": height,
            }

    @mcp.tool()  # type: ignore[attr-defined]
    def package_epub(
        volume_id: str,
        output_filename: str = "",
        skip_qc: bool = False,
        include_header_illustrations: bool = False,
    ) -> dict:
        args = [volume_id]
        if output_filename:
            args.extend(["--output", output_filename])
        if skip_qc:
            args.append("--skip-qc")
        if include_header_illustrations:
            args.append("--include-header-illustrations")
        execution = run_module("pipeline.builder.agent", args, cfg)
        return {
            "schema": "PackageResult",
            "ok": bool(execution.get("ok", False)),
            "volume_id": volume_id,
            "execution": execution,
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def run_builder(
        volume_id: str,
        output_filename: str = "",
        skip_qc: bool = False,
        include_header_illustrations: bool = False,
    ) -> dict:
        result = package_epub(
            volume_id=volume_id,
            output_filename=output_filename,
            skip_qc=skip_qc,
            include_header_illustrations=include_header_illustrations,
        )
        result["schema"] = "BuildResult"
        return result


def _split_markdown_paragraphs(content: str) -> List[str]:
    """Split markdown body into paragraph units for XHTML conversion."""
    if not content.strip():
        return []
    lines = content.replace("\r\n", "\n").split("\n")
    out: List[str] = []
    buffer: List[str] = []
    for line in lines:
        if not line.strip():
            if buffer:
                out.append("\n".join(buffer).strip())
                buffer = []
            continue
        buffer.append(line)
    if buffer:
        out.append("\n".join(buffer).strip())
    return out

"""Librarian phase MCP tools with plan-aligned contracts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from pipeline.librarian.content_splitter import ContentSplitter
from pipeline.librarian.image_extractor import ImageInfo, catalog_images as catalog_images_from_epub
from pipeline.librarian.metadata_parser import MetadataParser
from pipeline.librarian.publisher_profiles.manager import get_profile_manager
from pipeline.librarian.ruby_extractor import RubyExtractor, extract_ruby_from_directory
from pipeline.librarian.toc_parser import TOCParser
from pipeline.librarian.xhtml_to_markdown import XHTMLToMarkdownConverter

from ..config import MCPConfig
from ..runtime import MCPRuntimeError, ensure_allowed_path, run_module
from ..runtime import load_manifest


def register_librarian_tools(mcp: object, cfg: MCPConfig) -> None:
    """Register Phase 1 librarian tools."""

    @mcp.tool()  # type: ignore[attr-defined]
    def extract_epub(
        epub_path: str,
        volume_id: str = "",
        source_lang: str = "ja",
        target_lang: str = "en",
        ref_validate: bool = False,
    ) -> dict:
        path = Path(epub_path).expanduser()
        if not path.is_absolute():
            path = (cfg.pipeline_root / path).resolve()
        ensure_allowed_path(path, cfg)
        if not path.exists():
            raise MCPRuntimeError(f"EPUB not found: {path}")
        args = [str(path), "--source-lang", source_lang, "--target-lang", target_lang]
        if volume_id:
            args.extend(["--volume-id", volume_id])
        if ref_validate:
            args.append("--ref-validate")
        execution = run_module("pipeline.librarian.agent", args, cfg)
        resolved_volume_id = volume_id or _extract_volume_id_from_stdout(execution.get("stdout", ""))
        manifest = {}
        if execution.get("ok") and resolved_volume_id:
            try:
                manifest = load_manifest(resolved_volume_id, cfg)
            except Exception:
                manifest = {}
        return {
            "schema": "ExtractionResult",
            "ok": bool(execution.get("ok", False)),
            "volume_id": resolved_volume_id,
            "chapter_count": len(manifest.get("chapters", [])) if isinstance(manifest, dict) else 0,
            "manifest_path": str((cfg.work_dir / resolved_volume_id / "manifest.json")) if resolved_volume_id else "",
            "execution": execution,
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def parse_opf_metadata(opf_path: str) -> dict:
        path = Path(opf_path).expanduser()
        if not path.is_absolute():
            path = (cfg.pipeline_root / path).resolve()
        ensure_allowed_path(path, cfg)
        parser = MetadataParser()
        payload = parser.parse_opf(path).to_dict()
        payload["schema"] = "OPFMetadata"
        return payload

    @mcp.tool()  # type: ignore[attr-defined]
    def parse_toc(nav_path: str) -> dict:
        path = Path(nav_path).expanduser()
        if not path.is_absolute():
            path = (cfg.pipeline_root / path).resolve()
        ensure_allowed_path(path, cfg)
        parser_root = path.parent if path.is_file() else path
        parser = TOCParser(parser_root)
        payload = parser.parse().to_dict()
        payload["schema"] = "TableOfContents"
        return payload

    @mcp.tool()  # type: ignore[attr-defined]
    def extract_ruby_names(
        content: str,
        source_file: str = "inline.xhtml",
        filters: Optional[Dict[str, Any]] = None,
    ) -> dict:
        extractor = RubyExtractor()
        # NOTE: Runtime filters are accepted for schema parity but not currently used
        # by RubyExtractor. We surface this explicitly in contract metadata.
        entries = extractor.extract_from_xhtml(content or "", source_file=source_file)
        return {
            "schema": "RubyEntry[]",
            "ruby_entries": [item.to_dict() for item in entries],
            "filters_applied": bool(filters),
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def extract_ruby_from_xhtml_dir(xhtml_dir: str) -> dict:
        path = Path(xhtml_dir).expanduser()
        if not path.is_absolute():
            path = (cfg.pipeline_root / path).resolve()
        ensure_allowed_path(path, cfg)
        return extract_ruby_from_directory(path)

    @mcp.tool()  # type: ignore[attr-defined]
    def convert_xhtml_to_markdown(
        xhtml_content: str,
        source_file: str = "chapter.xhtml",
        chapter_title: str = "",
        publisher_profile: str = "",
    ) -> dict:
        converter = XHTMLToMarkdownConverter()
        chapter = converter.convert_html(
            html_content=xhtml_content or "",
            filename=source_file,
            chapter_title=chapter_title,
        )
        return {
            "schema": "ConvertedChapter",
            "filename": chapter.filename,
            "title": chapter.title,
            "content": chapter.content,
            "illustrations": chapter.illustrations,
            "word_count": chapter.word_count,
            "paragraph_count": chapter.paragraph_count,
            "publisher_profile": publisher_profile,
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def detect_publisher(metadata: Dict[str, Any]) -> dict:
        if not isinstance(metadata, dict):
            raise MCPRuntimeError("metadata must be a JSON object")
        publisher_text = str(
            metadata.get("publisher")
            or metadata.get("dc:publisher")
            or metadata.get("opf_publisher")
            or ""
        )
        manager = get_profile_manager()
        detected, confidence, profile = manager.detect_publisher(publisher_text)
        return {
            "schema": "PublisherProfile",
            "publisher_input": publisher_text,
            "canonical_name": detected,
            "confidence": confidence,
            "aliases": list(getattr(profile, "aliases", []) or []),
            "profile_found": bool(profile),
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def catalog_images(epub_dir: str, publisher: str = "") -> dict:
        path = Path(epub_dir).expanduser()
        if not path.is_absolute():
            path = (cfg.pipeline_root / path).resolve()
        ensure_allowed_path(path, cfg)
        payload = catalog_images_from_epub(path, publisher=publisher or None)
        return {
            "schema": "ImageCatalog",
            "cover": [_image_info_to_dict(item) for item in payload.get("cover", [])],
            "kuchie": [_image_info_to_dict(item) for item in payload.get("kuchie", [])],
            "illustrations": [_image_info_to_dict(item) for item in payload.get("illustrations", [])],
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def split_content(
        spine_items: Optional[List[Dict[str, Any]]] = None,
        content: str = "",
        max_tokens: int = 2000,
        min_tokens: int = 800,
    ) -> dict:
        if not content and spine_items:
            content = "\n\n".join(str(item.get("content", "") or "") for item in spine_items if isinstance(item, dict))
        splitter = ContentSplitter(max_tokens=max_tokens, min_tokens=min_tokens)
        parts = splitter.split_chapter(content or "")
        return {
            "schema": "SplitResult",
            "part_count": len(parts),
            "parts": [
                {
                    "part_number": part.part_number,
                    "word_count": part.word_count,
                    "estimated_tokens": part.estimated_tokens,
                    "illustrations": part.illustrations,
                    "start_line": part.start_line,
                    "end_line": part.end_line,
                    "content": part.content,
                }
                for part in parts
            ],
        }

    @mcp.tool()  # type: ignore[attr-defined]
    def run_librarian(
        epub_path: str,
        volume_id: str = "",
        source_lang: str = "ja",
        target_lang: str = "en",
    ) -> dict:
        result = extract_epub(
            epub_path=epub_path,
            volume_id=volume_id,
            source_lang=source_lang,
            target_lang=target_lang,
            ref_validate=False,
        )
        resolved_volume_id = str(result.get("volume_id", "") or "")
        manifest = {}
        if result.get("ok") and resolved_volume_id:
            try:
                manifest = load_manifest(resolved_volume_id, cfg)
            except Exception:
                manifest = {}
        return {
            "schema": "Manifest",
            "ok": bool(result.get("ok", False)),
            "volume_id": resolved_volume_id,
            "manifest": manifest,
            "execution": result.get("execution", {}),
        }


def _extract_volume_id_from_stdout(stdout_text: str) -> str:
    """Best-effort volume id extraction from librarian CLI output."""
    text = str(stdout_text or "")
    # Most recent line example: "Manifest saved to: <volume_id>/manifest.json"
    match = re.search(r"Manifest saved to:\s*([^\n/]+)/manifest\.json", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # Fallback from extraction banners.
    match = re.search(r"Volume(?:\s*ID)?\s*[:=]\s*([^\s\n]+)", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def _image_info_to_dict(image: ImageInfo) -> dict:
    """Serialize ImageInfo dataclass to plan-aligned dictionary."""
    return {
        "filename": image.filename,
        "filepath": str(image.filepath),
        "image_type": image.image_type,
        "width": image.width,
        "height": image.height,
        "orientation": image.orientation,
        "source_chapter": image.source_chapter,
    }

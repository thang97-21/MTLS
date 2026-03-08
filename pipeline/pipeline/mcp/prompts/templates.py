"""MCP prompt templates."""

from __future__ import annotations

from ..config import MCPConfig
from ..runtime import load_manifest, read_text_file


def register_prompt_templates(mcp: object, cfg: MCPConfig) -> None:
    """Register MCP prompt templates."""

    @mcp.prompt()  # type: ignore[attr-defined]
    def translate_chapter(volume_id: str, chapter_id: str, target_language: str = "en") -> str:
        manifest = load_manifest(volume_id, cfg)
        metadata_key = "metadata_vn" if str(target_language).lower() in {"vn", "vi"} else "metadata_en"
        metadata = manifest.get(metadata_key, {}) if isinstance(manifest, dict) else {}
        if str(target_language).lower() in {"vn", "vi"}:
            prompt_path = cfg.pipeline_root / "VN" / "master_prompt_vn_pipeline.xml"
        else:
            prompt_path = cfg.prompts_dir / "master_prompt_en_compressed.xml"
        master_prompt = read_text_file(prompt_path, cfg, max_chars=180_000)
        chapter_hint = (
            "Assemble translation context for this chapter using manifest metadata, "
            ".context caches, bible pull context, EPS signals, and Koji Fox fingerprints."
        )
        return (
            f"{master_prompt}\n\n"
            f"---\n"
            f"VOLUME ID: {volume_id}\n"
            f"CHAPTER ID: {chapter_id}\n"
            f"TARGET LANGUAGE: {target_language}\n"
            f"METADATA SNAPSHOT KEY: {metadata_key}\n"
            f"METADATA PRESENT: {'yes' if bool(metadata) else 'no'}\n"
            f"INSTRUCTION: {chapter_hint}\n"
        )

    @mcp.prompt()  # type: ignore[attr-defined]
    def metadata_processor(target_language: str = "en") -> str:
        if str(target_language).lower() in {"vn", "vi"}:
            path = cfg.prompts_dir / "metadata_processor_prompt_vn.xml"
        else:
            path = cfg.prompts_dir / "metadata_processor_prompt.xml"
        return read_text_file(path, cfg, max_chars=180_000)

    @mcp.prompt()  # type: ignore[attr-defined]
    def qc_rubric(target_language: str = "en") -> str:
        return (
            "QC rubric:\n"
            "1) Canon fidelity (names, terminology, lore)\n"
            "2) Voice consistency (Koji Fox / VN voice)\n"
            "3) Structural integrity (no truncation, no CJK residue)\n"
            "4) Prose quality (grammar, tense, POV, references)\n"
            f"Target language: {target_language}\n"
        )


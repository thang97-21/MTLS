"""
Anthropic Translation Brief Agent (Phase 1.56).

Generates a single comprehensive "Translator's Guidance" document for an entire
LN volume by having Gemini Flash read the full JP corpus in one pass.

The brief is injected into every chapter's batch prompt simultaneously, replacing
the sequential per-chapter summary feed.  Since all chapters are submitted to the
Anthropic Batch API at the same time, there is no inter-chapter dependency —
every chapter benefits from the complete picture instead of only what came before it.

Lifecycle:
  1. Called once before Phase 2 batch submission (translate_volume_batch Phase 1).
  2. Brief is cached to .context/TRANSLATION_BRIEF.md — skipped on re-runs.
  3. Brief text is prepended to every chapter's user prompt.
  4. Phase 3 chapter summarisation still runs in parallel for next-volume use.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from pipeline.common.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

_BRIEF_FILENAME = "TRANSLATION_BRIEF.md"

# ── Prompt ────────────────────────────────────────────────────────────────────

_BRIEF_SYSTEM_INSTRUCTION = """You are a senior literary translator and translation analyst specialising in Japanese light novels.
Your task is to read an entire LN volume in Japanese and produce a structured Translator's Guidance brief that will be shared with an AI translation engine as background context for every chapter.
Write in clear, concise English.  The brief will be injected verbatim into translation prompts, so make every word count."""

_BRIEF_PROMPT_TEMPLATE = """You are about to read the full Japanese source text of a light novel volume.
After reading, produce a **Translator's Guidance Brief** in the exact Markdown structure below.
This brief will be injected as shared context into the translation prompt for every chapter of this volume.

Volume metadata
  Title (JP): {title_jp}
  Title (EN): {title_en}
  Series:     {series}
  Target language: {target_language}

---

# FULL SOURCE TEXT

{full_corpus}

---

Now write the Translator's Guidance Brief using exactly this structure:

## 1. VOLUME OVERVIEW
One paragraph covering: genre, overall tone, narrative perspective (first/third person), pacing style, and the central emotional arc of this volume.

## 2. CHARACTER ROSTER
Use a rigid per-character template. No free-form character paragraphs.
For each named character, output exactly:

### [EN Name] ([JP name])
- **Role:** ...
- **Voice:** ... (register + personality expression in prose/dialogue)
- **EN name lock:** ... (fixed rendering + address rules; include forbidden variants if needed)
- **Speech markers:** ... (repeatable rhythm/lexical markers, punctuation habits, fragment tendencies)
- **Key relationships:** ... (relationship dynamics that must stay consistent)

Rules:
- Keep field order exactly as above for every character.
- If a field is unknown, write `N/A` (do not omit the field).
- Keep each field concise and directly actionable.

## 3. CHAPTER-BY-CHAPTER TIMELINE
Use a rigid per-chapter template. No free-form chapter paragraphs.
For each chapter, output exactly:

### [chapter_id]
- **Setting:** ...
- **Key events:** ... (2-5 compact event clauses)
- **Characters present:** ...
- **Emotional register:** ...
- **Continuity flags:** ... (foreshadowing/payoff/state changes that affect later chapters)

Rules:
- Keep field order exactly as above for every chapter.
- If a field is unknown, write `N/A` (do not omit the field).
- Keep entries compact and scannable.

## 4. LOCKED TERMINOLOGY
Use this exact table format (no extra columns, no prose between rows):

| JP Term | EN Rendering | Notes |
|---------|-------------|-------|
| ... | ... | ... |

Rules:
- Include domain-specific terms, world-building vocabulary, honorific handling, and recurring phrases.
- `EN Rendering` must be the mandatory locked form.
- `Notes` should contain usage constraints, register scope, or forbidden alternates.

## 5. TONE ARC & STYLE NOTES
Describe how the emotional register shifts across the volume (comedy peaks, dramatic weight, tender moments). Flag any chapters requiring extra care for humour, grief, or action pacing. Note the author's prose style: sentence length, fragment usage, use of internal monologue, etc.

## 6. RECURRING MOTIFS & CALLBACKS
List recurring jokes, metaphors, symbolic objects, or dialogue callbacks that span multiple chapters. For each, explain what it represents and how it should be rendered consistently.

## 7. FORESHADOWING & CONTINUITY FLAGS
List any details in earlier chapters that pay off later, or details the translator must render consistently to avoid retroactive inconsistency.

Formatting constraints:
- Output pure Markdown only.
- Keep section headers (`## 1` ... `## 7`) exactly as written.
- Sections 2, 3, and 4 must follow the rigid schemas above.
- Sections 1, 5, 6, and 7 may use concise prose/bullets.

Be thorough but not verbose. Every item in sections 2–7 must be directly actionable for a translator."""


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class TranslationBriefResult:
    """Result from a brief generation attempt."""
    success: bool
    brief_text: str
    brief_path: Optional[Path]
    model: str
    cached: bool = False
    error: Optional[str] = None


# ── Agent ─────────────────────────────────────────────────────────────────────

class AnthropicTranslationBriefAgent:
    """
    Reads the full JP corpus of a volume and produces a Translator's Guidance
    brief via a single Gemini Flash call.

    The brief replaces sequential chapter summaries for Anthropic batch runs.
    """

    def __init__(
        self,
        gemini_client: GeminiClient,
        work_dir: Path,
        manifest: Dict[str, Any],
        target_language: str = "en",
        model: str = "gemini-2.5-flash",
    ):
        self.client = gemini_client
        self.work_dir = work_dir
        self.manifest = manifest
        self.target_language = target_language
        self.model = model

        self.context_dir = work_dir / ".context"
        self.context_dir.mkdir(parents=True, exist_ok=True)
        self.brief_path = self.context_dir / _BRIEF_FILENAME

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_brief(self, force: bool = False) -> TranslationBriefResult:
        """
        Generate (or load from cache) the Translator's Guidance brief.

        Args:
            force: Re-generate even if a cached brief already exists.

        Returns:
            TranslationBriefResult with .brief_text populated on success.
        """
        # Use cached brief if available
        if not force and self.brief_path.exists():
            cached_text = self.brief_path.read_text(encoding="utf-8").strip()
            if cached_text:
                logger.info(
                    f"[BRIEF] Using cached Translator's Guidance brief "
                    f"({len(cached_text):,} chars) — {self.brief_path.name}"
                )
                return TranslationBriefResult(
                    success=True,
                    brief_text=cached_text,
                    brief_path=self.brief_path,
                    model=self.model,
                    cached=True,
                )

        logger.info("[BRIEF] Generating Translator's Guidance brief from full JP corpus…")

        # Build corpus
        corpus_text, chapter_count = self._build_jp_corpus()
        if not corpus_text.strip():
            return TranslationBriefResult(
                success=False,
                brief_text="",
                brief_path=None,
                model=self.model,
                error="No JP source text found — cannot generate brief.",
            )

        logger.info(
            f"[BRIEF] Corpus assembled: {chapter_count} chapters, "
            f"{len(corpus_text):,} chars → submitting to {self.model}"
        )

        # Build prompt
        meta = self.manifest.get("metadata", {})
        prompt = _BRIEF_PROMPT_TEMPLATE.format(
            title_jp=meta.get("title_jp") or meta.get("title") or "Unknown",
            title_en=meta.get("title_en") or meta.get("title") or "Unknown",
            series=meta.get("series") or meta.get("series_title") or "Standalone",
            target_language=self.target_language.upper(),
            full_corpus=corpus_text,
        )

        try:
            response = self.client.generate(
                prompt=prompt,
                system_instruction=_BRIEF_SYSTEM_INSTRUCTION,
                temperature=0.3,
                max_output_tokens=8192,
                model=self.model,
                force_new_session=True,
            )
            brief_text = (response.content or "").strip()
            if not brief_text:
                raise ValueError("Gemini returned empty brief")

            # Persist
            self.brief_path.write_text(brief_text, encoding="utf-8")
            logger.info(
                f"[BRIEF] Brief generated: {len(brief_text):,} chars → "
                f"saved to {self.brief_path}"
            )
            return TranslationBriefResult(
                success=True,
                brief_text=brief_text,
                brief_path=self.brief_path,
                model=self.model,
                cached=False,
            )

        except Exception as exc:
            logger.warning(
                f"[BRIEF] Brief generation failed: {exc}. "
                "Batch translation will proceed without the volume brief."
            )
            return TranslationBriefResult(
                success=False,
                brief_text="",
                brief_path=None,
                model=self.model,
                error=str(exc),
            )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_jp_corpus(self) -> tuple[str, int]:
        """
        Concatenate all JP chapter files in chapter order.

        Returns:
            (concatenated_text, chapter_count)
        """
        chapters = self.manifest.get("chapters", [])
        if not chapters:
            chapters = self.manifest.get("structure", {}).get("chapters", [])

        jp_dir = self.work_dir / "JP"
        parts: List[str] = []
        found = 0

        for chapter in chapters:
            jp_file = chapter.get("jp_file") or chapter.get("source_file")
            if not jp_file:
                continue
            source_path = jp_dir / jp_file
            if not source_path.exists():
                logger.debug(f"[BRIEF] JP file not found, skipping: {source_path}")
                continue
            try:
                text = source_path.read_text(encoding="utf-8").strip()
                if text:
                    chapter_id = chapter.get("id", jp_file)
                    parts.append(f"\n\n=== CHAPTER: {chapter_id} ===\n\n{text}")
                    found += 1
            except Exception as _e:
                logger.warning(f"[BRIEF] Could not read {source_path}: {_e}")

        return "".join(parts), found


# ── Standalone entry point ────────────────────────────────────────────────────

def main() -> None:
    """
    Subprocess entry point for Phase 1.56.

    Usage:
        python -m pipeline.post_processor.translation_brief_agent --volume <vol_id> [--force]
    """
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(
        description="Phase 1.56: Generate Translator's Guidance Brief for a volume."
    )
    parser.add_argument("--volume", required=True, help="Volume ID (directory name inside WORK/)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-generate even if a cached brief already exists",
    )
    args = parser.parse_args()

    # Bootstrap pipeline environment
    try:
        from pipeline.config import WORK_DIR
        from pipeline.common.gemini_client import GeminiClient
        from pipeline.translator.config import get_gemini_config, get_translation_config
    except ImportError as _e:
        logger.error(f"[BRIEF] Failed to import pipeline modules: {_e}")
        sys.exit(1)

    volume_dir = WORK_DIR / args.volume
    if not volume_dir.exists():
        logger.error(f"[BRIEF] Volume directory not found: {volume_dir}")
        sys.exit(1)

    manifest_path = volume_dir / "manifest.json"
    if not manifest_path.exists():
        logger.error(f"[BRIEF] No manifest.json found for volume: {args.volume}")
        logger.error("  Please run Phase 1 and Phase 1.5 first.")
        sys.exit(1)

    try:
        with open(manifest_path, "r", encoding="utf-8") as _f:
            manifest = json.load(_f)
    except Exception as _e:
        logger.error(f"[BRIEF] Failed to load manifest: {_e}")
        sys.exit(1)

    # Build Gemini Flash client (same pattern as chapter_summarizer)
    gemini_config  = get_gemini_config()
    trans_config   = get_translation_config()
    model = (
        trans_config.get("chapter_summarizer_model")
        or gemini_config.get("fallback_model")
        or "gemini-2.5-flash"
    )

    try:
        gemini_client = GeminiClient(
            api_key=gemini_config.get("api_key"),
            model=model,
        )
    except Exception as _e:
        logger.error(f"[BRIEF] Failed to initialise Gemini client: {_e}")
        sys.exit(1)

    brief_agent = AnthropicTranslationBriefAgent(
        gemini_client=gemini_client,
        work_dir=volume_dir,
        manifest=manifest,
        model=model,
    )

    result = brief_agent.generate_brief(force=args.force)

    if result.success:
        action = "Loaded from cache" if result.cached else "Generated"
        logger.info(
            f"[BRIEF] ✓ {action}: {len(result.brief_text):,} chars → {result.brief_path}"
        )
        sys.exit(0)
    else:
        logger.error(f"[BRIEF] ✗ Brief generation failed: {result.error}")
        sys.exit(1)


if __name__ == "__main__":
    main()

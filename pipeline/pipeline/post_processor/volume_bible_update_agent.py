"""
Volume Bible Update Agent (Phase 2.5)

Post-QC full-volume synthesis step that updates bible voice fields and writes
local translation decisions for next-volume continuity.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from pipeline.common.name_order_normalizer import (
    build_name_order_replacement_map,
    normalize_payload_names,
)

logger = logging.getLogger(__name__)


@dataclass
class VolumeBibleUpdateResult:
    success: bool
    voice_profiles_added: int = 0
    decisions_written: int = 0
    continuity_pack_path: Optional[Path] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        if not self.success:
            return f"failed: {self.error or 'unknown error'}"
        return (
            f"voice_profiles={self.voice_profiles_added}, "
            f"decisions={self.decisions_written}, "
            f"pack={self.continuity_pack_path.name if self.continuity_pack_path else 'none'}"
        )


class VolumeBibleUpdateAgent:
    """Post-translation bible synthesis pass (runs once per volume)."""

    def __init__(
        self,
        gemini_client,
        bible_sync,
        work_dir: Path,
        model: str = "gemini-2.5-pro",
        max_output_tokens: int = 65535,
    ):
        self.client = gemini_client
        self.bible_sync = bible_sync
        self.work_dir = work_dir
        self.model = model
        self.max_output_tokens = max_output_tokens

    def run(
        self,
        en_dir: Path,
        manifest: Dict[str, Any],
        qc_cleared: bool = False,
        target_language: str = "en",
    ) -> VolumeBibleUpdateResult:
        if not qc_cleared:
            return VolumeBibleUpdateResult(
                success=False,
                error="qc_not_cleared",
            )

        try:
            self._normalize_bible_name_order(manifest)
            full_volume_text = self._load_full_volume(en_dir)
            if not full_volume_text.strip():
                return VolumeBibleUpdateResult(success=False, error="empty_en_volume")

            update_payload = self._synthesize_bible_update(
                full_volume_text=full_volume_text,
                manifest=manifest,
                target_language=target_language,
            )
            if not isinstance(update_payload, dict):
                update_payload = {}

            voice_profiles = update_payload.get("character_voices", {})
            arc_resolution = str(update_payload.get("arc_resolution", "")).strip()
            push_result = self.bible_sync.push_extended(
                manifest=manifest,
                voice_profiles=voice_profiles if isinstance(voice_profiles, dict) else {},
                arc_resolution=arc_resolution,
            )

            decisions = update_payload.get("translation_decisions", {})
            written = self._write_local_translation_decisions(
                decisions=decisions if isinstance(decisions, dict) else {},
                target_language=target_language,
            )
            continuity_pack_path = self._write_continuity_pack(
                bible_update=update_payload,
                push_summary=push_result.summary(),
            )

            return VolumeBibleUpdateResult(
                success=True,
                voice_profiles_added=push_result.characters_enriched,
                decisions_written=written,
                continuity_pack_path=continuity_pack_path,
                metadata={"push_summary": push_result.summary()},
            )
        except Exception as exc:
            logger.exception("[PHASE 2.5] Volume bible update failed: %s", exc)
            return VolumeBibleUpdateResult(success=False, error=str(exc))

    def _normalize_bible_name_order(self, manifest: Dict[str, Any]) -> None:
        """Normalize loaded bible names to the local manifest's name-order policy."""
        bible = getattr(self.bible_sync, "bible", None)
        if bible is None:
            return

        replacements = build_name_order_replacement_map(manifest)
        if not replacements:
            return

        original_data = getattr(bible, "data", None)
        if not isinstance(original_data, dict):
            return

        original_text = json.dumps(original_data, ensure_ascii=False, sort_keys=True)
        replacement_count = sum(original_text.count(wrong) for wrong in replacements)
        if replacement_count <= 0:
            logger.info("[PHASE 2.5][NAME-ORDER] Bible already matches local manifest policy")
            return

        normalized_data = normalize_payload_names(original_data, manifest)
        normalized_text = json.dumps(normalized_data, ensure_ascii=False, sort_keys=True)
        if normalized_text == original_text:
            logger.info("[PHASE 2.5][NAME-ORDER] Bible already matches local manifest policy")
            return

        bible.data = normalized_data
        bible.save()
        logger.info(
            "[PHASE 2.5][NAME-ORDER] Normalized existing bible from local manifest policy: replacements=%s",
            replacement_count,
        )

    def _load_full_volume(self, en_dir: Path) -> str:
        files = sorted(
            en_dir.glob("*.md"),
            key=self._chapter_sort_key,
        )
        chunks = []
        for path in files:
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            if text.strip():
                chunks.append(f"\n\n# {path.name}\n\n{text.strip()}")
        return "".join(chunks)

    def _chapter_sort_key(self, path: Path):
        m = re.search(r"(?:chapter[_\-\s]*)(\d+)", path.stem, re.IGNORECASE)
        if m:
            return (0, int(m.group(1)))
        return (1, path.name.lower())

    def _synthesize_bible_update(self, full_volume_text: str, manifest: Dict[str, Any],
                                 target_language: str = "en") -> Dict[str, Any]:
        prompt = self._build_synthesis_prompt(
            full_volume_text=full_volume_text, manifest=manifest,
            target_language=target_language,
        )
        response = self.client.generate(
            prompt=prompt,
            temperature=0.2,
            max_output_tokens=self.max_output_tokens,
            model=self.model,
        )
        content = getattr(response, "content", "") if response is not None else ""
        return self._parse_update_json(content)

    def _build_synthesis_prompt(self, full_volume_text: str, manifest: Dict[str, Any],
                                target_language: str = "en") -> str:
        volume_id = manifest.get("volume_id", "")
        base_prompt = (
            "You are updating a long-running translation bible.\n"
            "Return STRICT JSON only with keys: character_voices, translation_decisions, arc_resolution.\n"
            "character_voices maps canonical character names to: voice_register, speech_patterns, "
            "established_nicknames, translation_notes.\n"
            "translation_decisions maps JP terms to established target-language renderings.\n"
        )
        if target_language in ("vn", "vi"):
            base_prompt += (
                "\nFor VN target: also include character_relationship_states inside translation_decisions.\n"
                "character_relationship_states maps character dyads (e.g. '有咲→真白') to:\n"
                "  jp_state: JP relationship descriptor (e.g. '確立したカップル')\n"
                "  source: volume/chapter where state was established\n"
                "  default_pair: PAIR_ID (PAIR_0=formal, PAIR_1=acquaintance, PAIR_2=close_friends, "
                "PAIR_3=romantic, PAIR_FAM=family)\n"
            )
        base_prompt += (
            f"\nVolume ID: {volume_id}\n\n"
            "EN VOLUME TEXT:\n"
            f"{full_volume_text}"
        )
        return base_prompt

    def _parse_update_json(self, content: str) -> Dict[str, Any]:
        text = str(content or "").strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except Exception:
            pass
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            logger.warning("[PHASE 2.5] Could not parse JSON response")
            return {}
        try:
            return json.loads(match.group(0))
        except Exception:
            logger.warning("[PHASE 2.5] Failed to parse extracted JSON block")
            return {}

    def _write_local_translation_decisions(self, decisions: Dict[str, Any], target_language: str) -> int:
        context_dir = self.work_dir / ".context"
        context_dir.mkdir(parents=True, exist_ok=True)
        path = context_dir / "translation_decisions.json"

        existing: Dict[str, Any] = {}
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}

        if target_language in decisions and isinstance(decisions.get(target_language), dict):
            lang_decisions = decisions.get(target_language, {})
        else:
            lang_decisions = decisions
        if not isinstance(lang_decisions, dict):
            lang_decisions = {}

        # Separate simple key-value pairs from nested structures (e.g., character_relationship_states)
        clean = {}
        nested_structures = {}
        for k, v in lang_decisions.items():
            key = str(k).strip()
            if not key:
                continue
            # Preserve nested dicts (like character_relationship_states) as-is
            if isinstance(v, dict):
                nested_structures[key] = v
            elif isinstance(v, str) and v.strip():
                clean[key] = v.strip()
            elif v:  # truthy non-string
                clean[key] = str(v)

        # Merge simple decisions (flat key-value)
        merged = dict(existing.get(target_language, {}))
        merged.update(clean)

        # Preserve and merge nested structures (don't overwrite, merge recursively)
        for ns_key, ns_value in nested_structures.items():
            if ns_key in merged and isinstance(merged[ns_key], dict):
                merged[ns_key].update(ns_value)
            else:
                merged[ns_key] = ns_value

        existing[target_language] = merged
        path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")

        total_entries = len(clean) + sum(len(v) for v in nested_structures.values() if isinstance(v, dict))
        logger.info(
            f"[PHASE 2.5] Translation decisions written: {total_entries} entries ({target_language})"
        )
        return total_entries

    def _write_continuity_pack(self, bible_update: Dict[str, Any], push_summary: str) -> Path:
        context_dir = self.work_dir / ".context"
        context_dir.mkdir(parents=True, exist_ok=True)
        pack_path = context_dir / "continuity_pack.json"
        payload = {
            "schema_version": "3.0",
            "generated_at": datetime.now().isoformat(),
            "source": "VolumeBibleUpdateAgent (Phase 2.5)",
            "bible_update": bible_update,
            "push_summary": push_summary,
        }
        pack_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(f"[PHASE 2.5] Continuity pack written: {pack_path}")
        return pack_path


def main() -> None:
    """Standalone subprocess entry point for Phase 2.5."""
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
        force=True,
    )

    parser = argparse.ArgumentParser(
        description="Phase 2.5: Volume Bible Update (post-translation continuity synthesis)"
    )
    parser.add_argument("--volume", required=True, help="Volume ID (directory name inside WORK/)")
    parser.add_argument(
        "--qc-cleared",
        action="store_true",
        help="Mark this run as QC-cleared (recommended)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass QC gate and run anyway (advanced)",
    )
    parser.add_argument(
        "--target-language",
        default="",
        help="Target language code for EN directory selection (default: config target language)",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Override synthesis model (default: translation.phase_2_5.model)",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=0,
        help="Override max output tokens (default: translation.phase_2_5.max_output_tokens)",
    )
    args = parser.parse_args()

    try:
        from pipeline.config import WORK_DIR, PIPELINE_ROOT, get_target_language
        from pipeline.translator.config import get_translation_config, get_gemini_config
        from pipeline.common.phase_llm_router import PhaseLLMRouter
        from pipeline.metadata_processor.bible_sync import BibleSyncAgent
    except Exception as exc:
        logger.error(f"[PHASE 2.5] Import failure: {exc}")
        sys.exit(1)

    volume_dir = WORK_DIR / args.volume
    if not volume_dir.exists():
        logger.error(f"[PHASE 2.5] Volume directory not found: {volume_dir}")
        sys.exit(1)

    manifest_path = volume_dir / "manifest.json"
    if not manifest_path.exists():
        logger.error(f"[PHASE 2.5] No manifest.json found for volume: {args.volume}")
        logger.error("  Please run Phase 1 and Phase 2 first")
        sys.exit(1)

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error(f"[PHASE 2.5] Failed to load manifest: {exc}")
        sys.exit(1)

    translation_cfg = get_translation_config()
    phase25_cfg = translation_cfg.get("phase_2_5", {})
    if not isinstance(phase25_cfg, dict):
        phase25_cfg = {}

    target_language = str(args.target_language or get_target_language()).strip().lower() or "en"
    explicit_target_language = bool(str(args.target_language or "").strip())
    qc_default = bool(phase25_cfg.get("qc_cleared", False))
    qc_gate = bool(args.qc_cleared or qc_default or args.force)
    if not qc_gate:
        logger.error(
            "[PHASE 2.5] QC gate blocked run. Set translation.phase_2_5.qc_cleared=true "
            "or pass --qc-cleared (or --force for override)."
        )
        sys.exit(1)
    if args.force and not args.qc_cleared and not qc_default:
        logger.warning("[PHASE 2.5] Running with --force (QC gate bypassed).")

    gemini_cfg = get_gemini_config()
    model = str(args.model or phase25_cfg.get("model") or gemini_cfg.get("model") or "gemini-2.5-pro")
    max_output_tokens = int(
        args.max_output_tokens
        or phase25_cfg.get("max_output_tokens")
        or 65535
    )

    try:
        gemini_client = PhaseLLMRouter().get_client(
            "2.5",
            api_key=gemini_cfg.get("api_key"),
            model=model,
        )
    except Exception as exc:
        logger.error(f"[PHASE 2.5] Failed to initialize Gemini client: {exc}")
        sys.exit(1)

    bible_sync = BibleSyncAgent(volume_dir, PIPELINE_ROOT)
    if not bible_sync.resolve(manifest):
        logger.error("[PHASE 2.5] No series bible resolved for this volume")
        sys.exit(1)

    requested_dir = volume_dir / target_language.upper()
    en_dir = requested_dir
    if not requested_dir.exists():
        fallback_candidates = [volume_dir / "EN", volume_dir / "VN"]
        fallback_candidates = [path for path in fallback_candidates if path.exists()]
        if fallback_candidates:
            en_dir = fallback_candidates[0]
            resolved_lang = en_dir.name.lower()
            if explicit_target_language:
                logger.warning(
                    "[PHASE 2.5] Target folder missing: %s. Falling back to %s/",
                    requested_dir.name,
                    en_dir.name,
                )
            else:
                logger.info(
                    "[PHASE 2.5] Auto-detected output folder: %s/ "
                    "(configured target %s missing)",
                    en_dir.name,
                    requested_dir.name,
                )
            target_language = resolved_lang
        else:
            logger.error(f"[PHASE 2.5] Output directory not found: {requested_dir}")
            sys.exit(1)

    agent = VolumeBibleUpdateAgent(
        gemini_client=gemini_client,
        bible_sync=bible_sync,
        work_dir=volume_dir,
        model=model,
        max_output_tokens=max_output_tokens,
    )
    result = agent.run(
        en_dir=en_dir,
        manifest=manifest,
        qc_cleared=qc_gate,
        target_language=target_language,
    )
    if result.success:
        logger.info(f"[PHASE 2.5] ✓ Completed: {result.summary()}")
        sys.exit(0)

    logger.error(f"[PHASE 2.5] ✗ Failed: {result.summary()}")
    sys.exit(1)


if __name__ == "__main__":
    main()

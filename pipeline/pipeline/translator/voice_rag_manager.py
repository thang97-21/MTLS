"""
Voice Consistency RAG Manager — Phase 1 of Koji Fox Expansion

Indexes character voice fingerprints from manifest metadata and retrieves
voice directives for injection into the translator's thinking block.

Architecture:
  - Indexing: Load character_voice_fingerprints from manifest metadata_en
  - Storage: ChromaDB (with JSON fallback if ChromaDB unavailable)
  - Retrieval: Query by character name + chapter EPS band
  - Injection: Format as CHARACTER VOICE DIRECTIVE block for <thinking>
"""

import json
import logging
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# ChromaDB optional dependency
try:
    import chromadb
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    logger.debug("ChromaDB not available — using JSON fallback for voice RAG")


# EPS band → voice modifier mapping (replaces RTAS_VOICE_MODIFIERS)
EPS_BAND_VOICE_MODIFIERS = {
    "COLD":    ["minimal emotional expression", "deflects with silence or bluntness", "formal register"],
    "COOL":    ["polite distance", "controlled warmth", "short answers"],
    "NEUTRAL": ["character baseline", "consistent with archetype"],
    "WARM":    ["casual intimacy", "relaxed formality", "occasional warmth"],
    "HOT":     ["genuine emotional expression", "longer sentences", "direct statements", "vulnerable"],
}


class VoiceRAGManager:
    """
    Manages character voice fingerprint indexing and retrieval.

    Reads character_voice_fingerprints from manifest metadata_en (populated
    by the metadata processor's Koji Fox extraction) and provides formatted
    voice directives for the translator's thinking block.

    Usage:
        manager = VoiceRAGManager(work_dir)
        manager.index_from_manifest()
        directive = manager.get_voice_directive(["Tanaka", "Kurosawa"], chapter_num=3)
    """

    EPS_BAND_VOICE_MODIFIERS = EPS_BAND_VOICE_MODIFIERS

    def __init__(self, work_dir: Path):
        self.work_dir = work_dir
        self.context_dir = work_dir / ".context" / "voice_rag"
        self.context_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.context_dir / "voice_index.json"
        self._index: Dict[str, Dict] = {}  # canonical_name_en → fingerprint
        self._alias_index: Dict[str, Dict] = {}
        self._loaded = False

    # ─── Indexing ────────────────────────────────────────────────────────────

    def index_from_manifest(self) -> int:
        """
        Load character_voice_fingerprints from manifest.json metadata_en.
        Returns number of characters indexed.
        """
        manifest_path = self.work_dir / "manifest.json"
        if not manifest_path.exists():
            logger.warning("manifest.json not found — voice RAG empty")
            return 0

        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

        fingerprints = (
            manifest.get("metadata_en", {}).get("character_voice_fingerprints")
            or manifest.get("metadata_vn", {}).get("character_voice_fingerprints")
            or []
        )

        if not fingerprints:
            logger.info("No character_voice_fingerprints in manifest — voice RAG empty")
            return 0

        self._index = {}
        self._alias_index = {}
        for fp in fingerprints:
            name = fp.get("canonical_name_en", "").strip()
            if name:
                self._index[name.lower()] = fp

        self._rebuild_alias_index()
        self._save_index()
        self._loaded = True
        logger.info(f"Voice RAG indexed {len(self._index)} character(s)")
        return len(self._index)

    def load_index(self) -> bool:
        """Load previously saved index from disk."""
        if not self.index_path.exists():
            return False
        with open(self.index_path, encoding="utf-8") as f:
            self._index = json.load(f)
        self._rebuild_alias_index()
        self._loaded = bool(self._index)
        return self._loaded

    def _save_index(self) -> None:
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(self._index, f, indent=2, ensure_ascii=False)

    def _rebuild_alias_index(self) -> None:
        self._alias_index = {}
        for fp in self._index.values():
            for alias in self._iter_fingerprint_aliases(fp):
                normalized = self._normalize_name(alias)
                if normalized and normalized not in self._alias_index:
                    self._alias_index[normalized] = fp

    # ─── Retrieval ───────────────────────────────────────────────────────────

    def get_fingerprint(self, character_name: str) -> Optional[Dict]:
        """Return voice fingerprint for a character, tolerating common alias drift."""
        if not self._loaded:
            self.load_index()
        if not character_name:
            return None

        direct = self._index.get(character_name.lower())
        if direct:
            return direct

        normalized_query = self._normalize_name(character_name)
        if not normalized_query:
            return None
        alias_match = self._alias_index.get(normalized_query)
        if alias_match:
            return alias_match

        for alias_candidate in self._extract_parenthetical_aliases(character_name):
            alias_fp = self.get_fingerprint(alias_candidate)
            if alias_fp:
                return alias_fp

        all_fingerprints = self.all_fingerprints()
        token_counts: Dict[str, int] = {}
        for fp in all_fingerprints:
            for lookup_name in self._build_lookup_names(fp, {}):
                for token in lookup_name.split():
                    token_counts[token] = token_counts.get(token, 0) + 1

        best_fp: Optional[Dict] = None
        best_candidate = ""
        best_score = 0.0
        second_best = 0.0

        for fp in all_fingerprints:
            for candidate in self._build_lookup_names(fp, token_counts):
                if normalized_query == candidate:
                    return fp
                score = self._name_similarity(normalized_query, candidate)
                if score > best_score:
                    second_best = best_score
                    best_score = score
                    best_fp = fp
                    best_candidate = candidate
                elif score > second_best:
                    second_best = score

        if best_fp and self._accept_fuzzy_match(
            normalized_query,
            best_candidate,
            best_score,
            second_best,
        ):
            logger.debug(
                "Voice RAG fuzzy-resolved '%s' -> '%s' (score=%.2f)",
                character_name,
                best_fp.get("canonical_name_en", ""),
                best_score,
            )
            return best_fp
        return None

    def all_fingerprints(self) -> List[Dict]:
        """Return unique canonical fingerprints from the loaded index."""
        if not self._loaded:
            self.load_index()
        deduped: List[Dict] = []
        seen = set()
        for fp in self._index.values():
            canonical = str(fp.get("canonical_name_en", "")).strip().lower()
            key = canonical or json.dumps(fp, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(fp)
        return deduped

    @staticmethod
    def _normalize_name(value: Any) -> str:
        text = str(value or "").strip().lower()
        text = re.sub(r"\([^)]*\)", " ", text)
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return " ".join(part for part in text.split() if part)

    @classmethod
    def _iter_fingerprint_aliases(cls, fp: Dict[str, Any]) -> List[str]:
        aliases: List[str] = []

        def add(value: Any) -> None:
            text = str(value or "").strip()
            if text and text not in aliases:
                aliases.append(text)

        add(fp.get("canonical_name_en", ""))
        for key in ("full_name", "nickname", "display_name", "short_name"):
            add(fp.get(key))
        raw_aliases = fp.get("name_aliases", [])
        if isinstance(raw_aliases, list):
            for alias in raw_aliases:
                add(alias)
        return aliases

    @classmethod
    def _extract_parenthetical_aliases(cls, value: Any) -> List[str]:
        text = str(value or "").strip()
        aliases: List[str] = []
        for match in re.findall(r"\(([^)]+)\)", text):
            alias = match.strip()
            if alias and alias not in aliases:
                aliases.append(alias)
        return aliases

    @classmethod
    def _build_lookup_names(cls, fp: Dict[str, Any], token_counts: Dict[str, int]) -> List[str]:
        candidates = set()
        for alias in cls._iter_fingerprint_aliases(fp):
            normalized = cls._normalize_name(alias)
            if not normalized:
                continue
            candidates.add(normalized)
            tokens = normalized.split()
            if len(tokens) >= 2:
                candidates.add(" ".join(reversed(tokens)))
            for token in tokens:
                if len(token) >= 3 and token_counts.get(token, 0) in {0, 1}:
                    candidates.add(token)
        return [candidate for candidate in candidates if candidate]

    @staticmethod
    def _accept_fuzzy_match(
        normalized_query: str,
        best_candidate: str,
        best_score: float,
        second_best: float,
    ) -> bool:
        if best_score >= 0.82 and (best_score - second_best >= 0.05 or best_score >= 0.92):
            return True

        query_tokens = normalized_query.split()
        candidate_tokens = best_candidate.split()
        if len(query_tokens) == 1 and len(candidate_tokens) == 1:
            if best_score >= 0.78 and second_best <= 0.60:
                return True
            if (
                best_score >= 0.72
                and abs(len(query_tokens[0]) - len(candidate_tokens[0])) <= 2
                and second_best <= 0.50
            ):
                return True
        return False

    @staticmethod
    def _name_similarity(left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        ratio = SequenceMatcher(None, left, right).ratio()
        left_tokens = set(left.split())
        right_tokens = set(right.split())
        if left_tokens and right_tokens:
            overlap = len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))
            ratio = max(ratio, (ratio * 0.65) + (overlap * 0.35))
        return ratio

    def get_voice_directive(
        self,
        character_names: List[str],
        eps_data: Optional[Dict[str, Dict]] = None,
        chapter_num: int = 0,
    ) -> str:
        """
        Build a CHARACTER VOICE DIRECTIVE block for injection into <thinking>.

        Args:
            character_names: List of character names appearing in this chunk
            eps_data: Dict of character_name → {eps_score, voice_band, signals} for this chapter
            chapter_num: Current chapter number (for context)

        Returns:
            Formatted directive string, or empty string if no data available
        """
        if not self._loaded:
            self.load_index()

        if not self._index:
            return ""

        eps_data = eps_data or {}
        lines = ["## CHARACTER VOICE DIRECTIVE"]

        found_any = False
        for name in character_names:
            fp = self.get_fingerprint(name)
            if not fp:
                continue
            found_any = True

            archetype = fp.get("archetype", "unknown")
            contraction = fp.get("contraction_rate", "?")
            sentence_bias = fp.get("sentence_length_bias", "medium")
            forbidden = fp.get("forbidden_vocabulary", [])
            signature = fp.get("signature_phrases", [])
            verbal_tics = fp.get("verbal_tics", [])

            # Get EPS data for this character
            char_eps = eps_data.get(name, eps_data.get(name.lower(), {}))
            eps_score = char_eps.get("eps_score", 0.0) if isinstance(char_eps, dict) else 0.0
            voice_band = char_eps.get("voice_band", "NEUTRAL") if isinstance(char_eps, dict) else "NEUTRAL"
            eps_mods = self.EPS_BAND_VOICE_MODIFIERS.get(voice_band, [])

            lines.append(f"\nCharacter: {name}")
            lines.append(f"  Archetype: {archetype}")
            lines.append(f"  Contraction rate: {int(float(contraction) * 100) if isinstance(contraction, (int, float)) else contraction}%")
            lines.append(f"  Sentence bias: {sentence_bias}")

            # Add EPS-based voice guidance
            lines.append(f"  EPS: {eps_score:+.2f} [{voice_band}]")
            if eps_mods:
                lines.append(f"  Voice modifiers: {', '.join(eps_mods[:2])}")

            if forbidden:
                quoted = [f'"{w}"' for w in forbidden[:5]]
                lines.append(f"  Forbidden: {', '.join(quoted)}")

            if signature:
                quoted = [f'"{p}"' for p in signature[:3]]
                lines.append(f"  Signature: {', '.join(quoted)}")

            if verbal_tics:
                lines.append(f"  Verbal tics: {', '.join(verbal_tics[:3])}")

        if not found_any:
            return ""

        return "\n".join(lines)

    def get_scene_intent(self, chapter_id: str, manifest: Optional[Dict] = None) -> str:
        """
        Retrieve scene intent directives for a chapter from manifest scene_intent_map.

        Returns formatted SCENE INTENT block or empty string.
        """
        if manifest is None:
            manifest_path = self.work_dir / "manifest.json"
            if not manifest_path.exists():
                return ""
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)

        scene_map = (
            manifest.get("metadata_en", {}).get("scene_intent_map")
            or manifest.get("metadata_vn", {}).get("scene_intent_map")
            or []
        )

        for entry in scene_map:
            if entry.get("chapter_id") == chapter_id:
                scenes = entry.get("scenes", [])
                if not scenes:
                    return ""
                lines = ["## SCENE INTENT MAP"]
                for scene in scenes:
                    primary = scene.get("primary_intent", "")
                    secondary = scene.get("secondary_intents", [])
                    goal = scene.get("emotional_goal", "")
                    loc = scene.get("location", "")
                    if primary:
                        intent_str = primary
                        if secondary:
                            intent_str += f" + {', '.join(secondary)}"
                        lines.append(f"  [{loc}] {intent_str}: {goal}")
                return "\n".join(lines)

        return ""

    def extract_characters_from_jp(self, jp_text: str, manifest: Optional[Dict] = None) -> List[str]:
        """
        Scan JP source chunk for character names that have voice fingerprints.
        Returns list of canonical EN names found.
        """
        if not self._loaded:
            self.load_index()

        if not self._index:
            return []

        # Load JP→EN name mapping from manifest
        jp_to_en: Dict[str, str] = {}
        if manifest is None:
            manifest_path = self.work_dir / "manifest.json"
            if manifest_path.exists():
                with open(manifest_path, encoding="utf-8") as f:
                    manifest = json.load(f)

        if manifest:
            char_names = (
                manifest.get("metadata_en", {}).get("character_names")
                or manifest.get("metadata_vn", {}).get("character_names")
                or {}
            )
            jp_to_en = {jp: en for jp, en in char_names.items()}

        found = []
        for jp_name, en_name in jp_to_en.items():
            if jp_name in jp_text and en_name.lower() in self._index:
                found.append(en_name)

        return found

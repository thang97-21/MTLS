"""
SeriesBibleRAG — Per-chapter prose passage retrieval from prior volumes.
=======================================================================

Availability: Ships now at 200K. No 1M gate.

Architecture:
  ChromaDB index:  PIPELINE_ROOT/chroma_series_bible/<series_id>/
  Build index:     ./mtl index-series-bible <series_id>
  Per chapter:     Two-phase retrieval → injectable block (~30-60K chars)

  Phase 1 – Term-triggered:
    Find known bible JP terms in the current chapter source.
    Query index for passages from prior volumes where those terms appear.

  Phase 2 – Semantic:
    Embed the first ~2000 chars of the current chapter.
    Retrieve top-k most similar passages from prior volumes.

  Combined, deduplicated, budget-trimmed → injected via _inject_before_source.

Relationship with the flat JSON bible:
  The flat JSON bible (prompt_loader.set_series_bible_prompt) stays COMPLETELY
  UNCHANGED. It handles world_setting directives, honorifics mode, name_order
  policy, EPS arc states, and glossary dedup keys — all cached in Block 0.

  SeriesBibleRAG is ADDITIVE. It provides prose context (character voice samples,
  motif instances, recurring metaphors, scene rhythm) that the glossary cannot.

At 1M:
  Same index, same class. Agent passes volume_id_exclude=N-1 so the current
  volume's prequel (already hot-cached in Block 1) isn't duplicated in the
  user message. No index rebuild needed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

COLLECTION_NAME = "series_bible_passages"

# Lower threshold than general pattern stores: prose passages are thematically
# broader, so we accept a wider semantic match.
THRESHOLD_RETRIEVE = 0.52          # Semantic phase minimum similarity
THRESHOLD_TERM_TRIGGERED = 0.40    # Term-triggered phase: the term hit IS the signal

BOOST_LOCATION_OVERLAP = 0.06
BOOST_POI_OVERLAP = 0.05
BOOST_CALLBACK_OVERLAP = 0.12
BOOST_POV_SIGNATURE_MATCH = 0.10
BOOST_ECR_ARCHETYPE_MATCH = 0.08  # ECR: archetype label appears in both source and prior-volume passage

MAX_INJECT_PASSAGES = 40           # Hard cap: total passages returned
INJECT_BUDGET_CHARS = 60_000       # ~1/3 of 200K user-message budget

LOCATION_SUFFIXES = (
    "城", "王都", "帝都", "都", "都市", "村", "町", "街", "国", "領", "宮",
    "宮殿", "神殿", "砦", "塔", "森", "山", "川", "湖", "海", "港", "駅",
    "学院", "学園", "寮", "館", "邸", "通り", "広場", "市場", "ダンジョン", "迷宮",
)

POI_SUFFIXES = (
    "剣", "槍", "弓", "短剣", "刀", "杖", "宝石", "紋章", "指輪", "首飾り", "腕輪",
    "聖杯", "聖印", "しおり", "鍵", "鍵束", "地図", "巻物", "日記", "手紙", "書簡",
    "証", "証明", "遺物", "遺産", "印", "加護", "呪文", "魔法", "竜具",
)


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class BiblePassage:
    """A single prose passage retrieved from a prior volume's index."""
    passage_id: str
    text: str
    volume_id: str
    chapter_id: str
    passage_type: str      # "term_triggered" | "semantic"
    terms_found: List[str] = field(default_factory=list)
    location_terms: List[str] = field(default_factory=list)
    poi_terms: List[str] = field(default_factory=list)
    callback_phrases: List[str] = field(default_factory=list)
    similarity: float = 0.0
    adjusted_score: float = 0.0


# ── Main class ───────────────────────────────────────────────────────────────

class SeriesBibleRAG:
    """
    Retrieves contextually relevant prose passages from prior volumes of the
    same series, anchored by the series bible's JP term glossary.

    Usage (in chapter_processor.py):
        rag = SeriesBibleRAG(series_id, PIPELINE_ROOT)
        passages = rag.retrieve_for_chapter(jp_source, bible_glossary)
        block = rag.format_for_prompt(passages)
        _inject_before_source(block, "SERIES CONTINUITY RAG CONTEXT")
    """

    def __init__(self, series_id: str, pipeline_root: Path) -> None:
        self.series_id = series_id
        self.pipeline_root = pipeline_root
        self._store = None
        self._init_store()

    # ── Initialization ────────────────────────────────────────────────────────

    def _init_store(self) -> None:
        index_dir = self.pipeline_root / f"chroma_series_bible/{self.series_id}"
        if not index_dir.exists():
            logger.warning(
                f"[BIBLE-RAG] Index not found: {index_dir}. "
                f"Run: ./mtl index-series-bible {self.series_id}"
            )
            return
        try:
            from modules.vector_search import PatternVectorStore
            self._store = PatternVectorStore(
                persist_directory=str(index_dir),
                collection_name=COLLECTION_NAME,
            )
            stats = self._store.get_collection_stats()
            logger.info(
                f"[BIBLE-RAG] Loaded index for {self.series_id!r}: "
                f"{stats['total_patterns']} passages"
            )
        except Exception as exc:
            logger.warning(
                f"[BIBLE-RAG] Failed to initialize store for {self.series_id!r}: {exc}"
            )
            self._store = None

    @property
    def is_available(self) -> bool:
        return self._store is not None

    # ── Core Retrieval ────────────────────────────────────────────────────────

    def retrieve_for_chapter(
        self,
        jp_source: str,
        bible_glossary: Dict[str, str],
        *,
        max_passages: int = MAX_INJECT_PASSAGES,
        volume_id_exclude: Optional[str] = None,
    ) -> List[BiblePassage]:
        """
        Two-phase retrieval for a single chapter.

        Phase 1 — Term-triggered:
            Find JP bible terms present in jp_source.
            Query index for prior-volume passages containing those terms.

        Phase 2 — Semantic:
            Embed the first ~2000 chars of jp_source.
            Retrieve top-k similar passages from the index.

        Args:
            jp_source:         Raw JP chapter text.
            bible_glossary:    Output of SeriesBible.flat_glossary() — JP→EN dict.
            max_passages:      Hard cap on returned passages.
            volume_id_exclude: At 1M, pass the N-1 volume ID to skip it
                               (it lives in Block 1 and doesn't need to be
                               duplicated in the user message).

        Returns:
            Combined, deduplicated, similarity-sorted list of BiblePassages.
        """
        if not self.is_available:
            return []

        seen_ids: Set[str] = set()
        results: List[BiblePassage] = []

        # ── Phase 1: Term-triggered ───────────────────────────────────────────
        terms_in_chapter = self._find_terms_in_source(jp_source, bible_glossary)
        _, source_location_terms, source_poi_terms = self._classify_terms(terms_in_chapter)
        source_callbacks = self._extract_callback_phrases(jp_source)
        source_pov_signature = self._build_pov_signature(jp_source)
        if terms_in_chapter:
            logger.debug(
                f"[BIBLE-RAG] Terms detected in chapter "
                f"({len(terms_in_chapter)}): {terms_in_chapter[:8]!r}"
            )
            # Avoid querying too many terms (each is a separate Chroma call)
            for term in terms_in_chapter[:20]:
                try:
                    hits = self._store.search(query=term, top_k=4) # type: ignore
                    for hit in hits:
                        pid = hit["pattern_id"]
                        if pid in seen_ids:
                            continue
                        meta = hit.get("metadata", {})
                        if volume_id_exclude and meta.get("volume_id") == volume_id_exclude:
                            continue
                        terms_found = self._split_csv(meta.get("terms_found", ""))
                        location_terms = self._split_csv(meta.get("location_terms", ""))
                        poi_terms = self._split_csv(meta.get("poi_terms", ""))
                        callback_phrases = self._split_pipe(meta.get("callback_phrases", ""))
                        adjusted_score = self._apply_continuity_boosts(
                            base_similarity=hit["similarity"],
                            source_location_terms=source_location_terms,
                            source_poi_terms=source_poi_terms,
                            source_callbacks=source_callbacks,
                            source_pov_signature=source_pov_signature,
                            hit_location_terms=location_terms,
                            hit_poi_terms=poi_terms,
                            hit_callbacks=callback_phrases,
                            hit_pov_signature=meta.get("pov_signature", ""),
                            source_ecr_terms=set(terms_in_chapter),
                            hit_text=hit.get("document", ""),
                        )
                        if adjusted_score < THRESHOLD_TERM_TRIGGERED:
                            continue
                        seen_ids.add(pid)
                        results.append(BiblePassage(
                            passage_id=pid,
                            text=hit.get("document", ""),
                            volume_id=meta.get("volume_id", ""),
                            chapter_id=meta.get("chapter_id", ""),
                            passage_type="term_triggered",
                            terms_found=terms_found,
                            location_terms=location_terms,
                            poi_terms=poi_terms,
                            callback_phrases=callback_phrases,
                            similarity=hit["similarity"],
                            adjusted_score=adjusted_score,
                        ))
                except Exception as exc:
                    logger.debug(
                        f"[BIBLE-RAG] Term-triggered search failed for {term!r}: {exc}"
                    )

        # ── Phase 2: Semantic ─────────────────────────────────────────────────
        try:
            anchor = jp_source[:2000].strip()
            if anchor:
                hits = self._store.search(query=anchor, top_k=max_passages) # type: ignore
                for hit in hits:
                    pid = hit["pattern_id"]
                    if pid in seen_ids:
                        continue
                    meta = hit.get("metadata", {})
                    if volume_id_exclude and meta.get("volume_id") == volume_id_exclude:
                        continue
                    terms_found = self._split_csv(meta.get("terms_found", ""))
                    location_terms = self._split_csv(meta.get("location_terms", ""))
                    poi_terms = self._split_csv(meta.get("poi_terms", ""))
                    callback_phrases = self._split_pipe(meta.get("callback_phrases", ""))
                    adjusted_score = self._apply_continuity_boosts(
                        base_similarity=hit["similarity"],
                        source_location_terms=source_location_terms,
                        source_poi_terms=source_poi_terms,
                        source_callbacks=source_callbacks,
                        source_pov_signature=source_pov_signature,
                        hit_location_terms=location_terms,
                        hit_poi_terms=poi_terms,
                        hit_callbacks=callback_phrases,
                        hit_pov_signature=meta.get("pov_signature", ""),
                        source_ecr_terms=set(terms_in_chapter),
                        hit_text=hit.get("document", ""),
                    )
                    if adjusted_score < THRESHOLD_RETRIEVE:
                        continue
                    seen_ids.add(pid)
                    results.append(BiblePassage(
                        passage_id=pid,
                        text=hit.get("document", ""),
                        volume_id=meta.get("volume_id", ""),
                        chapter_id=meta.get("chapter_id", ""),
                        passage_type="semantic",
                        terms_found=terms_found,
                        location_terms=location_terms,
                        poi_terms=poi_terms,
                        callback_phrases=callback_phrases,
                        similarity=hit["similarity"],
                        adjusted_score=adjusted_score,
                    ))
        except Exception as exc:
            logger.debug(f"[BIBLE-RAG] Semantic search failed: {exc}")

        # Sort by similarity, apply cap
        results.sort(key=lambda p: p.adjusted_score or p.similarity, reverse=True)
        return results[:max_passages]

    # ── Prompt Formatting ─────────────────────────────────────────────────────

    def format_for_prompt(
        self,
        passages: List[BiblePassage],
        budget_chars: int = INJECT_BUDGET_CHARS,
    ) -> str:
        """
        Format retrieved passages as an injectable prompt block.

        Passages are grouped by prior volume for readability and trimmed to
        budget_chars. Returns empty string if no passages.
        """
        if not passages:
            return ""

        # Group by volume
        by_volume: Dict[str, List[BiblePassage]] = {}
        for p in passages:
            by_volume.setdefault(p.volume_id, []).append(p)

        lines: List[str] = [
            "=== SERIES CONTINUITY CONTEXT (from prior volumes) ===",
            (
                "The following passages are from earlier volumes of this series. "
                "Use them to calibrate character voice, recurring motifs, established "
                "register, and terminology. DO NOT retranslate — reference only."
            ),
            "",
        ]
        total_chars = sum(len(ln) + 1 for ln in lines)

        for vol_id, vol_passages in by_volume.items():
            header = f"--- Prior Volume: {vol_id} ---"
            if total_chars + len(header) + 2 > budget_chars:
                break
            lines.append(header)
            total_chars += len(header) + 1

            for p in vol_passages:
                text = (p.text or "").strip()
                if not text:
                    continue
                meaningful_terms = [t for t in p.terms_found if t.strip()]
                terms_tag = (
                    f" [terms: {', '.join(meaningful_terms[:5])}]"
                    if meaningful_terms else ""
                )
                location_tag = (
                    f" [loc: {', '.join(p.location_terms[:3])}]"
                    if p.location_terms else ""
                )
                poi_tag = (
                    f" [poi: {', '.join(p.poi_terms[:3])}]"
                    if p.poi_terms else ""
                )
                callback_tag = " [callback]" if p.callback_phrases else ""
                block = f"[{p.chapter_id}{terms_tag}{location_tag}{poi_tag}{callback_tag}]\n{text}"
                if total_chars + len(block) + 3 > budget_chars:
                    break
                lines.append(block)
                lines.append("")
                total_chars += len(block) + 2

        lines.append("=== END SERIES CONTINUITY CONTEXT ===")
        result = "\n".join(lines)

        logger.info(
            f"[BIBLE-RAG] Injecting {len(passages)} passages from "
            f"{len(by_volume)} prior volume(s) ({len(result):,} chars)"
        )
        return result

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _find_terms_in_source(
        jp_source: str,
        bible_glossary: Dict[str, str],
    ) -> List[str]:
        """
        Return all JP glossary terms that appear in jp_source.
        Sorted longest-first so more specific terms take priority.
        """
        found = [
            term for term in bible_glossary
            if term and len(term) >= 2 and term in jp_source
        ]
        found.sort(key=len, reverse=True)
        return found

    @staticmethod
    def _classify_terms(terms: List[str]) -> tuple[List[str], List[str], List[str]]:
        character_terms: List[str] = []
        location_terms: List[str] = []
        poi_terms: List[str] = []

        for term in terms:
            if any(sfx in term for sfx in LOCATION_SUFFIXES):
                location_terms.append(term)
                continue
            if any(sfx in term for sfx in POI_SUFFIXES):
                poi_terms.append(term)
                continue
            character_terms.append(term)

        return character_terms, location_terms, poi_terms

    @staticmethod
    def _extract_callback_phrases(text: str, max_items: int = 8) -> List[str]:
        phrases: List[str] = []
        for phrase in re.findall(r"「([^」]{8,90})」", text):
            cleaned = re.sub(r"\s+", " ", phrase).strip()
            if len(cleaned) >= 8:
                phrases.append(cleaned)

        for phrase in re.findall(r"『([^』]{8,90})』", text):
            cleaned = re.sub(r"\s+", " ", phrase).strip()
            if len(cleaned) >= 8:
                phrases.append(cleaned)

        for phrase in re.findall(r'"([^"\n]{8,120})"', text):
            cleaned = re.sub(r"\s+", " ", phrase).strip()
            if len(cleaned) >= 8:
                phrases.append(cleaned)

        seen: Set[str] = set()
        deduped: List[str] = []
        for phrase in phrases:
            key = phrase.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(phrase)
            if len(deduped) >= max_items:
                break
        return deduped

    @staticmethod
    def _build_pov_signature(text: str, max_sentences: int = 3) -> str:
        raw_sentences = [s.strip() for s in re.split(r"(?<=[。！？!?])", text) if s.strip()]
        signatures: List[str] = []

        for sent in raw_sentences[:max_sentences]:
            length = len(sent)
            if length < 26:
                bucket = "S"
            elif length < 61:
                bucket = "M"
            else:
                bucket = "L"

            quote_flag = "Q" if ("「" in sent or "」" in sent or '"' in sent) else "N"
            tail = sent[-1] if sent else "_"
            flags = f"{int('?' in sent or '？' in sent)}{int('!' in sent or '！' in sent)}"
            signatures.append(f"{bucket}:{quote_flag}:{tail}:{flags}")

        return "|".join(signatures[:max_sentences])

    @staticmethod
    def _split_csv(value: str) -> List[str]:
        if not value:
            return []
        return [v.strip() for v in value.split(",") if v.strip()]

    @staticmethod
    def _split_pipe(value: str) -> List[str]:
        if not value:
            return []
        return [v.strip() for v in value.split("|") if v.strip()]

    @staticmethod
    def _normalize_callback_phrase(phrase: str) -> str:
        return re.sub(r"\s+", "", phrase).lower().strip()

    def _apply_continuity_boosts(
        self,
        *,
        base_similarity: float,
        source_location_terms: List[str],
        source_poi_terms: List[str],
        source_callbacks: List[str],
        source_pov_signature: str,
        hit_location_terms: List[str],
        hit_poi_terms: List[str],
        hit_callbacks: List[str],
        hit_pov_signature: str,
        source_ecr_terms: Optional[Set[str]] = None,
        hit_text: str = "",
    ) -> float:
        score = base_similarity

        if set(source_location_terms) & set(hit_location_terms):
            score += BOOST_LOCATION_OVERLAP
        if set(source_poi_terms) & set(hit_poi_terms):
            score += BOOST_POI_OVERLAP

        source_cb_norm = {self._normalize_callback_phrase(c) for c in source_callbacks if c}
        hit_cb_norm = {self._normalize_callback_phrase(c) for c in hit_callbacks if c}
        if source_cb_norm & hit_cb_norm:
            score += BOOST_CALLBACK_OVERLAP

        if source_pov_signature and hit_pov_signature and source_pov_signature == hit_pov_signature:
            score += BOOST_POV_SIGNATURE_MATCH

        # ECR archetype boost: JP cultural archetype term appears in both
        # the current source chapter AND a prior-volume passage — strong
        # signal that this passage has continuity-relevant cultural context.
        if source_ecr_terms and hit_text:
            if any(term in hit_text for term in source_ecr_terms):
                score += BOOST_ECR_ARCHETYPE_MATCH

        return score

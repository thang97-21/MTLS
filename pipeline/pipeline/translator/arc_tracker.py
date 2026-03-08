"""
Arc Tracker — Phase 2 of Koji Fox Expansion (EPS Update)

Tracks character Emotional Proximity Signal (EPS) evolution across
volumes and chapters. Provides arc-aware voice modifier suggestions for
the translator's thinking block.

EPS: Emotional Proximity Signal (-1.0 COLD to +1.0 HOT)
Derived from raw JP corpus signals: keigo, sentence length, particles, pronouns, dialogue volume, direct address

EPS Bands:
  - COLD (≤-0.5): guarded, formal, minimal
  - COOL (-0.5 to -0.1): reserved, polite
  - NEUTRAL (-0.1 to +0.1): baseline
  - WARM (+0.1 to +0.5): casual, intimate
  - HOT (≥+0.5): open, vulnerable, direct
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

# EPS voice band mapping (for display and validation)
EPS_BANDS = {
    "COLD": (-1.0, -0.5),
    "COOL": (-0.5, -0.1),
    "NEUTRAL": (-0.1, 0.1),
    "WARM": (0.1, 0.5),
    "HOT": (0.5, 1.0),
}

# Signal weights for EPS computation
EPS_SIGNAL_WEIGHTS = {
    "keigo_shift": 0.30,           # Most reliable indicator
    "sentence_length_delta": 0.20,
    "particle_signature": 0.15,
    "pronoun_shift": 0.15,
    "dialogue_volume": 0.10,
    "direct_address": 0.10,
}


def compute_eps_score(signals: Dict[str, float]) -> float:
    """
    Compute EPS score from raw signal values (-1.0 to +1.0 each).

    Args:
        signals: Dict of signal_name → value (-1.0 to +1.0)

    Returns:
        Weighted EPS score in range -1.0 to +1.0
    """
    score = 0.0
    total_weight = 0.0

    for signal_name, value in signals.items():
        weight = EPS_SIGNAL_WEIGHTS.get(signal_name, 0.0)
        if weight > 0:
            # Clamp value to valid range
            clamped_value = max(-1.0, min(1.0, value))
            score += clamped_value * weight
            total_weight += weight

    if total_weight > 0:
        score = score / total_weight

    return round(score, 2)


def eps_to_band(eps: float) -> str:
    """Map EPS score to voice band name."""
    for band, (lo, hi) in EPS_BANDS.items():
        if lo <= eps <= hi:
            return band
    # Handle edge cases
    if eps < -0.5:
        return "COLD"
    if eps > 0.5:
        return "HOT"
    return "NEUTRAL"


@dataclass
class EpsSignalSnapshot:
    """Raw signal values at a point in the story."""
    keigo_shift: float = 0.0           # -1.0 to +1.0
    sentence_length_delta: float = 0.0  # -1.0 to +1.0
    particle_signature: float = 0.0     # -1.0 to +1.0
    pronoun_shift: float = 0.0         # -1.0 to +1.0
    dialogue_volume: float = 0.0        # -1.0 to +1.0
    direct_address: float = 0.0        # -1.0 to +1.0

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "EpsSignalSnapshot":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ArcMilestone:
    """A significant narrative event that shifts a character's EPS."""
    volume_id: str
    chapter_id: str
    character_id: str
    previous_eps: float
    new_eps: float
    previous_band: str
    new_band: str
    trigger: str          # Brief description of what caused the shift
    dominant_signal: str  # Signal that drove the shift


@dataclass
class CharacterArcHistory:
    """Full arc history for a character across volumes using EPS."""
    character_id: str
    canonical_name_en: str
    archetype: str
    baseline_signals: EpsSignalSnapshot = None  # Character's baseline (first chapter)
    current_eps: float = 0.0
    current_band: str = "NEUTRAL"
    carried_forward_state: Dict[str, Any] = field(default_factory=dict)
    chapter_signals: Dict[str, Dict] = field(default_factory=dict)  # "V1Ch3" → {eps, band, signals}
    milestones: List[ArcMilestone] = field(default_factory=list)

    def __post_init__(self):
        if self.baseline_signals is None:
            self.baseline_signals = EpsSignalSnapshot()

    def signals_at(self, volume_id: str, chapter_id: str) -> Optional[Dict]:
        key = f"{volume_id}:{chapter_id}"
        return self.chapter_signals.get(key)

    def record_signals(self, volume_id: str, chapter_id: str, signals: EpsSignalSnapshot) -> None:
        key = f"{volume_id}:{chapter_id}"
        eps = compute_eps_score(asdict(signals))
        band = eps_to_band(eps)
        self.chapter_signals[key] = {
            "eps": eps,
            "band": band,
            "signals": signals.to_dict(),
        }
        self.current_eps = eps
        self.current_band = band

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["baseline_signals"] = self.baseline_signals.to_dict() if self.baseline_signals else {}
        d["milestones"] = [asdict(m) for m in self.milestones]
        return d

    @classmethod
    def from_dict(cls, data: Dict) -> "CharacterArcHistory":
        baseline = data.pop("baseline_signals", {})
        if baseline:
            baseline = EpsSignalSnapshot.from_dict(baseline)
        milestones = [ArcMilestone(**m) for m in data.pop("milestones", [])]
        obj = cls(**data)
        obj.baseline_signals = baseline
        obj.milestones = milestones
        return obj


class ArcTracker:
    """
    Tracks and persists character EPS (Emotional Proximity Signal) across volumes.

    Reads emotional_proximity_signals from chapter metadata (populated by metadata processor)
    and maintains a persistent arc history in .context/arc_tracker.json.

    Usage:
        tracker = ArcTracker(work_dir)
        tracker.sync_from_manifest()
        directive = tracker.get_arc_directive(["Tanaka"], chapter_id="chapter_03")
    """

    def __init__(self, work_dir: Path):
        self.work_dir = work_dir
        self.context_dir = work_dir / ".context"
        self.context_dir.mkdir(parents=True, exist_ok=True)
        self.arc_file = self.context_dir / "arc_tracker.json"
        self._histories: Dict[str, CharacterArcHistory] = {}  # lower(name) → history
        self._volume_id = work_dir.name
        self._load()

    # ─── Persistence ─────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self.arc_file.exists():
            return
        with open(self.arc_file, encoding="utf-8") as f:
            data = json.load(f)
        for key, hist_data in data.items():
            self._histories[key] = CharacterArcHistory.from_dict(hist_data)

    def _save(self) -> None:
        data = {k: v.to_dict() for k, v in self._histories.items()}
        with open(self.arc_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # ─── Sync from manifest ───────────────────────────────────────────────────

    def sync_from_manifest(self) -> int:
        """
        Read emotional_proximity_signals from manifest chapters and update arc histories.
        Returns number of signal records updated.
        """
        manifest_path = self.work_dir / "manifest.json"
        if not manifest_path.exists():
            return 0

        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

        chapters = (
            manifest.get("metadata_en", {}).get("chapters")
            or manifest.get("metadata_vn", {}).get("chapters")
            or {}
        )

        fingerprints = (
            manifest.get("metadata_en", {}).get("character_voice_fingerprints")
            or manifest.get("metadata_vn", {}).get("character_voice_fingerprints")
            or []
        )

        # Build archetype lookup
        archetype_map: Dict[str, str] = {}
        for fp in fingerprints:
            name = fp.get("canonical_name_en", "").strip()
            if name:
                archetype_map[name.lower()] = fp.get("archetype", "unknown")

        updated = 0
        # Handle both dict (chapter_01 → data) and list ([{id, ...}]) formats
        chapter_items = chapters.values() if isinstance(chapters, dict) else chapters
        for ch in chapter_items:
            if isinstance(ch, str):
                continue  # Skip dict key string
            ch_id = ch.get("id", "")
            eps_data = ch.get("emotional_proximity_signals", {})

            for char_name, signal_data in eps_data.items():
                key = char_name.lower()
                signals_dict = signal_data.get("signals", {})

                # Handle legacy RTAS format (convert to EPS)
                if "rtas_state" in signal_data:
                    # Convert old RTAS to EPS
                    rtas = signal_data.get("rtas_state", "NEUTRAL")
                    legacy_eps = self._rtas_to_eps(rtas)
                    signals_dict = {
                        "keigo_shift": legacy_eps * 0.3,
                        "sentence_length_delta": legacy_eps * 0.2,
                        "particle_signature": legacy_eps * 0.15,
                        "pronoun_shift": legacy_eps * 0.15,
                        "dialogue_volume": legacy_eps * 0.1,
                        "direct_address": legacy_eps * 0.1,
                    }
                    signal_data["eps_score"] = legacy_eps

                # Extract EPS score and band
                eps = signal_data.get("eps_score", 0.0)
                band = eps_to_band(eps)

                # Initialize history if new character
                if key not in self._histories:
                    self._histories[key] = CharacterArcHistory(
                        character_id=key,
                        canonical_name_en=char_name,
                        archetype=archetype_map.get(key, "unknown"),
                        current_eps=eps,
                        current_band=band,
                    )

                hist = self._histories[key]

                # Set baseline on first appearance
                if not hist.baseline_signals or all(
                    v == 0.0 for v in asdict(hist.baseline_signals).values()
                ):
                    hist.baseline_signals = EpsSignalSnapshot(**signals_dict)

                # Get previous EPS for milestone detection
                prev_eps = hist.current_eps
                prev_band = hist.current_band

                # Record new signals
                signals = EpsSignalSnapshot(**signals_dict)
                hist.record_signals(self._volume_id, ch_id, signals)

                # Record milestone if band changed significantly
                if prev_band and prev_band != band:
                    dominant = max(signals_dict.items(), key=lambda x: abs(x[1]))[0] if signals_dict else "keigo_shift"
                    hist.milestones.append(ArcMilestone(
                        volume_id=self._volume_id,
                        chapter_id=ch_id,
                        character_id=key,
                        previous_eps=prev_eps,
                        new_eps=eps,
                        previous_band=prev_band,
                        new_band=band,
                        trigger="auto-detected from metadata",
                        dominant_signal=dominant,
                    ))
                updated += 1

        self._save()
        logger.info(f"Arc tracker synced {updated} EPS record(s) from manifest")
        return updated

    def hydrate_from_bible(self, bible) -> int:
        """
        Seed carried-forward EPS continuity from the series bible.

        This does not create synthetic chapter records for the current volume.
        It only establishes a prior-volume baseline that prompt builders can
        fall back to when the current chapter has no local EPS record yet.
        """
        if not bible:
            return 0

        updated = 0
        for _jp_name, char_data in bible.get_all_characters().items():
            if not isinstance(char_data, dict):
                continue
            latest_eps = char_data.get("latest_eps_state")
            if not isinstance(latest_eps, dict):
                continue

            canonical_name = str(
                latest_eps.get("canonical_name_en")
                or char_data.get("canonical_en")
                or ""
            ).strip()
            if not canonical_name:
                continue

            key = canonical_name.lower()
            try:
                eps = float(latest_eps.get("eps_score", 0.0))
            except (TypeError, ValueError):
                eps = 0.0
            band = str(latest_eps.get("voice_band", "")).strip().upper() or eps_to_band(eps)
            raw_signals = latest_eps.get("signals", {})
            if not isinstance(raw_signals, dict):
                raw_signals = {}
            clean_signals = {}
            for signal_name, value in raw_signals.items():
                try:
                    clean_signals[str(signal_name).strip()] = float(value)
                except (TypeError, ValueError):
                    continue

            if key not in self._histories:
                self._histories[key] = CharacterArcHistory(
                    character_id=key,
                    canonical_name_en=canonical_name,
                    archetype=str(char_data.get("category", "") or "unknown"),
                    current_eps=eps,
                    current_band=band,
                )

            hist = self._histories[key]
            hist.carried_forward_state = {
                "eps": round(eps, 3),
                "band": band,
                "signals": clean_signals,
                "source_volume_id": str(latest_eps.get("source_volume_id", "")).strip(),
                "source_chapter_id": str(latest_eps.get("source_chapter_id", "")).strip(),
            }

            if (
                clean_signals
                and (
                    hist.baseline_signals is None
                    or all(v == 0.0 for v in asdict(hist.baseline_signals).values())
                )
            ):
                hist.baseline_signals = EpsSignalSnapshot(**clean_signals)
            updated += 1

        if updated:
            self._save()
            logger.info("Arc tracker hydrated %s carried-forward EPS record(s) from bible", updated)
        return updated

    def _rtas_to_eps(self, rtas: str) -> float:
        """Convert legacy RTAS state to EPS score for backward compatibility."""
        rtas_map = {
            "CLOSED": -0.7,
            "GUARDED": -0.3,
            "WARMING": 0.1,
            "OPEN": 0.4,
            "BONDED": 0.6,
            "FRACTURED": -0.5,
            "RESOLVED": 0.2,
        }
        return rtas_map.get(rtas, 0.0)

    # ─── Retrieval ───────────────────────────────────────────────────────────

    def get_eps(self, character_name: str, chapter_id: Optional[str] = None) -> Optional[float]:
        """Return EPS score for a character at a given chapter."""
        hist = self._histories.get(character_name.lower())
        if not hist:
            return None
        if chapter_id:
            signals = hist.signals_at(self._volume_id, chapter_id)
            return signals.get("eps") if signals else hist.current_eps
        return hist.current_eps

    def get_band(self, character_name: str, chapter_id: Optional[str] = None) -> Optional[str]:
        """Return voice band (COLD/COOL/NEUTRAL/WARM/HOT) for a character."""
        hist = self._histories.get(character_name.lower())
        if not hist:
            return None
        if chapter_id:
            signals = hist.signals_at(self._volume_id, chapter_id)
            return signals.get("band") if signals else hist.current_band
        return hist.current_band

    def get_eps_for_chapter(self, chapter_id: str) -> Dict[str, Dict]:
        """Return {character_name: {eps, band, signals}} for all tracked characters at a chapter."""
        result = {}
        for key, hist in self._histories.items():
            signals = hist.signals_at(self._volume_id, chapter_id)
            if signals:
                result[hist.canonical_name_en] = signals
        return result

    def get_arc_directive(
        self,
        character_names: List[str],
        chapter_id: Optional[str] = None,
    ) -> str:
        """
        Build CHARACTER ARC STATE block for injection into <thinking>.
        Uses EPS bands for voice modifier guidance.
        """
        lines = []
        for name in character_names:
            hist = self._histories.get(name.lower())
            if not hist:
                continue

            carried_forward = False
            signals = hist.signals_at(self._volume_id, chapter_id) if chapter_id else None
            if not signals:
                carried_state = hist.carried_forward_state if isinstance(hist.carried_forward_state, dict) else {}
                if not carried_state:
                    continue
                signals = {
                    "eps": carried_state.get("eps", hist.current_eps),
                    "band": carried_state.get("band", hist.current_band or "NEUTRAL"),
                    "signals": carried_state.get("signals", {}),
                }
                carried_forward = True

            eps = signals.get("eps", 0.0)
            band = signals.get("band", "NEUTRAL")
            raw_signals = signals.get("signals", {})

            # Generate voice modifiers based on band
            band_modifiers = self._get_band_voice_modifiers(band, raw_signals)

            line = f"  {name}: EPS {eps:+.2f} [{band}]"
            if carried_forward:
                source_bits = []
                source_volume = hist.carried_forward_state.get("source_volume_id", "")
                source_chapter = hist.carried_forward_state.get("source_chapter_id", "")
                if source_volume:
                    source_bits.append(source_volume)
                if source_chapter:
                    source_bits.append(source_chapter)
                if source_bits:
                    line += f" (carried forward from {' / '.join(source_bits)})"
                else:
                    line += " (carried forward from prior volume)"
            lines.append(line)
            for mod in band_modifiers:
                lines.append(f"    → {mod}")

        if not lines:
            return ""

        return "## CHARACTER ARC STATES (EPS)\n" + "\n".join(lines)

    def _get_band_voice_modifiers(self, band: str, signals: Dict[str, float]) -> List[str]:
        """Generate voice modifiers based on EPS band and dominant signals."""
        modifiers = []

        # Band-based base modifiers
        band_mods = {
            "COLD": ["minimal emotional expression", "formal register", "guarded brevity"],
            "COOL": ["polite distance", "controlled warmth", "observed boundaries"],
            "NEUTRAL": ["character baseline", "consistent with archetype"],
            "WARM": ["casual intimacy", "relaxed formality", "personal address"],
            "HOT": ["vulnerable openness", "direct emotional statements", "confident intimacy"],
        }
        modifiers.extend(band_mods.get(band, []))

        # Signal-driven adjustments
        if signals.get("keigo_shift", 0) < -0.3:
            modifiers.append("dropping to casual register")
        elif signals.get("keigo_shift", 0) > 0.3:
            modifiers.append("using polite forms")

        if signals.get("sentence_length_delta", 0) < -0.3:
            modifiers.append("short clipped sentences")
        elif signals.get("sentence_length_delta", 0) > 0.3:
            modifiers.append("longer, more open sentences")

        if signals.get("direct_address", 0) > 0.3:
            modifiers.append("freely using protagonist's name")
        elif signals.get("direct_address", 0) < -0.3:
            modifiers.append("avoiding direct address")

        return modifiers[:4]  # Limit to 4 modifiers

    def get_arc_delta(
        self, character_name: str, from_chapter: str, to_chapter: str
    ) -> Optional[Tuple[float, float]]:
        """
        Return (from_eps, to_eps) if character's EPS changed significantly between chapters.
        Returns None if no change or character not tracked.
        """
        hist = self._histories.get(character_name.lower())
        if not hist:
            return None

        from_signals = hist.signals_at(self._volume_id, from_chapter)
        to_signals = hist.signals_at(self._volume_id, to_chapter)

        if from_signals and to_signals:
            from_eps = from_signals.get("eps", 0.0)
            to_eps = to_signals.get("eps", 0.0)
            if abs(to_eps - from_eps) >= 0.2:  # Significant change threshold
                return (from_eps, to_eps)
        return None

    # ─── Visual signal write-back ─────────────────────────────────────────────

    def record_visual_signal(
        self,
        character_name: str,
        chapter_id: str,
        visual_eps_band: str,
        confidence: float,
        source: str = "visual",
    ) -> bool:
        """
        Record a visual EPS band observation from Phase 1.6 (VisualAssetProcessor).

        Stores under a synthetic key "<volume_id>:<chapter_id>:visual" so visual
        evidence is kept separate from text-derived signals and can be correlated
        without overwriting authoritative text data.

        Args:
            character_name: Canonical EN name of the character.
            chapter_id: Chapter or illustration ID the observation belongs to.
            visual_eps_band: One of COLD/COOL/NEUTRAL/WARM/HOT.
            confidence: Model confidence in the band assessment (0.0–1.0).
            source: String tag for provenance (default "visual").

        Returns:
            True if the observation was stored, False if ignored (low confidence).
        """
        if confidence < 0.60:
            return False

        band_to_midpoint = {
            "COLD": -0.7,
            "COOL": -0.3,
            "NEUTRAL": 0.0,
            "WARM": 0.3,
            "HOT": 0.7,
        }
        eps_value = band_to_midpoint.get(visual_eps_band.upper(), 0.0)

        key = character_name.lower()
        if key not in self._histories:
            self._histories[key] = CharacterArcHistory(
                character_id=key,
                canonical_name_en=character_name,
                archetype="unknown",
                current_eps=eps_value,
                current_band=visual_eps_band.upper(),
            )

        hist = self._histories[key]
        storage_key = f"{self._volume_id}:{chapter_id}:{source}"
        hist.chapter_signals[storage_key] = {
            "eps": eps_value,
            "band": visual_eps_band.upper(),
            "confidence": round(confidence, 3),
            "source": source,
            "signals": {},  # No raw sub-signals from visual channel
        }

        self._save()
        logger.debug(
            "[ARC] Visual signal stored: %s @ %s → %s (eps=%.2f, conf=%.2f)",
            character_name, chapter_id, visual_eps_band, eps_value, confidence,
        )
        return True

    def get_chapter_eps_band_shifts(self, chapter_id: str) -> List[Dict]:
        """
        Return characters whose EPS band shifted IN OR BEFORE this chapter.

        Used by Phase 1.6 to escalate thinking to 'high' when a band crossing
        has been recorded for the chapter's protagonists.

        Returns list of dicts: [{character, from_band, to_band, eps_delta}]
        """
        shifts = []
        for key, hist in self._histories.items():
            chapter_key = f"{self._volume_id}:{chapter_id}"
            current = hist.chapter_signals.get(chapter_key)
            if not current:
                continue

            current_band = current.get("band", "NEUTRAL")
            # Find the previous text-derived entry for this character
            sorted_keys = sorted(
                k for k in hist.chapter_signals
                if not k.endswith(":visual") and k < chapter_key
            )
            if not sorted_keys:
                previous_band = hist.current_band or "NEUTRAL"
            else:
                previous_band = hist.chapter_signals[sorted_keys[-1]].get("band", "NEUTRAL")

            if current_band != previous_band:
                shifts.append({
                    "character": hist.canonical_name_en,
                    "from_band": previous_band,
                    "to_band": current_band,
                    "eps_delta": round(
                        current.get("eps", 0.0)
                        - hist.chapter_signals.get(sorted_keys[-1], {}).get("eps", 0.0),
                        2,
                    ) if sorted_keys else 0.0,
                })
        return shifts

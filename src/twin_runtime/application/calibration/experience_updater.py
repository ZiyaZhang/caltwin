"""ExperienceUpdater — conflict-aware gating for experience library updates.

Replaces direct exp_lib.add() with deduplication, confirmation, and
conflict detection logic.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel

from twin_runtime.domain.models.experience import ExperienceEntry, ExperienceLibrary


class UpdateAction(str, Enum):
    ADDED = "added"
    CONFIRMED = "confirmed"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class UpdateResult(BaseModel):
    action: UpdateAction
    reason: str
    affected_entry_id: Optional[str] = None


class ExperienceUpdater:
    """Decides whether to add, confirm, supersede, or reject a new entry."""

    def __init__(self, *, duplicate_threshold: float = 0.6, keyword_overlap_threshold: float = 0.5):
        self._dup_threshold = duplicate_threshold
        self._kw_threshold = keyword_overlap_threshold

    def update(self, new_entry: ExperienceEntry, library: ExperienceLibrary) -> UpdateResult:
        """Evaluate new_entry against library and apply the appropriate action."""
        similar = library.search_entries(new_entry.scenario_type, top_k=3)

        if not similar:
            library.add(new_entry)
            return UpdateResult(
                action=UpdateAction.ADDED,
                reason="No similar entries found",
            )

        best = similar[0]
        jaccard = self._jaccard_similarity(new_entry.scenario_type, best.scenario_type)
        kw_overlap = self._keyword_overlap(new_entry.insight, best.insight)

        # Conflict detection first: same scenario type but different correctness verdict
        if jaccard > self._dup_threshold and new_entry.was_correct != best.was_correct:
            # Preference drift — supersede old with new, halve old weight
            best.weight = max(0.1, best.weight * 0.5)
            library.add(new_entry)
            return UpdateResult(
                action=UpdateAction.SUPERSEDED,
                reason=f"Conflicting verdict (new={new_entry.was_correct}, old={best.was_correct}). Old weight halved.",
                affected_entry_id=best.id,
            )

        # Duplicate detection: high scenario overlap + high insight overlap
        if jaccard > self._dup_threshold and kw_overlap > self._kw_threshold:
            # Same scenario, same lesson → confirm existing
            best.confirmation_count += 1
            from datetime import datetime, timezone
            best.last_confirmed = datetime.now(timezone.utc)
            return UpdateResult(
                action=UpdateAction.CONFIRMED,
                reason=f"Duplicate of existing entry (jaccard={jaccard:.2f}, kw_overlap={kw_overlap:.2f})",
                affected_entry_id=best.id,
            )

        # Complementary: same domain or partial overlap but different angle
        library.add(new_entry)
        return UpdateResult(
            action=UpdateAction.ADDED,
            reason=f"Complementary entry (jaccard={jaccard:.2f}, different angle)",
        )

    @staticmethod
    def _jaccard_similarity(tags_a: list, tags_b: list) -> float:
        """Jaccard similarity between two tag lists."""
        set_a = {t.lower() for t in tags_a}
        set_b = {t.lower() for t in tags_b}
        if not set_a and not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    @staticmethod
    def _keyword_overlap(text_a: str, text_b: str) -> float:
        """Word-level overlap between two insight texts."""
        words_a = {w.lower() for w in text_a.split() if len(w) > 2}
        words_b = {w.lower() for w in text_b.split() if len(w) > 2}
        if not words_a or not words_b:
            return 0.0
        intersection = len(words_a & words_b)
        smaller = min(len(words_a), len(words_b))
        return intersection / smaller if smaller > 0 else 0.0

"""Experience Library models — ExperienceEntry, PatternInsight, and search."""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from twin_runtime.domain.models.primitives import DomainEnum


class ExperienceEntry(BaseModel):
    """A single experience or lesson learned."""

    id: str = Field(min_length=1)
    scenario_type: List[str] = Field(
        description="Tags/keywords for search",
    )
    insight: str = Field(description="The actual experience/lesson")
    applicable_when: str = Field(description="When this applies")
    not_applicable_when: str = Field(
        default="", description="When this doesn't apply"
    )
    domain: Optional[DomainEnum] = None
    source_trace_id: Optional[str] = None
    was_correct: bool = True
    weight: float = Field(default=1.0, ge=0.0, le=2.0)
    confirmation_count: int = Field(default=0, ge=0)
    created_at: datetime
    last_confirmed: Optional[datetime] = None
    entry_kind: Literal["principle", "narrative", "reflection"] = "reflection"


class PatternInsight(BaseModel):
    """A higher-level pattern detected across multiple experiences."""

    id: str = Field(min_length=1)
    pattern_description: str
    systematic_bias: str
    correction_strategy: str
    affected_trace_ids: List[str] = Field(default_factory=list)
    domains: List[DomainEnum] = Field(default_factory=list)
    weight: float = Field(default=2.0, ge=0.0)
    created_at: datetime


class SearchResult(BaseModel):
    """A single search result — either an entry or a pattern."""

    kind: Literal["entry", "pattern"]
    score: float
    entry: Optional[ExperienceEntry] = None
    pattern: Optional[PatternInsight] = None


class ExperienceLibrary(BaseModel):
    """In-memory collection of experience entries and pattern insights."""

    entries: List[ExperienceEntry] = Field(default_factory=list)
    patterns: List[PatternInsight] = Field(default_factory=list)
    version: str = "1.0"

    def search(
        self,
        query_keywords: List[str],
        top_k: int = 5,
        min_weight: float = 0.1,
    ) -> List[SearchResult]:
        """Search entries and patterns by keyword overlap.

        Entry score:   overlap(query ∩ scenario_type) × weight × (1 + 0.1 × confirmation_count)
        Pattern score: overlap(query ∩ description words) × weight × 1.5
        """
        query_set = {kw.lower() for kw in query_keywords}
        results: List[SearchResult] = []

        for entry in self.entries:
            if entry.weight < min_weight:
                continue
            entry_tags = {t.lower() for t in entry.scenario_type}
            overlap = len(query_set & entry_tags)
            if overlap == 0:
                continue
            score = overlap * entry.weight * (1 + 0.1 * entry.confirmation_count)
            results.append(SearchResult(kind="entry", score=score, entry=entry))

        for pattern in self.patterns:
            if pattern.weight < min_weight:
                continue
            desc_words = set(pattern.pattern_description.lower().split())
            overlap = len(query_set & desc_words)
            if overlap == 0:
                continue
            score = overlap * pattern.weight * 1.5
            results.append(
                SearchResult(kind="pattern", score=score, pattern=pattern)
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def search_entries(
        self,
        query_keywords: List[str],
        top_k: int = 5,
        min_weight: float = 0.1,
    ) -> List[ExperienceEntry]:
        """Search entries only, ignoring patterns entirely.

        Scores entries directly rather than filtering search() results,
        so patterns cannot starve entries from the top_k slots.
        """
        query_set = {kw.lower() for kw in query_keywords}
        scored: List[tuple] = []
        for entry in self.entries:
            if entry.weight < min_weight:
                continue
            entry_tags = {t.lower() for t in entry.scenario_type}
            overlap = len(query_set & entry_tags)
            if overlap == 0:
                continue
            score = overlap * entry.weight * (1 + 0.1 * entry.confirmation_count)
            scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:top_k]]

    def add(self, entry: ExperienceEntry) -> None:
        """Append an entry to the library."""
        self.entries.append(entry)

    @property
    def size(self) -> int:
        """Total number of entries and patterns."""
        return len(self.entries) + len(self.patterns)

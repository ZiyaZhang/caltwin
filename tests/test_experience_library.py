"""Tests for ExperienceLibrary domain models and ExperienceLibraryStore."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

import pytest

from twin_runtime.domain.models.primitives import DomainEnum
from twin_runtime.domain.models.experience import (
    ExperienceEntry,
    ExperienceLibrary,
    PatternInsight,
    SearchResult,
)
from twin_runtime.infrastructure.backends.json_file.experience_store import (
    ExperienceLibraryStore,
)


def _make_entry(
    id: str = "e1",
    scenario_type: Optional[List[str]] = None,
    weight: float = 1.0,
    confirmation_count: int = 0,
    domain: Optional[DomainEnum] = None,
) -> ExperienceEntry:
    return ExperienceEntry(
        id=id,
        scenario_type=scenario_type or ["negotiation", "salary"],
        insight="Always anchor first.",
        applicable_when="When negotiating salary.",
        domain=domain,
        weight=weight,
        confirmation_count=confirmation_count,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def _make_pattern(
    id: str = "p1",
    description: str = "overconfidence in negotiation outcomes",
    weight: float = 2.0,
) -> PatternInsight:
    return PatternInsight(
        id=id,
        pattern_description=description,
        systematic_bias="anchoring bias",
        correction_strategy="Consider the other party's BATNA.",
        weight=weight,
        created_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
    )


# ── ExperienceEntry creation and validation ──────────────────────────


class TestExperienceEntry:
    def test_create_minimal(self):
        entry = _make_entry()
        assert entry.id == "e1"
        assert entry.weight == 1.0
        assert entry.was_correct is True
        assert entry.entry_kind == "reflection"
        assert entry.not_applicable_when == ""

    def test_id_min_length(self):
        with pytest.raises(Exception):
            _make_entry(id="")

    def test_weight_bounds(self):
        with pytest.raises(Exception):
            _make_entry(weight=3.0)
        with pytest.raises(Exception):
            _make_entry(weight=-0.1)

    def test_domain_set(self):
        entry = _make_entry(domain=DomainEnum.WORK)
        assert entry.domain == DomainEnum.WORK


# ── SearchResult ─────────────────────────────────────────────────────


class TestSearchResult:
    def test_kind_entry(self):
        entry = _make_entry()
        sr = SearchResult(kind="entry", score=1.0, entry=entry)
        assert sr.kind == "entry"
        assert sr.entry is not None
        assert sr.pattern is None

    def test_kind_pattern(self):
        pat = _make_pattern()
        sr = SearchResult(kind="pattern", score=2.0, pattern=pat)
        assert sr.kind == "pattern"
        assert sr.pattern is not None
        assert sr.entry is None


# ── ExperienceLibrary ────────────────────────────────────────────────


class TestExperienceLibrary:
    def test_add_and_size(self):
        lib = ExperienceLibrary()
        assert lib.size == 0
        lib.add(_make_entry(id="a"))
        assert lib.size == 1
        lib.add(_make_entry(id="b"))
        assert lib.size == 2

    def test_size_includes_patterns(self):
        lib = ExperienceLibrary(
            entries=[_make_entry()],
            patterns=[_make_pattern()],
        )
        assert lib.size == 2

    def test_empty_search(self):
        lib = ExperienceLibrary()
        assert lib.search(["anything"]) == []

    def test_search_ranking_higher_weight(self):
        lib = ExperienceLibrary(
            entries=[
                _make_entry(id="low", weight=0.5),
                _make_entry(id="high", weight=2.0),
            ]
        )
        results = lib.search(["negotiation"])
        assert len(results) == 2
        assert results[0].entry is not None
        assert results[0].entry.id == "high"
        assert results[1].entry is not None
        assert results[1].entry.id == "low"

    def test_confirmation_count_boost(self):
        lib = ExperienceLibrary(
            entries=[
                _make_entry(id="unconfirmed", weight=1.0, confirmation_count=0),
                _make_entry(id="confirmed", weight=1.0, confirmation_count=5),
            ]
        )
        results = lib.search(["salary"])
        assert results[0].entry is not None
        assert results[0].entry.id == "confirmed"
        assert results[0].score > results[1].score

    def test_search_entries_only(self):
        lib = ExperienceLibrary(
            entries=[_make_entry(id="e1", scenario_type=["negotiation"])],
            patterns=[_make_pattern(description="negotiation pattern")],
        )
        entries = lib.search_entries(["negotiation"])
        assert len(entries) == 1
        assert entries[0].id == "e1"

    def test_pattern_in_search_results(self):
        lib = ExperienceLibrary(
            patterns=[_make_pattern(description="negotiation overconfidence")],
        )
        results = lib.search(["negotiation"])
        assert len(results) == 1
        assert results[0].kind == "pattern"
        assert results[0].pattern is not None

    def test_min_weight_filter(self):
        lib = ExperienceLibrary(
            entries=[
                _make_entry(id="weak", weight=0.05),
                _make_entry(id="strong", weight=1.0),
            ]
        )
        results = lib.search(["negotiation"], min_weight=0.1)
        assert len(results) == 1
        assert results[0].entry is not None
        assert results[0].entry.id == "strong"

    def test_no_keyword_overlap_returns_nothing(self):
        lib = ExperienceLibrary(entries=[_make_entry()])
        assert lib.search(["unrelated"]) == []

    def test_top_k_limit(self):
        lib = ExperienceLibrary(
            entries=[_make_entry(id=f"e{i}") for i in range(10)]
        )
        results = lib.search(["negotiation"], top_k=3)
        assert len(results) == 3


# ── ExperienceLibraryStore ───────────────────────────────────────────


class TestExperienceLibraryStore:
    def test_load_empty(self, tmp_path):
        store = ExperienceLibraryStore(str(tmp_path), "user1")
        lib = store.load()
        assert lib.size == 0
        assert lib.version == "1.0"

    def test_roundtrip(self, tmp_path):
        store = ExperienceLibraryStore(str(tmp_path), "user1")
        lib = ExperienceLibrary()
        lib.add(_make_entry(id="e1"))
        lib.patterns.append(_make_pattern(id="p1"))
        store.save(lib)

        loaded = store.load()
        assert loaded.size == 2
        assert loaded.entries[0].id == "e1"
        assert loaded.patterns[0].id == "p1"

    def test_unsafe_user_id(self, tmp_path):
        with pytest.raises(ValueError, match="Unsafe"):
            ExperienceLibraryStore(str(tmp_path), "../evil")

    def test_overwrite(self, tmp_path):
        store = ExperienceLibraryStore(str(tmp_path), "user1")
        lib1 = ExperienceLibrary(entries=[_make_entry(id="old")])
        store.save(lib1)

        lib2 = ExperienceLibrary(entries=[_make_entry(id="new")])
        store.save(lib2)

        loaded = store.load()
        assert loaded.size == 1
        assert loaded.entries[0].id == "new"

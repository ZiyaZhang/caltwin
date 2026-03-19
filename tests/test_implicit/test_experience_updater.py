"""Tests for ExperienceUpdater — conflict-aware experience gating."""

from datetime import datetime, timezone

from twin_runtime.application.calibration.experience_updater import (
    ExperienceUpdater,
    UpdateAction,
)
from twin_runtime.domain.models.experience import (
    ExperienceEntry,
    ExperienceLibrary,
)


def _make_entry(
    id: str = "e1",
    scenario_type: list = None,
    insight: str = "some insight",
    was_correct: bool = True,
    weight: float = 1.0,
) -> ExperienceEntry:
    return ExperienceEntry(
        id=id,
        scenario_type=scenario_type or ["redis", "caching", "backend"],
        insight=insight,
        applicable_when="backend caching decisions",
        domain=None,
        was_correct=was_correct,
        weight=weight,
        created_at=datetime.now(timezone.utc),
    )


def test_add_new_scenario():
    """Empty library → ADDED."""
    lib = ExperienceLibrary()
    updater = ExperienceUpdater()
    entry = _make_entry()
    result = updater.update(entry, lib)

    assert result.action == UpdateAction.ADDED
    assert len(lib.entries) == 1
    assert lib.entries[0].id == "e1"


def test_duplicate_confirmed():
    """High overlap in scenario_type + insight → CONFIRMED, count++."""
    existing = _make_entry(id="existing", insight="Use Redis for caching backend services")
    lib = ExperienceLibrary(entries=[existing])
    updater = ExperienceUpdater()

    new = _make_entry(
        id="new",
        scenario_type=["redis", "caching", "backend"],  # same tags
        insight="Redis is good for caching backend workloads",  # high word overlap
    )
    result = updater.update(new, lib)

    assert result.action == UpdateAction.CONFIRMED
    assert result.affected_entry_id == "existing"
    assert lib.entries[0].confirmation_count == 1
    assert lib.entries[0].last_confirmed is not None
    # Should NOT add new entry
    assert len(lib.entries) == 1


def test_conflict_superseded():
    """Same scenario, different was_correct → SUPERSEDED, old weight halved."""
    existing = _make_entry(id="old", was_correct=True, weight=1.0)
    lib = ExperienceLibrary(entries=[existing])
    updater = ExperienceUpdater()

    new = _make_entry(
        id="new",
        scenario_type=["redis", "caching", "backend"],
        insight="some insight about redis caching backend",
        was_correct=False,
    )
    result = updater.update(new, lib)

    assert result.action == UpdateAction.SUPERSEDED
    assert result.affected_entry_id == "old"
    assert lib.entries[0].weight == 0.5  # halved
    assert len(lib.entries) == 2  # old + new both present


def test_complementary_added():
    """Same domain, different angle → ADDED."""
    existing = _make_entry(
        id="existing",
        scenario_type=["redis", "caching", "backend"],
        insight="Use Redis for caching",
    )
    lib = ExperienceLibrary(entries=[existing])
    updater = ExperienceUpdater()

    new = _make_entry(
        id="new",
        scenario_type=["postgresql", "database", "backend"],  # low jaccard
        insight="PostgreSQL handles complex queries well",
    )
    result = updater.update(new, lib)

    assert result.action == UpdateAction.ADDED
    assert len(lib.entries) == 2


def test_jaccard_similarity():
    assert ExperienceUpdater._jaccard_similarity(["a", "b", "c"], ["a", "b", "c"]) == 1.0
    assert ExperienceUpdater._jaccard_similarity(["a", "b"], ["c", "d"]) == 0.0
    assert ExperienceUpdater._jaccard_similarity([], []) == 0.0
    # Case insensitive
    assert ExperienceUpdater._jaccard_similarity(["Redis"], ["redis"]) == 1.0


def test_keyword_overlap():
    assert ExperienceUpdater._keyword_overlap("", "") == 0.0
    overlap = ExperienceUpdater._keyword_overlap(
        "Use Redis for caching backend",
        "Redis works well for backend caching",
    )
    assert overlap > 0.5


def test_weight_floor_on_supersede():
    """Superseded entry weight doesn't go below 0.1."""
    existing = _make_entry(id="old", was_correct=True, weight=0.15)
    lib = ExperienceLibrary(entries=[existing])
    updater = ExperienceUpdater()

    new = _make_entry(
        id="new",
        scenario_type=["redis", "caching", "backend"],
        insight="some insight about redis caching backend",
        was_correct=False,
    )
    updater.update(new, lib)

    assert lib.entries[0].weight >= 0.1

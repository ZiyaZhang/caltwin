"""Tests for ReflectionGenerator — post-outcome reflection logic."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List
from unittest.mock import MagicMock

from twin_runtime.application.calibration.reflection_generator import (
    ReflectionGenerator,
    ReflectionResult,
)
from twin_runtime.domain.models.experience import (
    ExperienceEntry,
    ExperienceLibrary,
    PatternInsight,
)
from twin_runtime.domain.models.primitives import DomainEnum


def _make_head_assessment(
    ranking: List[str],
    confidence: float = 0.8,
    domain: DomainEnum = DomainEnum.WORK,
) -> MagicMock:
    ha = MagicMock()
    ha.option_ranking = ranking
    ha.confidence = confidence
    ha.domain = domain
    return ha


def _make_trace(
    query: str = "should I take the job",
    ranking: List[str] = None,
    final_decision: str = "A",
    output_text: str = "reasoning here",
    assessments: List[MagicMock] = None,
) -> MagicMock:
    trace = MagicMock()
    trace.trace_id = "t-100"
    trace.query = query
    trace.final_decision = final_decision
    trace.output_text = output_text
    trace.activated_domains = [DomainEnum.WORK]

    if assessments is not None:
        trace.head_assessments = assessments
    elif ranking is not None:
        trace.head_assessments = [_make_head_assessment(ranking)]
    else:
        trace.head_assessments = [_make_head_assessment(["A", "B"])]

    return trace


def _make_entry(
    entry_id: str = "exp-1",
    scenario_type: List[str] = None,
    confirmation_count: int = 0,
) -> ExperienceEntry:
    return ExperienceEntry(
        id=entry_id,
        scenario_type=scenario_type or ["should", "job"],
        insight="Take the job if it pays well",
        applicable_when="Career decisions",
        domain=DomainEnum.WORK,
        confirmation_count=confirmation_count,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def _make_llm_mock() -> MagicMock:
    llm = MagicMock()
    llm.ask_json.return_value = {
        "insight": "User prefers stability over salary",
        "scenario_type": ["career", "stability"],
        "applicable_when": "Job offers with trade-offs",
        "not_applicable_when": "Clear upgrades",
    }
    return llm


class TestCheckCorrect:
    def test_check_correct_hit(self) -> None:
        """Ranking ['A', 'B'] with ground_truth 'A' => True (rank 1)."""
        llm = _make_llm_mock()
        gen = ReflectionGenerator(llm)
        trace = _make_trace(ranking=["A", "B"])
        assert gen._check_correct(trace, "A") is True

    def test_check_correct_miss(self) -> None:
        """Ranking ['A', 'B'] with ground_truth 'B' => False (rank 2, not 1)."""
        llm = _make_llm_mock()
        gen = ReflectionGenerator(llm)
        trace = _make_trace(ranking=["A", "B"])
        assert gen._check_correct(trace, "B") is False

    def test_check_correct_empty_assessments(self) -> None:
        """No head assessments => empty ranking => False."""
        llm = _make_llm_mock()
        gen = ReflectionGenerator(llm)
        trace = _make_trace(assessments=[])
        assert gen._check_correct(trace, "A") is False


class TestHandleHit:
    def test_hit_confirms_matching_entry(self) -> None:
        """On hit, search_entries finds match => confirmation_count incremented, LLM NOT called."""
        llm = _make_llm_mock()
        gen = ReflectionGenerator(llm)
        trace = _make_trace(query="should I take the job", ranking=["A", "B"])

        entry = _make_entry(confirmation_count=2)
        lib = ExperienceLibrary(entries=[entry])

        result = gen.process(trace, "A", lib)

        assert result.action == "confirmed"
        assert result.was_correct is True
        assert result.confirmed_entry_id == "exp-1"
        assert entry.confirmation_count == 3
        assert entry.last_confirmed is not None
        llm.ask_json.assert_not_called()

    def test_hit_no_matching_entry(self) -> None:
        """On hit with empty lib, still returns confirmed without error."""
        llm = _make_llm_mock()
        gen = ReflectionGenerator(llm)
        trace = _make_trace(ranking=["A", "B"])

        lib = ExperienceLibrary(entries=[])

        result = gen.process(trace, "A", lib)

        assert result.action == "confirmed"
        assert result.was_correct is True
        assert result.confirmed_entry_id is None
        assert result.new_entry is None
        llm.ask_json.assert_not_called()


class TestHandleMiss:
    def test_miss_generates_entry(self) -> None:
        """On miss, LLM generates a new ExperienceEntry with entry_kind='reflection', weight=1.0."""
        llm = _make_llm_mock()
        gen = ReflectionGenerator(llm)
        trace = _make_trace(ranking=["A", "B"])

        lib = ExperienceLibrary(entries=[])
        result = gen.process(trace, "C", lib)

        assert result.action == "generated"
        assert result.was_correct is False
        assert result.new_entry is not None

        new = result.new_entry
        assert new.entry_kind == "reflection"
        assert new.weight == 1.0
        assert new.was_correct is False
        assert new.source_trace_id == "t-100"
        assert new.domain == DomainEnum.WORK
        assert new.insight == "User prefers stability over salary"
        assert new.scenario_type == ["career", "stability"]

    def test_miss_llm_called(self) -> None:
        """On miss, LLM.ask_json called exactly once."""
        llm = _make_llm_mock()
        gen = ReflectionGenerator(llm)
        trace = _make_trace(ranking=["A", "B"])

        lib = ExperienceLibrary(entries=[])
        gen.process(trace, "C", lib)

        llm.ask_json.assert_called_once()


class TestPatternNotConfirmed:
    def test_pattern_not_confirmed(self) -> None:
        """Even if a PatternInsight scores highest in full search(),
        search_entries() excludes patterns — confirmation only hits entries."""
        llm = _make_llm_mock()
        gen = ReflectionGenerator(llm)
        trace = _make_trace(query="should I take the job", ranking=["A", "B"])

        # Pattern with high weight that would rank first in full search()
        pattern = PatternInsight(
            id="pat-1",
            pattern_description="should take job offers quickly",
            systematic_bias="anchoring on first offer",
            correction_strategy="compare multiple",
            weight=2.0,
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        # Entry with lower score
        entry = _make_entry(
            entry_id="exp-2",
            scenario_type=["should", "job"],
            confirmation_count=0,
        )
        lib = ExperienceLibrary(entries=[entry], patterns=[pattern])

        # Full search would include the pattern ranked above the entry
        full_results = lib.search(["should", "job"])
        has_pattern = any(r.kind == "pattern" for r in full_results)
        assert has_pattern, "Pattern should appear in full search()"

        # But process only confirms entries, not patterns
        result = gen.process(trace, "A", lib)
        assert result.action == "confirmed"
        assert result.confirmed_entry_id == "exp-2"
        llm.ask_json.assert_not_called()

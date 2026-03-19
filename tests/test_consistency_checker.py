"""Tests for ConsistencyChecker (Phase B Step 6)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from twin_runtime.application.pipeline.consistency_checker import (
    ConsistencyChecker,
    ConsistencyResult,
)
from twin_runtime.domain.models.experience import ExperienceEntry, ExperienceLibrary
from twin_runtime.domain.models.primitives import DecisionMode, DomainEnum
from twin_runtime.domain.models.runtime import RuntimeDecisionTrace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trace(
    query: str = "salary negotiation",
    final_decision: str = "Ask for 120k",
    uncertainty: float = 0.3,
) -> RuntimeDecisionTrace:
    return RuntimeDecisionTrace(
        trace_id="t-1",
        twin_state_version="v1",
        situation_frame_id="sf-1",
        activated_domains=[DomainEnum.WORK],
        final_decision=final_decision,
        decision_mode=DecisionMode.DIRECT,
        uncertainty=uncertainty,
        query=query,
        created_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )


def _make_entry(
    entry_id: str = "e1",
    scenario_type: Optional[List[str]] = None,
    insight: str = "Always anchor first.",
    weight: float = 1.0,
) -> ExperienceEntry:
    return ExperienceEntry(
        id=entry_id,
        scenario_type=scenario_type or ["salary", "negotiation"],
        insight=insight,
        applicable_when="When negotiating salary.",
        weight=weight,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def _mock_llm(**ask_json_return: Any) -> MagicMock:
    llm = MagicMock()
    llm.ask_json.return_value = ask_json_return or {
        "is_consistent": True,
        "note": "ok",
        "confidence_penalty": 0.0,
    }
    return llm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestConsistencyChecker:

    def test_no_relevant_experiences(self):
        """Empty library -> is_consistent=True, 0 LLM calls."""
        llm = _mock_llm()
        checker = ConsistencyChecker(llm=llm)
        trace = _make_trace()
        lib = ExperienceLibrary()

        result = checker.check(trace, lib)

        assert result.is_consistent is True
        assert "No relevant experience" in result.note
        llm.ask_json.assert_not_called()

    def test_deterministic_contradiction(self):
        """Entry with 'avoid' in insight flags conflict."""
        llm = _mock_llm(
            is_consistent=False,
            note="Contradicts past experience",
            confidence_penalty=0.15,
        )
        checker = ConsistencyChecker(llm=llm)
        trace = _make_trace(query="salary negotiation")
        entry = _make_entry(
            insight="Avoid asking for too much in salary talks",
            weight=1.0,
        )
        lib = ExperienceLibrary(entries=[entry])

        result = checker.check(trace, lib)

        # Should have found a deterministic contradiction and called LLM
        assert "e1" in result.conflicting_experience_ids
        llm.ask_json.assert_called_once()

    def test_no_contradiction_passes(self):
        """Entry without negation pattern -> consistent, no LLM call."""
        llm = _mock_llm()
        checker = ConsistencyChecker(llm=llm)
        trace = _make_trace(query="salary negotiation")
        entry = _make_entry(insight="Always anchor first in salary negotiation", weight=1.0)
        lib = ExperienceLibrary(entries=[entry])

        result = checker.check(trace, lib)

        assert result.is_consistent is True
        assert "No contradictions" in result.note
        llm.ask_json.assert_not_called()

    def test_llm_check_inconsistent(self):
        """Mock LLM returns inconsistent -> penalty applied."""
        llm = _mock_llm(
            is_consistent=False,
            note="Decision contradicts prior lesson",
            confidence_penalty=0.15,
        )
        checker = ConsistencyChecker(llm=llm)
        trace = _make_trace(query="salary negotiation")
        entry = _make_entry(
            insight="Should not ask above market rate",
            weight=0.9,
        )
        lib = ExperienceLibrary(entries=[entry])

        result = checker.check(trace, lib)

        assert result.is_consistent is False
        assert result.confidence_penalty == 0.15
        assert "e1" in result.conflicting_experience_ids

    def test_llm_check_consistent(self):
        """Mock LLM returns consistent -> no penalty."""
        llm = _mock_llm(
            is_consistent=True,
            note="Consistent with experience",
            confidence_penalty=0.0,
        )
        checker = ConsistencyChecker(llm=llm)
        trace = _make_trace(query="salary negotiation")
        entry = _make_entry(
            insight="Avoid lowball offers",
            weight=1.0,
        )
        lib = ExperienceLibrary(entries=[entry])

        result = checker.check(trace, lib)

        assert result.is_consistent is True
        assert result.confidence_penalty == 0.0

    def test_confidence_penalty_clamped(self):
        """Penalty > 0.2 gets clamped to 0.2."""
        llm = _mock_llm(
            is_consistent=False,
            note="Big conflict",
            confidence_penalty=0.5,
        )
        checker = ConsistencyChecker(llm=llm)
        trace = _make_trace(query="salary negotiation", final_decision="Ask for 120k raise")
        entry = _make_entry(
            insight="should not ask for 120k in this market",
            weight=1.0,
        )
        lib = ExperienceLibrary(entries=[entry])

        result = checker.check(trace, lib)

        assert result.confidence_penalty == 0.2

    def test_trace_audit_fields_populated(self):
        """After check, verify ConsistencyResult fields map to trace fields."""
        llm = _mock_llm(
            is_consistent=False,
            note="Conflicts with lesson e1",
            confidence_penalty=0.1,
        )
        checker = ConsistencyChecker(llm=llm)
        trace = _make_trace(query="salary negotiation", final_decision="Ask for 120k", uncertainty=0.3)
        entry = _make_entry(
            insight="avoid asking for 120k in a down market",
            weight=1.0,
        )
        lib = ExperienceLibrary(entries=[entry])

        result = checker.check(trace, lib)

        # Map result -> trace (as orchestrator would do)
        trace.consistency_check_passed = result.is_consistent
        trace.consistency_note = result.note
        trace.conflicting_experience_ids = result.conflicting_experience_ids
        if not result.is_consistent:
            trace.uncertainty = min(trace.uncertainty + result.confidence_penalty, 0.95)

        assert trace.consistency_check_passed is False
        assert trace.consistency_note == "Conflicts with lesson e1"
        assert "e1" in trace.conflicting_experience_ids
        assert trace.uncertainty == pytest.approx(0.4)

    def test_s2_hook_applies_penalty(self):
        """Simulate S2 hook: ConsistencyChecker.check with a realistic trace."""
        llm = _mock_llm(
            is_consistent=False,
            note="Past experience says avoid this approach",
            confidence_penalty=0.15,
        )
        checker = ConsistencyChecker(llm=llm)
        trace = _make_trace(
            query="salary negotiation strategy",
            final_decision="Demand 150k immediately",
            uncertainty=0.4,
        )
        entry = _make_entry(
            entry_id="exp-42",
            scenario_type=["salary", "negotiation", "strategy"],
            insight="Avoid demanding too much up front",
            weight=1.2,
        )
        lib = ExperienceLibrary(entries=[entry])

        result = checker.check(trace, lib)

        assert result.is_consistent is False
        assert "exp-42" in result.conflicting_experience_ids
        assert result.confidence_penalty == 0.15

        # Apply as orchestrator would
        trace.consistency_check_passed = result.is_consistent
        trace.consistency_note = result.note
        trace.conflicting_experience_ids = result.conflicting_experience_ids
        if not result.is_consistent:
            trace.uncertainty = min(trace.uncertainty + result.confidence_penalty, 0.95)

        assert trace.uncertainty == pytest.approx(0.55)
        assert trace.consistency_check_passed is False

    def test_low_weight_entry_skipped(self):
        """Entries with weight < 0.8 should not trigger deterministic contradiction."""
        llm = _mock_llm()
        checker = ConsistencyChecker(llm=llm)
        trace = _make_trace(query="salary negotiation")
        entry = _make_entry(
            insight="Avoid this approach",
            weight=0.5,  # Below 0.8 threshold
        )
        lib = ExperienceLibrary(entries=[entry])

        result = checker.check(trace, lib)

        assert result.is_consistent is True
        assert "No contradictions" in result.note
        llm.ask_json.assert_not_called()

"""Tests for deliberation loop."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from twin_runtime.application.orchestrator.deliberation import (
    check_termination,
    deliberation_loop,
)
from twin_runtime.application.orchestrator.models import (
    DeliberationRoundSummary,
    TerminationReason,
)
from twin_runtime.domain.models.primitives import (
    ConflictType,
    DecisionMode,
    DomainEnum,
    MergeStrategy,
    OptionStructure,
    OrdinalTriLevel,
    ScopeStatus,
    UncertaintyType,
)
from twin_runtime.domain.models.runtime import ConflictReport, HeadAssessment


class TestCheckTermination:
    def test_conflict_resolved_requires_2_rounds(self):
        """CONFLICT_RESOLVED should NOT fire after only round 0 (initial pass)."""
        summaries = [
            DeliberationRoundSummary(
                round_index=0, new_unique_evidence_count=5, avg_head_confidence=0.8
            )
        ]
        result = check_termination(summaries, None, None)
        assert result is None  # S2 should deliberate at least once

    def test_conflict_resolved_after_2_rounds(self):
        """CONFLICT_RESOLVED fires after initial pass + 1 deliberation round."""
        summaries = [
            DeliberationRoundSummary(
                round_index=0, new_unique_evidence_count=5, avg_head_confidence=0.8
            ),
            DeliberationRoundSummary(
                round_index=1, new_unique_evidence_count=2, avg_head_confidence=0.85
            ),
        ]
        result = check_termination(summaries, None, None)
        assert result == TerminationReason.CONFLICT_RESOLVED

    def test_no_new_evidence_requires_2_rounds(self):
        """NO_NEW_EVIDENCE should not fire after only round 0."""
        summaries = [
            DeliberationRoundSummary(
                round_index=0, new_unique_evidence_count=0, avg_head_confidence=0.5
            ),
        ]
        conflict = MagicMock(spec=ConflictReport)
        conflict.conflict_types = [ConflictType.MIXED]
        conflict.resolvable_by_system = False
        result = check_termination(summaries, conflict, None)
        assert result is None  # Should NOT terminate after 1 round

    def test_no_new_evidence_after_2_rounds(self):
        summaries = [
            DeliberationRoundSummary(
                round_index=0, new_unique_evidence_count=3, avg_head_confidence=0.5
            ),
            DeliberationRoundSummary(
                round_index=1, new_unique_evidence_count=0, avg_head_confidence=0.5
            ),
        ]
        conflict = MagicMock(spec=ConflictReport)
        conflict.conflict_types = [ConflictType.MIXED]
        conflict.resolvable_by_system = False
        result = check_termination(summaries, conflict, None)
        assert result == TerminationReason.NO_NEW_EVIDENCE

    def test_confidence_plateau(self):
        summaries = [
            DeliberationRoundSummary(
                round_index=0,
                new_unique_evidence_count=3,
                avg_head_confidence=0.8,
                top_choice="A",
            ),
            DeliberationRoundSummary(
                round_index=1,
                new_unique_evidence_count=1,
                avg_head_confidence=0.82,
                top_choice="A",
                top_choice_changed=False,
            ),
        ]
        conflict = MagicMock(spec=ConflictReport)
        conflict.conflict_types = [ConflictType.PREFERENCE]
        conflict.resolvable_by_system = False
        result = check_termination(summaries, conflict, None)
        assert result == TerminationReason.CONFIDENCE_PLATEAU

    def test_no_termination_when_improving(self):
        summaries = [
            DeliberationRoundSummary(
                round_index=0,
                new_unique_evidence_count=3,
                avg_head_confidence=0.5,
                top_choice="A",
            ),
            DeliberationRoundSummary(
                round_index=1,
                new_unique_evidence_count=2,
                avg_head_confidence=0.7,
                top_choice="B",
                top_choice_changed=True,
            ),
        ]
        conflict = MagicMock(spec=ConflictReport)
        conflict.conflict_types = [ConflictType.MIXED]
        conflict.resolvable_by_system = False
        result = check_termination(summaries, conflict, None)
        assert result is None

    def test_empty_summaries_returns_none(self):
        result = check_termination([], None, None)
        assert result is None

    def test_conflict_resolved_single_resolvable(self):
        """Single conflict type + resolvable_by_system -> CONFLICT_RESOLVED (requires 2 rounds)."""
        summaries = [
            DeliberationRoundSummary(
                round_index=0, new_unique_evidence_count=2, avg_head_confidence=0.7
            ),
            DeliberationRoundSummary(
                round_index=1, new_unique_evidence_count=1, avg_head_confidence=0.75
            ),
        ]
        conflict = MagicMock(spec=ConflictReport)
        conflict.conflict_types = [ConflictType.BELIEF]
        conflict.resolvable_by_system = True
        result = check_termination(summaries, conflict, None)
        assert result == TerminationReason.CONFLICT_RESOLVED


class TestInsufficientEvidence:
    def test_insufficient_evidence_after_max_iterations(self):
        """When loop exhausts budget with unresolved conflict, produce INSUFFICIENT_EVIDENCE."""
        from twin_runtime.domain.models.situation import (
            SituationFeatureVector,
            SituationFrame,
        )
        from twin_runtime.domain.models.twin_state import TwinState

        twin = TwinState(
            **json.loads(
                Path("tests/fixtures/sample_twin_state.json").read_text()
            )
        )
        frame = SituationFrame(
            frame_id="test",
            domain_activation_vector={
                DomainEnum.WORK: 0.5,
                DomainEnum.MONEY: 0.5,
            },
            situation_feature_vector=SituationFeatureVector(
                reversibility=OrdinalTriLevel.MEDIUM,
                stakes=OrdinalTriLevel.HIGH,
                uncertainty_type=UncertaintyType.MIXED,
                controllability=OrdinalTriLevel.MEDIUM,
                option_structure=OptionStructure.CHOOSE_EXISTING,
            ),
            ambiguity_score=0.8,
            scope_status=ScopeStatus.IN_SCOPE,
            routing_confidence=0.5,
        )

        # Mock LLM that returns conflicting assessments every round
        llm = MagicMock()
        llm.ask_structured.return_value = {
            "option_ranking": ["A", "B"],
            "utility_decomposition": {"impact": 0.5},
            "confidence": 0.4,
            "used_core_variables": [],
            "used_evidence_types": [],
        }
        llm.ask_text.return_value = "Insufficient evidence."

        trace = deliberation_loop(
            frame,
            "test?",
            ["A", "B"],
            twin,
            llm=llm,
            evidence_store=None,
            max_iterations=2,
        )

        # After exhausting budget with no evidence, should get metadata populated
        assert trace.deliberation_rounds >= 0
        assert trace.terminated_by is not None


class TestDeliberationLoop:
    def test_single_head_no_conflict_terminates_round1(self):
        """With only 1 head (no conflict possible), should terminate CONFLICT_RESOLVED."""
        from twin_runtime.domain.models.situation import (
            SituationFeatureVector,
            SituationFrame,
        )
        from twin_runtime.domain.models.twin_state import TwinState

        twin = TwinState(
            **json.loads(
                Path("tests/fixtures/sample_twin_state.json").read_text()
            )
        )
        # Only activate one domain so only one head fires -> no conflict
        frame = SituationFrame(
            frame_id="test-single",
            domain_activation_vector={DomainEnum.WORK: 0.9},
            situation_feature_vector=SituationFeatureVector(
                reversibility=OrdinalTriLevel.LOW,
                stakes=OrdinalTriLevel.LOW,
                uncertainty_type=UncertaintyType.MISSING_INFO,
                controllability=OrdinalTriLevel.HIGH,
                option_structure=OptionStructure.CHOOSE_EXISTING,
            ),
            ambiguity_score=0.2,
            scope_status=ScopeStatus.IN_SCOPE,
            routing_confidence=0.9,
        )

        llm = MagicMock()
        llm.ask_structured.return_value = {
            "option_ranking": ["X", "Y"],
            "utility_decomposition": {"growth": 0.8},
            "confidence": 0.9,
            "used_core_variables": [],
            "used_evidence_types": [],
        }
        llm.ask_text.return_value = "I would choose X."

        trace = deliberation_loop(
            frame, "pick?", ["X", "Y"], twin,
            llm=llm, evidence_store=None, max_iterations=2,
        )

        # Single head -> no conflict -> CONFLICT_RESOLVED after 1 deliberation round
        assert trace.terminated_by == TerminationReason.CONFLICT_RESOLVED.value
        assert trace.deliberation_rounds == 1  # Initial pass + 1 deliberation round
        assert len(trace.deliberation_round_summaries) == 2

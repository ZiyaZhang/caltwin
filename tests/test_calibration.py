"""Unit tests for calibration engine components (no API calls)."""

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone

import pytest

from twin_runtime.models.calibration import CalibrationCase, CandidateCalibrationCase, TwinEvaluation
from twin_runtime.models.primitives import (
    CandidateSourceType,
    ConflictType,
    DecisionMode,
    DomainEnum,
    MergeStrategy,
    OrdinalTriLevel,
    RuntimeEventType,
)
from twin_runtime.models.runtime import HeadAssessment, RuntimeDecisionTrace
from twin_runtime.models.twin_state import TwinState
from twin_runtime.calibration.event_collector import collect_event, collect_manual_case
from twin_runtime.calibration.case_manager import promote_candidate
from twin_runtime.calibration.state_updater import apply_evaluation
from twin_runtime.store.calibration_store import CalibrationStore


def _load_twin() -> TwinState:
    fixture = os.path.join(os.path.dirname(__file__), "fixtures", "sample_twin_state.json")
    with open(fixture) as f:
        return TwinState(**json.load(f))


def _make_trace(decision="Recommended: Option A", domains=None) -> RuntimeDecisionTrace:
    return RuntimeDecisionTrace(
        trace_id=str(uuid.uuid4()),
        twin_state_version="v001",
        situation_frame_id=str(uuid.uuid4()),
        activated_domains=domains or [DomainEnum.WORK],
        head_assessments=[
            HeadAssessment(
                domain=DomainEnum.WORK,
                head_version="v001",
                option_ranking=["Option A", "Option B"],
                utility_decomposition={"impact": 0.8, "learning": 0.6},
                confidence=0.75,
                used_core_variables=["risk_tolerance"],
                used_evidence_types=["historical_behavior"],
            )
        ],
        final_decision=decision,
        decision_mode=DecisionMode.DIRECT,
        uncertainty=0.25,
        output_text="I would go with Option A.",
        created_at=datetime.now(timezone.utc),
    )


class TestEventCollector:
    def test_collect_agreement(self):
        trace = _make_trace()
        event, candidate = collect_event(trace, "Option A")
        assert event.event_type == RuntimeEventType.OUTCOME_OBSERVED
        assert event.payload["agreed"] is True
        assert candidate.observed_choice == "Option A"
        assert candidate.originating_trace_id == trace.trace_id

    def test_collect_disagreement(self):
        trace = _make_trace()
        event, candidate = collect_event(trace, "Option B", user_reasoning="I prefer safety")
        assert event.event_type == RuntimeEventType.DISAGREEMENT_FLAGGED
        assert event.payload["agreed"] is False
        assert candidate.observed_reasoning == "I prefer safety"

    def test_collect_manual_case(self):
        candidate = collect_manual_case(
            domain=DomainEnum.WORK,
            context="Choosing between two job offers",
            option_set=["Company A", "Company B"],
            actual_choice="Company A",
            reasoning="Better growth trajectory",
        )
        assert candidate.source_type == CandidateSourceType.USER_REFLECTION
        assert candidate.ground_truth_confidence == 0.9


class TestCaseManager:
    def test_promote_valid_candidate(self):
        candidate = CandidateCalibrationCase(
            candidate_id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc),
            source_type=CandidateSourceType.RUNTIME_TRACE,
            domain_label=DomainEnum.WORK,
            observed_context="Should I take the risky project or the safe one?",
            option_set=["risky", "safe"],
            observed_choice="risky",
            stakes=OrdinalTriLevel.HIGH,
            reversibility=OrdinalTriLevel.MEDIUM,
            ground_truth_confidence=0.85,
        )
        case = promote_candidate(candidate, task_type="prioritization")
        assert case is not None
        assert case.actual_choice == "risky"
        assert case.task_type == "prioritization"
        assert candidate.promoted_to_calibration_case is True

    def test_reject_low_confidence(self):
        candidate = CandidateCalibrationCase(
            candidate_id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc),
            source_type=CandidateSourceType.RUNTIME_TRACE,
            domain_label=DomainEnum.WORK,
            observed_context="Some context here for testing",
            option_set=["A", "B"],
            observed_choice="A",
            stakes=OrdinalTriLevel.LOW,
            reversibility=OrdinalTriLevel.HIGH,
            ground_truth_confidence=0.3,
        )
        case = promote_candidate(candidate)
        assert case is None
        assert candidate.promoted_to_calibration_case is False

    def test_reject_choice_not_in_options(self):
        candidate = CandidateCalibrationCase(
            candidate_id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc),
            source_type=CandidateSourceType.RUNTIME_TRACE,
            domain_label=DomainEnum.WORK,
            observed_context="Enough context for the quality gate",
            option_set=["A", "B"],
            observed_choice="C",
            stakes=OrdinalTriLevel.MEDIUM,
            reversibility=OrdinalTriLevel.MEDIUM,
            ground_truth_confidence=0.9,
        )
        case = promote_candidate(candidate)
        assert case is None


class TestStateUpdater:
    def test_apply_evaluation_updates_reliability(self):
        twin = _load_twin()
        original_work_reliability = twin.domain_heads[0].head_reliability

        evaluation = TwinEvaluation(
            evaluation_id=str(uuid.uuid4()),
            twin_state_version="v001",
            calibration_case_ids=["c1", "c2", "c3", "c4"],
            choice_similarity=0.9,
            domain_reliability={"work": 0.95},
            evaluated_at=datetime.now(timezone.utc),
        )

        updated = apply_evaluation(twin, evaluation)

        # Should have moved toward 0.95
        assert updated.domain_heads[0].head_reliability > original_work_reliability
        assert updated.state_version == "v002"
        assert updated.shared_decision_core.evidence_count == twin.shared_decision_core.evidence_count + 4

    def test_apply_evaluation_preserves_original(self):
        twin = _load_twin()
        original_version = twin.state_version

        evaluation = TwinEvaluation(
            evaluation_id=str(uuid.uuid4()),
            twin_state_version="v001",
            calibration_case_ids=["c1", "c2", "c3"],
            choice_similarity=0.5,
            domain_reliability={"work": 0.5},
            evaluated_at=datetime.now(timezone.utc),
        )

        updated = apply_evaluation(twin, evaluation)
        assert twin.state_version == original_version  # Original not mutated

    def test_skip_update_with_few_cases(self):
        twin = _load_twin()
        original_reliability = twin.domain_heads[0].head_reliability

        evaluation = TwinEvaluation(
            evaluation_id=str(uuid.uuid4()),
            twin_state_version="v001",
            calibration_case_ids=["c1"],
            choice_similarity=0.1,
            domain_reliability={"work": 0.1},
            evaluated_at=datetime.now(timezone.utc),
        )

        updated = apply_evaluation(twin, evaluation)
        # Should NOT have changed reliability (too few cases)
        assert updated.domain_heads[0].head_reliability == original_reliability


class TestCalibrationStore:
    def test_save_and_load_candidate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CalibrationStore(tmpdir, "user-test")
            candidate = CandidateCalibrationCase(
                candidate_id="cand-001",
                created_at=datetime.now(timezone.utc),
                source_type=CandidateSourceType.USER_REFLECTION,
                domain_label=DomainEnum.WORK,
                observed_context="Test context",
                option_set=["A", "B"],
                observed_choice="A",
                stakes=OrdinalTriLevel.MEDIUM,
                reversibility=OrdinalTriLevel.MEDIUM,
                ground_truth_confidence=0.8,
            )
            store.save_candidate(candidate)
            loaded = store.load_candidate("cand-001")
            assert loaded.candidate_id == "cand-001"
            assert loaded.observed_choice == "A"

    def test_save_and_list_cases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CalibrationStore(tmpdir, "user-test")
            for i in range(3):
                case = CalibrationCase(
                    case_id=f"case-{i:03d}",
                    created_at=datetime.now(timezone.utc),
                    domain_label=DomainEnum.WORK,
                    task_type="prioritization",
                    observed_context=f"Context {i}",
                    option_set=["A", "B"],
                    actual_choice="A",
                    stakes=OrdinalTriLevel.MEDIUM,
                    reversibility=OrdinalTriLevel.MEDIUM,
                    confidence_of_ground_truth=0.8,
                )
                store.save_case(case)
            cases = store.list_cases()
            assert len(cases) == 3

    def test_list_unused_cases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CalibrationStore(tmpdir, "user-test")
            for i, used in enumerate([True, False, False]):
                case = CalibrationCase(
                    case_id=f"case-{i:03d}",
                    created_at=datetime.now(timezone.utc),
                    domain_label=DomainEnum.WORK,
                    task_type="test",
                    observed_context=f"Context {i}",
                    option_set=["X", "Y"],
                    actual_choice="X",
                    stakes=OrdinalTriLevel.LOW,
                    reversibility=OrdinalTriLevel.HIGH,
                    confidence_of_ground_truth=0.7,
                    used_for_calibration=used,
                )
                store.save_case(case)
            unused = store.list_cases(used=False)
            assert len(unused) == 2

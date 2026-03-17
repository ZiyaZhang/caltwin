"""Tests for Phase 5a interface changes — must land before other chunks."""
import pytest
from datetime import datetime, timezone
from twin_runtime.domain.models.primitives import ConflictType, DecisionMode, DomainEnum, MergeStrategy, ScopeStatus
from twin_runtime.domain.models.situation import SituationFrame, SituationFeatureVector
from twin_runtime.domain.models.runtime import RuntimeDecisionTrace, HeadAssessment, ConflictReport
from twin_runtime.domain.models.primitives import OrdinalTriLevel, UncertaintyType, OptionStructure


class TestSituationFrameEmptyActivation:
    def test_empty_activation_allowed(self):
        frame = SituationFrame(
            frame_id="test",
            domain_activation_vector={},
            situation_feature_vector=SituationFeatureVector(
                reversibility=OrdinalTriLevel.MEDIUM, stakes=OrdinalTriLevel.MEDIUM,
                uncertainty_type=UncertaintyType.MIXED, controllability=OrdinalTriLevel.MEDIUM,
                option_structure=OptionStructure.CHOOSE_EXISTING,
            ),
            ambiguity_score=0.9,
            scope_status=ScopeStatus.OUT_OF_SCOPE,
            routing_confidence=0.0,
        )
        assert frame.domain_activation_vector == {}


class TestTraceNewFields:
    def test_trace_accepts_empty_assessments(self):
        trace = RuntimeDecisionTrace(
            trace_id="t1", twin_state_version="v1", situation_frame_id="f1",
            activated_domains=[], head_assessments=[],
            final_decision="Refused", decision_mode=DecisionMode.REFUSED,
            uncertainty=1.0, created_at=datetime.now(timezone.utc),
        )
        assert trace.head_assessments == []

    def test_trace_has_query_field(self):
        trace = RuntimeDecisionTrace(
            trace_id="t1", twin_state_version="v1", situation_frame_id="f1",
            activated_domains=[], head_assessments=[],
            final_decision="test", decision_mode=DecisionMode.REFUSED,
            uncertainty=1.0, created_at=datetime.now(timezone.utc),
            query="Should I take the job?",
        )
        assert trace.query == "Should I take the job?"

    def test_trace_has_situation_frame_field(self):
        trace = RuntimeDecisionTrace(
            trace_id="t1", twin_state_version="v1", situation_frame_id="f1",
            activated_domains=[], head_assessments=[],
            final_decision="test", decision_mode=DecisionMode.REFUSED,
            uncertainty=1.0, created_at=datetime.now(timezone.utc),
            situation_frame={"scope_status": "out_of_scope"},
        )
        assert trace.situation_frame["scope_status"] == "out_of_scope"

    def test_trace_has_scope_guard_result_field(self):
        trace = RuntimeDecisionTrace(
            trace_id="t1", twin_state_version="v1", situation_frame_id="f1",
            activated_domains=[], head_assessments=[],
            final_decision="test", decision_mode=DecisionMode.REFUSED,
            uncertainty=1.0, created_at=datetime.now(timezone.utc),
            scope_guard_result={"restricted_hit": True, "matched_terms": ["medical"]},
        )
        assert trace.scope_guard_result["restricted_hit"] is True

    def test_trace_has_refusal_reason_code(self):
        trace = RuntimeDecisionTrace(
            trace_id="t1", twin_state_version="v1", situation_frame_id="f1",
            activated_domains=[], head_assessments=[],
            final_decision="Refused", decision_mode=DecisionMode.REFUSED,
            uncertainty=1.0, created_at=datetime.now(timezone.utc),
            refusal_reason_code="OUT_OF_SCOPE",
        )
        assert trace.refusal_reason_code == "OUT_OF_SCOPE"


class TestConflictReportRankingDivergence:
    def test_has_ranking_divergence_pairs(self):
        report = ConflictReport(
            report_id="r1",
            activated_heads=[DomainEnum.WORK, DomainEnum.MONEY],
            conflict_types=[ConflictType.BELIEF],
            utility_conflict_axes=[],
            ranking_divergence_pairs=["work↔money"],
            resolvable_by_system=False,
            requires_user_clarification=True,
            requires_more_evidence=False,
            final_merge_strategy=MergeStrategy.CLARIFY,
        )
        assert report.ranking_divergence_pairs == ["work↔money"]


class TestInterpretSituationReturnType:
    def test_returns_tuple(self):
        from unittest.mock import MagicMock
        from twin_runtime.application.pipeline.situation_interpreter import interpret_situation
        import json
        from pathlib import Path
        from twin_runtime.domain.models.twin_state import TwinState

        llm = MagicMock()
        llm.ask_structured.return_value = {
            "domain_activation": {"work": 0.9},
            "reversibility": "medium", "stakes": "medium",
            "uncertainty_type": "mixed", "controllability": "medium",
            "option_structure": "choose_existing",
            "ambiguity_score": 0.3, "clarification_questions": [],
        }
        twin = TwinState(**json.loads(Path("tests/fixtures/sample_twin_state.json").read_text()))

        result = interpret_situation("Should I deploy?", twin, llm=llm)
        assert isinstance(result, tuple), "Must return (frame, guard_result) tuple"
        frame, guard_result = result
        assert hasattr(frame, "scope_status")
        # guard_result is None until Chunk 3 adds scope guard
        assert guard_result is None

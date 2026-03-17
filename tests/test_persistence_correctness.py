"""Tests for persistence correctness and evaluator purity."""
import pytest
import time
from unittest.mock import MagicMock
from datetime import datetime, timezone
from twin_runtime.domain.models.primitives import DecisionMode, DomainEnum, ConflictType, MergeStrategy
from twin_runtime.domain.models.calibration import CalibrationCase
from twin_runtime.domain.models.runtime import HeadAssessment, RuntimeDecisionTrace
from twin_runtime.application.calibration.fidelity_evaluator import evaluate_fidelity


def _make_case(case_id="test-1"):
    return CalibrationCase(
        case_id=case_id, created_at=datetime.now(timezone.utc),
        observed_context="test", option_set=["A", "B"],
        actual_choice="A", domain_label=DomainEnum.WORK,
        task_type="test", stakes="high", reversibility="medium",
        confidence_of_ground_truth=0.9,
    )

def _make_trace():
    ha = MagicMock(spec=HeadAssessment)
    ha.domain = DomainEnum.WORK
    ha.option_ranking = ["A", "B"]
    ha.confidence = 0.8
    trace = MagicMock(spec=RuntimeDecisionTrace)
    trace.head_assessments = [ha]
    trace.output_text = "test"
    trace.uncertainty = 0.2
    trace.trace_id = "t1"
    trace.decision_mode = DecisionMode.DIRECT
    return trace


class TestEvaluatorPurity:
    def test_evaluate_fidelity_does_not_mutate_cases(self):
        runner = MagicMock(return_value=_make_trace())
        twin = MagicMock()
        twin.state_version = "v1"
        case = _make_case()
        assert case.used_for_calibration is False
        evaluate_fidelity([case], twin, runner=runner)
        assert case.used_for_calibration is False, "Evaluator must not mutate input cases"


from twin_runtime.infrastructure.backends.json_file.trace_store import JsonFileTraceStore

class TestTraceStoreAlignment:
    def test_save_then_list_finds_trace(self, tmp_path):
        store = JsonFileTraceStore(tmp_path)
        trace = MagicMock(spec=RuntimeDecisionTrace)
        trace.trace_id = "test-trace-1"
        trace.model_dump_json.return_value = '{"trace_id": "test-trace-1"}'
        store.save_trace(trace)
        traces = store.list_traces()
        assert "test-trace-1" in traces

    def test_list_traces_mtime_order(self, tmp_path):
        store = JsonFileTraceStore(tmp_path)
        (tmp_path / "older.json").write_text('{"trace_id": "older"}')
        time.sleep(0.05)
        (tmp_path / "newer.json").write_text('{"trace_id": "newer"}')
        traces = store.list_traces()
        assert traces[0] == "newer"

    def test_list_traces_empty_store(self, tmp_path):
        store = JsonFileTraceStore(tmp_path)
        assert store.list_traces() == []


from twin_runtime.application.pipeline.conflict_arbiter import _detect_utility_conflict, arbitrate

def _make_assessment(domain, ranking, utility=None):
    a = MagicMock(spec=HeadAssessment)
    a.domain = domain
    a.option_ranking = ranking
    a.confidence = 0.8
    a.utility_decomposition = utility or {}
    return a


class TestConflictArbiterSeparation:
    def test_axis_only_returns_preference(self):
        a1 = _make_assessment(DomainEnum.WORK, ["A", "B"], {"growth": 0.9})
        a2 = _make_assessment(DomainEnum.MONEY, ["A", "B"], {"growth": 0.2})
        report = arbitrate([a1, a2])
        assert report is not None
        assert ConflictType.PREFERENCE in report.conflict_types
        assert report.ranking_divergence_pairs == []

    def test_ranking_only_returns_belief(self):
        a1 = _make_assessment(DomainEnum.WORK, ["A", "B", "C"], {"impact": 0.8})
        a2 = _make_assessment(DomainEnum.MONEY, ["C", "B", "A"], {"roi": 0.8})
        report = arbitrate([a1, a2])
        assert report is not None
        assert ConflictType.BELIEF in report.conflict_types
        assert len(report.ranking_divergence_pairs) > 0
        assert report.utility_conflict_axes == []

    def test_both_returns_mixed(self):
        a1 = _make_assessment(DomainEnum.WORK, ["A", "B"], {"shared": 0.9})
        a2 = _make_assessment(DomainEnum.MONEY, ["B", "A"], {"shared": 0.2})
        report = arbitrate([a1, a2])
        assert report is not None
        assert ConflictType.MIXED in report.conflict_types

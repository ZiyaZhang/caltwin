"""Tests for fidelity_evaluator with injected runner."""
import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone

from twin_runtime.domain.models.primitives import DecisionMode, DomainEnum
from twin_runtime.domain.models.calibration import CalibrationCase
from twin_runtime.domain.models.runtime import RuntimeDecisionTrace, HeadAssessment
from twin_runtime.application.calibration.fidelity_evaluator import evaluate_single_case, evaluate_fidelity


def _make_case(case_id="test-1"):
    return CalibrationCase(
        case_id=case_id,
        created_at=datetime.now(timezone.utc),
        observed_context="Should I deploy?",
        option_set=["Deploy", "Wait"],
        actual_choice="Deploy",
        domain_label=DomainEnum.WORK,
        task_type="deployment",
        stakes="high",
        reversibility="medium",
        confidence_of_ground_truth=0.9,
    )


def _make_trace(ranking=None):
    ha = MagicMock(spec=HeadAssessment)
    ha.domain = DomainEnum.WORK
    ha.option_ranking = ranking or ["Deploy", "Wait"]
    ha.confidence = 0.8
    trace = MagicMock(spec=RuntimeDecisionTrace)
    trace.head_assessments = [ha]
    trace.output_text = "Deploy is better"
    trace.uncertainty = 0.2
    trace.trace_id = "trace-1"
    trace.decision_mode = DecisionMode.DIRECT
    return trace


class TestEvaluateSingleCaseInjection:
    def test_uses_injected_runner(self):
        mock_runner = MagicMock(return_value=_make_trace())
        case = _make_case()
        twin = MagicMock()
        result = evaluate_single_case(case, twin, runner=mock_runner)
        mock_runner.assert_called_once()
        assert result.choice_score == 1.0
        assert result.rank == 1

    def test_default_runner_importable(self):
        from twin_runtime.application.calibration.fidelity_evaluator import _get_default_runner
        runner = _get_default_runner()
        assert callable(runner)


class TestFidelityErrorIsolation:
    def test_failed_cases_excluded_from_cf(self):
        mock_runner = MagicMock(side_effect=Exception("API timeout"))
        case = _make_case()
        twin = MagicMock()
        twin.state_version = "v1"
        eval_ = evaluate_fidelity([case], twin, runner=mock_runner)
        assert eval_.choice_similarity == 0.0
        assert eval_.failed_case_count == 1

    def test_mixed_success_and_failure(self):
        good_trace = _make_trace(["Deploy", "Wait"])
        mock_runner = MagicMock(side_effect=[good_trace, Exception("timeout")])
        cases = [_make_case("test-1"), _make_case("test-2")]
        twin = MagicMock()
        twin.state_version = "v1"
        eval_ = evaluate_fidelity(cases, twin, runner=mock_runner)
        assert eval_.choice_similarity == 1.0
        assert eval_.failed_case_count == 1

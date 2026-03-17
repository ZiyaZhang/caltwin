"""Tests for Abstention Correctness KPI."""
import pytest
from twin_runtime.domain.models.calibration import TwinEvaluation
from twin_runtime.domain.models.primitives import DecisionMode
from twin_runtime.application.calibration.fidelity_evaluator import compute_abstention_accuracy


class TestAbstentionField:
    def test_abstention_accuracy_default(self):
        """TwinEvaluation must have abstention_accuracy field, default None."""
        eval_ = TwinEvaluation(
            evaluation_id="test-1",
            twin_state_version="v1",
            calibration_case_ids=["c1"],
            choice_similarity=0.8,
            domain_reliability={"work": 0.8},
            evaluated_at="2026-03-17T00:00:00Z",
        )
        assert eval_.abstention_accuracy is None

    def test_abstention_accuracy_set(self):
        """abstention_accuracy can be set to a value."""
        eval_ = TwinEvaluation(
            evaluation_id="test-2",
            twin_state_version="v1",
            calibration_case_ids=["c1"],
            choice_similarity=0.8,
            domain_reliability={"work": 0.8},
            evaluated_at="2026-03-17T00:00:00Z",
            abstention_accuracy=0.9,
            abstention_case_count=5,
        )
        assert eval_.abstention_accuracy == 0.9
        assert eval_.abstention_case_count == 5


class TestComputeAbstentionAccuracy:
    def test_all_correctly_refused(self):
        modes = [DecisionMode.REFUSED, DecisionMode.DEGRADED, DecisionMode.REFUSED]
        accuracy = compute_abstention_accuracy(modes)
        assert accuracy == 1.0

    def test_mixed_results(self):
        modes = [DecisionMode.REFUSED, DecisionMode.DIRECT, DecisionMode.DEGRADED, DecisionMode.DIRECT]
        accuracy = compute_abstention_accuracy(modes)
        assert accuracy == 0.5

    def test_empty_returns_none(self):
        accuracy = compute_abstention_accuracy([])
        assert accuracy is None

    def test_all_incorrectly_direct(self):
        modes = [DecisionMode.DIRECT, DecisionMode.DIRECT]
        accuracy = compute_abstention_accuracy(modes)
        assert accuracy == 0.0


class TestAbstentionWiredIntoEvaluateFidelity:
    """Verify evaluate_fidelity populates abstention_accuracy from decision modes."""

    def test_evaluate_fidelity_sets_abstention_fields(self):
        """evaluate_fidelity must populate abstention_accuracy and abstention_case_count."""
        from unittest.mock import MagicMock
        from twin_runtime.domain.models.primitives import DomainEnum
        from twin_runtime.domain.models.runtime import HeadAssessment, RuntimeDecisionTrace
        from twin_runtime.domain.models.calibration import CalibrationCase
        from twin_runtime.application.calibration.fidelity_evaluator import evaluate_fidelity

        # Create a mock runner that returns REFUSED mode trace
        mock_trace = MagicMock(spec=RuntimeDecisionTrace)
        mock_trace.head_assessments = [MagicMock(spec=HeadAssessment)]
        mock_trace.head_assessments[0].domain = DomainEnum.WORK
        mock_trace.head_assessments[0].option_ranking = ["A", "B"]
        mock_trace.head_assessments[0].confidence = 0.5
        mock_trace.output_text = "test"
        mock_trace.uncertainty = 0.8
        mock_trace.trace_id = "t1"
        mock_trace.decision_mode = DecisionMode.REFUSED

        mock_runner = MagicMock(return_value=mock_trace)

        case = CalibrationCase(
            case_id="test-oos",
            created_at="2026-03-17T00:00:00Z",
            domain_label=DomainEnum.WORK,
            task_type="test",
            observed_context="out of scope query",
            option_set=["A", "B"],
            actual_choice="A",
            stakes="high",
            reversibility="low",
            confidence_of_ground_truth=0.9,
        )

        twin = MagicMock()
        twin.state_version = "v1"

        eval_ = evaluate_fidelity([case], twin, runner=mock_runner)

        assert eval_.abstention_accuracy is not None
        assert eval_.abstention_accuracy == 1.0  # 1 REFUSED out of 1
        assert eval_.abstention_case_count == 1

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
    """Verify evaluate_fidelity only counts OOS cases (expect_abstention=True) for abstention."""

    @staticmethod
    def _mock_trace(mode=DecisionMode.DIRECT):
        from unittest.mock import MagicMock
        from twin_runtime.domain.models.primitives import DomainEnum
        from twin_runtime.domain.models.runtime import HeadAssessment, RuntimeDecisionTrace
        trace = MagicMock(spec=RuntimeDecisionTrace)
        trace.head_assessments = [MagicMock(spec=HeadAssessment)]
        trace.head_assessments[0].domain = DomainEnum.WORK
        trace.head_assessments[0].option_ranking = ["A", "B"]
        trace.head_assessments[0].confidence = 0.5
        trace.output_text = "test"
        trace.uncertainty = 0.8
        trace.trace_id = "t1"
        trace.decision_mode = mode
        return trace

    @staticmethod
    def _make_case(case_id, expect_abstention=False):
        from twin_runtime.domain.models.primitives import DomainEnum
        from twin_runtime.domain.models.calibration import CalibrationCase
        return CalibrationCase(
            case_id=case_id,
            created_at="2026-03-17T00:00:00Z",
            domain_label=DomainEnum.WORK,
            task_type="test",
            observed_context="query",
            option_set=["A", "B"],
            actual_choice="A",
            stakes="high",
            reversibility="low",
            confidence_of_ground_truth=0.9,
            expect_abstention=expect_abstention,
        )

    def test_oos_case_counted_for_abstention(self):
        """OOS case (expect_abstention=True) with REFUSED → abstention_accuracy=1.0."""
        from unittest.mock import MagicMock
        from twin_runtime.application.calibration.fidelity_evaluator import evaluate_fidelity

        runner = MagicMock(return_value=self._mock_trace(DecisionMode.REFUSED))
        twin = MagicMock()
        twin.state_version = "v1"

        case = self._make_case("oos-1", expect_abstention=True)
        eval_ = evaluate_fidelity([case], twin, runner=runner)

        assert eval_.abstention_accuracy == 1.0
        assert eval_.abstention_case_count == 1

    def test_in_scope_case_not_counted_for_abstention(self):
        """In-scope case (expect_abstention=False) must NOT affect abstention metric."""
        from unittest.mock import MagicMock
        from twin_runtime.application.calibration.fidelity_evaluator import evaluate_fidelity

        runner = MagicMock(return_value=self._mock_trace(DecisionMode.DIRECT))
        twin = MagicMock()
        twin.state_version = "v1"

        case = self._make_case("normal-1", expect_abstention=False)
        eval_ = evaluate_fidelity([case], twin, runner=runner)

        assert eval_.abstention_accuracy is None  # No OOS cases → None
        assert eval_.abstention_case_count == 0

    def test_mixed_cases_only_oos_affects_abstention(self):
        """Mix of in-scope and OOS cases: abstention only from OOS."""
        from unittest.mock import MagicMock
        from twin_runtime.application.calibration.fidelity_evaluator import evaluate_fidelity

        direct_trace = self._mock_trace(DecisionMode.DIRECT)
        refused_trace = self._mock_trace(DecisionMode.REFUSED)
        runner = MagicMock(side_effect=[direct_trace, refused_trace, direct_trace])
        twin = MagicMock()
        twin.state_version = "v1"

        cases = [
            self._make_case("normal-1", expect_abstention=False),
            self._make_case("oos-1", expect_abstention=True),
            self._make_case("normal-2", expect_abstention=False),
        ]
        eval_ = evaluate_fidelity(cases, twin, runner=runner)

        # Only 1 OOS case, it was REFUSED → 1.0
        assert eval_.abstention_accuracy == 1.0
        assert eval_.abstention_case_count == 1
        # CF should still be computed from all 3 cases
        assert len(eval_.case_details) == 3

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

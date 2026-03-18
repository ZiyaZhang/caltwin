"""Tests for time decay functions."""
import pytest
import math
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from twin_runtime.application.calibration.time_decay import (
    time_decay_weight,
    calibration_decay_weight,
    evidence_decay_weight,
    case_age_days,
)


class TestTimeDecayWeight:
    def test_zero_age_returns_one(self):
        assert time_decay_weight(0, 60, 0.1) == 1.0

    def test_negative_age_returns_one(self):
        assert time_decay_weight(-5, 60, 0.1) == 1.0

    def test_at_half_life_approximately_half(self):
        w = time_decay_weight(60, 60, 0.0)
        assert abs(w - 0.5) < 0.01

    def test_floor_prevents_zero(self):
        w = time_decay_weight(10000, 60, 0.1)
        assert w >= 0.1

    def test_very_old_approaches_floor(self):
        w = time_decay_weight(365 * 5, 60, 0.1)
        assert abs(w - 0.1) < 0.01

    def test_newer_has_higher_weight(self):
        assert time_decay_weight(10, 60, 0.1) > time_decay_weight(100, 60, 0.1)

    def test_evidence_defaults(self):
        w = evidence_decay_weight(60)
        assert abs(w - 0.55) < 0.01

    def test_calibration_defaults(self):
        w = calibration_decay_weight(120)
        assert abs(w - 0.625) < 0.01


class TestCaseAgeDays:
    def test_uses_decision_occurred_at_when_present(self):
        case = MagicMock()
        case.decision_occurred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        case.created_at = datetime(2026, 3, 1, tzinfo=timezone.utc)
        age = case_age_days(case, datetime(2026, 3, 18, tzinfo=timezone.utc))
        assert age > 70

    def test_falls_back_to_created_at(self):
        case = MagicMock()
        case.decision_occurred_at = None
        case.created_at = datetime(2026, 3, 1, tzinfo=timezone.utc)
        age = case_age_days(case, datetime(2026, 3, 18, tzinfo=timezone.utc))
        assert abs(age - 17) < 0.1


class TestModelFields:
    def test_calibration_case_has_decision_occurred_at(self):
        from twin_runtime.domain.models.calibration import CalibrationCase

        case = CalibrationCase(
            case_id="t1",
            created_at=datetime.now(timezone.utc),
            domain_label="work",
            task_type="test",
            observed_context="test context here",
            option_set=["A", "B"],
            actual_choice="A",
            stakes="high",
            reversibility="medium",
            confidence_of_ground_truth=0.9,
            decision_occurred_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
        assert case.decision_occurred_at is not None

    def test_evaluation_case_detail_has_decay_weight(self):
        from twin_runtime.domain.models.calibration import EvaluationCaseDetail

        d = EvaluationCaseDetail(
            case_id="t1",
            domain="work",
            task_type="test",
            observed_context="test",
            choice_score=0.8,
            prediction_ranking=["A"],
            actual_choice="A",
            confidence_at_prediction=0.8,
            residual_direction="",
            time_decay_weight=0.55,
        )
        assert d.time_decay_weight == 0.55

    def test_twin_evaluation_has_weighted_fields(self):
        from twin_runtime.domain.models.calibration import TwinEvaluation

        e = TwinEvaluation(
            evaluation_id="e1",
            twin_state_version="v1",
            calibration_case_ids=["c1"],
            choice_similarity=0.8,
            domain_reliability={"work": 0.8},
            evaluated_at=datetime.now(timezone.utc),
            weighted_choice_similarity=0.75,
        )
        assert e.weighted_choice_similarity == 0.75


class TestWeightedFidelity:
    """Tests for time-decayed weighted fidelity metrics integration."""

    def test_weighted_differs_from_raw_when_ages_differ(self):
        """Old low-score case + recent high-score case: weighted CF > raw CF."""
        from twin_runtime.domain.models.primitives import DecisionMode, DomainEnum
        from twin_runtime.domain.models.runtime import HeadAssessment, RuntimeDecisionTrace
        from twin_runtime.domain.models.calibration import CalibrationCase
        from twin_runtime.application.calibration.fidelity_evaluator import evaluate_fidelity

        def _case(case_id, age_days, actual_choice):
            """Create case with specified actual_choice."""
            return CalibrationCase(
                case_id=case_id,
                created_at=datetime.now(timezone.utc) - timedelta(days=age_days),
                domain_label=DomainEnum.WORK,
                task_type="test",
                observed_context="test context here",
                option_set=["A", "B"],
                actual_choice=actual_choice,
                stakes="medium",
                reversibility="medium",
                confidence_of_ground_truth=0.9,
            )

        def _trace():
            """Twin always predicts ['A', 'B']."""
            ha = MagicMock(spec=HeadAssessment)
            ha.domain = DomainEnum.WORK
            ha.option_ranking = ["A", "B"]
            ha.confidence = 0.8
            t = MagicMock(spec=RuntimeDecisionTrace)
            t.head_assessments = [ha]
            t.output_text = "test"
            t.uncertainty = 0.2
            t.trace_id = "t1"
            t.decision_mode = DecisionMode.DIRECT
            return t

        # Old case (300 days) - actual='B' so twin is wrong (score=0.5)
        # Recent case (5 days) - actual='A' so twin is right (score=1.0)
        old_case = _case("old", 300, "B")
        new_case = _case("new", 5, "A")

        runner = MagicMock(side_effect=[_trace(), _trace()])
        twin = MagicMock()
        twin.state_version = "v1"

        eval_ = evaluate_fidelity([old_case, new_case], twin, runner=runner)

        # Raw: (0.5 + 1.0) / 2 = 0.75  (old case scores 0.5 since B is rank 2)
        assert eval_.choice_similarity == 0.75
        # Weighted: recent high-weight (1.0) + old low-weight (0.5) -> > 0.75
        assert eval_.weighted_choice_similarity is not None
        assert eval_.weighted_choice_similarity > eval_.choice_similarity
        # Decay params should be recorded
        assert eval_.decay_params_used is not None
        assert eval_.decay_params_used["half_life"] == 120.0
        assert eval_.decay_params_used["floor"] == 0.25

    def test_weighted_equals_raw_when_same_age(self):
        """All cases same age: weighted == raw."""
        from twin_runtime.domain.models.primitives import DecisionMode, DomainEnum
        from twin_runtime.domain.models.runtime import HeadAssessment, RuntimeDecisionTrace
        from twin_runtime.domain.models.calibration import CalibrationCase
        from twin_runtime.application.calibration.fidelity_evaluator import evaluate_fidelity

        def _case(case_id):
            return CalibrationCase(
                case_id=case_id,
                created_at=datetime.now(timezone.utc) - timedelta(days=10),
                domain_label=DomainEnum.WORK,
                task_type="test",
                observed_context="test context here",
                option_set=["A", "B"],
                actual_choice="A",
                stakes="medium",
                reversibility="medium",
                confidence_of_ground_truth=0.9,
            )

        def _trace():
            ha = MagicMock(spec=HeadAssessment)
            ha.domain = DomainEnum.WORK
            ha.option_ranking = ["A", "B"]
            ha.confidence = 0.8
            t = MagicMock(spec=RuntimeDecisionTrace)
            t.head_assessments = [ha]
            t.output_text = "test"
            t.uncertainty = 0.2
            t.trace_id = "t1"
            t.decision_mode = DecisionMode.DIRECT
            return t

        runner = MagicMock(side_effect=[_trace(), _trace()])
        twin = MagicMock()
        twin.state_version = "v1"

        eval_ = evaluate_fidelity([_case("c1"), _case("c2")], twin, runner=runner)

        # When ages are identical, weighted and raw should be the same
        assert eval_.weighted_choice_similarity == eval_.choice_similarity

    def test_compute_fidelity_score_weighted_mode(self):
        """compute_fidelity_score(weighted=True) uses decay weights."""
        from twin_runtime.domain.models.calibration import (
            EvaluationCaseDetail, TwinEvaluation, DomainEnum,
        )
        from twin_runtime.application.calibration.fidelity_evaluator import compute_fidelity_score

        # Two cases: one high-weight high-score, one low-weight low-score
        details = [
            EvaluationCaseDetail(
                case_id="c1", domain=DomainEnum.WORK, task_type="test",
                observed_context="test", choice_score=1.0,
                prediction_ranking=["A"], actual_choice="A",
                confidence_at_prediction=0.8, residual_direction="",
                time_decay_weight=0.95,  # recent
            ),
            EvaluationCaseDetail(
                case_id="c2", domain=DomainEnum.WORK, task_type="test",
                observed_context="test", choice_score=0.0,
                prediction_ranking=["B"], actual_choice="A",
                confidence_at_prediction=0.8, residual_direction="miss",
                time_decay_weight=0.30,  # old
            ),
        ]
        ev = TwinEvaluation(
            evaluation_id="e1", twin_state_version="v1",
            calibration_case_ids=["c1", "c2"],
            choice_similarity=0.5,
            domain_reliability={"work": 0.5},
            evaluated_at=datetime.now(timezone.utc),
            case_details=details,
        )

        raw_score = compute_fidelity_score(ev, weighted=False)
        weighted_score = compute_fidelity_score(ev, weighted=True)

        # Raw CF = 0.5 (uniform average)
        assert abs(raw_score.choice_fidelity.value - 0.5) < 0.01
        # Weighted CF > 0.5 (high-weight case scored 1.0)
        assert weighted_score.choice_fidelity.value > 0.5
        # Weighted CF = 0.95*1.0 / (0.95+0.30) = 0.76
        assert abs(weighted_score.choice_fidelity.value - 0.76) < 0.02

    def test_compute_fidelity_score_weighted_handles_pre5c_evaluation(self):
        """weighted=True gracefully handles evaluations without weighted fields."""
        from twin_runtime.domain.models.calibration import (
            EvaluationCaseDetail, TwinEvaluation, DomainEnum,
        )
        from twin_runtime.application.calibration.fidelity_evaluator import compute_fidelity_score

        # Pre-5c case_details: time_decay_weight defaults to 1.0
        details = [
            EvaluationCaseDetail(
                case_id="c1", domain=DomainEnum.WORK, task_type="test",
                observed_context="test", choice_score=0.8,
                prediction_ranking=["A"], actual_choice="A",
                confidence_at_prediction=0.8, residual_direction="",
                # time_decay_weight defaults to 1.0
            ),
        ]
        ev = TwinEvaluation(
            evaluation_id="e1", twin_state_version="v1",
            calibration_case_ids=["c1"],
            choice_similarity=0.8,
            domain_reliability={"work": 0.8},
            evaluated_at=datetime.now(timezone.utc),
            case_details=details,
            # weighted_choice_similarity is None (pre-5c)
        )

        # Should not raise
        score = compute_fidelity_score(ev, weighted=True)
        assert abs(score.choice_fidelity.value - 0.8) < 0.01

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

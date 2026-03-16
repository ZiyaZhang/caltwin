# tests/test_micro_calibration.py
"""Tests for micro-calibration engine."""
import pytest
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import MagicMock
from twin_runtime.application.calibration.micro_calibration import (
    recalibrate_confidence, apply_outcome_update, apply_update,
)
from twin_runtime.domain.models.calibration import OutcomeRecord, MicroCalibrationUpdate
from twin_runtime.domain.models.primitives import (
    DomainEnum, DecisionMode, OutcomeSource, MicroCalibrationTrigger,
)


@pytest.fixture
def sample_twin():
    import json
    from twin_runtime.domain.models.twin_state import TwinState
    with open("tests/fixtures/sample_twin_state.json") as f:
        return TwinState(**json.load(f))


@pytest.fixture
def sample_trace():
    trace = MagicMock()
    trace.activated_domains = [DomainEnum.WORK]
    trace.decision_mode = DecisionMode.DIRECT
    trace.uncertainty = 0.27
    trace.head_assessments = [MagicMock(domain=DomainEnum.WORK, confidence=0.73)]
    trace.twin_state_version = "v002"
    trace.trace_id = "trace-1"
    return trace


class TestRecalibrateConfidence:
    def test_returns_update_for_direct_trace(self, sample_twin, sample_trace):
        update = recalibrate_confidence(sample_trace, sample_twin)
        assert update is not None
        assert update.trigger == MicroCalibrationTrigger.CONFIDENCE_RECAL
        assert update.learning_rate_used == 0.01
        assert update.applied is False

    def test_skips_refused_trace(self, sample_twin, sample_trace):
        sample_trace.decision_mode = DecisionMode.REFUSED
        update = recalibrate_confidence(sample_trace, sample_twin)
        assert update is None

    def test_delta_within_bounds(self, sample_twin, sample_trace):
        update = recalibrate_confidence(sample_trace, sample_twin)
        if update:
            for key, delta in update.parameter_deltas.items():
                assert abs(delta) <= 0.02


class TestApplyOutcomeUpdate:
    def _make_outcome(self, rank=1):
        return OutcomeRecord(
            outcome_id="out-1", trace_id="t1", user_id="test",
            actual_choice="A", outcome_source=OutcomeSource.USER_CORRECTION,
            prediction_rank=rank, confidence_at_prediction=0.73,
            domain=DomainEnum.WORK, created_at=datetime.now(timezone.utc),
        )

    def test_hit_boosts_reliability(self, sample_twin):
        outcome = self._make_outcome(rank=1)
        update = apply_outcome_update(outcome, sample_twin)
        assert update is not None
        assert update.trigger == MicroCalibrationTrigger.OUTCOME_UPDATE
        has_positive = any(d > 0 for d in update.parameter_deltas.values())
        assert has_positive

    def test_miss_decreases_reliability(self, sample_twin):
        outcome = self._make_outcome(rank=None)
        update = apply_outcome_update(outcome, sample_twin)
        assert update is not None
        has_negative = any(d < 0 for d in update.parameter_deltas.values())
        assert has_negative

    def test_learning_rate_005(self, sample_twin):
        outcome = self._make_outcome()
        update = apply_outcome_update(outcome, sample_twin)
        assert update.learning_rate_used == 0.05


class TestApplyUpdate:
    def test_applies_delta(self, sample_twin):
        old_risk = sample_twin.shared_decision_core.risk_tolerance
        update = MicroCalibrationUpdate(
            update_id="mcu-1", twin_state_version="v002",
            trigger=MicroCalibrationTrigger.OUTCOME_UPDATE,
            created_at=datetime.now(timezone.utc),
            parameter_deltas={"shared_decision_core.risk_tolerance": 0.03},
            previous_values={"shared_decision_core.risk_tolerance": old_risk},
            learning_rate_used=0.05, rationale="test",
        )
        new_twin = apply_update(update, sample_twin)
        assert new_twin.shared_decision_core.risk_tolerance == pytest.approx(old_risk + 0.03, abs=0.001)
        assert update.applied is True
        assert update.applied_at is not None

    def test_clamps_to_01(self, sample_twin):
        update = MicroCalibrationUpdate(
            update_id="mcu-2", twin_state_version="v002",
            trigger=MicroCalibrationTrigger.OUTCOME_UPDATE,
            created_at=datetime.now(timezone.utc),
            parameter_deltas={"shared_decision_core.risk_tolerance": 999},
            previous_values={"shared_decision_core.risk_tolerance": 0.5},
            learning_rate_used=0.05, rationale="test",
        )
        new_twin = apply_update(update, sample_twin)
        assert new_twin.shared_decision_core.risk_tolerance <= 1.0

    def test_max_delta_enforced(self, sample_twin):
        update = MicroCalibrationUpdate(
            update_id="mcu-3", twin_state_version="v002",
            trigger=MicroCalibrationTrigger.OUTCOME_UPDATE,
            created_at=datetime.now(timezone.utc),
            parameter_deltas={"shared_decision_core.risk_tolerance": 0.5},
            previous_values={"shared_decision_core.risk_tolerance": 0.5},
            learning_rate_used=0.05, rationale="test",
        )
        old = sample_twin.shared_decision_core.risk_tolerance
        new_twin = apply_update(update, sample_twin)
        actual_delta = abs(new_twin.shared_decision_core.risk_tolerance - old)
        assert actual_delta <= 0.05

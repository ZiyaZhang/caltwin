"""Tests for drift detection."""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
from twin_runtime.domain.models.primitives import DomainEnum, DecisionMode
from twin_runtime.domain.models.calibration import CalibrationCase
from twin_runtime.domain.models.runtime import RuntimeDecisionTrace, HeadAssessment
from twin_runtime.application.calibration.drift_detector import detect_drift, _jsd


def _case(domain, task_type, choice, days_ago):
    return CalibrationCase(
        case_id=f"c-{days_ago}-{choice}",
        created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        domain_label=domain, task_type=task_type,
        observed_context="test", option_set=["A", "B"],
        actual_choice=choice, stakes="medium", reversibility="medium",
        confidence_of_ground_truth=0.9,
    )


def _trace(days_ago, axis_scores, mode=DecisionMode.DIRECT):
    ha = MagicMock(spec=HeadAssessment)
    ha.domain = DomainEnum.WORK
    ha.option_ranking = ["A"]
    ha.confidence = 0.8
    ha.utility_decomposition = axis_scores
    t = MagicMock(spec=RuntimeDecisionTrace)
    t.head_assessments = [ha]
    t.decision_mode = mode
    t.created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return t


class TestJSD:
    def test_identical_distributions(self):
        assert _jsd([0.5, 0.5], [0.5, 0.5]) < 0.01
    def test_opposite_distributions(self):
        assert _jsd([0.99, 0.01], [0.01, 0.99]) > 0.5


class TestDomainDrift:
    def test_detects_choice_shift(self):
        twin = MagicMock()
        twin.state_version = "v1"
        # Historical: mostly A. Recent: mostly B.
        cases = (
            [_case(DomainEnum.WORK, "test", "A", d) for d in range(60, 120)] +
            [_case(DomainEnum.WORK, "test", "B", d) for d in range(0, 20)]
        )
        report = detect_drift(cases, [], twin, recent_window_days=30, historical_window_days=180)
        assert len(report.domain_signals) > 0
        assert "shifted" in report.domain_signals[0].direction

    def test_no_drift_on_stable_data(self):
        twin = MagicMock()
        twin.state_version = "v1"
        cases = [_case(DomainEnum.WORK, "test", "A", d) for d in range(0, 100)]
        report = detect_drift(cases, [], twin)
        assert len(report.domain_signals) == 0

    def test_skips_insufficient_data(self):
        twin = MagicMock()
        twin.state_version = "v1"
        cases = [_case(DomainEnum.WORK, "test", "A", 5)]  # Only 1 case
        report = detect_drift(cases, [], twin)
        assert len(report.domain_signals) == 0


class TestAxisDrift:
    def test_detects_axis_shift(self):
        twin = MagicMock()
        twin.state_version = "v1"
        # Historical: growth=0.8. Recent: growth=0.3.
        traces = (
            [_trace(d, {"growth": 0.8}) for d in range(60, 120)] +
            [_trace(d, {"growth": 0.3}) for d in range(0, 20)]
        )
        report = detect_drift([], traces, twin, recent_window_days=30, historical_window_days=180)
        assert len(report.axis_signals) > 0
        assert "decreased" in report.axis_signals[0].direction

    def test_excludes_refused_traces(self):
        twin = MagicMock()
        twin.state_version = "v1"
        traces = [_trace(d, {"growth": 0.8}, mode=DecisionMode.REFUSED) for d in range(0, 30)]
        report = detect_drift([], traces, twin)
        assert len(report.axis_signals) == 0

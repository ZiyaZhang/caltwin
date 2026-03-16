"""Tests for outcome tracking flow."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from twin_runtime.application.calibration.outcome_tracker import record_outcome
from twin_runtime.domain.models.primitives import DomainEnum, OutcomeSource, DecisionMode


class TestRecordOutcome:
    def _mock_trace(self):
        trace = MagicMock()
        trace.trace_id = "t-1"
        trace.uncertainty = 0.27
        trace.twin_state_version = "v002"
        trace.activated_domains = [DomainEnum.WORK]
        ha = MagicMock()
        ha.domain = DomainEnum.WORK
        ha.confidence = 0.73
        ha.option_ranking = ["选项A", "选项B"]
        trace.head_assessments = [ha]
        return trace

    def test_basic_outcome(self):
        trace = self._mock_trace()
        trace_store = MagicMock()
        trace_store.load_trace.return_value = trace
        cal_store = MagicMock()
        cal_store.save_outcome.return_value = "out-1"
        twin = MagicMock()
        twin.user_id = "user-ziya"

        outcome, update = record_outcome(
            trace_id="t-1",
            actual_choice="选项A",
            source=OutcomeSource.USER_CORRECTION,
            twin=twin,
            trace_store=trace_store,
            calibration_store=cal_store,
        )
        assert outcome.trace_id == "t-1"
        assert outcome.prediction_rank == 1
        assert outcome.choice_matched_prediction is True
        cal_store.save_outcome.assert_called_once()

    def test_miss_outcome(self):
        trace = self._mock_trace()
        trace_store = MagicMock()
        trace_store.load_trace.return_value = trace
        cal_store = MagicMock()
        twin = MagicMock()
        twin.user_id = "user-ziya"

        outcome, _ = record_outcome(
            trace_id="t-1",
            actual_choice="选项C",
            source=OutcomeSource.USER_CORRECTION,
            twin=twin,
            trace_store=trace_store,
            calibration_store=cal_store,
        )
        assert outcome.prediction_rank is None
        assert outcome.choice_matched_prediction is False

    def test_returns_update_without_applying(self):
        trace = self._mock_trace()
        trace_store = MagicMock()
        trace_store.load_trace.return_value = trace
        cal_store = MagicMock()
        twin = MagicMock()
        twin.user_id = "user-ziya"

        _, update = record_outcome(
            trace_id="t-1",
            actual_choice="选项A",
            source=OutcomeSource.USER_CORRECTION,
            twin=twin,
            trace_store=trace_store,
            calibration_store=cal_store,
        )
        if update:
            assert update.applied is False


class TestOutcomeE2E:
    def _mock_trace(self):
        from unittest.mock import MagicMock
        trace = MagicMock()
        trace.trace_id = "t-1"
        trace.uncertainty = 0.27
        trace.twin_state_version = "v002"
        trace.activated_domains = [DomainEnum.WORK]
        ha = MagicMock()
        ha.domain = DomainEnum.WORK
        ha.confidence = 0.73
        ha.option_ranking = ["选项A", "选项B"]
        trace.head_assessments = [ha]
        return trace

    def test_full_outcome_flow(self):
        import json
        from unittest.mock import MagicMock
        from twin_runtime.domain.models.twin_state import TwinState
        with open("tests/fixtures/sample_twin_state.json") as f:
            twin = TwinState(**json.load(f))

        trace = self._mock_trace()
        trace_store = MagicMock()
        trace_store.load_trace.return_value = trace
        cal_store = MagicMock()
        cal_store.save_outcome.return_value = "out-1"

        outcome, update = record_outcome(
            trace_id="t-1", actual_choice="选项A",
            source=OutcomeSource.USER_CORRECTION,
            twin=twin, trace_store=trace_store, calibration_store=cal_store,
        )
        assert outcome.choice_matched_prediction is True
        if update:
            assert update.applied is False

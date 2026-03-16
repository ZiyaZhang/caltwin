"""Tests for Phase 3 domain models."""
import pytest
from twin_runtime.domain.models.primitives import (
    OutcomeSource, MicroCalibrationTrigger, DetectedBiasStatus,
    uncertainty_to_confidence, canonicalize_task_type,
)


class TestNewEnums:
    def test_outcome_source_values(self):
        assert OutcomeSource.USER_CORRECTION == "user_correction"
        assert OutcomeSource.USER_REFLECTION == "user_reflection"
        assert OutcomeSource.OBSERVED == "observed"

    def test_micro_calibration_trigger_values(self):
        assert MicroCalibrationTrigger.CONFIDENCE_RECAL == "confidence_recal"
        assert MicroCalibrationTrigger.OUTCOME_UPDATE == "outcome_update"

    def test_detected_bias_status_values(self):
        assert DetectedBiasStatus.PENDING_REVIEW == "pending_review"
        assert DetectedBiasStatus.ACCEPTED == "accepted"
        assert DetectedBiasStatus.DISMISSED == "dismissed"


class TestUncertaintyToConfidence:
    def test_zero_uncertainty(self):
        assert uncertainty_to_confidence(0.0) == 1.0

    def test_full_uncertainty(self):
        assert uncertainty_to_confidence(1.0) == 0.0

    def test_mid_value(self):
        assert uncertainty_to_confidence(0.27) == 0.73

    def test_rounding(self):
        result = uncertainty_to_confidence(0.333)
        assert result == 0.667


class TestCanonicalizeTaskType:
    def test_lowercase_strip(self):
        assert canonicalize_task_type("  Career_Direction  ") == "career_direction"

    def test_space_to_underscore(self):
        assert canonicalize_task_type("collaboration style") == "collaboration_style"

    def test_already_canonical(self):
        assert canonicalize_task_type("tool_selection") == "tool_selection"


from datetime import datetime, timezone
from twin_runtime.domain.models.calibration import (
    OutcomeRecord, EvaluationCaseDetail, TwinEvaluation,
)
from twin_runtime.domain.models.primitives import DomainEnum, OutcomeSource


class TestOutcomeRecord:
    def _make(self, **overrides):
        defaults = dict(
            outcome_id="out-1",
            trace_id="trace-1",
            user_id="user-ziya",
            actual_choice="选项A",
            outcome_source=OutcomeSource.USER_CORRECTION,
            prediction_rank=1,
            confidence_at_prediction=0.73,
            domain=DomainEnum.WORK,
            created_at=datetime.now(timezone.utc),
        )
        defaults.update(overrides)
        return OutcomeRecord(**defaults)

    def test_valid_hit(self):
        o = self._make(prediction_rank=1)
        assert o.choice_matched_prediction is True

    def test_valid_miss(self):
        o = self._make(prediction_rank=None)
        assert o.choice_matched_prediction is False

    def test_partial_rank2(self):
        o = self._make(prediction_rank=2)
        assert o.choice_matched_prediction is False

    def test_reflection_requires_reasoning(self):
        with pytest.raises(Exception):
            self._make(
                outcome_source=OutcomeSource.USER_REFLECTION,
                actual_reasoning=None,
            )

    def test_reflection_with_reasoning_ok(self):
        o = self._make(
            outcome_source=OutcomeSource.USER_REFLECTION,
            actual_reasoning="因为...",
        )
        assert o.actual_reasoning == "因为..."

    def test_task_type_canonicalized(self):
        o = self._make(task_type="Career Direction")
        assert o.task_type == "career_direction"

    def test_prediction_rank_must_be_ge1(self):
        with pytest.raises(Exception):
            self._make(prediction_rank=0)

    def test_confidence_clamped(self):
        with pytest.raises(Exception):
            self._make(confidence_at_prediction=1.5)


class TestEvaluationCaseDetail:
    def test_valid(self):
        d = EvaluationCaseDetail(
            case_id="c1",
            domain=DomainEnum.WORK,
            task_type="collaboration_style",
            observed_context="写PRD时选择工作方式",
            choice_score=1.0,
            prediction_ranking=["AI先出稿", "自己先写"],
            actual_choice="AI先出稿",
            confidence_at_prediction=0.78,
            residual_direction="",
        )
        assert d.task_type == "collaboration_style"

    def test_task_type_canonicalized(self):
        d = EvaluationCaseDetail(
            case_id="c1",
            domain=DomainEnum.WORK,
            task_type="Collaboration Style",
            observed_context="test",
            choice_score=0.5,
            prediction_ranking=["A"],
            actual_choice="B",
            confidence_at_prediction=0.5,
            residual_direction="twin首选'A'，实际为'B'",
        )
        assert d.task_type == "collaboration_style"

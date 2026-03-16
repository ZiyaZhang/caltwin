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

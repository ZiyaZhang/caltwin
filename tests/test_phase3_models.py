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
            user_id="user-default",
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


from twin_runtime.domain.models.calibration import (
    DetectedBias, BiasCorrectionSuggestion,
    FidelityMetric, TwinFidelityScore, MicroCalibrationUpdate,
)
from twin_runtime.domain.models.primitives import (
    DetectedBiasStatus, BiasCorrectionAction, MicroCalibrationTrigger,
)


class TestDetectedBias:
    def _make(self, **overrides):
        defaults = dict(
            bias_id="bias-1",
            detected_at=datetime.now(timezone.utc),
            domain=DomainEnum.WORK,
            task_type="collaboration_style",
            direction_description="twin偏向自主，用户偏向协作",
            supporting_case_ids=["c1", "c2", "c3"],
            sample_size=3,
            bias_strength=0.67,
            llm_analysis="LLM founder prior",
            status=DetectedBiasStatus.PENDING_REVIEW,
        )
        defaults.update(overrides)
        return DetectedBias(**defaults)

    def test_pending_no_review_fields_ok(self):
        b = self._make()
        assert b.reviewed_at is None

    def test_accepted_requires_review_fields(self):
        with pytest.raises(Exception):
            self._make(status=DetectedBiasStatus.ACCEPTED)

    def test_accepted_with_review_fields_ok(self):
        b = self._make(
            status=DetectedBiasStatus.ACCEPTED,
            reviewed_at=datetime.now(timezone.utc),
            reviewed_by="user-default",
        )
        assert b.status == DetectedBiasStatus.ACCEPTED

    def test_sample_size_mismatch_fails(self):
        with pytest.raises(Exception):
            self._make(sample_size=5)

    def test_with_suggestion(self):
        suggestion = BiasCorrectionSuggestion(
            target_scope={"domain": "work", "task_type": "collaboration_style"},
            correction_action=BiasCorrectionAction.FORCE_COMPARE,
            correction_payload={"instruction": "Prefer collaborative approaches"},
            rationale="Batch eval shows systematic bias",
        )
        b = self._make(suggested_correction=suggestion)
        assert b.suggested_correction.correction_action == BiasCorrectionAction.FORCE_COMPARE


class TestFidelityMetric:
    def test_valid(self):
        m = FidelityMetric(value=0.75, confidence_in_metric=0.67, case_count=20)
        assert m.value == 0.75

    def test_out_of_range(self):
        with pytest.raises(Exception):
            FidelityMetric(value=1.5, confidence_in_metric=0.5, case_count=10)


class TestTwinFidelityScore:
    def _make_metric(self, value=0.75, conf=0.67, count=20):
        return FidelityMetric(value=value, confidence_in_metric=conf, case_count=count)

    def test_valid_score(self):
        s = TwinFidelityScore(
            score_id="fs-1",
            twin_state_version="v002",
            computed_at=datetime.now(timezone.utc),
            choice_fidelity=self._make_metric(),
            reasoning_fidelity=self._make_metric(0.5, 0.3, 10),
            calibration_quality=self._make_metric(0.82, 0.5, 20),
            temporal_stability=self._make_metric(1.0, 0.0, 20),
            overall_score=0.72,
            overall_confidence=0.0,
            total_cases=20,
        )
        assert s.overall_score == 0.72

    def test_domain_breakdown_range_validator(self):
        with pytest.raises(Exception):
            TwinFidelityScore(
                score_id="fs-1",
                twin_state_version="v002",
                computed_at=datetime.now(timezone.utc),
                choice_fidelity=self._make_metric(),
                reasoning_fidelity=self._make_metric(),
                calibration_quality=self._make_metric(),
                temporal_stability=self._make_metric(),
                overall_score=0.72,
                overall_confidence=0.5,
                total_cases=20,
                domain_breakdown={"work": 1.5},
            )


class TestMicroCalibrationUpdate:
    def _make(self, **overrides):
        defaults = dict(
            update_id="mcu-1",
            twin_state_version="v002",
            trigger=MicroCalibrationTrigger.CONFIDENCE_RECAL,
            created_at=datetime.now(timezone.utc),
            parameter_deltas={"shared_decision_core.risk_tolerance": -0.01},
            previous_values={"shared_decision_core.risk_tolerance": 0.65},
            learning_rate_used=0.01,
            rationale="Confidence recalibration after pipeline run",
        )
        defaults.update(overrides)
        return MicroCalibrationUpdate(**defaults)

    def test_valid(self):
        u = self._make()
        assert u.applied is False

    def test_applied_requires_applied_at(self):
        with pytest.raises(Exception):
            self._make(applied=True)

    def test_applied_with_timestamp_ok(self):
        u = self._make(applied=True, applied_at=datetime.now(timezone.utc))
        assert u.applied is True


import tempfile
from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore as JsonCalibrationStore
from twin_runtime.domain.models.calibration import (
    OutcomeRecord, DetectedBias, TwinFidelityScore, FidelityMetric, TwinEvaluation,
)
from twin_runtime.domain.models.primitives import (
    DomainEnum, OutcomeSource, DetectedBiasStatus,
)


class TestCalibrationStorePhase3:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = JsonCalibrationStore(self.tmpdir, "test-user")

    def test_save_and_list_outcomes(self):
        o = OutcomeRecord(
            outcome_id="out-1", trace_id="t1", user_id="test-user",
            actual_choice="A", outcome_source=OutcomeSource.USER_CORRECTION,
            prediction_rank=1, confidence_at_prediction=0.73,
            domain=DomainEnum.WORK, created_at=datetime.now(timezone.utc),
        )
        self.store.save_outcome(o)
        results = self.store.list_outcomes()
        assert len(results) == 1
        assert results[0].outcome_id == "out-1"

    def test_list_outcomes_by_trace(self):
        for i, tid in enumerate(["t1", "t1", "t2"]):
            self.store.save_outcome(OutcomeRecord(
                outcome_id=f"out-{i}", trace_id=tid, user_id="test-user",
                actual_choice="A", outcome_source=OutcomeSource.USER_CORRECTION,
                prediction_rank=1, confidence_at_prediction=0.73,
                domain=DomainEnum.WORK, created_at=datetime.now(timezone.utc),
            ))
        assert len(self.store.list_outcomes(trace_id="t1")) == 2
        assert len(self.store.list_outcomes(trace_id="t2")) == 1

    def test_save_and_list_detected_biases(self):
        b = DetectedBias(
            bias_id="b-1", detected_at=datetime.now(timezone.utc),
            domain=DomainEnum.WORK, direction_description="test",
            supporting_case_ids=["c1", "c2", "c3"], sample_size=3,
            bias_strength=0.67, llm_analysis="test",
            status=DetectedBiasStatus.PENDING_REVIEW,
        )
        self.store.save_detected_bias(b)
        results = self.store.list_detected_biases()
        assert len(results) == 1
        assert len(self.store.list_detected_biases(DetectedBiasStatus.PENDING_REVIEW)) == 1
        assert len(self.store.list_detected_biases(DetectedBiasStatus.ACCEPTED)) == 0

    def test_save_and_list_fidelity_scores(self):
        metric = FidelityMetric(value=0.75, confidence_in_metric=0.67, case_count=20)
        s = TwinFidelityScore(
            score_id="fs-1", twin_state_version="v002",
            computed_at=datetime.now(timezone.utc),
            choice_fidelity=metric, reasoning_fidelity=metric,
            calibration_quality=metric, temporal_stability=metric,
            overall_score=0.75, overall_confidence=0.5, total_cases=20,
        )
        self.store.save_fidelity_score(s)
        results = self.store.list_fidelity_scores(limit=10)
        assert len(results) == 1

    def test_fidelity_scores_ordered_desc(self):
        metric = FidelityMetric(value=0.75, confidence_in_metric=0.67, case_count=20)
        for i in range(3):
            self.store.save_fidelity_score(TwinFidelityScore(
                score_id=f"fs-{i}", twin_state_version="v002",
                computed_at=datetime(2026, 3, 16+i, tzinfo=timezone.utc),
                choice_fidelity=metric, reasoning_fidelity=metric,
                calibration_quality=metric, temporal_stability=metric,
                overall_score=0.75, overall_confidence=0.5, total_cases=20,
            ))
        results = self.store.list_fidelity_scores(limit=2)
        assert len(results) == 2
        assert results[0].score_id == "fs-2"  # newest first

    def test_list_evaluations(self):
        evals = self.store.list_evaluations()
        assert isinstance(evals, list)

    def test_list_evaluations_ordered_asc(self):
        for i in range(3):
            self.store.save_evaluation(TwinEvaluation(
                evaluation_id=f"ev-{i}", twin_state_version="v002",
                calibration_case_ids=[], choice_similarity=0.75,
                domain_reliability={},
                evaluated_at=datetime(2026, 3, 14+i, tzinfo=timezone.utc),
            ))
        evals = self.store.list_evaluations()
        assert len(evals) == 3
        assert evals[0].evaluation_id == "ev-0"  # oldest first

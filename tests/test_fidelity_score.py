"""Tests for TwinFidelityScore computation (CF, RF, CQ, TS)."""
import pytest
from datetime import datetime, timezone
from twin_runtime.application.calibration.fidelity_evaluator import compute_fidelity_score
from twin_runtime.domain.models.calibration import (
    TwinEvaluation, EvaluationCaseDetail, TwinFidelityScore,
)
from twin_runtime.domain.models.primitives import DomainEnum


def _make_eval(details, choice_sim=0.75, eval_id="ev-1"):
    return TwinEvaluation(
        evaluation_id=eval_id, twin_state_version="v002",
        calibration_case_ids=[d.case_id for d in details],
        choice_similarity=choice_sim,
        domain_reliability={"work": 0.72},
        evaluated_at=datetime.now(timezone.utc),
        case_details=details,
    )

def _make_detail(case_id, rank=1, confidence=0.73, reasoning_score=None,
                 domain=DomainEnum.WORK, task_type="tool_selection"):
    pred = ["A", "B", "C"]
    actual = pred[rank - 1] if rank else "D"
    residual = "" if rank == 1 else f"twin首选'A'，实际为'{actual}'"
    return EvaluationCaseDetail(
        case_id=case_id, domain=domain, task_type=task_type,
        observed_context="test", choice_score=1.0 / rank if rank else 0.0,
        prediction_ranking=pred, actual_choice=actual,
        confidence_at_prediction=confidence, residual_direction=residual,
        reasoning_score=reasoning_score,
    )

class TestChoiceFidelity:
    def test_all_hits(self):
        details = [_make_detail(f"c{i}", rank=1) for i in range(10)]
        ev = _make_eval(details)
        score = compute_fidelity_score(ev)
        assert score.choice_fidelity.value == 1.0

    def test_mixed_results(self):
        details = [_make_detail(f"c{i}", rank=1) for i in range(5)]
        details += [_make_detail(f"c{i+5}", rank=2) for i in range(5)]
        ev = _make_eval(details)
        score = compute_fidelity_score(ev)
        assert 0.5 < score.choice_fidelity.value < 1.0

    def test_confidence_scales_with_case_count(self):
        small = [_make_detail("c1", rank=1)]
        large = [_make_detail(f"c{i}", rank=1) for i in range(30)]
        s1 = compute_fidelity_score(_make_eval(small, eval_id="e1"))
        s2 = compute_fidelity_score(_make_eval(large, eval_id="e2"))
        assert s1.choice_fidelity.confidence_in_metric < s2.choice_fidelity.confidence_in_metric

class TestCalibrationQuality:
    def test_perfect_calibration(self):
        details = [_make_detail(f"c{i}", rank=1, confidence=0.9) for i in range(10)]
        ev = _make_eval(details)
        score = compute_fidelity_score(ev)
        assert score.calibration_quality.value > 0.7

    def test_ece_bins_in_details(self):
        details = [_make_detail(f"c{i}", rank=1, confidence=0.8) for i in range(10)]
        ev = _make_eval(details)
        score = compute_fidelity_score(ev)
        assert "bins" in score.calibration_quality.details

class TestTemporalStability:
    def test_single_eval_high_value_low_confidence(self):
        details = [_make_detail("c1")]
        ev = _make_eval(details)
        score = compute_fidelity_score(ev)
        assert score.temporal_stability.value == 1.0
        assert score.temporal_stability.confidence_in_metric == 0.0

    def test_stable_history(self):
        details = [_make_detail("c1")]
        ev = _make_eval(details, eval_id="ev-3")
        hist = [
            _make_eval(details, choice_sim=0.74, eval_id="ev-1"),
            _make_eval(details, choice_sim=0.75, eval_id="ev-2"),
        ]
        score = compute_fidelity_score(ev, hist)
        assert score.temporal_stability.value > 0.9
        assert score.temporal_stability.confidence_in_metric > 0

    def test_unstable_history(self):
        details = [_make_detail("c1")]
        ev = _make_eval(details, choice_sim=0.9, eval_id="ev-3")
        hist = [
            _make_eval(details, choice_sim=0.3, eval_id="ev-1"),
            _make_eval(details, choice_sim=0.9, eval_id="ev-2"),
        ]
        score = compute_fidelity_score(ev, hist)
        assert score.temporal_stability.value < 0.8

class TestOverallAggregation:
    def test_overall_within_bounds(self):
        details = [_make_detail(f"c{i}", rank=1) for i in range(20)]
        ev = _make_eval(details)
        score = compute_fidelity_score(ev)
        assert 0.0 <= score.overall_score <= 1.0
        assert 0.0 <= score.overall_confidence <= 1.0

    def test_domain_breakdown_valid(self):
        details = [_make_detail(f"c{i}", rank=1) for i in range(5)]
        ev = _make_eval(details)
        score = compute_fidelity_score(ev)
        for v in score.domain_breakdown.values():
            assert 0.0 <= v <= 1.0

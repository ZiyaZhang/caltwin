# tests/test_bias_detector.py
"""Tests for prior bias auto-detection."""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from twin_runtime.application.calibration.bias_detector import detect_biases
from twin_runtime.domain.models.calibration import (
    TwinEvaluation, EvaluationCaseDetail,
)
from twin_runtime.domain.models.primitives import DomainEnum, DetectedBiasStatus


def _make_case_detail(case_id, domain, task_type, rank, context="test context"):
    pred = ["A", "B", "C"]
    actual = pred[0] if rank == 1 else "D"
    residual = "" if rank == 1 else f"twin首选'A'，实际为'{actual}'"
    return EvaluationCaseDetail(
        case_id=case_id, domain=domain, task_type=task_type,
        observed_context=context,
        choice_score=1.0 / rank if rank else 0.0,
        prediction_ranking=pred, actual_choice=actual,
        confidence_at_prediction=0.73, residual_direction=residual,
    )


class TestDetectBiases:
    def test_no_bias_all_hits(self):
        details = [_make_case_detail(f"c{i}", DomainEnum.WORK, "tool_selection", 1) for i in range(5)]
        eval_ = MagicMock(spec=TwinEvaluation)
        eval_.case_details = details
        llm = MagicMock()
        biases = detect_biases(eval_, llm=llm)
        assert len(biases) == 0
        llm.ask_json.assert_not_called()

    def test_detects_bias_when_enough_misses(self):
        details = [
            _make_case_detail("c1", DomainEnum.WORK, "collaboration_style", 2),
            _make_case_detail("c2", DomainEnum.WORK, "collaboration_style", 3),
            _make_case_detail("c3", DomainEnum.WORK, "collaboration_style", 2),
            _make_case_detail("c4", DomainEnum.WORK, "collaboration_style", 1),
        ]
        eval_ = MagicMock(spec=TwinEvaluation)
        eval_.case_details = details
        llm = MagicMock()
        llm.ask_json.return_value = {
            "direction_description": "twin偏向自主",
            "common_pattern": "LLM prior",
            "suggested_instruction": "Prefer collaborative",
        }
        biases = detect_biases(eval_, llm=llm, min_sample=3)
        assert len(biases) == 1
        assert biases[0].status == DetectedBiasStatus.PENDING_REVIEW
        assert biases[0].domain == DomainEnum.WORK
        llm.ask_json.assert_called_once()

    def test_below_min_sample_no_detection(self):
        details = [
            _make_case_detail("c1", DomainEnum.WORK, "collaboration_style", 2),
            _make_case_detail("c2", DomainEnum.WORK, "collaboration_style", 3),
        ]
        eval_ = MagicMock(spec=TwinEvaluation)
        eval_.case_details = details
        llm = MagicMock()
        biases = detect_biases(eval_, llm=llm, min_sample=3)
        assert len(biases) == 0

    def test_below_bias_strength_no_detection(self):
        details = [
            _make_case_detail("c1", DomainEnum.WORK, "collaboration_style", 2),
            _make_case_detail("c2", DomainEnum.WORK, "collaboration_style", 1),
            _make_case_detail("c3", DomainEnum.WORK, "collaboration_style", 1),
            _make_case_detail("c4", DomainEnum.WORK, "collaboration_style", 1),
        ]
        eval_ = MagicMock(spec=TwinEvaluation)
        eval_.case_details = details
        llm = MagicMock()
        biases = detect_biases(eval_, llm=llm, min_sample=3, min_bias_strength=0.6)
        assert len(biases) == 0

    def test_mixed_direction_residuals_no_detection(self):
        details = [
            _make_case_detail("c1", DomainEnum.WORK, "tool_selection", 2, "context1"),
            _make_case_detail("c2", DomainEnum.WORK, "tool_selection", 3, "context2"),
            _make_case_detail("c3", DomainEnum.WORK, "tool_selection", 2, "context3"),
        ]
        details[0].residual_direction = "twin首选'X'，实际为'Y'"
        details[1].residual_direction = "twin首选'Y'，实际为'X'"
        details[2].residual_direction = "twin首选'X'，实际为'Y'"
        eval_ = MagicMock(spec=TwinEvaluation)
        eval_.case_details = details
        llm = MagicMock()
        biases = detect_biases(eval_, llm=llm, min_sample=3)
        # At minimum shouldn't crash

    def test_llm_failure_degrades_gracefully(self):
        details = [_make_case_detail(f"c{i}", DomainEnum.WORK, "collaboration_style", 2) for i in range(4)]
        eval_ = MagicMock(spec=TwinEvaluation)
        eval_.case_details = details
        llm = MagicMock()
        llm.ask_json.side_effect = Exception("LLM failed")
        biases = detect_biases(eval_, llm=llm, min_sample=3)
        assert len(biases) == 1
        assert biases[0].suggested_correction is None
        assert "失败" in biases[0].llm_analysis or "failed" in biases[0].llm_analysis.lower()

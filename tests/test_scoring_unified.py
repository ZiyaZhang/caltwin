"""Tests for unified scoring function, SingleCaseResult, and evaluate_fidelity."""
import pytest
from unittest.mock import patch, MagicMock
from twin_runtime.application.calibration.fidelity_evaluator import (
    choice_similarity, SingleCaseResult,
)


class TestChoiceSimilarity:
    def test_exact_match_top1(self):
        score, rank = choice_similarity(["选项A", "选项B"], "选项A")
        assert score == 1.0
        assert rank == 1

    def test_exact_match_rank2(self):
        score, rank = choice_similarity(["选项A", "选项B"], "选项B")
        assert score == 0.5
        assert rank == 2

    def test_miss(self):
        score, rank = choice_similarity(["选项A", "选项B"], "选项C")
        assert score == 0.0
        assert rank is None

    def test_case_insensitive(self):
        score, rank = choice_similarity(["Python + Pydantic", "TypeScript"], "python + pydantic")
        assert rank == 1

    def test_containment_with_length_guard(self):
        score, rank = choice_similarity(["Plan A/B", "Plan C"], "A")
        assert rank is None

    def test_containment_valid(self):
        score, rank = choice_similarity(["基于现有平台做插件/扩展", "从头造工具"], "基于现有平台做插件")
        assert rank == 1

    def test_empty_ranking(self):
        score, rank = choice_similarity([], "A")
        assert score == 0.0
        assert rank is None

    def test_rank3(self):
        score, rank = choice_similarity(["A", "B", "C"], "C")
        assert rank == 3
        assert abs(score - 1.0/3) < 0.01


class TestEvaluateFidelityPopulatesCaseDetails:
    @patch("twin_runtime.application.calibration.fidelity_evaluator.run")
    def test_case_details_populated(self, mock_run):
        from twin_runtime.application.calibration.fidelity_evaluator import evaluate_fidelity
        from twin_runtime.domain.models.calibration import CalibrationCase
        from twin_runtime.domain.models.primitives import DomainEnum, OrdinalTriLevel
        from datetime import datetime, timezone
        import json

        mock_trace = MagicMock()
        mock_trace.trace_id = "t-1"
        mock_trace.uncertainty = 0.27
        mock_trace.output_text = "I'd go with A"
        ha = MagicMock()
        ha.option_ranking = ["A", "B"]
        ha.domain = DomainEnum.WORK
        mock_trace.head_assessments = [ha]
        mock_run.return_value = mock_trace

        with open("tests/fixtures/sample_twin_state.json") as f:
            from twin_runtime.domain.models.twin_state import TwinState
            twin = TwinState(**json.load(f))

        case = CalibrationCase(
            case_id="c-test", created_at=datetime.now(timezone.utc),
            domain_label=DomainEnum.WORK, task_type="tool_selection",
            observed_context="选择技术栈",
            option_set=["A", "B"], actual_choice="A",
            stakes=OrdinalTriLevel.MEDIUM, reversibility=OrdinalTriLevel.HIGH,
            confidence_of_ground_truth=0.9,
        )

        evaluation = evaluate_fidelity([case], twin)
        assert len(evaluation.case_details) == 1
        detail = evaluation.case_details[0]
        assert detail.case_id == "c-test"
        assert detail.observed_context == "选择技术栈"
        assert detail.confidence_at_prediction == pytest.approx(0.73, abs=0.01)
        assert detail.prediction_ranking == ["A", "B"]
        assert detail.residual_direction == ""  # HIT

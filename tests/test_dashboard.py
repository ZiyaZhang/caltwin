"""Tests for dashboard generation."""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from twin_runtime.application.dashboard.payload import DashboardPayload
from twin_runtime.application.dashboard.generator import generate_dashboard
from twin_runtime.domain.models.calibration import (
    FidelityMetric, TwinFidelityScore, TwinEvaluation, EvaluationCaseDetail,
    DetectedBias,
)
from twin_runtime.domain.models.primitives import DomainEnum, DetectedBiasStatus


@pytest.fixture
def sample_payload():
    metric = FidelityMetric(value=0.75, confidence_in_metric=0.67, case_count=20)
    score = TwinFidelityScore(
        score_id="fs-1", twin_state_version="v002",
        computed_at=datetime.now(timezone.utc),
        choice_fidelity=metric, reasoning_fidelity=metric,
        calibration_quality=FidelityMetric(
            value=0.82, confidence_in_metric=0.5, case_count=20,
            details={"bins": [
                {"range": "[0.0,0.3)", "avg_conf": 0.15, "accuracy": 0.1, "count": 2},
                {"range": "[0.3,0.6)", "avg_conf": 0.45, "accuracy": 0.5, "count": 8},
                {"range": "[0.6,1.0]", "avg_conf": 0.75, "accuracy": 0.8, "count": 10},
            ], "non_empty_bins": 3},
        ),
        temporal_stability=FidelityMetric(value=1.0, confidence_in_metric=0.0, case_count=20),
        overall_score=0.75, overall_confidence=0.0, total_cases=20,
        domain_breakdown={"work": 0.722, "life_planning": 0.667, "money": 1.0},
    )
    eval_ = MagicMock(spec=TwinEvaluation)
    eval_.case_details = [
        EvaluationCaseDetail(
            case_id="c1", domain=DomainEnum.WORK, task_type="collaboration_style",
            observed_context="<script>alert('xss')</script>",
            choice_score=0.5, prediction_ranking=["A", "B"],
            actual_choice="B", confidence_at_prediction=0.73,
            residual_direction="twin首选'A'，实际为'B'",
        ),
    ]
    eval_.evaluation_id = "ev-1"
    twin = MagicMock()
    twin.state_version = "v002"
    twin.id = "twin-ziya"
    return DashboardPayload(
        fidelity_score=score, evaluation=eval_, twin=twin,
    )


class TestDashboardGeneration:
    def test_generates_html(self, sample_payload):
        html = generate_dashboard(sample_payload)
        assert "<html" in html
        assert "Twin Fidelity Report" in html

    def test_html_escapes_user_content(self, sample_payload):
        html = generate_dashboard(sample_payload)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_contains_domain_breakdown(self, sample_payload):
        html = generate_dashboard(sample_payload)
        assert "work" in html
        assert "0.722" in html or "72.2" in html

    def test_contains_svg_radar_chart(self, sample_payload):
        html = generate_dashboard(sample_payload)
        assert "<svg" in html

    def test_contains_ece_calibration_data(self, sample_payload):
        html = generate_dashboard(sample_payload)
        assert "calibration" in html.lower() or "ECE" in html

    def test_contains_footer(self, sample_payload):
        html = generate_dashboard(sample_payload)
        assert "twin-runtime" in html
        assert "OpenClaw" in html

    def test_low_sample_warning_red(self, sample_payload):
        sample_payload.fidelity_score.choice_fidelity = FidelityMetric(
            value=1.0, confidence_in_metric=0.1, case_count=3
        )
        html = generate_dashboard(sample_payload)
        assert "数据不足" in html or "⚠" in html

    def test_low_confidence_warning(self, sample_payload):
        sample_payload.fidelity_score.temporal_stability = FidelityMetric(
            value=1.0, confidence_in_metric=0.0, case_count=1
        )
        html = generate_dashboard(sample_payload)
        assert "置信度不足" in html or "confidence" in html.lower()

    def test_trend_line_with_history(self, sample_payload):
        metric = FidelityMetric(value=0.72, confidence_in_metric=0.5, case_count=20)
        sample_payload.historical_scores = [
            TwinFidelityScore(
                score_id="fs-old", twin_state_version="v001",
                computed_at=datetime(2026, 3, 15, tzinfo=timezone.utc),
                choice_fidelity=metric, reasoning_fidelity=metric,
                calibration_quality=metric, temporal_stability=metric,
                overall_score=0.65, overall_confidence=0.3, total_cases=20,
            ),
        ]
        html = generate_dashboard(sample_payload)
        assert "0.65" in html or "trend" in html.lower()

    def test_bias_section_rendered(self, sample_payload):
        sample_payload.detected_biases = [
            DetectedBias(
                bias_id="b1", detected_at=datetime.now(timezone.utc),
                domain=DomainEnum.WORK, direction_description="twin偏向自主",
                supporting_case_ids=["c1", "c2", "c3"], sample_size=3,
                bias_strength=0.67, llm_analysis="test",
                status=DetectedBiasStatus.ACCEPTED,
                reviewed_at=datetime.now(timezone.utc), reviewed_by="user-ziya",
            ),
        ]
        html = generate_dashboard(sample_payload)
        assert "偏差" in html or "bias" in html.lower()


import tempfile
from pathlib import Path
from twin_runtime.interfaces.cli import dashboard_command


class TestDashboardCommand:
    def test_no_scores_early_exit(self, capsys):
        from unittest.mock import patch, MagicMock
        with patch("twin_runtime.interfaces.cli.CalibrationStore") as MockStore:
            MockStore.return_value.list_fidelity_scores.return_value = []
            dashboard_command(output="/tmp/test_no_scores.html")
            captured = capsys.readouterr()
            assert "No fidelity scores" in captured.out

"""Tests for HTML comparison report generation."""

from twin_runtime.application.comparison.report import generate_comparison_report
from twin_runtime.application.comparison.schemas import (
    AggregateMetrics,
    ComparisonReport,
    DomainBreakdown,
    RunnerOutput,
)


def _make_report():
    return ComparisonReport(
        scenario_set_name="test-scenarios",
        runner_outputs={
            "vanilla": [
                RunnerOutput(runner_id="vanilla", scenario_id="s1", chosen="A", is_correct=True, latency_ms=100),
                RunnerOutput(runner_id="vanilla", scenario_id="s2", chosen="B", is_correct=False, latency_ms=150),
            ],
            "twin": [
                RunnerOutput(runner_id="twin", scenario_id="s1", chosen="A", is_correct=True, latency_ms=200),
                RunnerOutput(runner_id="twin", scenario_id="s2", chosen="A", is_correct=True, latency_ms=250),
            ],
        },
        aggregates={
            "vanilla": AggregateMetrics(
                runner_id="vanilla",
                cf_score=0.5,
                mean_confidence=0.7,
                mean_latency_ms=125,
                total=2,
                correct=1,
                domain_breakdown=[
                    DomainBreakdown(domain="work", cf_score=1.0, count=1, correct=1),
                    DomainBreakdown(domain="money", cf_score=0.0, count=1, correct=0),
                ],
                pairwise_deltas={"vanilla_vs_twin": -0.5},
            ),
            "twin": AggregateMetrics(
                runner_id="twin",
                cf_score=1.0,
                mean_confidence=0.9,
                mean_latency_ms=225,
                total=2,
                correct=2,
                domain_breakdown=[
                    DomainBreakdown(domain="work", cf_score=1.0, count=1, correct=1),
                    DomainBreakdown(domain="money", cf_score=1.0, count=1, correct=1),
                ],
                pairwise_deltas={"twin_vs_vanilla": 0.5},
            ),
        },
    )


class TestGenerateComparisonReport:
    def test_generates_html(self):
        html = generate_comparison_report(_make_report())
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_has_summary_section(self):
        html = generate_comparison_report(_make_report())
        assert "Summary" in html

    def test_has_bar_chart_section(self):
        html = generate_comparison_report(_make_report())
        assert "CF Score Comparison" in html

    def test_has_scenario_table(self):
        html = generate_comparison_report(_make_report())
        assert "Per-Scenario Results" in html

    def test_has_domain_breakdown(self):
        html = generate_comparison_report(_make_report())
        assert "Domain Breakdown" in html

    def test_has_human_baseline(self):
        html = generate_comparison_report(_make_report())
        assert "0.85" in html
        assert "Human" in html

    def test_correct_markers(self):
        html = generate_comparison_report(_make_report())
        assert "\u2713" in html  # checkmark
        assert "\u2717" in html  # cross

    def test_runner_names_in_cards(self):
        html = generate_comparison_report(_make_report())
        assert "vanilla" in html
        assert "twin" in html

    def test_empty_report(self):
        report = ComparisonReport()
        html = generate_comparison_report(report)
        assert "<!DOCTYPE html>" in html

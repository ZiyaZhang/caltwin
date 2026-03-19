"""Tests for comparison data schemas."""

from pathlib import Path

import pytest

from twin_runtime.application.comparison.schemas import (
    AggregateMetrics,
    ComparisonReport,
    ComparisonScenario,
    DomainBreakdown,
    RunnerOutput,
    ScenarioSet,
)

FIXTURES_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "comparison" / "fixtures.json"


class TestComparisonScenario:
    def test_valid_scenario(self):
        s = ComparisonScenario(
            scenario_id="test-01",
            domain="work",
            query="Pick one",
            options=["A", "B"],
            ground_truth="A",
        )
        assert s.ground_truth == "A"

    def test_refuse_ground_truth_allowed(self):
        s = ComparisonScenario(
            scenario_id="test-02",
            domain="work",
            query="Out of scope",
            options=["A", "B"],
            ground_truth="REFUSE",
        )
        assert s.ground_truth == "REFUSE"

    def test_invalid_ground_truth_rejected(self):
        with pytest.raises(ValueError, match="ground_truth"):
            ComparisonScenario(
                scenario_id="test-03",
                domain="work",
                query="Pick one",
                options=["A", "B"],
                ground_truth="C",
            )

    def test_minimum_two_options(self):
        with pytest.raises(ValueError):
            ComparisonScenario(
                scenario_id="test-04",
                domain="work",
                query="Pick one",
                options=["A"],
                ground_truth="A",
            )


class TestScenarioSet:
    def test_load_fixtures(self):
        ss = ScenarioSet.load(FIXTURES_PATH)
        assert len(ss.scenarios) >= 20
        assert ss.name == "ci-baseline-scenarios"

    def test_refuse_scenarios_present(self):
        ss = ScenarioSet.load(FIXTURES_PATH)
        refuse = [s for s in ss.scenarios if s.ground_truth == "REFUSE"]
        assert len(refuse) >= 2

    def test_all_domains_covered(self):
        ss = ScenarioSet.load(FIXTURES_PATH)
        domains = {s.domain for s in ss.scenarios}
        assert domains >= {"work", "money", "life_planning", "relationships", "public_expression"}

    def test_load_bare_list(self, tmp_path):
        import json

        data = [
            {
                "scenario_id": "t1",
                "domain": "work",
                "query": "q",
                "options": ["A", "B"],
                "ground_truth": "A",
            }
        ]
        p = tmp_path / "scenarios.json"
        p.write_text(json.dumps(data))
        ss = ScenarioSet.load(p)
        assert len(ss.scenarios) == 1


class TestRunnerOutput:
    def test_basic_output(self):
        o = RunnerOutput(
            runner_id="vanilla",
            scenario_id="test-01",
            chosen="A",
            is_correct=True,
            confidence=0.9,
            latency_ms=120.0,
        )
        assert o.is_correct is True


class TestAggregateMetrics:
    def test_pairwise_deltas(self):
        m = AggregateMetrics(
            runner_id="twin",
            cf_score=0.85,
            total=20,
            correct=17,
            pairwise_deltas={"twin_vs_vanilla": 0.25, "twin_vs_persona": 0.10},
        )
        assert m.pairwise_deltas["twin_vs_vanilla"] == 0.25

    def test_domain_breakdown(self):
        m = AggregateMetrics(
            runner_id="twin",
            cf_score=0.85,
            total=20,
            correct=17,
            domain_breakdown=[
                DomainBreakdown(domain="work", cf_score=0.9, count=4, correct=3),
            ],
        )
        assert m.domain_breakdown[0].domain == "work"


class TestComparisonReport:
    def test_auto_id(self):
        r = ComparisonReport()
        assert r.report_id.startswith("cmp-")

    def test_with_data(self):
        r = ComparisonReport(
            runner_outputs={"vanilla": []},
            aggregates={},
        )
        assert "vanilla" in r.runner_outputs

"""Tests for ComparisonExecutor and aggregate computation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from twin_runtime.application.comparison.executor import ComparisonExecutor, _compute_aggregates
from twin_runtime.application.comparison.schemas import (
    ComparisonScenario,
    RunnerOutput,
    ScenarioSet,
)


def _make_scenario(sid="t1", domain="work", gt="A"):
    return ComparisonScenario(
        scenario_id=sid,
        domain=domain,
        query="Test",
        options=["A", "B"],
        ground_truth=gt,
    )


def _make_output(runner_id="vanilla", scenario_id="t1", chosen="A", is_correct=True, latency_ms=100.0):
    return RunnerOutput(
        runner_id=runner_id,
        scenario_id=scenario_id,
        chosen=chosen,
        is_correct=is_correct,
        latency_ms=latency_ms,
    )


def _mock_runner(runner_id, outputs):
    """Create a mock runner that returns pre-set outputs."""
    r = MagicMock()
    r.runner_id = runner_id
    call_count = [0]

    def side_effect(scenario, twin):
        idx = call_count[0]
        call_count[0] += 1
        return outputs[idx]

    r.run_scenario.side_effect = side_effect
    return r


class TestExecutorRunAll:
    def test_basic_run(self):
        scenarios = ScenarioSet(scenarios=[
            _make_scenario("s1", "work", "A"),
            _make_scenario("s2", "money", "B"),
        ])
        r1 = _mock_runner("vanilla", [
            _make_output("vanilla", "s1", "A", True),
            _make_output("vanilla", "s2", "A", False),
        ])
        twin = MagicMock()
        executor = ComparisonExecutor([r1], twin)
        report = executor.run_all(scenarios)

        assert "vanilla" in report.runner_outputs
        assert len(report.runner_outputs["vanilla"]) == 2
        assert report.aggregates["vanilla"].cf_score == 0.5
        assert report.aggregates["vanilla"].total == 2
        assert report.aggregates["vanilla"].correct == 1

    def test_multiple_runners(self):
        scenarios = ScenarioSet(scenarios=[_make_scenario("s1")])
        r1 = _mock_runner("vanilla", [_make_output("vanilla", "s1", "A", True)])
        r2 = _mock_runner("twin", [_make_output("twin", "s1", "A", True)])
        twin = MagicMock()
        executor = ComparisonExecutor([r1, r2], twin)
        report = executor.run_all(scenarios)

        assert len(report.aggregates) == 2
        assert report.aggregates["vanilla"].cf_score == 1.0
        assert report.aggregates["twin"].cf_score == 1.0

    def test_runner_filter(self):
        scenarios = ScenarioSet(scenarios=[_make_scenario("s1")])
        r1 = _mock_runner("vanilla", [_make_output("vanilla", "s1", "A", True)])
        r2 = _mock_runner("twin", [_make_output("twin", "s1", "A", True)])
        twin = MagicMock()
        executor = ComparisonExecutor([r1, r2], twin)
        report = executor.run_all(scenarios, runner_ids=["vanilla"])

        assert "vanilla" in report.aggregates
        assert "twin" not in report.aggregates

    def test_progress_callback(self):
        scenarios = ScenarioSet(scenarios=[
            _make_scenario("s1"),
            _make_scenario("s2"),
        ])
        r1 = _mock_runner("vanilla", [
            _make_output("vanilla", "s1", "A", True),
            _make_output("vanilla", "s2", "A", True),
        ])
        twin = MagicMock()
        executor = ComparisonExecutor([r1], twin)
        calls = []
        report = executor.run_all(scenarios, progress_callback=lambda d, t: calls.append((d, t)))
        assert calls == [(1, 2), (2, 2)]


class TestAggregateMetrics:
    def test_pairwise_deltas(self):
        scenarios = {
            "s1": _make_scenario("s1"),
            "s2": _make_scenario("s2"),
        }
        outputs = {
            "vanilla": [
                _make_output("vanilla", "s1", "A", True),
                _make_output("vanilla", "s2", "A", False),
            ],
            "twin": [
                _make_output("twin", "s1", "A", True),
                _make_output("twin", "s2", "A", True),
            ],
        }
        agg = _compute_aggregates(outputs, scenarios)
        assert agg["vanilla"].cf_score == 0.5
        assert agg["twin"].cf_score == 1.0
        assert agg["twin"].pairwise_deltas["twin_vs_vanilla"] == 0.5
        assert agg["vanilla"].pairwise_deltas["vanilla_vs_twin"] == -0.5

    def test_domain_breakdown(self):
        scenarios = {
            "s1": _make_scenario("s1", "work"),
            "s2": _make_scenario("s2", "money"),
            "s3": _make_scenario("s3", "work"),
        }
        outputs = {
            "vanilla": [
                _make_output("vanilla", "s1", "A", True),
                _make_output("vanilla", "s2", "A", False),
                _make_output("vanilla", "s3", "A", True),
            ],
        }
        agg = _compute_aggregates(outputs, scenarios)
        bd = {d.domain: d for d in agg["vanilla"].domain_breakdown}
        assert bd["work"].cf_score == 1.0
        assert bd["work"].count == 2
        assert bd["money"].cf_score == 0.0
        assert bd["money"].count == 1

    def test_empty_outputs(self):
        agg = _compute_aggregates({}, {})
        assert agg == {}


class TestLoadScenarios:
    def test_load_from_path(self, tmp_path):
        import json
        data = {"name": "test", "scenarios": [
            {"scenario_id": "s1", "domain": "work", "query": "q", "options": ["A", "B"], "ground_truth": "A"}
        ]}
        p = tmp_path / "test.json"
        p.write_text(json.dumps(data))
        twin = MagicMock()
        executor = ComparisonExecutor([], twin)
        ss = executor.load_scenarios(p)
        assert len(ss.scenarios) == 1

"""ComparisonExecutor — batch runner + aggregation."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

from twin_runtime.application.comparison.schemas import (
    AggregateMetrics,
    ComparisonReport,
    DomainBreakdown,
    RunnerOutput,
    ScenarioSet,
)

if TYPE_CHECKING:
    from twin_runtime.application.comparison.runners.base import BaseRunner
    from twin_runtime.domain.models.twin_state import TwinState


class ComparisonExecutor:
    """Run comparison scenarios across multiple runners and aggregate results."""

    def __init__(
        self,
        runners: List["BaseRunner"],
        twin: "TwinState",
    ) -> None:
        self._runners = {r.runner_id: r for r in runners}
        self._twin = twin

    def load_scenarios(self, path: Path) -> ScenarioSet:
        """Load scenarios from a JSON file."""
        return ScenarioSet.load(path)

    def run_all(
        self,
        scenario_set: ScenarioSet,
        runner_ids: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> ComparisonReport:
        """Run all scenarios across selected runners and produce a report."""
        runners = self._runners
        if runner_ids:
            runners = {k: v for k, v in runners.items() if k in runner_ids}

        total = len(scenario_set.scenarios) * len(runners)
        done = 0

        all_outputs: Dict[str, List[RunnerOutput]] = defaultdict(list)
        scenarios_by_id = {s.scenario_id: s for s in scenario_set.scenarios}

        for scenario in scenario_set.scenarios:
            for rid, runner in runners.items():
                output = runner.run_scenario(scenario, self._twin)
                all_outputs[rid].append(output)
                done += 1
                if progress_callback:
                    progress_callback(done, total)

        aggregates = _compute_aggregates(all_outputs, scenarios_by_id)

        return ComparisonReport(
            scenario_set_name=scenario_set.name,
            runner_outputs=dict(all_outputs),
            aggregates=aggregates,
        )


def _compute_aggregates(
    all_outputs: Dict[str, List[RunnerOutput]],
    scenarios_by_id: dict,
) -> Dict[str, AggregateMetrics]:
    """Compute per-runner aggregate metrics."""
    aggregates: Dict[str, AggregateMetrics] = {}
    cf_scores: Dict[str, float] = {}

    for runner_id, outputs in all_outputs.items():
        # Split into non-REFUSE (for CF) and REFUSE (for abstention report)
        non_refuse = []
        refuse = []
        for o in outputs:
            scenario = scenarios_by_id.get(o.scenario_id)
            if scenario and scenario.ground_truth == "REFUSE":
                refuse.append(o)
            else:
                non_refuse.append(o)

        # CF is always on the same denominator: non-REFUSE scenarios only
        total = len(non_refuse)
        correct = sum(1 for o in non_refuse if o.is_correct)
        cf_score = correct / total if total > 0 else 0.0
        cf_scores[runner_id] = cf_score

        # Abstention metrics (separate)
        refuse_total = len(refuse)
        refuse_correct = sum(1 for o in refuse if o.is_correct)

        # Uncertainty: use None when no runner populates it (not 0.0)
        uncertainties = [o.uncertainty for o in outputs if o.uncertainty is not None and o.uncertainty > 0]
        mean_uncertainty = sum(uncertainties) / len(uncertainties) if uncertainties else None

        latencies = [o.latency_ms for o in outputs if o.latency_ms > 0]
        mean_latency = sum(latencies) / len(latencies) if latencies else 0.0

        # Domain breakdown always excludes REFUSE (same basis as CF)
        domain_breakdown = _compute_domain_breakdown(outputs, scenarios_by_id, exclude_refuse=True)

        aggregates[runner_id] = AggregateMetrics(
            runner_id=runner_id,
            cf_score=cf_score,
            mean_uncertainty=mean_uncertainty,
            mean_latency_ms=mean_latency,
            total=total,
            correct=correct,
            refuse_total=refuse_total,
            refuse_correct=refuse_correct,
            domain_breakdown=domain_breakdown,
        )

    # Compute pairwise deltas
    runner_ids = list(cf_scores.keys())
    for i, r1 in enumerate(runner_ids):
        for r2 in runner_ids[i + 1:]:
            delta = cf_scores[r1] - cf_scores[r2]
            aggregates[r1].pairwise_deltas[f"{r1}_vs_{r2}"] = round(delta, 4)
            aggregates[r2].pairwise_deltas[f"{r2}_vs_{r1}"] = round(-delta, 4)

    return aggregates


def _compute_domain_breakdown(
    outputs: List[RunnerOutput],
    scenarios_by_id: dict,
    exclude_refuse: bool = False,
) -> List[DomainBreakdown]:
    """Group outputs by domain and compute per-domain CF."""
    domain_groups: Dict[str, List[RunnerOutput]] = defaultdict(list)
    for o in outputs:
        scenario = scenarios_by_id.get(o.scenario_id)
        if scenario:
            if exclude_refuse and scenario.ground_truth == "REFUSE":
                continue
            domain_groups[scenario.domain].append(o)

    breakdowns = []
    for domain, group in sorted(domain_groups.items()):
        count = len(group)
        correct = sum(1 for o in group if o.is_correct)
        cf = correct / count if count > 0 else 0.0
        breakdowns.append(DomainBreakdown(
            domain=domain,
            cf_score=cf,
            count=count,
            correct=correct,
        ))
    return breakdowns

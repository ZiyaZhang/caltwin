"""PersonaRunner — LLM with persona prompt from TwinState."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from twin_runtime.application.comparison.runners.base import BaseRunner
from twin_runtime.application.comparison.runners.vanilla import parse_choice, _build_user_prompt
from twin_runtime.application.comparison.schemas import RunnerOutput

if TYPE_CHECKING:
    from twin_runtime.application.comparison.schemas import ComparisonScenario
    from twin_runtime.domain.models.twin_state import TwinState
    from twin_runtime.domain.ports.llm_port import LLMPort


# Human-readable labels for axis ranges
_AXIS_LABELS = {
    (0.0, 0.3): "low",
    (0.3, 0.6): "moderate",
    (0.6, 1.01): "high",
}


def _axis_label(value: float) -> str:
    for (lo, hi), label in _AXIS_LABELS.items():
        if lo <= value < hi:
            return label
    return "moderate"


def build_persona_system_prompt(twin: "TwinState") -> str:
    """Extract natural language persona from TwinState. No raw numbers."""
    core = twin.shared_decision_core
    lines = [
        "You are acting as a specific person's decision-making twin.",
        "This person has the following decision-making profile:",
        "",
        f"- {_axis_label(core.risk_tolerance)} risk tolerance",
        f"- {_axis_label(core.ambiguity_tolerance)} ambiguity tolerance",
        f"- {_axis_label(core.action_threshold)} action threshold (tendency to act)",
        f"- {_axis_label(core.information_threshold)} information threshold",
        f"- {_axis_label(core.reversibility_preference)} preference for reversible choices",
        f"- {_axis_label(core.regret_sensitivity)} regret sensitivity",
        f"- {_axis_label(core.explore_exploit_balance)} explore-exploit balance",
        f"- conflict style: {core.conflict_style.value}",
    ]

    # Causal beliefs
    cbm = twin.causal_belief_model
    lines.append(f"- control orientation: {cbm.control_orientation.value}")
    if cbm.preferred_levers:
        lines.append(f"- preferred levers: {', '.join(cbm.preferred_levers)}")

    # Domain priorities
    domains = [dh.domain.value for dh in twin.domain_heads]
    if domains:
        lines.append(f"- active domains: {', '.join(domains)}")

    lines.append("")
    lines.append(
        "Choose the option that best matches this person's profile. "
        "Think about how this specific person would decide."
    )
    return "\n".join(lines)


class PersonaRunner(BaseRunner):
    """Baseline: LLM with persona prompt from TwinState, no evidence retrieval."""

    def __init__(self, llm: "LLMPort") -> None:
        self._llm = llm

    @property
    def runner_id(self) -> str:
        return "persona"

    def run_scenario(
        self,
        scenario: "ComparisonScenario",
        twin: "TwinState",
    ) -> RunnerOutput:
        system = build_persona_system_prompt(twin)
        user_prompt = _build_user_prompt(scenario.query, scenario.options)
        t0 = time.monotonic()
        raw = self._llm.ask_text(system, user_prompt, max_tokens=256)
        latency_ms = (time.monotonic() - t0) * 1000

        chosen = parse_choice(raw, scenario.options)
        is_correct = chosen == scenario.ground_truth
        return RunnerOutput(
            runner_id=self.runner_id,
            scenario_id=scenario.scenario_id,
            chosen=chosen,
            is_correct=is_correct,
            latency_ms=latency_ms,
            raw_response=raw,
        )

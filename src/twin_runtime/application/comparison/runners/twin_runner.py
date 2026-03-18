"""TwinRunner — full pipeline wrapper for A/B comparison."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, List, Optional

from twin_runtime.application.comparison.runners.base import BaseRunner
from twin_runtime.application.comparison.schemas import RunnerOutput

if TYPE_CHECKING:
    from twin_runtime.application.comparison.schemas import ComparisonScenario
    from twin_runtime.domain.models.twin_state import TwinState
    from twin_runtime.domain.ports.llm_port import LLMPort
    from twin_runtime.infrastructure.backends.json_file.evidence_store import JsonFileEvidenceStore


class TwinRunner(BaseRunner):
    """Full Twin Runtime pipeline wrapper."""

    def __init__(
        self,
        llm: Optional["LLMPort"] = None,
        evidence_store: Optional["JsonFileEvidenceStore"] = None,
    ) -> None:
        self._llm = llm
        self._evidence_store = evidence_store

    @property
    def runner_id(self) -> str:
        return "twin"

    def run_scenario(
        self,
        scenario: "ComparisonScenario",
        twin: "TwinState",
    ) -> RunnerOutput:
        from twin_runtime.application.pipeline.runner import run

        t0 = time.monotonic()
        trace = run(
            query=scenario.query,
            option_set=scenario.options,
            twin=twin,
            llm=self._llm,
            evidence_store=self._evidence_store,
        )
        latency_ms = (time.monotonic() - t0) * 1000

        # Determine correctness
        if scenario.ground_truth == "REFUSE":
            is_correct = _is_refusal(trace)
            chosen = "REFUSE" if is_correct else _extract_chosen(trace, scenario.options)
        else:
            chosen = _extract_chosen(trace, scenario.options)
            is_correct = chosen == scenario.ground_truth

        return RunnerOutput(
            runner_id=self.runner_id,
            scenario_id=scenario.scenario_id,
            chosen=chosen,
            is_correct=is_correct,
            uncertainty=trace.uncertainty,
            latency_ms=latency_ms,
            raw_response=trace.final_decision,
            notes=f"mode={trace.decision_mode.value}",
        )


def _is_refusal(trace) -> bool:
    """Check if trace represents a genuine refusal (not degraded).

    DEGRADED still produces a decision (weak signal), so it's not a true refusal.
    Only REFUSED mode counts as abstention for REFUSE scenario scoring.
    """
    if trace.decision_mode.value == "refused":
        return True
    # Also check explicit out-of-scope refusal codes even if mode isn't "refused"
    return trace.refusal_reason_code in ("OUT_OF_SCOPE", "POLICY_RESTRICTED")


def _extract_chosen(trace, options: List[str]) -> str:
    """Parse chosen option from trace.final_decision.

    Handles "Recommended: X (over Y)" format and plain text.
    """
    decision = trace.final_decision

    # Try "Recommended: X" format
    if "Recommended:" in decision:
        after = decision.split("Recommended:", 1)[1].strip()
        # Strip "(over ...)" suffix
        if "(" in after:
            after = after.split("(", 1)[0].strip()
        for opt in options:
            if opt.lower() == after.lower():
                return opt

    # Fuzzy substring match
    decision_lower = decision.lower()
    for opt in options:
        if opt.lower() in decision_lower:
            return opt

    # Fallback: first option
    return options[0]

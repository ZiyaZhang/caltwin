"""VanillaRunner — zero-context LLM baseline."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, List

from twin_runtime.application.comparison.runners.base import BaseRunner
from twin_runtime.application.comparison.schemas import RunnerOutput

if TYPE_CHECKING:
    from twin_runtime.application.comparison.schemas import ComparisonScenario
    from twin_runtime.domain.models.twin_state import TwinState
    from twin_runtime.domain.ports.llm_port import LLMPort

_SYSTEM = "You are a helpful assistant. Choose the best option for the user."


class VanillaRunner(BaseRunner):
    """Baseline: plain LLM with no persona or context."""

    def __init__(self, llm: "LLMPort") -> None:
        self._llm = llm

    @property
    def runner_id(self) -> str:
        return "vanilla"

    def run_scenario(
        self,
        scenario: "ComparisonScenario",
        twin: "TwinState",
    ) -> RunnerOutput:
        user_prompt = _build_user_prompt(scenario.query, scenario.options)
        t0 = time.monotonic()
        raw = self._llm.ask_text(_SYSTEM, user_prompt, max_tokens=256)
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


def _build_user_prompt(query: str, options: List[str]) -> str:
    opts = "\n".join(f"- {o}" for o in options)
    return (
        f"{query}\n\nOptions:\n{opts}\n\n"
        'Respond with JSON: {"chosen": "<exact option text>"}'
    )


def parse_choice(raw: str, options: List[str]) -> str:
    """3-layer response parsing: JSON -> fuzzy match -> first option fallback."""
    # Layer 1: JSON parse
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "chosen" in data:
            val = data["chosen"]
            if val in options:
                return val
            # Try fuzzy on JSON value
            match = _fuzzy_match(val, options)
            if match:
                return match
    except (json.JSONDecodeError, TypeError):
        pass

    # Layer 2: fuzzy match on raw text
    match = _fuzzy_match(raw, options)
    if match:
        return match

    # Layer 3: first option fallback
    return options[0]


def _fuzzy_match(text: str, options: List[str]) -> str | None:
    """Substring matching — returns the first option found in text."""
    text_lower = text.lower()
    for opt in options:
        if opt.lower() in text_lower:
            return opt
    return None

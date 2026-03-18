"""RagPersonaRunner — persona prompt + evidence retrieval."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, List

from twin_runtime.application.comparison.runners.base import BaseRunner
from twin_runtime.application.comparison.runners.persona import build_persona_system_prompt
from twin_runtime.application.comparison.runners.vanilla import parse_choice, _build_user_prompt
from twin_runtime.application.comparison.schemas import RunnerOutput
from twin_runtime.domain.models.recall_query import RecallQuery

if TYPE_CHECKING:
    from twin_runtime.application.comparison.schemas import ComparisonScenario
    from twin_runtime.domain.models.twin_state import TwinState
    from twin_runtime.domain.ports.llm_port import LLMPort
    from twin_runtime.infrastructure.backends.json_file.evidence_store import JsonFileEvidenceStore


class RagPersonaRunner(BaseRunner):
    """Persona prompt + evidence retrieval via RecallQuery."""

    def __init__(self, llm: "LLMPort", evidence_store: "JsonFileEvidenceStore") -> None:
        self._llm = llm
        self._evidence_store = evidence_store

    @property
    def runner_id(self) -> str:
        return "rag_persona"

    def run_scenario(
        self,
        scenario: "ComparisonScenario",
        twin: "TwinState",
    ) -> RunnerOutput:
        system = build_persona_system_prompt(twin)

        # Retrieve relevant evidence
        rq = RecallQuery(
            query_type="by_topic",
            user_id=twin.user_id,
            topic_keywords=scenario.query.split()[:10],
            limit=5,
        )
        fragments = self._evidence_store.query(rq)

        notes = ""
        if fragments:
            evidence_text = _format_evidence(fragments)
            system += (
                "\n\nRelevant evidence from this person's history:\n"
                + evidence_text
            )
        else:
            notes = "degraded:no_evidence"

        user_prompt = _build_user_prompt(scenario.query, scenario.options)
        t0 = time.monotonic()
        raw = self._llm.ask_text(system, user_prompt, max_tokens=256, temperature=0)
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
            notes=notes,
        )


def _format_evidence(fragments: List) -> str:
    lines = []
    for f in fragments:
        lines.append(f"- {f.summary}")
    return "\n".join(lines)

"""Top-level runtime pipeline: query -> decision trace."""

from __future__ import annotations

from typing import List, Optional

from twin_runtime.domain.models.runtime import RuntimeDecisionTrace
from twin_runtime.domain.models.twin_state import TwinState
from twin_runtime.domain.ports.llm_port import LLMPort
from twin_runtime.domain.ports.evidence_store import EvidenceStore
from twin_runtime.application.pipeline.situation_interpreter import interpret_situation
from twin_runtime.application.pipeline.head_activator import activate_heads
from twin_runtime.application.pipeline.conflict_arbiter import arbitrate
from twin_runtime.application.pipeline.decision_synthesizer import synthesize


def run(
    query: str,
    option_set: List[str],
    twin: TwinState,
    *,
    llm: Optional[LLMPort] = None,
    evidence_store: Optional[EvidenceStore] = None,
) -> RuntimeDecisionTrace:
    """Execute the full runtime pipeline."""
    if llm is None:
        # ARCHITECTURE NOTE: interfaces/ should wire this, not application/.
        # Acceptable for v0.1; Phase 4 MCP Server introduces a proper composition root.
        from twin_runtime.interfaces.defaults import DefaultLLM
        llm = DefaultLLM()

    # 1. Situation Interpreter
    frame = interpret_situation(query, twin, llm=llm)

    # 2. Memory Access Planner (will be wired in Task 5/6)
    evidence = []

    # 3. Head Activation
    assessments = activate_heads(query, option_set, frame, twin, llm=llm)

    # 4. Conflict Arbiter
    conflict = arbitrate(assessments)

    # 5. Decision Synthesis
    trace = synthesize(query, option_set, frame, assessments, conflict, twin, llm=llm)

    return trace

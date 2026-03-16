"""Top-level runtime pipeline: query -> decision trace."""

from __future__ import annotations

from typing import List, Optional

from twin_runtime.domain.models.planner import EnrichedActivationContext
from twin_runtime.domain.models.runtime import RuntimeDecisionTrace
from twin_runtime.domain.models.twin_state import TwinState
from twin_runtime.domain.ports.llm_port import LLMPort
from twin_runtime.domain.ports.evidence_store import EvidenceStore
from twin_runtime.application.pipeline.situation_interpreter import interpret_situation
from twin_runtime.application.pipeline.head_activator import activate_heads
from twin_runtime.application.pipeline.conflict_arbiter import arbitrate
from twin_runtime.application.pipeline.decision_synthesizer import synthesize
from twin_runtime.application.planner.memory_access_planner import plan_memory_access


def run(
    query: str,
    option_set: List[str],
    twin: TwinState,
    *,
    llm: Optional[LLMPort] = None,
    evidence_store: Optional[EvidenceStore] = None,
    micro_calibrate: bool = False,
) -> RuntimeDecisionTrace:
    """Execute the full runtime pipeline."""
    if llm is None:
        # ARCHITECTURE NOTE: interfaces/ should wire this, not application/.
        # Acceptable for v0.1; Phase 4 MCP Server introduces a proper composition root.
        from twin_runtime.interfaces.defaults import DefaultLLM
        llm = DefaultLLM()

    # 1. Situation Interpreter
    frame = interpret_situation(query, twin, llm=llm)

    # 2. Memory Access Planner
    plan, evidence = plan_memory_access(frame, twin, evidence_store)

    # 3. Head Activation — pass enriched context with retrieved evidence
    context = EnrichedActivationContext(
        twin=twin, frame=frame,
        retrieved_evidence=evidence,
        retrieval_rationale=plan.rationale,
        domains_to_activate=plan.domains_to_activate,
    )
    assessments = activate_heads(query, option_set, context, llm=llm)

    # 4. Conflict Arbiter
    conflict = arbitrate(assessments)

    # 5. Decision Synthesis
    trace = synthesize(query, option_set, frame, assessments, conflict, twin, llm=llm)

    # 6. Populate audit fields
    trace.memory_access_plan = plan.model_dump()
    trace.retrieved_evidence_count = len(evidence)
    trace.skipped_domains = {d.value: reason for d, reason in plan.skipped_domains.items()}

    if micro_calibrate:
        from twin_runtime.application.calibration.micro_calibration import recalibrate_confidence
        trace.pending_calibration_update = recalibrate_confidence(trace, twin)

    return trace

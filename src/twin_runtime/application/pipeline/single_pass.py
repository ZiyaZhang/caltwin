"""Single-pass pipeline executor: frame -> plan -> activate -> arbitrate -> synthesize."""
from __future__ import annotations
from typing import List, Optional

from twin_runtime.domain.models.runtime import RuntimeDecisionTrace
from twin_runtime.domain.models.situation import SituationFrame
from twin_runtime.domain.models.twin_state import TwinState
from twin_runtime.domain.ports.llm_port import LLMPort
from twin_runtime.domain.ports.evidence_store import EvidenceStore
from twin_runtime.application.pipeline.scope_guard import ScopeGuardResult
from twin_runtime.application.planner.memory_access_planner import plan_memory_access
from twin_runtime.application.pipeline.head_activator import activate_heads
from twin_runtime.application.pipeline.conflict_arbiter import arbitrate
from twin_runtime.application.pipeline.decision_synthesizer import synthesize
from twin_runtime.domain.models.planner import EnrichedActivationContext
from twin_runtime.domain.models.primitives import DecisionMode, ScopeStatus


def execute_from_frame_once(
    frame: SituationFrame,
    query: str,
    option_set: List[str],
    twin: TwinState,
    *,
    llm: LLMPort,
    evidence_store: Optional[EvidenceStore] = None,
    guard_result: Optional[ScopeGuardResult] = None,
    micro_calibrate: bool = False,
) -> RuntimeDecisionTrace:
    """Execute a single pass of the pipeline from a pre-computed SituationFrame."""
    plan, evidence = plan_memory_access(frame, twin, evidence_store, query=query)

    context = EnrichedActivationContext(
        twin=twin, frame=frame,
        retrieved_evidence=evidence,
        retrieval_rationale=plan.rationale,
        domains_to_activate=plan.domains_to_activate,
    )
    assessments = activate_heads(query, option_set, context, llm=llm)
    conflict = arbitrate(assessments)
    trace = synthesize(query, option_set, frame, assessments, conflict, twin, llm=llm)

    # Audit fields
    trace.memory_access_plan = plan.model_dump()
    trace.retrieved_evidence_count = len(evidence)
    trace.skipped_domains = {d.value: reason for d, reason in plan.skipped_domains.items()}
    trace.query = query
    trace.situation_frame = frame.model_dump(mode="json")
    if guard_result:
        from dataclasses import asdict
        trace.scope_guard_result = asdict(guard_result)

    # Refusal reason code: only assign scope/guard-derived reasons here.
    # LOW_RELIABILITY is handled by orchestrator's explicit post-execution rule.
    # Do NOT default unclassified refusals to LOW_RELIABILITY — orchestrator owns that.
    if trace.refusal_reason_code is None:
        if trace.decision_mode == DecisionMode.REFUSED:
            if guard_result and getattr(guard_result, 'restricted_hit', False):
                trace.refusal_reason_code = "POLICY_RESTRICTED"
            elif guard_result and getattr(guard_result, 'non_modeled_hit', False):
                trace.refusal_reason_code = "NON_MODELED"
            elif frame.scope_status == ScopeStatus.OUT_OF_SCOPE:
                trace.refusal_reason_code = "OUT_OF_SCOPE"
            # No else fallback — orchestrator handles remaining classification
        elif trace.decision_mode == DecisionMode.DEGRADED:
            trace.refusal_reason_code = "DEGRADED_SCOPE"

    if micro_calibrate:
        from twin_runtime.application.calibration.micro_calibration import recalibrate_confidence
        trace.pending_calibration_update = recalibrate_confidence(trace, twin)

    return trace

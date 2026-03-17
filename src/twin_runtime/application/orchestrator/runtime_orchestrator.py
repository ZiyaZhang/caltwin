"""Runtime orchestrator: owns interpretation, routes to S1/S2, assembles trace."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from twin_runtime.application.orchestrator.models import (
    BoundaryPolicy, ExecutionPath, RouteDecision,
)
from twin_runtime.application.orchestrator.route_decision import decide_route
from twin_runtime.application.orchestrator.deliberation import deliberation_loop
from twin_runtime.application.pipeline.single_pass import execute_from_frame_once
from twin_runtime.application.pipeline.situation_interpreter import interpret_situation
from twin_runtime.application.pipeline.scope_guard import ScopeGuardResult
from twin_runtime.domain.models.primitives import DecisionMode, ScopeStatus
from twin_runtime.domain.models.runtime import RuntimeDecisionTrace
from twin_runtime.domain.models.twin_state import TwinState
from twin_runtime.domain.ports.evidence_store import EvidenceStore
from twin_runtime.domain.ports.llm_port import LLMPort


def run(
    query: str,
    option_set: List[str],
    twin: TwinState,
    *,
    llm: Optional[LLMPort] = None,
    evidence_store: Optional[EvidenceStore] = None,
    micro_calibrate: bool = False,
    max_deliberation_rounds: int = 2,
    force_path: Optional[ExecutionPath] = None,
) -> RuntimeDecisionTrace:
    """Orchestrate the full pipeline: interpret -> route -> execute -> assemble trace."""
    if llm is None:
        from twin_runtime.interfaces.defaults import DefaultLLM
        llm = DefaultLLM()

    # 1. Interpret
    frame, guard_result = interpret_situation(query, twin, llm=llm)

    # 2. Route
    route = decide_route(frame, guard_result, twin)

    # 3. force_path override (for golden trace testing)
    if force_path is not None:
        route = RouteDecision(
            execution_path=force_path,
            boundary_policy=route.boundary_policy,
            reason_codes=route.reason_codes + [f"force_path_override:{force_path.value}"],
            shadow_scores=route.shadow_scores,
        )

    # 4. FORCE_REFUSE -> build minimal refusal trace
    if route.boundary_policy == BoundaryPolicy.FORCE_REFUSE:
        trace = _build_refusal_trace(query, frame, guard_result, route, twin)
        return trace

    # 5. S1_DIRECT -> single pass
    if route.execution_path == ExecutionPath.S1_DIRECT:
        trace = execute_from_frame_once(
            frame, query, option_set, twin,
            llm=llm, evidence_store=evidence_store,
            guard_result=guard_result, micro_calibrate=micro_calibrate,
        )

    # 6. S2_DELIBERATE -> deliberation loop
    elif route.execution_path == ExecutionPath.S2_DELIBERATE:
        trace = deliberation_loop(
            frame, query, option_set, twin,
            llm=llm, evidence_store=evidence_store,
            guard_result=guard_result,
            max_iterations=max_deliberation_rounds,
        )

    else:
        # NO_EXECUTION but not FORCE_REFUSE shouldn't happen, but handle gracefully
        trace = _build_refusal_trace(query, frame, guard_result, route, twin)
        return trace

    # 7. FORCE_DEGRADE -- only downgrades answerable results, NEVER overrides REFUSED
    if (route.boundary_policy == BoundaryPolicy.FORCE_DEGRADE
            and trace.decision_mode != DecisionMode.REFUSED):
        trace.decision_mode = DecisionMode.DEGRADED
        if trace.refusal_reason_code is None:
            trace.refusal_reason_code = "DEGRADED_SCOPE"

    # 8. Populate routing metadata
    trace.route_path = route.execution_path.value
    trace.route_reason_codes = route.reason_codes
    trace.boundary_policy = route.boundary_policy.value
    trace.shadow_scores = route.shadow_scores

    # 9. Refusal reason code precedence: don't overwrite existing
    if trace.refusal_reason_code is None:
        _assign_refusal_reason(trace, frame, guard_result)

    # 10. LOW_RELIABILITY post-execution rule
    if (trace.decision_mode == DecisionMode.REFUSED
            and len(trace.head_assessments) == 0
            and trace.skipped_domains
            and all("reliability" in reason.lower() for reason in trace.skipped_domains.values())
            and trace.refusal_reason_code is None):
        trace.refusal_reason_code = "LOW_RELIABILITY"

    return trace


def _build_refusal_trace(
    query: str,
    frame,
    guard_result: Optional[ScopeGuardResult],
    route: RouteDecision,
    twin: TwinState,
) -> RuntimeDecisionTrace:
    """Build a minimal REFUSED trace without running the pipeline."""
    refusal_code = _determine_refusal_code(route, guard_result, frame)
    trace = RuntimeDecisionTrace(
        trace_id=str(uuid.uuid4()),
        twin_state_version=twin.state_version,
        situation_frame_id=frame.frame_id,
        activated_domains=[],
        head_assessments=[],
        final_decision="This query is outside the twin's modeled capabilities.",
        decision_mode=DecisionMode.REFUSED,
        uncertainty=1.0,
        query=query,
        situation_frame=frame.model_dump(mode="json"),
        scope_guard_result=_guard_to_dict(guard_result),
        route_path=route.execution_path.value,
        route_reason_codes=route.reason_codes,
        boundary_policy=route.boundary_policy.value,
        shadow_scores=route.shadow_scores,
        refusal_reason_code=refusal_code,
        created_at=datetime.now(timezone.utc),
    )
    return trace


def _determine_refusal_code(route, guard_result, frame) -> str:
    if guard_result and guard_result.restricted_hit:
        return "POLICY_RESTRICTED"
    if guard_result and guard_result.non_modeled_hit:
        return "NON_MODELED"
    if frame.scope_status == ScopeStatus.OUT_OF_SCOPE:
        return "OUT_OF_SCOPE"
    return "OUT_OF_SCOPE"


def _assign_refusal_reason(trace, frame, guard_result):
    """Generic refusal reason assignment (only if not already set)."""
    if trace.decision_mode == DecisionMode.REFUSED:
        if guard_result and getattr(guard_result, 'restricted_hit', False):
            trace.refusal_reason_code = "POLICY_RESTRICTED"
        elif guard_result and getattr(guard_result, 'non_modeled_hit', False):
            trace.refusal_reason_code = "NON_MODELED"
        elif frame.scope_status == ScopeStatus.OUT_OF_SCOPE:
            trace.refusal_reason_code = "OUT_OF_SCOPE"
        else:
            trace.refusal_reason_code = "LOW_RELIABILITY"
    elif trace.decision_mode == DecisionMode.DEGRADED:
        trace.refusal_reason_code = "DEGRADED_SCOPE"


def _guard_to_dict(guard_result):
    if guard_result is None:
        return None
    from dataclasses import asdict
    return asdict(guard_result)

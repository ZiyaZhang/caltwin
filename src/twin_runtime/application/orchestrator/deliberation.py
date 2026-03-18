"""Bounded deliberation loop: retrieve -> activate -> arbitrate -> check convergence."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from twin_runtime.application.orchestrator.models import (
    DeliberationRoundSummary,
    StructuredDecision,
    TerminationReason,
)
from twin_runtime.application.pipeline.conflict_arbiter import arbitrate
from twin_runtime.application.pipeline.decision_synthesizer import (
    merge_structured_decision,
    synthesize,
)
from twin_runtime.application.pipeline.head_activator import activate_heads
from twin_runtime.application.pipeline.scope_guard import ScopeGuardResult
from twin_runtime.application.planner.memory_access_planner import plan_memory_access
from twin_runtime.domain.evidence.base import EvidenceFragment
from twin_runtime.domain.models.planner import EnrichedActivationContext
from twin_runtime.domain.models.primitives import DecisionMode
from twin_runtime.domain.models.runtime import ConflictReport, RuntimeDecisionTrace
from twin_runtime.domain.models.situation import SituationFrame
from twin_runtime.domain.models.twin_state import TwinState
from twin_runtime.domain.ports.evidence_store import EvidenceStore
from twin_runtime.domain.ports.llm_port import LLMPort


def check_termination(
    round_summaries: List[DeliberationRoundSummary],
    current_conflict: Optional[ConflictReport],
    previous_conflict: Optional[ConflictReport],
) -> Optional[TerminationReason]:
    """Check if deliberation should stop. Returns reason or None to continue."""
    if len(round_summaries) < 1:
        return None

    # 1. CONFLICT_RESOLVED — require at least 2 rounds (initial pass + 1 deliberation)
    #    before allowing early termination, so S2 always deliberates at least once
    if len(round_summaries) >= 2:
        if current_conflict is None:
            return TerminationReason.CONFLICT_RESOLVED
        if (len(current_conflict.conflict_types) == 1
                and current_conflict.resolvable_by_system):
            return TerminationReason.CONFLICT_RESOLVED

    # Require at least 2 rounds for evidence/confidence checks
    if len(round_summaries) < 2:
        return None

    latest = round_summaries[-1]

    # 2. NO_NEW_EVIDENCE
    if latest.new_unique_evidence_count == 0:
        return TerminationReason.NO_NEW_EVIDENCE

    # 3. CONFIDENCE_PLATEAU
    prev = round_summaries[-2]
    if (abs(latest.avg_head_confidence - prev.avg_head_confidence) < 0.05
            and not latest.top_choice_changed):
        return TerminationReason.CONFIDENCE_PLATEAU

    return None


def deliberation_loop(
    frame: SituationFrame,
    query: str,
    option_set: List[str],
    twin: TwinState,
    *,
    llm: LLMPort,
    evidence_store: Optional[EvidenceStore] = None,
    guard_result: Optional[ScopeGuardResult] = None,
    max_iterations: int = 2,
    micro_calibrate: bool = False,
) -> RuntimeDecisionTrace:
    """Run bounded deliberation: initial pass + up to max_iterations rounds."""
    seen_hashes: Set[str] = set()
    cumulative_evidence: List[EvidenceFragment] = []
    round_summaries: List[DeliberationRoundSummary] = []
    previous_conflict: Optional[ConflictReport] = None
    termination: Optional[TerminationReason] = None

    # --- Initial pass (round 0) ---
    plan, evidence = plan_memory_access(frame, twin, evidence_store, query=query)
    seen_hashes.update(e.content_hash for e in evidence)
    cumulative_evidence.extend(evidence)

    context = EnrichedActivationContext(
        twin=twin, frame=frame,
        retrieved_evidence=cumulative_evidence,
        retrieval_rationale=plan.rationale,
        domains_to_activate=plan.domains_to_activate,
    )
    assessments = activate_heads(query, option_set, context, llm=llm)
    conflict = arbitrate(assessments)
    structured = merge_structured_decision(assessments, conflict, frame, option_set=option_set)

    round_summaries.append(DeliberationRoundSummary(
        round_index=0,
        new_unique_evidence_count=len(evidence),
        conflict_types=[c.value for c in conflict.conflict_types] if conflict else [],
        top_choice=structured.top_choice,
        avg_head_confidence=structured.avg_confidence,
    ))

    # --- Deliberation rounds (1..max_iterations) ---
    for round_idx in range(1, max_iterations + 1):
        # Check termination
        termination = check_termination(round_summaries, conflict, previous_conflict)
        if termination is not None:
            break

        # Re-plan with seen evidence excluded
        plan, new_evidence = plan_memory_access(
            frame, twin, evidence_store, query=query,
            seen_content_hashes=seen_hashes,
            round_index=round_idx,
            previous_conflict=conflict,
        )
        unique_new = [e for e in new_evidence if e.content_hash not in seen_hashes]
        seen_hashes.update(e.content_hash for e in unique_new)
        cumulative_evidence.extend(unique_new)

        # Re-activate with cumulative evidence
        context = EnrichedActivationContext(
            twin=twin, frame=frame,
            retrieved_evidence=cumulative_evidence,
            retrieval_rationale=plan.rationale,
            domains_to_activate=plan.domains_to_activate,
        )
        assessments = activate_heads(query, option_set, context, llm=llm)
        previous_conflict = conflict
        conflict = arbitrate(assessments)
        structured = merge_structured_decision(assessments, conflict, frame, option_set=option_set)

        # None->None is NOT a change
        prev_top = round_summaries[-1].top_choice
        choice_changed = (
            structured.top_choice is not None
            and prev_top is not None
            and structured.top_choice != prev_top
        )

        round_summaries.append(DeliberationRoundSummary(
            round_index=round_idx,
            new_unique_evidence_count=len(unique_new),
            conflict_types=[c.value for c in conflict.conflict_types] if conflict else [],
            top_choice=structured.top_choice,
            avg_head_confidence=structured.avg_confidence,
            top_choice_changed=choice_changed,
        ))
    else:
        termination = TerminationReason.MAX_ITERATIONS

    # --- Final synthesis (one time only) ---
    trace = synthesize(query, option_set, frame, assessments, conflict, twin, llm=llm)

    # Populate audit fields
    trace.memory_access_plan = plan.model_dump()
    trace.retrieved_evidence_count = len(cumulative_evidence)
    trace.skipped_domains = {d.value: reason for d, reason in plan.skipped_domains.items()}
    trace.query = query
    trace.situation_frame = frame.model_dump(mode="json")
    if guard_result:
        from dataclasses import asdict
        trace.scope_guard_result = asdict(guard_result)

    # Deliberation metadata
    trace.deliberation_rounds = len(round_summaries) - 1  # Exclude initial pass
    trace.terminated_by = termination.value if termination else None
    trace.deliberation_round_summaries = [s.model_dump() for s in round_summaries]

    # Post-loop abstention: unresolved conflict after exhaustion → INSUFFICIENT_EVIDENCE
    # Applies to NO_NEW_EVIDENCE, MAX_ITERATIONS, and CONFIDENCE_PLATEAU when conflict persists
    if (termination in (TerminationReason.NO_NEW_EVIDENCE,
                        TerminationReason.MAX_ITERATIONS,
                        TerminationReason.CONFIDENCE_PLATEAU)
            and conflict is not None
            and not conflict.resolvable_by_system):
        trace.decision_mode = DecisionMode.REFUSED
        trace.refusal_reason_code = "INSUFFICIENT_EVIDENCE"
        trace.refusal_or_degrade_reason = "insufficient_evidence_after_deliberation"
        trace.uncertainty = 1.0
        trace.final_decision = "Insufficient evidence to resolve conflicting assessments."
        trace.output_text = (
            "After deliberation, I don't have enough evidence to give a reliable answer "
            "on this question. The underlying domain assessments conflict and additional "
            "evidence retrieval did not resolve the disagreement."
        )

    # Micro-calibration (same as single_pass, preserves backward compat for S2 path)
    if micro_calibrate:
        from twin_runtime.application.calibration.micro_calibration import recalibrate_confidence
        trace.pending_calibration_update = recalibrate_confidence(trace, twin)

    return trace

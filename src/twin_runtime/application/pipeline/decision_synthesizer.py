"""Decision Synthesizer: merge head assessments into final decision + surface realization.

Step A: Structured decision from head assessments + conflict report
Step B: Natural language output from structured decision
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from twin_runtime.domain.models.primitives import DecisionMode, DomainEnum, MergeStrategy
from twin_runtime.domain.models.runtime import ConflictReport, HeadAssessment, RuntimeDecisionTrace
from twin_runtime.domain.models.situation import SituationFrame
from twin_runtime.domain.models.twin_state import TwinState
from twin_runtime.domain.ports.llm_port import LLMPort
from twin_runtime.application.orchestrator.models import StructuredDecision


def _compute_option_scores(assessments, frame, option_set=None):
    """Shared scoring: weighted merge + phantom option filtering."""
    option_scores = {}
    for assessment in assessments:
        domain_weight = frame.domain_activation_vector.get(assessment.domain, 0.5)
        for rank, option in enumerate(assessment.option_ranking):
            rank_score = 1.0 / (rank + 1)
            weighted = rank_score * domain_weight * assessment.confidence
            option_scores[option] = option_scores.get(option, 0.0) + weighted

    all_phantom = False
    if option_set:
        valid_options = {o.lower().strip(): o for o in option_set}
        filtered_scores = {}
        for opt, score in option_scores.items():
            normalized = opt.lower().strip()
            if normalized in valid_options:
                canonical = valid_options[normalized]
                filtered_scores[canonical] = filtered_scores.get(canonical, 0.0) + score
        if not filtered_scores:
            all_phantom = True
            for opt in option_set:
                filtered_scores[opt] = 0.01
        else:
            for opt in option_set:
                if opt not in filtered_scores:
                    filtered_scores[opt] = 0.01
        option_scores = filtered_scores

    return option_scores, all_phantom


def _synthesize_decision(
    assessments: List[HeadAssessment],
    conflict: Optional[ConflictReport],
    frame: SituationFrame,
    *,
    option_set: Optional[List[str]] = None,
) -> tuple[str, DecisionMode, float, Optional[str]]:
    """Step A: produce structured decision from assessments.

    Returns (decision_text, mode, uncertainty, refusal_reason).
    """
    # Refused: out of scope
    if frame.scope_status.value == "out_of_scope":
        return (
            "This query is outside the twin's modeled capabilities.",
            DecisionMode.REFUSED,
            1.0,
            "out_of_scope",
        )

    # Degraded: borderline scope or very low confidence
    if frame.scope_status.value == "borderline":
        mode = DecisionMode.DEGRADED
    elif conflict and conflict.final_merge_strategy == MergeStrategy.CLARIFY:
        mode = DecisionMode.CLARIFIED
    else:
        mode = DecisionMode.DIRECT

    # Merge rankings using shared scoring helper
    option_scores, _all_phantom = _compute_option_scores(assessments, frame, option_set)
    if _all_phantom:
        mode = DecisionMode.DEGRADED

    if not option_scores:
        return "Unable to evaluate options.", DecisionMode.REFUSED, 1.0, "no_assessments"

    ranked = sorted(option_scores.items(), key=lambda x: -x[1])
    top_choice = ranked[0][0]

    # Uncertainty: inverse of confidence spread
    avg_confidence = sum(a.confidence for a in assessments) / len(assessments) if assessments else 0.0
    uncertainty = 1.0 - avg_confidence
    if _all_phantom:
        uncertainty = min(1.0, uncertainty + 0.3)
    if conflict and not conflict.resolvable_by_system:
        uncertainty = min(1.0, uncertainty + 0.2)

    decision = f"Recommended: {top_choice}"
    if len(ranked) > 1:
        decision += f" (over {', '.join(o for o, _ in ranked[1:])})"

    refusal = None
    if mode == DecisionMode.DEGRADED:
        refusal = "borderline_scope"

    return decision, mode, round(uncertainty, 3), refusal


def merge_structured_decision(assessments, conflict, frame, *, option_set=None):
    """Structured decision without surface realization. For deliberation loop convergence checks."""
    if frame.scope_status.value == "out_of_scope":
        return StructuredDecision(
            top_choice=None, option_scores={}, avg_confidence=0.0,
            mode=DecisionMode.REFUSED, refusal_reason="out_of_scope",
        )

    option_scores, all_phantom = _compute_option_scores(assessments, frame, option_set)

    if not option_scores:
        return StructuredDecision(
            top_choice=None, option_scores={}, avg_confidence=0.0,
            mode=DecisionMode.REFUSED, refusal_reason="no_assessments",
        )

    ranked = sorted(option_scores.items(), key=lambda x: -x[1])
    top_choice = ranked[0][0]
    avg_confidence = sum(a.confidence for a in assessments) / len(assessments) if assessments else 0.0

    mode = DecisionMode.DIRECT
    if frame.scope_status.value == "borderline":
        mode = DecisionMode.DEGRADED
    elif all_phantom:
        mode = DecisionMode.DEGRADED
    elif conflict and conflict.final_merge_strategy.value == "clarify":
        mode = DecisionMode.CLARIFIED

    return StructuredDecision(
        top_choice=top_choice, option_scores=option_scores,
        avg_confidence=avg_confidence, mode=mode,
        refusal_reason="borderline_scope" if mode == DecisionMode.DEGRADED else None,
    )


def _surface_realize(
    query: str,
    decision: str,
    mode: DecisionMode,
    uncertainty: float,
    assessments: List[HeadAssessment],
    conflict: Optional[ConflictReport],
    twin: TwinState,
    llm: LLMPort,
) -> str:
    """Step B: convert structured decision into natural language as the twin."""
    if mode == DecisionMode.REFUSED:
        return decision

    # Build context for surface realization
    assessment_summary = []
    for a in assessments:
        top3_utility = sorted(
            ((k, v) for k, v in a.utility_decomposition.items() if isinstance(v, (int, float))),
            key=lambda x: -x[1],
        )[:3]
        utility_str = ", ".join(f"{k}={v:.1f}" for k, v in top3_utility)
        assessment_summary.append(
            f"  [{a.domain.value}] top={a.option_ranking[0]}, conf={a.confidence:.2f}, drivers: {utility_str}"
        )

    conflict_note = ""
    if conflict:
        conflict_note = f"\nConflict: {', '.join(t.value for t in conflict.conflict_types)}. Strategy: {conflict.final_merge_strategy.value}."

    system = f"""You are a judgment twin speaking as the user. Be direct and concise.
Uncertainty level: {uncertainty:.2f} (0=certain, 1=uncertain).
Mode: {mode.value}.
If uncertain, say so honestly. If degraded, add caveats.
Do NOT mention that you are an AI or twin. Speak as "I would..." or "My preference is..."
Keep response under 150 words."""

    user = f"""Query: {query}

Structured decision: {decision}

Head assessments:
{chr(10).join(assessment_summary)}
{conflict_note}

Generate a natural response as the twin."""

    return llm.ask_text(system, user, max_tokens=300)


def synthesize(
    query: str,
    option_set: List[str],
    frame: SituationFrame,
    assessments: List[HeadAssessment],
    conflict: Optional[ConflictReport],
    twin: TwinState,
    *,
    llm: LLMPort,
) -> RuntimeDecisionTrace:
    """Full synthesis: Step A (structured) + Step B (surface) -> RuntimeDecisionTrace."""
    decision, mode, uncertainty, refusal = _synthesize_decision(
        assessments, conflict, frame, option_set=option_set
    )

    output_text = _surface_realize(
        query, decision, mode, uncertainty, assessments, conflict, twin, llm
    )

    return RuntimeDecisionTrace(
        trace_id=str(uuid.uuid4()),
        twin_state_version=twin.state_version,
        situation_frame_id=frame.frame_id,
        activated_domains=list(frame.domain_activation_vector.keys()),
        head_assessments=assessments,
        conflict_report_id=conflict.report_id if conflict else None,
        final_decision=decision,
        decision_mode=mode,
        uncertainty=uncertainty,
        refusal_or_degrade_reason=refusal,
        output_text=output_text,
        created_at=datetime.now(timezone.utc),
    )

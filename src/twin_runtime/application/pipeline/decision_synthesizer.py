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
from twin_runtime.infrastructure.llm.client import ask_text


def _synthesize_decision(
    assessments: List[HeadAssessment],
    conflict: Optional[ConflictReport],
    frame: SituationFrame,
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

    # Merge rankings: weighted by domain activation and head confidence
    option_scores: dict[str, float] = {}
    for assessment in assessments:
        domain_weight = frame.domain_activation_vector.get(assessment.domain, 0.5)
        for rank, option in enumerate(assessment.option_ranking):
            # Score: higher rank = higher score, weighted by domain activation * confidence
            rank_score = 1.0 / (rank + 1)
            weighted = rank_score * domain_weight * assessment.confidence
            option_scores[option] = option_scores.get(option, 0.0) + weighted

    if not option_scores:
        return "Unable to evaluate options.", DecisionMode.REFUSED, 1.0, "no_assessments"

    ranked = sorted(option_scores.items(), key=lambda x: -x[1])
    top_choice = ranked[0][0]

    # Uncertainty: inverse of confidence spread
    avg_confidence = sum(a.confidence for a in assessments) / len(assessments)
    uncertainty = 1.0 - avg_confidence
    if conflict and not conflict.resolvable_by_system:
        uncertainty = min(1.0, uncertainty + 0.2)

    decision = f"Recommended: {top_choice}"
    if len(ranked) > 1:
        decision += f" (over {', '.join(o for o, _ in ranked[1:])})"

    refusal = None
    if mode == DecisionMode.DEGRADED:
        refusal = "borderline_scope"

    return decision, mode, round(uncertainty, 3), refusal


def _surface_realize(
    query: str,
    decision: str,
    mode: DecisionMode,
    uncertainty: float,
    assessments: List[HeadAssessment],
    conflict: Optional[ConflictReport],
    twin: TwinState,
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

    return ask_text(system, user, max_tokens=300)


def synthesize(
    query: str,
    option_set: List[str],
    frame: SituationFrame,
    assessments: List[HeadAssessment],
    conflict: Optional[ConflictReport],
    twin: TwinState,
) -> RuntimeDecisionTrace:
    """Full synthesis: Step A (structured) + Step B (surface) -> RuntimeDecisionTrace."""
    decision, mode, uncertainty, refusal = _synthesize_decision(
        assessments, conflict, frame
    )

    output_text = _surface_realize(
        query, decision, mode, uncertainty, assessments, conflict, twin
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

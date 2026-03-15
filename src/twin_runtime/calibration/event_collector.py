"""Event Collector: convert runtime traces + user feedback into calibration candidates.

Flow: RuntimeDecisionTrace + user_actual_choice → RuntimeEvent + CandidateCalibrationCase
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from ..models.calibration import CandidateCalibrationCase
from ..models.primitives import CandidateSourceType, DomainEnum, OrdinalTriLevel, RuntimeEventType
from ..models.runtime import RuntimeDecisionTrace, RuntimeEvent


def collect_event(
    trace: RuntimeDecisionTrace,
    user_actual_choice: str,
    user_reasoning: Optional[str] = None,
    source_type: CandidateSourceType = CandidateSourceType.RUNTIME_TRACE,
    ground_truth_confidence: float = 0.8,
) -> tuple[RuntimeEvent, CandidateCalibrationCase]:
    """Create a RuntimeEvent and CandidateCalibrationCase from a completed trace.

    Args:
        trace: The completed runtime decision trace
        user_actual_choice: What the user actually chose
        user_reasoning: Optional reasoning from the user
        source_type: How this observation was collected
        ground_truth_confidence: How confident we are this is the real choice

    Returns:
        (RuntimeEvent, CandidateCalibrationCase) pair
    """
    now = datetime.now(timezone.utc)

    # Did the twin get it right?
    twin_top_choice = trace.final_decision
    agreed = user_actual_choice in twin_top_choice

    event = RuntimeEvent(
        event_id=str(uuid.uuid4()),
        trace_id=trace.trace_id,
        event_type=RuntimeEventType.OUTCOME_OBSERVED if agreed else RuntimeEventType.DISAGREEMENT_FLAGGED,
        payload={
            "twin_decision": trace.final_decision,
            "user_actual_choice": user_actual_choice,
            "user_reasoning": user_reasoning,
            "agreed": agreed,
            "twin_uncertainty": trace.uncertainty,
            "decision_mode": trace.decision_mode.value,
        },
        event_confidence=ground_truth_confidence,
        observed_at=now,
    )

    # Use the primary activated domain
    primary_domain = trace.activated_domains[0] if trace.activated_domains else DomainEnum.WORK

    # Extract stakes/reversibility from head assessments if available
    # Default to medium — the situation interpreter already classified these
    # but they're in the SituationFrame which isn't stored on the trace.
    # For v0.1, use defaults; later we can thread the frame through.
    candidate = CandidateCalibrationCase(
        candidate_id=str(uuid.uuid4()),
        created_at=now,
        source_type=source_type,
        originating_trace_id=trace.trace_id,
        domain_label=primary_domain,
        observed_context=f"Query that produced trace {trace.trace_id}",
        option_set=_extract_options(trace),
        observed_choice=user_actual_choice,
        observed_reasoning=user_reasoning,
        stakes=OrdinalTriLevel.MEDIUM,
        reversibility=OrdinalTriLevel.MEDIUM,
        ground_truth_confidence=ground_truth_confidence,
    )

    return event, candidate


def collect_manual_case(
    domain: DomainEnum,
    context: str,
    option_set: list[str],
    actual_choice: str,
    reasoning: Optional[str] = None,
    stakes: OrdinalTriLevel = OrdinalTriLevel.MEDIUM,
    reversibility: OrdinalTriLevel = OrdinalTriLevel.MEDIUM,
    ground_truth_confidence: float = 0.9,
) -> CandidateCalibrationCase:
    """Create a CandidateCalibrationCase from manual user input (life-anchor).

    This is for retroactive calibration data — real decisions the user made
    that weren't mediated by the twin.
    """
    return CandidateCalibrationCase(
        candidate_id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc),
        source_type=CandidateSourceType.USER_REFLECTION,
        domain_label=domain,
        observed_context=context,
        option_set=option_set,
        observed_choice=actual_choice,
        observed_reasoning=reasoning,
        stakes=stakes,
        reversibility=reversibility,
        ground_truth_confidence=ground_truth_confidence,
    )


def _extract_options(trace: RuntimeDecisionTrace) -> list[str]:
    """Extract option set from head assessments."""
    options: list[str] = []
    seen = set()
    for ha in trace.head_assessments:
        for opt in ha.option_ranking:
            if opt not in seen:
                options.append(opt)
                seen.add(opt)
    return options if options else ["unknown"]

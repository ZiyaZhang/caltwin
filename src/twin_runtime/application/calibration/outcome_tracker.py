"""Outcome tracking: record decision outcomes and generate micro-calibration updates."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from twin_runtime.domain.models.calibration import OutcomeRecord, MicroCalibrationUpdate
from twin_runtime.domain.models.primitives import OutcomeSource, DomainEnum, uncertainty_to_confidence
from twin_runtime.application.calibration.fidelity_evaluator import choice_similarity
from twin_runtime.application.calibration.micro_calibration import apply_outcome_update


def record_outcome(
    trace_id: str,
    actual_choice: str,
    source: OutcomeSource,
    actual_reasoning: Optional[str] = None,
    *,
    twin,
    trace_store,
    calibration_store,
) -> tuple[OutcomeRecord, Optional[MicroCalibrationUpdate]]:
    """Full outcome recording flow."""
    # 1. Load original trace
    trace = trace_store.load_trace(trace_id)

    # 2. Get prediction ranking from highest-confidence head assessment
    head_assessments = sorted(trace.head_assessments, key=lambda h: h.confidence, reverse=True)
    ranking = head_assessments[0].option_ranking if head_assessments else []
    domain = head_assessments[0].domain if head_assessments else DomainEnum.WORK

    # 3. Compute rank using unified choice_similarity
    score, rank = choice_similarity(ranking, actual_choice)

    # 4. Build OutcomeRecord
    outcome = OutcomeRecord(
        outcome_id=str(uuid.uuid4()),
        trace_id=trace_id,
        user_id=trace.twin_state_version,  # placeholder — real user_id from twin
        actual_choice=actual_choice,
        actual_reasoning=actual_reasoning,
        outcome_source=source,
        prediction_rank=rank,
        confidence_at_prediction=uncertainty_to_confidence(trace.uncertainty),
        domain=domain,
        created_at=datetime.now(timezone.utc),
    )

    # 5. Save
    calibration_store.save_outcome(outcome)

    # 6. Generate update (NOT apply)
    update = apply_outcome_update(outcome, twin)

    return outcome, update

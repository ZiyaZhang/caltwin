"""Case Manager: quality gate for promoting candidates to calibration cases.

Promotion criteria (v0.1):
- ground_truth_confidence >= threshold (default 0.6)
- observed_choice is in option_set
- context is non-trivial (> 10 chars)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from ..models.calibration import CalibrationCase, CandidateCalibrationCase

# Quality gate thresholds
_MIN_GROUND_TRUTH_CONFIDENCE = 0.6
_MIN_CONTEXT_LENGTH = 10


def promote_candidate(
    candidate: CandidateCalibrationCase,
    task_type: str = "general",
    min_confidence: float = _MIN_GROUND_TRUTH_CONFIDENCE,
) -> Optional[CalibrationCase]:
    """Promote a CandidateCalibrationCase through the quality gate.

    Returns CalibrationCase if promoted, None if rejected.
    Also mutates the candidate's promoted_to_calibration_case flag.
    """
    # Quality gate checks
    rejection_reasons = []

    if candidate.ground_truth_confidence < min_confidence:
        rejection_reasons.append(
            f"confidence {candidate.ground_truth_confidence:.2f} < {min_confidence:.2f}"
        )

    if candidate.observed_choice not in candidate.option_set:
        rejection_reasons.append(
            f"choice '{candidate.observed_choice}' not in option_set"
        )

    if len(candidate.observed_context) < _MIN_CONTEXT_LENGTH:
        rejection_reasons.append(
            f"context too short ({len(candidate.observed_context)} chars)"
        )

    if rejection_reasons:
        return None

    # Promote
    case = CalibrationCase(
        case_id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc),
        domain_label=candidate.domain_label,
        task_type=task_type,
        observed_context=candidate.observed_context,
        option_set=candidate.option_set,
        actual_choice=candidate.observed_choice,
        actual_reasoning_if_known=candidate.observed_reasoning,
        stakes=candidate.stakes,
        reversibility=candidate.reversibility,
        time_pressure=candidate.time_pressure,
        confidence_of_ground_truth=candidate.ground_truth_confidence,
        used_for_calibration=False,
    )

    candidate.promoted_to_calibration_case = True
    candidate.promotion_reason = "passed_quality_gate"

    return case

"""State Updater: apply evaluation results to update TwinState parameters.

This closes the flywheel: evaluation → parameter adjustment → better predictions.

Update strategy (v0.1):
- Update head_reliability from domain_reliability scores
- Update core_confidence from overall choice_similarity
- Update evidence_count
- Bump recalibration timestamps
- Optionally detect bias patterns (future)
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from ..models.calibration import TwinEvaluation
from ..models.twin_state import TwinState


# How much to blend new evaluation vs existing state (EMA alpha)
_LEARNING_RATE = 0.3
_MIN_CASES_FOR_UPDATE = 3


def apply_evaluation(
    twin: TwinState,
    evaluation: TwinEvaluation,
    learning_rate: float = _LEARNING_RATE,
) -> TwinState:
    """Apply a TwinEvaluation to produce an updated TwinState.

    Uses exponential moving average to blend new signals with existing state.
    Returns a NEW TwinState (does not mutate input).
    """
    updated = deepcopy(twin)
    now = datetime.now(timezone.utc)
    alpha = learning_rate

    total_cases = len(evaluation.calibration_case_ids)
    if total_cases < _MIN_CASES_FOR_UPDATE:
        # Not enough data — only update timestamps, not parameters
        updated.shared_decision_core.last_recalibrated_at = now
        return updated

    # 1. Update head reliability per domain
    for head in updated.domain_heads:
        d = head.domain.value
        if d in evaluation.domain_reliability:
            new_rel = evaluation.domain_reliability[d]
            head.head_reliability = round(
                head.head_reliability * (1 - alpha) + new_rel * alpha, 3
            )
            head.last_recalibrated_at = now

    # 2. Update reliability profile entries
    for entry in updated.reliability_profile:
        d = entry.domain.value
        if d in evaluation.domain_reliability:
            new_rel = evaluation.domain_reliability[d]
            entry.reliability_score = round(
                entry.reliability_score * (1 - alpha) + new_rel * alpha, 3
            )
            entry.last_updated_at = now

    # 3. Update core confidence from overall choice similarity
    overall = evaluation.choice_similarity
    updated.shared_decision_core.core_confidence = round(
        updated.shared_decision_core.core_confidence * (1 - alpha) + overall * alpha, 3
    )
    updated.shared_decision_core.evidence_count += total_cases
    updated.shared_decision_core.last_recalibrated_at = now

    # 4. Bump state version
    current_version = updated.state_version
    if current_version.startswith("v"):
        try:
            num = int(current_version[1:])
            updated.state_version = f"v{num + 1:03d}"
        except ValueError:
            updated.state_version = current_version + ".1"
    else:
        updated.state_version = current_version + ".1"

    # 5. Update temporal metadata
    updated.temporal_metadata.state_valid_from = now

    return updated

"""Micro-calibration engine: small, safe parameter updates from live trace data and outcomes."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Optional
import uuid

from twin_runtime.domain.models.calibration import MicroCalibrationUpdate, OutcomeRecord
from twin_runtime.domain.models.primitives import DecisionMode, DomainEnum, MicroCalibrationTrigger
from twin_runtime.domain.models.twin_state import TwinState


# Safety caps per parameter path pattern
_MAX_DELTA_RULES: list[tuple[str, float]] = [
    ("core_confidence", 0.02),
    ("head_reliability", 0.03),
    ("shared_decision_core.", 0.05),
]
_DEFAULT_MAX_DELTA = 0.05


def _max_delta_for(param_path: str) -> float:
    """Return the safety-cap for a given parameter path."""
    for pattern, cap in _MAX_DELTA_RULES:
        if pattern in param_path:
            return cap
    return _DEFAULT_MAX_DELTA


def recalibrate_confidence(trace, twin: TwinState) -> Optional[MicroCalibrationUpdate]:
    """Produce a confidence micro-calibration update from a runtime trace.

    Skips REFUSED and DEGRADED traces.  Computes a small delta toward the mean
    head confidence observed in the trace, capped at ±0.02.
    """
    if trace.decision_mode in (DecisionMode.REFUSED, DecisionMode.DEGRADED):
        return None

    # Compute mean confidence across activated head assessments
    assessments = trace.head_assessments or []
    if not assessments:
        return None

    mean_head_conf = sum(a.confidence for a in assessments) / len(assessments)
    current_conf = twin.shared_decision_core.core_confidence
    raw_delta = (mean_head_conf - current_conf) * 0.01

    # Cap at ±0.02
    max_d = 0.02
    delta = max(-max_d, min(max_d, raw_delta))

    param_key = "shared_decision_core.core_confidence"
    return MicroCalibrationUpdate(
        update_id=f"mcu-{uuid.uuid4().hex[:8]}",
        twin_state_version=twin.state_version,
        trigger=MicroCalibrationTrigger.CONFIDENCE_RECAL,
        created_at=datetime.now(timezone.utc),
        parameter_deltas={param_key: delta},
        previous_values={param_key: current_conf},
        learning_rate_used=0.01,
        rationale=(
            f"Confidence recalibration: mean_head_conf={mean_head_conf:.4f}, "
            f"current={current_conf:.4f}, delta={delta:.4f}"
        ),
    )


def apply_outcome_update(outcome: OutcomeRecord, twin: TwinState) -> Optional[MicroCalibrationUpdate]:
    """Produce a reliability micro-calibration update from an observed outcome.

    HIT (prediction_rank==1): +0.02 on head_reliability for the domain.
    MISS (prediction_rank is None): -0.03 on head_reliability for the domain.
    PARTIAL (any other rank): no change — just return a zero-delta update.
    """
    # Find the matching domain head
    domain_head = next(
        (h for h in twin.domain_heads if h.domain == outcome.domain),
        None,
    )
    if domain_head is None:
        return None

    current_reliability = domain_head.head_reliability
    param_key = f"domain_heads.{outcome.domain.value}.head_reliability"

    if outcome.prediction_rank == 1:
        # HIT
        delta = 0.02
        rationale = f"Outcome HIT for domain={outcome.domain.value}; boosting head_reliability"
    elif outcome.prediction_rank is None:
        # MISS
        delta = -0.03
        rationale = f"Outcome MISS for domain={outcome.domain.value}; reducing head_reliability"
    else:
        # PARTIAL — record but no change
        delta = 0.0
        rationale = (
            f"Partial outcome (rank={outcome.prediction_rank}) for "
            f"domain={outcome.domain.value}; no reliability change"
        )

    return MicroCalibrationUpdate(
        update_id=f"mcu-{uuid.uuid4().hex[:8]}",
        twin_state_version=twin.state_version,
        trigger=MicroCalibrationTrigger.OUTCOME_UPDATE,
        created_at=datetime.now(timezone.utc),
        parameter_deltas={param_key: delta},
        previous_values={param_key: current_reliability},
        learning_rate_used=0.05,
        rationale=rationale,
    )


class UpdateResult:
    """Immutable result of applying a micro-calibration update."""
    __slots__ = ("new_twin", "applied_update")

    def __init__(self, new_twin: TwinState, applied_update: MicroCalibrationUpdate):
        object.__setattr__(self, "new_twin", new_twin)
        object.__setattr__(self, "applied_update", applied_update)


def apply_update(update: MicroCalibrationUpdate, twin: TwinState) -> UpdateResult:
    """Apply a MicroCalibrationUpdate to a TwinState (deepcopy — non-destructive).

    Each delta is safety-capped per path pattern and then clamped to [0, 1].
    Returns an UpdateResult with both the new TwinState and a copy of the
    update marked as applied. The original update object is NOT mutated,
    ensuring retries are safe if persistence fails.
    Raises ValueError if the update was already applied (idempotency guard).
    """
    if update.applied:
        raise ValueError(
            f"MicroCalibrationUpdate {update.update_id} has already been applied "
            f"at {update.applied_at}. Cannot re-apply."
        )

    new_twin = deepcopy(twin)

    for param_path, raw_delta in update.parameter_deltas.items():
        max_d = _max_delta_for(param_path)
        delta = max(-max_d, min(max_d, raw_delta))

        parts = param_path.split(".")
        _apply_delta_to_model(new_twin, parts, delta)

    applied_update = update.model_copy(update={
        "applied": True,
        "applied_at": datetime.now(timezone.utc),
    })

    return UpdateResult(new_twin, applied_update)


def _apply_delta_to_model(obj, parts: list[str], delta: float) -> None:
    """Recursively walk obj via parts, apply delta to the final numeric attribute.

    Supports:
      - Simple dot-path on nested Pydantic models: shared_decision_core.risk_tolerance
      - Domain-head paths: domain_heads.<domain_value>.head_reliability
    """
    if not parts:
        return

    attr = parts[0]
    rest = parts[1:]

    # Special handling for domain_heads list: domain_heads.<domain>.field
    if attr == "domain_heads" and rest:
        domain_value = rest[0]
        field_parts = rest[1:]
        # Find the head by domain value
        for head in obj.domain_heads:
            if head.domain.value == domain_value:
                _apply_delta_to_model(head, field_parts, delta)
        return

    child = getattr(obj, attr, None)
    if child is None:
        import logging
        logging.getLogger(__name__).warning(
            "Cannot resolve attribute '%s' on %s — delta silently dropped",
            attr, type(obj).__name__,
        )
        return

    if rest:
        _apply_delta_to_model(child, rest, delta)
    else:
        # Leaf: apply delta and clamp
        current = getattr(obj, attr)
        if isinstance(current, (int, float)):
            new_val = round(float(current) + delta, 10)
            new_val = max(0.0, min(1.0, new_val))
            # Use setattr which triggers Pydantic v2 validators if validate_assignment=True
            try:
                setattr(obj, attr, new_val)
            except (AttributeError, ValueError):
                # Fallback for frozen or non-validating models
                object.__setattr__(obj, attr, new_val)

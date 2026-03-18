"""Time decay functions for temporal calibration."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional


def time_decay_weight(age_days: float, half_life: float, floor: float) -> float:
    """Exponential decay with minimum floor.

    weight = floor + (1 - floor) * exp(-ln(2) * age_days / half_life)
    """
    if age_days <= 0:
        return 1.0
    decay = math.exp(-math.log(2) * age_days / half_life)
    return floor + (1.0 - floor) * decay


EVIDENCE_HALF_LIFE = 60.0
EVIDENCE_FLOOR = 0.1
CALIBRATION_HALF_LIFE = 120.0
CALIBRATION_FLOOR = 0.25


def evidence_decay_weight(age_days: float) -> float:
    """Decay weight for evidence fragments (60-day half-life, 0.1 floor)."""
    return time_decay_weight(age_days, EVIDENCE_HALF_LIFE, EVIDENCE_FLOOR)


def calibration_decay_weight(age_days: float) -> float:
    """Decay weight for calibration cases (120-day half-life, 0.25 floor)."""
    return time_decay_weight(age_days, CALIBRATION_HALF_LIFE, CALIBRATION_FLOOR)


def case_age_days(case, as_of: Optional[datetime] = None) -> float:
    """Calculate age in days for a calibration case.

    Uses decision_occurred_at if available, falls back to created_at.
    """
    if as_of is None:
        as_of = datetime.now(timezone.utc)
    reference = getattr(case, "decision_occurred_at", None) or case.created_at
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    return max(0.0, (as_of - reference).total_seconds() / 86400.0)


def evidence_age_days(fragment, as_of: Optional[datetime] = None) -> float:
    """Calculate age in days for an evidence fragment."""
    if as_of is None:
        as_of = datetime.now(timezone.utc)
    ref = fragment.occurred_at
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    return max(0.0, (as_of - ref).total_seconds() / 86400.0)

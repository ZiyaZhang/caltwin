"""Stability assessment for shadow ontology clusters."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import List, Optional
from twin_runtime.application.calibration.time_decay import calibration_decay_weight, case_age_days
from twin_runtime.domain.models.calibration import CalibrationCase


def assess_stability(
    cluster_case_ids: List[str],
    all_cases: List[CalibrationCase],
    as_of: Optional[datetime] = None,
    min_support: int = 3,
    min_decayed_support: float = 1.5,
) -> dict:
    """Assess cluster stability. Returns {stable, support_count, decayed_support, stability_score}."""
    if as_of is None:
        as_of = datetime.now(timezone.utc)
    case_map = {c.case_id: c for c in all_cases}
    cluster_cases = [case_map[cid] for cid in cluster_case_ids if cid in case_map]

    support_count = len(cluster_cases)
    decayed_support = sum(
        calibration_decay_weight(case_age_days(c, as_of))
        for c in cluster_cases
    )

    if support_count < min_support:
        return {"stable": False, "support_count": support_count, "decayed_support": decayed_support, "stability_score": 0.0}

    # Stability score: ratio of decayed_support to raw support (higher = more recent)
    stability_score = decayed_support / support_count if support_count > 0 else 0.0

    stable = decayed_support >= min_decayed_support and support_count >= min_support
    return {
        "stable": stable,
        "support_count": support_count,
        "decayed_support": round(decayed_support, 3),
        "stability_score": round(stability_score, 3),
    }

"""Drift detection: domain-level preference drift + axis-level confidence drift."""
from __future__ import annotations

import math
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from twin_runtime.application.calibration.time_decay import case_age_days
from twin_runtime.domain.models.calibration import CalibrationCase
from twin_runtime.domain.models.drift import DriftReport, DriftSignal
from twin_runtime.domain.models.primitives import DecisionMode
from twin_runtime.domain.models.runtime import RuntimeDecisionTrace
from twin_runtime.domain.models.twin_state import TwinState


def _jsd(p: List[float], q: List[float]) -> float:
    """Jensen-Shannon Divergence between two distributions."""
    m = [(pi + qi) / 2 for pi, qi in zip(p, q)]
    def kl(a, b):
        return sum(ai * math.log(ai / bi) for ai, bi in zip(a, b) if ai > 0 and bi > 0)
    return (kl(p, m) + kl(q, m)) / 2


def _choice_distribution(cases: List[CalibrationCase]) -> Tuple[List[str], List[float]]:
    """Build normalized choice distribution."""
    counts = Counter(c.actual_choice for c in cases)
    total = sum(counts.values())
    labels = sorted(counts.keys())
    probs = [counts[l] / total for l in labels]
    return labels, probs


def _detect_domain_drift(
    cases: List[CalibrationCase],
    as_of: datetime,
    recent_days: int,
    historical_days: int,
    jsd_threshold: float,
    min_recent: int = 3,
    min_historical: int = 5,
) -> List[DriftSignal]:
    """Detect domain-level preference drift per (domain, task_type)."""
    signals = []
    recent_cutoff = as_of - timedelta(days=recent_days)
    historical_cutoff = as_of - timedelta(days=historical_days)

    # Group by (domain, task_type)
    groups: Dict[Tuple[str, str], List[CalibrationCase]] = {}
    for c in cases:
        ref = c.decision_occurred_at or c.created_at
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        key = (c.domain_label.value, c.task_type)
        groups.setdefault(key, []).append(c)

    for (domain, task_type), group_cases in groups.items():
        recent = []
        historical = []
        for c in group_cases:
            ref = c.decision_occurred_at or c.created_at
            if ref.tzinfo is None:
                ref = ref.replace(tzinfo=timezone.utc)
            if ref >= recent_cutoff:
                recent.append(c)
            elif ref >= historical_cutoff:
                historical.append(c)

        if len(recent) < min_recent or len(historical) < min_historical:
            continue

        # Align choice labels
        all_choices = sorted(set(c.actual_choice for c in recent + historical))
        if len(all_choices) < 2:
            continue

        r_counts = Counter(c.actual_choice for c in recent)
        h_counts = Counter(c.actual_choice for c in historical)
        r_total = sum(r_counts.values())
        h_total = sum(h_counts.values())
        r_probs = [(r_counts.get(ch, 0) + 1e-10) / (r_total + 1e-10 * len(all_choices)) for ch in all_choices]
        h_probs = [(h_counts.get(ch, 0) + 1e-10) / (h_total + 1e-10 * len(all_choices)) for ch in all_choices]

        jsd = _jsd(r_probs, h_probs)
        if jsd > jsd_threshold:
            # Determine direction
            r_top = max(r_counts, key=r_counts.get) if r_counts else "?"
            h_top = max(h_counts, key=h_counts.get) if h_counts else "?"
            direction = f"{domain}/{task_type}: shifted from '{h_top}' to '{r_top}'"
            signals.append(DriftSignal(
                dimension=f"{domain}/{task_type}",
                dimension_type="domain",
                direction=direction,
                magnitude=min(1.0, jsd),
                confidence=min(1.0, (len(recent) + len(historical)) / 20),
                recent_window=(recent_cutoff, as_of),
                historical_window=(historical_cutoff, recent_cutoff),
                metric_used="jsd",
            ))

    return signals


def _detect_axis_drift(
    traces: List[RuntimeDecisionTrace],
    as_of: datetime,
    recent_days: int,
    historical_days: int,
    delta_threshold: float,
    min_recent: int = 3,
    min_historical: int = 5,
) -> List[DriftSignal]:
    """Detect axis-level confidence drift from trace head assessments."""
    signals = []
    recent_cutoff = as_of - timedelta(days=recent_days)
    historical_cutoff = as_of - timedelta(days=historical_days)

    # Filter traces: exclude REFUSED, require non-empty assessments
    valid_traces = [
        t for t in traces
        if t.decision_mode != DecisionMode.REFUSED
        and len(t.head_assessments) > 0
    ]

    # Collect per-axis scores with timestamps
    axis_scores: Dict[str, List[Tuple[datetime, float]]] = {}
    for t in valid_traces:
        ts = t.created_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        for ha in t.head_assessments:
            for axis, value in ha.utility_decomposition.items():
                if isinstance(value, (int, float)):
                    axis_scores.setdefault(axis, []).append((ts, float(value)))

    for axis, scores in axis_scores.items():
        recent = [v for ts, v in scores if ts >= recent_cutoff]
        historical = [v for ts, v in scores if historical_cutoff <= ts < recent_cutoff]

        if len(recent) < min_recent or len(historical) < min_historical:
            continue

        r_mean = sum(recent) / len(recent)
        h_mean = sum(historical) / len(historical)
        delta = abs(r_mean - h_mean)

        if delta > delta_threshold:
            direction_word = "increased" if r_mean > h_mean else "decreased"
            signals.append(DriftSignal(
                dimension=axis,
                dimension_type="axis",
                direction=f"{axis}: {direction_word} from {h_mean:.2f} to {r_mean:.2f}",
                magnitude=min(1.0, delta),
                confidence=min(1.0, (len(recent) + len(historical)) / 20),
                recent_window=(recent_cutoff, as_of),
                historical_window=(historical_cutoff, recent_cutoff),
                metric_used="weighted_mean_delta",
            ))

    return signals


def detect_drift(
    cases: List[CalibrationCase],
    traces: List[RuntimeDecisionTrace],
    twin: TwinState,
    *,
    as_of: Optional[datetime] = None,
    recent_window_days: int = 30,
    historical_window_days: int = 180,
    domain_jsd_threshold: float = 0.15,
    axis_delta_threshold: float = 0.1,
) -> DriftReport:
    """Detect preference and confidence drift."""
    if as_of is None:
        as_of = datetime.now(timezone.utc)

    domain_signals = _detect_domain_drift(
        cases, as_of, recent_window_days, historical_window_days, domain_jsd_threshold,
    )
    axis_signals = _detect_axis_drift(
        traces, as_of, recent_window_days, historical_window_days, axis_delta_threshold,
    )

    n_signals = len(domain_signals) + len(axis_signals)
    summary = f"Found {n_signals} drift signal(s): {len(domain_signals)} domain, {len(axis_signals)} axis."

    return DriftReport(
        report_id=str(uuid.uuid4()),
        twin_state_version=twin.state_version,
        as_of=as_of,
        recent_window_days=recent_window_days,
        historical_window_days=historical_window_days,
        domain_signals=domain_signals,
        axis_signals=axis_signals,
        summary=summary,
    )

"""Fidelity Evaluator: run twin against calibration cases, compute similarity scores.

For each CalibrationCase, re-runs the runtime pipeline and compares
the twin's prediction against the actual observed choice.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, List

from ..models.calibration import CalibrationCase, TwinEvaluation
from ..models.primitives import DomainEnum
from ..models.twin_state import TwinState
from ..runtime import run as run_pipeline


def _choice_similarity(predicted_ranking: list[str], actual_choice: str) -> float:
    """Compute how well the twin's ranking matches the actual choice.

    Returns 1.0 if actual_choice is #1 ranked, decaying by position.
    """
    for i, opt in enumerate(predicted_ranking):
        if actual_choice in opt or opt in actual_choice:
            # Position-based score: 1.0 for first, 0.5 for second, etc.
            return 1.0 / (i + 1)
    return 0.0


def _reasoning_similarity(twin_output: str, actual_reasoning: str | None) -> float | None:
    """Simple reasoning overlap score. v0.1: keyword overlap ratio."""
    if not actual_reasoning:
        return None

    twin_words = set(twin_output.lower().split())
    actual_words = set(actual_reasoning.lower().split())

    if not actual_words:
        return None

    overlap = twin_words & actual_words
    # Jaccard-ish but biased toward actual (recall)
    return len(overlap) / len(actual_words) if actual_words else 0.0


def evaluate_single_case(
    case: CalibrationCase,
    twin: TwinState,
) -> tuple[float, float | None, str]:
    """Run twin against a single calibration case.

    Returns (choice_sim, reasoning_sim, twin_output).
    """
    trace = run_pipeline(
        query=case.observed_context,
        option_set=case.option_set,
        twin=twin,
    )

    # Extract twin's ranking from head assessments
    all_rankings: list[str] = []
    for ha in trace.head_assessments:
        all_rankings = ha.option_ranking
        break  # Use first head's ranking as primary

    choice_sim = _choice_similarity(all_rankings, case.actual_choice)
    reasoning_sim = _reasoning_similarity(
        trace.output_text or "", case.actual_reasoning_if_known
    )

    return choice_sim, reasoning_sim, trace.output_text or ""


def evaluate_fidelity(
    cases: List[CalibrationCase],
    twin: TwinState,
) -> TwinEvaluation:
    """Run fidelity evaluation across multiple calibration cases.

    This is the core calibration measurement: how well does the current
    TwinState predict real decisions?
    """
    choice_scores: list[float] = []
    reasoning_scores: list[float] = []
    domain_scores: Dict[str, list[float]] = {}
    case_ids: list[str] = []

    for case in cases:
        choice_sim, reasoning_sim, _ = evaluate_single_case(case, twin)

        choice_scores.append(choice_sim)
        if reasoning_sim is not None:
            reasoning_scores.append(reasoning_sim)

        # Track per-domain
        d = case.domain_label.value
        domain_scores.setdefault(d, []).append(choice_sim)
        case_ids.append(case.case_id)

        # Mark as used
        case.used_for_calibration = True

    # Aggregate
    avg_choice = sum(choice_scores) / len(choice_scores) if choice_scores else 0.0
    avg_reasoning = (
        sum(reasoning_scores) / len(reasoning_scores) if reasoning_scores else None
    )

    domain_reliability = {
        d: sum(scores) / len(scores) for d, scores in domain_scores.items()
    }

    return TwinEvaluation(
        evaluation_id=str(uuid.uuid4()),
        twin_state_version=twin.state_version,
        calibration_case_ids=case_ids,
        choice_similarity=round(avg_choice, 3),
        reasoning_similarity=round(avg_reasoning, 3) if avg_reasoning is not None else None,
        domain_reliability=domain_reliability,
        evaluated_at=datetime.now(timezone.utc),
    )

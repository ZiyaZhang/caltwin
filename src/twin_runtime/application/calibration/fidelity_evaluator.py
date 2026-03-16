"""Fidelity Evaluator: run twin against calibration cases, compute similarity scores.

For each CalibrationCase, re-runs the runtime pipeline and compares
the twin's prediction against the actual observed choice.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from twin_runtime.domain.models.calibration import (
    CalibrationCase,
    EvaluationCaseDetail,
    TwinEvaluation,
)
from twin_runtime.domain.models.primitives import DomainEnum, uncertainty_to_confidence
from twin_runtime.domain.models.twin_state import TwinState

# Lazy import sentinel — actual import deferred to avoid circular dependency at
# collection time. The name `run` is bound at module level via _get_run() so
# that unittest.mock.patch("...fidelity_evaluator.run") can find it.
try:
    from twin_runtime.application.pipeline.runner import run  # noqa: F401
except ImportError:  # pragma: no cover — circular guard during early import
    run = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize(s: str) -> str:
    """Lowercase and strip whitespace for comparison."""
    return s.lower().strip()


def choice_similarity(
    prediction_ranking: list[str],
    actual_choice: str,
) -> tuple[float, Optional[int]]:
    """Compute how well the twin's ranking matches the actual choice.

    Four-step matching:
      1. Normalize (lowercase + strip)
      2. Exact match on normalized strings
      3. Alias lookup (empty for now)
      4. Containment with length guard: len(shorter)/len(longer) > 0.5

    Returns (score, rank) where score = 1/rank for hits, 0.0 for misses.
    rank is 1-indexed (None if no match).
    """
    if not prediction_ranking:
        return 0.0, None

    norm_actual = _normalize(actual_choice)

    for i, opt in enumerate(prediction_ranking):
        norm_opt = _normalize(opt)
        rank = i + 1

        # Step 2: Exact match
        if norm_opt == norm_actual:
            return 1.0 / rank, rank

        # Step 3: Alias lookup (empty for now — placeholder for future extension)

    # Step 4: Containment with length guard
    for i, opt in enumerate(prediction_ranking):
        norm_opt = _normalize(opt)
        rank = i + 1

        # Check containment in either direction
        if norm_actual in norm_opt or norm_opt in norm_actual:
            shorter = min(norm_opt, norm_actual, key=len)
            longer = max(norm_opt, norm_actual, key=len)
            if len(longer) > 0 and len(shorter) / len(longer) > 0.5:
                return 1.0 / rank, rank

    return 0.0, None


def _reasoning_similarity(
    twin_output: str,
    actual_reasoning: Optional[str],
    method: str = "jaccard",
) -> Optional[float]:
    """Simple reasoning overlap score.

    v0.1: keyword overlap ratio (Jaccard-ish, biased toward actual recall).
    method param reserved for future extension.
    """
    if not actual_reasoning:
        return None

    twin_words = set(twin_output.lower().split())
    actual_words = set(actual_reasoning.lower().split())

    if not actual_words:
        return None

    overlap = twin_words & actual_words
    return len(overlap) / len(actual_words)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class SingleCaseResult:
    """Result of evaluating a single calibration case."""
    choice_score: float
    reasoning_score: Optional[float]
    rank: Optional[int]
    prediction_ranking: list[str]
    confidence_at_prediction: float
    output_text: str
    trace_id: str


# ---------------------------------------------------------------------------
# Core evaluation functions
# ---------------------------------------------------------------------------

def evaluate_single_case(
    case: CalibrationCase,
    twin: TwinState,
) -> SingleCaseResult:
    """Run twin against a single calibration case.

    Returns a SingleCaseResult with all per-case scoring data.
    """
    trace = run(
        query=case.observed_context,
        option_set=case.option_set,
        twin=twin,
    )

    # Extract twin's ranking from first head assessment
    prediction_ranking: list[str] = []
    for ha in trace.head_assessments:
        prediction_ranking = ha.option_ranking
        break

    choice_score, rank = choice_similarity(prediction_ranking, case.actual_choice)
    reasoning_score = _reasoning_similarity(
        trace.output_text or "", case.actual_reasoning_if_known
    )
    confidence_at_prediction = uncertainty_to_confidence(trace.uncertainty)

    return SingleCaseResult(
        choice_score=choice_score,
        reasoning_score=reasoning_score,
        rank=rank,
        prediction_ranking=prediction_ranking,
        confidence_at_prediction=confidence_at_prediction,
        output_text=trace.output_text or "",
        trace_id=trace.trace_id,
    )


def evaluate_fidelity(
    cases: List[CalibrationCase],
    twin: TwinState,
) -> TwinEvaluation:
    """Run fidelity evaluation across multiple calibration cases.

    Iterates cases, calls evaluate_single_case for each, builds
    EvaluationCaseDetail per case, and aggregates into TwinEvaluation
    with case_details populated.

    Note: compute_fidelity_score (CF/RF/CQ/TS) is implemented in Task 6.
    """
    choice_scores: list[float] = []
    reasoning_scores: list[float] = []
    domain_scores: Dict[str, list[float]] = {}
    case_ids: list[str] = []
    case_details: list[EvaluationCaseDetail] = []

    for case in cases:
        result = evaluate_single_case(case, twin)

        choice_scores.append(result.choice_score)
        if result.reasoning_score is not None:
            reasoning_scores.append(result.reasoning_score)

        # Track per-domain
        d = case.domain_label.value
        domain_scores.setdefault(d, []).append(result.choice_score)
        case_ids.append(case.case_id)

        # Mark as used
        case.used_for_calibration = True

        # Build residual_direction
        actual = case.actual_choice
        if result.rank is None or result.rank > 1:
            if result.prediction_ranking:
                top_pred = result.prediction_ranking[0]
            else:
                top_pred = "（无预测）"
            residual_direction = f"twin首选'{top_pred}'，实际为'{actual}'"
        else:
            residual_direction = ""

        # Build EvaluationCaseDetail
        detail = EvaluationCaseDetail(
            case_id=case.case_id,
            domain=case.domain_label,
            task_type=case.task_type,
            observed_context=case.observed_context,
            choice_score=result.choice_score,
            reasoning_score=result.reasoning_score,
            prediction_ranking=result.prediction_ranking,
            actual_choice=case.actual_choice,
            confidence_at_prediction=result.confidence_at_prediction,
            residual_direction=residual_direction,
        )
        case_details.append(detail)

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
        case_details=case_details,
    )

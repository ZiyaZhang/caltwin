"""Fidelity Evaluator: run twin against calibration cases, compute similarity scores.

For each CalibrationCase, re-runs the runtime pipeline and compares
the twin's prediction against the actual observed choice.
"""

from __future__ import annotations

import statistics
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from twin_runtime.domain.models.calibration import (
    CalibrationCase,
    EvaluationCaseDetail,
    FidelityMetric,
    TwinEvaluation,
    TwinFidelityScore,
)
from twin_runtime.domain.models.primitives import DomainEnum, uncertainty_to_confidence
from twin_runtime.domain.models.twin_state import TwinState

from twin_runtime.domain.models.runtime import RuntimeDecisionTrace

PipelineRunner = Callable[..., RuntimeDecisionTrace]


def _get_default_runner() -> PipelineRunner:
    """Lazy import of pipeline runner to avoid circular dependency."""
    from twin_runtime.application.pipeline.runner import run
    return run


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
    *,
    runner: Optional[PipelineRunner] = None,
) -> SingleCaseResult:
    """Run twin against a single calibration case.

    Returns a SingleCaseResult with all per-case scoring data.
    """
    if runner is None:
        runner = _get_default_runner()
    trace = runner(
        query=case.observed_context,
        option_set=case.option_set,
        twin=twin,
    )

    # Extract twin's ranking — prefer the head matching this case's domain,
    # fall back to highest-confidence head if no domain match
    prediction_ranking: list[str] = []
    target_domain = case.domain_label
    domain_match = [ha for ha in trace.head_assessments if ha.domain == target_domain]
    if domain_match:
        prediction_ranking = domain_match[0].option_ranking
    elif trace.head_assessments:
        # Fallback: highest-confidence head
        best = max(trace.head_assessments, key=lambda h: getattr(h, 'confidence', 0))
        prediction_ranking = best.option_ranking

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
    *,
    strict: bool = False,
    runner: Optional[PipelineRunner] = None,
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

    error_count = 0
    failed_case_ids: list[str] = []

    for case in cases:
        try:
            result = evaluate_single_case(case, twin, runner=runner)
        except Exception as e:
            if strict:
                raise
            error_count += 1
            failed_case_ids.append(case.case_id)
            print(f"  ERROR on case {case.case_id}: {e}")
            continue  # Skip - don't add 0.0 to scores

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
        failed_case_count=error_count,
    )


# ---------------------------------------------------------------------------
# Fidelity score computation (CF / RF / CQ / TS)
# ---------------------------------------------------------------------------

def _compute_choice_fidelity(details: List[EvaluationCaseDetail]) -> FidelityMetric:
    """Average choice_score; confidence = min(1, n/30)."""
    n = len(details)
    if n == 0:
        return FidelityMetric(value=0.0, confidence_in_metric=0.0, case_count=0)
    avg = sum(d.choice_score for d in details) / n
    confidence = min(1.0, n / 30.0)
    return FidelityMetric(value=avg, confidence_in_metric=confidence, case_count=n)


def _compute_reasoning_fidelity(details: List[EvaluationCaseDetail]) -> FidelityMetric:
    """Average reasoning_score where not None; confidence = min(1, n/20)."""
    scored = [d.reasoning_score for d in details if d.reasoning_score is not None]
    n = len(scored)
    if n == 0:
        return FidelityMetric(value=0.0, confidence_in_metric=0.0, case_count=0)
    avg = sum(scored) / n
    confidence = min(1.0, n / 20.0)
    return FidelityMetric(value=avg, confidence_in_metric=confidence, case_count=n)


def _compute_calibration_quality(details: List[EvaluationCaseDetail]) -> FidelityMetric:
    """ECE bins [0,0.3), [0.3,0.6), [0.6,1.0]; CQ = 1 - ECE.

    confidence = min(1, non_empty_bins / 3 * n / 15)
    """
    n = len(details)
    if n == 0:
        return FidelityMetric(
            value=0.0, confidence_in_metric=0.0, case_count=0,
            details={"bins": []},
        )

    # Define bins: [0,0.3), [0.3,0.6), [0.6,1.0]
    bin_edges = [(0.0, 0.3), (0.3, 0.6), (0.6, 1.0)]
    bins: List[Dict] = []
    total_ece = 0.0

    for low, high in bin_edges:
        bucket = [
            d for d in details
            if low <= d.confidence_at_prediction < high
            or (high == 1.0 and d.confidence_at_prediction == 1.0)
        ]
        if not bucket:
            bins.append({"range": [low, high], "count": 0, "avg_conf": None, "accuracy": None})
            continue
        avg_conf = sum(d.confidence_at_prediction for d in bucket) / len(bucket)
        accuracy = sum(1 for d in bucket if d.choice_score >= 1.0) / len(bucket)
        bin_ece = abs(avg_conf - accuracy) * len(bucket) / n
        total_ece += bin_ece
        bins.append({
            "range": [low, high], "count": len(bucket),
            "avg_conf": avg_conf, "accuracy": accuracy,
        })

    cq = max(0.0, 1.0 - total_ece)
    non_empty = sum(1 for b in bins if b["count"] > 0)
    confidence = min(1.0, (non_empty / 3.0) * (n / 15.0))

    return FidelityMetric(
        value=cq, confidence_in_metric=confidence, case_count=n,
        details={"bins": bins},
    )


def _compute_temporal_stability(
    current: TwinEvaluation,
    historical: Optional[List[TwinEvaluation]],
) -> FidelityMetric:
    """CV = std / max(mean, 1e-6); TS = 1 - CV; confidence = min(1, n/5).

    Single eval → value=1.0, confidence=0.0.
    """
    if not historical:
        return FidelityMetric(value=1.0, confidence_in_metric=0.0, case_count=1)

    all_sims = [ev.choice_similarity for ev in historical] + [current.choice_similarity]
    n = len(all_sims)

    if n < 2:
        return FidelityMetric(value=1.0, confidence_in_metric=0.0, case_count=n)

    mean = statistics.mean(all_sims)
    std = statistics.stdev(all_sims)
    cv = std / max(mean, 1e-6)
    ts = max(0.0, 1.0 - cv)
    confidence = min(1.0, n / 5.0)

    return FidelityMetric(value=ts, confidence_in_metric=confidence, case_count=n)


def compute_fidelity_score(
    evaluation: TwinEvaluation,
    historical_evaluations: Optional[List[TwinEvaluation]] = None,
) -> TwinFidelityScore:
    """Compute four-metric fidelity decomposition (CF, RF, CQ, TS).

    Returns a TwinFidelityScore with choice_fidelity, reasoning_fidelity,
    calibration_quality, temporal_stability, and derived overall_score.
    """
    details = evaluation.case_details or []

    cf = _compute_choice_fidelity(details)
    rf = _compute_reasoning_fidelity(details)
    cq = _compute_calibration_quality(details)
    ts = _compute_temporal_stability(evaluation, historical_evaluations)

    # Overall score: confidence-weighted average of CF and CQ (RF/TS contribute when available)
    weights = [
        (cf.value, cf.confidence_in_metric),
        (cq.value, cq.confidence_in_metric),
        (ts.value, ts.confidence_in_metric),
    ]
    if rf.case_count > 0:
        weights.append((rf.value, rf.confidence_in_metric))

    total_weight = sum(w for _, w in weights)
    if total_weight > 0:
        overall_score = sum(v * w for v, w in weights) / total_weight
        overall_confidence = min(1.0, total_weight / len(weights))
    else:
        # Fallback: simple average of CF and CQ
        overall_score = (cf.value + cq.value) / 2.0
        overall_confidence = 0.0

    overall_score = max(0.0, min(1.0, overall_score))
    overall_confidence = max(0.0, min(1.0, overall_confidence))

    # Domain breakdown: average choice_score per domain
    domain_scores: Dict[str, List[float]] = {}
    for d in details:
        key = d.domain.value if hasattr(d.domain, "value") else str(d.domain)
        domain_scores.setdefault(key, []).append(d.choice_score)
    domain_breakdown = {
        k: sum(v) / len(v) for k, v in domain_scores.items()
    }

    return TwinFidelityScore(
        score_id=str(uuid.uuid4()),
        twin_state_version=evaluation.twin_state_version,
        computed_at=datetime.now(timezone.utc),
        choice_fidelity=cf,
        reasoning_fidelity=rf,
        calibration_quality=cq,
        temporal_stability=ts,
        overall_score=round(overall_score, 4),
        overall_confidence=round(overall_confidence, 4),
        total_cases=len(details),
        domain_breakdown=domain_breakdown,
        evaluation_ids=[evaluation.evaluation_id],
    )

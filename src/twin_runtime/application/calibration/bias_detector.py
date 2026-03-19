"""Prior bias auto-detection module.

Two-stage pipeline:
  Stage 1 — Frequency filter: group case_details by (domain, task_type),
             find groups with enough misses and sufficient bias strength.
  Stage 2 — LLM commonality analysis: call llm.ask_json() to characterise
             the pattern and build a BiasCorrectionSuggestion.

On LLM failure the module degrades gracefully: returns a DetectedBias
with suggested_correction=None and a plain-text llm_analysis.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from twin_runtime.domain.models.calibration import (
    BiasCorrectionSuggestion,
    DetectedBias,
    EvaluationCaseDetail,
    TwinEvaluation,
)
from twin_runtime.domain.models.primitives import (
    BiasCorrectionAction,
    DetectedBiasStatus,
    DomainEnum,
)
from twin_runtime.domain.ports.llm_port import LLMPort


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_miss(detail: EvaluationCaseDetail) -> bool:
    """Return True when the twin did NOT hit the actual choice at rank 1."""
    return bool(detail.residual_direction)


def _dominant_residual(miss_details: List[EvaluationCaseDetail]) -> Tuple[str, int]:
    """Return the most common residual direction string and its count.

    Counts exact-string occurrences across the miss cases.
    """
    if not miss_details:
        return "", 0
    counts: Dict[str, int] = defaultdict(int)
    for d in miss_details:
        counts[d.residual_direction] += 1
    dominant = max(counts, key=lambda k: counts[k])
    return dominant, counts[dominant]


def _build_llm_prompt(
    domain: DomainEnum,
    task_type: str,
    miss_details: List[EvaluationCaseDetail],
) -> Tuple[str, str]:
    """Build (system, user) prompt for LLM commonality analysis."""
    system = (
        "You are a calibration analyst for a decision-making twin model. "
        "Your job is to identify systematic prior biases from a set of "
        "evaluation misses and suggest a corrective instruction. "
        "Respond ONLY with valid JSON containing these keys: "
        '"direction_description" (str), "common_pattern" (str), '
        '"suggested_instruction" (str).'
    )

    cases_text = []
    for d in miss_details:
        top_pred = d.prediction_ranking[0] if d.prediction_ranking else "（无预测）"
        cases_text.append(
            f"- case_id={d.case_id}\n"
            f"  context: {d.observed_context}\n"
            f"  twin_top_prediction: {top_pred}\n"
            f"  actual_choice: {d.actual_choice}\n"
            f"  residual: {d.residual_direction}"
        )

    user = (
        f"Domain: {domain.value}, task_type: {task_type}\n\n"
        f"The following cases were evaluation misses (twin ranked actual choice below #1):\n\n"
        + "\n".join(cases_text)
        + "\n\nIdentify the common bias pattern and suggest a calibration instruction."
    )
    return system, user


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_biases(
    evaluation: TwinEvaluation,
    *,
    llm: LLMPort,
    min_sample: int = 3,
    min_bias_strength: float = 0.6,
) -> List[DetectedBias]:
    """Detect systematic prior biases in a TwinEvaluation.

    Parameters
    ----------
    evaluation:
        A completed TwinEvaluation whose case_details are populated.
    llm:
        An LLMPort implementation used for commonality analysis.
    min_sample:
        Minimum number of cases in a (domain, task_type) group before
        bias detection is attempted.
    min_bias_strength:
        Minimum miss ratio (misses / total) required to flag a bias.

    Returns
    -------
    List[DetectedBias]
        Zero or more detected biases, each in PENDING_REVIEW status.
    """
    # -----------------------------------------------------------------------
    # Stage 1: Frequency filter
    # -----------------------------------------------------------------------
    groups: Dict[Tuple[DomainEnum, str], List[EvaluationCaseDetail]] = defaultdict(list)
    for detail in evaluation.case_details:
        groups[(detail.domain, detail.task_type)].append(detail)

    candidate_groups: List[Tuple[DomainEnum, str, List[EvaluationCaseDetail], float]] = []

    for (domain, task_type), cases in groups.items():
        n = len(cases)
        if n < min_sample:
            continue

        misses = [c for c in cases if _is_miss(c)]
        miss_ratio = len(misses) / n

        if miss_ratio < min_bias_strength:
            continue

        # Require at least 2 distinct case_ids with non-empty residuals
        distinct_miss_ids = {c.case_id for c in misses}
        if len(distinct_miss_ids) < 2:
            continue

        candidate_groups.append((domain, task_type, misses, miss_ratio))

    if not candidate_groups:
        return []

    # -----------------------------------------------------------------------
    # Stage 2: LLM commonality analysis
    # -----------------------------------------------------------------------
    detected: List[DetectedBias] = []

    for domain, task_type, miss_details, bias_strength in candidate_groups:
        supporting_ids = [d.case_id for d in miss_details]

        # Attempt LLM analysis
        suggested_correction: BiasCorrectionSuggestion | None = None
        direction_description = "（未知偏向）"
        llm_analysis: str | None = None

        try:
            system_prompt, user_prompt = _build_llm_prompt(domain, task_type, miss_details)
            response = llm.ask_json(system_prompt, user_prompt)

            if not isinstance(response, dict):
                raise ValueError(f"LLM returned non-dict response: {type(response)}")

            direction_description = response.get("direction_description", direction_description)
            common_pattern = response.get("common_pattern", "")
            suggested_instruction = response.get("suggested_instruction", "")

            llm_analysis = f"common_pattern={common_pattern}; suggested_instruction={suggested_instruction}"

            suggested_correction = BiasCorrectionSuggestion(
                target_scope={"domain": domain.value, "task_type": task_type},
                correction_action=BiasCorrectionAction.REWEIGHT,
                correction_payload={"instruction": suggested_instruction},
                rationale=common_pattern,
            )

        except Exception as exc:  # noqa: BLE001
            llm_analysis = f"LLM分析失败，仅基于统计 (error: {exc})"
            suggested_correction = None

        bias = DetectedBias(
            bias_id=str(uuid.uuid4()),
            detected_at=datetime.now(timezone.utc),
            domain=domain,
            task_type=task_type,
            direction_description=direction_description,
            supporting_case_ids=supporting_ids,
            sample_size=len(supporting_ids),
            bias_strength=round(bias_strength, 4),
            llm_analysis=llm_analysis,
            status=DetectedBiasStatus.PENDING_REVIEW,
            suggested_correction=suggested_correction,
        )
        detected.append(bias)

    return detected

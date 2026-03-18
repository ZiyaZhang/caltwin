"""Build text documents from CalibrationCases for TF-IDF vectorization."""
from __future__ import annotations
from twin_runtime.domain.models.calibration import CalibrationCase


def build_document(case: CalibrationCase) -> str:
    """Build text document from CalibrationCase. No trace enrichment in v1."""
    parts = [case.observed_context]
    if case.actual_reasoning_if_known:
        parts.append(case.actual_reasoning_if_known)
    parts.append(f"stakes:{case.stakes.value}")
    parts.append(f"reversibility:{case.reversibility.value}")
    parts.append(f"domain:{case.domain_label.value}")
    parts.append(f"task_type:{case.task_type}")
    return " ".join(parts)

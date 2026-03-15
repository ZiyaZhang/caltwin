"""Calibration engine models: CalibrationCase, CandidateCalibrationCase, TwinEvaluation."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from .primitives import (
    CandidateSourceType,
    DomainEnum,
    OrdinalTriLevel,
    confidence_field,
)


class CandidateCalibrationCase(BaseModel):
    candidate_id: str = Field(min_length=1)
    created_at: datetime
    source_type: CandidateSourceType
    originating_trace_id: Optional[str] = None
    domain_label: DomainEnum
    observed_context: str
    option_set: List[str] = Field(min_length=1)
    observed_choice: str
    observed_reasoning: Optional[str] = None
    stakes: OrdinalTriLevel
    reversibility: OrdinalTriLevel
    time_pressure: Optional[OrdinalTriLevel] = None
    ground_truth_confidence: float = confidence_field()
    promoted_to_calibration_case: bool = False
    promotion_reason: Optional[str] = None


class CalibrationCase(BaseModel):
    case_id: str = Field(min_length=1)
    created_at: datetime
    domain_label: DomainEnum
    task_type: str
    observed_context: str
    option_set: List[str] = Field(min_length=1)
    actual_choice: str
    actual_reasoning_if_known: Optional[str] = None
    stakes: OrdinalTriLevel
    reversibility: OrdinalTriLevel
    time_pressure: Optional[OrdinalTriLevel] = None
    confidence_of_ground_truth: float = confidence_field()
    used_for_calibration: bool = False


class TwinEvaluation(BaseModel):
    evaluation_id: str = Field(min_length=1)
    twin_state_version: str
    calibration_case_ids: List[str]
    choice_similarity: float = confidence_field()
    reasoning_similarity: Optional[float] = confidence_field(default=None)
    style_similarity: Optional[float] = confidence_field(default=None)
    social_similarity: Optional[float] = confidence_field(default=None)
    domain_reliability: Dict[str, float] = Field(
        description="Map of domain -> reliability score."
    )
    transfer_reliability: Dict[str, float] = Field(
        default_factory=dict,
        description="Map of 'from->to' -> reliability score.",
    )
    prior_bias_flags: List[str] = Field(default_factory=list)
    evaluated_at: datetime

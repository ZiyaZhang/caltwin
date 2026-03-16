"""Calibration engine models: CalibrationCase, CandidateCalibrationCase, TwinEvaluation."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

from twin_runtime.domain.models.primitives import (
    CandidateSourceType,
    DomainEnum,
    OrdinalTriLevel,
    OutcomeSource,
    canonicalize_task_type,
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


class EvaluationCaseDetail(BaseModel):
    case_id: str
    domain: DomainEnum
    task_type: str
    observed_context: str
    choice_score: float = confidence_field()
    reasoning_score: Optional[float] = None
    prediction_ranking: List[str]
    actual_choice: str
    confidence_at_prediction: float = confidence_field()
    residual_direction: str

    @field_validator("task_type", mode="before")
    @classmethod
    def _canonicalize(cls, v: str) -> str:
        return canonicalize_task_type(v)


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
    case_details: List[EvaluationCaseDetail] = Field(default_factory=list)
    fidelity_score_id: Optional[str] = None


class OutcomeRecord(BaseModel):
    outcome_id: str
    trace_id: str
    user_id: str
    actual_choice: str
    actual_reasoning: Optional[str] = None
    outcome_source: OutcomeSource
    prediction_rank: Optional[int] = Field(default=None, ge=1)
    confidence_at_prediction: float = confidence_field()
    time_to_outcome_hours: Optional[float] = Field(default=None, ge=0)
    domain: DomainEnum
    task_type: Optional[str] = None
    created_at: datetime

    @computed_field
    @property
    def choice_matched_prediction(self) -> bool:
        return self.prediction_rank == 1

    @field_validator("task_type", mode="before")
    @classmethod
    def _canonicalize(cls, v):
        return canonicalize_task_type(v) if v else v

    @model_validator(mode="after")
    def _validate_outcome_source(self):
        if self.outcome_source == OutcomeSource.USER_REFLECTION and not self.actual_reasoning:
            raise ValueError("USER_REFLECTION requires actual_reasoning")
        return self

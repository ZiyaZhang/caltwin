"""Calibration engine models: CalibrationCase, CandidateCalibrationCase, TwinEvaluation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, Dict, List, Optional

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

from twin_runtime.domain.models.primitives import (
    BiasCorrectionAction,
    CandidateSourceType,
    DetectedBiasStatus,
    DomainEnum,
    MicroCalibrationTrigger,
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
    decision_occurred_at: Optional[datetime] = Field(
        default=None,
        description="When the original decision was made. Decay uses this if available, falls back to created_at.",
    )
    promoted_to_calibration_case: bool = False
    promotion_reason: Optional[str] = None

    @model_validator(mode="after")
    def _validate_observed_choice_in_options(self):
        if self.observed_choice and self.option_set:
            normalized_options = {o.lower().strip() for o in self.option_set}
            if self.observed_choice.lower().strip() not in normalized_options:
                raise ValueError(
                    f"observed_choice '{self.observed_choice}' not found in option_set {self.option_set}"
                )
        return self


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
    expect_abstention: bool = Field(
        default=False,
        description="True for out-of-scope cases where twin SHOULD refuse/degrade. "
        "Only these cases contribute to abstention_accuracy.",
    )
    decision_occurred_at: Optional[datetime] = Field(
        default=None,
        description="When the original decision was made. Decay uses this if available, falls back to created_at.",
    )
    contradiction_discount: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Reserved for future use.",
    )
    used_for_calibration: bool = False

    @model_validator(mode="after")
    def _validate_actual_choice_in_options(self):
        if self.actual_choice and self.option_set:
            normalized_options = {o.lower().strip() for o in self.option_set}
            if self.actual_choice.lower().strip() not in normalized_options:
                raise ValueError(
                    f"actual_choice '{self.actual_choice}' not found in option_set {self.option_set}"
                )
        return self


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
    time_decay_weight: float = Field(default=1.0, description="Decay weight at evaluation time")

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
    failed_case_count: int = Field(default=0, description="Cases that failed due to system error, excluded from metrics")
    abstention_accuracy: Optional[float] = Field(
        default=None,
        ge=0.0, le=1.0,
        description="% of out-of-scope cases correctly REFUSED or DEGRADED",
    )
    abstention_case_count: int = Field(
        default=0,
        description="Number of out-of-scope cases evaluated for abstention",
    )
    weighted_choice_similarity: Optional[float] = Field(default=None)
    weighted_reasoning_similarity: Optional[float] = Field(default=None)
    weighted_domain_reliability: Optional[Dict[str, float]] = Field(default=None)
    decay_params_used: Optional[Dict[str, Any]] = Field(default=None)
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


class BiasCorrectionSuggestion(BaseModel):
    target_scope: Dict[str, Any]
    correction_action: BiasCorrectionAction
    correction_payload: Dict[str, Any] = Field(default_factory=dict)
    rationale: str


class DetectedBias(BaseModel):
    bias_id: str = Field(min_length=1)
    detected_at: datetime
    domain: DomainEnum
    task_type: Optional[str] = None
    direction_description: str
    supporting_case_ids: List[str] = Field(default_factory=list)
    sample_size: int = Field(ge=1)
    bias_strength: float = confidence_field()
    llm_analysis: Optional[str] = None
    status: DetectedBiasStatus = DetectedBiasStatus.PENDING_REVIEW
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    suggested_correction: Optional[BiasCorrectionSuggestion] = None

    @field_validator("task_type", mode="before")
    @classmethod
    def _canonicalize(cls, v):
        return canonicalize_task_type(v) if v else v

    @model_validator(mode="after")
    def _validate_review_fields(self):
        if self.status in (DetectedBiasStatus.ACCEPTED, DetectedBiasStatus.DISMISSED):
            if self.reviewed_at is None or self.reviewed_by is None:
                raise ValueError(
                    f"status={self.status.value} requires reviewed_at and reviewed_by"
                )
        return self

    @model_validator(mode="after")
    def _validate_sample_consistency(self):
        if self.supporting_case_ids and len(self.supporting_case_ids) != self.sample_size:
            raise ValueError(
                f"sample_size={self.sample_size} does not match "
                f"len(supporting_case_ids)={len(self.supporting_case_ids)}"
            )
        return self


class FidelityMetric(BaseModel):
    value: float = confidence_field()
    confidence_in_metric: float = confidence_field()
    case_count: int = Field(ge=0)
    details: Optional[Dict[str, Any]] = None


class TwinFidelityScore(BaseModel):
    ECE_BIN_EDGES: ClassVar[List[float]] = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5,
                                             0.6, 0.7, 0.8, 0.9, 1.0]

    score_id: str = Field(min_length=1)
    twin_state_version: str
    computed_at: datetime
    choice_fidelity: FidelityMetric
    reasoning_fidelity: FidelityMetric
    calibration_quality: FidelityMetric
    temporal_stability: FidelityMetric
    overall_score: float = confidence_field()
    overall_confidence: float = confidence_field()
    total_cases: int = Field(ge=0)
    domain_breakdown: Dict[str, float] = Field(default_factory=dict)
    evaluation_ids: List[str] = Field(default_factory=list)
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _validate_domain_breakdown(self):
        for domain, score in self.domain_breakdown.items():
            if not (0.0 <= score <= 1.0):
                raise ValueError(
                    f"domain_breakdown['{domain}']={score} is out of range [0.0, 1.0]"
                )
        return self


class MicroCalibrationUpdate(BaseModel):
    update_id: str = Field(min_length=1)
    twin_state_version: str
    trigger: MicroCalibrationTrigger
    created_at: datetime
    parameter_deltas: Dict[str, float]
    previous_values: Dict[str, float] = Field(default_factory=dict)
    learning_rate_used: float = Field(gt=0.0)
    rationale: str
    applied: bool = False
    applied_at: Optional[datetime] = None
    applied_by: Optional[str] = None

    @model_validator(mode="after")
    def _validate_applied_state(self):
        if self.applied and self.applied_at is None:
            raise ValueError("applied=True requires applied_at timestamp")
        return self

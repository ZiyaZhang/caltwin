"""Runtime pipeline models: HeadAssessment, ConflictReport, RuntimeDecisionTrace, RuntimeEvent."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from twin_runtime.domain.models.primitives import (
    ConflictType,
    DecisionMode,
    DomainEnum,
    MergeStrategy,
    RuntimeEventType,
    confidence_field,
)


class HeadAssessment(BaseModel):
    domain: DomainEnum
    head_version: str
    option_ranking: List[str] = Field(min_length=1)
    utility_decomposition: Dict[str, Union[float, str, Dict[str, Any]]] = Field(
        description="Value-axis decomposition. Keys are axes, values are scores or labels."
    )
    confidence: float = confidence_field()
    used_core_variables: List[str] = Field(default_factory=list)
    used_evidence_types: List[str] = Field(default_factory=list)


class ConflictReport(BaseModel):
    report_id: str = Field(min_length=1)
    activated_heads: List[DomainEnum]
    conflict_types: List[ConflictType] = Field(min_length=1)
    utility_conflict_axes: List[str] = Field(default_factory=list)
    belief_conflict_axes: List[str] = Field(default_factory=list)
    evidence_conflict_sources: List[str] = Field(default_factory=list)
    resolvable_by_system: bool
    requires_user_clarification: bool
    requires_more_evidence: bool
    final_merge_strategy: MergeStrategy


class RuntimeDecisionTrace(BaseModel):
    trace_id: str = Field(min_length=1)
    twin_state_version: str
    situation_frame_id: str = Field(min_length=1)
    activated_domains: List[DomainEnum]
    head_assessments: List[HeadAssessment] = Field(min_length=1)
    conflict_report_id: Optional[str] = None
    final_decision: str
    decision_mode: DecisionMode
    uncertainty: float = confidence_field()
    refusal_or_degrade_reason: Optional[str] = None
    output_text: Optional[str] = None
    memory_access_plan: Optional[Any] = Field(
        default=None, description="MemoryAccessPlan used for this decision (audit)"
    )
    retrieved_evidence_count: int = Field(
        default=0, description="Number of evidence fragments retrieved by planner"
    )
    skipped_domains: Dict[str, str] = Field(
        default_factory=dict, description="Domains skipped by planner gating, with reasons"
    )
    outcome_id: Optional[str] = None
    fidelity_prediction: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Predicted fidelity [0,1]"
    )
    pending_calibration_update: Optional[Any] = Field(
        default=None, description="MicroCalibrationUpdate if micro_calibrate=True"
    )
    created_at: datetime


class RuntimeEvent(BaseModel):
    event_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    event_type: RuntimeEventType
    payload: Dict[str, Any]
    event_confidence: float = confidence_field(
        description="Confidence that this observation is accurate."
    )
    observed_at: datetime

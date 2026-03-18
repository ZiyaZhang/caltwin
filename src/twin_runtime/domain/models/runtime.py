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
    ranking_divergence_pairs: List[str] = Field(
        default_factory=list,
        description="Cross-domain ranking inversions",
    )
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
    head_assessments: List[HeadAssessment] = Field(default_factory=list)
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
    query: str = Field(default="", description="Original decision query")
    situation_frame: Optional[Dict[str, Any]] = Field(
        default=None,
        description="JSON-safe snapshot of SituationFrame at decision time",
    )
    scope_guard_result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Deterministic scope guard output",
    )
    refusal_reason_code: Optional[str] = Field(
        default=None,
        description="OUT_OF_SCOPE | NON_MODELED | NON_MODELED_PARTIAL | POLICY_RESTRICTED | LOW_RELIABILITY | DEGRADED_SCOPE | INSUFFICIENT_EVIDENCE",
    )
    # Routing metadata (Phase 5b)
    route_path: str = Field(default="s1_direct", description="Execution path: s1_direct | s2_deliberate | no_execution")
    route_reason_codes: List[str] = Field(default_factory=list)
    boundary_policy: str = Field(default="normal", description="normal | force_degrade | force_refuse")
    deliberation_rounds: int = Field(default=0, description="Number of deliberation rounds (S1=0)")
    terminated_by: Optional[str] = Field(default=None, description="TerminationReason value")
    deliberation_round_summaries: List[Dict[str, Any]] = Field(default_factory=list)
    shadow_scores: Optional[Dict[str, float]] = Field(default=None)


class RuntimeEvent(BaseModel):
    event_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    event_type: RuntimeEventType
    payload: Dict[str, Any]
    event_confidence: float = confidence_field(
        description="Confidence that this observation is accurate."
    )
    observed_at: datetime

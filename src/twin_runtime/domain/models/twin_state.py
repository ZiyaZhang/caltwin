"""TwinState and all sub-component models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from twin_runtime.domain.models.primitives import (
    BiasCorrectionAction,
    ChangeStrategy,
    ConflictStyle,
    ControlOrientation,
    DomainEnum,
    MergeStrategy,
    OrdinalTriLevel,
    ReliabilityScopeStatus,
    RelationshipModel,
    confidence_field,
    weight_field,
    bipolar_field,
)


# --- Sub-components ---


class SharedDecisionCore(BaseModel):
    risk_tolerance: float = confidence_field()
    ambiguity_tolerance: float = confidence_field()
    action_threshold: float = confidence_field()
    information_threshold: float = confidence_field()
    reversibility_preference: float = confidence_field()
    regret_sensitivity: float = confidence_field()
    explore_exploit_balance: float = confidence_field()
    conflict_style: ConflictStyle
    social_proof_dependence: Optional[float] = confidence_field(default=None)
    decision_latency_hours_p50: Optional[float] = Field(
        default=None, ge=0.0, description="Median observed decision latency in hours."
    )
    decision_latency_confidence: Optional[float] = confidence_field(default=None)
    core_confidence: float = confidence_field()
    evidence_count: int = Field(ge=0)
    last_recalibrated_at: datetime


class CausalBeliefModel(BaseModel):
    control_orientation: ControlOrientation
    effort_vs_system_weight: Optional[float] = bipolar_field(
        default=None,
        description="0 = effort/ability dominant, 1 = system/luck dominant.",
    )
    relationship_model: Optional[RelationshipModel] = None
    change_strategy: Optional[ChangeStrategy] = None
    preferred_levers: List[str] = Field(default_factory=list)
    ignored_levers: List[str] = Field(default_factory=list)
    option_visibility_bias: List[str] = Field(default_factory=list)
    causal_confidence: float = confidence_field()
    anchor_cases: List[str] = Field(default_factory=list)


class EvidenceWeightProfile(BaseModel):
    self_report_weight: float = weight_field()
    historical_behavior_weight: float = weight_field()
    recent_behavior_weight: float = weight_field()
    explicit_reflection_weight: Optional[float] = weight_field(default=None)
    public_expression_weight: Optional[float] = weight_field(default=None)
    private_expression_weight: Optional[float] = weight_field(default=None)
    outcome_feedback_weight: float = weight_field()
    weight_confidence: float = confidence_field()

    model_config = {
        "json_schema_extra": {
            "description": "Relative importance weights. The system normalizes internally; they do not need to sum to 1."
        }
    }


class DomainHead(BaseModel):
    domain: DomainEnum
    head_version: str
    goal_axes: List[str]
    default_priority_order: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(
        default_factory=list,
        description="Domain-specific keywords for rule-based routing. Supports any language."
    )
    evidence_weight_profile: EvidenceWeightProfile
    head_reliability: float = confidence_field()
    supported_task_types: List[str]
    unsupported_task_types: List[str] = Field(default_factory=list)
    last_recalibrated_at: datetime


class TransferCoefficient(BaseModel):
    from_domain: DomainEnum
    to_domain: DomainEnum
    coefficient: float = confidence_field()
    confidence: float = confidence_field()
    supporting_case_count: int = Field(ge=0)
    last_validated_at: datetime


class ReliabilityProfileEntry(BaseModel):
    domain: DomainEnum
    task_type: str
    reliability_score: float = confidence_field()
    uncertainty_band: Optional[str] = None
    evidence_strength: float = confidence_field()
    known_failure_modes: List[str] = Field(default_factory=list)
    scope_status: ReliabilityScopeStatus
    last_updated_at: datetime


class RejectionPolicyMap(BaseModel):
    out_of_scope: MergeStrategy
    borderline: MergeStrategy


class ScopeDeclaration(BaseModel):
    modeled_capabilities: List[str]
    non_modeled_capabilities: List[str]
    restricted_use_cases: List[str]
    min_reliability_threshold: float = confidence_field()
    rejection_policy: RejectionPolicyMap
    user_facing_summary: str


class PriorBiasPattern(BaseModel):
    pattern_id: str
    description: str
    trigger_conditions: List[str]
    affected_domains: List[DomainEnum]
    severity: float = confidence_field()
    supporting_cases: List[str] = Field(default_factory=list)
    last_observed_at: datetime


class BiasCorrectionEntry(BaseModel):
    entry_id: str
    bias_pattern_id: str
    target_scope: Dict[str, Any] = Field(
        description="Rule scope: domain/task/situation features."
    )
    correction_action: BiasCorrectionAction
    correction_payload: Dict[str, Any]
    created_at: datetime
    last_validated_at: datetime
    validation_window: Optional[str] = Field(
        default=None, description="ISO-8601 duration, e.g. P30D."
    )
    expiry_condition: Optional[str] = None
    still_active: bool
    evidence_count: int = Field(ge=0)
    last_observed_effect: Optional[str] = None


class TemporalMetadata(BaseModel):
    state_valid_from: datetime
    state_valid_to: Optional[datetime] = None
    fast_variables: List[str]
    slow_variables: List[str]
    irreversible_shifts: List[str] = Field(default_factory=list)
    major_life_events: List[str] = Field(default_factory=list)
    last_version_rollover_at: Optional[datetime] = None


# --- Top-level TwinState ---


class TwinState(BaseModel):
    id: str = Field(min_length=1)
    created_at: datetime
    user_id: str
    state_version: str
    shared_decision_core: SharedDecisionCore
    causal_belief_model: CausalBeliefModel
    domain_heads: List[DomainHead] = Field(min_length=1)
    transfer_coefficients: List[TransferCoefficient] = Field(default_factory=list)
    reliability_profile: List[ReliabilityProfileEntry] = Field(min_length=1)
    scope_declaration: ScopeDeclaration
    prior_bias_profile: List[PriorBiasPattern] = Field(default_factory=list)
    bias_correction_policy: List[BiasCorrectionEntry] = Field(default_factory=list)
    temporal_metadata: TemporalMetadata
    active: bool
    notes: Optional[str] = None

    def valid_domains(self) -> List[DomainEnum]:
        """Derive valid domains from head_reliability >= min_reliability_threshold."""
        threshold = self.scope_declaration.min_reliability_threshold
        return [
            h.domain
            for h in self.domain_heads
            if h.head_reliability >= threshold
        ]

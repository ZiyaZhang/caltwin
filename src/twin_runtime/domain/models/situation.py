"""Situation Interpreter output models."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from twin_runtime.domain.models.primitives import (
    DependencyScope,
    DomainEnum,
    OptionStructure,
    OrdinalTriLevel,
    ScopeStatus,
    SituationConflictType,
    UncertaintyType,
    confidence_field,
    weight_field,
)


class SituationFeatureVector(BaseModel):
    reversibility: OrdinalTriLevel
    stakes: OrdinalTriLevel
    time_pressure: Optional[OrdinalTriLevel] = None
    identity_load: Optional[OrdinalTriLevel] = None
    social_exposure: Optional[OrdinalTriLevel] = None
    dependency_scope: Optional[DependencyScope] = None
    uncertainty_type: UncertaintyType
    controllability: OrdinalTriLevel
    option_structure: OptionStructure
    situation_conflict_type: Optional[SituationConflictType] = Field(
        default=None,
        description="Inherent tension in the situation, distinct from ConflictType (inter-head disagreement).",
    )


class SituationFrame(BaseModel):
    frame_id: str = Field(min_length=1)
    domain_activation_vector: Dict[DomainEnum, float] = Field(
        description="Map of domain -> activation weight (0-1).",
    )
    situation_feature_vector: SituationFeatureVector

    @model_validator(mode="after")
    def _validate_activation_weights(self):
        for domain, weight in self.domain_activation_vector.items():
            if not (0.0 <= weight <= 1.0):
                raise ValueError(
                    f"domain_activation_vector[{domain.value}]={weight} is out of range [0.0, 1.0]"
                )
        return self
    ambiguity_score: float = confidence_field()
    clarification_questions: List[str] = Field(default_factory=list)
    scope_status: ScopeStatus
    routing_confidence: float = confidence_field()

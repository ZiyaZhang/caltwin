"""Primitive types and enums matching twin-runtime-core-v0.1.1.schema.json $defs."""

from __future__ import annotations

from enum import Enum
from typing import Dict, Literal

from pydantic import Field


# --- Annotated scalar types ---

ConfidenceScore = float  # 0.0 – 1.0
WeightScore = float      # 0.0 – 1.0
BipolarScore = float     # 0.0 = first pole, 1.0 = second pole


def confidence_field(description: str = "", **kw):
    return Field(ge=0.0, le=1.0, description=description, **kw)


def weight_field(description: str = "", **kw):
    return Field(ge=0.0, le=1.0, description=description, **kw)


def bipolar_field(description: str = "", **kw):
    return Field(ge=0.0, le=1.0, description=description, **kw)


# --- Enums ---

class DomainEnum(str, Enum):
    WORK = "work"
    LIFE_PLANNING = "life_planning"
    MONEY = "money"
    RELATIONSHIPS = "relationships"
    PUBLIC_EXPRESSION = "public_expression"


class OrdinalTriLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ConflictStyle(str, Enum):
    AVOIDANT = "avoidant"
    DIRECT = "direct"
    DELAYED = "delayed"
    ADAPTIVE = "adaptive"
    COLLABORATIVE = "collaborative"
    COMPETITIVE = "competitive"
    ACCOMMODATING = "accommodating"


class ControlOrientation(str, Enum):
    INTERNAL = "internal"
    MIXED = "mixed"
    EXTERNAL = "external"


class RelationshipModel(str, Enum):
    INSTRUMENTAL = "instrumental"
    INTRINSIC = "intrinsic"
    MIXED = "mixed"


class ChangeStrategy(str, Enum):
    SHAPE_SYSTEM = "shape_system"
    ADAPT_TO_SYSTEM = "adapt_to_system"
    MIXED = "mixed"


class ConflictType(str, Enum):
    PREFERENCE = "preference"
    BELIEF = "belief"
    EVIDENCE_CREDIBILITY = "evidence_credibility"
    MIXED = "mixed"


class MergeStrategy(str, Enum):
    AUTO_MERGE = "auto_merge"
    CLARIFY = "clarify"
    DEGRADE = "degrade"
    REFUSE = "refuse"


class DecisionMode(str, Enum):
    DIRECT = "direct"
    CLARIFIED = "clarified"
    DEGRADED = "degraded"
    REFUSED = "refused"


class ScopeStatus(str, Enum):
    IN_SCOPE = "in_scope"
    BORDERLINE = "borderline"
    OUT_OF_SCOPE = "out_of_scope"


class ReliabilityScopeStatus(str, Enum):
    MODELED = "modeled"
    WEAKLY_MODELED = "weakly_modeled"
    UNMODELED = "unmodeled"
    RESTRICTED = "restricted"


class CandidateSourceType(str, Enum):
    RUNTIME_TRACE = "runtime_trace"
    USER_CORRECTION = "user_correction"
    USER_REFLECTION = "user_reflection"
    OBSERVED_OUTCOME = "observed_outcome"
    SIMULATION_REPLAY = "simulation_replay"
    HISTORICAL_REBUILD = "historical_rebuild"


class RuntimeEventType(str, Enum):
    DECISION_EMITTED = "decision_emitted"
    OUTCOME_OBSERVED = "outcome_observed"
    DISAGREEMENT_FLAGGED = "disagreement_flagged"
    USER_REJECTED = "user_rejected"
    USER_REPHRASED = "user_rephrased"
    USER_CORRECTED = "user_corrected"
    REAL_OUTCOME_OBSERVED = "real_outcome_observed"
    SIMULATION_DIVERGENCE_DETECTED = "simulation_divergence_detected"
    HIGH_UNCERTAINTY_CASE = "high_uncertainty_case"
    CLARIFICATION_INVOKED = "clarification_invoked"


class BiasCorrectionAction(str, Enum):
    REWEIGHT = "reweight"
    DIMENSION_SPLIT = "dimension_split"
    FORCE_COMPARE = "force_compare"
    BLOCK_AUTOMERGE = "block_automerge"
    FORCE_CLARIFICATION = "force_clarification"


class OutcomeSource(str, Enum):
    USER_CORRECTION = "user_correction"
    USER_REFLECTION = "user_reflection"
    OBSERVED = "observed"


class MicroCalibrationTrigger(str, Enum):
    CONFIDENCE_RECAL = "confidence_recal"
    OUTCOME_UPDATE = "outcome_update"


class DetectedBiasStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"


class DependencyScope(str, Enum):
    SELF = "self"
    FEW_OTHERS = "few_others"
    MANY_OTHERS = "many_others"


class UncertaintyType(str, Enum):
    MISSING_INFO = "missing_info"
    OUTCOME_UNCERTAINTY = "outcome_uncertainty"
    VALUE_CONFLICT = "value_conflict"
    MIXED = "mixed"


class OptionStructure(str, Enum):
    CHOOSE_EXISTING = "choose_existing"
    GENERATE_NEW = "generate_new"
    MIXED = "mixed"


class SituationConflictType(str, Enum):
    EFFICIENCY_VS_QUALITY = "efficiency_vs_quality"
    STABILITY_VS_GROWTH = "stability_vs_growth"
    INDEPENDENCE_VS_RELATIONSHIP = "independence_vs_relationship"
    REWARD_VS_RISK = "reward_vs_risk"
    MIXED = "mixed"
    OTHER = "other"


# --- Utility functions ---

_TASK_TYPE_ALIASES: Dict[str, str] = {}


def uncertainty_to_confidence(uncertainty: float) -> float:
    """Convert uncertainty (higher=less certain) to confidence (higher=more certain)."""
    return round(1.0 - uncertainty, 4)


def canonicalize_task_type(raw: str) -> str:
    """Normalize task_type: lowercase, strip, spaces to underscores, alias lookup."""
    normalized = raw.lower().strip().replace(" ", "_")
    return _TASK_TYPE_ALIASES.get(normalized, normalized)

"""Data models for the runtime orchestrator."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from twin_runtime.domain.models.primitives import DecisionMode


class ExecutionPath(str, Enum):
    NO_EXECUTION = "no_execution"
    S1_DIRECT = "s1_direct"
    S2_DELIBERATE = "s2_deliberate"


class BoundaryPolicy(str, Enum):
    NORMAL = "normal"
    FORCE_DEGRADE = "force_degrade"
    FORCE_REFUSE = "force_refuse"


class TerminationReason(str, Enum):
    CONFLICT_RESOLVED = "conflict_resolved"
    NO_NEW_EVIDENCE = "no_new_evidence"
    CONFIDENCE_PLATEAU = "confidence_plateau"
    MAX_ITERATIONS = "max_iterations"
    BUDGET_EXHAUSTED = "budget_exhausted"


class RouteDecision(BaseModel):
    execution_path: ExecutionPath
    boundary_policy: BoundaryPolicy
    reason_codes: List[str] = Field(default_factory=list)
    shadow_scores: Dict[str, float] = Field(default_factory=dict)


class DeliberationRoundSummary(BaseModel):
    round_index: int
    new_unique_evidence_count: int
    conflict_types: List[str] = Field(default_factory=list)
    top_choice: Optional[str] = None
    avg_head_confidence: float = 0.0
    top_choice_changed: bool = False


@dataclass
class StructuredDecision:
    top_choice: Optional[str]
    option_scores: Dict[str, float]
    avg_confidence: float
    mode: DecisionMode
    refusal_reason: Optional[str] = None

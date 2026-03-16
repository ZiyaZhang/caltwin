"""Memory Access Planner domain models."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from twin_runtime.domain.evidence.base import EvidenceFragment, EvidenceType
from twin_runtime.domain.models.primitives import DomainEnum
from twin_runtime.domain.models.recall_query import RecallQuery
from twin_runtime.domain.models.situation import SituationFrame
from twin_runtime.domain.models.twin_state import TwinState


class MemoryAccessPlan(BaseModel):
    """Output of the planner: what evidence to retrieve and how."""

    queries: List[RecallQuery] = Field(default_factory=list)
    execution_strategy: Literal["parallel", "sequential", "conditional"] = "parallel"
    total_evidence_budget: int = Field(default=10, ge=0)
    per_query_limit: int = Field(default=5, ge=0)
    freshness_preference: Literal["recent_first", "historical_first", "balanced"] = "balanced"
    disabled_evidence_types: List[EvidenceType] = Field(default_factory=list)
    rationale: str = ""
    # Domain gating — Planner decides which heads to activate
    domains_to_activate: List[DomainEnum] = Field(default_factory=list)
    skipped_domains: Dict[DomainEnum, str] = Field(default_factory=dict)


class EnrichedActivationContext(BaseModel):
    """What Head Activator receives after Planner enrichment."""

    twin: TwinState
    frame: SituationFrame
    retrieved_evidence: List[EvidenceFragment] = Field(default_factory=list)
    retrieval_rationale: str = ""

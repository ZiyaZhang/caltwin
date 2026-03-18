"""Shadow ontology models."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from twin_runtime.domain.models.primitives import DomainEnum


class OntologySuggestion(BaseModel):
    suggested_subdomain: str
    parent_domain: DomainEnum
    deterministic_label: str
    llm_label: Optional[str] = None
    support_count: int
    decayed_support: float
    stability_score: float
    representative_terms: List[str]
    representative_case_ids: List[str]
    drift_relation: Optional[str] = None


class OntologyReport(BaseModel):
    report_id: str
    twin_state_version: str
    as_of: datetime
    decay_params: Dict[str, Any]
    suggestions: List[OntologySuggestion] = Field(default_factory=list)
    domains_analyzed: List[str] = Field(default_factory=list)
    total_cases_analyzed: int = 0
    clustering_params: Dict[str, Any] = Field(default_factory=dict)

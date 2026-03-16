"""RecallQuery: typed evidence retrieval queries."""
from __future__ import annotations
from datetime import datetime
from typing import List, Literal, Optional, Tuple
from pydantic import BaseModel, Field
from twin_runtime.domain.models.primitives import DomainEnum
from twin_runtime.domain.evidence.base import EvidenceType


class RecallQuery(BaseModel):
    """Typed query for evidence retrieval."""
    query_type: Literal[
        "by_topic", "by_timeline", "by_domain", "by_evidence_type",
        "decisions_about", "preference_on_axis", "state_trajectory", "similar_situations",
    ]
    user_id: str
    time_range: Optional[Tuple[datetime, datetime]] = None
    domain_filter: Optional[List[DomainEnum]] = None
    evidence_type_filter: Optional[List[EvidenceType]] = None
    limit: int = Field(default=20, ge=1, le=100)
    sort_by: Literal["recency", "relevance", "confidence"] = "recency"
    # Query-type-specific parameters
    topic_keywords: Optional[List[str]] = None
    target_domain: Optional[str] = None
    target_evidence_type: Optional[str] = None
    decision_topic: Optional[str] = None
    preference_dimension: Optional[str] = None
    state_variable: Optional[str] = None
    situation_description: Optional[str] = None

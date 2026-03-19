"""RecallQuery: typed evidence retrieval queries."""
from __future__ import annotations
import warnings
from datetime import datetime
from typing import List, Literal, Optional, Tuple
from pydantic import BaseModel, Field, model_validator
from twin_runtime.domain.models.primitives import DomainEnum
from twin_runtime.domain.evidence.base import EvidenceType

# Mapping from query_type to the parameter name it expects.
_QUERY_TYPE_EXPECTED_PARAM: dict[str, str] = {
    "by_topic": "topic_keywords",
    "by_domain": "target_domain",
    "by_evidence_type": "target_evidence_type",
    "decisions_about": "decision_topic",
    "preference_on_axis": "preference_dimension",
    "state_trajectory": "state_variable",
    "similar_situations": "situation_description",
}


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
    target_domain: Optional[DomainEnum] = None
    target_evidence_type: Optional[EvidenceType] = None
    decision_topic: Optional[str] = None
    preference_dimension: Optional[str] = None
    state_variable: Optional[str] = None
    situation_description: Optional[str] = None

    @model_validator(mode="after")
    def _check_parameter_consistency(self) -> RecallQuery:
        """Warn when query-type-specific parameters are missing."""
        expected = _QUERY_TYPE_EXPECTED_PARAM.get(self.query_type)
        if expected is None:
            # by_timeline has no dedicated parameter — nothing to check.
            return self
        value = getattr(self, expected)
        # For list fields (topic_keywords), also treat an empty list as missing.
        missing = value is None or (isinstance(value, list) and len(value) == 0)
        if missing:
            warnings.warn(
                f"RecallQuery with query_type={self.query_type!r} is missing "
                f"expected parameter '{expected}'. Results may be incomplete.",
                UserWarning,
                stacklevel=2,
            )
        return self

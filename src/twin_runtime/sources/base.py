"""Base classes for data source adapters.

Architecture inspired by:
- OmniMemory STKG: temporal anchoring of evidence
- MemOS memory types: raw evidence → structured extraction → parameter update
- OpenClaw memory: cross-session persistence with provenance tracking
"""

from __future__ import annotations

import hashlib
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from ..models.primitives import DomainEnum, OrdinalTriLevel, confidence_field


class EvidenceType(str, Enum):
    """What kind of evidence this fragment represents."""
    DECISION = "decision"           # User made a choice between options
    PREFERENCE = "preference"       # User expressed a preference/opinion
    BEHAVIOR = "behavior"           # Observed behavior pattern
    REFLECTION = "reflection"       # User's self-report or reflection
    CONTEXT = "context"             # Background info (role, tools, environment)
    INTERACTION_STYLE = "interaction_style"  # How user communicates/collaborates


class EvidenceFragment(BaseModel):
    """Atomic unit of evidence extracted from any data source.

    This is the universal interface between source adapters and the persona compiler.
    """

    fragment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = Field(default="user-default", description="Owner user ID for multi-user isolation")
    source_type: str = Field(description="Adapter that produced this: 'openclaw', 'notion', 'gmail', etc.")
    source_id: str = Field(description="Unique ID within the source (file path, message ID, page ID, etc.)")
    evidence_type: EvidenceType

    # Temporal triple
    occurred_at: datetime = Field(description="When the event happened")
    valid_from: datetime = Field(description="When this evidence starts being relevant")
    valid_until: Optional[datetime] = Field(
        default=None,
        description="When this evidence stops being relevant (None = still valid)"
    )

    domain_hint: Optional[DomainEnum] = Field(
        default=None,
        description="Domain this evidence likely belongs to. None = let compiler decide."
    )

    # Content
    summary: str = Field(description="Short summary of what this evidence tells us about the user.")
    raw_excerpt: Optional[str] = Field(
        default=None,
        description="Verbatim excerpt from the source. May be truncated."
    )
    structured_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured extraction. Prefer typed subclass fields over this."
    )

    # Quality signals
    confidence: float = confidence_field(
        description="How confident we are this evidence is accurate and relevant."
    )
    stakes: Optional[OrdinalTriLevel] = None
    temporal_weight: float = Field(
        default=1.0, ge=0.0, le=2.0,
        description="Time-decay weight. Recent evidence > old evidence."
    )

    # Provenance
    extraction_method: str = Field(
        default="manual",
        description="How this was extracted: 'manual', 'llm_extraction', 'rule_based', 'api_structured'."
    )

    # Dedup
    content_hash: str = Field(
        default="",
        description="Semantic fingerprint for cross-source dedup. Auto-computed if empty."
    )

    @model_validator(mode="before")
    @classmethod
    def _migrate_timestamp(cls, data: Any) -> Any:
        if isinstance(data, dict) and "timestamp" in data and "occurred_at" not in data:
            data["occurred_at"] = data.pop("timestamp")
            if "valid_from" not in data:
                data["valid_from"] = data["occurred_at"]
        return data

    def model_post_init(self, __context: Any) -> None:
        if not self.content_hash:
            self.content_hash = self._compute_content_hash()

    def _compute_content_hash(self) -> str:
        """Compute semantic fingerprint. Subclasses override for type-specific hashing."""
        parts = [
            self.evidence_type.value,
            self.domain_hint.value if self.domain_hint else "",
            self.summary[:100],
        ]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


class SourceAdapter(ABC):
    """Abstract base for all data source adapters.

    Each adapter:
    1. Connects to a data source (file, API, database)
    2. Scans for evidence-bearing content
    3. Extracts EvidenceFragments with provenance

    Adapters should be stateless — all state lives in the evidence store.
    """

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Unique identifier for this source type (e.g. 'openclaw', 'notion')."""
        ...

    @abstractmethod
    def check_connection(self) -> bool:
        """Verify the source is accessible. Returns True if connected."""
        ...

    @abstractmethod
    def scan(self, since: Optional[datetime] = None) -> List[EvidenceFragment]:
        """Scan the source for evidence fragments.

        Args:
            since: Only return evidence newer than this timestamp.
                   None = scan everything available.

        Returns:
            List of EvidenceFragments extracted from the source.
        """
        ...

    def get_source_metadata(self) -> Dict[str, Any]:
        """Return metadata about this source connection."""
        return {"source_type": self.source_type}

"""Base classes for data source adapters.

Architecture inspired by:
- OmniMemory STKG: temporal anchoring of evidence
- MemOS memory types: raw evidence → structured extraction → parameter update
- OpenClaw memory: cross-session persistence with provenance tracking
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

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
    Every adapter produces these; the compiler consumes them.
    """
    fragment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_type: str = Field(description="Adapter that produced this: 'openclaw', 'notion', 'gmail', etc.")
    source_id: str = Field(description="Unique ID within the source (file path, message ID, page ID, etc.)")
    evidence_type: EvidenceType
    timestamp: datetime = Field(description="When this evidence was observed/created")
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
        description="Structured extraction: options, choice, reasoning, etc."
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

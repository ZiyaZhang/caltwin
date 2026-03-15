"""Data source adapters for evidence extraction.

Each adapter connects to a data source and produces EvidenceFragments
that feed into the persona compiler.
"""

from .base import SourceAdapter, EvidenceFragment, EvidenceType
from .registry import SourceRegistry
from .openclaw_adapter import OpenClawAdapter
from .document_adapter import DocumentAdapter
from .notion_adapter import NotionAdapter
from .gmail_adapter import GmailAdapter
from .calendar_adapter import CalendarAdapter
from .evidence_types import (
    DecisionEvidence, PreferenceEvidence, BehaviorEvidence,
    ReflectionEvidence, InteractionStyleEvidence, ContextEvidence,
    migrate_fragment,
)

__all__ = [
    "SourceAdapter", "EvidenceFragment", "EvidenceType", "SourceRegistry",
    "OpenClawAdapter", "DocumentAdapter", "NotionAdapter",
    "GmailAdapter", "CalendarAdapter",
    "DecisionEvidence", "PreferenceEvidence", "BehaviorEvidence",
    "ReflectionEvidence", "InteractionStyleEvidence", "ContextEvidence",
    "migrate_fragment",
]

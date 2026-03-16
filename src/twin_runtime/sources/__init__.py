"""Backward-compat shim."""
from twin_runtime.domain.evidence.base import SourceAdapter, EvidenceFragment, EvidenceType
from twin_runtime.infrastructure.sources.registry import SourceRegistry
from twin_runtime.infrastructure.sources.openclaw_adapter import OpenClawAdapter
from twin_runtime.infrastructure.sources.document_adapter import DocumentAdapter
from twin_runtime.infrastructure.sources.notion_adapter import NotionAdapter
from twin_runtime.infrastructure.sources.gmail_adapter import GmailAdapter
from twin_runtime.infrastructure.sources.calendar_adapter import CalendarAdapter
from twin_runtime.domain.evidence.types import (
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

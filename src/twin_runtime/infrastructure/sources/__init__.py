"""Infrastructure source adapters — data source IO."""
from twin_runtime.domain.evidence.base import SourceAdapter, EvidenceFragment, EvidenceType
from .registry import SourceRegistry
from .openclaw_adapter import OpenClawAdapter
from .document_adapter import DocumentAdapter
from .notion_adapter import NotionAdapter
from .gmail_adapter import GmailAdapter
from .calendar_adapter import CalendarAdapter

__all__ = [
    "SourceAdapter", "EvidenceFragment", "EvidenceType", "SourceRegistry",
    "OpenClawAdapter", "DocumentAdapter", "NotionAdapter",
    "GmailAdapter", "CalendarAdapter",
]

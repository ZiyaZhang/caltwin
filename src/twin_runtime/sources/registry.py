"""Source adapter registry: manage multiple data sources."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from .base import EvidenceFragment, SourceAdapter


class SourceRegistry:
    """Central registry for all connected data source adapters.

    Usage:
        registry = SourceRegistry()
        registry.register(OpenClawAdapter("/path/to/workspace"))
        registry.register(NotionAdapter(token="..."))

        # Scan all sources
        fragments = registry.scan_all()

        # Scan specific source
        fragments = registry.scan("openclaw")
    """

    def __init__(self):
        self._adapters: Dict[str, SourceAdapter] = {}

    def register(self, adapter: SourceAdapter) -> None:
        """Register a source adapter."""
        self._adapters[adapter.source_type] = adapter

    def unregister(self, source_type: str) -> None:
        """Remove a source adapter."""
        self._adapters.pop(source_type, None)

    def list_sources(self) -> List[str]:
        """List all registered source types."""
        return list(self._adapters.keys())

    def get(self, source_type: str) -> Optional[SourceAdapter]:
        """Get a specific adapter by type."""
        return self._adapters.get(source_type)

    def check_all(self) -> Dict[str, bool]:
        """Check connectivity for all registered sources."""
        return {
            name: adapter.check_connection()
            for name, adapter in self._adapters.items()
        }

    def scan(self, source_type: str, since: Optional[datetime] = None) -> List[EvidenceFragment]:
        """Scan a specific source for evidence."""
        adapter = self._adapters.get(source_type)
        if adapter is None:
            raise KeyError(f"No adapter registered for source type: {source_type}")
        return adapter.scan(since)

    def scan_all(self, since: Optional[datetime] = None) -> List[EvidenceFragment]:
        """Scan all registered sources for evidence."""
        fragments: List[EvidenceFragment] = []
        for adapter in self._adapters.values():
            try:
                fragments.extend(adapter.scan(since))
            except Exception as e:
                # Don't let one source failure block others
                print(f"Warning: {adapter.source_type} scan failed: {e}")
        return fragments

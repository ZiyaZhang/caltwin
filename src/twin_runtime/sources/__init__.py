"""Data source adapters for evidence extraction.

Each adapter connects to a data source and produces EvidenceFragments
that feed into the persona compiler.
"""

from .base import SourceAdapter, EvidenceFragment, EvidenceType
from .registry import SourceRegistry

__all__ = ["SourceAdapter", "EvidenceFragment", "EvidenceType", "SourceRegistry"]

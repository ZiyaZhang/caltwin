"""Domain evidence types — typed fragments, clustering, dedup."""
from .base import EvidenceFragment, EvidenceType, SourceAdapter
from .types import (
    DecisionEvidence, PreferenceEvidence, BehaviorEvidence,
    ReflectionEvidence, InteractionStyleEvidence, ContextEvidence,
    migrate_fragment,
)
from .clustering import EvidenceCluster, deduplicate

__all__ = [
    "EvidenceFragment", "EvidenceType", "SourceAdapter",
    "DecisionEvidence", "PreferenceEvidence", "BehaviorEvidence",
    "ReflectionEvidence", "InteractionStyleEvidence", "ContextEvidence",
    "migrate_fragment", "EvidenceCluster", "deduplicate",
]

"""Evidence deduplication and clustering.

Groups EvidenceFragments with the same content_hash into EvidenceClusters.
Multi-source corroboration boosts confidence.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any, Dict, List, Union

from pydantic import BaseModel, Field

from twin_runtime.domain.evidence.base import EvidenceFragment


class EvidenceCluster(BaseModel):
    """Multiple fragments describing the same underlying event."""

    cluster_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    canonical_fragment: EvidenceFragment
    supporting_fragments: List[EvidenceFragment] = Field(default_factory=list)
    source_types: List[str] = Field(default_factory=list)
    merged_confidence: float = 0.0


def deduplicate(
    fragments: List[EvidenceFragment],
    confidence_boost_per_source: float = 0.05,
) -> List[Union[EvidenceFragment, EvidenceCluster]]:
    """Group fragments by content_hash. Singletons pass through; duplicates become clusters."""
    by_hash: Dict[str, List[EvidenceFragment]] = defaultdict(list)
    for f in fragments:
        by_hash[f.content_hash].append(f)

    result: List[Union[EvidenceFragment, EvidenceCluster]] = []
    for content_hash, group in by_hash.items():
        if len(group) == 1:
            result.append(group[0])
        else:
            group.sort(key=lambda f: f.confidence, reverse=True)
            canonical = group[0]
            supporting = group[1:]
            source_types = list({f.source_type for f in group})
            boost = confidence_boost_per_source * (len(source_types) - 1)
            merged_confidence = min(1.0, canonical.confidence + boost)

            result.append(EvidenceCluster(
                canonical_fragment=canonical,
                supporting_fragments=supporting,
                source_types=source_types,
                merged_confidence=merged_confidence,
            ))

    return result

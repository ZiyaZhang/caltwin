"""JSON file implementation of EvidenceStore protocol."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

from twin_runtime.domain.evidence.base import EvidenceFragment
from twin_runtime.domain.evidence.clustering import EvidenceCluster
from twin_runtime.domain.models.recall_query import RecallQuery

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


def _validate_safe_id(value: str, label: str = "ID") -> str:
    if not value or not _SAFE_ID_RE.match(value):
        raise ValueError(f"Unsafe {label} for filesystem use: {value!r}")
    return value


class JsonFileEvidenceStore:
    """File-based storage for evidence fragments and clusters."""

    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)
        (self.base / "fragments").mkdir(exist_ok=True)
        (self.base / "clusters").mkdir(exist_ok=True)

    def store_fragment(self, fragment: EvidenceFragment) -> str:
        _validate_safe_id(fragment.content_hash, "content_hash")
        existing = self.get_by_hash(fragment.content_hash)
        if existing is None:
            path = self.base / "fragments" / f"{fragment.content_hash}.json"
            path.write_text(fragment.model_dump_json(indent=2))
        elif existing.source_type != fragment.source_type:
            from twin_runtime.domain.evidence.clustering import EvidenceCluster
            import uuid
            higher = existing if existing.confidence >= fragment.confidence else fragment
            lower = fragment if higher is existing else existing
            cluster = EvidenceCluster(
                cluster_id=str(uuid.uuid4()),
                canonical_fragment=higher,
                supporting_fragments=[lower],
                source_types=[existing.source_type, fragment.source_type],
                merged_confidence=min(1.0, higher.confidence + 0.05),
            )
            self.store_cluster(cluster)
        else:
            if fragment.confidence > existing.confidence:
                path = self.base / "fragments" / f"{fragment.content_hash}.json"
                path.write_text(fragment.model_dump_json(indent=2))
        return fragment.content_hash

    def store_cluster(self, cluster: EvidenceCluster) -> str:
        path = self.base / "clusters" / f"{cluster.cluster_id}.json"
        path.write_text(cluster.model_dump_json(indent=2))
        return cluster.cluster_id

    def query(self, recall_query: RecallQuery) -> List[EvidenceFragment]:
        """Filter and rank evidence fragments by domain, type, and keyword relevance."""
        fragments = []
        for p in (self.base / "fragments").glob("*.json"):
            try:
                frag = EvidenceFragment.model_validate_json(p.read_text())
                fragments.append(frag)
            except Exception:
                continue

        # Filter by domain (EvidenceFragment uses domain_hint)
        if recall_query.target_domain:
            fragments = [f for f in fragments if f.domain_hint == recall_query.target_domain]
        elif recall_query.domain_filter:
            fragments = [f for f in fragments if f.domain_hint in recall_query.domain_filter]

        # Filter by evidence type
        if recall_query.target_evidence_type:
            fragments = [f for f in fragments if f.evidence_type == recall_query.target_evidence_type]
        elif recall_query.evidence_type_filter:
            fragments = [f for f in fragments if f.evidence_type in recall_query.evidence_type_filter]

        # Rank by topic_keywords relevance
        if recall_query.topic_keywords:
            def relevance_score(frag):
                text = (frag.summary or "") + " " + (frag.raw_excerpt or "")
                text_lower = text.lower()
                return sum(1 for kw in recall_query.topic_keywords if kw.lower() in text_lower)

            # Compute scores once to avoid O(2nk)
            scored = [(relevance_score(f), f) for f in fragments]
            scored = [(s, f) for s, f in scored if s > 0]
            scored.sort(key=lambda x: x[0], reverse=True)
            fragments = [f for _, f in scored]
        else:
            # Default: sort by recency (EvidenceFragment uses occurred_at)
            fragments.sort(key=lambda f: f.occurred_at, reverse=True)

        return fragments[:recall_query.limit]

    def get_by_hash(self, content_hash: str) -> Optional[EvidenceFragment]:
        path = self.base / "fragments" / f"{content_hash}.json"
        if path.exists():
            return EvidenceFragment.model_validate_json(path.read_text())
        return None

    def count(self, user_id: str, filters: Optional[Dict] = None) -> int:
        count = 0
        for p in (self.base / "fragments").glob("*.json"):
            frag = EvidenceFragment.model_validate_json(p.read_text())
            if frag.user_id == user_id:
                count += 1
        return count

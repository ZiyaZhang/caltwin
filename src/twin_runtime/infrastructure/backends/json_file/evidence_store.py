"""JSON file implementation of EvidenceStore protocol."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from twin_runtime.domain.evidence.base import EvidenceFragment
from twin_runtime.domain.evidence.clustering import EvidenceCluster
from twin_runtime.domain.models.recall_query import RecallQuery


class JsonFileEvidenceStore:
    """File-based storage for evidence fragments and clusters."""

    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)
        (self.base / "fragments").mkdir(exist_ok=True)
        (self.base / "clusters").mkdir(exist_ok=True)

    def store_fragment(self, fragment: EvidenceFragment) -> str:
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

    def query(self, query: RecallQuery) -> List[EvidenceFragment]:
        results = []
        for p in (self.base / "fragments").glob("*.json"):
            frag = EvidenceFragment.model_validate_json(p.read_text())
            if hasattr(query, "user_id") and frag.user_id == query.user_id:
                results.append(frag)
        return results

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

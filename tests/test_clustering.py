"""Tests for evidence deduplication and clustering."""

from datetime import datetime, timezone

import pytest

from twin_runtime.sources.evidence_types import DecisionEvidence, BehaviorEvidence
from twin_runtime.sources.clustering import deduplicate, EvidenceCluster


NOW = datetime.now(timezone.utc)


def _make_decision(source_type: str, source_id: str, confidence: float = 0.6):
    return DecisionEvidence(
        source_type=source_type,
        source_id=source_id,
        occurred_at=NOW,
        valid_from=NOW,
        summary="Chose option A",
        confidence=confidence,
        user_id="user-test",
        option_set=["A", "B"],
        chosen="A",
    )


class TestDeduplicate:
    def test_no_duplicates(self):
        d1 = _make_decision("gmail", "g-1")
        b1 = BehaviorEvidence(
            source_type="calendar", source_id="c-1",
            occurred_at=NOW, valid_from=NOW,
            summary="Meeting pattern", confidence=0.7,
            user_id="user-test",
            action_type="meeting", pattern="weekly standup",
        )
        result = deduplicate([d1, b1])
        assert len(result) == 2
        assert all(not isinstance(r, EvidenceCluster) for r in result)

    def test_duplicates_clustered(self):
        d1 = _make_decision("gmail", "g-1", confidence=0.6)
        d2 = _make_decision("notion", "n-1", confidence=0.8)
        result = deduplicate([d1, d2])
        assert len(result) == 1
        cluster = result[0]
        assert isinstance(cluster, EvidenceCluster)
        assert cluster.merged_confidence > max(d1.confidence, d2.confidence)
        assert len(cluster.source_types) == 2
        assert "gmail" in cluster.source_types
        assert "notion" in cluster.source_types

    def test_cluster_canonical_is_highest_confidence(self):
        d1 = _make_decision("gmail", "g-1", confidence=0.5)
        d2 = _make_decision("notion", "n-1", confidence=0.9)
        result = deduplicate([d1, d2])
        cluster = result[0]
        assert cluster.canonical_fragment.source_type == "notion"

    def test_three_way_merge(self):
        d1 = _make_decision("gmail", "g-1", confidence=0.5)
        d2 = _make_decision("notion", "n-1", confidence=0.7)
        d3 = _make_decision("calendar", "c-1", confidence=0.6)
        result = deduplicate([d1, d2, d3])
        assert len(result) == 1
        cluster = result[0]
        assert len(cluster.supporting_fragments) == 2
        assert len(cluster.source_types) == 3

    def test_mixed_duplicates_and_uniques(self):
        d1 = _make_decision("gmail", "g-1")
        d2 = _make_decision("notion", "n-1")
        b1 = BehaviorEvidence(
            source_type="calendar", source_id="c-1",
            occurred_at=NOW, valid_from=NOW,
            summary="Pattern", confidence=0.7,
            user_id="user-test",
            action_type="meeting", pattern="weekly",
        )
        result = deduplicate([d1, d2, b1])
        assert len(result) == 2  # 1 cluster + 1 standalone

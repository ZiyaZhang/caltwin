# tests/test_evidence_integration.py
"""Integration test: typed evidence → dedup → compiler consumption."""

from datetime import datetime, timezone

from twin_runtime.domain.evidence.types import (
    DecisionEvidence, PreferenceEvidence, BehaviorEvidence,
    ContextEvidence, ReflectionEvidence, migrate_fragment,
)
from twin_runtime.domain.evidence.clustering import deduplicate, EvidenceCluster
from twin_runtime.domain.evidence.base import EvidenceFragment, EvidenceType


NOW = datetime.now(timezone.utc)


class TestEvidenceFlowIntegration:
    def test_typed_fragments_dedup_and_cluster(self):
        """Typed fragments from different sources cluster correctly."""
        # Same decision from Gmail and Notion
        gmail_decision = DecisionEvidence(
            source_type="gmail", source_id="g-1",
            occurred_at=NOW, valid_from=NOW,
            summary="Chose Python", confidence=0.6, user_id="user-test",
            option_set=["Python", "TypeScript"], chosen="Python",
        )
        notion_decision = DecisionEvidence(
            source_type="notion", source_id="n-1",
            occurred_at=NOW, valid_from=NOW,
            summary="Project language: Python", confidence=0.8, user_id="user-test",
            option_set=["Python", "TypeScript"], chosen="Python",
        )
        # Unrelated behavior
        calendar_behavior = BehaviorEvidence(
            source_type="calendar", source_id="c-1",
            occurred_at=NOW, valid_from=NOW,
            summary="Morning meetings", confidence=0.7, user_id="user-test",
            action_type="schedule", pattern="Prefers 9-11am",
        )

        result = deduplicate([gmail_decision, notion_decision, calendar_behavior])
        assert len(result) == 2  # 1 cluster + 1 standalone

        clusters = [r for r in result if isinstance(r, EvidenceCluster)]
        assert len(clusters) == 1
        assert clusters[0].canonical_fragment.source_type == "notion"  # Higher confidence

    def test_legacy_migration_then_dedup(self):
        """Legacy flat fragments migrate to typed, then dedup works."""
        legacy1 = EvidenceFragment(
            source_type="gmail", source_id="g-1",
            evidence_type=EvidenceType.BEHAVIOR,
            timestamp=NOW, summary="Calendar patterns",
            structured_data={"total_events": 50, "action_type": "calendar"},
            confidence=0.7,
        )
        legacy2 = EvidenceFragment(
            source_type="notion", source_id="n-1",
            evidence_type=EvidenceType.BEHAVIOR,
            timestamp=NOW, summary="Calendar patterns",
            structured_data={"total_events": 50, "action_type": "calendar"},
            confidence=0.6,
        )
        typed1 = migrate_fragment(legacy1)
        typed2 = migrate_fragment(legacy2)
        assert typed1.content_hash == typed2.content_hash

        result = deduplicate([typed1, typed2])
        assert len(result) == 1
        assert isinstance(result[0], EvidenceCluster)

    def test_cold_start_produces_valid_twin(self):
        """Cold start twin can be created and has correct defaults."""
        from twin_runtime.application.compiler.persona_compiler import PersonaCompiler
        from twin_runtime.infrastructure.sources.registry import SourceRegistry

        compiler = PersonaCompiler(SourceRegistry())
        twin = compiler._create_initial(user_id="new-user", fragments=[])

        assert twin.user_id == "new-user"
        assert twin.state_version == "v000-cold-start"
        assert len(twin.valid_domains()) == 0  # All below threshold (0.3 < 0.5)
        assert twin.shared_decision_core.core_confidence <= 0.3

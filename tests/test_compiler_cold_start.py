"""Tests for PersonaCompiler cold-start path."""

from datetime import datetime, timezone

import pytest

from twin_runtime.compiler.compiler import PersonaCompiler
from twin_runtime.sources.registry import SourceRegistry
from twin_runtime.sources.evidence_types import PreferenceEvidence, ContextEvidence
from twin_runtime.models.twin_state import TwinState


class TestColdStart:
    def test_create_initial_zero_evidence(self):
        """With zero evidence, produce a minimal TwinState that refuses most decisions."""
        registry = SourceRegistry()
        compiler = PersonaCompiler(registry)
        twin = compiler._create_initial(user_id="user-new", fragments=[])

        assert isinstance(twin, TwinState)
        assert twin.user_id == "user-new"
        assert twin.state_version.startswith("v000")
        # All 5 domain heads should exist and be below default threshold
        assert len(twin.domain_heads) == 5
        for head in twin.domain_heads:
            assert head.head_reliability <= 0.3
            assert head.head_version == "v000"

        # Core params at median
        assert twin.shared_decision_core.risk_tolerance == 0.5
        assert twin.shared_decision_core.core_confidence <= 0.3
        # No valid domains (all below 0.5 threshold)
        assert len(twin.valid_domains()) == 0

    def test_create_initial_with_some_evidence(self):
        """With some evidence, produce a TwinState with partial modeling."""
        registry = SourceRegistry()
        compiler = PersonaCompiler(registry)
        now = datetime.now(timezone.utc)

        fragments = [
            PreferenceEvidence(
                source_type="test", source_id="t-1",
                occurred_at=now, valid_from=now,
                summary="Prefers low risk",
                confidence=0.8, user_id="user-new",
                dimension="risk_tolerance", direction="prefers_low", strength=0.8,
            ),
            ContextEvidence(
                source_type="test", source_id="t-2",
                occurred_at=now, valid_from=now,
                summary="Product manager at Tencent",
                confidence=0.9, user_id="user-new",
                context_category="role", description="PM trainee at Tencent",
            ),
        ]
        twin = compiler._create_initial(user_id="user-new", fragments=fragments)
        assert isinstance(twin, TwinState)
        assert twin.user_id == "user-new"

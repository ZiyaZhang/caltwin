"""Tests for typed EvidenceFragment subclasses."""

from datetime import datetime, timezone

import pytest

from twin_runtime.domain.evidence.base import EvidenceType
from twin_runtime.domain.evidence.types import (
    BehaviorEvidence,
    ContextEvidence,
    DecisionEvidence,
    InteractionStyleEvidence,
    PreferenceEvidence,
    ReflectionEvidence,
)
from twin_runtime.domain.models.primitives import DomainEnum, OrdinalTriLevel


NOW = datetime.now(timezone.utc)
BASE = dict(
    source_type="test",
    source_id="t-1",
    occurred_at=NOW,
    valid_from=NOW,
    summary="Test",
    confidence=0.8,
    user_id="user-test",
)


class TestDecisionEvidence:
    def test_create(self):
        d = DecisionEvidence(
            **BASE,
            option_set=["A", "B", "C"],
            chosen="A",
            reasoning="A has lower risk",
            stakes=OrdinalTriLevel.HIGH,
        )
        assert d.evidence_type == EvidenceType.DECISION
        assert d.chosen == "A"
        assert d.option_set == ["A", "B", "C"]
        assert d.outcome_known is False

    def test_content_hash_stable(self):
        """Same decision from different sources should produce same hash."""
        d1 = DecisionEvidence(
            **{**BASE, "source_type": "gmail"},
            option_set=["A", "B"],
            chosen="A",
        )
        d2 = DecisionEvidence(
            **{**BASE, "source_type": "notion", "source_id": "t-2"},
            option_set=["A", "B"],
            chosen="A",
        )
        assert d1.content_hash == d2.content_hash

    def test_content_hash_differs_for_different_choice(self):
        d1 = DecisionEvidence(**BASE, option_set=["A", "B"], chosen="A")
        d2 = DecisionEvidence(**BASE, option_set=["A", "B"], chosen="B")
        assert d1.content_hash != d2.content_hash


class TestPreferenceEvidence:
    def test_create(self):
        p = PreferenceEvidence(
            **BASE,
            dimension="risk_tolerance",
            direction="prefers_low",
            strength=0.8,
        )
        assert p.evidence_type == EvidenceType.PREFERENCE
        assert p.dimension == "risk_tolerance"
        assert p.strength == 0.8

    def test_content_hash_stable(self):
        p1 = PreferenceEvidence(
            **{**BASE, "source_type": "gmail"},
            dimension="risk", direction="low", strength=0.8,
        )
        p2 = PreferenceEvidence(
            **{**BASE, "source_type": "notion"},
            dimension="risk", direction="low", strength=0.5,
        )
        # Same dimension+direction = same hash (strength excluded)
        assert p1.content_hash == p2.content_hash


class TestBehaviorEvidence:
    def test_create(self):
        b = BehaviorEvidence(
            **BASE,
            action_type="meeting_pattern",
            pattern="Prefers morning meetings",
        )
        assert b.evidence_type == EvidenceType.BEHAVIOR
        assert b.action_type == "meeting_pattern"

    def test_structured_metrics(self):
        b = BehaviorEvidence(
            **BASE,
            action_type="calendar",
            pattern="Weekly patterns",
            structured_metrics={"avg_duration": 45, "count": 12},
        )
        assert b.structured_metrics["avg_duration"] == 45


class TestReflectionEvidence:
    def test_create(self):
        r = ReflectionEvidence(
            **BASE,
            topic="career choice",
            sentiment="negative",
            insight="I regret choosing Tencent over MiniMax",
        )
        assert r.evidence_type == EvidenceType.REFLECTION
        assert r.sentiment == "negative"

    def test_references_decision(self):
        r = ReflectionEvidence(
            **BASE,
            topic="career",
            insight="Should have stayed",
            references_decision="decision-123",
        )
        assert r.references_decision == "decision-123"


class TestInteractionStyleEvidence:
    def test_create(self):
        s = InteractionStyleEvidence(
            **BASE,
            style_markers=["direct", "concise"],
            style_context="in emails",
        )
        assert s.evidence_type == EvidenceType.INTERACTION_STYLE
        assert "direct" in s.style_markers


class TestContextEvidence:
    def test_create(self):
        c = ContextEvidence(
            **BASE,
            context_category="role",
            description="Product manager trainee at Tencent",
        )
        assert c.evidence_type == EvidenceType.CONTEXT
        assert c.context_category == "role"

    def test_flexible_structured_data(self):
        c = ContextEvidence(
            **BASE,
            context_category="tools",
            description="Uses NotebookLM and Claude Code",
            structured_data={"tools": ["notebooklm", "claude_code"]},
        )
        assert "notebooklm" in c.structured_data["tools"]


class TestMigrateLegacyFragment:
    def test_migrate_flat_decision(self):
        from twin_runtime.domain.evidence.types import migrate_fragment
        from twin_runtime.domain.evidence.base import EvidenceFragment

        legacy = EvidenceFragment(
            source_type="gmail",
            source_id="msg-1",
            evidence_type=EvidenceType.DECISION,
            timestamp=NOW,
            summary="Chose option A",
            structured_data={
                "message_id": "msg-1",
                "subject": "Re: project decision",
                "needs_llm_analysis": True,
            },
            confidence=0.6,
        )
        typed = migrate_fragment(legacy)
        assert isinstance(typed, DecisionEvidence)
        assert typed.occurred_at == NOW
        assert typed.user_id == "user-default"

    def test_migrate_flat_behavior(self):
        from twin_runtime.domain.evidence.types import migrate_fragment
        from twin_runtime.domain.evidence.base import EvidenceFragment

        legacy = EvidenceFragment(
            source_type="calendar",
            source_id="cal-1",
            evidence_type=EvidenceType.BEHAVIOR,
            timestamp=NOW,
            summary="Calendar patterns",
            structured_data={"total_events": 50, "avg_duration_minutes": 45},
            confidence=0.7,
        )
        typed = migrate_fragment(legacy)
        assert isinstance(typed, BehaviorEvidence)
        assert typed.structured_metrics.get("total_events") == 50

    def test_migrate_unknown_falls_back_to_context(self):
        from twin_runtime.domain.evidence.types import migrate_fragment
        from twin_runtime.domain.evidence.base import EvidenceFragment

        legacy = EvidenceFragment(
            source_type="unknown",
            source_id="x-1",
            evidence_type=EvidenceType.CONTEXT,
            timestamp=NOW,
            summary="Something",
            confidence=0.5,
        )
        typed = migrate_fragment(legacy)
        assert isinstance(typed, ContextEvidence)

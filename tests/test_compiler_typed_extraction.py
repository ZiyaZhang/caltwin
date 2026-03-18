"""Tests for PersonaCompiler typed evidence field extraction.

TDD: These tests were written BEFORE the implementation of typed evidence
formatting in extract_parameters(). They verify that:
1. DecisionEvidence uses 'chosen', 'option_set', and 'reasoning' fields in the prompt
2. PreferenceEvidence uses 'dimension', 'direction', and 'strength' fields
3. ReflectionEvidence uses 'topic' and 'insight' fields
4. Base EvidenceFragment (legacy) falls back to summary + raw_excerpt
5. Typed fragments without their key fields fall back to legacy format
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from twin_runtime.application.compiler.persona_compiler import PersonaCompiler
from twin_runtime.domain.evidence.base import EvidenceFragment, EvidenceType
from twin_runtime.domain.evidence.types import (
    DecisionEvidence,
    PreferenceEvidence,
    ReflectionEvidence,
    BehaviorEvidence,
    ContextEvidence,
)
from twin_runtime.domain.models.primitives import DomainEnum
from twin_runtime.infrastructure.sources.registry import SourceRegistry


NOW = datetime.now(timezone.utc)
BASE = dict(
    source_type="test",
    source_id="t-1",
    occurred_at=NOW,
    valid_from=NOW,
    confidence=0.8,
    user_id="user-test",
)


def make_compiler():
    return PersonaCompiler(SourceRegistry())


def capture_prompt(fragments):
    """Run extract_parameters and capture the user message sent to ask_json."""
    compiler = make_compiler()
    captured = {}

    def fake_ask_json(system, user_msg, **kwargs):
        captured["user_msg"] = user_msg
        return {}

    with patch("twin_runtime.application.compiler.persona_compiler.ask_json", fake_ask_json):
        compiler.extract_parameters(fragments)

    return captured.get("user_msg", "")


class TestDecisionEvidenceFormatting:
    def test_decision_with_chosen_uses_typed_format(self):
        """DecisionEvidence with chosen field uses DECISION typed format."""
        fragment = DecisionEvidence(
            **BASE,
            summary="Chose to go with remote work",
            domain_hint=DomainEnum.WORK,
            option_set=["remote", "onsite", "hybrid"],
            chosen="remote",
            reasoning="Better work-life balance",
        )
        prompt = capture_prompt([fragment])

        assert "[DECISION|work|" in prompt
        assert "Chose 'remote'" in prompt
        assert "['remote', 'onsite', 'hybrid']" in prompt or "remote" in prompt
        assert "Reasoning: Better work-life balance" in prompt

    def test_decision_without_chosen_falls_back(self):
        """DecisionEvidence with empty chosen field uses fallback format."""
        fragment = DecisionEvidence(
            **BASE,
            summary="Made a career decision",
            domain_hint=DomainEnum.WORK,
            chosen="",  # empty — should fall back
            option_set=[],
        )
        prompt = capture_prompt([fragment])

        # Should use legacy fallback format since chosen is empty
        # (evidence_type.value is lowercase "decision")
        assert "[decision|work|" in prompt
        assert "Made a career decision" in prompt
        # Should NOT use typed format (no "Chose ''" pattern expected)
        assert "Chose ''" not in prompt

    def test_decision_reasoning_omitted_when_none(self):
        """DecisionEvidence with no reasoning doesn't include Reasoning line."""
        fragment = DecisionEvidence(
            **BASE,
            summary="Chose to apply",
            domain_hint=DomainEnum.WORK,
            chosen="apply",
            option_set=["apply", "skip"],
            reasoning=None,
        )
        prompt = capture_prompt([fragment])

        assert "[DECISION|work|" in prompt
        assert "Chose 'apply'" in prompt
        assert "Reasoning:" not in prompt


class TestPreferenceEvidenceFormatting:
    def test_preference_with_dimension_uses_typed_format(self):
        """PreferenceEvidence with dimension uses PREFERENCE typed format."""
        fragment = PreferenceEvidence(
            **BASE,
            summary="Prefers low-risk investments",
            domain_hint=DomainEnum.MONEY,
            dimension="risk_tolerance",
            direction="prefers_low",
            strength=0.85,
        )
        prompt = capture_prompt([fragment])

        assert "[PREFERENCE|money|" in prompt
        assert "risk_tolerance" in prompt
        assert "prefers_low" in prompt
        assert "strength=0.8" in prompt

    def test_preference_without_dimension_falls_back(self):
        """PreferenceEvidence with empty dimension uses fallback format."""
        fragment = PreferenceEvidence(
            **BASE,
            summary="Some preference noted",
            domain_hint=DomainEnum.WORK,
            dimension="",  # empty — should fall back
            direction="",
            strength=0.5,
        )
        prompt = capture_prompt([fragment])

        assert "Some preference noted" in prompt
        # Should NOT have dimension: direction format
        assert ": " not in prompt or "PREFERENCE" not in prompt.split(": ")[0]


class TestReflectionEvidenceFormatting:
    def test_reflection_with_insight_uses_typed_format(self):
        """ReflectionEvidence with insight uses REFLECTION typed format."""
        fragment = ReflectionEvidence(
            **BASE,
            summary="Reflection on career switch",
            domain_hint=DomainEnum.LIFE_PLANNING,
            topic="career switch",
            insight="I should have left Company A sooner to pursue AI work",
        )
        prompt = capture_prompt([fragment])

        assert "[REFLECTION|life_planning|" in prompt
        assert "Topic: career switch" in prompt
        assert "I should have left Company A sooner" in prompt

    def test_reflection_insight_truncated_at_200_chars(self):
        """ReflectionEvidence insight is truncated to 200 characters."""
        long_insight = "A" * 300
        fragment = ReflectionEvidence(
            **BASE,
            summary="Long reflection",
            domain_hint=DomainEnum.LIFE_PLANNING,
            topic="something",
            insight=long_insight,
        )
        prompt = capture_prompt([fragment])

        assert "A" * 200 in prompt
        assert "A" * 201 not in prompt

    def test_reflection_without_insight_falls_back(self):
        """ReflectionEvidence with empty insight uses fallback format."""
        fragment = ReflectionEvidence(
            **BASE,
            summary="Empty reflection",
            domain_hint=DomainEnum.WORK,
            topic="nothing",
            insight="",  # empty — should fall back
        )
        prompt = capture_prompt([fragment])

        assert "Empty reflection" in prompt


class TestLegacyFragmentFallback:
    def test_base_fragment_uses_legacy_format(self):
        """Plain EvidenceFragment (no subclass) uses legacy format."""
        fragment = EvidenceFragment(
            source_type="test",
            source_id="t-1",
            evidence_type=EvidenceType.BEHAVIOR,
            timestamp=NOW,
            summary="User attends morning stand-ups",
            confidence=0.7,
        )
        prompt = capture_prompt([fragment])

        assert "[behavior|unknown|conf=0.7]" in prompt
        assert "User attends morning stand-ups" in prompt

    def test_base_fragment_with_excerpt(self):
        """Plain EvidenceFragment with raw_excerpt includes excerpt in prompt."""
        fragment = EvidenceFragment(
            source_type="test",
            source_id="t-2",
            evidence_type=EvidenceType.CONTEXT,
            timestamp=NOW,
            summary="Context about role",
            raw_excerpt="I am a PM at Company A working on AI products",
            confidence=0.9,
        )
        prompt = capture_prompt([fragment])

        assert "Excerpt: I am a PM at Company A" in prompt

    def test_behavior_evidence_uses_fallback_format(self):
        """BehaviorEvidence (no typed format path) uses fallback format."""
        fragment = BehaviorEvidence(
            **BASE,
            summary="Attends daily standups",
            domain_hint=DomainEnum.WORK,
            action_type="meeting",
            pattern="daily standup attendance",
        )
        prompt = capture_prompt([fragment])

        # BehaviorEvidence has no special branch — should fall back to legacy
        assert "[behavior|work|" in prompt
        assert "Attends daily standups" in prompt


class TestConfidenceFormatting:
    def test_confidence_formatted_to_one_decimal(self):
        """Confidence value is formatted to 1 decimal place."""
        fragment = DecisionEvidence(
            **{**BASE, "confidence": 0.666},
            summary="Some decision",
            chosen="A",
            option_set=["A", "B"],
        )
        prompt = capture_prompt([fragment])
        assert "conf=0.7" in prompt

    def test_domain_unknown_when_no_hint(self):
        """Fragments without domain_hint show 'unknown' in prompt."""
        fragment = DecisionEvidence(
            **BASE,
            summary="Decision with no domain",
            chosen="yes",
            option_set=["yes", "no"],
            domain_hint=None,
        )
        prompt = capture_prompt([fragment])
        assert "|unknown|" in prompt


class TestPromptCap:
    def test_only_first_30_fragments_included(self):
        """extract_parameters only processes first 30 fragments."""
        fragments = [
            DecisionEvidence(
                **{**BASE, "source_id": f"t-{i}"},
                summary=f"Decision {i}",
                chosen=f"choice_{i}",
                option_set=[f"choice_{i}", "other"],
            )
            for i in range(40)
        ]
        prompt = capture_prompt(fragments)

        # Fragment 29 should appear, fragment 30+ should not
        assert "Decision 29" in prompt
        assert "Decision 30" not in prompt

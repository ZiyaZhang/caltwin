# tests/test_planner.py
"""Tests for the Memory Access Planner rule-based decision table."""

import logging
from unittest.mock import MagicMock

import pytest

from twin_runtime.domain.models.planner import MemoryAccessPlan
from twin_runtime.domain.models.primitives import DomainEnum, OrdinalTriLevel, ScopeStatus, UncertaintyType, OptionStructure
from twin_runtime.domain.models.situation import SituationFeatureVector, SituationFrame
from twin_runtime.domain.evidence.base import EvidenceFragment, EvidenceType
from twin_runtime.application.planner.memory_access_planner import plan_memory_access


def _make_frame(
    *,
    stakes=OrdinalTriLevel.MEDIUM,
    ambiguity=0.5,
    routing_confidence=0.8,
    domains=None,
    scope_status=ScopeStatus.IN_SCOPE,
) -> SituationFrame:
    """Create a SituationFrame with controllable signals."""
    if domains is None:
        domains = {DomainEnum.WORK: 0.9}
    return SituationFrame(
        frame_id="test-frame",
        domain_activation_vector=domains,
        situation_feature_vector=SituationFeatureVector(
            reversibility=OrdinalTriLevel.MEDIUM,
            stakes=stakes,
            uncertainty_type=UncertaintyType.MISSING_INFO,
            controllability=OrdinalTriLevel.MEDIUM,
            option_structure=OptionStructure.CHOOSE_EXISTING,
        ),
        ambiguity_score=ambiguity,
        scope_status=scope_status,
        routing_confidence=routing_confidence,
    )


def _make_twin(domains=None) -> MagicMock:
    """Create a minimal mock TwinState."""
    twin = MagicMock()
    if domains is None:
        domains = [DomainEnum.WORK]
    twin.domain_heads = [MagicMock(domain=d) for d in domains]
    twin.user_id = "user-test"
    return twin


class TestPlannerNoStore:
    def test_no_store_returns_empty_plan(self):
        frame = _make_frame()
        twin = _make_twin()
        plan, evidence = plan_memory_access(frame, twin, evidence_store=None)
        assert plan.queries == []
        assert evidence == []
        assert "no evidence store" in plan.rationale.lower()


class TestPlannerRules:
    def test_high_stakes_low_ambiguity(self):
        """High stakes + ambiguity < 0.3 -> decisions_about query."""
        frame = _make_frame(stakes=OrdinalTriLevel.HIGH, ambiguity=0.2)
        twin = _make_twin()
        plan, _ = plan_memory_access(frame, twin, evidence_store=None)
        query_types = [q.query_type for q in plan.queries]
        assert "decisions_about" in query_types

    def test_high_ambiguity(self):
        """Ambiguity > 0.6 -> preference_on_axis query."""
        frame = _make_frame(ambiguity=0.75)
        twin = _make_twin()
        plan, _ = plan_memory_access(frame, twin, evidence_store=None)
        query_types = [q.query_type for q in plan.queries]
        assert "preference_on_axis" in query_types

    def test_multi_domain(self):
        """Multiple domains -> by_domain + state_trajectory queries."""
        frame = _make_frame(domains={DomainEnum.WORK: 0.8, DomainEnum.MONEY: 0.6})
        twin = _make_twin(domains=[DomainEnum.WORK, DomainEnum.MONEY])
        plan, _ = plan_memory_access(frame, twin, evidence_store=None)
        query_types = [q.query_type for q in plan.queries]
        assert "by_domain" in query_types
        assert "state_trajectory" in query_types

    def test_low_routing_confidence(self):
        """Routing confidence < 0.5 -> expanded budget + by_timeline."""
        frame = _make_frame(routing_confidence=0.3)
        twin = _make_twin()
        plan, _ = plan_memory_access(frame, twin, evidence_store=None)
        query_types = [q.query_type for q in plan.queries]
        assert "by_timeline" in query_types
        assert plan.total_evidence_budget > 10  # expanded

    def test_no_signals_empty_plan(self):
        """Default signals -> empty queries list."""
        frame = _make_frame(
            stakes=OrdinalTriLevel.LOW,
            ambiguity=0.4,
            routing_confidence=0.8,
        )
        twin = _make_twin()
        plan, _ = plan_memory_access(frame, twin, evidence_store=None)
        assert plan.queries == []


class TestDomainGating:
    def test_gating_activates_matching_domains(self):
        """Domains with heads and weight > 0.1 are activated."""
        frame = _make_frame(domains={DomainEnum.WORK: 0.9, DomainEnum.MONEY: 0.6})
        twin = _make_twin(domains=[DomainEnum.WORK, DomainEnum.MONEY])
        plan, _ = plan_memory_access(frame, twin, evidence_store=None)
        assert DomainEnum.WORK in plan.domains_to_activate
        assert DomainEnum.MONEY in plan.domains_to_activate
        assert plan.skipped_domains == {}

    def test_gating_skips_low_weight_domains(self):
        """Domains with weight < 0.1 are skipped."""
        frame = _make_frame(domains={DomainEnum.WORK: 0.9, DomainEnum.MONEY: 0.05})
        twin = _make_twin(domains=[DomainEnum.WORK, DomainEnum.MONEY])
        plan, _ = plan_memory_access(frame, twin, evidence_store=None)
        assert DomainEnum.WORK in plan.domains_to_activate
        assert DomainEnum.MONEY not in plan.domains_to_activate
        assert DomainEnum.MONEY in plan.skipped_domains

    def test_gating_skips_unmodeled_domains(self):
        """Domains without head data are skipped."""
        frame = _make_frame(domains={DomainEnum.WORK: 0.9, DomainEnum.MONEY: 0.6})
        twin = _make_twin(domains=[DomainEnum.WORK])  # no MONEY head
        plan, _ = plan_memory_access(frame, twin, evidence_store=None)
        assert DomainEnum.WORK in plan.domains_to_activate
        assert DomainEnum.MONEY not in plan.domains_to_activate
        assert "no head data" in plan.skipped_domains[DomainEnum.MONEY]


class TestPlannerExecution:
    def test_executes_queries_against_store(self):
        """When store is provided, planner executes queries and returns evidence."""
        frame = _make_frame(ambiguity=0.75)  # triggers preference_on_axis
        twin = _make_twin()

        mock_store = MagicMock()
        mock_frag = MagicMock(spec=EvidenceFragment)
        mock_store.query.return_value = [mock_frag]

        plan, evidence = plan_memory_access(frame, twin, evidence_store=mock_store)
        assert len(evidence) > 0
        mock_store.query.assert_called()

    def test_store_error_returns_empty(self):
        """When store.query() raises, planner returns empty evidence, logs warning."""
        frame = _make_frame(ambiguity=0.75)
        twin = _make_twin()

        mock_store = MagicMock()
        mock_store.query.side_effect = RuntimeError("store down")

        plan, evidence = plan_memory_access(frame, twin, evidence_store=mock_store)
        assert evidence == []

    def test_budget_enforcement(self):
        """Total evidence budget is enforced."""
        frame = _make_frame(
            ambiguity=0.75,
            domains={DomainEnum.WORK: 0.8, DomainEnum.MONEY: 0.6},
        )
        twin = _make_twin(domains=[DomainEnum.WORK, DomainEnum.MONEY])

        mock_store = MagicMock()
        # Return 20 fragments per query (over budget)
        mock_store.query.return_value = [MagicMock(spec=EvidenceFragment)] * 20

        plan, evidence = plan_memory_access(frame, twin, evidence_store=mock_store)
        assert len(evidence) <= plan.total_evidence_budget

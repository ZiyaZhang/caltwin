"""Tests for Memory Access Planner domain models."""

from twin_runtime.domain.models.planner import MemoryAccessPlan, EnrichedActivationContext
from twin_runtime.domain.models.recall_query import RecallQuery
from twin_runtime.domain.models.primitives import DomainEnum
from twin_runtime.domain.evidence.base import EvidenceType


class TestMemoryAccessPlan:
    def test_create_empty_plan(self):
        plan = MemoryAccessPlan(
            queries=[],
            execution_strategy="parallel",
            total_evidence_budget=10,
            per_query_limit=5,
            freshness_preference="balanced",
            disabled_evidence_types=[],
            rationale="No signals matched",
        )
        assert plan.queries == []
        assert plan.total_evidence_budget == 10

    def test_create_plan_with_queries(self):
        q = RecallQuery(
            query_type="by_domain",
            user_id="user-1",
            target_domain=DomainEnum.WORK,
        )
        plan = MemoryAccessPlan(
            queries=[q],
            execution_strategy="parallel",
            total_evidence_budget=10,
            per_query_limit=5,
            freshness_preference="recent_first",
            disabled_evidence_types=[EvidenceType.CONTEXT],
            rationale="Multi-domain activation",
            domains_to_activate=[DomainEnum.WORK],
            skipped_domains={DomainEnum.MONEY: "reliability 0.30 < 0.50"},
        )
        assert len(plan.queries) == 1
        assert plan.freshness_preference == "recent_first"
        assert plan.domains_to_activate == [DomainEnum.WORK]
        assert DomainEnum.MONEY in plan.skipped_domains

    def test_enriched_activation_context(self):
        """EnrichedActivationContext requires twin, frame, evidence, rationale."""
        from twin_runtime.domain.models.planner import EnrichedActivationContext
        assert hasattr(EnrichedActivationContext, "model_fields")
        fields = set(EnrichedActivationContext.model_fields.keys())
        assert {"twin", "frame", "retrieved_evidence", "retrieval_rationale"} <= fields


class TestRuntimeDecisionTraceAudit:
    def test_trace_has_planner_fields(self):
        """RuntimeDecisionTrace should have optional planner audit fields."""
        from twin_runtime.domain.models.runtime import RuntimeDecisionTrace
        fields = RuntimeDecisionTrace.model_fields
        assert "memory_access_plan" in fields
        assert "retrieved_evidence_count" in fields
        assert "skipped_domains" in fields

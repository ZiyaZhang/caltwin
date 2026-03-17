"""Integration tests: planner wired into pipeline with mock LLM + store."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest

from twin_runtime.domain.models.planner import MemoryAccessPlan, EnrichedActivationContext
from twin_runtime.domain.models.primitives import DomainEnum, OrdinalTriLevel
from twin_runtime.domain.evidence.base import EvidenceFragment, EvidenceType


class TestPlannerInPipeline:
    def test_planner_called_when_store_provided(self):
        """Verify planner is invoked with evidence_store during pipeline run."""
        from twin_runtime.application.pipeline.runner import run

        empty_plan = MemoryAccessPlan(rationale="test", domains_to_activate=[DomainEnum.WORK])
        mock_store = MagicMock()
        mock_context = MagicMock(spec=EnrichedActivationContext)

        with patch("twin_runtime.application.pipeline.runner.plan_memory_access",
                    return_value=(empty_plan, [])) as mock_planner, \
             patch("twin_runtime.application.pipeline.runner.EnrichedActivationContext",
                    return_value=mock_context), \
             patch("twin_runtime.application.pipeline.runner.interpret_situation") as mock_si, \
             patch("twin_runtime.application.pipeline.runner.activate_heads") as mock_ah, \
             patch("twin_runtime.application.pipeline.runner.arbitrate") as mock_arb, \
             patch("twin_runtime.application.pipeline.runner.synthesize") as mock_syn:

            mock_si.return_value = (MagicMock(), None)
            mock_ah.return_value = [MagicMock()]
            mock_arb.return_value = MagicMock()
            mock_trace = MagicMock()
            mock_syn.return_value = mock_trace

            mock_llm = MagicMock()
            mock_twin = MagicMock()

            run("test query", ["A", "B"], mock_twin, llm=mock_llm, evidence_store=mock_store)

            # Planner was called with the evidence store
            mock_planner.assert_called_once()
            call_args = mock_planner.call_args
            assert call_args[0][2] is mock_store

    def test_enriched_context_passed_to_activator(self):
        """Verify EnrichedActivationContext is created and passed to activate_heads."""
        from twin_runtime.application.pipeline.runner import run

        empty_plan = MemoryAccessPlan(rationale="test", domains_to_activate=[DomainEnum.WORK])
        mock_context = MagicMock(spec=EnrichedActivationContext)

        with patch("twin_runtime.application.pipeline.runner.plan_memory_access",
                    return_value=(empty_plan, [])), \
             patch("twin_runtime.application.pipeline.runner.EnrichedActivationContext",
                    return_value=mock_context) as mock_ctx_cls, \
             patch("twin_runtime.application.pipeline.runner.interpret_situation") as mock_si, \
             patch("twin_runtime.application.pipeline.runner.activate_heads") as mock_ah, \
             patch("twin_runtime.application.pipeline.runner.arbitrate") as mock_arb, \
             patch("twin_runtime.application.pipeline.runner.synthesize") as mock_syn:

            mock_si.return_value = (MagicMock(), None)
            mock_ah.return_value = [MagicMock()]
            mock_arb.return_value = MagicMock()
            mock_syn.return_value = MagicMock()

            mock_llm = MagicMock()
            mock_twin = MagicMock()

            run("test query", ["A", "B"], mock_twin, llm=mock_llm)

            # EnrichedActivationContext was constructed
            mock_ctx_cls.assert_called_once()
            # activate_heads received the context
            ah_call = mock_ah.call_args
            assert ah_call[0][2] is mock_context

    def test_run_without_store_backward_compat(self):
        """Pipeline works without evidence_store (current behavior)."""
        import inspect
        from twin_runtime.application.pipeline.runner import run
        sig = inspect.signature(run)
        assert "evidence_store" in sig.parameters
        assert sig.parameters["evidence_store"].default is None

    def test_trace_has_planner_audit(self):
        """RuntimeDecisionTrace can hold planner audit data."""
        from twin_runtime.domain.models.runtime import RuntimeDecisionTrace

        plan = MemoryAccessPlan(rationale="test")
        trace_data = {
            "trace_id": "t-1",
            "twin_state_version": "v001",
            "situation_frame_id": "sf-1",
            "activated_domains": [DomainEnum.WORK],
            "head_assessments": [{
                "domain": DomainEnum.WORK,
                "head_version": "v1",
                "option_ranking": ["A"],
                "utility_decomposition": {"growth": 0.8},
                "confidence": 0.7,
            }],
            "final_decision": "A",
            "decision_mode": "direct",
            "uncertainty": 0.3,
            "created_at": datetime.now(timezone.utc),
            "memory_access_plan": plan.model_dump(),
            "retrieved_evidence_count": 3,
            "skipped_domains": {"money": "reliability 0.30 < 0.50"},
        }
        trace = RuntimeDecisionTrace.model_validate(trace_data)
        assert trace.retrieved_evidence_count == 3
        assert trace.memory_access_plan is not None
        assert trace.skipped_domains["money"] == "reliability 0.30 < 0.50"

    def test_audit_fields_populated_by_runner(self):
        """Verify runner populates audit fields on the trace."""
        from twin_runtime.application.pipeline.runner import run

        plan = MemoryAccessPlan(
            rationale="test",
            domains_to_activate=[DomainEnum.WORK],
            skipped_domains={DomainEnum.MONEY: "low weight"},
        )
        mock_frag = MagicMock(spec=EvidenceFragment)
        mock_context = MagicMock(spec=EnrichedActivationContext)

        with patch("twin_runtime.application.pipeline.runner.plan_memory_access",
                    return_value=(plan, [mock_frag])), \
             patch("twin_runtime.application.pipeline.runner.EnrichedActivationContext",
                    return_value=mock_context), \
             patch("twin_runtime.application.pipeline.runner.interpret_situation") as mock_si, \
             patch("twin_runtime.application.pipeline.runner.activate_heads") as mock_ah, \
             patch("twin_runtime.application.pipeline.runner.arbitrate") as mock_arb, \
             patch("twin_runtime.application.pipeline.runner.synthesize") as mock_syn:

            mock_si.return_value = (MagicMock(), None)
            mock_ah.return_value = [MagicMock()]
            mock_arb.return_value = MagicMock()
            mock_trace = MagicMock()
            mock_syn.return_value = mock_trace

            mock_llm = MagicMock()
            mock_twin = MagicMock()

            result = run("test", ["A"], mock_twin, llm=mock_llm)

            # Audit fields should be set on the trace
            assert result.memory_access_plan is not None
            assert result.retrieved_evidence_count == 1
            assert result.skipped_domains == {"money": "low weight"}

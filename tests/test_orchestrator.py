"""Tests for runtime orchestrator: S1/S2 routing, refusal, degradation, force_path."""
import uuid
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from tests.helpers import make_situation_frame, make_twin
from twin_runtime.application.orchestrator.models import (
    BoundaryPolicy, ExecutionPath, RouteDecision,
)
from twin_runtime.application.orchestrator.runtime_orchestrator import run
from twin_runtime.application.pipeline.scope_guard import ScopeGuardResult
from twin_runtime.domain.models.primitives import (
    DecisionMode, DomainEnum, ScopeStatus,
)
from twin_runtime.domain.models.runtime import RuntimeDecisionTrace


def _twin():
    return make_twin()


def _frame(scope=ScopeStatus.IN_SCOPE, stakes="medium", ambiguity=0.3, domains=None):
    return make_situation_frame(scope=scope, stakes=stakes, ambiguity=ambiguity, domains=domains)


def _mock_trace(
    decision_mode=DecisionMode.DIRECT,
    refusal_reason_code=None,
    head_assessments=None,
    skipped_domains=None,
):
    """Build a mock RuntimeDecisionTrace."""
    return RuntimeDecisionTrace(
        trace_id=str(uuid.uuid4()),
        twin_state_version="v-test",
        situation_frame_id="test-frame",
        activated_domains=[DomainEnum.WORK],
        head_assessments=head_assessments or [],
        final_decision="Test decision",
        decision_mode=decision_mode,
        uncertainty=0.3,
        query="test query",
        situation_frame={},
        route_path="s1_direct",
        route_reason_codes=[],
        boundary_policy="normal",
        refusal_reason_code=refusal_reason_code,
        skipped_domains=skipped_domains or {},
        created_at=datetime.now(timezone.utc),
    )


INTERPRET_PATH = "twin_runtime.application.orchestrator.runtime_orchestrator.interpret_situation"
SINGLE_PASS_PATH = "twin_runtime.application.orchestrator.runtime_orchestrator.execute_from_frame_once"
DELIBERATION_PATH = "twin_runtime.application.orchestrator.runtime_orchestrator.deliberation_loop"


class TestS1Path:
    """Simple query -> S1 direct path."""

    @patch(SINGLE_PASS_PATH)
    @patch(INTERPRET_PATH)
    def test_s1_route_path(self, mock_interpret, mock_single_pass):
        frame = _frame()
        guard = ScopeGuardResult()
        mock_interpret.return_value = (frame, guard)
        mock_single_pass.return_value = _mock_trace()

        twin = _twin()
        trace = run("What project should I prioritize?", ["A", "B"], twin, llm=MagicMock())

        assert trace.route_path == "s1_direct"
        assert trace.boundary_policy == "normal"
        mock_single_pass.assert_called_once()


class TestForceRefuse:
    """Restricted query -> FORCE_REFUSE -> REFUSED trace without pipeline."""

    @patch(INTERPRET_PATH)
    def test_restricted_query_refused(self, mock_interpret):
        frame = _frame(scope=ScopeStatus.OUT_OF_SCOPE, domains={})
        guard = ScopeGuardResult(restricted_hit=True, matched_terms=["restricted:x=y"])
        mock_interpret.return_value = (frame, guard)

        twin = _twin()
        trace = run("impersonate my partner", ["A", "B"], twin, llm=MagicMock())

        assert trace.decision_mode == DecisionMode.REFUSED
        assert trace.route_path == "no_execution"
        assert trace.boundary_policy == "force_refuse"
        assert trace.refusal_reason_code == "POLICY_RESTRICTED"


class TestForceDegradeDoesNotOverrideRefused:
    """FORCE_DEGRADE must NOT override a REFUSED trace from single_pass."""

    @patch(SINGLE_PASS_PATH)
    @patch(INTERPRET_PATH)
    def test_refused_stays_refused_under_degrade(self, mock_interpret, mock_single_pass):
        # non_modeled_hit with activation -> Rule 3: S1 + FORCE_DEGRADE
        frame = _frame()
        guard = ScopeGuardResult(non_modeled_hit=True)
        mock_interpret.return_value = (frame, guard)

        # single_pass returns REFUSED
        refused_trace = _mock_trace(
            decision_mode=DecisionMode.REFUSED,
            refusal_reason_code="LOW_RELIABILITY",
        )
        mock_single_pass.return_value = refused_trace

        twin = _twin()
        trace = run("how do i feel right now?", ["A", "B"], twin, llm=MagicMock())

        # FORCE_DEGRADE should NOT override REFUSED
        assert trace.decision_mode == DecisionMode.REFUSED
        assert trace.refusal_reason_code == "LOW_RELIABILITY"


class TestForcePathOverride:
    """force_path=S1_DIRECT overrides S2 routing."""

    @patch(SINGLE_PASS_PATH)
    @patch(INTERPRET_PATH)
    def test_force_path_s1_executes_s1(self, mock_interpret, mock_single_pass):
        # multi-domain -> would normally route S2
        frame = _frame(domains={DomainEnum.WORK: 0.6, DomainEnum.MONEY: 0.4})
        guard = ScopeGuardResult()
        mock_interpret.return_value = (frame, guard)
        mock_single_pass.return_value = _mock_trace()

        twin = _twin()
        trace = run(
            "Should I take the higher-paying job?", ["A", "B"], twin,
            llm=MagicMock(),
            force_path=ExecutionPath.S1_DIRECT,
        )

        assert trace.route_path == "s1_direct"
        assert any("force_path_override" in rc for rc in trace.route_reason_codes)
        mock_single_pass.assert_called_once()


class TestLowReliabilityPostExecution:
    """Empty assessments + all skipped_domains with 'reliability' -> LOW_RELIABILITY."""

    @patch(SINGLE_PASS_PATH)
    @patch(INTERPRET_PATH)
    def test_low_reliability_rule(self, mock_interpret, mock_single_pass):
        frame = _frame()
        guard = ScopeGuardResult()
        mock_interpret.return_value = (frame, guard)

        trace = _mock_trace(
            decision_mode=DecisionMode.REFUSED,
            refusal_reason_code=None,
            head_assessments=[],
            skipped_domains={"work": "below reliability threshold"},
        )
        mock_single_pass.return_value = trace

        twin = _twin()
        result = run("test", ["A", "B"], twin, llm=MagicMock())

        assert result.refusal_reason_code == "LOW_RELIABILITY"


class TestRefusalCodePrecedence:
    """Deliberation loop setting INSUFFICIENT_EVIDENCE must not be overwritten."""

    @patch(DELIBERATION_PATH)
    @patch(INTERPRET_PATH)
    def test_existing_refusal_code_preserved(self, mock_interpret, mock_delib):
        # multi-domain -> S2
        frame = _frame(domains={DomainEnum.WORK: 0.6, DomainEnum.MONEY: 0.4})
        guard = ScopeGuardResult()
        mock_interpret.return_value = (frame, guard)

        trace = _mock_trace(
            decision_mode=DecisionMode.REFUSED,
            refusal_reason_code="INSUFFICIENT_EVIDENCE",
        )
        mock_delib.return_value = trace

        twin = _twin()
        result = run("complex multi-domain question", ["A", "B"], twin, llm=MagicMock())

        # orchestrator must NOT overwrite INSUFFICIENT_EVIDENCE
        assert result.refusal_reason_code == "INSUFFICIENT_EVIDENCE"

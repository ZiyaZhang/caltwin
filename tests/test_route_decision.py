"""Tests for route decision engine."""
import json
from pathlib import Path

import pytest

from twin_runtime.application.orchestrator.models import BoundaryPolicy, ExecutionPath
from twin_runtime.application.orchestrator.route_decision import decide_route
from twin_runtime.application.pipeline.scope_guard import ScopeGuardResult
from twin_runtime.domain.models.primitives import (
    DomainEnum,
    OptionStructure,
    OrdinalTriLevel,
    ScopeStatus,
    UncertaintyType,
)
from twin_runtime.domain.models.situation import SituationFeatureVector, SituationFrame


def _frame(scope=ScopeStatus.IN_SCOPE, stakes="medium", ambiguity=0.3, domains=None):
    return SituationFrame(
        frame_id="test",
        domain_activation_vector=domains if domains is not None else {DomainEnum.WORK: 0.9},
        situation_feature_vector=SituationFeatureVector(
            reversibility=OrdinalTriLevel.MEDIUM,
            stakes=OrdinalTriLevel(stakes),
            uncertainty_type=UncertaintyType.MIXED,
            controllability=OrdinalTriLevel.MEDIUM,
            option_structure=OptionStructure.CHOOSE_EXISTING,
        ),
        ambiguity_score=ambiguity,
        scope_status=scope,
        routing_confidence=0.8,
    )


def _twin():
    from twin_runtime.domain.models.twin_state import TwinState

    return TwinState(**json.loads(Path("tests/fixtures/sample_twin_state.json").read_text()))


class TestRouteDecisionRules:
    def test_rule1_restricted_refuses(self):
        guard = ScopeGuardResult(restricted_hit=True, matched_terms=["restricted:x=y"])
        route = decide_route(_frame(), guard, _twin())
        assert route.execution_path == ExecutionPath.NO_EXECUTION
        assert route.boundary_policy == BoundaryPolicy.FORCE_REFUSE
        assert "policy_restricted" in route.reason_codes

    def test_rule2_non_modeled_no_activation_refuses(self):
        guard = ScopeGuardResult(non_modeled_hit=True)
        route = decide_route(_frame(domains={}), guard, _twin())
        assert route.execution_path == ExecutionPath.NO_EXECUTION
        assert route.boundary_policy == BoundaryPolicy.FORCE_REFUSE
        assert "non_modeled_no_activation" in route.reason_codes

    def test_rule3_non_modeled_with_activation_degrades(self):
        guard = ScopeGuardResult(non_modeled_hit=True)
        route = decide_route(_frame(), guard, _twin())
        assert route.execution_path == ExecutionPath.S1_DIRECT
        assert route.boundary_policy == BoundaryPolicy.FORCE_DEGRADE
        assert "non_modeled_partial" in route.reason_codes

    def test_rule4_out_of_scope_refuses(self):
        route = decide_route(_frame(scope=ScopeStatus.OUT_OF_SCOPE, domains={}), None, _twin())
        assert route.execution_path == ExecutionPath.NO_EXECUTION
        assert route.boundary_policy == BoundaryPolicy.FORCE_REFUSE
        assert "out_of_scope" in route.reason_codes

    def test_rule5_borderline_high_stakes_s2(self):
        route = decide_route(_frame(scope=ScopeStatus.BORDERLINE, stakes="high"), None, _twin())
        assert route.execution_path == ExecutionPath.S2_DELIBERATE
        assert route.boundary_policy == BoundaryPolicy.FORCE_DEGRADE
        assert "borderline_high_stakes" in route.reason_codes

    def test_rule6_borderline_degrades(self):
        route = decide_route(_frame(scope=ScopeStatus.BORDERLINE), None, _twin())
        assert route.execution_path == ExecutionPath.S1_DIRECT
        assert route.boundary_policy == BoundaryPolicy.FORCE_DEGRADE

    def test_rule7_high_stakes_high_ambiguity_s2(self):
        route = decide_route(_frame(stakes="high", ambiguity=0.7), None, _twin())
        assert route.execution_path == ExecutionPath.S2_DELIBERATE
        assert route.boundary_policy == BoundaryPolicy.NORMAL
        assert "high_stakes_high_ambiguity" in route.reason_codes

    def test_rule8_multi_domain_s2(self):
        route = decide_route(
            _frame(domains={DomainEnum.WORK: 0.6, DomainEnum.MONEY: 0.4}), None, _twin()
        )
        assert route.execution_path == ExecutionPath.S2_DELIBERATE
        assert "multi_domain" in route.reason_codes

    def test_rule9_default_s1(self):
        route = decide_route(_frame(), None, _twin())
        assert route.execution_path == ExecutionPath.S1_DIRECT
        assert route.boundary_policy == BoundaryPolicy.NORMAL
        assert route.reason_codes == []

    def test_shadow_scores_always_present(self):
        route = decide_route(_frame(), None, _twin())
        assert "deliberation_pressure" in route.shadow_scores
        assert "abstention_risk" in route.shadow_scores
        assert 0.0 <= route.shadow_scores["deliberation_pressure"] <= 1.0
        assert 0.0 <= route.shadow_scores["abstention_risk"] <= 1.0

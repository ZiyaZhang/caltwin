"""Route decision engine — 9-rule cascade with shadow scores."""
from __future__ import annotations

from typing import Dict, Optional

from twin_runtime.application.orchestrator.models import (
    BoundaryPolicy,
    ExecutionPath,
    RouteDecision,
)
from twin_runtime.application.pipeline.scope_guard import ScopeGuardResult
from twin_runtime.domain.models.primitives import OrdinalTriLevel, ScopeStatus
from twin_runtime.domain.models.situation import SituationFrame
from twin_runtime.domain.models.twin_state import TwinState


def _shadow_scores(
    frame: SituationFrame,
    guard_result: Optional[ScopeGuardResult],
    twin: TwinState,
) -> Dict[str, float]:
    """Compute observation-only shadow scores (never used in routing decisions)."""
    sfv = frame.situation_feature_vector
    stakes_val = {"low": 0.0, "medium": 0.5, "high": 1.0}.get(sfv.stakes.value, 0.5)
    n_domains = len(frame.domain_activation_vector)
    guard_pressure = 1.0 if (guard_result and guard_result.triggered) else 0.0
    deliberation_pressure = (
        stakes_val * 0.3
        + frame.ambiguity_score * 0.3
        + min(n_domains / 3.0, 1.0) * 0.2
        + (1.0 - frame.routing_confidence) * 0.2
    )
    abstention_risk = (
        guard_pressure * 0.4
        + (1.0 if frame.scope_status != ScopeStatus.IN_SCOPE else 0.0) * 0.3
        + frame.ambiguity_score * 0.3
    )
    return {
        "deliberation_pressure": round(deliberation_pressure, 3),
        "abstention_risk": round(abstention_risk, 3),
    }


def decide_route(
    frame: SituationFrame,
    guard_result: Optional[ScopeGuardResult],
    twin: TwinState,
) -> RouteDecision:
    """Apply 9-rule cascade to determine execution path and boundary policy.

    Rules are evaluated in strict priority order; the first match wins.
    Shadow scores are always attached for observability.
    """
    shadow = _shadow_scores(frame, guard_result, twin)
    activation = frame.domain_activation_vector
    sfv = frame.situation_feature_vector

    # Rule 1: restricted scope-guard hit
    if guard_result and guard_result.restricted_hit:
        return RouteDecision(
            execution_path=ExecutionPath.NO_EXECUTION,
            boundary_policy=BoundaryPolicy.FORCE_REFUSE,
            reason_codes=["policy_restricted"],
            shadow_scores=shadow,
        )

    # Rule 2: non-modeled hit with no domain activation
    if guard_result and guard_result.non_modeled_hit and not activation:
        return RouteDecision(
            execution_path=ExecutionPath.NO_EXECUTION,
            boundary_policy=BoundaryPolicy.FORCE_REFUSE,
            reason_codes=["non_modeled_no_activation"],
            shadow_scores=shadow,
        )

    # Rule 3: non-modeled hit with some activation
    if guard_result and guard_result.non_modeled_hit:
        return RouteDecision(
            execution_path=ExecutionPath.S1_DIRECT,
            boundary_policy=BoundaryPolicy.FORCE_DEGRADE,
            reason_codes=["non_modeled_partial"],
            shadow_scores=shadow,
        )

    # Rule 4: out of scope
    if frame.scope_status == ScopeStatus.OUT_OF_SCOPE:
        return RouteDecision(
            execution_path=ExecutionPath.NO_EXECUTION,
            boundary_policy=BoundaryPolicy.FORCE_REFUSE,
            reason_codes=["out_of_scope"],
            shadow_scores=shadow,
        )

    # Rule 5: borderline + high stakes
    if frame.scope_status == ScopeStatus.BORDERLINE and sfv.stakes == OrdinalTriLevel.HIGH:
        return RouteDecision(
            execution_path=ExecutionPath.S2_DELIBERATE,
            boundary_policy=BoundaryPolicy.FORCE_DEGRADE,
            reason_codes=["borderline_high_stakes"],
            shadow_scores=shadow,
        )

    # Rule 6: borderline scope (any stakes)
    if frame.scope_status == ScopeStatus.BORDERLINE:
        return RouteDecision(
            execution_path=ExecutionPath.S1_DIRECT,
            boundary_policy=BoundaryPolicy.FORCE_DEGRADE,
            reason_codes=["borderline_scope"],
            shadow_scores=shadow,
        )

    # Rule 7: high stakes + high ambiguity
    if sfv.stakes == OrdinalTriLevel.HIGH and frame.ambiguity_score > 0.6:
        return RouteDecision(
            execution_path=ExecutionPath.S2_DELIBERATE,
            boundary_policy=BoundaryPolicy.NORMAL,
            reason_codes=["high_stakes_high_ambiguity"],
            shadow_scores=shadow,
        )

    # Rule 8: multi-domain activation
    if len(activation) > 1:
        return RouteDecision(
            execution_path=ExecutionPath.S2_DELIBERATE,
            boundary_policy=BoundaryPolicy.NORMAL,
            reason_codes=["multi_domain"],
            shadow_scores=shadow,
        )

    # Rule 9: default
    return RouteDecision(
        execution_path=ExecutionPath.S1_DIRECT,
        boundary_policy=BoundaryPolicy.NORMAL,
        reason_codes=[],
        shadow_scores=shadow,
    )

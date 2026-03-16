"""Domain Head Activation: generate HeadAssessment for each activated domain.

Step A of the runtime — structured evaluation only, no prose.
"""

from __future__ import annotations

import json
from typing import Dict, List

from twin_runtime.domain.models.primitives import DomainEnum, confidence_field
from twin_runtime.domain.models.runtime import HeadAssessment
from twin_runtime.domain.models.situation import SituationFrame
from twin_runtime.domain.models.twin_state import TwinState, DomainHead, SharedDecisionCore, CausalBeliefModel
from twin_runtime.infrastructure.llm.client import ask_json


def _build_head_prompt(
    query: str,
    option_set: List[str],
    head: DomainHead,
    core: SharedDecisionCore,
    causal: CausalBeliefModel,
    feature_summary: str,
) -> tuple[str, str]:
    """Build system + user prompts for a single domain head assessment."""
    system = f"""You are a decision-assessment module for the "{head.domain.value}" domain.
You evaluate options strictly from the perspective of this domain's goals: {head.goal_axes}.
Priority order: {head.default_priority_order or head.goal_axes}.

The person you model has these decision parameters:
- Risk tolerance: {core.risk_tolerance}
- Ambiguity tolerance: {core.ambiguity_tolerance}
- Action threshold: {core.action_threshold}
- Conflict style: {core.conflict_style.value}
- Regret sensitivity: {core.regret_sensitivity}
- Control orientation: {causal.control_orientation.value}
- Change strategy: {causal.change_strategy.value if causal.change_strategy else 'unknown'}

Output ONLY a JSON object:
{{
  "option_ranking": ["best_option", "second", ...],
  "utility_decomposition": {{"axis_name": score_0_to_1, ...}},
  "confidence": 0.0-1.0,
  "used_core_variables": ["var1", ...],
  "used_evidence_types": ["type1", ...]
}}
Use the goal axes as utility decomposition keys. Output ONLY valid JSON."""

    user = f"""Situation: {feature_summary}

Query: {query}

Options to rank: {json.dumps(option_set)}"""

    return system, user


def activate_heads(
    query: str,
    option_set: List[str],
    frame: SituationFrame,
    twin: TwinState,
) -> List[HeadAssessment]:
    """Generate HeadAssessment for each activated domain."""
    # Select heads to activate: domains in activation vector with weight > 0.1
    active_domains = {
        d for d, w in frame.domain_activation_vector.items() if w > 0.1
    }

    # Map domain -> head
    head_map: Dict[DomainEnum, DomainHead] = {
        h.domain: h for h in twin.domain_heads
    }

    feature_summary = (
        f"stakes={frame.situation_feature_vector.stakes.value}, "
        f"reversibility={frame.situation_feature_vector.reversibility.value}, "
        f"controllability={frame.situation_feature_vector.controllability.value}, "
        f"uncertainty={frame.situation_feature_vector.uncertainty_type.value}"
    )

    assessments: List[HeadAssessment] = []
    for domain in active_domains:
        head = head_map.get(domain)
        if head is None:
            continue  # No head for this domain

        system, user = _build_head_prompt(
            query, option_set, head,
            twin.shared_decision_core,
            twin.causal_belief_model,
            feature_summary,
        )

        raw = ask_json(system, user, max_tokens=512)

        assessment = HeadAssessment(
            domain=domain,
            head_version=head.head_version,
            option_ranking=raw.get("option_ranking", option_set),
            utility_decomposition=raw.get("utility_decomposition", {}),
            confidence=min(1.0, max(0.0, float(raw.get("confidence", 0.5)))),
            used_core_variables=raw.get("used_core_variables", []),
            used_evidence_types=raw.get("used_evidence_types", []),
        )
        assessments.append(assessment)

    return assessments

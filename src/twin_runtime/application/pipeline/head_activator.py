"""Domain Head Activation: generate HeadAssessment for each activated domain.

Step A of the runtime — structured evaluation only, no prose.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional, Union

from twin_runtime.domain.models.primitives import DomainEnum, confidence_field
from twin_runtime.domain.models.runtime import HeadAssessment
from twin_runtime.domain.models.situation import SituationFrame
from twin_runtime.domain.models.twin_state import TwinState, DomainHead, SharedDecisionCore, CausalBeliefModel, BiasCorrectionEntry
from twin_runtime.domain.models.planner import EnrichedActivationContext
from twin_runtime.domain.evidence.base import EvidenceFragment
from twin_runtime.domain.ports.llm_port import LLMPort


def _format_evidence(evidence: List[EvidenceFragment]) -> str:
    """Format evidence fragments for LLM prompt injection."""
    if not evidence:
        return ""
    lines = []
    for i, frag in enumerate(evidence, 1):
        lines.append(f"{i}. [{frag.evidence_type.value}] {frag.summary} (confidence: {frag.confidence:.2f})")
    return "\n".join(lines)


def _find_bias_corrections(
    domain: DomainEnum,
    corrections: List[BiasCorrectionEntry],
) -> List[BiasCorrectionEntry]:
    """Find active bias corrections that apply to this domain."""
    matched = []
    for bc in corrections:
        if not bc.still_active:
            continue
        scope = bc.target_scope
        if scope.get("domain") and scope["domain"] != domain.value:
            continue
        matched.append(bc)
    return matched


def _build_head_prompt(
    query: str,
    option_set: List[str],
    head: DomainHead,
    core: SharedDecisionCore,
    causal: CausalBeliefModel,
    feature_summary: str,
    evidence_summary: str = "",
    bias_corrections: Optional[List[BiasCorrectionEntry]] = None,
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

    if evidence_summary:
        system += f"""

## Relevant Evidence
The following raw evidence fragments were retrieved for this decision:
{evidence_summary}

Use these alongside the persona parameters to inform your assessment."""

    if bias_corrections:
        correction_lines = []
        for bc in bias_corrections:
            instruction = bc.correction_payload.get("instruction", "")
            if instruction:
                correction_lines.append(f"- {instruction}")
        if correction_lines:
            system += f"""

## Known Bias Corrections
IMPORTANT: The following corrections are based on observed discrepancies between
LLM default assumptions and this person's actual behavior. Apply these when ranking:
{chr(10).join(correction_lines)}"""

    user = f"""Situation: {feature_summary}

Query: {query}

Options to rank: {json.dumps(option_set)}"""

    return system, user


def activate_heads(
    query: str,
    option_set: List[str],
    context: Union[EnrichedActivationContext, SituationFrame],
    twin: Optional[TwinState] = None,
    *,
    llm: LLMPort,
) -> List[HeadAssessment]:
    """Generate HeadAssessment for each activated domain.

    Args:
        context: Either EnrichedActivationContext (from planner) or SituationFrame (backward compat)
        twin: Required when context is SituationFrame, ignored when EnrichedActivationContext
    """
    if isinstance(context, EnrichedActivationContext):
        twin = context.twin
        frame = context.frame
        evidence = context.retrieved_evidence
    else:
        frame = context
        evidence = []
        if twin is None:
            raise ValueError("twin is required when context is a SituationFrame")

    evidence_summary = _format_evidence(evidence)

    # Select heads to activate: use planner's domain gating when available,
    # otherwise fall back to raw activation vector (backward compat)
    if isinstance(context, EnrichedActivationContext) and context.domains_to_activate:
        active_domains = set(context.domains_to_activate)
    else:
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

        domain_corrections = _find_bias_corrections(domain, twin.bias_correction_policy)

        system, user = _build_head_prompt(
            query, option_set, head,
            twin.shared_decision_core,
            twin.causal_belief_model,
            feature_summary,
            evidence_summary,
            bias_corrections=domain_corrections,
        )

        raw = llm.ask_json(system, user, max_tokens=2048)

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

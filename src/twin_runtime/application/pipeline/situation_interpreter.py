"""Situation Interpreter: three-stage hybrid routing.

Stage 1: Rule-based feature extraction (hard signals)
Stage 2: LLM-assisted interpretation (domain activation + feature vector)
Stage 3: Constrained routing policy (thresholds + scope gate)
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Dict, List, Optional

from twin_runtime.domain.models.primitives import DomainEnum, OrdinalTriLevel, ScopeStatus, UncertaintyType, OptionStructure
from twin_runtime.domain.models.situation import SituationFeatureVector, SituationFrame
from twin_runtime.domain.models.twin_state import TwinState, ScopeDeclaration
from twin_runtime.runtime.llm_client import ask_json


# --- Stage 1: Rule-based hard signal extraction ---

_DOMAIN_KEYWORDS: Dict[DomainEnum, List[str]] = {
    DomainEnum.WORK: ["project", "task", "deadline", "code", "team", "meeting", "sprint",
                       "deploy", "review", "hire", "product", "feature", "bug",
                       "工作", "项目", "任务", "代码", "团队", "会议"],
    DomainEnum.LIFE_PLANNING: ["career", "move", "city", "life", "future", "direction",
                                "quit", "start", "long-term", "purpose",
                                "职业", "搬家", "城市", "未来", "方向", "人生"],
    DomainEnum.MONEY: ["salary", "invest", "cost", "budget", "price", "income", "equity",
                        "薪资", "投资", "成本", "预算", "收入"],
    DomainEnum.RELATIONSHIPS: ["partner", "friend", "family", "relationship", "social",
                                "伴侣", "朋友", "家人", "关系"],
    DomainEnum.PUBLIC_EXPRESSION: ["post", "publish", "tweet", "blog", "public", "audience",
                                    "发布", "公开", "受众"],
}


def _keyword_scores(query: str) -> Dict[DomainEnum, float]:
    """Count keyword hits per domain, return normalized scores."""
    q = query.lower()
    hits: Dict[DomainEnum, int] = {}
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        hits[domain] = sum(1 for kw in keywords if kw in q)
    total = sum(hits.values())
    if total == 0:
        return {}
    return {d: c / total for d, c in hits.items() if c > 0}


# --- Stage 2: LLM-assisted interpretation ---

_INTERPRET_SYSTEM = """You are a situation analysis engine for a decision-twin system.
Given a user query and the twin's valid domains, output a JSON object with exactly these fields:
{
  "domain_activation": {"work": 0.0-1.0, ...},
  "reversibility": "low"|"medium"|"high",
  "stakes": "low"|"medium"|"high",
  "uncertainty_type": "missing_info"|"outcome_uncertainty"|"value_conflict"|"mixed",
  "controllability": "low"|"medium"|"high",
  "option_structure": "choose_existing"|"generate_new"|"mixed",
  "ambiguity_score": 0.0-1.0,
  "clarification_questions": []
}
Only include domains from the provided list. Output ONLY valid JSON, no explanation."""


def _llm_interpret(query: str, valid_domains: List[str]) -> dict:
    user_msg = f"Valid domains: {valid_domains}\n\nQuery: {query}"
    return ask_json(_INTERPRET_SYSTEM, user_msg, max_tokens=512)


# --- Stage 3: Constrained routing policy ---

_DOMINANCE_GAP = 0.5
_MULTI_DOMAIN_GAP = 0.15
_AMBIGUITY_THRESHOLD = 0.7
_CONFIDENCE_THRESHOLD = 0.4


def _apply_routing_policy(
    activation: Dict[DomainEnum, float],
    ambiguity: float,
    scope: ScopeDeclaration,
    twin: TwinState,
) -> tuple[Dict[DomainEnum, float], ScopeStatus, float]:
    """Apply thresholds; return (filtered_activation, scope_status, routing_confidence)."""
    # Filter to valid domains only
    valid = set(twin.valid_domains())
    filtered = {d: w for d, w in activation.items() if d in valid}

    if not filtered:
        # Check if ANY domain was activated (just not valid ones)
        if activation:
            return activation, ScopeStatus.BORDERLINE, 0.3
        return {DomainEnum.WORK: 1.0}, ScopeStatus.OUT_OF_SCOPE, 0.1

    # Normalize
    total = sum(filtered.values())
    if total > 0:
        filtered = {d: w / total for d, w in filtered.items()}

    # Routing confidence based on ambiguity and activation clarity
    sorted_weights = sorted(filtered.values(), reverse=True)
    if len(sorted_weights) >= 2:
        gap = sorted_weights[0] - sorted_weights[1]
    else:
        gap = 1.0
    routing_confidence = min(1.0, (1.0 - ambiguity) * 0.6 + gap * 0.4)

    scope_status = ScopeStatus.IN_SCOPE
    if ambiguity > _AMBIGUITY_THRESHOLD:
        scope_status = ScopeStatus.BORDERLINE

    return filtered, scope_status, routing_confidence


# --- Public API ---


def interpret_situation(query: str, twin: TwinState) -> SituationFrame:
    """Run the three-stage Situation Interpreter pipeline."""
    all_domains = [d.value for d in DomainEnum]

    # Stage 1: keyword hints
    keyword_hints = _keyword_scores(query)

    # Stage 2: LLM interpretation
    llm_result = _llm_interpret(query, all_domains)

    # Merge: LLM is primary, keyword hints boost
    raw_activation: Dict[DomainEnum, float] = {}
    llm_act = llm_result.get("domain_activation", {})
    for d_str, weight in llm_act.items():
        try:
            d = DomainEnum(d_str)
            raw_activation[d] = float(weight)
        except (ValueError, TypeError):
            continue

    # Boost with keyword hints (additive, small weight)
    for d, kw_score in keyword_hints.items():
        raw_activation[d] = raw_activation.get(d, 0.0) + kw_score * 0.2

    ambiguity = float(llm_result.get("ambiguity_score", 0.5))

    # Stage 3: routing policy
    filtered_activation, scope_status, routing_confidence = _apply_routing_policy(
        raw_activation, ambiguity, twin.scope_declaration, twin
    )

    # Build feature vector from LLM output
    feature_vector = SituationFeatureVector(
        reversibility=OrdinalTriLevel(llm_result.get("reversibility", "medium")),
        stakes=OrdinalTriLevel(llm_result.get("stakes", "medium")),
        uncertainty_type=UncertaintyType(llm_result.get("uncertainty_type", "mixed")),
        controllability=OrdinalTriLevel(llm_result.get("controllability", "medium")),
        option_structure=OptionStructure(llm_result.get("option_structure", "choose_existing")),
    )

    return SituationFrame(
        frame_id=str(uuid.uuid4()),
        domain_activation_vector=filtered_activation,
        situation_feature_vector=feature_vector,
        ambiguity_score=ambiguity,
        clarification_questions=llm_result.get("clarification_questions", []),
        scope_status=scope_status,
        routing_confidence=routing_confidence,
    )

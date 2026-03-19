"""Situation Interpreter: three-stage hybrid routing.

Stage 1: Rule-based feature extraction (hard signals)
Stage 2: LLM-assisted interpretation (domain activation + feature vector)
Stage 3: Constrained routing policy (thresholds + scope gate)
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from twin_runtime.domain.models.primitives import DomainEnum, OrdinalTriLevel, ScopeStatus, UncertaintyType, OptionStructure
from twin_runtime.domain.models.situation import SituationFeatureVector, SituationFrame
from twin_runtime.domain.models.twin_state import TwinState, ScopeDeclaration
from twin_runtime.domain.ports.llm_port import LLMPort
from twin_runtime.application.pipeline.scope_guard import ScopeGuardResult, deterministic_scope_guard


# --- Stage 1: Rule-based hard signal extraction ---

_LEGACY_KEYWORDS: Dict[DomainEnum, List[str]] = {
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


def _keyword_scores_from_twin(query: str, domain_heads: list) -> Dict[DomainEnum, float]:
    """Count keyword hits per domain using DomainHead.keywords, return normalized scores.

    Falls back to _LEGACY_KEYWORDS for heads with empty keywords (pre-migration TwinState).
    """
    q = query.lower()
    hits: Dict[DomainEnum, int] = {}
    for head in domain_heads:
        keywords = head.keywords or _LEGACY_KEYWORDS.get(head.domain, [])
        if not keywords:
            continue
        hits[head.domain] = sum(
            1 for kw in keywords
            if (re.search(r'\b' + re.escape(kw) + r'\b', q) if kw.isascii() else kw in q)
        )
    total = sum(hits.values())
    if total == 0:
        return {}
    return {d: c / total for d, c in hits.items() if c > 0}


# --- Stage 2: LLM-assisted interpretation ---

_INTERPRET_SYSTEM = """You are a situation analysis engine for a decision-twin system.
Given a user query and the twin's valid domains, analyze the situation and provide:
- domain activation weights (0.0-1.0 for each relevant domain)
- situational features (reversibility, stakes, uncertainty, controllability)
- option structure and ambiguity assessment
Only include domains from the provided valid domains list."""

_SITUATION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "domain_activation": {
            "type": "object",
            "description": "Domain name to activation weight (0.0-1.0)",
            "additionalProperties": {"type": "number"},
        },
        "reversibility": {"type": "string", "enum": ["low", "medium", "high"], "description": "How reversible is this decision"},
        "stakes": {"type": "string", "enum": ["low", "medium", "high"], "description": "How high are the stakes"},
        "uncertainty_type": {
            "type": "string",
            "enum": ["missing_info", "outcome_uncertainty", "value_conflict", "mixed"],
            "description": "Primary source of uncertainty",
        },
        "controllability": {"type": "string", "enum": ["low", "medium", "high"], "description": "How much control the decision-maker has"},
        "option_structure": {
            "type": "string",
            "enum": ["choose_existing", "generate_new", "mixed"],
            "description": "Whether options are given or need to be generated",
        },
        "ambiguity_score": {"type": "number", "minimum": 0.0, "maximum": 1.0, "description": "How ambiguous the situation is"},
        "clarification_questions": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "domain_activation", "reversibility", "stakes", "uncertainty_type",
        "controllability", "option_structure", "ambiguity_score", "clarification_questions",
    ],
}


def _llm_interpret(query: str, valid_domains: List[str], llm: LLMPort) -> dict:
    user_msg = f"Valid domains: {valid_domains}\n\nQuery: {query}"
    return llm.ask_structured(
        _INTERPRET_SYSTEM, user_msg,
        schema=_SITUATION_SCHEMA,
        schema_name="situation_analysis",
        max_tokens=512,
    )


# --- Stage 3: Constrained routing policy ---

_AMBIGUITY_THRESHOLD = 0.7


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
        return {}, ScopeStatus.OUT_OF_SCOPE, 0.0

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


def interpret_situation(query: str, twin: TwinState, *, llm: LLMPort) -> Tuple[SituationFrame, ScopeGuardResult]:
    """Run the three-stage Situation Interpreter pipeline."""
    all_domains = [d.value for d in twin.valid_domains()] if hasattr(twin, 'valid_domains') else [d.value for d in DomainEnum]

    # Stage 0: Deterministic scope guard (pre-LLM)
    guard_result = deterministic_scope_guard(query, twin.scope_declaration)

    if guard_result.restricted_hit:
        # Short-circuit: don't even call LLM
        feature_vector = SituationFeatureVector(
            reversibility=OrdinalTriLevel.MEDIUM, stakes=OrdinalTriLevel.HIGH,
            uncertainty_type=UncertaintyType.MIXED, controllability=OrdinalTriLevel.LOW,
            option_structure=OptionStructure.CHOOSE_EXISTING,
        )
        frame = SituationFrame(
            frame_id=str(uuid.uuid4()),
            domain_activation_vector={},
            situation_feature_vector=feature_vector,
            ambiguity_score=1.0,
            scope_status=ScopeStatus.OUT_OF_SCOPE,
            routing_confidence=0.0,
        )
        return frame, guard_result

    # Stage 1: keyword hints
    keyword_hints = _keyword_scores_from_twin(query, twin.domain_heads)

    # Stage 2: LLM interpretation
    llm_result = _llm_interpret(query, all_domains, llm)

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

    ambiguity = min(1.0, max(0.0, float(llm_result.get("ambiguity_score", 0.5))))

    # Stage 3: routing policy
    filtered_activation, scope_status, routing_confidence = _apply_routing_policy(
        raw_activation, ambiguity, twin.scope_declaration, twin
    )

    # Apply non_modeled guard result
    if guard_result.non_modeled_hit and not filtered_activation:
        scope_status = ScopeStatus.OUT_OF_SCOPE
    elif guard_result.non_modeled_hit:
        scope_status = ScopeStatus.BORDERLINE

    # Build feature vector from LLM output
    feature_vector = SituationFeatureVector(
        reversibility=OrdinalTriLevel(llm_result.get("reversibility", "medium")),
        stakes=OrdinalTriLevel(llm_result.get("stakes", "medium")),
        uncertainty_type=UncertaintyType(llm_result.get("uncertainty_type", "mixed")),
        controllability=OrdinalTriLevel(llm_result.get("controllability", "medium")),
        option_structure=OptionStructure(llm_result.get("option_structure", "choose_existing")),
    )

    frame = SituationFrame(
        frame_id=str(uuid.uuid4()),
        domain_activation_vector=filtered_activation,
        situation_feature_vector=feature_vector,
        ambiguity_score=ambiguity,
        clarification_questions=llm_result.get("clarification_questions", []),
        scope_status=scope_status,
        routing_confidence=routing_confidence,
    )
    return frame, guard_result

# src/twin_runtime/application/planner/memory_access_planner.py
"""Memory Access Planner: rule-based evidence scheduling.

Sits between Situation Interpreter and Head Activator in the pipeline.
Inspects SituationFrame signals to decide which RecallQueries to issue,
executes them against the EvidenceStore, and returns retrieved evidence.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from twin_runtime.domain.evidence.base import EvidenceFragment, EvidenceType
from twin_runtime.domain.models.planner import MemoryAccessPlan
from twin_runtime.domain.models.primitives import DomainEnum, OrdinalTriLevel
from twin_runtime.domain.models.recall_query import RecallQuery
from twin_runtime.domain.models.situation import SituationFrame
from twin_runtime.domain.models.twin_state import TwinState
from twin_runtime.domain.ports.evidence_store import EvidenceStore

logger = logging.getLogger(__name__)

_DEFAULT_BUDGET = 10
_DEFAULT_PER_QUERY = 5
_EXPANDED_BUDGET = 20


def _llm_fallback_plan(
    frame: SituationFrame,
    twin: TwinState,
) -> Optional[MemoryAccessPlan]:
    """LLM-based planning fallback for high-ambiguity cases.

    TODO: LLM fallback when ambiguity > 0.7 — rule-based covers 80%+ of cases.
    Deferred to a future phase.
    """
    return None


def _compute_domain_gating(
    frame: SituationFrame,
    twin: TwinState,
) -> Tuple[List[DomainEnum], Dict[DomainEnum, str]]:
    """Decide which domains to activate and which to skip.

    Uses domain_activation_vector weights, twin head availability,
    and head_reliability vs min_reliability_threshold to gate which
    heads should fire.
    """
    active_domains: List[DomainEnum] = []
    skipped: Dict[DomainEnum, str] = {}
    head_map = {h.domain: h for h in twin.domain_heads}
    threshold = twin.scope_declaration.min_reliability_threshold

    for domain, weight in frame.domain_activation_vector.items():
        if weight < 0.1:
            skipped[domain] = f"activation weight {weight:.2f} < 0.10"
        elif domain not in head_map:
            skipped[domain] = f"no head data for {domain.value}"
        elif head_map[domain].head_reliability < threshold:
            rel = head_map[domain].head_reliability
            skipped[domain] = f"reliability {rel:.2f} < {threshold:.2f}"
        else:
            active_domains.append(domain)

    return active_domains, skipped


def plan_memory_access(
    frame: SituationFrame,
    twin: TwinState,
    evidence_store: Optional[EvidenceStore] = None,
) -> Tuple[MemoryAccessPlan, List[EvidenceFragment]]:
    """Plan and execute evidence retrieval for a decision.

    Returns:
        (plan, retrieved_evidence) — the plan for audit + the actual fragments.
        If evidence_store is None or queries are empty, returns empty evidence.
    """
    queries: List[RecallQuery] = []
    rationale_parts: List[str] = []
    budget = _DEFAULT_BUDGET
    freshness = "balanced"
    disabled: List[EvidenceType] = []

    user_id = twin.user_id

    # --- Domain gating ---
    domains_to_activate, skipped_domains = _compute_domain_gating(frame, twin)

    # --- Rule-based decision table ---

    stakes = frame.situation_feature_vector.stakes
    ambiguity = frame.ambiguity_score
    routing_confidence = frame.routing_confidence
    # active_domains from raw frame (includes unmodeled), separate from gating result
    all_activated = [d for d, w in frame.domain_activation_vector.items() if w > 0.1]
    twin_domain_set = {h.domain for h in twin.domain_heads}

    # Rule 1: High stakes + low uncertainty -> verify past decisions
    if stakes == OrdinalTriLevel.HIGH and ambiguity < 0.3:
        queries.append(RecallQuery(
            query_type="decisions_about",
            user_id=user_id,
            decision_topic=frame.frame_id,
            limit=_DEFAULT_PER_QUERY,
        ))
        rationale_parts.append("High stakes + low ambiguity: checking past decision consistency")

    # Rule 2: High ambiguity -> check preferences
    if ambiguity > 0.6:
        queries.append(RecallQuery(
            query_type="preference_on_axis",
            user_id=user_id,
            limit=_DEFAULT_PER_QUERY,
        ))
        rationale_parts.append("High ambiguity: retrieving preference evidence")

    # Rule 3: Multiple domains -> per-domain + cross-domain trajectory
    if len(all_activated) >= 2:
        for domain in all_activated:
            queries.append(RecallQuery(
                query_type="by_domain",
                user_id=user_id,
                target_domain=domain,
                limit=_DEFAULT_PER_QUERY,
            ))
        queries.append(RecallQuery(
            query_type="state_trajectory",
            user_id=user_id,
            limit=_DEFAULT_PER_QUERY,
        ))
        rationale_parts.append(f"Multi-domain ({len(all_activated)}): per-domain + cross-domain trajectory")

    # Rule 4: Unmodeled domain -> rely on reflections
    for domain in all_activated:
        if domain not in twin_domain_set:
            queries.append(RecallQuery(
                query_type="by_evidence_type",
                user_id=user_id,
                target_evidence_type=EvidenceType.REFLECTION,
                limit=_DEFAULT_PER_QUERY,
            ))
            disabled.append(EvidenceType.BEHAVIOR)
            rationale_parts.append(f"Unmodeled domain {domain.value}: using reflections only")
            break  # only add once

    # NOTE: Spec rules "Recurring decision type" (similar_situations) and
    # "Time-sensitive decision" (by_timeline + 30-day limit) are deferred —
    # SituationFrame lacks the signals to detect these reliably.

    # Rule 5: Low routing confidence -> expand budget + broader context
    if routing_confidence < 0.5:
        budget = _EXPANDED_BUDGET
        queries.append(RecallQuery(
            query_type="by_timeline",
            user_id=user_id,
            limit=_DEFAULT_PER_QUERY,
        ))
        rationale_parts.append("Low routing confidence: expanded budget + timeline context")

    # Build the plan
    rationale = "; ".join(rationale_parts) if rationale_parts else "No signals matched — proceeding with TwinState only"

    if evidence_store is None:
        rationale = "No evidence store available — " + rationale.lower()

    plan = MemoryAccessPlan(
        queries=queries,
        execution_strategy="parallel",
        total_evidence_budget=budget,
        per_query_limit=_DEFAULT_PER_QUERY,
        freshness_preference=freshness,
        disabled_evidence_types=disabled,
        rationale=rationale,
        domains_to_activate=domains_to_activate,
        skipped_domains=skipped_domains,
    )

    # --- Execute queries ---
    if not queries or evidence_store is None:
        return plan, []

    all_evidence: List[EvidenceFragment] = []
    for query in queries:
        try:
            results = evidence_store.query(query)
            all_evidence.extend(results)
        except Exception:
            logger.warning("EvidenceStore.query() failed for %s, skipping", query.query_type, exc_info=True)

    # Enforce budget
    if len(all_evidence) > budget:
        all_evidence = all_evidence[:budget]

    return plan, all_evidence

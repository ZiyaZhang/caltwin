"""Persona Compiler: aggregate evidence into TwinState.

Pipeline:
1. Collect EvidenceFragments from all registered sources
2. Classify and deduplicate fragments
3. LLM-assisted extraction of decision parameters
4. Merge extracted parameters into existing TwinState (or create new)
5. Produce versioned TwinState + evidence graph
"""

from __future__ import annotations

import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..models.primitives import DomainEnum
from ..models.twin_state import TwinState
from ..sources.base import EvidenceFragment, EvidenceType
from ..sources.registry import SourceRegistry
from ..runtime.llm_client import ask_json


class EvidenceGraph:
    """Tracks provenance: which evidence supports which TwinState parameters."""

    def __init__(self):
        self.edges: List[Dict[str, Any]] = []

    def add_edge(self, fragment_id: str, parameter_path: str, strength: float = 1.0):
        self.edges.append({
            "fragment_id": fragment_id,
            "parameter_path": parameter_path,
            "strength": strength,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    def to_dict(self) -> List[Dict[str, Any]]:
        return self.edges

    def supports(self, parameter_path: str) -> List[str]:
        """Which fragments support a given parameter?"""
        return [e["fragment_id"] for e in self.edges if e["parameter_path"] == parameter_path]


_EXTRACT_SYSTEM = """You are a persona analysis engine. Given evidence fragments about a person,
extract structured decision-making parameters.

For each fragment, determine:
1. What domain(s) it relates to: work, life_planning, money, relationships, public_expression
2. What decision parameters it reveals (risk_tolerance, conflict_style, etc.)
3. What goal axes matter to this person in each domain
4. Any behavioral patterns or preferences

Output a JSON object:
{
  "domain_signals": {
    "work": {"goal_axes": [...], "patterns": [...], "parameters": {...}},
    ...
  },
  "core_parameters": {
    "risk_tolerance": 0.0-1.0 or null,
    "ambiguity_tolerance": 0.0-1.0 or null,
    "conflict_style": "direct"|"avoidant"|"collaborative"|"competitive"|"accommodating" or null,
    "social_proof_dependence": 0.0-1.0 or null
  },
  "causal_beliefs": {
    "preferred_levers": [...],
    "option_visibility_bias": [...],
    "control_orientation": "internal"|"external"|"mixed" or null
  },
  "confidence": 0.0-1.0
}

Only include fields where the evidence provides signal. Use null for uncertain values."""


class PersonaCompiler:
    """Compile evidence from multiple sources into a TwinState."""

    def __init__(self, registry: SourceRegistry):
        self.registry = registry
        self.evidence_graph = EvidenceGraph()

    def collect_evidence(self, since: Optional[datetime] = None) -> List[EvidenceFragment]:
        """Collect evidence from all registered sources."""
        return self.registry.scan_all(since)

    def extract_parameters(
        self, fragments: List[EvidenceFragment]
    ) -> Dict[str, Any]:
        """LLM-assisted extraction of decision parameters from evidence.

        Groups fragments into batches to avoid exceeding context limits.
        """
        if not fragments:
            return {}

        # Group by evidence type for structured processing
        by_type: Dict[EvidenceType, List[EvidenceFragment]] = {}
        for f in fragments:
            by_type.setdefault(f.evidence_type, []).append(f)

        # Build evidence summary for LLM
        evidence_lines = []
        for f in fragments[:30]:  # Cap at 30 to fit context
            domain_str = f.domain_hint.value if f.domain_hint else "unknown"
            evidence_lines.append(
                f"[{f.evidence_type.value}|{domain_str}|conf={f.confidence:.1f}] "
                f"{f.summary}"
            )
            if f.raw_excerpt:
                excerpt = f.raw_excerpt[:300].replace("\n", " ")
                evidence_lines.append(f"  Excerpt: {excerpt}")

        user_msg = f"""Analyze these {len(evidence_lines)} evidence fragments about a person and extract decision-making parameters:

{chr(10).join(evidence_lines)}"""

        return ask_json(_EXTRACT_SYSTEM, user_msg, max_tokens=1024)

    def compile(
        self,
        existing: Optional[TwinState] = None,
        since: Optional[datetime] = None,
    ) -> tuple[TwinState, EvidenceGraph, List[EvidenceFragment]]:
        """Full compilation: collect → extract → merge.

        Args:
            existing: Existing TwinState to update. None = create from scratch.
            since: Only process evidence newer than this.

        Returns:
            (updated_twin_state, evidence_graph, fragments_used)
        """
        fragments = self.collect_evidence(since)
        if not fragments:
            if existing:
                return existing, self.evidence_graph, []
            # Cold start with no evidence
            twin = self._create_initial(user_id="user-default", fragments=[])
            return twin, self.evidence_graph, []

        extracted = self.extract_parameters(fragments)

        if existing is None:
            twin = self._create_initial(user_id="user-default", fragments=fragments)
            if extracted:
                twin = self._merge_into_existing(twin, extracted, fragments)
            updated = twin
        else:
            updated = self._merge_into_existing(existing, extracted, fragments)

        return updated, self.evidence_graph, fragments

    def _merge_into_existing(
        self,
        twin: TwinState,
        extracted: Dict[str, Any],
        fragments: List[EvidenceFragment],
    ) -> TwinState:
        """Merge extracted parameters into existing TwinState."""
        updated = deepcopy(twin)
        alpha = 0.2  # Conservative learning rate for merge
        now = datetime.now(timezone.utc)

        core_params = extracted.get("core_parameters", {})

        # Update core parameters where we have signal
        if core_params.get("risk_tolerance") is not None:
            old = updated.shared_decision_core.risk_tolerance
            new = float(core_params["risk_tolerance"])
            updated.shared_decision_core.risk_tolerance = round(old * (1 - alpha) + new * alpha, 3)
            self.evidence_graph.add_edge("compiled", "shared_decision_core.risk_tolerance")

        if core_params.get("conflict_style") is not None:
            updated.shared_decision_core.conflict_style = core_params["conflict_style"]
            self.evidence_graph.add_edge("compiled", "shared_decision_core.conflict_style")

        if core_params.get("ambiguity_tolerance") is not None:
            old = updated.shared_decision_core.ambiguity_tolerance
            new = float(core_params["ambiguity_tolerance"])
            updated.shared_decision_core.ambiguity_tolerance = round(old * (1 - alpha) + new * alpha, 3)

        # Update causal beliefs
        causal = extracted.get("causal_beliefs", {})
        if causal.get("preferred_levers"):
            existing_levers = set(updated.causal_belief_model.preferred_levers)
            new_levers = set(causal["preferred_levers"])
            updated.causal_belief_model.preferred_levers = list(existing_levers | new_levers)

        if causal.get("option_visibility_bias"):
            existing_bias = set(updated.causal_belief_model.option_visibility_bias)
            new_bias = set(causal["option_visibility_bias"])
            updated.causal_belief_model.option_visibility_bias = list(existing_bias | new_bias)

        # Update domain heads with new goal axes
        domain_signals = extracted.get("domain_signals", {})
        head_map = {h.domain.value: h for h in updated.domain_heads}
        for domain_str, signals in domain_signals.items():
            head = head_map.get(domain_str)
            if head and signals.get("goal_axes"):
                existing_axes = set(head.goal_axes)
                new_axes = set(signals["goal_axes"])
                # Only add new ones, don't remove existing
                combined = list(existing_axes | new_axes)
                head.goal_axes = combined[:8]  # Cap at 8

        # Bump version and evidence count
        updated.shared_decision_core.evidence_count += len(fragments)
        updated.shared_decision_core.last_recalibrated_at = now

        return updated

    def _create_initial(self, user_id: str = "user-default", fragments: Optional[List] = None) -> TwinState:
        """Create a minimal TwinState for cold start.

        With zero evidence: all parameters at population median, all reliabilities
        below threshold (twin will DEGRADE/REFUSE). With some evidence: set what
        we can, leave the rest at median.
        """
        from twin_runtime.models.twin_state import (
            TwinState, SharedDecisionCore, CausalBeliefModel,
            DomainHead, EvidenceWeightProfile, TransferCoefficient,
            ReliabilityProfileEntry, ScopeDeclaration, TemporalMetadata,
            RejectionPolicyMap,
        )
        from twin_runtime.models.primitives import (
            DomainEnum, ConflictStyle, ControlOrientation,
            MergeStrategy, ReliabilityScopeStatus,
        )

        now = datetime.now(timezone.utc)

        all_domains = [
            DomainEnum.WORK, DomainEnum.LIFE_PLANNING, DomainEnum.MONEY,
            DomainEnum.RELATIONSHIPS, DomainEnum.PUBLIC_EXPRESSION,
        ]
        domain_heads = []
        for domain in all_domains:
            domain_heads.append(DomainHead(
                domain=domain,
                head_version="v000",
                goal_axes=["unknown"],
                default_priority_order=["unknown"],
                evidence_weight_profile=EvidenceWeightProfile(
                    self_report_weight=0.5,
                    historical_behavior_weight=0.5,
                    recent_behavior_weight=0.5,
                    outcome_feedback_weight=0.5,
                    weight_confidence=0.2,
                ),
                head_reliability=0.3,
                supported_task_types=["general"],
                last_recalibrated_at=now,
            ))

        twin = TwinState(
            id=f"twin-{user_id}",
            created_at=now,
            user_id=user_id,
            state_version="v000-cold-start",
            active=True,
            shared_decision_core=SharedDecisionCore(
                risk_tolerance=0.5,
                ambiguity_tolerance=0.5,
                action_threshold=0.5,
                information_threshold=0.5,
                reversibility_preference=0.5,
                regret_sensitivity=0.5,
                explore_exploit_balance=0.5,
                conflict_style=ConflictStyle.ADAPTIVE,
                decision_latency_hours_p50=None,
                social_proof_dependence=None,
                evidence_count=len(fragments) if fragments else 0,
                core_confidence=0.2,
                last_recalibrated_at=now,
            ),
            causal_belief_model=CausalBeliefModel(
                control_orientation=ControlOrientation.MIXED,
                effort_vs_system_weight=0.0,
                relationship_model=None,
                change_strategy=None,
                preferred_levers=[],
                ignored_levers=[],
                option_visibility_bias=[],
                causal_confidence=0.2,
                anchor_cases=[],
            ),
            domain_heads=domain_heads,
            transfer_coefficients=[],
            reliability_profile=[
                ReliabilityProfileEntry(
                    domain=d,
                    task_type="general",
                    reliability_score=0.3,
                    uncertainty_band="0.1-0.5",
                    evidence_strength=0.2,
                    scope_status=ReliabilityScopeStatus.WEAKLY_MODELED,
                    last_updated_at=now,
                )
                for d in all_domains
            ],
            scope_declaration=ScopeDeclaration(
                modeled_capabilities=[],
                non_modeled_capabilities=["all — cold start, no evidence yet"],
                restricted_use_cases=["financial advice", "medical decisions", "legal counsel"],
                min_reliability_threshold=0.5,
                rejection_policy=RejectionPolicyMap(
                    out_of_scope=MergeStrategy.REFUSE,
                    borderline=MergeStrategy.DEGRADE,
                ),
                user_facing_summary="This twin has minimal data. Most decisions will be declined until more evidence is collected.",
            ),
            temporal_metadata=TemporalMetadata(
                state_valid_from=now,
                fast_variables=["core_confidence"],
                slow_variables=["risk_tolerance", "conflict_style"],
                irreversible_shifts=[],
                major_life_events=[],
            ),
        )
        return twin

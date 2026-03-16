"""Typed EvidenceFragment subclasses.

Each subclass captures type-specific structured fields instead of relying
on the untyped `structured_data` dict. The base class EvidenceFragment
remains for backward compatibility; adapters should migrate to these.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Literal, Optional

from pydantic import Field

from twin_runtime.domain.evidence.base import EvidenceFragment, EvidenceType
from twin_runtime.domain.models.primitives import DomainEnum, OrdinalTriLevel


class DecisionEvidence(EvidenceFragment):
    """User made or described a decision."""

    evidence_type: Literal[EvidenceType.DECISION] = EvidenceType.DECISION
    option_set: List[str] = Field(default_factory=list)
    chosen: str = ""
    reasoning: Optional[str] = None
    stakes: Optional[OrdinalTriLevel] = None
    outcome_known: bool = False

    def _compute_content_hash(self) -> str:
        parts = [
            self.evidence_type.value,
            self.domain_hint.value if self.domain_hint else "",
            "|".join(sorted(self.option_set)),
            self.chosen,
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


class PreferenceEvidence(EvidenceFragment):
    """User expressed a preference along some dimension."""

    evidence_type: Literal[EvidenceType.PREFERENCE] = EvidenceType.PREFERENCE
    dimension: str = ""
    direction: str = ""
    strength: float = Field(default=0.5, ge=0.0, le=1.0)
    preference_context: Optional[str] = None

    def _compute_content_hash(self) -> str:
        parts = [
            self.evidence_type.value,
            self.domain_hint.value if self.domain_hint else "",
            self.dimension,
            self.direction,
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


class BehaviorEvidence(EvidenceFragment):
    """Observed behavioral pattern."""

    evidence_type: Literal[EvidenceType.BEHAVIOR] = EvidenceType.BEHAVIOR
    action_type: str = ""
    pattern: str = ""
    frequency: Optional[str] = None
    structured_metrics: Dict[str, Any] = Field(default_factory=dict)

    def _compute_content_hash(self) -> str:
        parts = [
            self.evidence_type.value,
            self.domain_hint.value if self.domain_hint else "",
            self.action_type,
            self.pattern[:100],
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


class ReflectionEvidence(EvidenceFragment):
    """User's self-reflection or retrospective."""

    evidence_type: Literal[EvidenceType.REFLECTION] = EvidenceType.REFLECTION
    topic: str = ""
    sentiment: Optional[str] = None
    insight: str = ""
    references_decision: Optional[str] = None

    def _compute_content_hash(self) -> str:
        parts = [
            self.evidence_type.value,
            self.domain_hint.value if self.domain_hint else "",
            self.topic,
            self.insight[:100],
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


class InteractionStyleEvidence(EvidenceFragment):
    """How the user communicates and collaborates."""

    evidence_type: Literal[EvidenceType.INTERACTION_STYLE] = EvidenceType.INTERACTION_STYLE
    style_markers: List[str] = Field(default_factory=list)
    style_context: str = ""

    def _compute_content_hash(self) -> str:
        parts = [
            self.evidence_type.value,
            "|".join(sorted(self.style_markers)),
            self.style_context,
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


class ContextEvidence(EvidenceFragment):
    """Background context: role, environment, tools, relationships."""

    evidence_type: Literal[EvidenceType.CONTEXT] = EvidenceType.CONTEXT
    context_category: str = ""
    description: str = ""

    def _compute_content_hash(self) -> str:
        parts = [
            self.evidence_type.value,
            self.domain_hint.value if self.domain_hint else "",
            self.context_category,
            self.description[:100],
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def migrate_fragment(legacy: EvidenceFragment) -> EvidenceFragment:
    """Convert a legacy flat EvidenceFragment to a typed subclass.

    Best-effort migration: maps structured_data fields to typed fields where possible.
    Falls back to ContextEvidence if mapping is unclear.
    """
    base_kwargs = dict(
        fragment_id=legacy.fragment_id,
        user_id=getattr(legacy, "user_id", "user-default"),
        source_type=legacy.source_type,
        source_id=legacy.source_id,
        occurred_at=legacy.occurred_at,
        valid_from=legacy.valid_from,
        valid_until=legacy.valid_until,
        domain_hint=legacy.domain_hint,
        summary=legacy.summary,
        raw_excerpt=legacy.raw_excerpt,
        confidence=legacy.confidence,
        stakes=legacy.stakes,
        temporal_weight=legacy.temporal_weight,
        extraction_method=legacy.extraction_method,
    )
    sd = legacy.structured_data

    if legacy.evidence_type == EvidenceType.DECISION:
        return DecisionEvidence(
            **base_kwargs,
            option_set=sd.get("option_set", []),
            chosen=sd.get("chosen", sd.get("choice", "")),
            reasoning=sd.get("reasoning"),
            outcome_known=sd.get("outcome_known", False),
        )
    elif legacy.evidence_type == EvidenceType.PREFERENCE:
        return PreferenceEvidence(
            **base_kwargs,
            dimension=sd.get("dimension", ""),
            direction=sd.get("direction", ""),
            strength=sd.get("strength", 0.5),
            preference_context=sd.get("context"),
        )
    elif legacy.evidence_type == EvidenceType.BEHAVIOR:
        return BehaviorEvidence(
            **base_kwargs,
            action_type=sd.get("action_type", sd.get("type", "")),
            pattern=sd.get("pattern", legacy.summary),
            frequency=sd.get("frequency"),
            structured_metrics={k: v for k, v in sd.items()
                                if k not in ("action_type", "type", "pattern", "frequency")},
        )
    elif legacy.evidence_type == EvidenceType.REFLECTION:
        return ReflectionEvidence(
            **base_kwargs,
            topic=sd.get("topic", ""),
            sentiment=sd.get("sentiment"),
            insight=sd.get("insight", legacy.summary),
            references_decision=sd.get("references_decision"),
        )
    elif legacy.evidence_type == EvidenceType.INTERACTION_STYLE:
        return InteractionStyleEvidence(
            **base_kwargs,
            style_markers=sd.get("style_markers", []),
            style_context=sd.get("context", ""),
        )
    else:
        # CONTEXT or unknown — use ContextEvidence
        return ContextEvidence(
            **base_kwargs,
            context_category=sd.get("context_category", sd.get("type", "")),
            description=sd.get("description", legacy.summary),
            structured_data=sd,
        )

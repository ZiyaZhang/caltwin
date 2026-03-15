# Phase 1: Evidence Foundation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the evidence layer from flat `EvidenceFragment` with untyped `structured_data` to typed subclasses with temporal semantics, content hashing, dedup clustering, and cold-start support.

**Architecture:** Typed evidence subclasses (DecisionEvidence, PreferenceEvidence, etc.) extend the existing EvidenceFragment base class. The base class gains `user_id`, temporal triple (`occurred_at`/`valid_from`/`valid_until`), and `content_hash`. A migration function converts legacy fragments. All existing adapters are updated to produce typed fragments. PersonaCompiler gains cold-start path and typed fragment consumption.

**Tech Stack:** Python 3.9+, Pydantic v2, hashlib (stdlib), existing test infrastructure (pytest)

**Spec:** `docs/superpowers/specs/2026-03-16-twin-runtime-evolution-design.md` — Dimension 1

---

## Chunk 1: Typed Evidence Fragments

### Task 1: Add base class fields (user_id, temporal triple, content_hash)

**Files:**
- Modify: `src/twin_runtime/sources/base.py`
- Modify: `tests/test_sources.py`

- [ ] **Step 1: Write failing tests for new base fields**

```python
# Add to tests/test_sources.py, in class TestEvidenceFragment

def test_fragment_temporal_fields(self):
    now = datetime.now(timezone.utc)
    f = EvidenceFragment(
        source_type="test",
        source_id="t-1",
        evidence_type=EvidenceType.PREFERENCE,
        occurred_at=now,
        valid_from=now,
        summary="Test",
        confidence=0.8,
        user_id="user-test",
    )
    assert f.occurred_at == now
    assert f.valid_from == now
    assert f.valid_until is None
    assert f.user_id == "user-test"

def test_fragment_backward_compat_timestamp(self):
    """Legacy 'timestamp' field should still work via occurred_at."""
    now = datetime.now(timezone.utc)
    f = EvidenceFragment(
        source_type="test",
        source_id="t-1",
        evidence_type=EvidenceType.PREFERENCE,
        occurred_at=now,
        valid_from=now,
        summary="Test",
        confidence=0.8,
        user_id="user-default",
    )
    assert f.occurred_at == now

def test_fragment_content_hash_populated(self):
    f = EvidenceFragment(
        source_type="test",
        source_id="t-1",
        evidence_type=EvidenceType.PREFERENCE,
        occurred_at=datetime.now(timezone.utc),
        valid_from=datetime.now(timezone.utc),
        summary="Test preference",
        confidence=0.8,
        user_id="user-test",
    )
    assert isinstance(f.content_hash, str)
    assert len(f.content_hash) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_sources.py::TestEvidenceFragment::test_fragment_temporal_fields tests/test_sources.py::TestEvidenceFragment::test_fragment_backward_compat_timestamp tests/test_sources.py::TestEvidenceFragment::test_fragment_content_hash_populated -v`
Expected: FAIL — fields `occurred_at`, `valid_from`, `user_id`, `content_hash` don't exist

- [ ] **Step 3: Update EvidenceFragment base class**

In `src/twin_runtime/sources/base.py`, replace the existing `EvidenceFragment` class:

```python
import hashlib

class EvidenceFragment(BaseModel):
    """Atomic unit of evidence extracted from any data source.

    This is the universal interface between source adapters and the persona compiler.
    """

    fragment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = Field(default="user-default", description="Owner user ID for multi-user isolation")
    source_type: str = Field(description="Adapter that produced this: 'openclaw', 'notion', 'gmail', etc.")
    source_id: str = Field(description="Unique ID within the source (file path, message ID, page ID, etc.)")
    evidence_type: EvidenceType

    # Temporal triple
    occurred_at: datetime = Field(description="When the event happened")
    valid_from: datetime = Field(description="When this evidence starts being relevant")
    valid_until: Optional[datetime] = Field(
        default=None,
        description="When this evidence stops being relevant (None = still valid)"
    )

    domain_hint: Optional[DomainEnum] = Field(
        default=None,
        description="Domain this evidence likely belongs to. None = let compiler decide."
    )

    # Content
    summary: str = Field(description="Short summary of what this evidence tells us about the user.")
    raw_excerpt: Optional[str] = Field(
        default=None,
        description="Verbatim excerpt from the source. May be truncated."
    )
    structured_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured extraction. Prefer typed subclass fields over this."
    )

    # Quality signals
    confidence: float = confidence_field(
        description="How confident we are this evidence is accurate and relevant."
    )
    stakes: Optional[OrdinalTriLevel] = None
    temporal_weight: float = Field(
        default=1.0, ge=0.0, le=2.0,
        description="Time-decay weight. Recent evidence > old evidence."
    )

    # Provenance
    extraction_method: str = Field(
        default="manual",
        description="How this was extracted: 'manual', 'llm_extraction', 'rule_based', 'api_structured'."
    )

    # Dedup
    content_hash: str = Field(
        default="",
        description="Semantic fingerprint for cross-source dedup. Auto-computed if empty."
    )

    def model_post_init(self, __context: Any) -> None:
        if not self.content_hash:
            self.content_hash = self._compute_content_hash()

    def _compute_content_hash(self) -> str:
        """Compute semantic fingerprint. Subclasses override for type-specific hashing."""
        parts = [
            self.evidence_type.value,
            self.domain_hint.value if self.domain_hint else "",
            self.summary[:100],
        ]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
```

- [ ] **Step 4: Fix existing tests that use old `timestamp` field**

All existing tests and adapters use `timestamp=...`. We need to keep backward compatibility. Add a `@model_validator` that maps `timestamp` → `occurred_at` + `valid_from`:

```python
    @model_validator(mode="before")
    @classmethod
    def _migrate_timestamp(cls, data: Any) -> Any:
        if isinstance(data, dict) and "timestamp" in data and "occurred_at" not in data:
            data["occurred_at"] = data.pop("timestamp")
            if "valid_from" not in data:
                data["valid_from"] = data["occurred_at"]
        return data
```

- [ ] **Step 5: Run ALL existing tests to verify nothing breaks**

Run: `python3 -m pytest tests/ --ignore=tests/test_pipeline_integration.py --ignore=tests/test_full_cycle.py -v`
Expected: ALL PASS (86+ tests). The `timestamp` → `occurred_at` migration validator ensures backward compatibility.

- [ ] **Step 6: Commit**

```bash
git add src/twin_runtime/sources/base.py tests/test_sources.py
git commit -m "feat: add user_id, temporal triple, content_hash to EvidenceFragment"
```

---

### Task 2: Typed evidence subclasses

**Files:**
- Create: `src/twin_runtime/sources/evidence_types.py`
- Create: `tests/test_evidence_types.py`
- Modify: `src/twin_runtime/sources/__init__.py`

- [ ] **Step 1: Write failing tests for all typed subclasses**

```python
# tests/test_evidence_types.py
"""Tests for typed EvidenceFragment subclasses."""

from datetime import datetime, timezone

import pytest

from twin_runtime.sources.base import EvidenceType
from twin_runtime.sources.evidence_types import (
    BehaviorEvidence,
    ContextEvidence,
    DecisionEvidence,
    InteractionStyleEvidence,
    PreferenceEvidence,
    ReflectionEvidence,
)
from twin_runtime.models.primitives import DomainEnum, OrdinalTriLevel


NOW = datetime.now(timezone.utc)
BASE = dict(
    source_type="test",
    source_id="t-1",
    occurred_at=NOW,
    valid_from=NOW,
    summary="Test",
    confidence=0.8,
    user_id="user-test",
)


class TestDecisionEvidence:
    def test_create(self):
        d = DecisionEvidence(
            **BASE,
            option_set=["A", "B", "C"],
            chosen="A",
            reasoning="A has lower risk",
            stakes=OrdinalTriLevel.HIGH,
        )
        assert d.evidence_type == EvidenceType.DECISION
        assert d.chosen == "A"
        assert d.option_set == ["A", "B", "C"]
        assert d.outcome_known is False

    def test_content_hash_stable(self):
        """Same decision from different sources should produce same hash."""
        d1 = DecisionEvidence(
            **BASE,
            source_type="gmail",
            option_set=["A", "B"],
            chosen="A",
        )
        d2 = DecisionEvidence(
            **BASE,
            source_type="notion",
            source_id="t-2",
            option_set=["A", "B"],
            chosen="A",
        )
        assert d1.content_hash == d2.content_hash

    def test_content_hash_differs_for_different_choice(self):
        d1 = DecisionEvidence(**BASE, option_set=["A", "B"], chosen="A")
        d2 = DecisionEvidence(**BASE, option_set=["A", "B"], chosen="B")
        assert d1.content_hash != d2.content_hash


class TestPreferenceEvidence:
    def test_create(self):
        p = PreferenceEvidence(
            **BASE,
            dimension="risk_tolerance",
            direction="prefers_low",
            strength=0.8,
        )
        assert p.evidence_type == EvidenceType.PREFERENCE
        assert p.dimension == "risk_tolerance"
        assert p.strength == 0.8

    def test_content_hash_stable(self):
        p1 = PreferenceEvidence(
            **BASE, source_type="gmail",
            dimension="risk", direction="low", strength=0.8,
        )
        p2 = PreferenceEvidence(
            **BASE, source_type="notion",
            dimension="risk", direction="low", strength=0.5,
        )
        # Same dimension+direction = same hash (strength excluded)
        assert p1.content_hash == p2.content_hash


class TestBehaviorEvidence:
    def test_create(self):
        b = BehaviorEvidence(
            **BASE,
            action_type="meeting_pattern",
            pattern="Prefers morning meetings",
        )
        assert b.evidence_type == EvidenceType.BEHAVIOR
        assert b.action_type == "meeting_pattern"

    def test_structured_metrics(self):
        b = BehaviorEvidence(
            **BASE,
            action_type="calendar",
            pattern="Weekly patterns",
            structured_metrics={"avg_duration": 45, "count": 12},
        )
        assert b.structured_metrics["avg_duration"] == 45


class TestReflectionEvidence:
    def test_create(self):
        r = ReflectionEvidence(
            **BASE,
            topic="career choice",
            sentiment="negative",
            insight="I regret choosing Tencent over MiniMax",
        )
        assert r.evidence_type == EvidenceType.REFLECTION
        assert r.sentiment == "negative"

    def test_references_decision(self):
        r = ReflectionEvidence(
            **BASE,
            topic="career",
            insight="Should have stayed",
            references_decision="decision-123",
        )
        assert r.references_decision == "decision-123"


class TestInteractionStyleEvidence:
    def test_create(self):
        s = InteractionStyleEvidence(
            **BASE,
            style_markers=["direct", "concise"],
            style_context="in emails",
        )
        assert s.evidence_type == EvidenceType.INTERACTION_STYLE
        assert "direct" in s.style_markers


class TestContextEvidence:
    def test_create(self):
        c = ContextEvidence(
            **BASE,
            context_category="role",
            description="Product manager trainee at Tencent",
        )
        assert c.evidence_type == EvidenceType.CONTEXT
        assert c.context_category == "role"

    def test_flexible_structured_data(self):
        c = ContextEvidence(
            **BASE,
            context_category="tools",
            description="Uses NotebookLM and Claude Code",
            structured_data={"tools": ["notebooklm", "claude_code"]},
        )
        assert "notebooklm" in c.structured_data["tools"]


class TestMigrateLegacyFragment:
    def test_migrate_flat_decision(self):
        from twin_runtime.sources.evidence_types import migrate_fragment
        from twin_runtime.sources.base import EvidenceFragment

        legacy = EvidenceFragment(
            source_type="gmail",
            source_id="msg-1",
            evidence_type=EvidenceType.DECISION,
            timestamp=NOW,
            summary="Chose option A",
            structured_data={
                "message_id": "msg-1",
                "subject": "Re: project decision",
                "needs_llm_analysis": True,
            },
            confidence=0.6,
        )
        typed = migrate_fragment(legacy)
        assert isinstance(typed, DecisionEvidence)
        assert typed.occurred_at == NOW
        assert typed.user_id == "user-default"

    def test_migrate_flat_behavior(self):
        from twin_runtime.sources.evidence_types import migrate_fragment
        from twin_runtime.sources.base import EvidenceFragment

        legacy = EvidenceFragment(
            source_type="calendar",
            source_id="cal-1",
            evidence_type=EvidenceType.BEHAVIOR,
            timestamp=NOW,
            summary="Calendar patterns",
            structured_data={"total_events": 50, "avg_duration_minutes": 45},
            confidence=0.7,
        )
        typed = migrate_fragment(legacy)
        assert isinstance(typed, BehaviorEvidence)
        assert typed.structured_metrics.get("total_events") == 50

    def test_migrate_unknown_falls_back_to_context(self):
        from twin_runtime.sources.evidence_types import migrate_fragment
        from twin_runtime.sources.base import EvidenceFragment

        legacy = EvidenceFragment(
            source_type="unknown",
            source_id="x-1",
            evidence_type=EvidenceType.CONTEXT,
            timestamp=NOW,
            summary="Something",
            confidence=0.5,
        )
        typed = migrate_fragment(legacy)
        assert isinstance(typed, ContextEvidence)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_evidence_types.py -v`
Expected: FAIL — `twin_runtime.sources.evidence_types` does not exist

- [ ] **Step 3: Implement typed subclasses and migration function**

```python
# src/twin_runtime/sources/evidence_types.py
"""Typed EvidenceFragment subclasses.

Each subclass captures type-specific structured fields instead of relying
on the untyped `structured_data` dict. The base class EvidenceFragment
remains for backward compatibility; adapters should migrate to these.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Literal, Optional

from pydantic import Field

from .base import EvidenceFragment, EvidenceType
from ..models.primitives import DomainEnum, OrdinalTriLevel


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
```

- [ ] **Step 4: Update `__init__.py` exports**

Add to `src/twin_runtime/sources/__init__.py`:

```python
from .evidence_types import (
    DecisionEvidence, PreferenceEvidence, BehaviorEvidence,
    ReflectionEvidence, InteractionStyleEvidence, ContextEvidence,
    migrate_fragment,
)
```

And update `__all__` to include them.

- [ ] **Step 5: Run all tests**

Run: `python3 -m pytest tests/test_evidence_types.py tests/test_sources.py tests/test_google_sources.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/twin_runtime/sources/evidence_types.py src/twin_runtime/sources/__init__.py tests/test_evidence_types.py
git commit -m "feat: typed EvidenceFragment subclasses with content hashing and migration"
```

---

### Task 3: Evidence clustering (dedup)

**Files:**
- Create: `src/twin_runtime/sources/clustering.py`
- Create: `tests/test_clustering.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_clustering.py
"""Tests for evidence deduplication and clustering."""

from datetime import datetime, timezone

import pytest

from twin_runtime.sources.evidence_types import DecisionEvidence, BehaviorEvidence
from twin_runtime.sources.clustering import deduplicate, EvidenceCluster


NOW = datetime.now(timezone.utc)


def _make_decision(source_type: str, source_id: str, confidence: float = 0.6):
    return DecisionEvidence(
        source_type=source_type,
        source_id=source_id,
        occurred_at=NOW,
        valid_from=NOW,
        summary="Chose option A",
        confidence=confidence,
        user_id="user-test",
        option_set=["A", "B"],
        chosen="A",
    )


class TestDeduplicate:
    def test_no_duplicates(self):
        d1 = _make_decision("gmail", "g-1")
        b1 = BehaviorEvidence(
            source_type="calendar", source_id="c-1",
            occurred_at=NOW, valid_from=NOW,
            summary="Meeting pattern", confidence=0.7,
            user_id="user-test",
            action_type="meeting", pattern="weekly standup",
        )
        result = deduplicate([d1, b1])
        # No duplicates — both returned as-is
        assert len(result) == 2
        assert all(not isinstance(r, EvidenceCluster) for r in result)

    def test_duplicates_clustered(self):
        d1 = _make_decision("gmail", "g-1", confidence=0.6)
        d2 = _make_decision("notion", "n-1", confidence=0.8)
        result = deduplicate([d1, d2])
        assert len(result) == 1
        cluster = result[0]
        assert isinstance(cluster, EvidenceCluster)
        assert cluster.merged_confidence > max(d1.confidence, d2.confidence)
        assert len(cluster.source_types) == 2
        assert "gmail" in cluster.source_types
        assert "notion" in cluster.source_types

    def test_cluster_canonical_is_highest_confidence(self):
        d1 = _make_decision("gmail", "g-1", confidence=0.5)
        d2 = _make_decision("notion", "n-1", confidence=0.9)
        result = deduplicate([d1, d2])
        cluster = result[0]
        assert cluster.canonical_fragment.source_type == "notion"

    def test_three_way_merge(self):
        d1 = _make_decision("gmail", "g-1", confidence=0.5)
        d2 = _make_decision("notion", "n-1", confidence=0.7)
        d3 = _make_decision("calendar", "c-1", confidence=0.6)
        result = deduplicate([d1, d2, d3])
        assert len(result) == 1
        cluster = result[0]
        assert len(cluster.supporting_fragments) == 2
        assert len(cluster.source_types) == 3

    def test_mixed_duplicates_and_uniques(self):
        d1 = _make_decision("gmail", "g-1")
        d2 = _make_decision("notion", "n-1")
        b1 = BehaviorEvidence(
            source_type="calendar", source_id="c-1",
            occurred_at=NOW, valid_from=NOW,
            summary="Pattern", confidence=0.7,
            user_id="user-test",
            action_type="meeting", pattern="weekly",
        )
        result = deduplicate([d1, d2, b1])
        assert len(result) == 2  # 1 cluster + 1 standalone
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_clustering.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement clustering**

```python
# src/twin_runtime/sources/clustering.py
"""Evidence deduplication and clustering.

Groups EvidenceFragments with the same content_hash into EvidenceClusters.
Multi-source corroboration boosts confidence.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any, Dict, List, Union

from pydantic import BaseModel, Field

from .base import EvidenceFragment


class EvidenceCluster(BaseModel):
    """Multiple fragments describing the same underlying event."""

    cluster_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    canonical_fragment: EvidenceFragment
    supporting_fragments: List[EvidenceFragment] = Field(default_factory=list)
    source_types: List[str] = Field(default_factory=list)
    merged_confidence: float = 0.0


def deduplicate(
    fragments: List[EvidenceFragment],
    confidence_boost_per_source: float = 0.05,
) -> List[Union[EvidenceFragment, EvidenceCluster]]:
    """Group fragments by content_hash. Singletons pass through; duplicates become clusters.

    Args:
        fragments: List of evidence fragments (may include typed subclasses)
        confidence_boost_per_source: Confidence boost per additional corroborating source

    Returns:
        List of EvidenceFragment (unique) and EvidenceCluster (deduplicated groups)
    """
    by_hash: Dict[str, List[EvidenceFragment]] = defaultdict(list)
    for f in fragments:
        by_hash[f.content_hash].append(f)

    result: List[Union[EvidenceFragment, EvidenceCluster]] = []
    for content_hash, group in by_hash.items():
        if len(group) == 1:
            result.append(group[0])
        else:
            # Sort by confidence descending — highest becomes canonical
            group.sort(key=lambda f: f.confidence, reverse=True)
            canonical = group[0]
            supporting = group[1:]
            source_types = list({f.source_type for f in group})
            # Boost: base confidence + small bump per additional source
            boost = confidence_boost_per_source * (len(source_types) - 1)
            merged_confidence = min(1.0, canonical.confidence + boost)

            result.append(EvidenceCluster(
                canonical_fragment=canonical,
                supporting_fragments=supporting,
                source_types=source_types,
                merged_confidence=merged_confidence,
            ))

    return result
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_clustering.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/sources/clustering.py tests/test_clustering.py
git commit -m "feat: evidence deduplication and clustering by content_hash"
```

---

## Chunk 2: Adapter Migration + Compiler Upgrade

### Task 4: Migrate GmailAdapter to produce DecisionEvidence

**Files:**
- Modify: `src/twin_runtime/sources/gmail_adapter.py`
- Modify: `tests/test_google_sources.py`

- [ ] **Step 1: Write failing test for typed output**

Add to `tests/test_google_sources.py` in `TestGmailAdapter`:

```python
def test_scan_returns_typed_decision_evidence(self, mock_service):
    # (Same mock setup as existing test_scan_returns_fragments)
    mock_svc = MagicMock()
    mock_service.return_value = mock_svc
    mock_svc.users().messages().list().execute.return_value = {
        "messages": [{"id": "msg-001"}]
    }
    mock_svc.users().messages().get().execute.return_value = {
        "id": "msg-001",
        "snippet": "I decided to go with option A for the project",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Re: Project decision"},
                {"name": "Date", "value": "Thu, 13 Mar 2026 10:30:00 +0800"},
                {"name": "To", "value": "team@example.com"},
            ]
        }
    }
    adapter = GmailAdapter()
    adapter._service = mock_svc
    fragments = adapter.scan()
    assert len(fragments) == 1

    from twin_runtime.sources.evidence_types import DecisionEvidence
    assert isinstance(fragments[0], DecisionEvidence)
    assert fragments[0].occurred_at is not None
    assert fragments[0].valid_from is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_google_sources.py::TestGmailAdapter::test_scan_returns_typed_decision_evidence -v`
Expected: FAIL — fragment is plain EvidenceFragment, not DecisionEvidence

- [ ] **Step 3: Update GmailAdapter._process_message()**

In `src/twin_runtime/sources/gmail_adapter.py`, change the return in `_process_message()` from `EvidenceFragment(...)` to:

```python
from twin_runtime.sources.evidence_types import DecisionEvidence

# Replace the return EvidenceFragment(...) block with:
return DecisionEvidence(
    source_type=self.source_type,
    source_id=f"gmail:{msg_id}",
    occurred_at=timestamp,
    valid_from=timestamp,
    summary=f"Email: {subject[:100]}",
    raw_excerpt=body_excerpt if body_excerpt else snippet[:500],
    confidence=0.6,
    extraction_method="rule_based",
    user_id="user-default",
    # Typed fields
    option_set=[],  # Not extractable from email metadata alone
    chosen="",
    reasoning=snippet[:200],
    structured_data={
        "message_id": msg_id,
        "subject": subject,
        "to": to_addr,
        "snippet": snippet[:200],
        "needs_llm_analysis": True,
    },
)
```

- [ ] **Step 4: Run all Gmail tests**

Run: `python3 -m pytest tests/test_google_sources.py::TestGmailAdapter -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/sources/gmail_adapter.py tests/test_google_sources.py
git commit -m "feat: GmailAdapter produces typed DecisionEvidence"
```

---

### Task 5: Migrate CalendarAdapter to produce BehaviorEvidence

**Files:**
- Modify: `src/twin_runtime/sources/calendar_adapter.py`
- Modify: `tests/test_google_sources.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_google_sources.py` in `TestCalendarAdapter`:

```python
def test_scan_returns_typed_behavior_evidence(self, mock_service):
    mock_svc = MagicMock()
    mock_service.return_value = mock_svc
    mock_svc.events().list().execute.return_value = {
        "items": [
            {
                "id": "evt-001",
                "summary": "Sprint planning meeting",
                "start": {"dateTime": "2026-03-15T10:00:00+08:00"},
                "end": {"dateTime": "2026-03-15T11:00:00+08:00"},
                "attendees": [{"email": "a@b.com"}],
            },
        ] + [
            {
                "id": f"evt-{i}",
                "summary": f"Meeting {i}",
                "start": {"dateTime": f"2026-03-{10+i:02d}T10:00:00+08:00"},
                "end": {"dateTime": f"2026-03-{10+i:02d}T11:00:00+08:00"},
            } for i in range(2, 10)
        ]
    }
    adapter = CalendarAdapter()
    adapter._service = mock_svc
    fragments = adapter.scan()

    from twin_runtime.sources.evidence_types import BehaviorEvidence
    for f in fragments:
        assert isinstance(f, BehaviorEvidence)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_google_sources.py::TestCalendarAdapter::test_scan_returns_typed_behavior_evidence -v`
Expected: FAIL

- [ ] **Step 3: Update CalendarAdapter to produce typed fragments**

In `src/twin_runtime/sources/calendar_adapter.py`, update `_process_event()` and `_extract_patterns()` to return `BehaviorEvidence` instead of `EvidenceFragment`:

```python
from twin_runtime.sources.evidence_types import BehaviorEvidence

# In _process_event(), replace return EvidenceFragment(...) with:
return BehaviorEvidence(
    source_type=self.source_type,
    source_id=f"calendar:{event.get('id', '')}",
    occurred_at=start,
    valid_from=start,
    summary=f"Calendar: {summary[:100]}",
    confidence=0.5,
    extraction_method="api_structured",
    user_id="user-default",
    action_type="calendar_event",
    pattern=summary,
    structured_metrics={
        "event_id": event.get("id", ""),
        "summary": summary,
        "attendee_count": len(attendees),
        "duration_minutes": self._event_duration(event),
        "is_recurring": event.get("recurringEventId") is not None,
    },
)

# In _extract_patterns(), replace return EvidenceFragment(...) with:
return BehaviorEvidence(
    source_type=self.source_type,
    source_id="calendar:patterns",
    occurred_at=datetime.now(timezone.utc),
    valid_from=datetime.now(timezone.utc) - timedelta(days=self._lookback_days),
    summary=f"Calendar patterns: {total} events over {self._lookback_days} days",
    confidence=0.7,
    extraction_method="rule_based",
    user_id="user-default",
    action_type="calendar_patterns",
    pattern=f"{total} events, avg {avg_duration:.0f}min, busiest: {patterns['busiest_day']}",
    structured_metrics=patterns,
)
```

- [ ] **Step 4: Run all Calendar tests**

Run: `python3 -m pytest tests/test_google_sources.py::TestCalendarAdapter -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/sources/calendar_adapter.py tests/test_google_sources.py
git commit -m "feat: CalendarAdapter produces typed BehaviorEvidence"
```

---

### Task 6: Migrate OpenClawAdapter to produce typed fragments

**Files:**
- Modify: `src/twin_runtime/sources/openclaw_adapter.py`
- Modify: `tests/test_sources.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_sources.py` in `TestOpenClawAdapter`:

```python
def test_scan_returns_typed_fragments(self, tmp_path):
    from twin_runtime.sources.evidence_types import ContextEvidence, PreferenceEvidence
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "CLAUDE.md").write_text("# Project instructions\nUse Python 3.9+")
    adapter = OpenClawAdapter(str(ws))
    fragments = adapter.scan()
    assert len(fragments) >= 1
    # CLAUDE.md should produce ContextEvidence
    claude_frags = [f for f in fragments if "CLAUDE" in f.source_id or "claude" in f.source_id.lower()]
    assert len(claude_frags) >= 1
    assert isinstance(claude_frags[0], ContextEvidence)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_sources.py::TestOpenClawAdapter::test_scan_returns_typed_fragments -v`
Expected: FAIL

- [ ] **Step 3: Update OpenClawAdapter**

In `src/twin_runtime/sources/openclaw_adapter.py`, update all `EvidenceFragment(...)` calls:

- CLAUDE.md → `ContextEvidence(context_category="project_instructions", description=...)`
- Memory files → `ContextEvidence` or `PreferenceEvidence` based on `memory_type`
- Settings → `PreferenceEvidence(dimension="tool_settings", direction="configured", ...)`
- Transcripts → `BehaviorEvidence(action_type="conversation", pattern=..., ...)`

Each must use `occurred_at=mtime, valid_from=mtime` instead of `timestamp=mtime`.

- [ ] **Step 4: Run all OpenClaw tests**

Run: `python3 -m pytest tests/test_sources.py::TestOpenClawAdapter -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite**

Run: `python3 -m pytest tests/ --ignore=tests/test_pipeline_integration.py --ignore=tests/test_full_cycle.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/twin_runtime/sources/openclaw_adapter.py tests/test_sources.py
git commit -m "feat: OpenClawAdapter produces typed evidence fragments"
```

---

### Task 7: Migrate NotionAdapter and DocumentAdapter

**Files:**
- Modify: `src/twin_runtime/sources/notion_adapter.py`
- Modify: `src/twin_runtime/sources/document_adapter.py`

- [ ] **Step 1: Update NotionAdapter**

Update all `EvidenceFragment(...)` calls in `notion_adapter.py`:
- Pages classified as DECISION → `DecisionEvidence`
- Pages classified as REFLECTION → `ReflectionEvidence`
- Pages classified as PREFERENCE → `PreferenceEvidence`
- Pages classified as CONTEXT → `ContextEvidence`
- Databases → `ContextEvidence(context_category="database", ...)`

All must use `occurred_at=..., valid_from=...` instead of `timestamp=...`.

- [ ] **Step 2: Update DocumentAdapter**

Update `EvidenceFragment(...)` in `document_adapter.py`:
- All files → `ContextEvidence(context_category="document", description=f"Document: {file_path.name}", ...)`

- [ ] **Step 3: Run all source tests**

Run: `python3 -m pytest tests/test_sources.py tests/test_google_sources.py tests/test_evidence_types.py tests/test_clustering.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add src/twin_runtime/sources/notion_adapter.py src/twin_runtime/sources/document_adapter.py
git commit -m "feat: NotionAdapter and DocumentAdapter produce typed evidence fragments"
```

---

### Task 8: Update PersonaCompiler for typed fragments + cold start

**Files:**
- Modify: `src/twin_runtime/compiler/compiler.py`
- Create: `tests/test_compiler_cold_start.py`

- [ ] **Step 1: Write failing test for cold start**

```python
# tests/test_compiler_cold_start.py
"""Tests for PersonaCompiler cold-start path."""

from datetime import datetime, timezone

import pytest

from twin_runtime.compiler.compiler import PersonaCompiler
from twin_runtime.sources.registry import SourceRegistry
from twin_runtime.sources.evidence_types import PreferenceEvidence, ContextEvidence
from twin_runtime.models.twin_state import TwinState


class TestColdStart:
    def test_create_initial_zero_evidence(self):
        """With zero evidence, produce a minimal TwinState that refuses most decisions."""
        registry = SourceRegistry()
        compiler = PersonaCompiler(registry)
        twin = compiler._create_initial(user_id="user-new", fragments=[])

        assert isinstance(twin, TwinState)
        assert twin.user_id == "user-new"
        assert twin.state_version.startswith("v000")
        # All 5 domain heads should exist and be below default threshold
        assert len(twin.domain_heads) == 5
        for head in twin.domain_heads:
            assert head.head_reliability <= 0.3
            assert head.head_version == "v000"

        # Core params at median
        assert twin.shared_decision_core.risk_tolerance == 0.5
        assert twin.shared_decision_core.core_confidence <= 0.3
        # No valid domains (all below 0.5 threshold)
        assert len(twin.valid_domains()) == 0

    def test_create_initial_with_some_evidence(self):
        """With some evidence, produce a TwinState with partial modeling."""
        registry = SourceRegistry()
        compiler = PersonaCompiler(registry)
        now = datetime.now(timezone.utc)

        fragments = [
            PreferenceEvidence(
                source_type="test", source_id="t-1",
                occurred_at=now, valid_from=now,
                summary="Prefers low risk",
                confidence=0.8, user_id="user-new",
                dimension="risk_tolerance", direction="prefers_low", strength=0.8,
            ),
            ContextEvidence(
                source_type="test", source_id="t-2",
                occurred_at=now, valid_from=now,
                summary="Product manager at Tencent",
                confidence=0.9, user_id="user-new",
                context_category="role", description="PM trainee at Tencent",
            ),
        ]
        twin = compiler._create_initial(user_id="user-new", fragments=fragments)
        assert isinstance(twin, TwinState)
        assert twin.user_id == "user-new"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_compiler_cold_start.py -v`
Expected: FAIL — `_create_initial` raises NotImplementedError

- [ ] **Step 3: Implement cold-start path**

In `src/twin_runtime/compiler/compiler.py`, replace the `_create_initial` method.

Note: The actual model classes have specific field names and types. Check `src/twin_runtime/models/twin_state.py` for exact signatures. Key gotchas:
- `DomainHead` requires `head_version`, `default_priority_order` (not `priority_order`), `last_recalibrated_at`
- `ReliabilityProfileEntry` (not `ReliabilityProfile`) requires `uncertainty_band: Optional[str]`, `evidence_strength: float`, `scope_status: ReliabilityScopeStatus`, `last_updated_at`
- `RejectionPolicyMap` requires `MergeStrategy` enums, not strings
- `CausalBeliefModel` requires `causal_confidence: float`
- `SharedDecisionCore` uses `decision_latency_hours_p50` (not `decision_latency_p50`)
- `TwinState` requires `created_at: datetime`
- Include all 5 `DomainEnum` values, not just 3

```python
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

    # All 5 domain heads — all below reliability threshold
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
            evidence_weight_profile=EvidenceWeightProfile(),
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
```

- [ ] **Step 4: Update compile() to call _create_initial when no existing twin**

In the `compile()` method, find the cold-start branch (currently raises `NotImplementedError` or `ValueError`). Replace it with:

```python
# In compile(), after collect_evidence() and extract_parameters():
if existing is None:
    # Cold start: create minimal twin from whatever evidence we have
    twin = self._create_initial(user_id="user-default", fragments=fragments)
    # If we extracted parameters, apply them to the cold-start twin
    if extracted:
        twin = self._merge(twin, extracted, fragments)
else:
    twin = existing
    if extracted:
        twin = self._merge(twin, extracted, fragments)
```

Also update the old `_create_initial(extracted, fragments)` call signature to match the new `_create_initial(user_id, fragments)` signature. Search the file for any call to `_create_initial` and update accordingly.

- [ ] **Step 5: Run all tests**

Run: `python3 -m pytest tests/test_compiler_cold_start.py tests/test_sources.py tests/test_google_sources.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run full test suite to verify nothing broke**

Run: `python3 -m pytest tests/ --ignore=tests/test_pipeline_integration.py --ignore=tests/test_full_cycle.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/twin_runtime/compiler/compiler.py tests/test_compiler_cold_start.py
git commit -m "feat: PersonaCompiler cold-start path and typed fragment support"
```

---

### Task 9: Update PersonaCompiler to use typed fields in extraction

**Files:**
- Modify: `src/twin_runtime/compiler/compiler.py`

- [ ] **Step 1: Update extract_parameters() to leverage typed fields**

In the evidence summary building loop, detect typed fragments using `isinstance` and use their fields.

Add imports at the top of compiler.py:
```python
from twin_runtime.sources.evidence_types import (
    DecisionEvidence, PreferenceEvidence, ReflectionEvidence,
)
```

Then replace the evidence line building loop:
```python
for f in fragments[:30]:
    domain_str = f.domain_hint.value if f.domain_hint else "unknown"

    # Use typed fields if available (isinstance checks for type safety)
    if isinstance(f, DecisionEvidence) and f.chosen:
        evidence_lines.append(
            f"[DECISION|{domain_str}|conf={f.confidence:.1f}] "
            f"Chose '{f.chosen}' from {f.option_set}. {f.summary}"
        )
        if f.reasoning:
            evidence_lines.append(f"  Reasoning: {f.reasoning}")
    elif isinstance(f, PreferenceEvidence) and f.dimension:
        evidence_lines.append(
            f"[PREFERENCE|{domain_str}|conf={f.confidence:.1f}] "
            f"{f.dimension}: {f.direction} (strength={f.strength:.1f}). {f.summary}"
        )
    elif isinstance(f, ReflectionEvidence) and f.insight:
        evidence_lines.append(
            f"[REFLECTION|{domain_str}|conf={f.confidence:.1f}] "
            f"Topic: {f.topic}. {f.insight[:200]}"
        )
    else:
        # Fallback: use summary + raw_excerpt (works for legacy and all typed)
        evidence_lines.append(
            f"[{f.evidence_type.value}|{domain_str}|conf={f.confidence:.1f}] "
            f"{f.summary}"
        )
        if f.raw_excerpt:
            excerpt = f.raw_excerpt[:300].replace("\n", " ")
            evidence_lines.append(f"  Excerpt: {excerpt}")
```

- [ ] **Step 2: Run full test suite**

Run: `python3 -m pytest tests/ --ignore=tests/test_pipeline_integration.py --ignore=tests/test_full_cycle.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add src/twin_runtime/compiler/compiler.py
git commit -m "feat: PersonaCompiler uses typed evidence fields for richer LLM extraction"
```

---

### Task 10: Integration smoke test

**Files:**
- Create: `tests/test_evidence_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_evidence_integration.py
"""Integration test: typed evidence → dedup → compiler consumption."""

from datetime import datetime, timezone

from twin_runtime.sources.evidence_types import (
    DecisionEvidence, PreferenceEvidence, BehaviorEvidence,
    ContextEvidence, ReflectionEvidence, migrate_fragment,
)
from twin_runtime.sources.clustering import deduplicate, EvidenceCluster
from twin_runtime.sources.base import EvidenceFragment, EvidenceType


NOW = datetime.now(timezone.utc)


class TestEvidenceFlowIntegration:
    def test_typed_fragments_dedup_and_cluster(self):
        """Typed fragments from different sources cluster correctly."""
        # Same decision from Gmail and Notion
        gmail_decision = DecisionEvidence(
            source_type="gmail", source_id="g-1",
            occurred_at=NOW, valid_from=NOW,
            summary="Chose Python", confidence=0.6, user_id="user-test",
            option_set=["Python", "TypeScript"], chosen="Python",
        )
        notion_decision = DecisionEvidence(
            source_type="notion", source_id="n-1",
            occurred_at=NOW, valid_from=NOW,
            summary="Project language: Python", confidence=0.8, user_id="user-test",
            option_set=["Python", "TypeScript"], chosen="Python",
        )
        # Unrelated behavior
        calendar_behavior = BehaviorEvidence(
            source_type="calendar", source_id="c-1",
            occurred_at=NOW, valid_from=NOW,
            summary="Morning meetings", confidence=0.7, user_id="user-test",
            action_type="schedule", pattern="Prefers 9-11am",
        )

        result = deduplicate([gmail_decision, notion_decision, calendar_behavior])
        assert len(result) == 2  # 1 cluster + 1 standalone

        clusters = [r for r in result if isinstance(r, EvidenceCluster)]
        assert len(clusters) == 1
        assert clusters[0].canonical_fragment.source_type == "notion"  # Higher confidence

    def test_legacy_migration_then_dedup(self):
        """Legacy flat fragments migrate to typed, then dedup works."""
        legacy1 = EvidenceFragment(
            source_type="gmail", source_id="g-1",
            evidence_type=EvidenceType.BEHAVIOR,
            timestamp=NOW, summary="Calendar patterns",
            structured_data={"total_events": 50, "action_type": "calendar"},
            confidence=0.7,
        )
        legacy2 = EvidenceFragment(
            source_type="notion", source_id="n-1",
            evidence_type=EvidenceType.BEHAVIOR,
            timestamp=NOW, summary="Calendar patterns",
            structured_data={"total_events": 50, "action_type": "calendar"},
            confidence=0.6,
        )
        typed1 = migrate_fragment(legacy1)
        typed2 = migrate_fragment(legacy2)
        assert typed1.content_hash == typed2.content_hash

        result = deduplicate([typed1, typed2])
        assert len(result) == 1
        assert isinstance(result[0], EvidenceCluster)

    def test_cold_start_produces_valid_twin(self):
        """Cold start twin can be created and has correct defaults."""
        from twin_runtime.compiler.compiler import PersonaCompiler
        from twin_runtime.sources.registry import SourceRegistry

        compiler = PersonaCompiler(SourceRegistry())
        twin = compiler._create_initial(user_id="new-user", fragments=[])

        assert twin.user_id == "new-user"
        assert twin.state_version == "v000-cold-start"
        assert len(twin.valid_domains()) == 0  # All below threshold (0.3 < 0.5)
        assert twin.shared_decision_core.core_confidence <= 0.3
```

- [ ] **Step 2: Run integration test**

Run: `python3 -m pytest tests/test_evidence_integration.py -v`
Expected: ALL PASS

- [ ] **Step 3: Run full suite one final time**

Run: `python3 -m pytest tests/ --ignore=tests/test_pipeline_integration.py --ignore=tests/test_full_cycle.py -v`
Expected: ALL PASS (should be 86 original + ~25 new = ~111 tests)

- [ ] **Step 4: Commit**

```bash
git add tests/test_evidence_integration.py
git commit -m "test: evidence layer integration test — typed fragments, dedup, cold start"
```

---

## Summary

| Task | What it does | New tests |
|------|-------------|-----------|
| 1 | Base class: user_id, temporal triple, content_hash, backward compat | 3 |
| 2 | 6 typed subclasses + migration function | 14 |
| 3 | Dedup clustering by content_hash | 5 |
| 4 | GmailAdapter → DecisionEvidence | 1 |
| 5 | CalendarAdapter → BehaviorEvidence | 1 |
| 6 | OpenClawAdapter → typed fragments | 1 |
| 7 | NotionAdapter + DocumentAdapter → typed fragments | 0 (covered by existing) |
| 8 | PersonaCompiler cold-start path | 2 |
| 9 | PersonaCompiler typed field extraction | 0 (covered by existing) |
| 10 | Integration smoke test | 3 |

**Total new tests: ~30**
**Total after Phase 1: ~116 tests**

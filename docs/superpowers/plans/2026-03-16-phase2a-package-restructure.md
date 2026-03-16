# Phase 2a: Package Restructure + Backend Protocols

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the codebase into a 4-layer Hexagonal Architecture (domain/application/infrastructure/interfaces) with pluggable backend protocols.

**Architecture:** Move existing modules into 4 layers following the Ports & Adapters pattern. Domain layer contains pure models, evidence types, rules, and port protocols (zero IO). Application layer orchestrates pipeline, calibration, and compilation. Infrastructure implements port protocols (JSON file backend, source adapters, LLM client). Interfaces exposes CLI. Backward-compat re-export shims ensure all 131 tests pass at every step.

**Tech Stack:** Python 3.9+, Pydantic v2, typing.Protocol, existing pytest infrastructure

**Spec:** `docs/superpowers/specs/2026-03-16-twin-runtime-evolution-design.md` — "Target Architecture: 4-Layer Package Structure" + Dimension 2

**Migration Strategy:** For each file move: (1) create new file at target location with updated internal imports, (2) replace old file with backward-compat re-export shim. After all moves complete, update all consumers to new paths and remove shims.

---

## File Move Map

| Current Location | New Location | Layer |
|---|---|---|
| `models/primitives.py` | `domain/models/primitives.py` | domain |
| `models/twin_state.py` | `domain/models/twin_state.py` | domain |
| `models/calibration.py` | `domain/models/calibration.py` | domain |
| `models/runtime.py` | `domain/models/runtime.py` | domain |
| `models/situation.py` | `domain/models/situation.py` | domain |
| `sources/base.py` | `domain/evidence/base.py` | domain |
| `sources/evidence_types.py` | `domain/evidence/types.py` | domain |
| `sources/clustering.py` | `domain/evidence/clustering.py` | domain |
| *(new)* | `domain/ports/twin_state_store.py` | domain |
| *(new)* | `domain/ports/evidence_store.py` | domain |
| *(new)* | `domain/ports/calibration_store.py` | domain |
| *(new)* | `domain/ports/trace_store.py` | domain |
| *(new)* | `domain/ports/llm_port.py` | domain |
| *(new)* | `domain/models/recall_query.py` | domain |
| `runtime/pipeline.py` | `application/pipeline/runner.py` | application |
| `runtime/situation_interpreter.py` | `application/pipeline/situation_interpreter.py` | application |
| `runtime/head_activator.py` | `application/pipeline/head_activator.py` | application |
| `runtime/conflict_arbiter.py` | `application/pipeline/conflict_arbiter.py` | application |
| `runtime/decision_synthesizer.py` | `application/pipeline/decision_synthesizer.py` | application |
| `calibration/event_collector.py` | `application/calibration/event_collector.py` | application |
| `calibration/case_manager.py` | `application/calibration/case_manager.py` | application |
| `calibration/fidelity_evaluator.py` | `application/calibration/fidelity_evaluator.py` | application |
| `calibration/state_updater.py` | `application/calibration/state_updater.py` | application |
| `compiler/compiler.py` | `application/compiler/persona_compiler.py` | application |
| `store/twin_store.py` | `infrastructure/backends/json_file/twin_store.py` | infrastructure |
| `store/calibration_store.py` | `infrastructure/backends/json_file/calibration_store.py` | infrastructure |
| `runtime/llm_client.py` | `infrastructure/llm/client.py` | infrastructure |
| `sources/registry.py` | `infrastructure/sources/registry.py` | infrastructure |
| `sources/openclaw_adapter.py` | `infrastructure/sources/openclaw_adapter.py` | infrastructure |
| `sources/notion_adapter.py` | `infrastructure/sources/notion_adapter.py` | infrastructure |
| `sources/gmail_adapter.py` | `infrastructure/sources/gmail_adapter.py` | infrastructure |
| `sources/calendar_adapter.py` | `infrastructure/sources/calendar_adapter.py` | infrastructure |
| `sources/document_adapter.py` | `infrastructure/sources/document_adapter.py` | infrastructure |
| `sources/google_auth.py` | `infrastructure/sources/google_auth.py` | infrastructure |
| `cli.py` | `interfaces/cli.py` | interfaces |

All paths relative to `src/twin_runtime/`.

---

## Chunk 1: Domain Layer

### Task 1: Create directory skeleton + move domain/models

**Files:**
- Create: `src/twin_runtime/domain/__init__.py`
- Create: `src/twin_runtime/domain/models/__init__.py`
- Move: `src/twin_runtime/models/primitives.py` → `src/twin_runtime/domain/models/primitives.py`
- Move: `src/twin_runtime/models/twin_state.py` → `src/twin_runtime/domain/models/twin_state.py`
- Move: `src/twin_runtime/models/calibration.py` → `src/twin_runtime/domain/models/calibration.py`
- Move: `src/twin_runtime/models/runtime.py` → `src/twin_runtime/domain/models/runtime.py`
- Move: `src/twin_runtime/models/situation.py` → `src/twin_runtime/domain/models/situation.py`
- Modify: `src/twin_runtime/models/__init__.py` (backward-compat shim)
- Modify: `src/twin_runtime/models/primitives.py` (backward-compat shim)
- Modify: `src/twin_runtime/models/twin_state.py` (backward-compat shim)
- Modify: `src/twin_runtime/models/calibration.py` (backward-compat shim)
- Modify: `src/twin_runtime/models/runtime.py` (backward-compat shim)
- Modify: `src/twin_runtime/models/situation.py` (backward-compat shim)

- [ ] **Step 1: Create all new directories**

Create these directories with `__init__.py`:
```
src/twin_runtime/domain/
src/twin_runtime/domain/__init__.py          (empty)
src/twin_runtime/domain/models/
src/twin_runtime/domain/models/__init__.py   (empty for now)
src/twin_runtime/domain/evidence/
src/twin_runtime/domain/evidence/__init__.py (empty for now)
src/twin_runtime/domain/ports/
src/twin_runtime/domain/ports/__init__.py    (empty for now)
src/twin_runtime/application/
src/twin_runtime/application/__init__.py     (empty)
src/twin_runtime/application/pipeline/
src/twin_runtime/application/pipeline/__init__.py (empty)
src/twin_runtime/application/calibration/
src/twin_runtime/application/calibration/__init__.py (empty)
src/twin_runtime/application/compiler/
src/twin_runtime/application/compiler/__init__.py (empty)
src/twin_runtime/infrastructure/
src/twin_runtime/infrastructure/__init__.py  (empty)
src/twin_runtime/infrastructure/backends/
src/twin_runtime/infrastructure/backends/__init__.py (empty)
src/twin_runtime/infrastructure/backends/json_file/
src/twin_runtime/infrastructure/backends/json_file/__init__.py (empty)
src/twin_runtime/infrastructure/sources/
src/twin_runtime/infrastructure/sources/__init__.py (empty)
src/twin_runtime/infrastructure/llm/
src/twin_runtime/infrastructure/llm/__init__.py (empty)
src/twin_runtime/interfaces/
src/twin_runtime/interfaces/__init__.py      (empty)
```

- [ ] **Step 2: Copy model files to domain/models/**

Copy each model file to its new location. The domain/models files must NOT use relative imports that go above domain/. Update internal imports to use absolute paths:

`src/twin_runtime/domain/models/primitives.py` — Copy as-is (no internal imports to change, uses only stdlib + pydantic).

`src/twin_runtime/domain/models/twin_state.py` — Copy and change:
```python
# OLD: from .primitives import (...)
# NEW:
from twin_runtime.domain.models.primitives import (...)
```

`src/twin_runtime/domain/models/calibration.py` — Copy and change:
```python
# OLD: from .primitives import (...)
# NEW:
from twin_runtime.domain.models.primitives import (...)
```
Also check for any imports from `.runtime` or `.situation` and update similarly.

`src/twin_runtime/domain/models/runtime.py` — Copy and change (runtime.py only imports from primitives):
```python
# OLD: from .primitives import (...)
# NEW:
from twin_runtime.domain.models.primitives import (...)
```

`src/twin_runtime/domain/models/situation.py` — Copy and change:
```python
# OLD: from .primitives import (...)
# NEW:
from twin_runtime.domain.models.primitives import (...)
```

- [ ] **Step 3: Replace old model files with backward-compat shims**

Each old file becomes a simple re-export. Example for `src/twin_runtime/models/primitives.py`:
```python
"""Backward-compat shim — real code is in domain.models.primitives."""
from twin_runtime.domain.models.primitives import *  # noqa: F401,F403
```

Do the same for `twin_state.py`, `calibration.py`, `runtime.py`, `situation.py`.

Update `src/twin_runtime/models/__init__.py` to re-export ALL symbols from new locations (the current `__init__.py` exports 25+ symbols used by tests):
```python
"""Backward-compat shim — real code is in domain.models.*."""
from twin_runtime.domain.models.primitives import *  # noqa: F401,F403
from twin_runtime.domain.models.twin_state import (  # noqa: F401
    BiasCorrectionEntry,
    CausalBeliefModel,
    DomainHead,
    EvidenceWeightProfile,
    PriorBiasPattern,
    ReliabilityProfileEntry,
    RejectionPolicyMap,
    ScopeDeclaration,
    SharedDecisionCore,
    TemporalMetadata,
    TransferCoefficient,
    TwinState,
)
from twin_runtime.domain.models.situation import SituationFeatureVector, SituationFrame  # noqa: F401
from twin_runtime.domain.models.runtime import (  # noqa: F401
    ConflictReport,
    HeadAssessment,
    RuntimeDecisionTrace,
    RuntimeEvent,
)
from twin_runtime.domain.models.calibration import (  # noqa: F401
    CalibrationCase,
    CandidateCalibrationCase,
    TwinEvaluation,
)
```

Also create `src/twin_runtime/domain/models/__init__.py`:
```python
"""Domain models — pure data objects, zero side effects."""
from .primitives import *  # noqa: F401,F403
from .twin_state import (
    BiasCorrectionEntry,
    CausalBeliefModel,
    DomainHead,
    EvidenceWeightProfile,
    PriorBiasPattern,
    ReliabilityProfileEntry,
    RejectionPolicyMap,
    ScopeDeclaration,
    SharedDecisionCore,
    TemporalMetadata,
    TransferCoefficient,
    TwinState,
)
from .situation import SituationFeatureVector, SituationFrame
from .runtime import ConflictReport, HeadAssessment, RuntimeDecisionTrace, RuntimeEvent
from .calibration import CalibrationCase, CandidateCalibrationCase, TwinEvaluation
```

- [ ] **Step 4: Run ALL tests**

Run: `python3 -m pytest tests/ --ignore=tests/test_pipeline_integration.py --ignore=tests/test_full_cycle.py -v`
Expected: ALL 131 tests PASS (backward compat shims preserve all import paths)

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/domain/ src/twin_runtime/application/ src/twin_runtime/infrastructure/ src/twin_runtime/interfaces/ src/twin_runtime/models/
git commit -m "refactor: create 4-layer skeleton, move models to domain/models/"
```

---

### Task 2: Move evidence modules to domain/evidence/

**Files:**
- Move: `src/twin_runtime/sources/base.py` → `src/twin_runtime/domain/evidence/base.py`
- Move: `src/twin_runtime/sources/evidence_types.py` → `src/twin_runtime/domain/evidence/types.py`
- Move: `src/twin_runtime/sources/clustering.py` → `src/twin_runtime/domain/evidence/clustering.py`
- Modify: old files → backward-compat shims

- [ ] **Step 1: Copy evidence files to domain/evidence/**

`src/twin_runtime/domain/evidence/base.py` — Copy from `sources/base.py`. Update imports:
```python
# OLD: from ..models.primitives import DomainEnum, OrdinalTriLevel, confidence_field
# NEW:
from twin_runtime.domain.models.primitives import DomainEnum, OrdinalTriLevel, confidence_field
```
IMPORTANT: Keep only `EvidenceType`, `EvidenceFragment`, and `SourceAdapter` in this file. `SourceAdapter` is an ABC used by infrastructure adapters — it's fine in domain since it defines the contract.

`src/twin_runtime/domain/evidence/types.py` — Copy from `sources/evidence_types.py`. Update imports:
```python
# OLD: from .base import EvidenceFragment, EvidenceType
# OLD: from ..models.primitives import DomainEnum, OrdinalTriLevel
# NEW:
from twin_runtime.domain.evidence.base import EvidenceFragment, EvidenceType
from twin_runtime.domain.models.primitives import DomainEnum, OrdinalTriLevel
```

`src/twin_runtime/domain/evidence/clustering.py` — Copy from `sources/clustering.py`. Update imports:
```python
# OLD: from .base import EvidenceFragment
# NEW:
from twin_runtime.domain.evidence.base import EvidenceFragment
```

- [ ] **Step 2: Update domain/evidence/__init__.py**

```python
"""Domain evidence types — typed fragments, clustering, dedup."""
from .base import EvidenceFragment, EvidenceType, SourceAdapter
from .types import (
    DecisionEvidence, PreferenceEvidence, BehaviorEvidence,
    ReflectionEvidence, InteractionStyleEvidence, ContextEvidence,
    migrate_fragment,
)
from .clustering import EvidenceCluster, deduplicate

__all__ = [
    "EvidenceFragment", "EvidenceType", "SourceAdapter",
    "DecisionEvidence", "PreferenceEvidence", "BehaviorEvidence",
    "ReflectionEvidence", "InteractionStyleEvidence", "ContextEvidence",
    "migrate_fragment", "EvidenceCluster", "deduplicate",
]
```

- [ ] **Step 3: Replace old source files with shims**

`src/twin_runtime/sources/base.py`:
```python
"""Backward-compat shim."""
from twin_runtime.domain.evidence.base import *  # noqa: F401,F403
```

`src/twin_runtime/sources/evidence_types.py`:
```python
"""Backward-compat shim."""
from twin_runtime.domain.evidence.types import *  # noqa: F401,F403
```

`src/twin_runtime/sources/clustering.py`:
```python
"""Backward-compat shim."""
from twin_runtime.domain.evidence.clustering import *  # noqa: F401,F403
```

- [ ] **Step 4: Run ALL tests**

Run: `python3 -m pytest tests/ --ignore=tests/test_pipeline_integration.py --ignore=tests/test_full_cycle.py -v`
Expected: ALL 131 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/domain/evidence/ src/twin_runtime/sources/base.py src/twin_runtime/sources/evidence_types.py src/twin_runtime/sources/clustering.py
git commit -m "refactor: move evidence types to domain/evidence/"
```

---

### Task 3: Create domain/ports/ with 4 protocols + RecallQuery

**Files:**
- Create: `src/twin_runtime/domain/ports/twin_state_store.py`
- Create: `src/twin_runtime/domain/ports/evidence_store.py`
- Create: `src/twin_runtime/domain/ports/calibration_store.py`
- Create: `src/twin_runtime/domain/ports/trace_store.py`
- Create: `src/twin_runtime/domain/ports/llm_port.py`
- Create: `src/twin_runtime/domain/models/recall_query.py`
- Create: `tests/test_ports.py`

- [ ] **Step 1: Write tests for port protocol compliance**

```python
# tests/test_ports.py
"""Tests that verify port protocol definitions are importable and structurally correct."""

from typing import Protocol, runtime_checkable

import pytest


class TestPortProtocols:
    def test_twin_state_store_is_protocol(self):
        from twin_runtime.domain.ports.twin_state_store import TwinStateStore
        assert issubclass(TwinStateStore, Protocol)

    def test_evidence_store_is_protocol(self):
        from twin_runtime.domain.ports.evidence_store import EvidenceStore
        assert issubclass(EvidenceStore, Protocol)

    def test_calibration_store_is_protocol(self):
        from twin_runtime.domain.ports.calibration_store import CalibrationStore
        assert issubclass(CalibrationStore, Protocol)

    def test_trace_store_is_protocol(self):
        from twin_runtime.domain.ports.trace_store import TraceStore
        assert issubclass(TraceStore, Protocol)

    def test_llm_port_is_protocol(self):
        from twin_runtime.domain.ports.llm_port import LLMPort
        assert issubclass(LLMPort, Protocol)

    def test_recall_query_creation(self):
        from twin_runtime.domain.models.recall_query import RecallQuery
        q = RecallQuery(
            query_type="by_domain",
            user_id="user-test",
            target_domain="work",
        )
        assert q.query_type == "by_domain"
        assert q.limit == 20  # default

    def test_recall_query_by_topic(self):
        from twin_runtime.domain.models.recall_query import RecallQuery
        q = RecallQuery(
            query_type="by_topic",
            user_id="user-test",
            topic_keywords=["career", "decision"],
        )
        assert q.topic_keywords == ["career", "decision"]
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Create port protocol files**

`src/twin_runtime/domain/ports/twin_state_store.py`:
```python
"""Port: TwinState storage and retrieval."""
from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable

from twin_runtime.domain.models.twin_state import TwinState


@runtime_checkable
class TwinStateStore(Protocol):
    """Store and retrieve versioned TwinState snapshots."""

    def save_state(self, state: TwinState) -> str: ...
    def load_state(self, user_id: str, version: Optional[str] = None) -> TwinState: ...
    def list_versions(self, user_id: str) -> List[str]: ...
    def has_current(self, user_id: str) -> bool: ...
    def rollback(self, user_id: str, version: str) -> TwinState: ...
```

`src/twin_runtime/domain/ports/evidence_store.py`:
```python
"""Port: Evidence fragment storage and querying."""
from __future__ import annotations

from typing import Dict, List, Optional, Protocol, runtime_checkable

from twin_runtime.domain.evidence.base import EvidenceFragment
from twin_runtime.domain.evidence.clustering import EvidenceCluster
from twin_runtime.domain.models.recall_query import RecallQuery


@runtime_checkable
class EvidenceStore(Protocol):
    """Store and query evidence fragments."""

    def store_fragment(self, fragment: EvidenceFragment) -> str: ...
    def store_cluster(self, cluster: EvidenceCluster) -> str: ...
    def query(self, query: RecallQuery) -> List[EvidenceFragment]: ...
    def get_by_hash(self, content_hash: str) -> Optional[EvidenceFragment]: ...
    def count(self, user_id: str, filters: Optional[Dict] = None) -> int: ...
```

`src/twin_runtime/domain/ports/calibration_store.py`:
```python
"""Port: Calibration data storage."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Protocol, runtime_checkable

from twin_runtime.domain.models.calibration import (
    CalibrationCase, CandidateCalibrationCase, TwinEvaluation,
)
from twin_runtime.domain.models.runtime import RuntimeEvent


@runtime_checkable
class CalibrationStore(Protocol):
    """Store calibration lifecycle objects."""

    def save_candidate(self, candidate: CandidateCalibrationCase) -> str: ...
    def save_case(self, case: CalibrationCase) -> str: ...
    def save_evaluation(self, evaluation: TwinEvaluation) -> str: ...
    def save_event(self, event: RuntimeEvent) -> str: ...
    # save_outcome() deferred to Phase 3 — OutcomeRecord model doesn't exist yet.
    # Will be added as: def save_outcome(self, outcome: OutcomeRecord) -> str: ...
    def list_cases(self, used: Optional[bool] = None) -> List[CalibrationCase]: ...
    def list_events(self, since: Optional[datetime] = None) -> List[RuntimeEvent]: ...
```

`src/twin_runtime/domain/ports/trace_store.py`:
```python
"""Port: Runtime decision trace storage."""
from __future__ import annotations

from typing import List, Protocol, runtime_checkable

from twin_runtime.domain.models.runtime import RuntimeDecisionTrace


@runtime_checkable
class TraceStore(Protocol):
    """Store runtime decision traces for audit."""

    def save_trace(self, trace: RuntimeDecisionTrace) -> str: ...
    def load_trace(self, trace_id: str) -> RuntimeDecisionTrace: ...
    def list_traces(self, user_id: str, limit: int = 50) -> List[str]: ...
```

`src/twin_runtime/domain/ports/llm_port.py`:
```python
"""Port: LLM interaction."""
from __future__ import annotations

from typing import Any, Dict, Protocol, runtime_checkable


@runtime_checkable
class LLMPort(Protocol):
    """Abstract LLM client for testability."""

    def ask_json(self, system: str, user: str, max_tokens: int = 1024) -> Dict[str, Any]: ...
    def ask_text(self, system: str, user: str, max_tokens: int = 1024) -> str: ...
```

- [ ] **Step 4: Create RecallQuery model**

`src/twin_runtime/domain/models/recall_query.py`:
```python
"""RecallQuery: typed evidence retrieval queries."""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from twin_runtime.domain.models.primitives import DomainEnum
from twin_runtime.domain.evidence.base import EvidenceType


class RecallQuery(BaseModel):
    """Typed query for evidence retrieval."""

    query_type: Literal[
        "by_topic",
        "by_timeline",
        "by_domain",
        "by_evidence_type",
        "decisions_about",
        "preference_on_axis",
        "state_trajectory",
        "similar_situations",
    ]
    user_id: str
    time_range: Optional[Tuple[datetime, datetime]] = None
    domain_filter: Optional[List[DomainEnum]] = None
    evidence_type_filter: Optional[List[EvidenceType]] = None
    limit: int = Field(default=20, ge=1, le=100)
    sort_by: Literal["recency", "relevance", "confidence"] = "recency"

    # Query-type-specific parameters
    topic_keywords: Optional[List[str]] = None
    target_domain: Optional[str] = None
    target_evidence_type: Optional[str] = None
    decision_topic: Optional[str] = None
    preference_dimension: Optional[str] = None
    state_variable: Optional[str] = None
    situation_description: Optional[str] = None
```

- [ ] **Step 5: Update domain/ports/__init__.py**

```python
"""Domain ports — abstract protocols for infrastructure adapters."""
from .twin_state_store import TwinStateStore
from .evidence_store import EvidenceStore
from .calibration_store import CalibrationStore
from .trace_store import TraceStore
from .llm_port import LLMPort

__all__ = [
    "TwinStateStore", "EvidenceStore", "CalibrationStore",
    "TraceStore", "LLMPort",
]
```

- [ ] **Step 6: Run tests**

Run: `python3 -m pytest tests/test_ports.py tests/test_sources.py tests/test_evidence_types.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/twin_runtime/domain/ports/ src/twin_runtime/domain/models/recall_query.py tests/test_ports.py
git commit -m "feat: domain port protocols (TwinStateStore, EvidenceStore, CalibrationStore, TraceStore, LLMPort) + RecallQuery"
```

---

## Chunk 2: Application + Infrastructure Layers

### Task 4: Move runtime pipeline to application/pipeline/

**Files:**
- Move: `src/twin_runtime/runtime/pipeline.py` → `src/twin_runtime/application/pipeline/runner.py`
- Move: `src/twin_runtime/runtime/situation_interpreter.py` → `src/twin_runtime/application/pipeline/situation_interpreter.py`
- Move: `src/twin_runtime/runtime/head_activator.py` → `src/twin_runtime/application/pipeline/head_activator.py`
- Move: `src/twin_runtime/runtime/conflict_arbiter.py` → `src/twin_runtime/application/pipeline/conflict_arbiter.py`
- Move: `src/twin_runtime/runtime/decision_synthesizer.py` → `src/twin_runtime/application/pipeline/decision_synthesizer.py`
- Modify: old files → backward-compat shims

- [ ] **Step 1: Copy pipeline files to application/pipeline/**

For each file, copy and update imports to use absolute `twin_runtime.domain.models.*` paths instead of `..models.*`, and update cross-references within the pipeline to use `twin_runtime.application.pipeline.*`.

`runner.py` imports to update:
```python
from twin_runtime.domain.models.runtime import RuntimeDecisionTrace
from twin_runtime.domain.models.twin_state import TwinState
from twin_runtime.application.pipeline.situation_interpreter import interpret_situation
from twin_runtime.application.pipeline.head_activator import activate_heads
from twin_runtime.application.pipeline.conflict_arbiter import arbitrate
from twin_runtime.application.pipeline.decision_synthesizer import synthesize
```

`situation_interpreter.py` imports to update:
```python
from twin_runtime.domain.models.primitives import DomainEnum, OrdinalTriLevel, ScopeStatus, UncertaintyType, OptionStructure
from twin_runtime.domain.models.situation import SituationFeatureVector, SituationFrame
from twin_runtime.domain.models.twin_state import TwinState, ScopeDeclaration
```
Also check for any `ask_json` or `ask_text` imports from `llm_client` — update to `twin_runtime.runtime.llm_client` (will move later).

`head_activator.py`, `conflict_arbiter.py`, `decision_synthesizer.py` — same pattern: change `..models.*` to `twin_runtime.domain.models.*`.

For any LLM imports (`from ..runtime.llm_client import ...` or `from .llm_client import ...`), keep pointing to `twin_runtime.runtime.llm_client` for now (will be moved in Task 6).

- [ ] **Step 2: Replace old runtime files with shims**

`src/twin_runtime/runtime/pipeline.py`:
```python
"""Backward-compat shim."""
from twin_runtime.application.pipeline.runner import *  # noqa: F401,F403
```

Same for `situation_interpreter.py`, `head_activator.py`, `conflict_arbiter.py`, `decision_synthesizer.py`.

Update `src/twin_runtime/runtime/__init__.py`:
```python
"""Backward-compat shim."""
from twin_runtime.application.pipeline.runner import run  # noqa: F401

__all__ = ["run"]
```

Update `src/twin_runtime/application/pipeline/__init__.py`:
```python
"""Application pipeline — 4-stage runtime decision engine."""
from .runner import run

__all__ = ["run"]
```

- [ ] **Step 3: Run tests**

Run: `python3 -m pytest tests/test_runtime_units.py tests/test_pipeline_integration.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add src/twin_runtime/application/pipeline/ src/twin_runtime/runtime/
git commit -m "refactor: move runtime pipeline to application/pipeline/"
```

---

### Task 5: Move calibration + compiler to application/

**Files:**
- Move: 4 calibration files → `src/twin_runtime/application/calibration/`
- Move: `compiler/compiler.py` → `src/twin_runtime/application/compiler/persona_compiler.py`
- Modify: old files → backward-compat shims

- [ ] **Step 1: Copy calibration files to application/calibration/**

For each file (`event_collector.py`, `case_manager.py`, `fidelity_evaluator.py`, `state_updater.py`), copy and update imports:
- `..models.*` → `twin_runtime.domain.models.*`
- `..runtime import run` → `twin_runtime.application.pipeline.runner import run`

`fidelity_evaluator.py` imports the pipeline: `from ..runtime import run as run_pipeline` — change to:
```python
from twin_runtime.application.pipeline.runner import run as run_pipeline
```

- [ ] **Step 2: Copy compiler to application/compiler/persona_compiler.py**

Update imports:
```python
from twin_runtime.domain.models.primitives import DomainEnum
from twin_runtime.domain.models.twin_state import TwinState
from twin_runtime.domain.evidence.base import EvidenceFragment, EvidenceType
from twin_runtime.domain.evidence.types import (
    DecisionEvidence, PreferenceEvidence, ReflectionEvidence,
)
from twin_runtime.infrastructure.sources.registry import SourceRegistry  # will be moved later
from twin_runtime.runtime.llm_client import ask_json  # will be moved later
```

Note: `SourceRegistry` and `llm_client` haven't been moved yet. For now, use the old import paths via backward-compat shims. These will resolve correctly since the shims exist.

Actually, use the CURRENT working import paths: `twin_runtime.sources.registry` and `twin_runtime.runtime.llm_client`. These still work via shims.

- [ ] **Step 3: Replace old files with shims**

`src/twin_runtime/compiler/compiler.py`:
```python
"""Backward-compat shim."""
from twin_runtime.application.compiler.persona_compiler import *  # noqa: F401,F403
```

`src/twin_runtime/compiler/__init__.py`:
```python
"""Backward-compat shim."""
from twin_runtime.application.compiler.persona_compiler import PersonaCompiler  # noqa: F401

__all__ = ["PersonaCompiler"]
```

Each calibration file shim MUST use wildcard imports (`from ... import *`) to preserve private functions like `_choice_similarity` in `fidelity_evaluator.py` that may be used internally. Example for each file:
```python
# src/twin_runtime/calibration/event_collector.py
"""Backward-compat shim."""
from twin_runtime.application.calibration.event_collector import *  # noqa: F401,F403
```
```python
# src/twin_runtime/calibration/case_manager.py
"""Backward-compat shim."""
from twin_runtime.application.calibration.case_manager import *  # noqa: F401,F403
```
```python
# src/twin_runtime/calibration/fidelity_evaluator.py
"""Backward-compat shim."""
from twin_runtime.application.calibration.fidelity_evaluator import *  # noqa: F401,F403
```
```python
# src/twin_runtime/calibration/state_updater.py
"""Backward-compat shim."""
from twin_runtime.application.calibration.state_updater import *  # noqa: F401,F403
```

Update `src/twin_runtime/calibration/__init__.py`:
```python
"""Backward-compat shim."""
from twin_runtime.application.calibration.event_collector import collect_event  # noqa: F401
from twin_runtime.application.calibration.case_manager import promote_candidate  # noqa: F401
from twin_runtime.application.calibration.fidelity_evaluator import evaluate_fidelity  # noqa: F401
from twin_runtime.application.calibration.state_updater import apply_evaluation  # noqa: F401

__all__ = ["collect_event", "promote_candidate", "evaluate_fidelity", "apply_evaluation"]
```

Update `src/twin_runtime/application/calibration/__init__.py`:
```python
"""Application calibration — the flywheel that makes the twin learn."""
from .event_collector import collect_event
from .case_manager import promote_candidate
from .fidelity_evaluator import evaluate_fidelity
from .state_updater import apply_evaluation

__all__ = ["collect_event", "promote_candidate", "evaluate_fidelity", "apply_evaluation"]
```

Update `src/twin_runtime/application/compiler/__init__.py`:
```python
"""Application compiler — evidence → TwinState compilation."""
from .persona_compiler import PersonaCompiler

__all__ = ["PersonaCompiler"]
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/ --ignore=tests/test_pipeline_integration.py --ignore=tests/test_full_cycle.py -v`
Expected: ALL 131 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/application/calibration/ src/twin_runtime/application/compiler/ src/twin_runtime/calibration/ src/twin_runtime/compiler/
git commit -m "refactor: move calibration + compiler to application/"
```

---

### Task 6: Move infrastructure layer (backends, sources, LLM)

**Files:**
- Move: `store/twin_store.py` → `infrastructure/backends/json_file/twin_store.py`
- Move: `store/calibration_store.py` → `infrastructure/backends/json_file/calibration_store.py`
- Move: `runtime/llm_client.py` → `infrastructure/llm/client.py`
- Move: source adapters + registry → `infrastructure/sources/`
- Modify: old files → backward-compat shims

- [ ] **Step 1: Copy store files to infrastructure/backends/json_file/**

`infrastructure/backends/json_file/twin_store.py` — Copy from `store/twin_store.py`, update import:
```python
from twin_runtime.domain.models.twin_state import TwinState
```

`infrastructure/backends/json_file/calibration_store.py` — Copy from `store/calibration_store.py`, update imports:
```python
from twin_runtime.domain.models.calibration import CalibrationCase, CandidateCalibrationCase, TwinEvaluation
from twin_runtime.domain.models.runtime import RuntimeEvent
```

`infrastructure/backends/json_file/__init__.py`:
```python
"""JSON file backend — default storage implementation."""
from .twin_store import TwinStore
from .calibration_store import CalibrationStore

__all__ = ["TwinStore", "CalibrationStore"]
```

- [ ] **Step 2: Copy LLM client to infrastructure/llm/**

`infrastructure/llm/client.py` — Copy from `runtime/llm_client.py`. No internal imports to domain (it only uses anthropic SDK).

`infrastructure/llm/__init__.py`:
```python
"""LLM client — Anthropic API adapter."""
from .client import ask_json, ask_text

__all__ = ["ask_json", "ask_text"]
```

- [ ] **Step 3: Copy source adapters to infrastructure/sources/**

Copy these files: `registry.py`, `openclaw_adapter.py`, `notion_adapter.py`, `gmail_adapter.py`, `calendar_adapter.py`, `document_adapter.py`, `google_auth.py`.

For each, update imports:
- `from .base import ...` → `from twin_runtime.domain.evidence.base import ...`
- `from .evidence_types import ...` → `from twin_runtime.domain.evidence.types import ...`
- `from ..models.primitives import ...` → `from twin_runtime.domain.models.primitives import ...`

`infrastructure/sources/__init__.py`:
```python
"""Infrastructure source adapters — data source IO."""
from twin_runtime.domain.evidence.base import SourceAdapter, EvidenceFragment, EvidenceType
from .registry import SourceRegistry
from .openclaw_adapter import OpenClawAdapter
from .document_adapter import DocumentAdapter
from .notion_adapter import NotionAdapter
from .gmail_adapter import GmailAdapter
from .calendar_adapter import CalendarAdapter

__all__ = [
    "SourceAdapter", "EvidenceFragment", "EvidenceType", "SourceRegistry",
    "OpenClawAdapter", "DocumentAdapter", "NotionAdapter",
    "GmailAdapter", "CalendarAdapter",
]
```

- [ ] **Step 4: Replace old files with backward-compat shims**

`src/twin_runtime/store/twin_store.py`:
```python
"""Backward-compat shim."""
from twin_runtime.infrastructure.backends.json_file.twin_store import *  # noqa: F401,F403
```

Same pattern for `store/calibration_store.py`, `runtime/llm_client.py`, and all files in `sources/` (registry, adapters, google_auth).

Update `src/twin_runtime/store/__init__.py`:
```python
"""Backward-compat shim."""
from twin_runtime.infrastructure.backends.json_file.twin_store import TwinStore  # noqa: F401
from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore  # noqa: F401
```

Update `src/twin_runtime/sources/__init__.py` to re-export from infrastructure:
```python
"""Backward-compat shim."""
from twin_runtime.domain.evidence.base import SourceAdapter, EvidenceFragment, EvidenceType
from twin_runtime.infrastructure.sources.registry import SourceRegistry
from twin_runtime.infrastructure.sources.openclaw_adapter import OpenClawAdapter
from twin_runtime.infrastructure.sources.document_adapter import DocumentAdapter
from twin_runtime.infrastructure.sources.notion_adapter import NotionAdapter
from twin_runtime.infrastructure.sources.gmail_adapter import GmailAdapter
from twin_runtime.infrastructure.sources.calendar_adapter import CalendarAdapter
from twin_runtime.domain.evidence.types import (
    DecisionEvidence, PreferenceEvidence, BehaviorEvidence,
    ReflectionEvidence, InteractionStyleEvidence, ContextEvidence,
    migrate_fragment,
)

__all__ = [
    "SourceAdapter", "EvidenceFragment", "EvidenceType", "SourceRegistry",
    "OpenClawAdapter", "DocumentAdapter", "NotionAdapter",
    "GmailAdapter", "CalendarAdapter",
    "DecisionEvidence", "PreferenceEvidence", "BehaviorEvidence",
    "ReflectionEvidence", "InteractionStyleEvidence", "ContextEvidence",
    "migrate_fragment",
]
```

- [ ] **Step 5: Run ALL tests**

Run: `python3 -m pytest tests/ --ignore=tests/test_pipeline_integration.py --ignore=tests/test_full_cycle.py -v`
Expected: ALL 131 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/twin_runtime/infrastructure/ src/twin_runtime/store/ src/twin_runtime/sources/ src/twin_runtime/runtime/llm_client.py
git commit -m "refactor: move stores, source adapters, LLM client to infrastructure/"
```

---

## Chunk 3: Interfaces, Cleanup, Port Implementation (Tasks 7-10)

### Task 7: Move CLI to interfaces/ + update pyproject.toml

**Files:**
- Move: `src/twin_runtime/cli.py` → `src/twin_runtime/interfaces/cli.py`
- Modify: `pyproject.toml` (entry point)
- Modify: `src/twin_runtime/cli.py` (backward-compat shim)

- [ ] **Step 1: Copy CLI to interfaces/**

`src/twin_runtime/interfaces/cli.py` — Copy from `cli.py`. The CLI uses config paths and imports from `store` and `models`. Update any imports to use the backward-compat paths (they still work). No immediate import changes needed since all old paths still resolve.

- [ ] **Step 2: Replace old cli.py with shim**

`src/twin_runtime/cli.py`:
```python
"""Backward-compat shim."""
from twin_runtime.interfaces.cli import *  # noqa: F401,F403
```

- [ ] **Step 3: Update pyproject.toml entry point**

Change:
```toml
[project.scripts]
twin-runtime = "twin_runtime.interfaces.cli:main"
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/interfaces/cli.py src/twin_runtime/cli.py pyproject.toml
git commit -m "refactor: move CLI to interfaces/"
```

---

### Task 8: Update all imports to new paths + remove backward-compat shims

**Files:**
- Modify: ALL test files (update imports)
- Modify: ALL application/ files (update any remaining old-path imports)
- Modify: `src/twin_runtime/conftest.py` if it exists
- Remove: backward-compat content from old files

This is the final cleanup. After this task, the old package structure directories become empty `__init__.py` re-export files (kept for any external consumers) or are removed.

- [ ] **Step 1: Update all test file imports**

For each test file, update imports from old paths to new paths. The mapping:

| Old import path | New import path |
|---|---|
| `twin_runtime.models.primitives` | `twin_runtime.domain.models.primitives` |
| `twin_runtime.models.twin_state` | `twin_runtime.domain.models.twin_state` |
| `twin_runtime.models.calibration` | `twin_runtime.domain.models.calibration` |
| `twin_runtime.models.runtime` | `twin_runtime.domain.models.runtime` |
| `twin_runtime.models` (TwinState) | `twin_runtime.domain.models` |
| `twin_runtime.sources.base` | `twin_runtime.domain.evidence.base` |
| `twin_runtime.sources.evidence_types` | `twin_runtime.domain.evidence.types` |
| `twin_runtime.sources.clustering` | `twin_runtime.domain.evidence.clustering` |
| `twin_runtime.sources.registry` | `twin_runtime.infrastructure.sources.registry` |
| `twin_runtime.sources.openclaw_adapter` | `twin_runtime.infrastructure.sources.openclaw_adapter` |
| `twin_runtime.sources.document_adapter` | `twin_runtime.infrastructure.sources.document_adapter` |
| `twin_runtime.sources.gmail_adapter` | `twin_runtime.infrastructure.sources.gmail_adapter` |
| `twin_runtime.sources.calendar_adapter` | `twin_runtime.infrastructure.sources.calendar_adapter` |
| `twin_runtime.compiler.compiler` | `twin_runtime.application.compiler.persona_compiler` |
| `twin_runtime.calibration.*` | `twin_runtime.application.calibration.*` |
| `twin_runtime.runtime` (run) | `twin_runtime.application.pipeline` |
| `twin_runtime.runtime.conflict_arbiter` | `twin_runtime.application.pipeline.conflict_arbiter` |
| `twin_runtime.runtime.situation_interpreter` | `twin_runtime.application.pipeline.situation_interpreter` |
| `twin_runtime.store.twin_store` | `twin_runtime.infrastructure.backends.json_file.twin_store` |
| `twin_runtime.store.calibration_store` | `twin_runtime.infrastructure.backends.json_file.calibration_store` |
| `twin_runtime.cli` | `twin_runtime.interfaces.cli` |

Apply these changes to every test file. This is mechanical but must be precise.

- [ ] **Step 2: Update cross-references in application/ files**

In `application/compiler/persona_compiler.py`, update any imports still pointing to old paths:
```python
# Update to:
from twin_runtime.infrastructure.sources.registry import SourceRegistry
from twin_runtime.infrastructure.llm.client import ask_json
```

In `application/calibration/fidelity_evaluator.py`:
```python
from twin_runtime.application.pipeline.runner import run as run_pipeline
```

Check all application/ files for any remaining `twin_runtime.runtime.*`, `twin_runtime.sources.*`, `twin_runtime.store.*` imports and update them.

- [ ] **Step 3: Keep backward-compat shims as thin re-exports**

Do NOT delete the old directories yet — they serve as backward-compat for any external consumers. But ensure each shim file is minimal (just re-exports). This is already done from previous tasks.

- [ ] **Step 4: Run ALL tests (full suite)**

Run: `python3 -m pytest tests/ -v`
Expected: ALL PASS (131+ tests including pipeline_integration and full_cycle)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: update all imports to 4-layer paths"
```

---

### Task 9: Implement port protocols on JsonFile stores

**Files:**
- Modify: `src/twin_runtime/infrastructure/backends/json_file/twin_store.py`
- Modify: `src/twin_runtime/infrastructure/backends/json_file/calibration_store.py`
- Create: `tests/test_backend_protocols.py`

- [ ] **Step 1: Write tests for port compliance**

```python
# tests/test_backend_protocols.py
"""Tests that JsonFile backends satisfy port protocols."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from twin_runtime.domain.ports.twin_state_store import TwinStateStore
from twin_runtime.domain.ports.calibration_store import CalibrationStore as CalibrationStorePort
from twin_runtime.infrastructure.backends.json_file.twin_store import TwinStore
from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore


def _load_sample_twin():
    """Load the sample twin from fixtures (same as conftest sample_twin fixture)."""
    import json
    fixtures_dir = Path(__file__).parent / "fixtures"
    data = json.loads((fixtures_dir / "sample_twin_state.json").read_text(encoding="utf-8"))
    from twin_runtime.domain.models.twin_state import TwinState as TS
    return TS.model_validate(data)


class TestTwinStoreProtocol:
    def test_implements_protocol(self):
        """TwinStore should satisfy TwinStateStore protocol."""
        assert isinstance(TwinStore(tempfile.mkdtemp()), TwinStateStore)

    def test_save_state_method(self, tmp_path):
        store = TwinStore(tmp_path / "twins")
        twin = _load_sample_twin()
        result = store.save_state(twin)
        assert isinstance(result, str)

    def test_load_state_method(self, tmp_path):
        store = TwinStore(tmp_path / "twins")
        twin = _load_sample_twin()
        store.save_state(twin)
        loaded = store.load_state(twin.user_id)
        assert loaded.user_id == twin.user_id


class TestCalibrationStoreProtocol:
    def test_implements_protocol(self, tmp_path):
        """CalibrationStore should satisfy CalibrationStore port protocol."""
        store = CalibrationStore(str(tmp_path), "user-test")
        assert isinstance(store, CalibrationStorePort)
```

- [ ] **Step 2: Run tests to verify they fail**

The current `TwinStore` has `save()` not `save_state()`, and `load()` not `load_state()`. Tests will fail.

- [ ] **Step 3: Add protocol-compliant methods to TwinStore**

In `infrastructure/backends/json_file/twin_store.py`, add protocol-compliant method aliases:

```python
def save_state(self, state: TwinState) -> str:
    """Protocol-compliant: save TwinState, return version string."""
    path = self.save(state)
    return state.state_version

def load_state(self, user_id: str, version: Optional[str] = None) -> TwinState:
    """Protocol-compliant: load TwinState."""
    return self.load(user_id, version)
```

Keep the old `save()` and `load()` methods for backward compatibility.

- [ ] **Step 4: Add protocol-compliant methods to CalibrationStore**

In `infrastructure/backends/json_file/calibration_store.py`, the existing methods already match the protocol closely. Add any missing methods:

```python
def save_event(self, event: RuntimeEvent) -> str:
    """Protocol-compliant: returns event_id."""
    path = self.base / "events" / f"{event.event_id}.json"
    path.write_text(event.model_dump_json(indent=2))
    return event.event_id

def save_candidate(self, candidate: CandidateCalibrationCase) -> str:
    """Protocol-compliant: returns candidate_id."""
    path = self.base / "candidates" / f"{candidate.candidate_id}.json"
    path.write_text(candidate.model_dump_json(indent=2))
    return candidate.candidate_id

def save_case(self, case: CalibrationCase) -> str:
    """Protocol-compliant: returns case_id."""
    path = self.base / "cases" / f"{case.case_id}.json"
    path.write_text(case.model_dump_json(indent=2))
    return case.case_id

def save_evaluation(self, evaluation: TwinEvaluation) -> str:
    """Protocol-compliant: returns evaluation_id."""
    path = self.base / "evaluations" / f"{evaluation.evaluation_id}.json"
    path.write_text(evaluation.model_dump_json(indent=2))
    return evaluation.evaluation_id
```

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/test_backend_protocols.py tests/test_store.py tests/test_calibration.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run full test suite**

Run: `python3 -m pytest tests/ --ignore=tests/test_pipeline_integration.py --ignore=tests/test_full_cycle.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/twin_runtime/infrastructure/backends/json_file/ tests/test_backend_protocols.py
git commit -m "feat: JsonFile backends implement port protocols (TwinStateStore, CalibrationStore)"
```

---

### Task 10: Implement EvidenceStore + TraceStore JsonFile backends

The spec requires all four store protocols to have JsonFile implementations. Task 9 covers TwinStateStore and CalibrationStore. This task adds EvidenceStore and TraceStore.

**Files:**
- Create: `src/twin_runtime/infrastructure/backends/json_file/evidence_store.py`
- Create: `src/twin_runtime/infrastructure/backends/json_file/trace_store.py`
- Modify: `src/twin_runtime/infrastructure/backends/json_file/__init__.py`
- Modify: `tests/test_backend_protocols.py`

- [ ] **Step 1: Write failing tests for EvidenceStore and TraceStore protocols**

Add to `tests/test_backend_protocols.py`:

```python
from twin_runtime.domain.ports.evidence_store import EvidenceStore as EvidenceStorePort
from twin_runtime.domain.ports.trace_store import TraceStore as TraceStorePort
from twin_runtime.infrastructure.backends.json_file.evidence_store import JsonFileEvidenceStore
from twin_runtime.infrastructure.backends.json_file.trace_store import JsonFileTraceStore
from twin_runtime.domain.evidence.base import EvidenceFragment, EvidenceType
from twin_runtime.domain.models.runtime import RuntimeDecisionTrace
from twin_runtime.domain.models.primitives import DomainEnum, DecisionMode


class TestEvidenceStoreProtocol:
    def test_implements_protocol(self, tmp_path):
        store = JsonFileEvidenceStore(tmp_path / "evidence")
        assert isinstance(store, EvidenceStorePort)

    def test_store_and_retrieve_fragment(self, tmp_path):
        store = JsonFileEvidenceStore(tmp_path / "evidence")
        now = datetime.now(timezone.utc)
        frag = EvidenceFragment(
            source_type="test",
            source_id="test-001",
            evidence_type=EvidenceType.DECISION,
            user_id="user-1",
            occurred_at=now,
            valid_from=now,
            raw_excerpt="test content",
            summary="test summary",
        )
        frag_id = store.store_fragment(frag)
        assert isinstance(frag_id, str)
        retrieved = store.get_by_hash(frag.content_hash)
        assert retrieved is not None
        assert retrieved.content_hash == frag.content_hash

    def test_count(self, tmp_path):
        store = JsonFileEvidenceStore(tmp_path / "evidence")
        assert store.count("user-1") == 0


class TestTraceStoreProtocol:
    def test_implements_protocol(self, tmp_path):
        store = JsonFileTraceStore(tmp_path / "traces")
        assert isinstance(store, TraceStorePort)

    def test_save_and_load_trace(self, tmp_path):
        from datetime import datetime, timezone
        store = JsonFileTraceStore(tmp_path / "traces")
        trace = RuntimeDecisionTrace(
            trace_id="trace-001",
            twin_state_version="v001",
            situation_frame_id="sf-001",
            activated_domains=[DomainEnum.CAREER],
            head_assessments=[{
                "domain": DomainEnum.CAREER,
                "head_version": "v1",
                "option_ranking": ["A"],
                "utility_decomposition": {"growth": 0.8},
                "confidence": 0.7,
            }],
            final_decision="A",
            decision_mode=DecisionMode.SINGLE_HEAD,
            uncertainty=0.3,
            created_at=datetime.now(timezone.utc),
        )
        trace_id = store.save_trace(trace)
        assert trace_id == "trace-001"
        loaded = store.load_trace("trace-001")
        assert loaded.trace_id == trace.trace_id

    def test_list_traces(self, tmp_path):
        store = JsonFileTraceStore(tmp_path / "traces")
        assert store.list_traces("user-1") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_backend_protocols.py -v`
Expected: ImportError (modules don't exist yet)

- [ ] **Step 3: Implement JsonFileEvidenceStore**

```python
# src/twin_runtime/infrastructure/backends/json_file/evidence_store.py
"""JSON file implementation of EvidenceStore protocol."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from twin_runtime.domain.evidence.base import EvidenceFragment
from twin_runtime.domain.evidence.clustering import EvidenceCluster


class JsonFileEvidenceStore:
    """Store evidence fragments as JSON files, indexed by content_hash."""

    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)
        (self.base / "fragments").mkdir(exist_ok=True)
        (self.base / "clusters").mkdir(exist_ok=True)

    def store_fragment(self, fragment: EvidenceFragment) -> str:
        path = self.base / "fragments" / f"{fragment.content_hash}.json"
        path.write_text(fragment.model_dump_json(indent=2))
        return fragment.content_hash

    def store_cluster(self, cluster: EvidenceCluster) -> str:
        path = self.base / "clusters" / f"{cluster.cluster_id}.json"
        path.write_text(cluster.model_dump_json(indent=2))
        return cluster.cluster_id

    def query(self, query) -> List[EvidenceFragment]:
        # Basic implementation — scan all fragments, filter by user_id
        results = []
        for p in (self.base / "fragments").glob("*.json"):
            frag = EvidenceFragment.model_validate_json(p.read_text())
            if hasattr(query, "user_id") and frag.user_id == query.user_id:
                results.append(frag)
        return results

    def get_by_hash(self, content_hash: str) -> Optional[EvidenceFragment]:
        path = self.base / "fragments" / f"{content_hash}.json"
        if path.exists():
            return EvidenceFragment.model_validate_json(path.read_text())
        return None

    def count(self, user_id: str, filters: Optional[Dict] = None) -> int:
        count = 0
        for p in (self.base / "fragments").glob("*.json"):
            frag = EvidenceFragment.model_validate_json(p.read_text())
            if frag.user_id == user_id:
                count += 1
        return count
```

- [ ] **Step 4: Implement JsonFileTraceStore**

```python
# src/twin_runtime/infrastructure/backends/json_file/trace_store.py
"""JSON file implementation of TraceStore protocol."""

from __future__ import annotations

from pathlib import Path
from typing import List

from twin_runtime.domain.models.runtime import RuntimeDecisionTrace


class JsonFileTraceStore:
    """Store runtime decision traces as JSON files."""

    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    def save_trace(self, trace: RuntimeDecisionTrace) -> str:
        path = self.base / f"{trace.trace_id}.json"
        path.write_text(trace.model_dump_json(indent=2))
        return trace.trace_id

    def load_trace(self, trace_id: str) -> RuntimeDecisionTrace:
        path = self.base / f"{trace_id}.json"
        return RuntimeDecisionTrace.model_validate_json(path.read_text())

    def list_traces(self, user_id: str, limit: int = 50) -> List[str]:
        # Scan traces and filter by twin_state user context
        # For now, return all trace IDs up to limit
        return [p.stem for p in sorted(self.base.glob("*.json"))[:limit]]
```

- [ ] **Step 5: Update json_file __init__.py**

```python
# src/twin_runtime/infrastructure/backends/json_file/__init__.py
"""JSON file backend implementations."""
from .twin_store import TwinStore
from .calibration_store import CalibrationStore
from .evidence_store import JsonFileEvidenceStore
from .trace_store import JsonFileTraceStore

__all__ = ["TwinStore", "CalibrationStore", "JsonFileEvidenceStore", "JsonFileTraceStore"]
```

- [ ] **Step 6: Run tests**

Run: `python3 -m pytest tests/test_backend_protocols.py -v`
Expected: ALL PASS

- [ ] **Step 7: Run full test suite**

Run: `python3 -m pytest tests/ --ignore=tests/test_pipeline_integration.py --ignore=tests/test_full_cycle.py -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add src/twin_runtime/infrastructure/backends/json_file/evidence_store.py src/twin_runtime/infrastructure/backends/json_file/trace_store.py src/twin_runtime/infrastructure/backends/json_file/__init__.py tests/test_backend_protocols.py
git commit -m "feat: JsonFile EvidenceStore + TraceStore implement port protocols"
```

---

## Summary

| Task | What it does | Key risk |
|------|-------------|----------|
| 1 | Create skeleton + move domain/models | Internal import paths |
| 2 | Move evidence to domain/evidence | Cross-module re-exports |
| 3 | Create port protocols + RecallQuery | New code, low risk |
| 4 | Move pipeline to application/pipeline | LLM client import chain |
| 5 | Move calibration + compiler to application | Cross-layer imports |
| 6 | Move stores + sources + LLM to infrastructure | Many files, shim accuracy |
| 7 | Move CLI to interfaces + update entry point | pyproject.toml change |
| 8 | Update ALL imports to new paths | Largest change, most risk |
| 9 | Implement port protocols on JsonFile stores (TwinStateStore, CalibrationStore) | Method signature alignment |
| 10 | Implement EvidenceStore + TraceStore JsonFile backends | New code, spec completeness |

**Total new tests:** ~16 (port protocol tests + backend compliance + evidence/trace stores)
**Expected test count after:** 147+

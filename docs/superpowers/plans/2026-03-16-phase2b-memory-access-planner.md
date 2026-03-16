# Phase 2b: Memory Access Planner + Pipeline DI Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add rule-based Memory Access Planner to the runtime pipeline and fix hexagonal architecture DI violations.

**Architecture:** The planner sits between Situation Interpreter and Head Activator, issuing RecallQueries against the EvidenceStore port. Pipeline stages receive LLMPort via dependency injection instead of importing infrastructure directly. The `interfaces/defaults.py` wiring layer provides the default concrete implementations.

**Tech Stack:** Python 3.9+, Pydantic v2, typing.Protocol, existing pytest infrastructure

**Spec:** `docs/superpowers/specs/2026-03-16-phase2b-memory-access-planner-design.md`

---

## File Map

| File | Layer | Action |
|------|-------|--------|
| `src/twin_runtime/domain/models/planner.py` | domain | CREATE — MemoryAccessPlan, EnrichedActivationContext |
| `src/twin_runtime/domain/models/runtime.py` | domain | MODIFY — add planner audit fields to RuntimeDecisionTrace |
| `src/twin_runtime/interfaces/defaults.py` | interfaces | CREATE — DefaultLLM adapter |
| `src/twin_runtime/application/planner/__init__.py` | application | CREATE |
| `src/twin_runtime/application/planner/memory_access_planner.py` | application | CREATE — plan_memory_access() |
| `src/twin_runtime/application/pipeline/runner.py` | application | MODIFY — add DI params + planner step |
| `src/twin_runtime/application/pipeline/situation_interpreter.py` | application | MODIFY — accept llm param, remove infra import |
| `src/twin_runtime/application/pipeline/head_activator.py` | application | MODIFY — accept EnrichedActivationContext + llm param |
| `src/twin_runtime/application/pipeline/decision_synthesizer.py` | application | MODIFY — accept llm param, remove infra import |
| `src/twin_runtime/application/compiler/persona_compiler.py` | application | MODIFY — accept llm param, remove infra import |
| `tests/test_planner.py` | tests | CREATE |
| `tests/test_pipeline_di.py` | tests | CREATE |
| `tests/test_planner_integration.py` | tests | CREATE |

---

## Chunk 1: Domain Models + DefaultLLM (Tasks 1-2)

### Task 1: Create planner domain models

**Files:**
- Create: `src/twin_runtime/domain/models/planner.py`
- Modify: `src/twin_runtime/domain/models/runtime.py`
- Test: `tests/test_planner_models.py`

- [ ] **Step 1: Write failing tests for planner models**

```python
# tests/test_planner_models.py
"""Tests for Memory Access Planner domain models."""

from twin_runtime.domain.models.planner import MemoryAccessPlan, EnrichedActivationContext
from twin_runtime.domain.models.recall_query import RecallQuery
from twin_runtime.domain.models.primitives import DomainEnum
from twin_runtime.domain.evidence.base import EvidenceType


class TestMemoryAccessPlan:
    def test_create_empty_plan(self):
        plan = MemoryAccessPlan(
            queries=[],
            execution_strategy="parallel",
            total_evidence_budget=10,
            per_query_limit=5,
            freshness_preference="balanced",
            disabled_evidence_types=[],
            rationale="No signals matched",
        )
        assert plan.queries == []
        assert plan.total_evidence_budget == 10

    def test_create_plan_with_queries(self):
        q = RecallQuery(
            query_type="by_domain",
            user_id="user-1",
            target_domain=DomainEnum.WORK,
        )
        plan = MemoryAccessPlan(
            queries=[q],
            execution_strategy="parallel",
            total_evidence_budget=10,
            per_query_limit=5,
            freshness_preference="recent_first",
            disabled_evidence_types=[EvidenceType.CONTEXT],
            rationale="Multi-domain activation",
            domains_to_activate=[DomainEnum.WORK],
            skipped_domains={DomainEnum.MONEY: "reliability 0.30 < 0.50"},
        )
        assert len(plan.queries) == 1
        assert plan.freshness_preference == "recent_first"
        assert plan.domains_to_activate == [DomainEnum.WORK]
        assert DomainEnum.MONEY in plan.skipped_domains

    def test_enriched_activation_context(self):
        """EnrichedActivationContext requires twin, frame, evidence, rationale."""
        # Just test it's importable and has the right fields
        from twin_runtime.domain.models.planner import EnrichedActivationContext
        assert hasattr(EnrichedActivationContext, "model_fields")
        fields = set(EnrichedActivationContext.model_fields.keys())
        assert {"twin", "frame", "retrieved_evidence", "retrieval_rationale"} <= fields


class TestRuntimeDecisionTraceAudit:
    def test_trace_has_planner_fields(self):
        """RuntimeDecisionTrace should have optional planner audit fields."""
        from twin_runtime.domain.models.runtime import RuntimeDecisionTrace
        fields = RuntimeDecisionTrace.model_fields
        assert "memory_access_plan" in fields
        assert "retrieved_evidence_count" in fields
        assert "skipped_domains" in fields
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_planner_models.py -v`
Expected: FAIL (ImportError — planner.py doesn't exist)

- [ ] **Step 3: Create `domain/models/planner.py`**

```python
# src/twin_runtime/domain/models/planner.py
"""Memory Access Planner domain models."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from twin_runtime.domain.evidence.base import EvidenceFragment, EvidenceType
from twin_runtime.domain.models.primitives import DomainEnum
from twin_runtime.domain.models.recall_query import RecallQuery
from twin_runtime.domain.models.situation import SituationFrame
from twin_runtime.domain.models.twin_state import TwinState


class MemoryAccessPlan(BaseModel):
    """Output of the planner: what evidence to retrieve and how."""

    queries: List[RecallQuery] = Field(default_factory=list)
    execution_strategy: Literal["parallel", "sequential", "conditional"] = "parallel"
    total_evidence_budget: int = Field(default=10, ge=0)
    per_query_limit: int = Field(default=5, ge=0)
    freshness_preference: Literal["recent_first", "historical_first", "balanced"] = "balanced"
    disabled_evidence_types: List[EvidenceType] = Field(default_factory=list)
    rationale: str = ""
    # Domain gating — Planner decides which heads to activate
    domains_to_activate: List[DomainEnum] = Field(default_factory=list)
    skipped_domains: Dict[DomainEnum, str] = Field(default_factory=dict)


class EnrichedActivationContext(BaseModel):
    """What Head Activator receives after Planner enrichment."""

    twin: TwinState
    frame: SituationFrame
    retrieved_evidence: List[EvidenceFragment] = Field(default_factory=list)
    retrieval_rationale: str = ""
```

- [ ] **Step 4: Add planner audit fields to RuntimeDecisionTrace**

In `src/twin_runtime/domain/models/runtime.py`, add these optional fields to `RuntimeDecisionTrace`:

```python
# Add import at top:
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING
if TYPE_CHECKING:
    from twin_runtime.domain.models.planner import MemoryAccessPlan

# Add to RuntimeDecisionTrace class, after output_text field:
    memory_access_plan: Optional[Any] = Field(
        default=None, description="MemoryAccessPlan used for this decision (audit)"
    )
    retrieved_evidence_count: int = Field(
        default=0, description="Number of evidence fragments retrieved by planner"
    )
    skipped_domains: Dict[str, str] = Field(
        default_factory=dict, description="Domains skipped by planner gating, with reasons"
    )
```

Note: Use `Optional[Any]` instead of `Optional[MemoryAccessPlan]` to avoid circular import. The planner module imports from runtime.py's sibling modules. We use `Any` with a TYPE_CHECKING guard for documentation.

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/test_planner_models.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run full suite**

Run: `python3 -m pytest tests/ --ignore=tests/test_pipeline_integration.py --ignore=tests/test_full_cycle.py -v`
Expected: ALL 148+ tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/twin_runtime/domain/models/planner.py src/twin_runtime/domain/models/runtime.py tests/test_planner_models.py
git commit -m "feat: planner domain models (MemoryAccessPlan, EnrichedActivationContext) + trace audit fields"
```

---

### Task 2: Create DefaultLLM adapter in interfaces/

**Files:**
- Create: `src/twin_runtime/interfaces/defaults.py`
- Test: `tests/test_defaults.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_defaults.py
"""Tests for default infrastructure wiring."""

from twin_runtime.domain.ports.llm_port import LLMPort


class TestDefaultLLM:
    def test_implements_protocol(self):
        from twin_runtime.interfaces.defaults import DefaultLLM
        llm = DefaultLLM()
        assert isinstance(llm, LLMPort)

    def test_has_ask_json(self):
        from twin_runtime.interfaces.defaults import DefaultLLM
        llm = DefaultLLM()
        assert callable(llm.ask_json)

    def test_has_ask_text(self):
        from twin_runtime.interfaces.defaults import DefaultLLM
        llm = DefaultLLM()
        assert callable(llm.ask_text)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_defaults.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Create `interfaces/defaults.py`**

```python
# src/twin_runtime/interfaces/defaults.py
"""Default infrastructure wiring.

The interfaces layer is the correct place to bridge application ports to
infrastructure implementations. Application code imports ports (protocols);
this module provides the concrete defaults.
"""

from __future__ import annotations

from typing import Any, Dict


class DefaultLLM:
    """Adapts infrastructure.llm.client functions to LLMPort protocol."""

    def ask_json(self, system: str, user: str, max_tokens: int = 1024) -> Dict[str, Any]:
        from twin_runtime.infrastructure.llm.client import ask_json
        return ask_json(system, user, max_tokens)

    def ask_text(self, system: str, user: str, max_tokens: int = 1024) -> str:
        from twin_runtime.infrastructure.llm.client import ask_text
        return ask_text(system, user, max_tokens)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_defaults.py tests/test_planner_models.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/interfaces/defaults.py tests/test_defaults.py
git commit -m "feat: DefaultLLM adapter in interfaces/ wiring layer"
```

---

## Chunk 2: Pipeline DI (Tasks 3-4)

### Task 3: Inject LLM into pipeline stages

This task modifies all 4 pipeline stages + compiler to accept an `llm` parameter and removes direct infrastructure imports. This is the highest-risk task.

**Files:**
- Modify: `src/twin_runtime/application/pipeline/situation_interpreter.py`
- Modify: `src/twin_runtime/application/pipeline/head_activator.py`
- Modify: `src/twin_runtime/application/pipeline/decision_synthesizer.py`
- Modify: `src/twin_runtime/application/compiler/persona_compiler.py`
- Create: `tests/test_pipeline_di.py`

- [ ] **Step 1: Write DI tests**

```python
# tests/test_pipeline_di.py
"""Tests that pipeline stages accept injected LLM and don't import infrastructure."""

import ast
import importlib
from pathlib import Path
from unittest.mock import MagicMock

from twin_runtime.domain.ports.llm_port import LLMPort


class TestNoInfrastructureImports:
    """Verify application/ files don't import from infrastructure/ at module level."""

    def _get_imports(self, filepath: str) -> list[str]:
        """Parse a Python file and return all import strings."""
        source = Path(filepath).read_text()
        tree = ast.parse(source)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
        return imports

    def test_situation_interpreter_no_infra(self):
        path = "src/twin_runtime/application/pipeline/situation_interpreter.py"
        imports = self._get_imports(path)
        infra = [i for i in imports if "infrastructure" in i]
        assert infra == [], f"Direct infrastructure imports found: {infra}"

    def test_head_activator_no_infra(self):
        path = "src/twin_runtime/application/pipeline/head_activator.py"
        imports = self._get_imports(path)
        infra = [i for i in imports if "infrastructure" in i]
        assert infra == [], f"Direct infrastructure imports found: {infra}"

    def test_decision_synthesizer_no_infra(self):
        path = "src/twin_runtime/application/pipeline/decision_synthesizer.py"
        imports = self._get_imports(path)
        infra = [i for i in imports if "infrastructure" in i]
        assert infra == [], f"Direct infrastructure imports found: {infra}"


class TestLLMInjection:
    """Verify pipeline stages accept an llm parameter."""

    def test_interpret_situation_accepts_llm(self):
        import inspect
        from twin_runtime.application.pipeline.situation_interpreter import interpret_situation
        sig = inspect.signature(interpret_situation)
        assert "llm" in sig.parameters

    def test_activate_heads_accepts_llm(self):
        import inspect
        from twin_runtime.application.pipeline.head_activator import activate_heads
        sig = inspect.signature(activate_heads)
        assert "llm" in sig.parameters

    def test_synthesize_accepts_llm(self):
        import inspect
        from twin_runtime.application.pipeline.decision_synthesizer import synthesize
        sig = inspect.signature(synthesize)
        assert "llm" in sig.parameters
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_pipeline_di.py -v`
Expected: FAIL (infrastructure imports still present, no llm params)

- [ ] **Step 3: Modify `situation_interpreter.py`**

Remove the direct infrastructure import:
```python
# REMOVE: from twin_runtime.infrastructure.llm.client import ask_json
```

Add `LLMPort` import and modify `interpret_situation` signature. The function currently calls `ask_json(system, user)` directly. Change every call to `llm.ask_json(system, user)`.

The function signature changes from:
```python
def interpret_situation(query: str, twin: TwinState) -> SituationFrame:
```
to:
```python
def interpret_situation(query: str, twin: TwinState, *, llm: LLMPort) -> SituationFrame:
```

Add at top:
```python
from twin_runtime.domain.ports.llm_port import LLMPort
```

Then replace all `ask_json(...)` calls with `llm.ask_json(...)`.

- [ ] **Step 4: Modify `head_activator.py`**

Remove:
```python
# REMOVE: from twin_runtime.infrastructure.llm.client import ask_json
```

Add:
```python
from twin_runtime.domain.ports.llm_port import LLMPort
```

Change `activate_heads` signature from:
```python
def activate_heads(query, option_set, frame, twin) -> List[HeadAssessment]:
```
to:
```python
def activate_heads(query, option_set, frame, twin, *, llm: LLMPort) -> List[HeadAssessment]:
```

Replace all `ask_json(...)` calls with `llm.ask_json(...)`.

- [ ] **Step 5: Modify `decision_synthesizer.py`**

Remove:
```python
# REMOVE: from twin_runtime.infrastructure.llm.client import ask_text
```

Add:
```python
from twin_runtime.domain.ports.llm_port import LLMPort
```

Change `synthesize` signature from:
```python
def synthesize(query, option_set, frame, assessments, conflict, twin) -> RuntimeDecisionTrace:
```
to:
```python
def synthesize(query, option_set, frame, assessments, conflict, twin, *, llm: LLMPort) -> RuntimeDecisionTrace:
```

Replace the `ask_text(...)` call in `_surface_realize` with `llm.ask_text(...)`. Since `_surface_realize` is a private helper, pass `llm` to it as a parameter too.

- [ ] **Step 6: Modify `persona_compiler.py`**

Remove:
```python
# REMOVE: from twin_runtime.infrastructure.llm.client import ask_json
```

Add:
```python
from twin_runtime.domain.ports.llm_port import LLMPort
```

Add `llm` parameter to `PersonaCompiler.__init__` (keep existing `registry` param):
```python
def __init__(self, registry: SourceRegistry, *, llm: Optional[LLMPort] = None):
    self.registry = registry
    self.evidence_graph = EvidenceGraph()
    self._llm = llm
```

In `extract_parameters`, the current code uses a self-module reference trick (`_self_mod.ask_json`) so that `unittest.mock.patch("...persona_compiler.ask_json", ...)` works. Change the method to prefer `self._llm` when available, and fall back to the existing module-level reference when not:

```python
def extract_parameters(self, fragments: List[EvidenceFragment]) -> Dict[str, Any]:
    # ... existing prompt construction code stays the same ...

    if self._llm is not None:
        return self._llm.ask_json(_EXTRACT_SYSTEM, user_msg, max_tokens=1024)
    # Fallback: keep module-level ask_json for backward compat + test patching
    import twin_runtime.application.compiler.persona_compiler as _self_mod
    return _self_mod.ask_json(_EXTRACT_SYSTEM, user_msg, max_tokens=1024)
```

**IMPORTANT:** Keep the module-level `from twin_runtime.infrastructure.llm.client import ask_json` import! It is needed as the patch target for existing tests in `test_compiler_typed_extraction.py` and `test_compiler_cold_start.py`. The DI path (`self._llm`) bypasses it; the fallback path uses the `_self_mod.ask_json` reference that resolves to the module-level import. Existing test patches on `twin_runtime.application.compiler.persona_compiler.ask_json` continue to work.

Note: The compiler keeps the module-level infrastructure import because it's called from many places (CLI, tests) that don't yet pass an LLM. The pipeline stages don't need this — `run()` always provides `llm`.

- [ ] **Step 7: Run DI tests**

Run: `python3 -m pytest tests/test_pipeline_di.py -v`
Expected: ALL PASS

- [ ] **Step 8: Run full suite (WILL FAIL — callers not updated yet)**

Run: `python3 -m pytest tests/ --ignore=tests/test_pipeline_integration.py --ignore=tests/test_full_cycle.py -q 2>&1 | tail -10`
Expected: Some failures in test_runtime_units.py (callers don't pass llm yet). This is expected — Task 4 fixes it.

- [ ] **Step 9: Commit (WIP — callers need updating)**

```bash
git add src/twin_runtime/application/pipeline/situation_interpreter.py src/twin_runtime/application/pipeline/head_activator.py src/twin_runtime/application/pipeline/decision_synthesizer.py src/twin_runtime/application/compiler/persona_compiler.py tests/test_pipeline_di.py
git commit -m "refactor: inject LLMPort into pipeline stages, remove infrastructure imports"
```

---

### Task 4: Update runner.py + fix all callers

**Files:**
- Modify: `src/twin_runtime/application/pipeline/runner.py`
- Modify: `tests/test_runtime_units.py`
- Modify: `tests/test_compiler_cold_start.py`
- Modify: `tests/test_compiler_typed_extraction.py`
- Modify: any other failing test files

- [ ] **Step 1: Update `runner.py` with DI + planner placeholder**

```python
# src/twin_runtime/application/pipeline/runner.py
"""Top-level runtime pipeline: query -> decision trace."""

from __future__ import annotations

from typing import List, Optional

from twin_runtime.domain.models.runtime import RuntimeDecisionTrace
from twin_runtime.domain.models.twin_state import TwinState
from twin_runtime.domain.ports.llm_port import LLMPort
from twin_runtime.domain.ports.evidence_store import EvidenceStore
from twin_runtime.application.pipeline.situation_interpreter import interpret_situation
from twin_runtime.application.pipeline.head_activator import activate_heads
from twin_runtime.application.pipeline.conflict_arbiter import arbitrate
from twin_runtime.application.pipeline.decision_synthesizer import synthesize


def run(
    query: str,
    option_set: List[str],
    twin: TwinState,
    *,
    llm: Optional[LLMPort] = None,
    evidence_store: Optional[EvidenceStore] = None,
) -> RuntimeDecisionTrace:
    """Execute the full runtime pipeline.

    Args:
        query: The decision scenario / question
        option_set: Explicit options to evaluate
        twin: The canonical TwinState
        llm: LLM port (defaults to infrastructure.llm.client via DefaultLLM)
        evidence_store: Evidence store for planner (None = skip evidence retrieval)
    """
    if llm is None:
        # ARCHITECTURE NOTE: interfaces/ should wire this, not application/.
        # Acceptable for v0.1; Phase 4 MCP Server introduces a proper composition root.
        from twin_runtime.interfaces.defaults import DefaultLLM
        llm = DefaultLLM()

    # 1. Situation Interpreter
    frame = interpret_situation(query, twin, llm=llm)

    # 2. Memory Access Planner (will be wired in Task 5)
    # For now, pass empty evidence to maintain backward compat
    evidence = []

    # 3. Head Activation
    assessments = activate_heads(query, option_set, frame, twin, llm=llm)

    # 4. Conflict Arbiter
    conflict = arbitrate(assessments)

    # 5. Decision Synthesis
    trace = synthesize(query, option_set, frame, assessments, conflict, twin, llm=llm)

    return trace
```

- [ ] **Step 2: Fix test callers**

In `tests/test_runtime_units.py`, the tests call `activate_heads`, `arbitrate`, etc. directly. These now require `llm=` for the LLM-using stages. Since these are unit tests with mocked responses, create a mock LLM:

Add at top of test file:
```python
from unittest.mock import MagicMock
from twin_runtime.domain.ports.llm_port import LLMPort
```

Create a mock helper and pass it to any direct calls. But first READ the test file to understand what it does — the tests may use monkeypatching which means the LLM is never actually called.

For compiler tests (`test_compiler_cold_start.py`, `test_compiler_typed_extraction.py`): these monkeypatch `ask_json`. Since the compiler has a lazy fallback, these should still work. Verify by running tests.

- [ ] **Step 3: Run ALL tests**

Run: `python3 -m pytest tests/ --ignore=tests/test_pipeline_integration.py --ignore=tests/test_full_cycle.py -v`
Expected: ALL PASS (148+ tests)

If any fail, fix the callers by passing `llm=` where needed.

- [ ] **Step 4: Update backward-compat shims**

The shims at `src/twin_runtime/runtime/pipeline.py` re-export from `application.pipeline.runner`. Since `run()` now has new optional params, the shim still works — wildcard import picks them up.

Verify: `python3 -c "from twin_runtime.runtime import run; import inspect; print(inspect.signature(run))"`
Expected: `(query: str, option_set: List[str], twin: TwinState, *, llm: Optional[...] = None, evidence_store: Optional[...] = None) -> RuntimeDecisionTrace`

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/application/pipeline/runner.py tests/
git commit -m "refactor: wire DI through pipeline runner, fix all callers"
```

---

## Chunk 3: Memory Access Planner (Tasks 5-6)

### Task 5: Implement the Memory Access Planner

**Files:**
- Create: `src/twin_runtime/application/planner/__init__.py`
- Create: `src/twin_runtime/application/planner/memory_access_planner.py`
- Create: `tests/test_planner.py`

- [ ] **Step 1: Write planner tests**

```python
# tests/test_planner.py
"""Tests for the Memory Access Planner rule-based decision table."""

import logging
from unittest.mock import MagicMock

import pytest

from twin_runtime.domain.models.planner import MemoryAccessPlan
from twin_runtime.domain.models.primitives import DomainEnum, OrdinalTriLevel, ScopeStatus, UncertaintyType, OptionStructure
from twin_runtime.domain.models.situation import SituationFeatureVector, SituationFrame
from twin_runtime.domain.evidence.base import EvidenceFragment, EvidenceType
from twin_runtime.application.planner.memory_access_planner import plan_memory_access


def _make_frame(
    *,
    stakes=OrdinalTriLevel.MEDIUM,
    ambiguity=0.5,
    routing_confidence=0.8,
    domains=None,
    scope_status=ScopeStatus.IN_SCOPE,
) -> SituationFrame:
    """Create a SituationFrame with controllable signals."""
    if domains is None:
        domains = {DomainEnum.WORK: 0.9}
    return SituationFrame(
        frame_id="test-frame",
        domain_activation_vector=domains,
        situation_feature_vector=SituationFeatureVector(
            reversibility=OrdinalTriLevel.MEDIUM,
            stakes=stakes,
            uncertainty_type=UncertaintyType.MISSING_INFO,
            controllability=OrdinalTriLevel.MEDIUM,
            option_structure=OptionStructure.CHOOSE_EXISTING,
        ),
        ambiguity_score=ambiguity,
        scope_status=scope_status,
        routing_confidence=routing_confidence,
    )


def _make_twin(domains=None) -> MagicMock:
    """Create a minimal mock TwinState."""
    twin = MagicMock()
    if domains is None:
        domains = [DomainEnum.WORK]
    twin.domain_heads = [MagicMock(domain=d) for d in domains]
    twin.user_id = "user-test"
    return twin


class TestPlannerNoStore:
    def test_no_store_returns_empty_plan(self):
        frame = _make_frame()
        twin = _make_twin()
        plan, evidence = plan_memory_access(frame, twin, evidence_store=None)
        assert plan.queries == []
        assert evidence == []
        assert "no evidence store" in plan.rationale.lower()


class TestPlannerRules:
    def test_high_stakes_low_ambiguity(self):
        """High stakes + ambiguity < 0.3 -> decisions_about query."""
        frame = _make_frame(stakes=OrdinalTriLevel.HIGH, ambiguity=0.2)
        twin = _make_twin()
        plan, _ = plan_memory_access(frame, twin, evidence_store=None)
        query_types = [q.query_type for q in plan.queries]
        assert "decisions_about" in query_types

    def test_high_ambiguity(self):
        """Ambiguity > 0.6 -> preference_on_axis query."""
        frame = _make_frame(ambiguity=0.75)
        twin = _make_twin()
        plan, _ = plan_memory_access(frame, twin, evidence_store=None)
        query_types = [q.query_type for q in plan.queries]
        assert "preference_on_axis" in query_types

    def test_multi_domain(self):
        """Multiple domains -> by_domain + state_trajectory queries."""
        frame = _make_frame(domains={DomainEnum.WORK: 0.8, DomainEnum.MONEY: 0.6})
        twin = _make_twin(domains=[DomainEnum.WORK, DomainEnum.MONEY])
        plan, _ = plan_memory_access(frame, twin, evidence_store=None)
        query_types = [q.query_type for q in plan.queries]
        assert "by_domain" in query_types
        assert "state_trajectory" in query_types

    def test_low_routing_confidence(self):
        """Routing confidence < 0.5 -> expanded budget + by_timeline."""
        frame = _make_frame(routing_confidence=0.3)
        twin = _make_twin()
        plan, _ = plan_memory_access(frame, twin, evidence_store=None)
        query_types = [q.query_type for q in plan.queries]
        assert "by_timeline" in query_types
        assert plan.total_evidence_budget > 10  # expanded

    def test_no_signals_empty_plan(self):
        """Default signals -> empty queries list."""
        frame = _make_frame(
            stakes=OrdinalTriLevel.LOW,
            ambiguity=0.4,
            routing_confidence=0.8,
        )
        twin = _make_twin()
        plan, _ = plan_memory_access(frame, twin, evidence_store=None)
        assert plan.queries == []


class TestDomainGating:
    def test_gating_activates_matching_domains(self):
        """Domains with heads and weight > 0.1 are activated."""
        frame = _make_frame(domains={DomainEnum.WORK: 0.9, DomainEnum.MONEY: 0.6})
        twin = _make_twin(domains=[DomainEnum.WORK, DomainEnum.MONEY])
        plan, _ = plan_memory_access(frame, twin, evidence_store=None)
        assert DomainEnum.WORK in plan.domains_to_activate
        assert DomainEnum.MONEY in plan.domains_to_activate
        assert plan.skipped_domains == {}

    def test_gating_skips_low_weight_domains(self):
        """Domains with weight < 0.1 are skipped."""
        frame = _make_frame(domains={DomainEnum.WORK: 0.9, DomainEnum.MONEY: 0.05})
        twin = _make_twin(domains=[DomainEnum.WORK, DomainEnum.MONEY])
        plan, _ = plan_memory_access(frame, twin, evidence_store=None)
        assert DomainEnum.WORK in plan.domains_to_activate
        assert DomainEnum.MONEY not in plan.domains_to_activate
        assert DomainEnum.MONEY in plan.skipped_domains

    def test_gating_skips_unmodeled_domains(self):
        """Domains without head data are skipped."""
        frame = _make_frame(domains={DomainEnum.WORK: 0.9, DomainEnum.MONEY: 0.6})
        twin = _make_twin(domains=[DomainEnum.WORK])  # no MONEY head
        plan, _ = plan_memory_access(frame, twin, evidence_store=None)
        assert DomainEnum.WORK in plan.domains_to_activate
        assert DomainEnum.MONEY not in plan.domains_to_activate
        assert "no head data" in plan.skipped_domains[DomainEnum.MONEY]


class TestPlannerExecution:
    def test_executes_queries_against_store(self):
        """When store is provided, planner executes queries and returns evidence."""
        frame = _make_frame(ambiguity=0.75)  # triggers preference_on_axis
        twin = _make_twin()

        mock_store = MagicMock()
        mock_frag = MagicMock(spec=EvidenceFragment)
        mock_store.query.return_value = [mock_frag]

        plan, evidence = plan_memory_access(frame, twin, evidence_store=mock_store)
        assert len(evidence) > 0
        mock_store.query.assert_called()

    def test_store_error_returns_empty(self):
        """When store.query() raises, planner returns empty evidence, logs warning."""
        frame = _make_frame(ambiguity=0.75)
        twin = _make_twin()

        mock_store = MagicMock()
        mock_store.query.side_effect = RuntimeError("store down")

        plan, evidence = plan_memory_access(frame, twin, evidence_store=mock_store)
        assert evidence == []

    def test_budget_enforcement(self):
        """Total evidence budget is enforced."""
        frame = _make_frame(
            ambiguity=0.75,
            domains={DomainEnum.WORK: 0.8, DomainEnum.MONEY: 0.6},
        )
        twin = _make_twin(domains=[DomainEnum.WORK, DomainEnum.MONEY])

        mock_store = MagicMock()
        # Return 20 fragments per query (over budget)
        mock_store.query.return_value = [MagicMock(spec=EvidenceFragment)] * 20

        plan, evidence = plan_memory_access(frame, twin, evidence_store=mock_store)
        assert len(evidence) <= plan.total_evidence_budget
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_planner.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Create `application/planner/__init__.py`**

```python
# src/twin_runtime/application/planner/__init__.py
"""Memory Access Planner — rule-based evidence scheduling."""
from .memory_access_planner import plan_memory_access

__all__ = ["plan_memory_access"]
```

- [ ] **Step 4: Implement `memory_access_planner.py`**

```python
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

    Uses domain_activation_vector weights and twin head availability
    to gate which heads should fire.
    """
    active_domains: List[DomainEnum] = []
    skipped: Dict[DomainEnum, str] = {}
    twin_domains = {h.domain for h in twin.domain_heads}

    for domain, weight in frame.domain_activation_vector.items():
        if weight < 0.1:
            skipped[domain] = f"activation weight {weight:.2f} < 0.10"
        elif domain not in twin_domains:
            skipped[domain] = f"no head data for {domain.value}"
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
```

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/test_planner.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run full suite**

Run: `python3 -m pytest tests/ --ignore=tests/test_pipeline_integration.py --ignore=tests/test_full_cycle.py -q`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/twin_runtime/application/planner/ tests/test_planner.py
git commit -m "feat: Memory Access Planner with rule-based decision table"
```

---

### Task 6: Wire planner into pipeline + integration test

**Files:**
- Modify: `src/twin_runtime/application/pipeline/runner.py`
- Modify: `src/twin_runtime/application/pipeline/head_activator.py`
- Create: `tests/test_planner_integration.py`

- [ ] **Step 1: Write integration tests**

```python
# tests/test_planner_integration.py
"""Integration tests: planner wired into pipeline with mock LLM + store."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from twin_runtime.domain.models.planner import MemoryAccessPlan, EnrichedActivationContext
from twin_runtime.domain.models.primitives import DomainEnum, OrdinalTriLevel
from twin_runtime.domain.evidence.base import EvidenceFragment, EvidenceType


class TestPlannerInPipeline:
    def test_planner_called_when_store_provided(self):
        """Verify planner is invoked with evidence_store during pipeline run."""
        from unittest.mock import patch
        from twin_runtime.application.pipeline.runner import run
        from twin_runtime.application.planner.memory_access_planner import plan_memory_access

        # We patch plan_memory_access to verify it's called,
        # and patch each pipeline stage to avoid real LLM calls.
        empty_plan = MemoryAccessPlan(rationale="test", domains_to_activate=[DomainEnum.WORK])
        mock_store = MagicMock()

        with patch("twin_runtime.application.pipeline.runner.plan_memory_access",
                    return_value=(empty_plan, [])) as mock_planner, \
             patch("twin_runtime.application.pipeline.runner.interpret_situation") as mock_si, \
             patch("twin_runtime.application.pipeline.runner.activate_heads") as mock_ah, \
             patch("twin_runtime.application.pipeline.runner.arbitrate") as mock_arb, \
             patch("twin_runtime.application.pipeline.runner.synthesize") as mock_syn:

            # Set up minimal return values
            mock_si.return_value = MagicMock()  # SituationFrame
            mock_ah.return_value = [MagicMock()]  # List[HeadAssessment]
            mock_arb.return_value = MagicMock()  # ConflictReport
            mock_trace = MagicMock()
            mock_syn.return_value = mock_trace

            mock_llm = MagicMock()
            mock_twin = MagicMock()

            run("test query", ["A", "B"], mock_twin, llm=mock_llm, evidence_store=mock_store)

            # Planner was called with the evidence store
            mock_planner.assert_called_once()
            call_args = mock_planner.call_args
            assert call_args[0][2] is mock_store  # evidence_store arg

    def test_run_without_store_backward_compat(self):
        """Pipeline works without evidence_store (current behavior)."""
        # Verify run() signature accepts evidence_store=None
        import inspect
        from twin_runtime.application.pipeline.runner import run
        sig = inspect.signature(run)
        assert "evidence_store" in sig.parameters
        assert sig.parameters["evidence_store"].default is None

    def test_trace_has_planner_audit(self):
        """RuntimeDecisionTrace can hold planner audit data."""
        from twin_runtime.domain.models.runtime import RuntimeDecisionTrace
        from twin_runtime.domain.models.planner import MemoryAccessPlan

        plan = MemoryAccessPlan(rationale="test")
        # Verify the field accepts a MemoryAccessPlan
        trace_data = {
            "trace_id": "t-1",
            "twin_state_version": "v001",
            "situation_frame_id": "sf-1",
            "activated_domains": [DomainEnum.WORK],
            "head_assessments": [{
                "domain": DomainEnum.WORK,
                "head_version": "v1",
                "option_ranking": ["A"],
                "utility_decomposition": {"growth": 0.8},
                "confidence": 0.7,
            }],
            "final_decision": "A",
            "decision_mode": "direct",
            "uncertainty": 0.3,
            "created_at": datetime.now(timezone.utc),
            "memory_access_plan": plan.model_dump(),
            "retrieved_evidence_count": 3,
            "skipped_domains": {"money": "reliability 0.30 < 0.50"},
        }
        trace = RuntimeDecisionTrace.model_validate(trace_data)
        assert trace.retrieved_evidence_count == 3
        assert trace.memory_access_plan is not None
        assert trace.skipped_domains["money"] == "reliability 0.30 < 0.50"
```

- [ ] **Step 2: Run tests to see current state**

Run: `python3 -m pytest tests/test_planner_integration.py -v`

- [ ] **Step 3: Wire planner into `runner.py`**

Update the runner to call `plan_memory_access` between interpret and activate, and pass `EnrichedActivationContext` to head activator:

```python
from twin_runtime.application.planner.memory_access_planner import plan_memory_access
from twin_runtime.domain.models.planner import EnrichedActivationContext

# In run(), after interpret_situation:
    # 2. Memory Access Planner
    plan, evidence = plan_memory_access(frame, twin, evidence_store)

    # 3. Head Activation — pass enriched context with retrieved evidence
    context = EnrichedActivationContext(
        twin=twin, frame=frame,
        retrieved_evidence=evidence,
        retrieval_rationale=plan.rationale,
    )
    assessments = activate_heads(query, option_set, context, llm=llm)
```

Also update `activate_heads` signature in `head_activator.py` to accept `EnrichedActivationContext`:

```python
from typing import Union
from twin_runtime.domain.models.planner import EnrichedActivationContext

def activate_heads(
    query: str,
    option_set: List[str],
    context: Union[EnrichedActivationContext, SituationFrame],
    twin: Optional[TwinState] = None,
    *,
    llm: LLMPort,
) -> List[HeadAssessment]:
    # Extract twin + frame from context
    if isinstance(context, EnrichedActivationContext):
        twin = context.twin
        frame = context.frame
        evidence = context.retrieved_evidence
    else:
        frame = context
        evidence = []
    # ... rest of function uses frame, twin, evidence
```

When `evidence` is non-empty, append an evidence section to the head prompt (in `_build_head_prompt`):

```python
# Add evidence_summary parameter to _build_head_prompt
def _build_head_prompt(..., evidence_summary: str = "") -> tuple[str, str]:
    # In the system prompt, after existing parameters, if evidence_summary:
    if evidence_summary:
        system += f"\n\n## Relevant Evidence\n{evidence_summary}\n\nUse these alongside the persona parameters."
```

Also populate the trace's audit fields. In the `synthesize` call or after it, set:
```python
    trace.memory_access_plan = plan.model_dump()
    trace.retrieved_evidence_count = len(evidence)
    trace.skipped_domains = {d.value: reason for d, reason in plan.skipped_domains.items()}
```

- [ ] **Step 4: Run ALL tests**

Run: `python3 -m pytest tests/ --ignore=tests/test_pipeline_integration.py --ignore=tests/test_full_cycle.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/application/pipeline/runner.py tests/test_planner_integration.py
git commit -m "feat: wire Memory Access Planner into pipeline + integration tests"
```

---

## Summary

| Task | What it does | Key risk |
|------|-------------|----------|
| 1 | Planner domain models + trace audit fields | Low — pure models |
| 2 | DefaultLLM adapter in interfaces/ | Low — thin wrapper |
| 3 | Inject LLM into pipeline stages | HIGH — changes 4 files, breaks callers temporarily |
| 4 | Update runner + fix all callers | HIGH — must fix all test failures from Task 3 |
| 5 | Implement Memory Access Planner | Medium — new code, well-tested rules |
| 6 | Wire planner into pipeline + integration | Medium — integration concerns |

**Note on ignored tests:** `test_pipeline_integration.py` and `test_full_cycle.py` are **API-dependent** (real LLM calls). They are pre-existing and ignored throughout. They call `run()` which has backward-compat `llm=None` default, so they remain functional. They do NOT call `activate_heads` directly. No changes needed — they will continue to work when an API key is available.

**Total new tests:** ~28 (planner models, defaults, DI, planner rules, domain gating, integration)
**Expected test count after:** 176+

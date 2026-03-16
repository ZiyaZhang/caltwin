# Phase 2b: Memory Access Planner + Pipeline DI

## Goal

Add dynamic evidence retrieval to the runtime pipeline via a rule-based Memory Access Planner, and fix the hexagonal architecture violation where application layer imports infrastructure directly.

## Context

After Phase 2a, the codebase has a 4-layer Hexagonal Architecture with port protocols defined but not yet used for dependency injection. The pipeline currently operates on pre-compiled TwinState only — it cannot dynamically retrieve raw evidence at decision time. Phase 2b adds this capability.

## Scope

Three concerns, delivered together:

1. **Memory Access Planner** — rule-based evidence scheduling between Situation Interpreter and Head Activator
2. **Pipeline DI wiring** — inject `LLMPort` and `EvidenceStore` through the pipeline instead of direct infrastructure imports
3. **Pipeline integration** — wire planner into the 4-stage pipeline, pass retrieved evidence to Head Activator

## Non-scope

- LLM fallback planner (deferred — rule-based covers 80%+ of cases)
- Embedding-based similarity search in EvidenceStore
- Micro-calibration (Phase 3)
- Outcome tracking (Phase 3)

---

## 1. Memory Access Planner

### 1.1 Position in Pipeline

```
Query → Situation Interpreter → Memory Access Planner → Head Activator → Conflict Arbiter → Synthesizer
                                       │
                                       ├─ Decides which RecallQueries to issue
                                       ├─ Retrieves relevant evidence via EvidenceStore port
                                       ├─ Filters, ranks, truncates to budget
                                       └─ Injects into Head Activator context
```

### 1.2 Models

```python
# domain/models/planner.py

class MemoryAccessPlan(BaseModel):
    """Output of the planner: what evidence to retrieve and how."""
    queries: List[RecallQuery]        # Ordered by priority
    execution_strategy: Literal["parallel", "sequential", "conditional"]
    total_evidence_budget: int        # Max fragments to inject into pipeline
    per_query_limit: int              # Max per individual query
    freshness_preference: Literal["recent_first", "historical_first", "balanced"]
    disabled_evidence_types: List[EvidenceType]  # Types to skip
    rationale: str                    # Human-readable explanation (auditable)


class EnrichedActivationContext(BaseModel):
    """What Head Activator receives after Planner enrichment."""
    twin: TwinState
    frame: SituationFrame
    retrieved_evidence: List[EvidenceFragment]
    retrieval_rationale: str
```

### 1.3 Planning Logic — Rule-Based Decision Table

The planner inspects the `SituationFrame` and `TwinState` to produce a `MemoryAccessPlan`. No LLM.

| Situation Signal | RecallQuery Type | Rationale |
|-----------------|------------------|-----------|
| High stakes + low uncertainty (ambiguity < 0.3) | `decisions_about` same topic | Verify consistency with past choices |
| High ambiguity (> 0.6) | `preference_on_axis` | Check if user has expressed relevant preferences |
| Multiple domains activated (≥ 2) | Per-domain `by_domain` queries + `state_trajectory` for cross-domain patterns | Gather domain-specific evidence + detect cross-domain value conflicts |
| Unmodeled domain (no head data) | `by_evidence_type` for ReflectionEvidence | No behavior data, rely on self-reports |
| Time-sensitive decision | `by_timeline` with recent window | Freshness preference = "recent_first", 30-day limit |
| Recurring decision type | `similar_situations` | Find past instances of same decision pattern |
| Low routing confidence (< 0.5) | Expanded budget + `by_timeline` | Broader context when uncertain |
| No signals match | Empty queries list | Pipeline proceeds with TwinState only (current behavior) |

Default budget: `total_evidence_budget=10`, `per_query_limit=5`.

When no evidence store is available (None), the planner returns an empty plan and the pipeline falls back to current behavior (TwinState only).

### 1.4 File: `application/planner/memory_access_planner.py`

Single function:

```python
def plan_memory_access(
    frame: SituationFrame,
    twin: TwinState,
    evidence_store: Optional[EvidenceStore] = None,
) -> tuple[MemoryAccessPlan, List[EvidenceFragment]]:
    """Plan and execute evidence retrieval for a decision.

    Returns:
        (plan, retrieved_evidence) — the plan for audit + the actual fragments
    """
```

The function both plans AND executes (issues queries against the store). This is intentional — the planner owns the full retrieval lifecycle. Separation into plan-then-execute adds complexity with no benefit at this stage.

---

## 2. Pipeline Dependency Injection

### 2.1 Problem

Five direct imports from `infrastructure/` in `application/`:

| File | Violating Import |
|------|-----------------|
| `pipeline/head_activator.py` | `from twin_runtime.infrastructure.llm.client import ask_json` |
| `pipeline/situation_interpreter.py` | `from twin_runtime.infrastructure.llm.client import ask_json` |
| `pipeline/decision_synthesizer.py` | `from twin_runtime.infrastructure.llm.client import ask_text` |
| `compiler/persona_compiler.py` | `from twin_runtime.infrastructure.llm.client import ask_json` |
| `compiler/persona_compiler.py` | `from twin_runtime.infrastructure.sources.registry import SourceRegistry` |

### 2.2 Solution: Optional Parameter Injection

Each pipeline stage gains an optional `llm` parameter. The `run()` entry point resolves the default (using `interfaces/defaults.py`) and passes it down. Individual stages do NOT fall back to infrastructure imports — they require `llm` from the caller:

```python
def interpret_situation(query: str, twin: TwinState, *, llm: LLMPort) -> SituationFrame:
    # uses llm.ask_json(...) — no infrastructure import
```

Backward compat for direct callers of individual stages (e.g. tests): they must now pass `llm`. The `DefaultLLM` from `interfaces/defaults.py` can be used. The `run()` function handles the `None` → `DefaultLLM` fallback so the top-level API is unchanged.

### 2.3 `DefaultLLM` Adapter

A thin wrapper that adapts the module-level `ask_json`/`ask_text` functions to the `LLMPort` protocol:

```python
class DefaultLLM:
    """Adapts infrastructure.llm.client module functions to LLMPort protocol."""
    def ask_json(self, system: str, user: str, max_tokens: int = 1024):
        from twin_runtime.infrastructure.llm.client import ask_json
        return ask_json(system, user, max_tokens)

    def ask_text(self, system: str, user: str, max_tokens: int = 1024):
        from twin_runtime.infrastructure.llm.client import ask_text
        return ask_text(system, user, max_tokens)
```

This lives in `interfaces/defaults.py` — the **interfaces layer** is the correct place for wiring infrastructure to application. The `interfaces/` layer is explicitly allowed to import both `application/` and `infrastructure/`. This ensures the `application/` layer has zero infrastructure imports.

### 2.4 `run()` Signature

```python
def run(
    query: str,
    option_set: List[str],
    twin: TwinState,
    *,
    llm: Optional[LLMPort] = None,
    evidence_store: Optional[EvidenceStore] = None,
) -> RuntimeDecisionTrace:
```

`run()` passes `llm` to all stages and `evidence_store` to the planner.

### 2.5 Compiler DI

`PersonaCompiler` gains an optional `llm` constructor parameter. The `SourceRegistry` import stays as-is — the compiler legitimately needs to know about source adapters, and abstracting this behind a port adds no value at this stage.

---

## 3. Pipeline Integration

### 3.1 Updated Pipeline Flow

```python
def run(query, option_set, twin, *, llm=None, evidence_store=None):
    if llm is None:
        from twin_runtime.interfaces.defaults import DefaultLLM
        llm = DefaultLLM()

    # 1. Situation Interpreter
    frame = interpret_situation(query, twin, llm=llm)

    # 2. Memory Access Planner (NEW)
    plan, evidence = plan_memory_access(frame, twin, evidence_store)

    # 3. Head Activation (now receives evidence)
    context = EnrichedActivationContext(
        twin=twin, frame=frame,
        retrieved_evidence=evidence,
        retrieval_rationale=plan.rationale,
    )
    assessments = activate_heads(query, option_set, context, llm=llm)

    # 4. Conflict Arbiter (unchanged)
    conflict = arbitrate(assessments)

    # 5. Decision Synthesis
    trace = synthesize(query, option_set, frame, assessments, conflict, twin, llm=llm)

    return trace
```

### 3.2 Head Activator Changes

`activate_heads` currently takes `(query, option_set, frame, twin)`. Change to accept `EnrichedActivationContext` as an alternative:

```python
def activate_heads(
    query: str,
    option_set: List[str],
    context: Union[EnrichedActivationContext, SituationFrame],
    twin: Optional[TwinState] = None,
    *,
    llm: Optional[LLMPort] = None,
) -> List[HeadAssessment]:
```

When `context` is `EnrichedActivationContext`, extract `twin` and `frame` from it (the `twin` parameter is ignored), and include `retrieved_evidence` in the LLM prompt. When `context` is a `SituationFrame`, `twin` must be provided (backward compat with existing callers).

The LLM prompt for head assessment gains a new section:

```
## Relevant Evidence
The following raw evidence fragments were retrieved for this decision:
{formatted_evidence}

Use these alongside the persona parameters to inform your assessment.
```

### 3.3 Trace Audit Fields

Add optional fields to `RuntimeDecisionTrace`:

```python
class RuntimeDecisionTrace(BaseModel):
    # ... existing fields ...
    memory_access_plan: Optional[MemoryAccessPlan] = None
    retrieved_evidence_count: int = 0
```

---

## 4. Testing Strategy

### 4.1 Planner Tests (~10 tests)

- Each rule in the decision table gets a test: construct a `SituationFrame` with specific signals, verify the `MemoryAccessPlan` contains the expected query types
- Empty plan when no signals match
- Empty plan when `evidence_store` is None
- Graceful fallback when `evidence_store.query()` raises (returns empty evidence, logs warning)
- Budget enforcement (total and per-query limits)

### 4.2 DI Tests (~5 tests)

- `run()` with mock `LLMPort` — no monkeypatching needed
- `interpret_situation()` with injected `llm`
- `activate_heads()` with injected `llm`
- Default fallback (no injection) still works

### 4.3 Integration Test (~3 tests)

- Full pipeline with mock LLM + mock EvidenceStore — evidence flows from store through planner to head activator prompt
- Planner audit fields appear in trace
- Backward compat: existing tests pass without changes

### 4.4 Existing Tests

All 148 existing tests must continue to pass. The DI changes use `Optional` parameters with backward-compat defaults, so no existing call sites break.

---

## 5. File Map

| File | Layer | Action |
|------|-------|--------|
| `domain/models/planner.py` | domain | CREATE — MemoryAccessPlan, EnrichedActivationContext |
| `domain/models/runtime.py` | domain | MODIFY — add optional planner fields to RuntimeDecisionTrace |
| `application/planner/__init__.py` | application | CREATE |
| `application/planner/memory_access_planner.py` | application | CREATE — plan_memory_access() |
| `interfaces/defaults.py` | interfaces | CREATE — DefaultLLM adapter (wiring layer) |
| `application/pipeline/runner.py` | application | MODIFY — add llm/evidence_store params, planner step |
| `application/pipeline/situation_interpreter.py` | application | MODIFY — add llm param |
| `application/pipeline/head_activator.py` | application | MODIFY — accept EnrichedActivationContext, add llm param |
| `application/pipeline/conflict_arbiter.py` | application | NO CHANGE — no LLM, no IO |
| `application/pipeline/decision_synthesizer.py` | application | MODIFY — add llm param |
| `application/compiler/persona_compiler.py` | application | MODIFY — add llm param to constructor |
| `tests/test_planner.py` | tests | CREATE |
| `tests/test_pipeline_di.py` | tests | CREATE |
| `tests/test_planner_integration.py` | tests | CREATE |

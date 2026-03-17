# Phase 5b: Structured Deliberation & Abstention Router — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add S1/S2 dynamic routing with bounded deliberation loop and multi-signal abstention, plus golden trace regression infrastructure — making reasoning depth proportional to problem difficulty.

**Architecture:** (1) Add trace metadata fields + data models; (2) Extract single-pass executor from runner; (3) Build route decision engine (pure rules + shadow scores); (4) Build deliberation loop with discrete convergence signals; (5) Wire orchestrator as new entry point; (6) Create golden trace test infrastructure. Ordered to minimize integration risk: models first, then executor extraction, then new logic, then wiring, then tests.

**Tech Stack:** Python 3.9+, Pydantic v2, pytest, dataclasses

**Spec:** `docs/superpowers/specs/2026-03-18-phase5b-structured-deliberation-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `src/twin_runtime/domain/models/runtime.py` | Add route_path, route_reason_codes, boundary_policy, deliberation_rounds, terminated_by, deliberation_round_summaries, shadow_scores to trace |
| Create | `src/twin_runtime/application/orchestrator/__init__.py` | Package marker |
| Create | `src/twin_runtime/application/orchestrator/models.py` | ExecutionPath, BoundaryPolicy, RouteDecision, TerminationReason, DeliberationRoundSummary, StructuredDecision |
| Create | `src/twin_runtime/application/orchestrator/route_decision.py` | decide_route() rule cascade + shadow scores |
| Create | `src/twin_runtime/application/orchestrator/deliberation.py` | deliberation_loop() + merge_structured_decision() + check_termination() |
| Create | `src/twin_runtime/application/orchestrator/runtime_orchestrator.py` | run() entry point — owns interpret, delegates to single_pass or deliberation |
| Create | `src/twin_runtime/application/pipeline/single_pass.py` | execute_from_frame_once() — plan→activate→arbitrate→synthesize |
| Modify | `src/twin_runtime/application/pipeline/runner.py` | run() delegates to orchestrator.run() for backward compat |
| Modify | `src/twin_runtime/application/pipeline/decision_synthesizer.py` | Extract merge_structured_decision() from _synthesize_decision() |
| Modify | `src/twin_runtime/application/planner/memory_access_planner.py` | Add seen_content_hashes, round_index, previous_conflict params |
| Modify | `src/twin_runtime/cli.py` | cmd_run calls orchestrator, add --max-rounds flag |
| Modify | `src/twin_runtime/server/mcp_server.py` | _handle_decide calls orchestrator |
| Create | `tests/fixtures/golden_traces/*.json` | 7 golden trace cases |
| Create | `tests/test_golden_traces.py` | Parametrized golden trace runner |
| Create | `tests/test_route_decision.py` | Route decision unit tests |
| Create | `tests/test_deliberation.py` | Deliberation loop unit tests |
| Create | `tests/test_orchestrator.py` | Orchestrator integration tests |

---

## Chunk 0: Data Models + Trace Fields

### Task 1: Add orchestrator data models

**Files:**
- Create: `src/twin_runtime/application/orchestrator/__init__.py`
- Create: `src/twin_runtime/application/orchestrator/models.py`
- Modify: `src/twin_runtime/domain/models/runtime.py`

- [ ] **Step 1: Create orchestrator package and models**

Create `src/twin_runtime/application/orchestrator/__init__.py` (empty).

Create `src/twin_runtime/application/orchestrator/models.py`:

```python
"""Data models for the runtime orchestrator."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ExecutionPath(str, Enum):
    NO_EXECUTION = "no_execution"
    S1_DIRECT = "s1_direct"
    S2_DELIBERATE = "s2_deliberate"


class BoundaryPolicy(str, Enum):
    NORMAL = "normal"
    FORCE_DEGRADE = "force_degrade"
    FORCE_REFUSE = "force_refuse"


class TerminationReason(str, Enum):
    CONFLICT_RESOLVED = "conflict_resolved"
    NO_NEW_EVIDENCE = "no_new_evidence"
    CONFIDENCE_PLATEAU = "confidence_plateau"
    MAX_ITERATIONS = "max_iterations"


class RouteDecision(BaseModel):
    execution_path: ExecutionPath
    boundary_policy: BoundaryPolicy
    reason_codes: List[str] = Field(default_factory=list)
    shadow_scores: Dict[str, float] = Field(default_factory=dict)


class DeliberationRoundSummary(BaseModel):
    round_index: int
    new_unique_evidence_count: int
    conflict_types: List[str] = Field(default_factory=list)
    top_choice: Optional[str] = None
    avg_head_confidence: float = 0.0
    top_choice_changed: bool = False


@dataclass
class StructuredDecision:
    top_choice: Optional[str]
    option_scores: Dict[str, float]
    avg_confidence: float
    mode: str  # DecisionMode value
    refusal_reason: Optional[str] = None
```

- [ ] **Step 2: Add trace fields to RuntimeDecisionTrace**

In `src/twin_runtime/domain/models/runtime.py`, after the existing `refusal_reason_code` field, add:

```python
    # Routing metadata (Phase 5b)
    route_path: str = Field(default="s1_direct", description="Execution path: s1_direct | s2_deliberate | no_execution")
    route_reason_codes: List[str] = Field(default_factory=list)
    boundary_policy: str = Field(default="normal", description="normal | force_degrade | force_refuse")
    deliberation_rounds: int = Field(default=0, description="Number of deliberation rounds (S1=0)")
    terminated_by: Optional[str] = Field(default=None, description="TerminationReason value")
    deliberation_round_summaries: List[Dict[str, Any]] = Field(default_factory=list)
    shadow_scores: Optional[Dict[str, float]] = Field(default=None)
```

- [ ] **Step 3: Run full test suite**

Run: `python3 -m pytest tests/ -q -m "not requires_llm" --tb=short`
Expected: All 365+ pass (new fields have defaults).

- [ ] **Step 4: Commit**

```bash
git add src/twin_runtime/application/orchestrator/ src/twin_runtime/domain/models/runtime.py
git commit -m "feat: add orchestrator models and trace routing metadata fields"
```

---

## Chunk 1: Single-Pass Executor + merge_structured_decision

### Task 2: Extract single-pass executor from runner

**Files:**
- Create: `src/twin_runtime/application/pipeline/single_pass.py`
- Modify: `src/twin_runtime/application/pipeline/runner.py`

- [ ] **Step 1: Create single_pass.py**

Extract the plan→activate→arbitrate→synthesize logic from `runner.py:run()` into a new function. This function takes a pre-computed frame (does NOT call interpret_situation):

```python
"""Single-pass pipeline executor: frame → plan → activate → arbitrate → synthesize."""
from __future__ import annotations

from typing import List, Optional

from twin_runtime.domain.models.runtime import RuntimeDecisionTrace
from twin_runtime.domain.models.situation import SituationFrame
from twin_runtime.domain.models.twin_state import TwinState
from twin_runtime.domain.ports.llm_port import LLMPort
from twin_runtime.domain.ports.evidence_store import EvidenceStore
from twin_runtime.application.pipeline.situation_interpreter import ScopeGuardResult
from twin_runtime.application.planner.memory_access_planner import plan_memory_access
from twin_runtime.application.pipeline.head_activator import activate_heads
from twin_runtime.application.pipeline.conflict_arbiter import arbitrate
from twin_runtime.application.pipeline.decision_synthesizer import synthesize
from twin_runtime.domain.models.planner import EnrichedActivationContext


def execute_from_frame_once(
    frame: SituationFrame,
    query: str,
    option_set: List[str],
    twin: TwinState,
    *,
    llm: LLMPort,
    evidence_store: Optional[EvidenceStore] = None,
    guard_result: Optional[ScopeGuardResult] = None,
) -> RuntimeDecisionTrace:
    """Execute a single pass of the pipeline from a pre-computed SituationFrame."""
    # 1. Plan + retrieve evidence
    plan, evidence = plan_memory_access(frame, twin, evidence_store, query=query)

    # 2. Head activation
    context = EnrichedActivationContext(
        twin=twin, frame=frame,
        retrieved_evidence=evidence,
        retrieval_rationale=plan.rationale,
        domains_to_activate=plan.domains_to_activate,
    )
    assessments = activate_heads(query, option_set, context, llm=llm)

    # 3. Conflict arbitration
    conflict = arbitrate(assessments)

    # 4. Synthesis
    trace = synthesize(query, option_set, frame, assessments, conflict, twin, llm=llm)

    # 5. Populate audit fields
    trace.memory_access_plan = plan.model_dump()
    trace.retrieved_evidence_count = len(evidence)
    trace.skipped_domains = {d.value: reason for d, reason in plan.skipped_domains.items()}
    trace.query = query
    trace.situation_frame = frame.model_dump(mode="json")
    if guard_result:
        from dataclasses import asdict
        trace.scope_guard_result = asdict(guard_result)

    return trace
```

- [ ] **Step 2: Update runner.py to use single_pass**

`runner.py:run()` should now call `interpret_situation` then delegate to `single_pass.execute_from_frame_once()`. Keep the same signature for backward compat. After 5b orchestrator is wired, this will delegate to orchestrator instead.

- [ ] **Step 3: Run full suite — no regression**

Run: `python3 -m pytest tests/ -q -m "not requires_llm" --tb=short`

- [ ] **Step 4: Commit**

```bash
git add src/twin_runtime/application/pipeline/single_pass.py src/twin_runtime/application/pipeline/runner.py
git commit -m "refactor: extract single-pass executor from runner"
```

### Task 3: Extract merge_structured_decision from synthesizer

**Files:**
- Modify: `src/twin_runtime/application/pipeline/decision_synthesizer.py`

- [ ] **Step 1: Extract merge logic**

Create `merge_structured_decision()` that computes the structured decision (top_choice, scores, confidence, mode) WITHOUT doing surface realization. The existing `_synthesize_decision()` should call this internally.

```python
from twin_runtime.application.orchestrator.models import StructuredDecision

def merge_structured_decision(
    assessments: List[HeadAssessment],
    conflict: Optional[ConflictReport],
    frame: SituationFrame,
    *,
    option_set: Optional[List[str]] = None,
) -> StructuredDecision:
    """Compute structured decision without surface realization. Used by deliberation loop."""
    decision_text, mode, uncertainty, refusal = _synthesize_decision(
        assessments, conflict, frame, option_set=option_set
    )
    # Extract top choice from "Recommended: X (over Y, Z)"
    top_choice = None
    if mode not in (DecisionMode.REFUSED,):
        if decision_text.startswith("Recommended: "):
            top_choice = decision_text.split("Recommended: ")[1].split(" (over")[0].strip()

    option_scores = {}
    for assessment in assessments:
        domain_weight = frame.domain_activation_vector.get(assessment.domain, 0.5)
        for rank, option in enumerate(assessment.option_ranking):
            score = (1.0 / (rank + 1)) * domain_weight * assessment.confidence
            option_scores[option] = option_scores.get(option, 0.0) + score

    avg_confidence = sum(a.confidence for a in assessments) / len(assessments) if assessments else 0.0

    return StructuredDecision(
        top_choice=top_choice,
        option_scores=option_scores,
        avg_confidence=avg_confidence,
        mode=mode.value,
        refusal_reason=refusal,
    )
```

- [ ] **Step 2: Run tests, commit**

```bash
git add src/twin_runtime/application/pipeline/decision_synthesizer.py
git commit -m "feat: extract merge_structured_decision for deliberation loop"
```

---

## Chunk 2: Route Decision Engine

### Task 4: Implement decide_route with rule cascade + shadow scores

**Files:**
- Create: `src/twin_runtime/application/orchestrator/route_decision.py`
- Create: `tests/test_route_decision.py`

- [ ] **Step 1: Write tests**

Create `tests/test_route_decision.py` with tests for each rule in the cascade:

```python
"""Tests for route decision engine."""
import pytest
from unittest.mock import MagicMock
from twin_runtime.application.orchestrator.models import ExecutionPath, BoundaryPolicy
from twin_runtime.application.orchestrator.route_decision import decide_route
from twin_runtime.application.pipeline.scope_guard import ScopeGuardResult
from twin_runtime.domain.models.primitives import DomainEnum, ScopeStatus, OrdinalTriLevel


# Helper to build minimal frame
def _frame(scope=ScopeStatus.IN_SCOPE, stakes="medium", ambiguity=0.3, domains=None):
    from twin_runtime.domain.models.situation import SituationFrame, SituationFeatureVector
    from twin_runtime.domain.models.primitives import UncertaintyType, OptionStructure
    return SituationFrame(
        frame_id="test",
        domain_activation_vector=domains or {DomainEnum.WORK: 0.9},
        situation_feature_vector=SituationFeatureVector(
            reversibility=OrdinalTriLevel.MEDIUM,
            stakes=OrdinalTriLevel(stakes),
            uncertainty_type=UncertaintyType.MIXED,
            controllability=OrdinalTriLevel.MEDIUM,
            option_structure=OptionStructure.CHOOSE_EXISTING,
        ),
        ambiguity_score=ambiguity,
        scope_status=scope,
        routing_confidence=0.8,
    )

def _twin():
    import json
    from pathlib import Path
    from twin_runtime.domain.models.twin_state import TwinState
    return TwinState(**json.loads(Path("tests/fixtures/sample_twin_state.json").read_text()))


class TestRouteDecisionRules:
    def test_restricted_hit_refuses(self):
        guard = ScopeGuardResult(restricted_hit=True, matched_terms=["restricted:medical=medical"])
        route = decide_route(_frame(), guard, _twin())
        assert route.execution_path == ExecutionPath.NO_EXECUTION
        assert route.boundary_policy == BoundaryPolicy.FORCE_REFUSE
        assert "policy_restricted" in route.reason_codes

    def test_non_modeled_no_activation_refuses(self):
        guard = ScopeGuardResult(non_modeled_hit=True)
        route = decide_route(_frame(domains={}), guard, _twin())
        assert route.execution_path == ExecutionPath.NO_EXECUTION
        assert route.boundary_policy == BoundaryPolicy.FORCE_REFUSE

    def test_non_modeled_with_activation_degrades(self):
        guard = ScopeGuardResult(non_modeled_hit=True)
        route = decide_route(_frame(), guard, _twin())
        assert route.execution_path == ExecutionPath.S1_DIRECT
        assert route.boundary_policy == BoundaryPolicy.FORCE_DEGRADE

    def test_out_of_scope_refuses(self):
        route = decide_route(_frame(scope=ScopeStatus.OUT_OF_SCOPE, domains={}), None, _twin())
        assert route.execution_path == ExecutionPath.NO_EXECUTION
        assert route.boundary_policy == BoundaryPolicy.FORCE_REFUSE

    def test_high_stakes_high_ambiguity_triggers_s2(self):
        route = decide_route(_frame(stakes="high", ambiguity=0.7), None, _twin())
        assert route.execution_path == ExecutionPath.S2_DELIBERATE
        assert route.boundary_policy == BoundaryPolicy.NORMAL

    def test_multi_domain_triggers_s2(self):
        route = decide_route(
            _frame(domains={DomainEnum.WORK: 0.6, DomainEnum.MONEY: 0.4}),
            None, _twin()
        )
        assert route.execution_path == ExecutionPath.S2_DELIBERATE

    def test_default_is_s1(self):
        route = decide_route(_frame(), None, _twin())
        assert route.execution_path == ExecutionPath.S1_DIRECT
        assert route.boundary_policy == BoundaryPolicy.NORMAL

    def test_shadow_scores_always_present(self):
        route = decide_route(_frame(), None, _twin())
        assert "deliberation_pressure" in route.shadow_scores
        assert "abstention_risk" in route.shadow_scores
```

- [ ] **Step 2: Implement decide_route**

Create `src/twin_runtime/application/orchestrator/route_decision.py`:

```python
"""Route decision engine: pure rule cascade + shadow scoring."""
from __future__ import annotations

from typing import Optional

from twin_runtime.application.orchestrator.models import (
    BoundaryPolicy, ExecutionPath, RouteDecision,
)
from twin_runtime.application.pipeline.scope_guard import ScopeGuardResult
from twin_runtime.domain.models.primitives import DomainEnum, OrdinalTriLevel, ScopeStatus
from twin_runtime.domain.models.situation import SituationFrame
from twin_runtime.domain.models.twin_state import TwinState


def decide_route(
    frame: SituationFrame,
    guard_result: Optional[ScopeGuardResult],
    twin: TwinState,
) -> RouteDecision:
    """Determine execution path and boundary policy via rule cascade."""
    reason_codes = []

    # Rule 1: restricted_hit
    if guard_result and guard_result.restricted_hit:
        return RouteDecision(
            execution_path=ExecutionPath.NO_EXECUTION,
            boundary_policy=BoundaryPolicy.FORCE_REFUSE,
            reason_codes=["policy_restricted"],
            shadow_scores=_shadow_scores(frame, guard_result, twin),
        )

    # Rule 2: non_modeled + no activation
    if guard_result and guard_result.non_modeled_hit and not frame.domain_activation_vector:
        return RouteDecision(
            execution_path=ExecutionPath.NO_EXECUTION,
            boundary_policy=BoundaryPolicy.FORCE_REFUSE,
            reason_codes=["non_modeled_no_activation"],
            shadow_scores=_shadow_scores(frame, guard_result, twin),
        )

    # Rule 3: non_modeled + has activation
    if guard_result and guard_result.non_modeled_hit:
        return RouteDecision(
            execution_path=ExecutionPath.S1_DIRECT,
            boundary_policy=BoundaryPolicy.FORCE_DEGRADE,
            reason_codes=["non_modeled_partial"],
            shadow_scores=_shadow_scores(frame, guard_result, twin),
        )

    # Rule 4: OUT_OF_SCOPE
    if frame.scope_status == ScopeStatus.OUT_OF_SCOPE:
        return RouteDecision(
            execution_path=ExecutionPath.NO_EXECUTION,
            boundary_policy=BoundaryPolicy.FORCE_REFUSE,
            reason_codes=["out_of_scope"],
            shadow_scores=_shadow_scores(frame, guard_result, twin),
        )

    # Rule 5: BORDERLINE + high stakes
    sfv = frame.situation_feature_vector
    if frame.scope_status == ScopeStatus.BORDERLINE and sfv.stakes == OrdinalTriLevel.HIGH:
        return RouteDecision(
            execution_path=ExecutionPath.S2_DELIBERATE,
            boundary_policy=BoundaryPolicy.FORCE_DEGRADE,
            reason_codes=["borderline_high_stakes"],
            shadow_scores=_shadow_scores(frame, guard_result, twin),
        )

    # Rule 6: BORDERLINE
    if frame.scope_status == ScopeStatus.BORDERLINE:
        return RouteDecision(
            execution_path=ExecutionPath.S1_DIRECT,
            boundary_policy=BoundaryPolicy.FORCE_DEGRADE,
            reason_codes=["borderline_scope"],
            shadow_scores=_shadow_scores(frame, guard_result, twin),
        )

    # Rule 7: high stakes + high ambiguity
    if sfv.stakes == OrdinalTriLevel.HIGH and frame.ambiguity_score > 0.6:
        return RouteDecision(
            execution_path=ExecutionPath.S2_DELIBERATE,
            boundary_policy=BoundaryPolicy.NORMAL,
            reason_codes=["high_stakes_high_ambiguity"],
            shadow_scores=_shadow_scores(frame, guard_result, twin),
        )

    # Rule 8: multi-domain
    if len(frame.domain_activation_vector) > 1:
        return RouteDecision(
            execution_path=ExecutionPath.S2_DELIBERATE,
            boundary_policy=BoundaryPolicy.NORMAL,
            reason_codes=["multi_domain"],
            shadow_scores=_shadow_scores(frame, guard_result, twin),
        )

    # Rule 9: default S1
    return RouteDecision(
        execution_path=ExecutionPath.S1_DIRECT,
        boundary_policy=BoundaryPolicy.NORMAL,
        reason_codes=[],
        shadow_scores=_shadow_scores(frame, guard_result, twin),
    )


def _shadow_scores(
    frame: SituationFrame,
    guard_result: Optional[ScopeGuardResult],
    twin: TwinState,
) -> dict:
    """Compute observation-only scores (not used in decisions)."""
    sfv = frame.situation_feature_vector
    stakes_val = {"low": 0.0, "medium": 0.5, "high": 1.0}.get(sfv.stakes.value, 0.5)
    n_domains = len(frame.domain_activation_vector)
    guard_pressure = 1.0 if (guard_result and guard_result.triggered) else 0.0

    deliberation_pressure = (
        stakes_val * 0.3
        + frame.ambiguity_score * 0.3
        + min(n_domains / 3.0, 1.0) * 0.2
        + (1.0 - frame.routing_confidence) * 0.2
    )
    abstention_risk = (
        guard_pressure * 0.4
        + (1.0 if frame.scope_status != ScopeStatus.IN_SCOPE else 0.0) * 0.3
        + frame.ambiguity_score * 0.3
    )
    return {
        "deliberation_pressure": round(deliberation_pressure, 3),
        "abstention_risk": round(abstention_risk, 3),
    }
```

- [ ] **Step 3: Run tests**

Run: `python3 -m pytest tests/test_route_decision.py -v`

- [ ] **Step 4: Commit**

```bash
git add src/twin_runtime/application/orchestrator/route_decision.py tests/test_route_decision.py
git commit -m "feat: route decision engine with 9-rule cascade + shadow scores"
```

---

## Chunk 3: Deliberation Loop

### Task 5: Implement deliberation_loop + termination checks

**Files:**
- Create: `src/twin_runtime/application/orchestrator/deliberation.py`
- Modify: `src/twin_runtime/application/planner/memory_access_planner.py`
- Create: `tests/test_deliberation.py`

- [ ] **Step 1: Update planner to accept deliberation parameters**

In `src/twin_runtime/application/planner/memory_access_planner.py`, update `plan_memory_access` signature to accept `seen_content_hashes`, `round_index`, `previous_conflict`. When `round_index > 0`, exclude seen hashes and broaden limit.

- [ ] **Step 2: Implement deliberation.py**

Create `src/twin_runtime/application/orchestrator/deliberation.py` with:
- `deliberation_loop()` — bounded loop: initial pass + up to max_iterations deliberation rounds
- `check_termination()` — checks CONFLICT_RESOLVED → NO_NEW_EVIDENCE (≥2 rounds) → CONFIDENCE_PLATEAU (≥2 rounds) → MAX_ITERATIONS
- Post-loop: if NO_NEW_EVIDENCE/MAX_ITERATIONS + conflict unresolved → REFUSED + INSUFFICIENT_EVIDENCE
- Uses `merge_structured_decision()` per round for convergence checks
- Calls `synthesize()` once at the end
- Maintains `cumulative_evidence` and `seen_evidence_hashes` across rounds
- None→None top_choice comparison guard

- [ ] **Step 3: Write deliberation tests**

Create `tests/test_deliberation.py` covering:
- Single round convergence (CONFLICT_RESOLVED)
- Multi-round budget exhaustion (MAX_ITERATIONS)
- NO_NEW_EVIDENCE after deliberation attempt
- INSUFFICIENT_EVIDENCE production
- seen_evidence_hashes excludes duplicates
- top_choice_changed with None guard

- [ ] **Step 4: Run tests and commit**

```bash
git add src/twin_runtime/application/orchestrator/deliberation.py \
  src/twin_runtime/application/planner/memory_access_planner.py \
  tests/test_deliberation.py
git commit -m "feat: deliberation loop with bounded iteration and convergence signals"
```

---

## Chunk 4: Runtime Orchestrator + Wiring

### Task 6: Implement runtime_orchestrator.py

**Files:**
- Create: `src/twin_runtime/application/orchestrator/runtime_orchestrator.py`
- Create: `tests/test_orchestrator.py`

- [ ] **Step 1: Implement orchestrator**

The orchestrator is the 10-step flow from spec §5.2:
1. interpret_situation → (frame, guard_result)
2. decide_route
3. force_path override (if provided)
4. FORCE_REFUSE → build refusal trace, return
5. S1_DIRECT → execute_from_frame_once
6. S2_DELIBERATE → deliberation_loop
7. FORCE_DEGRADE → cap mode (only if not REFUSED)
8. Populate routing metadata
9. Assign refusal_reason_code (precedence: existing > new)
10. Return trace

Include LOW_RELIABILITY post-execution assignment rule from spec.

- [ ] **Step 2: Write integration tests**

Create `tests/test_orchestrator.py`:
- S1 path (simple query, mock LLM)
- FORCE_REFUSE path (restricted query)
- FORCE_DEGRADE does not override REFUSED
- force_path override works
- Backward compat: runner.run() delegates to orchestrator

- [ ] **Step 3: Run and commit**

```bash
git add src/twin_runtime/application/orchestrator/runtime_orchestrator.py tests/test_orchestrator.py
git commit -m "feat: runtime orchestrator with S1/S2 routing and refusal logic"
```

### Task 7: Wire CLI/MCP to orchestrator + update runner backward compat

**Files:**
- Modify: `src/twin_runtime/cli.py`
- Modify: `src/twin_runtime/server/mcp_server.py`
- Modify: `src/twin_runtime/application/pipeline/runner.py`

- [ ] **Step 1: Update runner.py backward compat**

`runner.py:run()` delegates to `orchestrator.run()`:

```python
def run(query, option_set, twin, *, llm=None, evidence_store=None, micro_calibrate=False):
    from twin_runtime.application.orchestrator.runtime_orchestrator import run as orchestrator_run
    return orchestrator_run(
        query=query, option_set=option_set, twin=twin,
        llm=llm, evidence_store=evidence_store, micro_calibrate=micro_calibrate,
    )
```

- [ ] **Step 2: Update cli.py cmd_run**

Add `--max-rounds` flag to run subparser. Pass to orchestrator:

```python
p_run.add_argument("--max-rounds", type=int, default=2, help="Max deliberation rounds for S2")
```

In `cmd_run`, call orchestrator directly:

```python
from twin_runtime.application.orchestrator.runtime_orchestrator import run as orchestrator_run
trace = orchestrator_run(
    query=args.query, option_set=args.options, twin=twin,
    evidence_store=evidence_store, max_deliberation_rounds=args.max_rounds,
)
```

- [ ] **Step 3: Update mcp_server.py _handle_decide**

```python
from twin_runtime.application.orchestrator.runtime_orchestrator import run as orchestrator_run
trace = orchestrator_run(query=query, option_set=options, twin=twin, evidence_store=evidence_store)
```

- [ ] **Step 4: Run full suite**

Run: `python3 -m pytest tests/ -q -m "not requires_llm" --tb=short`

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/cli.py src/twin_runtime/server/mcp_server.py \
  src/twin_runtime/application/pipeline/runner.py
git commit -m "feat: wire CLI/MCP to orchestrator; runner delegates for backward compat"
```

---

## Chunk 5: Golden Trace Infrastructure

### Task 8: Create golden trace cases

**Files:**
- Create: `tests/fixtures/golden_traces/s1_direct_simple.json`
- Create: `tests/fixtures/golden_traces/s2_deliberate_high_stakes.json`
- Create: `tests/fixtures/golden_traces/refuse_policy_restricted.json`
- Create: `tests/fixtures/golden_traces/refuse_non_modeled.json`
- Create: `tests/fixtures/golden_traces/refuse_low_reliability.json`
- Create: `tests/fixtures/golden_traces/refuse_insufficient_evidence.json`
- Create: `tests/fixtures/golden_traces/s2_budget_exhausted.json`

- [ ] **Step 1: Create golden trace JSON files**

Each file follows the schema from spec §4.2. Include:
- `name`, `description`, `query`, `option_set`, `twin_fixture`
- `llm_script` with per-step mock responses (interpret, head_assess, synthesize, and for S2 cases round_0/round_1)
- `force_path` (null for natural routing, "s1_direct" for baseline comparison cases)
- `expected` with control plane assertions

- [ ] **Step 2: Commit**

```bash
git add tests/fixtures/golden_traces/
git commit -m "data: 7 golden trace cases for control plane regression"
```

### Task 9: Create golden trace test runner

**Files:**
- Create: `tests/test_golden_traces.py`

- [ ] **Step 1: Implement ScriptedLLM mock + parametrized test**

```python
"""Golden trace regression tests — control plane behavior verification."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

GOLDEN_DIR = Path("tests/fixtures/golden_traces")


def _load_golden_cases():
    cases = []
    for f in sorted(GOLDEN_DIR.glob("*.json")):
        case = json.loads(f.read_text())
        cases.append(pytest.param(case, id=case["name"]))
    return cases


class ScriptedLLM:
    """Mock LLM that returns responses from a script, dispatched by schema_name or call order."""

    def __init__(self, script: dict):
        self._script = script
        self._call_index = 0

    def ask_structured(self, system, user, *, schema, schema_name="", max_tokens=1024):
        # Dispatch by schema_name
        if schema_name == "situation_analysis":
            return self._script["interpret"]
        if schema_name == "head_assessment":
            # Find the right round's assessment
            # ... (implementation details based on round tracking)
            pass
        self._call_index += 1
        return {}

    def ask_text(self, system, user, max_tokens=1024):
        return self._script.get("synthesize", "Mock decision text.")

    def ask_json(self, system, user, max_tokens=1024):
        return {}


@pytest.mark.parametrize("case", _load_golden_cases())
def test_golden_trace(case):
    from twin_runtime.domain.models.twin_state import TwinState
    from twin_runtime.application.orchestrator.runtime_orchestrator import run
    from twin_runtime.application.orchestrator.models import ExecutionPath

    twin = TwinState(**json.loads(Path(case["twin_fixture"]).read_text()))
    llm = ScriptedLLM(case["llm_script"])

    force_path = None
    if case.get("force_path"):
        force_path = ExecutionPath(case["force_path"])

    trace = run(
        query=case["query"],
        option_set=case["option_set"],
        twin=twin,
        llm=llm,
        force_path=force_path,
    )

    expected = case["expected"]

    # Control plane assertions
    if "decision_mode" in expected:
        assert trace.decision_mode.value == expected["decision_mode"]
    if "refusal_reason_code" in expected:
        assert trace.refusal_reason_code == expected["refusal_reason_code"]
    if "route_path" in expected:
        assert trace.route_path == expected["route_path"]
    if "boundary_policy" in expected:
        assert trace.boundary_policy == expected["boundary_policy"]
    if "deliberation_rounds" in expected:
        assert trace.deliberation_rounds == expected["deliberation_rounds"]
    if "terminated_by" in expected:
        assert trace.terminated_by == expected["terminated_by"]
    if "activated_domains_contains" in expected:
        actual_domains = [d.value for d in trace.activated_domains]
        for d in expected["activated_domains_contains"]:
            assert d in actual_domains
    if "situation_frame.scope_status" in expected:
        assert trace.situation_frame["scope_status"] == expected["situation_frame.scope_status"]
    if "expected_top_choice" in expected and expected["expected_top_choice"]:
        # Parse top choice from "Recommended: X (over Y)"
        if "Recommended: " in trace.final_decision:
            actual_top = trace.final_decision.split("Recommended: ")[1].split(" (over")[0].strip()
            assert actual_top == expected["expected_top_choice"]
```

- [ ] **Step 2: Run golden traces**

Run: `python3 -m pytest tests/test_golden_traces.py -v`

- [ ] **Step 3: Commit**

```bash
git add tests/test_golden_traces.py
git commit -m "feat: golden trace test runner with ScriptedLLM and parametrized assertions"
```

---

## Final Verification

- [ ] **Run full test suite**: `python3 -m pytest tests/ -q -m "not requires_llm" --tb=short`
- [ ] **Verify S1 path**: simple query goes through single_pass, deliberation_rounds=0
- [ ] **Verify S2 path**: high-stakes query triggers deliberation, deliberation_rounds≥1
- [ ] **Verify REFUSE path**: restricted query gets NO_EXECUTION + FORCE_REFUSE
- [ ] **Verify INSUFFICIENT_EVIDENCE**: S2 with empty evidence store after loop → REFUSED + INSUFFICIENT_EVIDENCE
- [ ] **Verify golden traces**: all 7 pass
- [ ] **Verify backward compat**: `runner.run()` still works (delegates to orchestrator)
- [ ] **Verify CLI --max-rounds**: `twin-runtime run --help` shows --max-rounds flag

---

## Notes

- **INSUFFICIENT_EVIDENCE** is the first refusal code actually produced by 5b. It was reserved but unused in 5a.
- Chunk 0-1 can be implemented first (models + extraction). Chunk 2-3 (router + loop) depend on Chunk 1. Chunk 4 (orchestrator) depends on all prior. Chunk 5 (golden traces) depends on Chunk 4.
- Shadow scores are computed everywhere but never used in decisions. They are observation-only.
- `force_path` on orchestrator.run() is for testing only. CLI/MCP should not expose it.

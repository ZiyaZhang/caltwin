# Phase 5b: Structured Deliberation & Abstention Router — Design Spec

**Date:** 2026-03-18
**Status:** Approved (brainstorming complete)
**Predecessor:** Phase 5a (Release Hardening)
**Baseline:** 365 tests, CF=0.758, trust boundary bugs=0, trace completeness=100%
**Target:** Add S1/S2 dynamic routing, bounded deliberation loop, multi-signal abstention, golden trace regression — making the judgment twin's reasoning depth proportional to problem difficulty.

## North Star

> Build a calibrated judgment twin that learns from evidence and feedback to increasingly judge like you, while knowing when it should not judge on your behalf at all.

## Invariants

1. Never impersonate a missing twin.
2. Prefer abstention over unsafe overreach.
3. Every decision must be traceable to evidence, routing signals, and reliability scores.
4. Online learning must not silently mutate ontology/control topology.

## Quantifiable Gate

| Metric | Requirement |
|--------|-------------|
| High-stakes golden accuracy | S2 golden traces produce correct top_choice more often than S1-only baseline (measured on curated golden trace set, NOT the calibration-based CF metric) |
| Abstention correctness | ≥ 0.9 on OOS + insufficient-evidence cases |
| p95 latency (S1 path) | No regression from 5a (single LLM call path unchanged) |
| p95 latency (S2 path) | ≤ 3× S1 latency (bounded by max_iterations=2) |
| INSUFFICIENT_EVIDENCE | Produced as refusal_reason_code in at least 1 golden case |
| Golden trace regression | 7/7 golden traces pass |

---

## 1. Goals

**Primary goal:** Make reasoning depth proportional to problem difficulty. Low-risk single-domain queries get fast S1 answers. High-risk, multi-domain, or evidence-sparse queries get structured S2 deliberation with bounded iteration.

**Secondary goal:** Productize INSUFFICIENT_EVIDENCE as a first-class refusal code. When the system doesn't have enough evidence after deliberation, it says so explicitly.

**Non-goals:**
- Free-text inner monologue or open-ended agent chains
- Embedding-based similarity for routing (deferred to 5c)
- Clarifying questions back to the user (deferred)
- Dynamic ontology / DomainEnum changes
- Time decay or concept drift

## 2. Architecture Overview

```
User Query
    │
    ▼
┌─────────────────────────┐
│  interpret_situation()   │ → (frame, guard_result)
└─────────┬───────────────┘
          │
          ▼
┌─────────────────────────┐
│  decide_route()         │ → RouteDecision(execution_path, boundary_policy, reason_codes, shadow_scores)
└─────────┬───────────────┘
          │
    ┌─────┼──────────────┐
    │     │              │
    ▼     ▼              ▼
 REFUSE  S1_DIRECT    S2_DELIBERATE
  │       │              │
  │       ▼              ▼
  │  execute_once()   deliberation_loop()
  │       │            │ plan/retrieve → activate → arbitrate → merge_decision
  │       │            │ check: conflict_resolved? evidence_saturated? confidence_plateau? max_iter?
  │       │            │ repeat or exit
  │       │              │
  │       └──────┬───────┘
  │              ▼
  │        synthesize()  (one final surface realization)
  │              │
  │              ▼
  └──────► RuntimeDecisionTrace (with route_path, deliberation metadata, shadow scores)
```

## 3. Data Models

### 3.1 RouteDecision

```python
class ExecutionPath(str, Enum):
    NO_EXECUTION = "no_execution"    # Force refuse, no pipeline run
    S1_DIRECT = "s1_direct"          # Single pass
    S2_DELIBERATE = "s2_deliberate"  # Bounded deliberation loop

class BoundaryPolicy(str, Enum):
    NORMAL = "normal"
    FORCE_DEGRADE = "force_degrade"  # Run pipeline but cap output as degraded
    FORCE_REFUSE = "force_refuse"    # Skip pipeline, emit refusal trace

class RouteDecision(BaseModel):
    execution_path: ExecutionPath
    boundary_policy: BoundaryPolicy
    reason_codes: List[str]
    shadow_scores: Dict[str, float] = Field(default_factory=dict)
```

### 3.2 TerminationReason

```python
class TerminationReason(str, Enum):
    CONFLICT_RESOLVED = "conflict_resolved"
    NO_NEW_EVIDENCE = "no_new_evidence"
    CONFIDENCE_PLATEAU = "confidence_plateau"
    MAX_ITERATIONS = "max_iterations"
```

Note: `ABSTAINED` is NOT a termination reason — it's a decision outcome (decision_mode=REFUSED + refusal_reason_code=INSUFFICIENT_EVIDENCE). Termination reasons are process signals, not outcome labels.

### 3.3 DeliberationRoundSummary

```python
class DeliberationRoundSummary(BaseModel):
    round_index: int
    new_unique_evidence_count: int
    conflict_types: List[str]
    top_choice: str
    avg_head_confidence: float
    top_choice_changed: bool = False
```

### 3.4 New Trace Fields

Add to `RuntimeDecisionTrace`:

```python
    # Routing metadata
    route_path: str = Field(default="s1_direct", description="Execution path: s1_direct | s2_deliberate | no_execution")
    route_reason_codes: List[str] = Field(default_factory=list)
    boundary_policy: str = Field(default="normal", description="normal | force_degrade | force_refuse")

    # Deliberation metadata
    deliberation_rounds: int = Field(default=0, description="Number of deliberation rounds (S1=0)")
    terminated_by: Optional[str] = Field(default=None, description="TerminationReason enum value")
    deliberation_round_summaries: List[Dict[str, Any]] = Field(default_factory=list)

    # Shadow scores (observation only, not used in decisions)
    shadow_scores: Optional[Dict[str, float]] = Field(default=None)
```

## 4. Component 1: Golden Traces Test Infrastructure

### 4.1 Directory

```
tests/fixtures/golden_traces/
├── s1_direct_simple.json
├── s2_deliberate_high_stakes.json
├── refuse_policy_restricted.json
├── refuse_non_modeled.json
├── refuse_low_reliability.json
├── refuse_insufficient_evidence.json
└── s2_budget_exhausted.json
```

### 4.2 Golden Trace Schema

```json
{
  "name": "s1_direct_simple",
  "description": "High-confidence single-domain work decision, S1 fast path",
  "query": "Should I prioritize the refactor or the new feature?",
  "option_set": ["Refactor first", "New feature first"],
  "twin_fixture": "tests/fixtures/sample_twin_state.json",
  "evidence_fixture": null,
  "llm_script": {
    "interpret": {
      "domain_activation": {"work": 0.95},
      "reversibility": "high", "stakes": "low",
      "uncertainty_type": "outcome_uncertainty",
      "controllability": "high",
      "option_structure": "choose_existing",
      "ambiguity_score": 0.1,
      "clarification_questions": []
    },
    "head_assess_work": {
      "option_ranking": ["Refactor first", "New feature first"],
      "utility_decomposition": {"impact": 0.8, "urgency": 0.6},
      "confidence": 0.85,
      "used_core_variables": ["risk_tolerance"],
      "used_evidence_types": []
    },
    "synthesize": "I'd prioritize the refactor."
  },
  "expected": {
    "situation_frame.scope_status": "in_scope",
    "decision_mode": "direct",
    "refusal_reason_code": null,
    "route_path": "s1_direct",
    "boundary_policy": "normal",
    "deliberation_rounds": 0,
    "terminated_by": null,
    "activated_domains_contains": ["work"]
  }
}
```

For S2 cases, `llm_script` includes multiple rounds:

```json
{
  "llm_script": {
    "interpret": { ... },
    "round_0": {
      "head_assess_work": { ... },
      "head_assess_money": { ... }
    },
    "round_1": {
      "head_assess_work": { ... },
      "head_assess_money": { ... }
    },
    "synthesize": "..."
  }
}
```

### 4.3 Test Runner

`tests/test_golden_traces.py` — pytest parametrized over all JSON files in `tests/fixtures/golden_traces/`. For each case:

1. Load twin from `twin_fixture`
2. Load evidence from `evidence_fixture` (if any) into a temp evidence store
3. Build a `ScriptedLLM` mock that returns responses from `llm_script` in sequence
4. Call `orchestrator.run(query, options, twin, evidence_store, llm=scripted_llm)`
5. Assert `expected` fields against the returned trace

The `ScriptedLLM` dispatches based on call context (interpret vs head_assess vs synthesize) using the system prompt or schema_name to distinguish.

### 4.4 Assertion Rules

- Exact match: `decision_mode`, `refusal_reason_code`, `route_path`, `boundary_policy`, `terminated_by`
- Nested path: `scope_status` asserted via `trace.situation_frame["scope_status"]` (not a top-level trace field)
- Exact match: `deliberation_rounds`
- Contains check: `activated_domains_contains`
- Not asserted: `trace_id`, `created_at`, `output_text`, `memory_access_plan`, `shadow_scores`

## 5. Component 2: Runtime Orchestrator + Route Decision

### 5.1 File Structure

```
src/twin_runtime/application/orchestrator/
├── __init__.py
├── runtime_orchestrator.py    # run() entry point
├── route_decision.py          # decide_route() + rule cascade + shadow scoring
└── deliberation.py            # deliberation_loop() + merge_structured_decision()
```

### 5.2 runtime_orchestrator.py

```python
def run(
    query: str,
    option_set: List[str],
    twin: TwinState,
    *,
    llm: Optional[LLMPort] = None,
    evidence_store: Optional[EvidenceStore] = None,
    micro_calibrate: bool = False,
    max_deliberation_rounds: int = 2,
) -> RuntimeDecisionTrace:
```

Flow:
1. `frame, guard_result = interpret_situation(query, twin, llm=llm)`
2. `route = decide_route(frame, guard_result, twin)`
3. If `route.boundary_policy == FORCE_REFUSE`: build refusal trace directly, return
4. If `route.execution_path == S1_DIRECT`: call `execute_from_frame_once(frame, query, option_set, twin, ...)`
5. If `route.execution_path == S2_DELIBERATE`: call `deliberation_loop(frame, query, option_set, twin, ..., max_iterations=max_deliberation_rounds)`
6. If `route.boundary_policy == FORCE_DEGRADE`: cap `trace.decision_mode = DEGRADED`
7. Populate routing metadata on trace: `route_path`, `route_reason_codes`, `boundary_policy`, `shadow_scores`
8. Assign `refusal_reason_code` with **precedence rule: if the deliberation loop or single-pass executor already set `refusal_reason_code` (e.g., INSUFFICIENT_EVIDENCE), do NOT overwrite it.** Only assign if currently None. This prevents the generic 5a assignment logic from clobbering specific codes set by the loop's post-abstention logic.
9. Return trace

### 5.3 Single-Pass Executor (avoiding circular dependency)

**Problem:** If orchestrator imports runner and runner imports orchestrator for backward compat, we get a circular dependency.

**Solution:** Extract the single-pass executor to its own module. Both orchestrator and runner depend on it, but neither depends on each other.

```
application/pipeline/single_pass.py    # NEW: execute_from_frame_once()
application/orchestrator/               # imports single_pass
application/pipeline/runner.py          # imports single_pass (backward compat)
```

- `application/pipeline/single_pass.py` — `execute_from_frame_once(frame, query, option_set, twin, *, llm, evidence_store, guard_result)` — does plan → activate → arbitrate → synthesize, returns trace.
- `runner.py:run()` preserved as backward-compatible entry: calls interpret_situation, then `single_pass.execute_from_frame_once()`. Does NOT import orchestrator.
- Orchestrator calls `single_pass.execute_from_frame_once()` directly for S1, and uses the same building blocks (plan, activate, arbitrate) individually for S2 loop.

Key: `execute_from_frame_once` does NOT call `interpret_situation`. The orchestrator owns interpretation. No circular imports.

### 5.4 route_decision.py

```python
def decide_route(
    frame: SituationFrame,
    guard_result: Optional[ScopeGuardResult],
    twin: TwinState,
) -> RouteDecision:
```

**Rule cascade (priority order):**

```
1. guard_result.restricted_hit
   → NO_EXECUTION + FORCE_REFUSE + ["policy_restricted"]

2. guard_result.non_modeled_hit AND frame.domain_activation_vector is empty
   → NO_EXECUTION + FORCE_REFUSE + ["non_modeled_no_activation"]

3. guard_result.non_modeled_hit AND frame has activation
   → S1_DIRECT + FORCE_DEGRADE + ["non_modeled_partial"]

4. frame.scope_status == OUT_OF_SCOPE
   → NO_EXECUTION + FORCE_REFUSE + ["out_of_scope"]

5. frame.scope_status == BORDERLINE AND stakes == HIGH
   → S2_DELIBERATE + FORCE_DEGRADE + ["borderline_high_stakes"]

6. frame.scope_status == BORDERLINE
   → S1_DIRECT + FORCE_DEGRADE + ["borderline_scope"]

7. stakes == HIGH AND ambiguity_score > 0.6
   → S2_DELIBERATE + NORMAL + ["high_stakes_high_ambiguity"]

8. Any ACTIVATED domain's head_reliability < twin.scope_declaration.min_reliability_threshold
   → S2_DELIBERATE + NORMAL + ["low_reliability_activated_domain"]
   NOTE: Only check domains present in frame.domain_activation_vector (post-filtering).
   Pre-filtered low-reliability domains were already removed by interpret_situation.
   This rule catches domains that passed the validity filter but are still below threshold
   (e.g., threshold was lowered, or domain is borderline).

9. Multiple domains activated (len > 1) AND any activated domain has reliability < 0.6
   → S2_DELIBERATE + NORMAL + ["multi_domain_low_reliability"]

10. Default
   → S1_DIRECT + NORMAL + []
```

**Shadow scores (computed but not used in decisions):**

```python
shadow_scores = {
    "deliberation_pressure": _compute_deliberation_pressure(frame, twin),
    "abstention_risk": _compute_abstention_risk(frame, guard_result, twin),
}
```

These are simple weighted sums of the same signals used in rules. Logged in trace for dashboard/analysis.

### 5.5 Refusal Trace Construction

When `boundary_policy == FORCE_REFUSE`, orchestrator builds a minimal trace:

```python
trace = RuntimeDecisionTrace(
    trace_id=str(uuid.uuid4()),
    twin_state_version=twin.state_version,
    situation_frame_id=frame.frame_id,
    activated_domains=[],
    head_assessments=[],
    final_decision="This query is outside the twin's modeled capabilities.",
    decision_mode=DecisionMode.REFUSED,
    uncertainty=1.0,
    query=query,
    situation_frame=frame.model_dump(mode="json"),
    scope_guard_result=asdict(guard_result) if guard_result else None,
    route_path=route.execution_path.value,
    route_reason_codes=route.reason_codes,
    boundary_policy=route.boundary_policy.value,
    refusal_reason_code=_determine_refusal_code(route),
    created_at=datetime.now(timezone.utc),
)
```

## 6. Component 3: S2 Deliberation Loop

### 6.1 deliberation.py

```python
def deliberation_loop(
    frame: SituationFrame,
    query: str,
    option_set: List[str],
    twin: TwinState,
    *,
    llm: LLMPort,
    evidence_store: Optional[EvidenceStore] = None,
    guard_result: Optional[ScopeGuardResult] = None,
    max_iterations: int = 2,
) -> RuntimeDecisionTrace:
```

### 6.2 Loop Structure

```python
seen_evidence_hashes: Set[str] = set()
cumulative_evidence: List[EvidenceFragment] = []
round_summaries: List[DeliberationRoundSummary] = []
previous_assessments = None
previous_conflict = None

# Initial pass (round 0)
plan, evidence = plan_memory_access(frame, twin, evidence_store, query=query)
seen_evidence_hashes.update(e.content_hash for e in evidence)
cumulative_evidence.extend(evidence)
assessments = activate_heads(query, option_set, context, llm=llm)
conflict = arbitrate(assessments)
structured = merge_structured_decision(assessments, conflict, frame, option_set=option_set)

round_summaries.append(DeliberationRoundSummary(
    round_index=0,
    new_unique_evidence_count=len(evidence),
    conflict_types=[c.value for c in conflict.conflict_types] if conflict else [],
    top_choice=structured.top_choice,
    avg_head_confidence=structured.avg_confidence,
))

# Deliberation rounds (1..max_iterations)
for round_idx in range(1, max_iterations + 1):
    # Check termination
    termination = check_termination(round_summaries, conflict, previous_conflict)
    if termination is not None:
        break

    # Re-plan with seen evidence excluded
    plan, new_evidence = plan_memory_access(
        frame, twin, evidence_store, query=query,
        seen_content_hashes=seen_evidence_hashes,
        round_index=round_idx,
        previous_conflict=conflict,
    )
    unique_new = [e for e in new_evidence if e.content_hash not in seen_evidence_hashes]
    seen_evidence_hashes.update(e.content_hash for e in unique_new)

    # Re-activate with CUMULATIVE evidence (all rounds, not just round 0 + current)
    cumulative_evidence.extend(unique_new)
    all_evidence = cumulative_evidence
    assessments = activate_heads(query, option_set, context_with_evidence, llm=llm)
    previous_conflict = conflict
    conflict = arbitrate(assessments)
    structured = merge_structured_decision(assessments, conflict, frame, option_set=option_set)

    round_summaries.append(DeliberationRoundSummary(
        round_index=round_idx,
        new_unique_evidence_count=len(unique_new),
        conflict_types=[c.value for c in conflict.conflict_types] if conflict else [],
        top_choice=structured.top_choice,
        avg_head_confidence=structured.avg_confidence,
        top_choice_changed=(structured.top_choice != round_summaries[-1].top_choice),
    ))
else:
    termination = TerminationReason.MAX_ITERATIONS

# Final synthesis (one time only)
trace = synthesize(query, option_set, frame, assessments, conflict, twin, llm=llm)
```

### 6.3 merge_structured_decision()

Extracted from `decision_synthesizer.py:_synthesize_decision()`. Returns structured decision data (top_choice, avg_confidence, option_scores) WITHOUT doing surface realization. This allows per-round termination checks without paying for LLM text generation.

```python
@dataclass
class StructuredDecision:
    top_choice: str
    option_scores: Dict[str, float]
    avg_confidence: float
    mode: DecisionMode
    refusal_reason: Optional[str]
```

### 6.4 Termination Check

```python
def check_termination(
    round_summaries: List[DeliberationRoundSummary],
    current_conflict: Optional[ConflictReport],
    previous_conflict: Optional[ConflictReport],
) -> Optional[TerminationReason]:
```

**Check order:**

1. **CONFLICT_RESOLVED**: `current_conflict is None`, or conflict types reduced to single + `resolvable_by_system=True`
2. **NO_NEW_EVIDENCE**: latest round `new_unique_evidence_count == 0`. **Only checked when `len(round_summaries) >= 2`** (i.e., after at least one deliberation round has actually run). This prevents the loop from exiting before the first re-plan with broadened search / 2× limit has a chance to find new evidence.
3. **CONFIDENCE_PLATEAU**: `|avg_head_confidence[current] - avg_head_confidence[previous]| < 0.05` AND `top_choice_changed == False`. Also requires `len(round_summaries) >= 2`.
4. **MAX_ITERATIONS**: (handled by for-loop exhaustion)

### 6.5 Post-Loop Abstention

After loop exits, if evidence was saturated AND conflict unresolved:
- If `last_round.new_unique_evidence_count == 0` AND conflict still exists AND `terminated_by in (NO_NEW_EVIDENCE, MAX_ITERATIONS)`:
  - `decision_mode = REFUSED`
  - `refusal_reason_code = INSUFFICIENT_EVIDENCE`

This is the first time INSUFFICIENT_EVIDENCE is actually produced in the system.

### 6.6 Planner Enhancements

`plan_memory_access()` gets new optional parameters:

```python
def plan_memory_access(
    frame: SituationFrame,
    twin: TwinState,
    evidence_store: Optional[EvidenceStore] = None,
    query: str = "",
    *,
    seen_content_hashes: Optional[Set[str]] = None,  # NEW
    round_index: int = 0,                             # NEW
    previous_conflict: Optional[ConflictReport] = None,  # NEW
) -> Tuple[MemoryAccessPlan, List[EvidenceFragment]]:
```

When `round_index > 0`:
- Exclude fragments with content_hash in `seen_content_hashes`
- If `previous_conflict` has `requires_more_evidence=True`, broaden domain filter
- Increase `limit` on RecallQuery (2× default)

## 7. CLI/MCP Integration

- `cli.py:cmd_run()` calls `orchestrator.run()` instead of `runner.run()`
- `mcp_server.py:_handle_decide()` calls `orchestrator.run()` instead of `runner.run()`
- `runner.py:run()` backward-compat: delegates to `orchestrator.run()`
- `max_deliberation_rounds` exposed as CLI flag `--max-rounds` (default 2) on `run` subcommand

## 8. Test Strategy

### 8.1 Golden Traces (~7 tests)
As defined in Component 1. These test the orchestrator end-to-end.

### 8.2 Route Decision Unit Tests (~10 tests)
- Each rule in the cascade gets its own test
- Shadow scores are computed and non-None
- Default path is S1_DIRECT + NORMAL

### 8.3 Deliberation Loop Unit Tests (~8 tests)
- Single round (termination on first check)
- Multi-round convergence
- Budget exhaustion (MAX_ITERATIONS)
- INSUFFICIENT_EVIDENCE production
- seen_evidence_hashes excludes duplicates
- merge_structured_decision produces correct top_choice

### 8.4 Integration Tests (~3 tests)
- S1 path latency (no extra LLM calls beyond current)
- S2 path makes ≤ max_iterations extra rounds
- Backward compat: `runner.run()` still works

## 9. Explicitly NOT in This Phase

- Free-text inner monologue / open-ended agent reasoning
- Embedding-based routing or similarity search
- Clarifying questions returned to user
- Dynamic domain creation or DomainEnum changes
- Time decay on evidence or calibration cases
- Shadow scores influencing runtime decisions
- HTTP/SSE MCP transport

## 10. What 5b Unlocks

- **5c can add time decay** because deliberation_round_summaries provide temporal evidence for drift detection
- **5c can promote shadow_scores to control** once enough golden trace data validates their correlation with fidelity
- **Future phases can add clarifying questions** by extending the deliberation loop with a CLARIFY_USER termination reason
- **Dashboard can show S1/S2 distribution** using route_path field for runtime behavior analytics

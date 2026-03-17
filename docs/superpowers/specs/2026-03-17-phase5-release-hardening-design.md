# Phase 5a: Release Hardening — Design Spec

**Date:** 2026-03-17
**Status:** Approved (brainstorming complete)
**Predecessor:** Phase 4 (Launch-Ready Release)
**Baseline:** 332 tests, CF=0.758, 5 MCP tools, v0.1.0 alpha
**Target:** Fix trust boundary violations, persistence bugs, and reasoning correctness issues; wire evidence retrieval to minimum viable; ship a foundation that #5b (looped runtime) and #5c (S1/S2 router) can build on.

## 1. Goals

**Primary goal:** Every product entry point (CLI, MCP) must operate on the user's real data, fail honestly when data is missing, and persist all state changes it claims to make.

**Secondary goal:** Wire the evidence retrieval pipeline end-to-end so that "memory is input" is not just a tagline but a working data path.

**Non-goals:**
- Semantic / embedding-based retrieval (deferred to #5c S1/S2 router)
- LLM-based planner fallback for ambiguous queries (deferred to #5b looped runtime)
- New ConflictType enum values (deferred to conflict decomposition v0.2)
- Removing DomainEnum (explicitly deferred to research branch)

## 2. Chunk Structure

```
Chunk 1: Entry Points & Trust Boundary    (independent)
Chunk 2: Correctness & Persistence        (independent, parallel with Chunk 1)
Chunk 3: Policy Engine & Retrieval        (depends on Chunk 1 #3 and #4)
```

## 3. Chunk 1: Entry Points & Trust Boundary

### 3.1 MCP Fail-Closed

**Problem:** `mcp_server.py:84-106` silently loads a package-bundled sample twin when the user has no twin state. For a judgment engine, this is a trust violation — the system impersonates a demo persona without disclosure.

**Fix:**
- Delete the fixture fallback branches in `_load_twin()` (lines 91-106: `importlib.resources` path and CWD fixture path).
- `_load_twin()` returns `None` when no twin exists. All handlers already check for `None` and return `{"error": "No twin state found. Run 'twin-runtime init' first."}`.
- The package resource fixture (`src/twin_runtime/resources/fixtures/sample_twin_state.json`) remains for `--demo` mode (see §3.2) and tests.

**Tests to update:**
- `tests/test_mcp_resource_fallback.py:test_mcp_load_twin_uses_fixture` → rename to `test_mcp_load_twin_returns_none_when_empty`, assert `twin is None`.
- `tests/test_mcp_server.py:test_no_twin_falls_back_to_fixture` → rename to `test_no_twin_returns_error`, assert error response.

### 3.2 CLI Explicit `--demo` Mode

**Problem:** `cli.py:_get_twin()` has an implicit fixture fallback via `config["fixture_path"]`. There is no way to distinguish "user hasn't init'd" from "user wants to try with sample data".

**Fix:**
- Create a shared parent parser with `--demo` flag:
  ```python
  _twin_parent = argparse.ArgumentParser(add_help=False)
  _twin_parent.add_argument("--demo", action="store_true",
      help="Use bundled sample twin (no data persisted)")
  ```
- Attach `_twin_parent` as parent to subcommands that need twin: `run`, `status`, `evaluate`, `dashboard`, `compile`, `reflect`.
- `_get_twin(config, demo=False)`:
  - If `demo=True`: load from `importlib.resources` fixture, print `[DEMO MODE] Using sample twin. No data will be persisted.`
  - If `demo=False` and no twin in store: raise `TwinNotFoundError` (current behavior after removing fixture fallback).
- **Demo mode behavior:**
  - `cmd_run()`: skip trace persistence entirely (no `trace_store.save_trace()`), print `[DEMO MODE]` banner.
  - `cmd_reflect()`: skip outcome persistence, print `[DEMO MODE]` banner.
  - `cmd_evaluate()`: skip evaluation persistence and case used_for_calibration writeback.
  - Other commands (`status`, `dashboard`): read-only, no persistence needed anyway.

**Tests to update:**
- `tests/test_cli.py:test_status_with_fixture` → update to use `--demo` flag or mock.
- New test: `test_demo_flag_loads_sample_twin`.
- New test: `test_demo_mode_does_not_persist_trace`.

### 3.3 Dashboard Reads Real Store

**Problem:** `application/dashboard/cli.py:5-11` hardcodes `data/store`, `user-ziya`, and `tests/fixtures/...`. The `cli.py:cmd_dashboard()` calls it without passing config. Real users see the demo fixture's dashboard, not their own data.

**Fix:**
- `application/dashboard/cli.py:dashboard_command()` signature changes to accept explicit parameters:
  ```python
  def dashboard_command(
      *,
      store_dir: str,
      user_id: str,
      output: str = "fidelity_report.html",
      open_browser: bool = False,
  ) -> None:
  ```
- Remove all hardcoded paths from `dashboard_command()`. Use the passed `store_dir` and `user_id` to construct `TwinStore`, `CalibrationStore`, etc.
- If store has no data (no twin, no evaluations), print `"No evaluation data found. Run 'twin-runtime evaluate' first."` and return.
- `cli.py:cmd_dashboard()` calls `_load_config()`, extracts `store_dir` and `user_id`, and passes them explicitly:
  ```python
  def cmd_dashboard(args):
      config = _load_config()
      user_id = config.get("user_id", "default")
      dashboard_command(
          store_dir=str(_STORE_DIR),
          user_id=user_id,
          output=args.output,
          open_browser=args.open,
      )
  ```

**Architecture principle:** Application layer never reads `~/.twin-runtime/config.json`. Composition root (CLI/MCP) reads config and injects dependencies.

### 3.4 RuntimeDecisionTrace Stores Query + Frame

**Problem:** `RuntimeDecisionTrace` (runtime.py:45-73) doesn't persist the original query or situation frame. Downstream `event_collector.py:61-77` can only write placeholder text "Query that produced trace..." and defaults stakes/reversibility to medium.

**Fix:**
- Add fields to `RuntimeDecisionTrace`:
  ```python
  query: str = Field(default="", description="Original decision query")
  situation_frame: Optional[Dict[str, Any]] = Field(
      default=None,
      description="JSON-safe snapshot of SituationFrame at decision time",
  )
  ```
- `runner.py:run()` populates after synthesis (same pattern as `trace.memory_access_plan`):
  ```python
  trace.query = query
  trace.situation_frame = frame.model_dump(mode="json")
  ```
- Using `mode="json"` ensures `Dict[DomainEnum, float]` keys are serialized as strings, avoiding enum key serialization bugs in `model_dump_json()`.

### 3.5 event_collector Consumes New Fields

**Problem:** `event_collector.py:61-77` hardcodes placeholder text because it doesn't have access to the real query or frame data.

**Fix:**
- `collect_event()` (or wherever the event is built) checks `trace.query` and `trace.situation_frame`:
  - If `trace.query` is non-empty: use it as event context instead of "Query that produced trace..."
  - If `trace.situation_frame` is available: extract `stakes`, `reversibility`, `ambiguity_score` from it instead of defaulting to medium.
- This is a small change but completes the reflection loop: trace → event → calibration candidate now carries real situation metadata.

### 3.6 EvidenceStore Wired to CLI/MCP

**Problem:** `cli.py:cmd_run()` and `mcp_server.py:_handle_decide()` don't pass `evidence_store` to `runner.run()`. The runner always gets `None`, so the planner always does empty retrieval.

**Fix:**
- `cli.py:cmd_run()`:
  ```python
  from twin_runtime.infrastructure.backends.json_file.evidence_store import JsonFileEvidenceStore
  evidence_store = JsonFileEvidenceStore(str(_STORE_DIR / user_id / "evidence"))
  trace = run_pipeline(query=..., option_set=..., twin=twin, evidence_store=evidence_store)
  ```
- `mcp_server.py:_get_stores()` returns a 5-tuple adding evidence_store:
  ```python
  evidence_store = JsonFileEvidenceStore(Path(store_dir) / user_id / "evidence")
  return twin_store, trace_store, cal_store, evidence_store, user_id
  ```
- All callers of `_get_stores()` updated to unpack 5 values.
- `_handle_decide()` passes `evidence_store` to `run()`.

**Expectation:** After this change, the pipeline will attempt real evidence retrieval. But the evidence store will be empty until scan/compile writes data (Chunk 3 #10). This is intentional plumbing — the data path is correct, just empty.

**Path convention:** Evidence stored at `~/.twin-runtime/store/{user_id}/evidence/` to avoid mixing with traces, calibration, and twin state files at the user_id level.

## 4. Chunk 2: Correctness & Persistence

### 4.1 evaluate_fidelity Becomes Pure

**Problem:** `fidelity_evaluator.py:245` mutates `case.used_for_calibration = True` as a side effect inside a function that should be pure computation. The mutation is only in-memory — `CalibrationStore` never persists it back.

**Fix:**
- Delete `case.used_for_calibration = True` from `evaluate_fidelity()`. The function becomes purely computational — takes cases and twin, returns TwinEvaluation.
- All callers persist the "used" flag after successful evaluation:
  ```python
  evaluation = evaluate_fidelity(cases, twin)
  cal_store.save_evaluation(evaluation)
  for case in cases:
      case.used_for_calibration = True
      cal_store.save_case(case)
  ```
- **Callers to update:**
  - `cli.py:cmd_evaluate()` (line ~261)
  - `mcp_server.py:_handle_calibrate()` (line ~303)
  - Any batch evaluation scripts (check `tools/` directory)
- Demo mode callers skip the writeback loop.

### 4.2 TraceStore Save/List Directory Alignment

**Problem:** `trace_store.py:17` saves to `self.base/{trace_id}.json`. `trace_store.py:26` reads from `self.base/{user_id}/*.json`. After saving, `list_traces()` returns empty because it looks in the wrong subdirectory.

**Fix:**
- `list_traces()` implementation changes to read `self.base/*.json` (flat, matching save behavior):
  ```python
  def list_traces(self, user_id: str = "", limit: int = 50) -> List[str]:
      """List trace IDs, sorted by modification time (newest first)."""
      files = sorted(
          self.base.glob("*.json"),
          key=lambda p: p.stat().st_mtime,
          reverse=True,
      )
      return [p.stem for p in files[:limit]]
  ```
- `user_id` parameter retained for interface compatibility but ignored (user isolation is at directory level: `_STORE_DIR / user_id / "traces"`).
- `mcp_server.py:_handle_history()` refactored to use `trace_store.list_traces()` + `trace_store.load_trace()` instead of manual glob:
  ```python
  trace_ids = trace_store.list_traces(limit=limit)
  for tid in trace_ids:
      try:
          trace = trace_store.load_trace(tid)
          traces.append({...})
      except Exception:
          continue
  ```

### 4.3 Conflict Arbiter: Ranking Divergence Independence

**Problem:** `conflict_arbiter.py:27-75` stuffs `ranking_divergence(work↔money)` strings into `utility_conflict_axes`. This means pure ranking disagreement is classified as `UTILITY` conflict by `_classify_conflict`, leaving belief conflict with no independent existence.

**Fix:**

**Step 1: Split return value of `_detect_utility_conflict`**
```python
def _detect_utility_conflict(
    assessments: List[HeadAssessment],
) -> tuple[List[str], List[str]]:
    """Returns (axis_conflicts, ranking_divergences) as separate lists."""
```
- `axis_conflicts`: same-axis score disagreement (original Strategy 1 logic, unchanged)
- `ranking_divergences`: cross-domain ranking inversion (current Strategy 2 logic, moved to separate list)

**Step 2: Add field to ConflictReport**
```python
ranking_divergence_pairs: List[str] = Field(
    default_factory=list,
    description="Cross-domain ranking inversions, e.g. 'work↔money'",
)
```

**Step 3: Update `_classify_conflict` mapping**
- Only `axis_conflicts` → `PREFERENCE` (was UTILITY, mapping to existing enum)
- Only `ranking_divergences` → `BELIEF` (v0.1 approximation: ranking disagreement is the closest signal to belief conflict until proper decomposition in v0.2)
- Both present → `MIXED`
- No new `ConflictType` enum values added.

**Step 4: Update `arbitrate()` to wire the split**
- Unpack tuple from `_detect_utility_conflict`
- Pass `axis_conflicts` to `utility_conflict_axes` on ConflictReport
- Pass `ranking_divergences` to `ranking_divergence_pairs` on ConflictReport
- Remove or merge the existing `_detect_ranking_disagreement()` function — its logic is now subsumed by the new `ranking_divergences` return from `_detect_utility_conflict`. Keeping both would produce contradictory classifications.

## 5. Chunk 3: Policy Engine & Retrieval

### 5.1 Scope Gate Deterministic Rules

**Problem:** `situation_interpreter.py:118-152` only filters by valid domain membership. It doesn't read `restricted_use_cases` or `non_modeled_capabilities` from `ScopeDeclaration`. The system can't enforce boundaries before LLM classification.

**Fix:**

**Stage 0 (new): Deterministic guard on raw query**

Before LLM interpretation, run keyword matching against scope declaration:

```python
def _deterministic_scope_guard(
    query: str,
    scope: ScopeDeclaration,
) -> Optional[ScopeStatus]:
    """Pre-LLM scope check using keyword matching against restricted/non-modeled lists.

    Returns ScopeStatus if a match is found, None if no match (proceed to LLM).
    """
    q_lower = query.lower()

    # Check restricted_use_cases first (strongest rejection signal)
    for restriction in scope.restricted_use_cases:
        if restriction.lower() in q_lower:
            return ScopeStatus.OUT_OF_SCOPE

    # Check non_modeled_capabilities
    for capability in scope.non_modeled_capabilities:
        if capability.lower() in q_lower:
            return ScopeStatus.OUT_OF_SCOPE  # tentative; may be overridden below

    return None  # No deterministic match; proceed to LLM
```

**Known limitation:** Naive substring matching can false-positive (e.g., "medical-grade monitor" matches "medical"). Acceptable for v0.1 since false-positive (wrongly refusing) is safer than false-negative (wrongly advising on medical/legal). Phase 5c S1/S2 router will add embedding-based matching to reduce false positives.

**Integration into `interpret_situation()`:**

Insert before Stage 2 (LLM interpretation):
```python
# Stage 0: Deterministic scope guard (pre-LLM)
deterministic_scope = _deterministic_scope_guard(query, twin.scope_declaration)
```

Then in Stage 3 (`_apply_routing_policy`), consume this signal:
- If `deterministic_scope == OUT_OF_SCOPE`: return immediately, skip further processing.
- If `deterministic_scope is None` but non_modeled was hit AND no modeled activation survived filtering: `OUT_OF_SCOPE`.
- If `deterministic_scope is None` but non_modeled was hit AND some modeled activation survived: `BORDERLINE`.

**Refined `_apply_routing_policy` check order:**
1. `restricted_use_cases` deterministic guard → OUT_OF_SCOPE
2. `non_modeled_capabilities` deterministic guard → OUT_OF_SCOPE or BORDERLINE (depends on modeled activation)
3. Valid domain filtering
4. Empty activation → OUT_OF_SCOPE (bug fix: no longer falls back to work)
5. Ambiguity threshold → BORDERLINE

### 5.2 Empty Activation No Longer Falls Back to Work

**Problem:** `situation_interpreter.py:133` injects a fake `{DomainEnum.WORK: 1.0}` activation when no domain matches. This masks scope failures.

**Fix:**
```python
# Before (line 133):
return {DomainEnum.WORK: 1.0}, ScopeStatus.OUT_OF_SCOPE, 0.1

# After:
return {}, ScopeStatus.OUT_OF_SCOPE, 0.0
```

**Pydantic constraint change required:** `SituationFrame.domain_activation_vector` has `min_length=1` (situation.py:40-43). Relax to `min_length=0` to allow empty activation for OUT_OF_SCOPE frames. Audit downstream consumers:
- `head_activator.py`: must handle empty activation (skip head activation, return empty assessments)
- `memory_access_planner.py`: must handle empty activation (return empty plan)
- `decision_synthesizer.py:32-38`: already handles `scope_status == out_of_scope` with REFUSED response

Downstream synthesizer handles the REFUSED path before reaching head assessments, so empty activation is safe.

### 5.3 JsonFileEvidenceStore.query() Minimum Viable

**Problem:** Current `evidence_store.py` `recall()` returns all fragments for a user with no filtering. `RecallQuery` model has `domain_filter`, `target_domain`, `target_evidence_type`, `topic_keywords`, `situation_description` but none are used.

**Fix:**

Implement `query()` method (matching existing port interface) with keyword-level filtering:

```python
def query(self, recall_query: RecallQuery, limit: int = 10) -> List[EvidenceFragment]:
    """Filter and rank evidence fragments by domain, type, and keyword relevance."""
    fragments = self._load_all_fragments()

    # Filter by domain (EvidenceFragment uses domain_hint, not domain)
    if recall_query.target_domain:
        fragments = [f for f in fragments if f.domain_hint == recall_query.target_domain]
    elif recall_query.domain_filter:
        fragments = [f for f in fragments if f.domain_hint in recall_query.domain_filter]

    # Filter by evidence type
    if recall_query.target_evidence_type:
        fragments = [f for f in fragments if f.evidence_type == recall_query.target_evidence_type]
    elif recall_query.evidence_type_filter:
        fragments = [f for f in fragments if f.evidence_type in recall_query.evidence_type_filter]

    # Rank by topic_keywords relevance (keyword hit count on summary + raw_excerpt)
    if recall_query.topic_keywords:
        def relevance_score(frag):
            text = (frag.summary or "") + " " + (frag.raw_excerpt or "")
            text_lower = text.lower()
            return sum(1 for kw in recall_query.topic_keywords if kw.lower() in text_lower)

        fragments.sort(key=relevance_score, reverse=True)
        # Drop zero-relevance fragments
        fragments = [f for f in fragments if relevance_score(f) > 0] or fragments
    else:
        # Default: sort by recency (EvidenceFragment uses occurred_at, not created_at)
        fragments.sort(key=lambda f: f.occurred_at, reverse=True)

    return fragments[:limit]
```

No new fields added to `RecallQuery`. Uses existing `topic_keywords`, `target_domain`, `target_evidence_type`, `domain_filter`, `evidence_type_filter`.

### 5.4 Planner Constructs Meaningful RecallQuery

**Problem:** `memory_access_planner.py` constructs an empty or trivial `RecallQuery`. The `TODO: LLM fallback when ambiguity > 0.7` remains unaddressed (deferred to #5b).

**Fix:**
- Planner extracts filter conditions from `SituationFrame`:
  - `target_domain`: highest-weight domain from `frame.domain_activation_vector`
  - `topic_keywords`: extracted from the query string (whitespace split for English; for Chinese queries, use character n-grams or jieba if available, fallback to full query as single keyword)
  - `domain_filter`: all activated domains (activation > threshold)
- This makes the planner produce a meaningful query even without LLM assistance.
- The `TODO` comment is updated to reference Phase 5b.

### 5.5 Scan/Compile Persists Evidence to Store

**Problem:** `cmd_scan()` prints evidence fragments but doesn't write them to `JsonFileEvidenceStore`. `cmd_compile()` reads fragments from the registry but also doesn't persist them. The evidence store is always empty.

**Fix:**
- `cmd_scan()` after scanning, persists fragments:
  ```python
  evidence_store = JsonFileEvidenceStore(str(_STORE_DIR / user_id / "evidence"))
  for fragment in fragments:
      evidence_store.store_fragment(fragment)  # port method is store_fragment(), not save_fragment()
  print(f"Persisted {len(fragments)} evidence fragments to store.")
  ```
- `cmd_compile()` similarly persists the fragments it processes.
- `JsonFileEvidenceStore` already has `store_fragment()` (port interface at `evidence_store.py:12`).
- Evidence fragments are stored as individual JSON files under `.../evidence/fragments/{fragment_id}.json`.

## 6. Test Strategy

Each chunk must maintain the existing 332-test baseline plus new tests:

**Chunk 1 new tests (~15):**
- MCP fail-closed (2 tests: no twin → error, with twin → success)
- CLI `--demo` flag (3 tests: demo loads sample, demo doesn't persist, non-demo fails without init)
- Dashboard real store (2 tests: with data, without data)
- Trace query/frame fields (2 tests: fields populated, JSON-safe serialization)
- event_collector uses new fields (2 tests)
- EvidenceStore wiring (2 tests: evidence_store passed to runner, path convention correct)

**Chunk 2 new tests (~8):**
- evaluate_fidelity purity (2 tests: no mutation of input cases, callers persist)
- TraceStore flat listing (3 tests: save then list, mtime ordering, empty store)
- Conflict arbiter separation (3 tests: axis-only → PREFERENCE, ranking-only → BELIEF, both → MIXED)

**Chunk 3 new tests (~10):**
- Scope gate deterministic guard (4 tests: restricted hit, non_modeled + no activation, non_modeled + some activation, no match)
- Empty activation → OUT_OF_SCOPE (1 test)
- RecallQuery filtering (3 tests: domain filter, keyword ranking, empty store)
- Planner meaningful query (1 test)
- Scan persists evidence (1 test)

## 7. Explicitly NOT in This Phase

- Embedding-based retrieval or similarity search
- LLM-based planner fallback for ambiguous queries
- New ConflictType enum values
- Dynamic domain clustering or DomainEnum removal
- System 1 / System 2 routing
- Looped / cyclic pipeline execution
- HTTP/SSE MCP transport
- Active learning or concept drift modeling

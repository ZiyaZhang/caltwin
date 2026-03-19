# Phase B: Bootstrap Protocol — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a cold-start system that lets a new user get a usable twin in 15 minutes via `twin-runtime bootstrap`, with ExperienceLibrary for semantic memory, ReflectionGenerator for learning from mistakes, and ConsistencyChecker for S2 self-refine.

**Architecture:** 4 components layered bottom-up: ExperienceLibrary (data model + persistence + keyword search), BootstrapEngine (forced-choice → aggregated bootstrap principles + narrative → experience extraction), ReflectionGenerator (CF-miss → new entry, CF-hit → confirmation), ConsistencyChecker (S2-only post-synthesis hook on the final trace). CLI `bootstrap` command orchestrates onboarding + mini A/B comparison.

**Tech Stack:** Python 3.9+, Pydantic v2, pytest. Reuses existing `LLMPort`, `ComparisonExecutor`, `TwinStore`. No new dependencies.

**Key design decisions:**
- ExperienceLibrary is a standalone JSON file at `~/.twin-runtime/store/{user_id}/experience_library.json`, parallel to TwinState
- Bootstrap sets `min_reliability_threshold = 0.35` in scope_declaration so that user-declared domains (head_reliability=0.4) are immediately usable; undeclared domains stay at 0.3 (below threshold). scope_declaration.user_facing_summary notes this is a "bootstrap-provisional" state. Contradictory axes → head_reliability 0.3 (below threshold, forces DEGRADE)
- ReflectionGenerator: CF-hit → 0 LLM calls (confirmation only); CF-miss → 1 LLM call (extraction)
- ConsistencyChecker: S2 only, never changes recommended option, only adjusts uncertainty + annotates. Hooks as a post-synthesis step in `runtime_orchestrator.py` after `deliberation_loop()` returns the final trace — NOT in `single_pass.py`
- 12 forced-choice answers are NOT stored as 12 individual ExperienceEntries. Instead they are aggregated into 3-5 "bootstrap principles" (one per axis cluster, LLM-synthesized). Only open narratives (Phase 3) and subsequent reflect-miss produce concrete experience entries
- `ExperienceEntry.weight` starts at 0.9 (bootstrap principle), 0.8 (narrative), 1.0 (reflect-miss)
- Bootstrap builds a full valid `TwinState` from scratch (no fixture file needed)
- ExperienceLibrary.search() returns typed results (`SearchResult` with `kind: "entry" | "pattern"` and typed payload) so downstream consumers can distinguish real entries from pattern pseudo-results. ReflectionGenerator confirmation flow only operates on `kind="entry"` results
- Phase 4 (document upload) is deferred to a future iteration. This plan covers Phase 1-3 only (20 questions)

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `src/twin_runtime/domain/models/experience.py` | ExperienceEntry, PatternInsight, ExperienceLibrary, SearchResult models |
| Create | `src/twin_runtime/infrastructure/backends/json_file/experience_store.py` | ExperienceLibraryStore (load/save JSON) |
| Create | `src/twin_runtime/application/bootstrap/__init__.py` | Package marker |
| Create | `src/twin_runtime/application/bootstrap/questions.py` | QuestionType, BootstrapQuestion, BootstrapAnswer, DEFAULT_QUESTIONS |
| Create | `src/twin_runtime/application/bootstrap/engine.py` | BootstrapEngine, BootstrapResult |
| Create | `src/twin_runtime/application/calibration/reflection_generator.py` | ReflectionGenerator, ReflectionResult |
| Create | `src/twin_runtime/application/pipeline/consistency_checker.py` | ConsistencyChecker, ConsistencyResult |
| Create | `tests/test_experience_library.py` | ExperienceLibrary model + search + persistence tests |
| Create | `tests/test_bootstrap/` | Bootstrap engine + questions tests |
| Create | `tests/test_reflection_generator.py` | ReflectionGenerator tests |
| Create | `tests/test_consistency_checker.py` | ConsistencyChecker tests |
| Modify | `src/twin_runtime/cli.py` | Add `bootstrap` command |
| Modify | `src/twin_runtime/cli.py` | Integrate ReflectionGenerator into `cmd_reflect` |
| Modify | `src/twin_runtime/application/orchestrator/runtime_orchestrator.py` | Hook ConsistencyChecker post-S2-synthesis + pass experience_library |
| Modify | `src/twin_runtime/application/orchestrator/deliberation.py` | Accept + forward experience_library |
| Modify | `README.md` | Add bootstrap + experience library docs |

---

## Step 1: ExperienceLibrary Data Model + Persistence (B2)

Create `src/twin_runtime/domain/models/experience.py` with all data models:

- `ExperienceEntry`: id, scenario_type (List[str]), insight, applicable_when, not_applicable_when, domain, source_trace_id, was_correct, weight (float, default 1.0), confirmation_count (int, default 0), created_at, last_confirmed, entry_kind (Literal["principle", "narrative", "reflection"], default "reflection")
- `PatternInsight`: id, pattern_description, systematic_bias, correction_strategy, affected_trace_ids, domains, weight (default 2.0), created_at — placeholder for Phase D
- `SearchResult`: kind (Literal["entry", "pattern"]), score (float), entry (Optional[ExperienceEntry]), pattern (Optional[PatternInsight]). Typed wrapper so callers can distinguish results without isinstance checks
- `ExperienceLibrary`: entries (List[ExperienceEntry]), patterns (List[PatternInsight]), version. Methods:
  - `search(query_keywords, top_k=5, min_weight=0.1) -> List[SearchResult]`: returns typed results
  - `search_entries(query_keywords, top_k=5, min_weight=0.1) -> List[ExperienceEntry]`: convenience — entries only, no patterns
  - `add(entry)`, `size` property

Create `src/twin_runtime/infrastructure/backends/json_file/experience_store.py`:

- `ExperienceLibraryStore(base_dir, user_id)`: load/save to `{base_dir}/{user_id}/experience_library.json`
- Validate user_id with `_validate_safe_id()` (same pattern as other backends)
- `load() -> ExperienceLibrary` (returns empty library if file doesn't exist)
- `save(library: ExperienceLibrary)`

Search scoring formula: `overlap(query_keywords ∩ scenario_type) × weight × (1 + 0.1 × confirmation_count)`. PatternInsight entries score with 1.5× bonus multiplier. Results are wrapped in `SearchResult` with `kind` set appropriately.

Tests: `tests/test_experience_library.py` — search ranking, search_entries vs search (typed results), add/persistence roundtrip, empty library, confirmation_count boost, PatternInsight in search returns kind="pattern", min_weight filter.

Commit: `"feat: ExperienceLibrary data model with typed search results and JSON persistence"`

---

## Step 2: Bootstrap Questions Schema + Question Set (B1 part 1)

Create `src/twin_runtime/application/bootstrap/__init__.py` (package marker).

Create `src/twin_runtime/application/bootstrap/questions.py`:

- `QuestionType` enum: FORCED_CHOICE, SLIDER, OPEN_SCENARIO
  - Note: DOCUMENT_UPLOAD is deferred to a future phase
- `BootstrapQuestion`: id, phase (1-3), type, question, options (List[str]), axes (dict mapping axis_name → [option0_direction, option1_direction] as floats), domain (Optional[str]), tags (List[str])
- `BootstrapAnswer`: question_id, type, chosen_option, slider_value, free_text, domain, tags
- `DEFAULT_QUESTIONS`: 20 questions total:
  - Phase 1: 12 forced-choice covering 5 axes (risk_tolerance, action_threshold, information_threshold, conflict_style proxy, explore_exploit_balance), 2-3 questions per axis for cross-validation
  - Phase 2: 5 questions about domain expertise (work, money, life_planning, relationships, public_expression)
  - Phase 3: 3 open-ended past decision scenarios

Axes mapping for forced-choice: each question maps `axes = {"risk_tolerance": [-0.5, 0.5]}` meaning option[0] pushes axis -0.5, option[1] pushes +0.5. Final axis value = 0.5 + mean(pushes), clamped to [0.0, 1.0].

Tests: `tests/test_bootstrap/test_questions.py` — question count, all axes covered, answer validation, no DOCUMENT_UPLOAD type in DEFAULT_QUESTIONS.

Commit: `"feat: bootstrap question schema + 20 default questions (Phase 1-3)"`

---

## Step 3: BootstrapEngine — Axis Extraction + TwinState Construction (B1 part 2)

Create `src/twin_runtime/application/bootstrap/engine.py`:

- `BootstrapResult`: twin (TwinState), experience_library (ExperienceLibrary), axis_reliability (Dict[str, float])

- `BootstrapEngine(llm: LLMPort)`:
  - `run(answers: List[BootstrapAnswer]) -> BootstrapResult`
  - `_extract_axes(answers) -> Dict[str, List[float]]`: collect axis pushes from forced-choice answers
  - `_compute_axis_values(raw_axes) -> Dict[str, float]`: mean + 0.5 base, clamp [0.0, 1.0]
  - `_check_consistency(raw_axes) -> Dict[str, float]`: if same-axis answers have opposite signs → reliability 0.3, else 0.5
  - `_infer_conflict_style(answers) -> ConflictStyle`: map from conflict-related forced-choice answers
  - `_build_shared_decision_core(axis_values, axis_reliability) -> SharedDecisionCore`
  - `_build_domain_heads(answers) -> List[DomainHead]`: from Phase 2 answers; user-declared domains get head_reliability=0.4, undeclared domains get 0.3
  - `_aggregate_bootstrap_principles(answers, axis_values) -> List[ExperienceEntry]`: 1 LLM call that takes ALL 12 forced-choice answers + computed axis values, synthesizes 3-5 bootstrap principles (one per axis cluster). Each principle is a reusable decision rule, not a per-question fragment. weight=0.9, entry_kind="principle"
  - `_extract_from_narrative(answer: BootstrapAnswer) -> List[ExperienceEntry]`: 1 LLM call per open-ended answer. weight=0.8, entry_kind="narrative"
  - `_build_initial_experiences(answers, axis_values) -> ExperienceLibrary`: calls _aggregate_bootstrap_principles + _extract_from_narrative
  - `_build_twin_state(core, heads, user_id) -> TwinState`: construct full valid TwinState with bootstrap defaults

TwinState construction specifics:
- state_version: "v000-bootstrap"
- scope_declaration.min_reliability_threshold = 0.35 (lowered from default 0.5 so that declared domains at 0.4 pass)
- scope_declaration.user_facing_summary = "Bootstrap-provisional twin. Reliability will improve with calibration data."
- scope_declaration.modeled_capabilities = [user-declared domain names]
- scope_declaration.non_modeled_capabilities = [undeclared domain names]

Tests: `tests/test_bootstrap/test_engine.py`:
- Axis extraction math
- Consistency detection (contradictory answers)
- TwinState validation (Pydantic accepts it)
- valid_domains() returns exactly user-declared domains (head_reliability 0.4 >= threshold 0.35)
- Undeclared domains NOT in valid_domains() (head_reliability 0.3 < 0.35)
- Bootstrap principles: 3-5 aggregated entries (not 12 fragments)
- Experience count from answers: ~5 principles + ~3 narratives = ~8, NOT ~17
- `@pytest.mark.requires_llm` for narrative extraction and principle aggregation

Commit: `"feat: BootstrapEngine with axis extraction, principle aggregation, and TwinState construction"`

---

## Step 4: CLI Bootstrap Command + Mini A/B (B1 part 3)

Modify `src/twin_runtime/cli.py`:

Add `cmd_bootstrap(args)`:
1. Load config, create LLM client
2. Present questions interactively (Phase 1 → 2 → 3)
3. Collect `BootstrapAnswer` list
4. Run `BootstrapEngine.run(answers)` → BootstrapResult
5. Save TwinState via `TwinStore.save_state()`
6. Save ExperienceLibrary via `ExperienceLibraryStore.save()`
7. If `--run-comparison` (default True): load comparison scenarios, run mini A/B with `ComparisonExecutor` (N scenarios, default 5), print table
8. Print summary: axes populated, valid domains, experience count (principles + narratives), mini A/B result

CLI flags:
```
twin-runtime bootstrap
    [--questions PATH]          # custom questions JSON
    [--run-comparison]          # run mini A/B (default: true)
    [--no-comparison]           # skip mini A/B
    [--comparison-scenarios N]  # number of scenarios (default: 5)
```

Note: `--skip-documents` removed since Phase 4 (document upload) is deferred.

Add argparser in `main()`, add to commands dict.

Tests: no interactive CLI tests (would need mock input). Covered by engine unit tests.

Commit: `"feat: twin-runtime bootstrap CLI command with mini A/B comparison"`

---

## Step 5: ReflectionGenerator + Reflect Integration (B3)

Create `src/twin_runtime/application/calibration/reflection_generator.py`:

- `ReflectionResult`: action ("confirmed" | "generated"), was_correct (bool), confirmed_entry_id (Optional[str]), new_entry (Optional[ExperienceEntry])

- `ReflectionGenerator(llm: LLMPort)`:
  - `process(trace: RuntimeDecisionTrace, ground_truth: str, exp_lib: ExperienceLibrary) -> ReflectionResult`
  - Logic:
    - `was_correct = _check_correct(trace, ground_truth)`: fuzzy match trace.final_decision against ground_truth (reuses choice_similarity from fidelity_evaluator)
    - If correct: search exp_lib via `search_entries()` (NOT `search()`) for matching entries, increment `confirmation_count` on best match **only if kind="entry"** (typed result guarantees this), return "confirmed"
    - If incorrect: call LLM to extract `ExperienceEntry` from the miss, return "generated" with new_entry (weight=1.0, entry_kind="reflection")
  - `_generate_entry(trace, ground_truth) -> ExperienceEntry`: 1 LLM call with prompt containing query, recommended, actual, reasoning excerpt. Returns structured ExperienceEntry

Modify `src/twin_runtime/cli.py` `cmd_reflect()`:
- After existing CalibrationCase/outcome processing, add:
  1. Load ExperienceLibrary via `ExperienceLibraryStore`
  2. If trace available: run `ReflectionGenerator.process(trace, args.choice, exp_lib)`
  3. If new_entry: `exp_lib.add(new_entry)`, save
  4. If confirmed: save (confirmation_count updated in place)
  5. Print result

Tests: `tests/test_reflection_generator.py`:
- CF hit → confirmation via search_entries (mock LLM not called), pattern results excluded from confirmation
- CF miss → generation (mock LLM returns structured JSON), entry_kind="reflection"
- _check_correct fuzzy matching
- Empty experience library → no confirmation, no error

Commit: `"feat: ReflectionGenerator with CF-hit confirmation and CF-miss extraction"`

---

## Step 6: ConsistencyChecker + S2 Post-Synthesis Hook (B4)

Create `src/twin_runtime/application/pipeline/consistency_checker.py`:

- `ConsistencyResult`: is_consistent (bool), note (str), confidence_penalty (float 0.0-0.2), conflicting_experience_ids (List[str])

- `ConsistencyChecker(llm: LLMPort)`:
  - `check(trace: RuntimeDecisionTrace, exp_lib: ExperienceLibrary) -> ConsistencyResult`
  - Takes a finalized trace (post-synthesis), checks for consistency against experience library
  - Logic:
    1. Extract keywords from trace.query
    2. Search exp_lib for top 3 relevant entries (via `search_entries()`)
    3. If no relevant entries → return is_consistent=True
    4. Deterministic pre-check: if any high-weight entry's insight contains an option name that contradicts the recommendation → flag
    5. If deterministic check passes → return is_consistent=True (0 LLM calls)
    6. If ambiguous → 1 LLM call for fine-grained check → return result with confidence_penalty

**Integration point — S2 post-synthesis hook in `runtime_orchestrator.py`:**

Modify `src/twin_runtime/application/orchestrator/runtime_orchestrator.py`:
- Add `experience_library: Optional[ExperienceLibrary] = None` parameter to `run()`
- After the S2 `deliberation_loop()` returns the final trace (line ~69-75), add the consistency check:
  ```python
  # S2-only post-synthesis consistency check
  if (route.execution_path == ExecutionPath.S2_DELIBERATE
          and experience_library is not None):
      from twin_runtime.application.pipeline.consistency_checker import ConsistencyChecker
      checker = ConsistencyChecker(llm=llm)
      consistency = checker.check(trace, experience_library)
      if not consistency.is_consistent:
          trace.uncertainty = min(trace.uncertainty + consistency.confidence_penalty, 0.95)
  ```
- For S1 paths: no change, consistency checker is never invoked
- **DO NOT modify `single_pass.py`** — the checker hooks at the orchestrator level, not inside the single-pass executor

Modify `src/twin_runtime/application/orchestrator/deliberation.py`:
- Add `experience_library` parameter to `deliberation_loop()`, forward to trace metadata for audit

Tests: `tests/test_consistency_checker.py`:
- No relevant experiences → consistent (0 LLM calls)
- Deterministic contradiction detected → inconsistent with penalty
- LLM check mock → returns structured result
- S2 integration: mock orchestrator run with experience_library → verify uncertainty increased on S2 path
- S1 gate: verify checker not called when route is S1_DIRECT (experience_library passed but ignored since route != S2)

Commit: `"feat: ConsistencyChecker with S2-only post-synthesis hook in runtime_orchestrator"`

---

## Step 7: Final Verification + README

- [ ] Run full test suite: `python3 -m pytest tests/ -m "not requires_llm"` — all pass
- [ ] Verify 13 golden traces unchanged
- [ ] Verify existing 437+ tests still pass
- [ ] `tests/test_experience_library.py` passes
- [ ] `tests/test_bootstrap/` passes
- [ ] `tests/test_reflection_generator.py` passes
- [ ] `tests/test_consistency_checker.py` passes
- [ ] Update README.md with `bootstrap` command in CLI table
- [ ] Verify ruff lint clean

Commit: `"docs: update README for Phase B bootstrap protocol"`

---

## Final Verification Checklist

- [ ] `twin-runtime bootstrap` builds valid TwinState from scratch
- [ ] 12 forced-choice + 5 domain + 3 open-ended = 20 questions (Phase 1-3)
- [ ] Axis values: 0.5 base + mean(pushes), clamped [0.0, 1.0]
- [ ] Contradictory same-axis answers → reliability 0.3 (below threshold, forces DEGRADE)
- [ ] User-declared domains → head_reliability 0.4, undeclared → 0.3
- [ ] scope_declaration.min_reliability_threshold = 0.35 so declared domains pass valid_domains()
- [ ] 12 forced-choice → 3-5 aggregated bootstrap principles (NOT 12 individual entries)
- [ ] ExperienceLibrary initial entries: ~5 principles (weight 0.9) + ~3 narratives (weight 0.8) = ~8
- [ ] `twin-runtime reflect` CF miss → new ExperienceEntry (weight 1.0, entry_kind="reflection")
- [ ] `twin-runtime reflect` CF hit → confirmation_count += 1 on `search_entries()` best match only
- [ ] ReflectionGenerator never confirms PatternInsight pseudo-results (uses search_entries, not search)
- [ ] ConsistencyChecker hooks in `runtime_orchestrator.py` after `deliberation_loop()`, NOT in `single_pass.py`
- [ ] ConsistencyChecker only triggers on S2 paths
- [ ] ConsistencyChecker never changes final_decision, only adjusts uncertainty
- [ ] Mini A/B runs with ComparisonExecutor on 5 scenarios
- [ ] ExperienceLibrary persists to `~/.twin-runtime/store/{user_id}/experience_library.json`
- [ ] All existing tests still pass
- [ ] 13 golden traces unchanged

---

## Change Log

> Changes from original plan based on pre-implementation review:

1. **ConsistencyChecker integration point (was: single_pass.py → now: runtime_orchestrator.py post-synthesis hook)** — S1 uses single_pass.py directly, S2 goes through deliberation_loop(). Hooking in single_pass.py would either affect S1 (contradicting "S2-only") or require double-wiring. The correct hook point is in `runtime_orchestrator.py` after `deliberation_loop()` returns the final trace.

2. **Bootstrap reliability threshold (was: 0.4 below default 0.5 threshold → now: bootstrap lowers threshold to 0.35)** — With default min_reliability_threshold=0.5, head_reliability=0.4 produces zero valid domains. Fix: bootstrap sets threshold to 0.35 so declared domains (0.4) are usable, undeclared (0.3) are not. Contradictory axes degrade to 0.3 (below 0.35), correctly forcing DEGRADE.

3. **ExperienceLibrary search typing (was: mixed results → now: SearchResult with kind field)** — search() returned untyped mix of entries and pattern pseudo-results. ReflectionGenerator's confirmation_count++ on pattern pseudo-results is semantically invalid. Fix: search() returns typed `SearchResult` objects; `search_entries()` convenience method; confirmation flow only touches entries.

4. **Phase 4 document upload deferred** — DocumentAdapter requires explicit file paths, not Q&A answers. The plan had half-defined Phase 4 with no clear CLI flow. Deferred to future iteration rather than shipping incomplete.

5. **Forced-choice → aggregated principles (was: 12 entries → now: 3-5 principles)** — Storing 12 per-question fragments pollutes the experience library with low-context axis questionnaire shards. Fix: 1 LLM call aggregates all 12 forced-choice answers into 3-5 reusable decision principles (one per axis cluster). Only open narratives and reflect-miss produce concrete experience entries. Library starts at ~8 high-quality entries instead of ~17 noisy ones.

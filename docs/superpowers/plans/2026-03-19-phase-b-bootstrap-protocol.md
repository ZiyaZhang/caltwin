# Phase B: Bootstrap Protocol — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a cold-start system that lets a new user get a usable twin in 15 minutes via `twin-runtime bootstrap`, with ExperienceLibrary for semantic memory, ReflectionGenerator for learning from mistakes, and ConsistencyChecker for S2 self-refine.

**Architecture:** 4 components layered bottom-up: ExperienceLibrary (data model + persistence + keyword search), BootstrapEngine (forced-choice → axis values + narrative → experience extraction), ReflectionGenerator (CF-miss → new entry, CF-hit → confirmation), ConsistencyChecker (S2-only post-arbitration consistency gate). CLI `bootstrap` command orchestrates onboarding + mini A/B comparison.

**Tech Stack:** Python 3.9+, Pydantic v2, pytest. Reuses existing `LLMPort`, `ComparisonExecutor`, `TwinStore`. No new dependencies.

**Key design decisions:**
- ExperienceLibrary is a standalone JSON file at `~/.twin-runtime/store/{user_id}/experience_library.json`, parallel to TwinState
- Bootstrap initial reliability = 0.4; contradictory axes get 0.3
- ReflectionGenerator: CF-hit → 0 LLM calls (confirmation only); CF-miss → 1 LLM call (extraction)
- ConsistencyChecker: S2 only, never changes recommended option, only adjusts uncertainty + annotates
- `ExperienceEntry.weight` starts at 0.6 (forced-choice), 0.8 (narrative), 1.0 (reflect-miss)
- Bootstrap builds a full valid `TwinState` from scratch (no fixture file needed)

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `src/twin_runtime/domain/models/experience.py` | ExperienceEntry, PatternInsight, ExperienceLibrary models |
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
| Modify | `src/twin_runtime/application/pipeline/single_pass.py` | Hook ConsistencyChecker after arbitrate (S2) |
| Modify | `src/twin_runtime/application/orchestrator/runtime_orchestrator.py` | Pass experience_library through pipeline |
| Modify | `README.md` | Add bootstrap + experience library docs |

---

## Step 1: ExperienceLibrary Data Model + Persistence (B2)

Create `src/twin_runtime/domain/models/experience.py` with all data models:

- `ExperienceEntry`: id, scenario_type (List[str]), insight, applicable_when, not_applicable_when, domain, source_trace_id, was_correct, weight (float, default 1.0), confirmation_count (int, default 0), created_at, last_confirmed
- `PatternInsight`: id, pattern_description, systematic_bias, correction_strategy, affected_trace_ids, domains, weight (default 2.0), created_at — placeholder for Phase D
- `ExperienceLibrary`: entries (List[ExperienceEntry]), patterns (List[PatternInsight]), version. Methods: `search(query_keywords, top_k=5, min_weight=0.1)`, `add(entry)`, `size` property

Create `src/twin_runtime/infrastructure/backends/json_file/experience_store.py`:

- `ExperienceLibraryStore(base_dir, user_id)`: load/save to `{base_dir}/{user_id}/experience_library.json`
- `load() -> ExperienceLibrary` (returns empty library if file doesn't exist)
- `save(library: ExperienceLibrary)`

Search scoring formula: `overlap(query_keywords ∩ scenario_type) × weight × (1 + 0.1 × confirmation_count)`. PatternInsight entries score with 1.5× bonus multiplier.

Tests: `tests/test_experience_library.py` — search ranking, add/persistence roundtrip, empty library, confirmation_count boost, PatternInsight pseudo-entry in search, min_weight filter.

Commit: `"feat: ExperienceLibrary data model with keyword search and JSON persistence"`

---

## Step 2: Bootstrap Questions Schema + Question Set (B1 part 1)

Create `src/twin_runtime/application/bootstrap/__init__.py` (package marker).

Create `src/twin_runtime/application/bootstrap/questions.py`:

- `QuestionType` enum: FORCED_CHOICE, SLIDER, OPEN_SCENARIO, DOCUMENT_UPLOAD
- `BootstrapQuestion`: id, phase (1-4), type, question, options (List[str]), axes (dict mapping axis_name → [option0_direction, option1_direction] as floats), domain (Optional[str]), tags (List[str])
- `BootstrapAnswer`: question_id, type, chosen_option, slider_value, free_text, domain, tags
- `DEFAULT_QUESTIONS`: 20 questions total:
  - Phase 1: 12 forced-choice covering 5 axes (risk_tolerance, action_threshold, information_threshold, conflict_style proxy, explore_exploit_balance), 2-3 questions per axis for cross-validation
  - Phase 2: 5 questions about domain expertise (work, money, life_planning, relationships, public_expression)
  - Phase 3: 3 open-ended past decision scenarios

Axes mapping for forced-choice: each question maps `axes = {"risk_tolerance": [-0.5, 0.5]}` meaning option[0] pushes axis -0.5, option[1] pushes +0.5. Final axis value = 0.5 + mean(pushes), clamped to [0.0, 1.0].

Tests: `tests/test_bootstrap/test_questions.py` — question count, all axes covered, answer validation.

Commit: `"feat: bootstrap question schema + 20 default questions"`

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
  - `_build_domain_heads(answers) -> List[DomainHead]`: from Phase 2 answers, initial head_reliability = 0.4
  - `_build_initial_experiences(answers) -> ExperienceLibrary`: forced-choice → weight 0.6, open-scenario → LLM extraction → weight 0.8
  - `_extract_from_narrative(answer: BootstrapAnswer) -> List[ExperienceEntry]`: 1 LLM call per open-ended answer
  - `_build_twin_state(core, heads, user_id) -> TwinState`: construct full valid TwinState with bootstrap defaults

TwinState construction requires: id, created_at, user_id, state_version ("0.1.0-bootstrap"), shared_decision_core, causal_belief_model (default neutral), domain_heads (min 1), transfer_coefficients ([]), reliability_profile (from domain answers), scope_declaration (default conservative), temporal_metadata, active=True.

Tests: `tests/test_bootstrap/test_engine.py` — axis extraction math, consistency detection (contradictory answers), TwinState validation (Pydantic accepts it), experience count from answers, `@pytest.mark.requires_llm` for narrative extraction.

Commit: `"feat: BootstrapEngine with axis extraction and TwinState construction"`

---

## Step 4: CLI Bootstrap Command + Mini A/B (B1 part 3)

Modify `src/twin_runtime/cli.py`:

Add `cmd_bootstrap(args)`:
1. Load config, create LLM client
2. Present questions interactively (Phase 1 → 2 → 3 → 4)
3. Collect `BootstrapAnswer` list
4. Run `BootstrapEngine.run(answers)` → BootstrapResult
5. Save TwinState via `TwinStore.save_state()`
6. Save ExperienceLibrary via `ExperienceLibraryStore.save()`
7. If `--run-comparison` (default True): load comparison scenarios, run mini A/B with `ComparisonExecutor` (N scenarios, default 5), print table
8. Print summary: axes populated, domains, experience count, mini A/B result

CLI flags:
```
twin-runtime bootstrap
    [--questions PATH]          # custom questions JSON
    [--skip-documents]          # skip Phase 4
    [--run-comparison]          # run mini A/B (default: true)
    [--no-comparison]           # skip mini A/B
    [--comparison-scenarios N]  # number of scenarios (default: 5)
```

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
    - `was_correct = _check_correct(trace, ground_truth)`: fuzzy match trace.final_decision against ground_truth
    - If correct: search exp_lib for matching entries, increment `confirmation_count` on best match, return "confirmed"
    - If incorrect: call LLM to extract `ExperienceEntry` from the miss, return "generated" with new_entry
  - `_generate_entry(trace, ground_truth) -> ExperienceEntry`: 1 LLM call with prompt containing query, recommended, actual, reasoning excerpt. Returns structured ExperienceEntry with weight=1.0

Modify `src/twin_runtime/cli.py` `cmd_reflect()`:
- After existing CalibrationCase/outcome processing, add:
  1. Load ExperienceLibrary via `ExperienceLibraryStore`
  2. If trace available: run `ReflectionGenerator.process(trace, args.choice, exp_lib)`
  3. If new_entry: `exp_lib.add(new_entry)`, save
  4. If confirmed: save (confirmation_count updated in place)
  5. Print result

Tests: `tests/test_reflection_generator.py` — CF hit → confirmation (mock LLM not called), CF miss → generation (mock LLM returns structured JSON), _check_correct fuzzy matching, empty experience library.

Commit: `"feat: ReflectionGenerator with CF-hit confirmation and CF-miss extraction"`

---

## Step 6: ConsistencyChecker + S2 Pipeline Integration (B4)

Create `src/twin_runtime/application/pipeline/consistency_checker.py`:

- `ConsistencyResult`: is_consistent (bool), note (str), confidence_penalty (float 0.0-0.2), conflicting_experience_ids (List[str])

- `ConsistencyChecker(llm: LLMPort)`:
  - `check(trace_partial, exp_lib: ExperienceLibrary) -> ConsistencyResult`
  - `trace_partial` is a dict/object with query, final_decision, output_text — enough to check but before full trace is finalized
  - Logic:
    1. Extract keywords from query
    2. Search exp_lib for top 3 relevant entries
    3. If no relevant entries → return is_consistent=True
    4. Deterministic pre-check: if any high-weight entry's insight contains an option name that contradicts the recommendation → flag
    5. If deterministic check passes → return is_consistent=True (0 LLM calls)
    6. If ambiguous → 1 LLM call for fine-grained check → return result with confidence_penalty

Integration point: Modify `src/twin_runtime/application/pipeline/single_pass.py` `execute_from_frame_once()`:
- Add `experience_library: Optional[ExperienceLibrary] = None` parameter
- After `synthesize()` (line ~40 in single_pass.py), if `experience_library` is not None:
  - Run `ConsistencyChecker.check(trace, experience_library)`
  - If not consistent: `trace.uncertainty = min(trace.uncertainty + penalty, 0.95)`

Gate: The orchestrator only passes `experience_library` for S2 paths. For S1, pass None → checker is skipped.

Modify `src/twin_runtime/application/orchestrator/runtime_orchestrator.py`:
- Add `experience_library` parameter to `run()`
- Pass to `deliberation_loop()` and `execute_from_frame_once()` for S2 only
- For S1 calls: pass `experience_library=None`

Modify `src/twin_runtime/application/pipeline/runner.py`:
- Add `experience_library` parameter, pass through to orchestrator

Tests: `tests/test_consistency_checker.py`:
- No relevant experiences → consistent (0 LLM calls)
- Deterministic contradiction detected → inconsistent with penalty
- LLM check mock → returns structured result
- S2 integration: verify uncertainty increased
- S1 gate: verify checker not called

Commit: `"feat: ConsistencyChecker with S2-only gate and experience-based consistency validation"`

---

## Step 7: Final Verification + README

- [ ] Run full test suite: `python3 -m pytest tests/ -m "not requires_llm"` — all pass
- [ ] Verify 13 golden traces unchanged
- [ ] Verify existing 496 tests still pass
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
- [ ] 12 forced-choice + 5 domain + 3 open-ended = 20 questions
- [ ] Axis values: 0.5 base + mean(pushes), clamped [0.0, 1.0]
- [ ] Contradictory same-axis answers → reliability 0.3
- [ ] ExperienceLibrary initial entries: 12 (forced-choice × 0.6) + 3-6 (narrative × 0.8) = 15-18
- [ ] `twin-runtime reflect` CF miss → new ExperienceEntry (weight 1.0)
- [ ] `twin-runtime reflect` CF hit → confirmation_count += 1
- [ ] ConsistencyChecker only triggers on S2 paths
- [ ] ConsistencyChecker never changes final_decision, only adjusts uncertainty
- [ ] Mini A/B runs with ComparisonExecutor on 5 scenarios
- [ ] ExperienceLibrary persists to `~/.twin-runtime/store/{user_id}/experience_library.json`
- [ ] All existing tests still pass
- [ ] 13 golden traces unchanged

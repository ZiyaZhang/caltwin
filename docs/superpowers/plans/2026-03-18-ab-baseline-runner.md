# A/B Baseline Runner — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI `twin-runtime compare` command that runs 4 approaches (vanilla LLM, persona prompt, RAG+persona, full Twin Runtime) on the same decision scenarios and produces a quantified CF comparison report.

**Architecture:** Sync runners sharing a BaseRunner interface, ComparisonExecutor for batch execution + aggregation, CLI command with table/json/html output, HTML report with bar chart + human baseline annotation.

**Tech Stack:** Python 3.9+, Pydantic v2, pytest. tqdm in `[dev]` optional.

**Key design decisions:**
- All sync (no async) — comparison is offline batch evaluation
- `temperature=0` on all LLM baseline calls for determinism
- TwinRunner parses `"Recommended: X (over Y)"` format from `trace.final_decision`
- RagPersonaRunner uses existing `RecallQuery` interface (not custom kwargs)
- `ground_truth="REFUSE"` allowed for out-of-scope scenarios
- CI fixtures in `tests/fixtures/comparison/`, personal data in `data/comparison/` (gitignored)
- tqdm soft-imported, fallback to simple print

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `src/twin_runtime/application/comparison/__init__.py` | Package marker |
| Create | `src/twin_runtime/application/comparison/schemas.py` | ComparisonScenario, ScenarioSet, RunnerOutput, ComparisonReport, AggregateMetrics |
| Create | `src/twin_runtime/application/comparison/runners/__init__.py` | Package marker |
| Create | `src/twin_runtime/application/comparison/runners/base.py` | BaseRunner ABC |
| Create | `src/twin_runtime/application/comparison/runners/vanilla.py` | VanillaRunner (zero context) |
| Create | `src/twin_runtime/application/comparison/runners/persona.py` | PersonaRunner (TwinState persona prompt) |
| Create | `src/twin_runtime/application/comparison/runners/rag_persona.py` | RagPersonaRunner (persona + evidence retrieval) |
| Create | `src/twin_runtime/application/comparison/runners/twin_runner.py` | TwinRunner (full pipeline wrapper) |
| Create | `src/twin_runtime/application/comparison/executor.py` | ComparisonExecutor (batch run + aggregate) |
| Create | `src/twin_runtime/application/comparison/report.py` | HTML comparison report generator |
| Create | `tests/fixtures/comparison/fixtures.json` | ≥20 CI scenarios with ground truth |
| Create | `tests/test_comparison/test_schemas.py` | Schema validation tests |
| Create | `tests/test_comparison/test_runners.py` | Runner unit tests (mock LLM) |
| Create | `tests/test_comparison/test_executor.py` | Executor + aggregate tests |
| Create | `tests/test_comparison/test_report.py` | HTML report generation tests |
| Modify | `src/twin_runtime/cli.py` | Add `compare` subcommand |
| Modify | `pyproject.toml` | Add tqdm to `[dev]` optional |
| Modify | `README.md` | Add `compare` to CLI table |

---

## Step 1: Data Schemas (Task 1)

Create `src/twin_runtime/application/comparison/schemas.py` with all data models. Key points:

- `ComparisonScenario.ground_truth` validator allows `"REFUSE"` OR any option in `options`
- `RunnerOutput.is_correct` is a stored field (set by runner, not computed)
- `AggregateMetrics.pairwise_deltas` stores `"twin_vs_vanilla" → float`

Create `tests/fixtures/comparison/fixtures.json` with ≥20 scenarios covering all domain heads. Include 2-3 REFUSE scenarios.

Tests: `tests/test_comparison/test_schemas.py` — ground_truth validation, fixture loading, REFUSE allowed.

Commit: `"feat: comparison schemas + fixture scenarios"`

---

## Step 2: BaseRunner + VanillaRunner (Task 2)

`BaseRunner` ABC with `runner_id` property and `run_scenario(scenario, twin) -> RunnerOutput`.

`VanillaRunner`:
- System prompt: "You are a helpful assistant. Choose the best option."
- User prompt: query + options, request JSON output
- `temperature=0`
- 3-layer response parsing: JSON → fuzzy match → first option fallback
- `_fuzzy_match`: substring matching, no new dependencies

Tests: prompt building, JSON parse, fallback parse, `@pytest.mark.requires_llm` end-to-end.

Commit: `"feat: BaseRunner + VanillaRunner with 3-layer response parsing"`

---

## Step 3: PersonaRunner + RagPersonaRunner (Task 3)

`PersonaRunner`:
- `_build_persona_system_prompt(twin)`: extract natural language persona from TwinState
- Important: NO raw axis values in prompt (use "moderate risk tolerance" not "0.72")
- Reuses VanillaRunner's LLM call + parse logic

`RagPersonaRunner`:
- Uses existing `RecallQuery` interface: `RecallQuery(query_type="by_topic", user_id=twin.user_id, topic_keywords=query.split()[:10], limit=5)`
- Calls `evidence_store.query(rq)` — existing `JsonFileEvidenceStore.query()`
- If evidence store empty → degrades to PersonaRunner (annotate in output)
- Evidence items use `fragment.summary` field (from `EvidenceFragment`)

Tests: persona prompt quality, RAG degradation when empty store.

Commit: `"feat: PersonaRunner + RagPersonaRunner with RecallQuery integration"`

---

## Step 4: TwinRunner (Task 4)

Thin wrapper around existing `runner.run()` (which delegates to orchestrator):

- `_extract_chosen(trace, options)`: parse `"Recommended: X (over Y)"` format. Fallback: substring match against options.
- REFUSE handling: if `scenario.ground_truth == "REFUSE"`, check `trace.decision_mode.value in ("refused", "degraded")` or `trace.refusal_reason_code is not None`
- `uncertainty` field populated from `trace.uncertainty`

Tests: `@pytest.mark.requires_llm` smoke test.

Commit: `"feat: TwinRunner wrapping existing orchestrator pipeline"`

---

## Step 5: Executor + Aggregate (Task 5)

`ComparisonExecutor`:
- `load_scenarios(path) -> ScenarioSet`
- `run_all(scenario_set, runner_ids=None, progress_callback=None) -> ComparisonReport`
- `_compute_aggregate()`: per-runner CF/confidence/latency, per-domain breakdown, pairwise deltas

Key: progress_callback receives `(done, total)` for tqdm integration.

Tests (most important offline tests):
- Mock runners → verify aggregate math
- Per-domain breakdown grouping
- Pairwise deltas computation
- Empty scenario set → no crash
- Partial runners (only 2 of 4)

Commit: `"feat: ComparisonExecutor with aggregate metrics and domain breakdown"`

---

## Step 6: CLI `compare` Command (Task 6)

Add to `cli.py:main()`:
```
twin-runtime compare
    [--scenarios PATH]        # default: tests/fixtures/comparison/fixtures.json
    [--runners vanilla,twin]  # default: all 4
    [--format table|json|html]
    [--output PATH]
    [--open]
```

`cmd_compare(args)`:
1. Load twin via `_require_twin(config)`
2. Build LLM client, evidence store
3. Instantiate requested runners
4. Load scenarios from path
5. Run with progress (tqdm soft-import, fallback to print)
6. Output as table/json/html

`print_comparison_table()`: formatted CLI table with CF, confidence, latency, pairwise delta, best-baseline summary.

tqdm in `[dev]` optional:
```toml
dev = ["pytest>=7.0", "pytest-cov>=4.0", "ruff>=0.1.0", "tqdm>=4.60.0"]
```

Commit: `"feat: twin-runtime compare CLI command with table/json/html output"`

---

## Step 7: HTML Comparison Report (Task 7)

`src/twin_runtime/application/comparison/report.py`:

Single-file HTML (inline CSS, no external deps), same pattern as existing dashboard generator.

4 sections:
1. **Summary Cards** — 4 metric cards, Twin highlighted
2. **Bar Chart** — CSS-width bars, human test-retest baseline dashed line at 0.85
3. **Per-Scenario Table** — rows = scenarios, cols = runners, ✓/✗ + chosen option
4. **Domain Breakdown** — grouped horizontal bars per domain

Human baseline annotation: "Human test-retest ≈ 0.85" — Stanford digital twin research reference.

Tests: HTML generates without error from mock report data, contains expected sections.

Commit: `"feat: HTML comparison report with bar chart and human baseline annotation"`

---

## Final Verification

- [ ] `tests/fixtures/comparison/fixtures.json` has ≥20 scenarios
- [ ] `python3 -m pytest tests/test_comparison/ -m "not requires_llm"` all pass
- [ ] `twin-runtime compare --format table` produces readable output (with mock or fixture)
- [ ] `twin-runtime compare --format html --output comparison.html` generates valid HTML
- [ ] HTML has 4 sections + human baseline line
- [ ] README updated with `compare` command
- [ ] All 434+ existing tests still pass
- [ ] 13 golden traces unchanged

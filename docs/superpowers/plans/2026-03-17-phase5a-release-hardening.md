# Phase 5a: Release Hardening — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix trust boundary violations, persistence bugs, reasoning correctness, and wire evidence retrieval end-to-end — making the codebase safe for Phase 5b (structured deliberation) and 5c (temporal calibration).

**Architecture:** (1) Lock interface changes first (interpret_situation tuple return, trace new fields, evidence query); (2) Fix trust boundaries (MCP fail-closed, CLI --demo via null adapters, dashboard parameterized); (3) Fix persistence/correctness (evaluator purity, trace store alignment, conflict arbiter); (4) Wire policy engine and retrieval (scope gate, RecallQuery, planner, scan persistence).

**Tech Stack:** Python 3.9+, Pydantic v2, pytest, argparse

**Spec:** `docs/superpowers/specs/2026-03-17-phase5-release-hardening-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `src/twin_runtime/domain/models/situation.py:40-42` | Relax `domain_activation_vector` min_length to 0 |
| Modify | `src/twin_runtime/domain/models/runtime.py:45-73` | Add query, situation_frame, scope_guard_result, refusal_reason_code; relax head_assessments min_length to 0 |
| Modify | `src/twin_runtime/application/pipeline/situation_interpreter.py:158-206` | Return `(SituationFrame, Optional[ScopeGuardResult])` tuple |
| Modify | `src/twin_runtime/application/pipeline/runner.py:19-65` | Unpack tuple, populate new trace fields, assign refusal_reason_code |
| Modify | `src/twin_runtime/infrastructure/backends/json_file/evidence_store.py:50-56` | Implement keyword-level query() |
| Modify | `src/twin_runtime/server/mcp_server.py:84-106` | Remove fixture fallback |
| Modify | `src/twin_runtime/cli.py` | Add --demo parent parser, null adapters, evidence wiring |
| Modify | `src/twin_runtime/application/dashboard/cli.py:1-60` | Remove hardcoded paths, accept store_dir/user_id params |
| Modify | `src/twin_runtime/application/calibration/fidelity_evaluator.py:241-245` | Remove case mutation side effect |
| Modify | `src/twin_runtime/infrastructure/backends/json_file/trace_store.py:26-30` | Fix list_traces to flat + mtime |
| Modify | `src/twin_runtime/application/pipeline/conflict_arbiter.py:27-139` | Split ranking_divergence from utility_conflict_axes |
| Modify | `src/twin_runtime/domain/models/runtime.py:32-42` | Add ranking_divergence_pairs to ConflictReport |
| Modify | `src/twin_runtime/application/calibration/event_collector.py:61-78` | Use trace.query and trace.situation_frame |
| Modify | `src/twin_runtime/application/planner/memory_access_planner.py:70-80` | Accept query param, construct meaningful RecallQuery |
| Create | `src/twin_runtime/application/pipeline/scope_guard.py` | Deterministic scope guard with alias map |
| Create | `tests/test_interface_lock.py` | Tests for new interfaces |
| Create | `tests/test_trust_boundary.py` | Tests for MCP fail-closed, CLI demo, dashboard |
| Create | `tests/test_persistence_correctness.py` | Tests for evaluator purity, trace store, conflict arbiter |
| Create | `tests/test_scope_and_retrieval.py` | Tests for scope gate, RecallQuery, planner, scan persistence |

---

## Chunk 0: Interface Lock

### Task 1: Relax Pydantic constraints + add trace fields

**Files:**
- Modify: `src/twin_runtime/domain/models/situation.py:40-42`
- Modify: `src/twin_runtime/domain/models/runtime.py:45-73`
- Create: `tests/test_interface_lock.py`

- [ ] **Step 1: Write tests for relaxed constraints and new fields**

Create `tests/test_interface_lock.py`:

```python
"""Tests for Phase 5a interface changes — must land before other chunks."""
import pytest
from datetime import datetime, timezone
from twin_runtime.domain.models.primitives import DecisionMode, DomainEnum, ScopeStatus
from twin_runtime.domain.models.situation import SituationFrame, SituationFeatureVector
from twin_runtime.domain.models.runtime import RuntimeDecisionTrace, HeadAssessment, ConflictReport


class TestSituationFrameEmptyActivation:
    def test_empty_activation_allowed(self):
        """SituationFrame must accept empty domain_activation_vector for OUT_OF_SCOPE."""
        from twin_runtime.domain.models.primitives import OrdinalTriLevel, UncertaintyType, OptionStructure
        frame = SituationFrame(
            frame_id="test",
            domain_activation_vector={},
            situation_feature_vector=SituationFeatureVector(
                reversibility=OrdinalTriLevel.MEDIUM,
                stakes=OrdinalTriLevel.MEDIUM,
                uncertainty_type=UncertaintyType.MIXED,
                controllability=OrdinalTriLevel.MEDIUM,
                option_structure=OptionStructure.CHOOSE_EXISTING,
            ),
            ambiguity_score=0.9,
            scope_status=ScopeStatus.OUT_OF_SCOPE,
            routing_confidence=0.0,
        )
        assert frame.domain_activation_vector == {}
        assert frame.scope_status == ScopeStatus.OUT_OF_SCOPE


class TestTraceNewFields:
    def test_trace_accepts_empty_assessments(self):
        """RuntimeDecisionTrace must accept empty head_assessments for REFUSED."""
        trace = RuntimeDecisionTrace(
            trace_id="t1",
            twin_state_version="v1",
            situation_frame_id="f1",
            activated_domains=[],
            head_assessments=[],
            final_decision="Refused",
            decision_mode=DecisionMode.REFUSED,
            uncertainty=1.0,
            created_at=datetime.now(timezone.utc),
        )
        assert trace.head_assessments == []

    def test_trace_has_query_field(self):
        trace = RuntimeDecisionTrace(
            trace_id="t1", twin_state_version="v1", situation_frame_id="f1",
            activated_domains=[], head_assessments=[],
            final_decision="test", decision_mode=DecisionMode.REFUSED,
            uncertainty=1.0, created_at=datetime.now(timezone.utc),
            query="Should I take the job?",
        )
        assert trace.query == "Should I take the job?"

    def test_trace_has_situation_frame_field(self):
        trace = RuntimeDecisionTrace(
            trace_id="t1", twin_state_version="v1", situation_frame_id="f1",
            activated_domains=[], head_assessments=[],
            final_decision="test", decision_mode=DecisionMode.REFUSED,
            uncertainty=1.0, created_at=datetime.now(timezone.utc),
            situation_frame={"scope_status": "out_of_scope"},
        )
        assert trace.situation_frame["scope_status"] == "out_of_scope"

    def test_trace_has_scope_guard_result_field(self):
        trace = RuntimeDecisionTrace(
            trace_id="t1", twin_state_version="v1", situation_frame_id="f1",
            activated_domains=[], head_assessments=[],
            final_decision="test", decision_mode=DecisionMode.REFUSED,
            uncertainty=1.0, created_at=datetime.now(timezone.utc),
            scope_guard_result={"restricted_hit": True, "matched_terms": ["medical"]},
        )
        assert trace.scope_guard_result["restricted_hit"] is True

    def test_trace_has_refusal_reason_code(self):
        trace = RuntimeDecisionTrace(
            trace_id="t1", twin_state_version="v1", situation_frame_id="f1",
            activated_domains=[], head_assessments=[],
            final_decision="Refused", decision_mode=DecisionMode.REFUSED,
            uncertainty=1.0, created_at=datetime.now(timezone.utc),
            refusal_reason_code="OUT_OF_SCOPE",
        )
        assert trace.refusal_reason_code == "OUT_OF_SCOPE"


class TestConflictReportRankingDivergence:
    def test_has_ranking_divergence_pairs(self):
        report = ConflictReport(
            report_id="r1",
            activated_heads=[DomainEnum.WORK, DomainEnum.MONEY],
            conflict_types=["belief"],
            utility_conflict_axes=[],
            ranking_divergence_pairs=["work↔money"],
            resolvable_by_system=False,
            requires_user_clarification=True,
            requires_more_evidence=False,
            final_merge_strategy="clarify",
        )
        assert report.ranking_divergence_pairs == ["work↔money"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_interface_lock.py -v`
Expected: Multiple failures — min_length violations, missing fields.

- [ ] **Step 3: Relax SituationFrame constraint**

In `src/twin_runtime/domain/models/situation.py:40-42`, change:

```python
    domain_activation_vector: Dict[DomainEnum, float] = Field(
        min_length=1,
```

To:

```python
    domain_activation_vector: Dict[DomainEnum, float] = Field(
```

(Remove `min_length=1` entirely.)

- [ ] **Step 4: Add trace fields and relax head_assessments**

In `src/twin_runtime/domain/models/runtime.py`, change `head_assessments` (line 50):

```python
    head_assessments: List[HeadAssessment] = Field(min_length=1)
```

To:

```python
    head_assessments: List[HeadAssessment] = Field(default_factory=list)
```

Add new fields after `created_at` (line 73):

```python
    query: str = Field(default="", description="Original decision query")
    situation_frame: Optional[Dict[str, Any]] = Field(
        default=None,
        description="JSON-safe snapshot of SituationFrame at decision time",
    )
    scope_guard_result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Deterministic scope guard output: {restricted_hit, non_modeled_hit, matched_terms}",
    )
    refusal_reason_code: Optional[str] = Field(
        default=None,
        description="Structured refusal reason: OUT_OF_SCOPE | NON_MODELED | POLICY_RESTRICTED | LOW_RELIABILITY | DEGRADED_SCOPE",
    )
```

Add `ranking_divergence_pairs` to `ConflictReport` (after `utility_conflict_axes`, line 36):

```python
    ranking_divergence_pairs: List[str] = Field(
        default_factory=list,
        description="Cross-domain ranking inversions, e.g. 'work↔money'",
    )
```

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/test_interface_lock.py -v`
Expected: All PASS.

- [ ] **Step 6: Run full test suite to verify no regressions**

Run: `python3 -m pytest tests/ -q -m "not requires_llm" --tb=short`
Expected: All 332+ pass.

- [ ] **Step 7: Commit**

```bash
git add src/twin_runtime/domain/models/situation.py \
  src/twin_runtime/domain/models/runtime.py \
  tests/test_interface_lock.py
git commit -m "feat: lock Phase 5a interfaces — trace fields, empty activation, ranking divergence"
```

### Task 2: Change interpret_situation return type to tuple

**Files:**
- Modify: `src/twin_runtime/application/pipeline/situation_interpreter.py:158-206`
- Modify: `src/twin_runtime/application/pipeline/runner.py:36`
- Modify: `tests/test_interface_lock.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_interface_lock.py`:

```python
class TestInterpretSituationReturnType:
    def test_returns_tuple(self):
        """interpret_situation must return (SituationFrame, Optional[ScopeGuardResult])."""
        from unittest.mock import MagicMock
        from twin_runtime.application.pipeline.situation_interpreter import interpret_situation

        llm = MagicMock()
        llm.ask_structured.return_value = {
            "domain_activation": {"work": 0.9},
            "reversibility": "medium", "stakes": "medium",
            "uncertainty_type": "mixed", "controllability": "medium",
            "option_structure": "choose_existing",
            "ambiguity_score": 0.3, "clarification_questions": [],
        }

        from twin_runtime.domain.models.twin_state import TwinState
        import json
        from pathlib import Path
        twin = TwinState(**json.loads(Path("tests/fixtures/sample_twin_state.json").read_text()))

        result = interpret_situation("Should I deploy?", twin, llm=llm)
        assert isinstance(result, tuple), "Must return (frame, guard_result) tuple"
        frame, guard_result = result
        assert hasattr(frame, "scope_status")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_interface_lock.py::TestInterpretSituationReturnType -v`
Expected: FAIL — returns SituationFrame, not tuple.

- [ ] **Step 3: Update interpret_situation to return tuple**

In `src/twin_runtime/application/pipeline/situation_interpreter.py`, change return type and return statement:

Change signature (line 158):
```python
def interpret_situation(query: str, twin: TwinState, *, llm: LLMPort) -> SituationFrame:
```
To:
```python
def interpret_situation(query: str, twin: TwinState, *, llm: LLMPort) -> tuple:
    """Run the three-stage Situation Interpreter pipeline.
    Returns (SituationFrame, Optional[ScopeGuardResult]).
    """
```

Change return (line 198-206):
```python
    return SituationFrame(
        frame_id=str(uuid.uuid4()),
        domain_activation_vector=filtered_activation,
        situation_feature_vector=feature_vector,
        ambiguity_score=ambiguity,
        clarification_questions=llm_result.get("clarification_questions", []),
        scope_status=scope_status,
        routing_confidence=routing_confidence,
    )
```
To:
```python
    frame = SituationFrame(
        frame_id=str(uuid.uuid4()),
        domain_activation_vector=filtered_activation,
        situation_feature_vector=feature_vector,
        ambiguity_score=ambiguity,
        clarification_questions=llm_result.get("clarification_questions", []),
        scope_status=scope_status,
        routing_confidence=routing_confidence,
    )
    return frame, None  # ScopeGuardResult added in Chunk 3
```

- [ ] **Step 4: Update runner.py to unpack tuple**

In `src/twin_runtime/application/pipeline/runner.py:36`, change:
```python
    frame = interpret_situation(query, twin, llm=llm)
```
To:
```python
    frame, guard_result = interpret_situation(query, twin, llm=llm)
```

After `trace.skipped_domains` assignment (around line 59), add:
```python
    # Phase 5a: populate new trace fields
    trace.query = query
    trace.situation_frame = frame.model_dump(mode="json")
    if guard_result:
        from dataclasses import asdict
        trace.scope_guard_result = asdict(guard_result)

    # Assign refusal_reason_code based on decision mode and available signals
    if trace.decision_mode == DecisionMode.REFUSED:
        if guard_result and getattr(guard_result, 'restricted_hit', False):
            trace.refusal_reason_code = "POLICY_RESTRICTED"
        elif guard_result and getattr(guard_result, 'non_modeled_hit', False):
            trace.refusal_reason_code = "NON_MODELED"
        elif frame.scope_status == ScopeStatus.OUT_OF_SCOPE:
            trace.refusal_reason_code = "OUT_OF_SCOPE"
        else:
            trace.refusal_reason_code = "LOW_RELIABILITY"
    elif trace.decision_mode == DecisionMode.DEGRADED:
        trace.refusal_reason_code = "DEGRADED_SCOPE"
```

Add imports at top of runner.py:
```python
from twin_runtime.domain.models.primitives import DecisionMode, ScopeStatus
```

- [ ] **Step 5: Update backward-compat shim**

Check `src/twin_runtime/runtime/situation_interpreter.py` — if it re-exports `interpret_situation`, it will still work since the function is the same, just returns a tuple now. No change needed if it uses wildcard re-export.

- [ ] **Step 6: Run tests**

Run: `python3 -m pytest tests/test_interface_lock.py tests/ -q -m "not requires_llm" --tb=short`
Expected: All pass. Any tests that directly call `interpret_situation` and expect a SituationFrame (not tuple) will need updating — check `tests/test_situation_interpreter.py` if it exists.

- [ ] **Step 7: Commit**

```bash
git add src/twin_runtime/application/pipeline/situation_interpreter.py \
  src/twin_runtime/application/pipeline/runner.py \
  tests/test_interface_lock.py
git commit -m "feat: interpret_situation returns (frame, guard_result) tuple; runner populates trace fields"
```

---

## Chunk 1: Entry Points & Trust Boundary

### Task 3: MCP fail-closed

**Files:**
- Modify: `src/twin_runtime/server/mcp_server.py:84-106`
- Modify: `tests/test_mcp_resource_fallback.py`
- Modify: `tests/test_mcp_server.py`

- [ ] **Step 1: Write test for fail-closed behavior**

Update `tests/test_mcp_resource_fallback.py`:

Replace `test_mcp_load_twin_uses_fixture` with:
```python
    def test_mcp_load_twin_returns_none_when_empty(self, tmp_path, monkeypatch):
        """_load_twin must return None when store is empty (fail-closed)."""
        from twin_runtime.infrastructure.backends.json_file.twin_store import TwinStore
        from twin_runtime.server.mcp_server import _load_twin

        store = TwinStore(tmp_path / "empty_store")
        monkeypatch.chdir(tmp_path)

        twin = _load_twin(store, "nonexistent-user")
        assert twin is None, "Must fail-closed: no silent fallback to sample twin"
```

- [ ] **Step 2: Remove fixture fallback from _load_twin**

In `src/twin_runtime/server/mcp_server.py`, replace `_load_twin` function (lines 84-106):

```python
def _load_twin(twin_store, user_id):
    """Load twin state from store. Returns None if not found (fail-closed)."""
    from twin_runtime.domain.models.twin_state import TwinState

    if twin_store.has_current(user_id):
        return twin_store.load_state(user_id)

    return None
```

- [ ] **Step 3: Update test_mcp_server.py if needed**

Check `test_no_twin_falls_back_to_fixture` — rename to `test_no_twin_returns_error` and verify it expects error response.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_mcp_resource_fallback.py tests/test_mcp_server.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/server/mcp_server.py tests/test_mcp_resource_fallback.py tests/test_mcp_server.py
git commit -m "fix: MCP fail-closed — remove silent sample twin fallback"
```

### Task 4: CLI --demo mode with null adapters

**Files:**
- Modify: `src/twin_runtime/cli.py`
- Create: `tests/test_trust_boundary.py`

- [ ] **Step 1: Write tests**

Create `tests/test_trust_boundary.py`:

```python
"""Tests for CLI --demo mode and trust boundary."""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


class TestDemoFlag:
    def test_demo_loads_sample_twin(self):
        """--demo must load twin from package resources."""
        from twin_runtime.cli import _get_twin
        twin = _get_twin({}, demo=True)
        assert twin is not None
        assert twin.user_id  # Has a user_id from fixture

    def test_non_demo_raises_without_init(self, tmp_path):
        """Without --demo and without init, must raise TwinNotFoundError."""
        from twin_runtime.cli import _get_twin, TwinNotFoundError
        with pytest.raises(TwinNotFoundError):
            _get_twin({"user_id": "nobody"}, demo=False)

    def test_demo_mode_prints_banner(self, capsys):
        """Demo mode must print [DEMO MODE] banner."""
        from twin_runtime.cli import _get_twin
        _get_twin({}, demo=True)
        captured = capsys.readouterr()
        assert "[DEMO MODE]" in captured.out
```

- [ ] **Step 2: Implement --demo in cli.py**

Add shared parent parser near the top of `cli.py` (after `_STORE_DIR`):

```python
# Shared parent parser for commands that accept --demo
_twin_parent = argparse.ArgumentParser(add_help=False)
_twin_parent.add_argument("--demo", action="store_true",
    help="Use bundled sample twin (no data persisted)")
```

Update `_get_twin` signature:

```python
def _get_twin(config: dict, demo: bool = False) -> TwinState:
    """Load or create TwinState. Raises TwinNotFoundError if unavailable."""
    if demo:
        try:
            from importlib.resources import files
        except ImportError:
            from importlib_resources import files
        import json as _json
        ref = files("twin_runtime") / "resources" / "fixtures" / "sample_twin_state.json"
        twin = TwinState(**_json.loads(ref.read_text()))
        print("[DEMO MODE] Using sample twin. No data will be persisted.")
        return twin

    user_id = config.get("user_id", "default")
    store = TwinStore(str(_STORE_DIR))

    if store.has_current(user_id):
        return store.load_state(user_id)

    raise TwinNotFoundError("No twin state found. Run 'twin-runtime init' first.")
```

Update `_require_twin`:

```python
def _require_twin(config: dict, demo: bool = False) -> TwinState:
    try:
        return _get_twin(config, demo=demo)
    except TwinNotFoundError as e:
        print(str(e))
        sys.exit(1)
```

Update subcommand parsers in `main()` to use parent:

```python
    p_run = sub.add_parser("run", help="Run decision pipeline", parents=[_twin_parent])
    p_status = sub.add_parser("status", help="Show twin state", parents=[_twin_parent])
    p_reflect = sub.add_parser("reflect", help="Record what you actually chose", parents=[_twin_parent])
```

Update `cmd_run`, `cmd_status`, `cmd_reflect` to pass `demo=args.demo` to `_require_twin`.

For `cmd_run`, when `args.demo` is True, skip trace persistence:

```python
def cmd_run(args):
    config = _load_config()
    _apply_env(config)
    from twin_runtime.application.pipeline.runner import run as run_pipeline
    twin = _require_twin(config, demo=getattr(args, 'demo', False))
    trace = run_pipeline(query=args.query, option_set=args.options, twin=twin)

    # Persist trace only in non-demo mode
    if not getattr(args, 'demo', False):
        user_id = config.get("user_id", "default")
        try:
            from twin_runtime.infrastructure.backends.json_file.trace_store import JsonFileTraceStore
            trace_store = JsonFileTraceStore(str(_STORE_DIR / user_id / "traces"))
            trace_store.save_trace(trace)
        except (IOError, OSError) as e:
            print(f"  Warning: could not persist trace: {e}", file=sys.stderr)
    # ... display output ...
```

- [ ] **Step 3: Run tests**

Run: `python3 -m pytest tests/test_trust_boundary.py -v`
Expected: All pass.

- [ ] **Step 4: Run full suite**

Run: `python3 -m pytest tests/ -q -m "not requires_llm" --tb=short`

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/cli.py tests/test_trust_boundary.py
git commit -m "feat: CLI --demo mode with sample twin, no persistence in demo"
```

### Task 5: Dashboard reads real store

**Files:**
- Modify: `src/twin_runtime/application/dashboard/cli.py`
- Modify: `src/twin_runtime/cli.py:344-347`

- [ ] **Step 1: Refactor dashboard_command signature**

Replace entire `src/twin_runtime/application/dashboard/cli.py`:

```python
"""Dashboard CLI command — lives here to avoid circular imports with interfaces/cli.py."""


def dashboard_command(
    *,
    store_dir: str,
    user_id: str,
    output: str = "fidelity_report.html",
    open_browser: bool = False,
) -> None:
    """Generate HTML fidelity dashboard from real user data."""
    import json
    from pathlib import Path
    from twin_runtime.domain.models.twin_state import TwinState
    from twin_runtime.infrastructure.backends.json_file.twin_store import TwinStore
    from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore
    from twin_runtime.application.dashboard.payload import DashboardPayload
    from twin_runtime.application.dashboard.generator import generate_dashboard

    cal_store = CalibrationStore(store_dir, user_id)
    scores = cal_store.list_fidelity_scores(limit=10)
    if not scores:
        print("No fidelity scores found. Run 'twin-runtime evaluate' first.")
        return

    latest_score = scores[0]
    eval_ids = latest_score.evaluation_ids or []
    evals = cal_store.list_evaluations()
    if eval_ids:
        evaluation = next((e for e in evals if e.evaluation_id == eval_ids[-1]), None)
    else:
        evaluation = evals[-1] if evals else None
    if not evaluation:
        print("No evaluation found. Run 'twin-runtime evaluate' first.")
        return

    twin = None
    try:
        twin_store = TwinStore(store_dir)
        twin = twin_store.load_state(user_id, latest_score.twin_state_version)
    except (FileNotFoundError, KeyError):
        try:
            twin_store = TwinStore(store_dir)
            twin = twin_store.load_state(user_id)
        except (FileNotFoundError, KeyError):
            pass

    if twin is None:
        print("Warning: could not load twin state for dashboard. Generating with evaluation data only.")

    biases = cal_store.list_detected_biases()
    payload = DashboardPayload(
        fidelity_score=latest_score, evaluation=evaluation,
        twin=twin, detected_biases=biases, historical_scores=scores,
    )
    html = generate_dashboard(payload)
    Path(output).write_text(html)
    print(f"Dashboard saved: {output}")

    if open_browser:
        import webbrowser
        webbrowser.open(f"file://{Path(output).absolute()}")
```

- [ ] **Step 2: Update cli.py cmd_dashboard**

In `src/twin_runtime/cli.py`, replace `cmd_dashboard`:

```python
def cmd_dashboard(args):
    """Generate HTML fidelity dashboard."""
    config = _load_config()
    user_id = config.get("user_id", "default")
    from twin_runtime.application.dashboard.cli import dashboard_command
    dashboard_command(
        store_dir=str(_STORE_DIR),
        user_id=user_id,
        output=args.output,
        open_browser=args.open,
    )
```

- [ ] **Step 3: Run full suite**

Run: `python3 -m pytest tests/ -q -m "not requires_llm" --tb=short`

- [ ] **Step 4: Commit**

```bash
git add src/twin_runtime/application/dashboard/cli.py src/twin_runtime/cli.py
git commit -m "fix: dashboard reads real store via injected store_dir/user_id"
```

### Task 6: EvidenceStore wired to CLI/MCP + event_collector uses trace fields

**Files:**
- Modify: `src/twin_runtime/cli.py:152-164`
- Modify: `src/twin_runtime/server/mcp_server.py:66-81,113-144`
- Modify: `src/twin_runtime/application/calibration/event_collector.py:61-78`

- [ ] **Step 1: Wire evidence store in cli.py cmd_run**

In `cmd_run`, after `twin = _require_twin(...)`, add evidence store construction:

```python
    user_id = config.get("user_id", "default")
    from twin_runtime.infrastructure.backends.json_file.evidence_store import JsonFileEvidenceStore
    evidence_store = JsonFileEvidenceStore(str(_STORE_DIR / user_id / "evidence"))

    trace = run_pipeline(
        query=args.query,
        option_set=args.options,
        twin=twin,
        evidence_store=evidence_store,
    )
```

- [ ] **Step 2: Wire evidence store in MCP _get_stores**

Update `_get_stores()` to return 5-tuple:

```python
def _get_stores():
    from twin_runtime.infrastructure.backends.json_file.twin_store import TwinStore
    from twin_runtime.infrastructure.backends.json_file.trace_store import JsonFileTraceStore as TraceStore
    from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore
    from twin_runtime.infrastructure.backends.json_file.evidence_store import JsonFileEvidenceStore
    from pathlib import Path
    import os

    store_dir = os.getenv("TWIN_STORE_DIR", str(Path.home() / ".twin-runtime" / "store"))
    user_id = os.getenv("TWIN_USER_ID", "default")

    twin_store = TwinStore(store_dir)
    trace_store = TraceStore(Path(store_dir) / user_id / "traces")
    cal_store = CalibrationStore(store_dir, user_id)
    evidence_store = JsonFileEvidenceStore(Path(store_dir) / user_id / "evidence")

    return twin_store, trace_store, cal_store, evidence_store, user_id
```

Update ALL callers to unpack 5 values. In `_handle_decide`:

```python
    twin_store, trace_store, cal_store, evidence_store, user_id = _get_stores()
    # ...
    trace = run(query=query, option_set=options, twin=twin, evidence_store=evidence_store)
```

Other handlers (`_handle_status`, `_handle_reflect`, `_handle_calibrate`, `_handle_history`): add `evidence_store` to unpacking, use `_` if not needed.

- [ ] **Step 3: Update event_collector to use trace.query and trace.situation_frame**

In `src/twin_runtime/application/calibration/event_collector.py`, update lines 65-78:

Replace:
```python
    candidate = CandidateCalibrationCase(
        ...
        observed_context=f"Query that produced trace {trace.trace_id}",
        ...
        stakes=OrdinalTriLevel.MEDIUM,
        reversibility=OrdinalTriLevel.MEDIUM,
        ...
    )
```

With:
```python
    # Use real query and frame data from trace (Phase 5a)
    observed_context = trace.query if trace.query else f"Query that produced trace {trace.trace_id}"

    # Extract stakes/reversibility from situation_frame snapshot if available
    stakes = OrdinalTriLevel.MEDIUM
    reversibility = OrdinalTriLevel.MEDIUM
    if trace.situation_frame:
        sfv = trace.situation_frame.get("situation_feature_vector", {})
        if sfv.get("stakes"):
            try:
                stakes = OrdinalTriLevel(sfv["stakes"])
            except ValueError:
                pass
        if sfv.get("reversibility"):
            try:
                reversibility = OrdinalTriLevel(sfv["reversibility"])
            except ValueError:
                pass

    candidate = CandidateCalibrationCase(
        ...
        observed_context=observed_context,
        ...
        stakes=stakes,
        reversibility=reversibility,
        ...
    )
```

- [ ] **Step 4: Run full suite**

Run: `python3 -m pytest tests/ -q -m "not requires_llm" --tb=short`

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/cli.py src/twin_runtime/server/mcp_server.py \
  src/twin_runtime/application/calibration/event_collector.py
git commit -m "feat: wire EvidenceStore to CLI/MCP; event_collector uses trace query/frame"
```

---

## Chunk 2: Correctness & Persistence

### Task 7: evaluate_fidelity becomes pure — callers persist used_for_calibration

**Files:**
- Modify: `src/twin_runtime/application/calibration/fidelity_evaluator.py:241-245`
- Modify: `src/twin_runtime/cli.py:242-266`
- Modify: `src/twin_runtime/server/mcp_server.py` (_handle_calibrate)

- [ ] **Step 1: Write test for purity**

Add to `tests/test_persistence_correctness.py` (create file):

```python
"""Tests for persistence correctness and evaluator purity."""
import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone
from twin_runtime.domain.models.primitives import DecisionMode, DomainEnum
from twin_runtime.domain.models.calibration import CalibrationCase
from twin_runtime.domain.models.runtime import HeadAssessment, RuntimeDecisionTrace
from twin_runtime.application.calibration.fidelity_evaluator import evaluate_fidelity


def _make_case(case_id="test-1"):
    return CalibrationCase(
        case_id=case_id,
        created_at=datetime.now(timezone.utc),
        observed_context="test", option_set=["A", "B"],
        actual_choice="A", domain_label=DomainEnum.WORK,
        task_type="test", stakes="high", reversibility="medium",
        confidence_of_ground_truth=0.9,
    )


def _make_trace():
    ha = MagicMock(spec=HeadAssessment)
    ha.domain = DomainEnum.WORK
    ha.option_ranking = ["A", "B"]
    ha.confidence = 0.8
    trace = MagicMock(spec=RuntimeDecisionTrace)
    trace.head_assessments = [ha]
    trace.output_text = "test"
    trace.uncertainty = 0.2
    trace.trace_id = "t1"
    trace.decision_mode = DecisionMode.DIRECT
    return trace


class TestEvaluatorPurity:
    def test_evaluate_fidelity_does_not_mutate_cases(self):
        """evaluate_fidelity must not set case.used_for_calibration."""
        runner = MagicMock(return_value=_make_trace())
        twin = MagicMock()
        twin.state_version = "v1"
        case = _make_case()
        assert case.used_for_calibration is False

        evaluate_fidelity([case], twin, runner=runner)

        assert case.used_for_calibration is False, "Evaluator must not mutate input cases"
```

- [ ] **Step 2: Remove side effect from evaluate_fidelity**

In `src/twin_runtime/application/calibration/fidelity_evaluator.py`, delete the line:

```python
        case.used_for_calibration = True
```

(Around line 245 in current code.)

- [ ] **Step 3: Update callers to persist**

In `src/twin_runtime/cli.py:cmd_evaluate()`, after `cal_store.save_evaluation(evaluation)`:

```python
    # Persist used_for_calibration flag (evaluator is pure, callers persist)
    if not getattr(args, 'demo', False):
        for case in cases:
            case.used_for_calibration = True
            cal_store.save_case(case)
```

In `src/twin_runtime/server/mcp_server.py:_handle_calibrate()`, after `cal_store.save_evaluation(evaluation)`:

```python
        for case in cases:
            case.used_for_calibration = True
            cal_store.save_case(case)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_persistence_correctness.py tests/ -q -m "not requires_llm" --tb=short`

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/application/calibration/fidelity_evaluator.py \
  src/twin_runtime/cli.py src/twin_runtime/server/mcp_server.py \
  tests/test_persistence_correctness.py
git commit -m "fix: evaluate_fidelity becomes pure; callers persist used_for_calibration"
```

### Task 8: TraceStore save/list alignment + mtime sort

**Files:**
- Modify: `src/twin_runtime/infrastructure/backends/json_file/trace_store.py:26-30`
- Modify: `src/twin_runtime/server/mcp_server.py` (_handle_history)

- [ ] **Step 1: Write test**

Add to `tests/test_persistence_correctness.py`:

```python
import json
import time
from pathlib import Path
from twin_runtime.infrastructure.backends.json_file.trace_store import JsonFileTraceStore


class TestTraceStoreAlignment:
    def test_save_then_list_finds_trace(self, tmp_path):
        """save_trace then list_traces must find the saved trace."""
        store = JsonFileTraceStore(tmp_path)
        trace = MagicMock(spec=RuntimeDecisionTrace)
        trace.trace_id = "test-trace-1"
        trace.model_dump_json.return_value = '{"trace_id": "test-trace-1"}'

        store.save_trace(trace)
        traces = store.list_traces()
        assert "test-trace-1" in traces

    def test_list_traces_mtime_order(self, tmp_path):
        """list_traces must return newest first."""
        store = JsonFileTraceStore(tmp_path)
        for tid in ["older", "newer"]:
            (tmp_path / f"{tid}.json").write_text(f'{{"trace_id": "{tid}"}}')
            time.sleep(0.05)  # Ensure different mtime

        traces = store.list_traces()
        assert traces[0] == "newer"

    def test_list_traces_empty_store(self, tmp_path):
        store = JsonFileTraceStore(tmp_path)
        assert store.list_traces() == []
```

- [ ] **Step 2: Fix list_traces**

In `src/twin_runtime/infrastructure/backends/json_file/trace_store.py`, replace `list_traces`:

```python
    def list_traces(self, user_id: str = "", limit: int = 50) -> List[str]:
        """List trace IDs sorted by modification time (newest first)."""
        files = sorted(
            self.base.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return [p.stem for p in files[:limit]]
```

- [ ] **Step 3: Update _handle_history to use trace_store**

In `src/twin_runtime/server/mcp_server.py`, replace `_handle_history` body to use `trace_store.list_traces()` + `trace_store.load_trace()` instead of manual glob.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_persistence_correctness.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/infrastructure/backends/json_file/trace_store.py \
  src/twin_runtime/server/mcp_server.py tests/test_persistence_correctness.py
git commit -m "fix: TraceStore list_traces uses flat glob + mtime sort; _handle_history uses store API"
```

### Task 9: Conflict arbiter ranking_divergence independence

**Files:**
- Modify: `src/twin_runtime/application/pipeline/conflict_arbiter.py`

- [ ] **Step 1: Write test**

Add to `tests/test_persistence_correctness.py`:

```python
from twin_runtime.application.pipeline.conflict_arbiter import _detect_utility_conflict, arbitrate


def _make_assessment(domain, ranking, utility=None):
    a = MagicMock(spec=HeadAssessment)
    a.domain = domain
    a.option_ranking = ranking
    a.confidence = 0.8
    a.utility_decomposition = utility or {}
    return a


class TestConflictArbiterSeparation:
    def test_axis_only_returns_preference(self):
        """Same-axis disagreement without ranking inversion → PREFERENCE."""
        a1 = _make_assessment(DomainEnum.WORK, ["A", "B"], {"growth": 0.9})
        a2 = _make_assessment(DomainEnum.MONEY, ["A", "B"], {"growth": 0.2})
        report = arbitrate([a1, a2])
        assert report is not None
        from twin_runtime.domain.models.primitives import ConflictType
        assert ConflictType.PREFERENCE in report.conflict_types
        assert report.ranking_divergence_pairs == []

    def test_ranking_only_returns_belief(self):
        """Ranking inversion without axis disagreement → BELIEF."""
        a1 = _make_assessment(DomainEnum.WORK, ["A", "B", "C"], {"impact": 0.8})
        a2 = _make_assessment(DomainEnum.MONEY, ["C", "B", "A"], {"roi": 0.8})
        report = arbitrate([a1, a2])
        assert report is not None
        assert ConflictType.BELIEF in report.conflict_types
        assert len(report.ranking_divergence_pairs) > 0
        assert report.utility_conflict_axes == []

    def test_both_returns_mixed(self):
        """Both axis disagreement and ranking inversion → MIXED."""
        a1 = _make_assessment(DomainEnum.WORK, ["A", "B"], {"shared": 0.9})
        a2 = _make_assessment(DomainEnum.MONEY, ["B", "A"], {"shared": 0.2})
        report = arbitrate([a1, a2])
        assert report is not None
        assert ConflictType.MIXED in report.conflict_types
```

- [ ] **Step 2: Split _detect_utility_conflict return**

Replace `_detect_utility_conflict` to return `tuple[List[str], List[str]]`:

```python
def _detect_utility_conflict(assessments: List[HeadAssessment]) -> tuple:
    """Returns (axis_conflicts, ranking_divergences) as separate lists."""
    if len(assessments) < 2:
        return [], []

    axis_conflicts = []
    ranking_divergences = []

    # Strategy 1: same-axis score disagreement
    all_axes = set()
    for a in assessments:
        for k, v in a.utility_decomposition.items():
            if isinstance(v, (int, float)):
                all_axes.add(k)
    for axis in all_axes:
        values = []
        for a in assessments:
            v = a.utility_decomposition.get(axis)
            if isinstance(v, (int, float)):
                values.append(float(v))
        if len(values) >= 2 and (max(values) - min(values)) > 0.3:
            axis_conflicts.append(axis)

    # Strategy 2: ranking inversion detection
    for i in range(len(assessments)):
        for j in range(i + 1, len(assessments)):
            r1 = assessments[i].option_ranking
            r2 = assessments[j].option_ranking
            if not r1 or not r2 or len(r1) < 2 or len(r2) < 2:
                continue
            top1, top2 = r1[0], r2[0]
            if top1 != top2:
                try:
                    rank_of_top1_in_r2 = r2.index(top1) + 1
                except ValueError:
                    rank_of_top1_in_r2 = len(r2)
                if rank_of_top1_in_r2 > 1:
                    ranking_divergences.append(
                        f"{assessments[i].domain.value}↔{assessments[j].domain.value}"
                    )

    return axis_conflicts, ranking_divergences
```

- [ ] **Step 3: Update _classify_conflict and arbitrate**

Remove `_detect_ranking_disagreement` function (subsumed by new ranking_divergences).

Update `_classify_conflict`:

```python
def _classify_conflict(
    axis_conflicts: List[str],
    ranking_divergences: List[str],
) -> List[ConflictType]:
    if axis_conflicts and ranking_divergences:
        return [ConflictType.MIXED]
    elif axis_conflicts:
        return [ConflictType.PREFERENCE]
    elif ranking_divergences:
        return [ConflictType.BELIEF]
    else:
        return [ConflictType.PREFERENCE]
```

Update `arbitrate`:

```python
def arbitrate(assessments: List[HeadAssessment]) -> Optional[ConflictReport]:
    if len(assessments) <= 1:
        return None

    axis_conflicts, ranking_divergences = _detect_utility_conflict(assessments)

    if not axis_conflicts and not ranking_divergences:
        return None

    conflict_types = _classify_conflict(axis_conflicts, ranking_divergences)
    activated = [a.domain for a in assessments]

    has_preference = ConflictType.PREFERENCE in conflict_types or ConflictType.MIXED in conflict_types
    has_belief = ConflictType.BELIEF in conflict_types

    resolvable = not has_preference
    needs_clarification = has_preference
    needs_evidence = has_belief

    if needs_clarification:
        strategy = MergeStrategy.CLARIFY
    elif resolvable:
        strategy = MergeStrategy.AUTO_MERGE
    else:
        strategy = MergeStrategy.CLARIFY

    return ConflictReport(
        report_id=str(uuid.uuid4()),
        activated_heads=activated,
        conflict_types=conflict_types,
        utility_conflict_axes=axis_conflicts,
        ranking_divergence_pairs=ranking_divergences,
        belief_conflict_axes=[],
        evidence_conflict_sources=[],
        resolvable_by_system=resolvable,
        requires_user_clarification=needs_clarification,
        requires_more_evidence=needs_evidence,
        final_merge_strategy=strategy,
    )
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_persistence_correctness.py tests/ -q -m "not requires_llm" --tb=short`

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/application/pipeline/conflict_arbiter.py \
  tests/test_persistence_correctness.py
git commit -m "fix: ranking_divergence independent from utility_conflict_axes; remove _detect_ranking_disagreement"
```

---

## Chunk 3: Policy Engine & Retrieval

### Task 10: Deterministic scope guard

**Files:**
- Create: `src/twin_runtime/application/pipeline/scope_guard.py`
- Modify: `src/twin_runtime/application/pipeline/situation_interpreter.py`
- Create: `tests/test_scope_and_retrieval.py`

- [ ] **Step 1: Create scope_guard module with alias map**

Create `src/twin_runtime/application/pipeline/scope_guard.py` with `ScopeGuardResult` dataclass, `_SCOPE_ALIASES` map, and `deterministic_scope_guard()` function as specified in the spec.

- [ ] **Step 2: Write tests**

Create `tests/test_scope_and_retrieval.py` with tests for:
- restricted_hit triggers on alias keyword
- non_modeled_hit triggers on alias keyword
- no match returns empty result
- empty activation returns OUT_OF_SCOPE (not work fallback)

- [ ] **Step 3: Integrate into interpret_situation**

Call `deterministic_scope_guard()` before LLM interpretation. Pass result through the tuple return. Update `_apply_routing_policy` to consume guard_result.

- [ ] **Step 4: Fix empty activation fallback**

Change line 133 from `{DomainEnum.WORK: 1.0}` to `{}`.

- [ ] **Step 5: Run tests and commit**

### Task 11: RecallQuery minimum viable implementation

**Files:**
- Modify: `src/twin_runtime/infrastructure/backends/json_file/evidence_store.py:50-56`

- [ ] **Step 1: Implement keyword-level query()**

Replace the `query()` method with filtering by `domain_hint`, `evidence_type`, and `topic_keywords` ranking as specified in spec §5.3.

- [ ] **Step 2: Write tests and commit**

### Task 12: Planner constructs meaningful RecallQuery

**Files:**
- Modify: `src/twin_runtime/application/planner/memory_access_planner.py:70-80`

- [ ] **Step 1: Add query parameter to plan_memory_access**

- [ ] **Step 2: Construct RecallQuery with target_domain + topic_keywords from query**

- [ ] **Step 3: Update runner.py to pass query**

- [ ] **Step 4: Write tests and commit**

### Task 13: Scan/compile persist evidence to store

**Files:**
- Modify: `src/twin_runtime/cli.py` (cmd_scan, cmd_compile)

- [ ] **Step 1: In cmd_scan, persist fragments after scanning**

- [ ] **Step 2: In cmd_compile, persist fragments**

- [ ] **Step 3: Write test and commit**

---

## Final Verification

- [ ] **Run full test suite**: `python3 -m pytest tests/ -q -m "not requires_llm" --tb=short`
- [ ] **Verify persistence integrity matrix**:
  - `python3 -c "..."` for twin save/load round-trip
  - `python3 -c "..."` for trace save/list/load round-trip
  - `python3 -c "..."` for calibration case save/update/load round-trip
  - `python3 -c "..."` for evidence store/query round-trip
- [ ] **Verify trust boundary**: MCP with empty store returns error (not sample twin)
- [ ] **Verify every REFUSED/DEGRADED trace has refusal_reason_code**
- [ ] **Verify trace.query and trace.situation_frame populated**

---

## Notes

- **INSUFFICIENT_EVIDENCE** is in the refusal_reason_code taxonomy but must NOT be produced by 5a code. It is a Phase 5b reserved value.
- Chunk 0 + Chunk 1 tests that mock `interpret_situation` must be updated to expect tuple return.
- Chunk 3 Tasks 10-13 are less detailed intentionally — the implementer should read the spec §5.1-5.5 for exact code. The interface contracts are locked by Chunk 0.

"""CLI entry point for twin-runtime.

Usage:
    twin-runtime init                    # Interactive setup
    twin-runtime run "query" -o "A" "B"  # Run decision pipeline
    twin-runtime scan                    # Scan all sources for evidence
    twin-runtime compile                 # Compile evidence into TwinState
    twin-runtime evaluate                # Run batch evaluation
    twin-runtime status                  # Show twin state summary
    twin-runtime sources                 # List configured sources
    twin-runtime config set KEY VALUE    # Set configuration
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure src is on path when running directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from twin_runtime.domain.models.twin_state import TwinState
from twin_runtime.infrastructure.backends.json_file.twin_store import TwinStore

_CONFIG_DIR = Path.home() / ".twin-runtime"
_CONFIG_FILE = _CONFIG_DIR / "config.json"
_STORE_DIR = _CONFIG_DIR / "store"

_twin_parent = argparse.ArgumentParser(add_help=False)
_twin_parent.add_argument("--demo", action="store_true",
    help="Use bundled sample twin (no data persisted)")


def _load_config() -> dict:
    if _CONFIG_FILE.exists():
        return json.loads(_CONFIG_FILE.read_text())
    return {}


def _save_config(config: dict) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(config, indent=2))
    # Restrict permissions to owner-only (sensitive data like API keys)
    os.chmod(str(_CONFIG_FILE), 0o600)


class TwinNotFoundError(Exception):
    """Raised when no TwinState is available."""
    pass


def _get_twin(config: dict, demo: bool = False) -> TwinState:
    """Load or create TwinState. Raises TwinNotFoundError if unavailable.

    If demo=True, load from bundled sample twin fixture (no persistence).
    """
    if demo:
        import importlib.resources as pkg_resources
        ref = pkg_resources.files("twin_runtime") / "resources" / "fixtures" / "sample_twin_state.json"
        twin = TwinState.model_validate_json(ref.read_text())
        print("[DEMO MODE] Using sample twin. No data will be persisted.")
        return twin

    user_id = config.get("user_id", "default")
    store = TwinStore(str(_STORE_DIR))

    if store.has_current(user_id):
        return store.load_state(user_id)

    raise TwinNotFoundError("No twin state found. Run 'twin-runtime init' first.")


def _require_twin(config: dict, demo: bool = False) -> TwinState:
    """Get twin or print friendly error and exit. For CLI commands that need twin."""
    try:
        return _get_twin(config, demo=demo)
    except TwinNotFoundError as e:
        print(str(e))
        sys.exit(1)


def cmd_init(args):
    """Interactive setup."""
    print("=== Twin Runtime Setup ===\n")
    config = _load_config()

    # User ID
    user_id = input(f"User ID [{config.get('user_id', 'user-default')}]: ").strip()
    if user_id:
        config["user_id"] = user_id
    elif "user_id" not in config:
        config["user_id"] = "user-default"

    # LLM API
    print("\n--- LLM API Configuration ---")
    api_key = input(f"Anthropic API Key [{_mask(config.get('api_key', ''))}]: ").strip()
    if api_key:
        config["api_key"] = api_key

    base_url = input(f"API Base URL [{config.get('api_base_url', 'https://api.anthropic.com')}]: ").strip()
    if base_url:
        config["api_base_url"] = base_url
    elif "api_base_url" not in config:
        config["api_base_url"] = "https://api.anthropic.com"

    model = input(f"Model [{config.get('model', 'claude-sonnet-4-20250514')}]: ").strip()
    if model:
        config["model"] = model
    elif "model" not in config:
        config["model"] = "claude-sonnet-4-20250514"

    # Sources
    print("\n--- Data Sources ---")

    # OpenClaw
    openclaw_path = input(f"OpenClaw workspace path [{config.get('openclaw_path', '')}]: ").strip()
    if openclaw_path:
        config["openclaw_path"] = openclaw_path

    # Notion
    notion_token = input(f"Notion API token [{_mask(config.get('notion_token', ''))}]: ").strip()
    if notion_token:
        config["notion_token"] = notion_token

    # Google
    google_creds = input(f"Google credentials.json path [{config.get('google_credentials', '')}]: ").strip()
    if google_creds:
        config["google_credentials"] = google_creds

    # Twin state fixture
    fixture = input(f"Initial TwinState fixture [{config.get('fixture_path', '')}]: ").strip()
    if fixture:
        config["fixture_path"] = fixture

    _save_config(config)
    _write_env(config)

    print(f"\nConfig saved to {_CONFIG_FILE}")
    print(f"Environment written to {_CONFIG_DIR / '.env'}")

    # Load/create initial twin state if fixture provided
    if config.get("fixture_path"):
        store = TwinStore(str(_STORE_DIR))
        if not store.has_current(config["user_id"]):
            try:
                with open(config["fixture_path"]) as f:
                    twin = TwinState(**json.load(f))
                store.save_state(twin)
                print(f"Twin state initialized: {twin.state_version}")
            except Exception as e:
                print(f"Warning: could not load fixture: {e}")

    print("\nSetup complete! Try: twin-runtime status")


def cmd_run(args):
    """Run decision pipeline."""
    config = _load_config()
    _apply_env(config)
    demo = getattr(args, 'demo', False)

    from twin_runtime.application.orchestrator.runtime_orchestrator import run as orchestrator_run
    from twin_runtime.infrastructure.backends.json_file.evidence_store import JsonFileEvidenceStore

    twin = _require_twin(config, demo=demo)
    user_id = config.get("user_id", "default")
    evidence_store = JsonFileEvidenceStore(str(_STORE_DIR / user_id / "evidence"))

    # Load ExperienceLibrary for ConsistencyChecker (S2 paths)
    exp_lib = None
    if not demo:
        try:
            from twin_runtime.infrastructure.backends.json_file.experience_store import ExperienceLibraryStore
            exp_store = ExperienceLibraryStore(str(_STORE_DIR), user_id)
            exp_lib = exp_store.load()
            if exp_lib.size == 0:
                exp_lib = None  # Don't pass empty library
        except Exception:
            pass  # No experience library yet — ConsistencyChecker will be skipped

    trace = orchestrator_run(
        query=args.query,
        option_set=args.options,
        twin=twin,
        evidence_store=evidence_store,
        experience_library=exp_lib,
        max_deliberation_rounds=getattr(args, 'max_rounds', 2),
    )

    # Persist trace for reflect --trace-id linkage (skip in demo mode)
    if not demo:
        try:
            from twin_runtime.infrastructure.backends.json_file.trace_store import JsonFileTraceStore
            trace_store = JsonFileTraceStore(str(_STORE_DIR / user_id / "traces"))
            trace_store.save_trace(trace)
        except (IOError, OSError) as e:
            print(f"  Warning: could not persist trace: {e}", file=sys.stderr)

    if args.json:
        print(trace.model_dump_json(indent=2))
    else:
        print(f"\n{'='*60}")
        print(f"Decision: {trace.final_decision}")
        print(f"Mode: {trace.decision_mode.value} | Uncertainty: {trace.uncertainty:.2f}")
        print(f"Domains: {[d.value for d in trace.activated_domains]}")
        print(f"Route: {trace.route_path} | Policy: {trace.boundary_policy}")
        if trace.refusal_reason_code:
            print(f"Refusal: {trace.refusal_reason_code}")
        if trace.deliberation_rounds > 0:
            print(f"Deliberation: {trace.deliberation_rounds} rounds | Terminated: {trace.terminated_by}")
        if trace.output_text:
            print(f"\n{trace.output_text}")
        print(f"{'='*60}")
        print(f"Trace: {trace.trace_id}")
        print(f"  (Use: twin-runtime reflect --trace-id {trace.trace_id} --choice \"...\")")


def cmd_scan(args):
    """Scan all configured sources for evidence."""
    config = _load_config()
    registry = _build_registry(config)

    sources = registry.list_sources()
    if not sources:
        print("No sources configured. Run 'twin-runtime init' first.")
        return

    print(f"Scanning {len(sources)} sources: {', '.join(sources)}")
    status = registry.check_all()
    for name, ok in status.items():
        print(f"  {'OK' if ok else 'FAIL'} {name}")

    fragments = registry.scan_all()
    print(f"\nFound {len(fragments)} evidence fragments:")
    by_type = {}
    for f in fragments:
        by_type.setdefault(f.evidence_type.value, []).append(f)
    for etype, frags in sorted(by_type.items()):
        print(f"  {etype}: {len(frags)}")

    # Persist evidence fragments to store
    user_id = config.get("user_id", "default")
    from twin_runtime.infrastructure.backends.json_file.evidence_store import JsonFileEvidenceStore
    evidence_store = JsonFileEvidenceStore(str(_STORE_DIR / user_id / "evidence"))
    persisted = 0
    for fragment in fragments:
        try:
            evidence_store.store_fragment(fragment)
            persisted += 1
        except Exception as e:
            print(f"  Warning: could not persist fragment: {e}", file=sys.stderr)
    print(f"Persisted {persisted}/{len(fragments)} evidence fragments to store.")

    if args.verbose:
        for f in fragments[:20]:
            print(f"\n  [{f.evidence_type.value}] {f.summary}")
            if f.raw_excerpt:
                print(f"    {f.raw_excerpt[:100]}...")


def cmd_compile(args):
    """Compile evidence into TwinState update."""
    config = _load_config()
    _apply_env(config)

    from twin_runtime.application.compiler.persona_compiler import PersonaCompiler

    registry = _build_registry(config)
    twin = _require_twin(config)

    compiler = PersonaCompiler(registry)
    updated, graph, fragments = compiler.compile(existing=twin)

    # Save updated state
    store = TwinStore(str(_STORE_DIR))
    store.save_state(updated)

    # Persist evidence fragments to store
    user_id = config.get("user_id", "default")
    from twin_runtime.infrastructure.backends.json_file.evidence_store import JsonFileEvidenceStore
    evidence_store = JsonFileEvidenceStore(str(_STORE_DIR / user_id / "evidence"))
    persisted = 0
    for fragment in fragments:
        try:
            evidence_store.store_fragment(fragment)
            persisted += 1
        except Exception as e:
            print(f"  Warning: could not persist fragment: {e}", file=sys.stderr)

    print(f"Compiled {len(fragments)} fragments")
    print(f"Twin state: {twin.state_version} → {updated.state_version}")
    print(f"Evidence graph: {len(graph.edges)} edges")
    print(f"Evidence count: {twin.shared_decision_core.evidence_count} → {updated.shared_decision_core.evidence_count}")
    print(f"Persisted {persisted}/{len(fragments)} evidence fragments to store.")


def cmd_evaluate(args):
    """Run batch evaluation."""
    config = _load_config()
    _apply_env(config)

    from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore

    twin = _require_twin(config)
    user_id = config.get("user_id", "default")
    cal_store = CalibrationStore(str(_STORE_DIR), user_id)

    cases = cal_store.list_cases(used=False)
    if not cases:
        print("No calibration cases found. Add cases first.")
        return

    print(f"Evaluating {len(cases)} cases against twin {twin.state_version}...")

    from twin_runtime.application.calibration.fidelity_evaluator import evaluate_fidelity
    evaluation = evaluate_fidelity(cases, twin)

    cal_store.save_evaluation(evaluation)

    # Mark cases as used for calibration
    for case in cases:
        case.used_for_calibration = True
        cal_store.save_case(case)

    # Compute and save fidelity scores (raw + weighted)
    from twin_runtime.application.calibration.fidelity_evaluator import compute_fidelity_score
    historical_evaluations = [e for e in cal_store.list_evaluations() if e.evaluation_id != evaluation.evaluation_id]
    raw_score = compute_fidelity_score(evaluation, historical_evaluations=historical_evaluations, weighted=False)
    weighted_score = compute_fidelity_score(evaluation, historical_evaluations=historical_evaluations, weighted=True)
    cal_store.save_fidelity_score(weighted_score)

    print(f"\nWeighted CF: {weighted_score.choice_fidelity.value:.3f} (raw: {raw_score.choice_fidelity.value:.3f})")
    print(f"Weighted CQ: {weighted_score.calibration_quality.value:.3f} (raw: {raw_score.calibration_quality.value:.3f})")
    print(f"Domain reliability: {evaluation.domain_reliability}")
    if evaluation.weighted_domain_reliability:
        print(f"Weighted domain reliability: {evaluation.weighted_domain_reliability}")
    if evaluation.failed_case_count > 0:
        print(f"Failed cases (excluded): {evaluation.failed_case_count}")
    if evaluation.abstention_accuracy is not None:
        print(f"Abstention accuracy: {evaluation.abstention_accuracy:.3f} ({evaluation.abstention_case_count} OOS cases)")
    print(f"Evaluation ID: {evaluation.evaluation_id}")


def cmd_status(args):
    """Show twin state summary."""
    config = _load_config()
    demo = getattr(args, 'demo', False)
    twin = _require_twin(config, demo=demo)

    print(f"Twin: {twin.id}")
    print(f"User: {twin.user_id}")
    print(f"Version: {twin.state_version}")
    print(f"Active: {twin.active}")
    print(f"\nDecision Core:")
    core = twin.shared_decision_core
    print(f"  Risk tolerance:    {core.risk_tolerance}")
    print(f"  Conflict style:    {core.conflict_style.value}")
    print(f"  Core confidence:   {core.core_confidence}")
    print(f"  Evidence count:    {core.evidence_count}")
    print(f"  Last calibrated:   {core.last_recalibrated_at.strftime('%Y-%m-%d %H:%M')}")

    print(f"\nDomain Heads:")
    for h in twin.domain_heads:
        valid = "valid" if h.head_reliability >= twin.scope_declaration.min_reliability_threshold else "below threshold"
        print(f"  {h.domain.value:20s} rel={h.head_reliability:.2f} ({valid})")
        print(f"    goals: {h.goal_axes}")

    print(f"\nValid domains: {[d.value for d in twin.valid_domains()]}")
    print(f"Scope threshold: {twin.scope_declaration.min_reliability_threshold}")

    if args.json:
        print(f"\n--- Full JSON ---")
        print(twin.model_dump_json(indent=2))


def cmd_sources(args):
    """List configured data sources."""
    config = _load_config()
    registry = _build_registry(config)

    sources = registry.list_sources()
    if not sources:
        print("No sources configured.")
        return

    status = registry.check_all()
    for name in sources:
        ok = status.get(name, False)
        adapter = registry.get(name)
        meta = adapter.get_source_metadata() if adapter else {}
        print(f"  {'OK' if ok else 'FAIL'} {name}")
        for k, v in meta.items():
            if k != "source_type":
                print(f"       {k}: {v}")


def cmd_config(args):
    """Get/set configuration."""
    config = _load_config()
    if args.action == "set":
        if not args.key or not args.value:
            print("Usage: twin-runtime config set <key> <value>")
            return
        config[args.key] = args.value
        _save_config(config)
        _write_env(config)
        print(f"Set {args.key} = {_mask(args.value) if 'key' in args.key.lower() or 'token' in args.key.lower() else args.value}")
    elif args.action == "get":
        if not args.key:
            print("Usage: twin-runtime config get <key>")
            return
        val = config.get(args.key, "(not set)")
        print(f"{args.key} = {_mask(val) if 'key' in args.key.lower() or 'token' in args.key.lower() else val}")
    elif args.action == "list":
        for k, v in sorted(config.items()):
            display = _mask(v) if ('key' in k.lower() or 'token' in k.lower()) and isinstance(v, str) else v
            print(f"  {k}: {display}")


def cmd_dashboard(args):
    """Generate HTML fidelity dashboard."""
    config = _load_config()
    user_id = config.get("user_id", "default")
    from twin_runtime.application.dashboard.cli import dashboard_command
    dashboard_command(store_dir=str(_STORE_DIR), user_id=user_id, output=args.output, open_browser=args.open)


def cmd_reflect(args):
    """Record an outcome for a previous decision."""
    import uuid as _uuid
    from datetime import datetime, timezone
    from twin_runtime.domain.models.primitives import OutcomeSource, DomainEnum, uncertainty_to_confidence
    from twin_runtime.domain.models.calibration import OutcomeRecord
    from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore

    demo = getattr(args, 'demo', False)
    if demo:
        print("[DEMO MODE] Reflection noted but no data will be persisted.")
        return

    config = _load_config()
    user_id = config.get("user_id", "default")
    cal_store = CalibrationStore(str(_STORE_DIR), user_id)

    if args.trace_id:
        # With trace_id: use full outcome_tracker flow
        try:
            from twin_runtime.application.calibration.outcome_tracker import record_outcome
            from twin_runtime.infrastructure.backends.json_file.trace_store import JsonFileTraceStore
            try:
                twin = _get_twin(config)
            except TwinNotFoundError:
                print("Twin not initialized. Recording as standalone outcome.")
                _save_standalone_outcome(args, cal_store, user_id)
                return
            trace_store = JsonFileTraceStore(str(_STORE_DIR / user_id / "traces"))
            outcome, update = record_outcome(
                trace_id=args.trace_id,
                actual_choice=args.choice,
                source=OutcomeSource.USER_CORRECTION,
                actual_reasoning=args.reasoning,
                twin=twin,
                trace_store=trace_store,
                calibration_store=cal_store,
            )
            print(f"Outcome recorded: {outcome.outcome_id}")
            print(f"  Choice: {outcome.actual_choice}")
            print(f"  Matched prediction: {outcome.choice_matched_prediction}")

            # ReflectionGenerator integration (Phase B)
            try:
                from twin_runtime.application.calibration.reflection_generator import ReflectionGenerator
                from twin_runtime.infrastructure.backends.json_file.experience_store import ExperienceLibraryStore
                from twin_runtime.interfaces.defaults import DefaultLLM

                exp_store = ExperienceLibraryStore(str(_STORE_DIR), user_id)
                exp_lib = exp_store.load()
                trace = trace_store.load_trace(args.trace_id)
                rg = ReflectionGenerator(llm=DefaultLLM())
                ref_result = rg.process(trace, args.choice, exp_lib)
                if ref_result.action == "generated" and ref_result.new_entry:
                    exp_lib.add(ref_result.new_entry)
                    exp_store.save(exp_lib)
                    print(f"  Experience: new lesson extracted (weight=1.0)")
                elif ref_result.action == "confirmed":
                    exp_store.save(exp_lib)
                    if ref_result.confirmed_entry_id:
                        print(f"  Experience: confirmed entry {ref_result.confirmed_entry_id}")
                    else:
                        print(f"  Experience: prediction confirmed (no matching entry to boost)")
            except Exception as e:
                print(f"  Experience library update skipped: {e}", file=sys.stderr)

            if update:
                print(f"  Calibration update generated (not yet applied)")
        except FileNotFoundError:
            print(f"Trace {args.trace_id} not found. Recording as standalone outcome.")
            _save_standalone_outcome(args, cal_store, user_id)
        except Exception as e:
            print(f"Error: {e}. Recording as standalone outcome.")
            _save_standalone_outcome(args, cal_store, user_id)
    else:
        # No trace_id: standalone outcome (manual reflection)
        _save_standalone_outcome(args, cal_store, user_id)




def _save_standalone_outcome(args, cal_store, user_id):
    """Save an outcome without linking to a specific trace."""
    import uuid as _uuid
    from datetime import datetime, timezone
    from twin_runtime.domain.models.primitives import OutcomeSource, DomainEnum
    from twin_runtime.domain.models.calibration import OutcomeRecord

    outcome = OutcomeRecord(
        outcome_id=str(_uuid.uuid4()),
        trace_id="standalone",  # marked as standalone — batch_evaluate should filter these
        user_id=user_id,
        actual_choice=args.choice,
        actual_reasoning=args.reasoning,
        outcome_source=OutcomeSource.USER_REFLECTION if args.reasoning else OutcomeSource.USER_CORRECTION,
        prediction_rank=None,  # unknown — no trace to compare against
        confidence_at_prediction=0.5,  # unknown
        domain=DomainEnum.WORK,  # default — could be enhanced later
        task_type="standalone_reflection",  # distinguishes from pipeline-linked outcomes
        created_at=datetime.now(timezone.utc),
    )
    cal_store.save_outcome(outcome)
    print(f"Standalone outcome recorded: {outcome.outcome_id}")
    print(f"  Choice: {outcome.actual_choice}")
    if args.feedback_target:
        print(f"  Feedback target: {args.feedback_target}")
    print(f"  Note: No trace linked. Use --trace-id for full calibration benefit.")


def cmd_install_skills(args):
    """Install Claude Code skills."""
    from pathlib import Path
    try:
        from importlib.resources import files
    except ImportError:
        from importlib_resources import files

    if args.personal:
        target = Path.home() / ".claude" / "skills"
    else:
        target = Path.cwd() / ".claude" / "skills"

    target.mkdir(parents=True, exist_ok=True)

    try:
        skills_pkg = files("twin_runtime.resources.skills")
    except (ModuleNotFoundError, TypeError):
        # Fallback: try to find skills relative to this file
        skills_pkg = Path(__file__).parent / "resources" / "skills"
        if not skills_pkg.exists():
            print("Error: skills resources not found. Is twin-runtime installed correctly?")
            return

    installed = []
    for skill_dir in sorted(skills_pkg.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_name = skill_dir.name
        dest = target / skill_name
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        if dest.exists() and not args.force:
            print(f"  SKIP {skill_name} (already exists, use --force to overwrite)")
            continue
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "SKILL.md").write_text(skill_file.read_text())
        installed.append(skill_name)
        print(f"  OK   {skill_name}")

    print(f"\nInstalled {len(installed)} skills to {target}")


def cmd_drift_report(args):
    """Generate drift detection report."""
    config = _load_config()
    _apply_env(config)
    user_id = config.get("user_id", "default")
    twin = _require_twin(config)

    from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore
    from twin_runtime.infrastructure.backends.json_file.trace_store import JsonFileTraceStore
    from twin_runtime.application.calibration.drift_detector import detect_drift
    from datetime import datetime, timezone

    cal_store = CalibrationStore(str(_STORE_DIR), user_id)
    trace_store = JsonFileTraceStore(str(_STORE_DIR / user_id / "traces"))

    cases = cal_store.list_cases(used=None)
    trace_ids = trace_store.list_traces(limit=10000)
    traces = []
    for tid in trace_ids:
        try:
            traces.append(trace_store.load_trace(tid))
        except Exception:
            continue

    as_of = datetime.now(timezone.utc)
    report = detect_drift(cases, traces, twin, as_of=as_of)

    # Persist
    report_dir = _STORE_DIR / user_id / "reports" / "drift"
    report_dir.mkdir(parents=True, exist_ok=True)
    output_path = getattr(args, 'output', None) or str(report_dir / f"{as_of.strftime('%Y%m%d_%H%M%S')}.json")
    Path(output_path).write_text(report.model_dump_json(indent=2))

    print(f"Drift report saved: {output_path}")
    print(f"Domain signals: {len(report.domain_signals)}, Axis signals: {len(report.axis_signals)}")
    for sig in report.domain_signals:
        print(f"  [{sig.dimension}] {sig.direction} (magnitude={sig.magnitude:.2f})")
    for sig in report.axis_signals:
        print(f"  [{sig.dimension}] {sig.direction} (magnitude={sig.magnitude:.2f})")


def cmd_ontology_report(args):
    """Generate shadow ontology report."""
    try:
        from twin_runtime.application.ontology.report_generator import generate_ontology_report
    except ImportError:
        print("This command requires: pip install twin-runtime[analysis]")
        return

    config = _load_config()
    _apply_env(config)
    user_id = config.get("user_id", "default")
    twin = _require_twin(config)

    from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore
    from datetime import datetime, timezone

    cal_store = CalibrationStore(str(_STORE_DIR), user_id)
    cases = cal_store.list_cases(used=None)

    as_of = datetime.now(timezone.utc)
    report = generate_ontology_report(cases, twin, as_of=as_of)

    # Persist
    report_dir = _STORE_DIR / user_id / "reports" / "ontology"
    report_dir.mkdir(parents=True, exist_ok=True)
    output_path = getattr(args, 'output', None) or str(report_dir / f"{as_of.strftime('%Y%m%d_%H%M%S')}.json")
    Path(output_path).write_text(report.model_dump_json(indent=2))

    print(f"Ontology report saved: {output_path}")
    print(f"Domains analyzed: {report.domains_analyzed}")
    print(f"Suggestions: {len(report.suggestions)}")
    for s in report.suggestions:
        label = s.llm_label or s.deterministic_label
        print(f"  [{s.parent_domain.value}] {label} (support={s.support_count}, stability={s.stability_score:.2f})")


def cmd_bootstrap(args):
    """Interactive bootstrap: build a usable twin in 15 minutes."""
    config = _load_config()
    _apply_env(config)

    from twin_runtime.application.bootstrap.questions import (
        DEFAULT_QUESTIONS,
        QuestionType,
        BootstrapAnswer,
    )
    from twin_runtime.application.bootstrap.engine import BootstrapEngine, validate_bootstrap_questions
    from twin_runtime.infrastructure.backends.json_file.experience_store import (
        ExperienceLibraryStore,
    )
    from twin_runtime.interfaces.defaults import DefaultLLM

    user_id = config.get("user_id", "user-default")
    questions = DEFAULT_QUESTIONS
    # Load custom questions if provided
    if getattr(args, "questions", None):
        import json as _json
        from twin_runtime.application.bootstrap.questions import BootstrapQuestion
        try:
            with open(args.questions) as f:
                raw = _json.load(f)
            if not isinstance(raw, list):
                print(f"Error: questions file must contain a JSON array, got {type(raw).__name__}")
                sys.exit(1)
            questions = [BootstrapQuestion(**q) for q in raw]
        except FileNotFoundError:
            print(f"Error: questions file not found: {args.questions}")
            sys.exit(1)
        except _json.JSONDecodeError as e:
            print(f"Error: invalid JSON in questions file: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"Error: could not load questions file: {e}")
            sys.exit(1)

    # Validate question set before starting interactive session (fail-early)
    try:
        validate_bootstrap_questions(questions)
    except ValueError as e:
        print(f"Error: invalid question set — {e}")
        sys.exit(1)

    # Pre-flight LLM check before starting interactive session
    try:
        llm = DefaultLLM()
        llm.ask_text("ping", "respond with 'ok'", max_tokens=8)
        print("LLM connection verified.\n")
    except Exception as e:
        print(f"Error: LLM connection failed — {e}")
        print("Check your API key (twin-runtime config get api_key) and network.")
        sys.exit(1)

    # Present questions interactively
    answers = []
    phases = sorted(set(q.phase for q in questions))
    phase_names = {1: "Decision Style", 2: "Domain Expertise", 3: "Past Decisions"}

    for phase in phases:
        phase_qs = [q for q in questions if q.phase == phase]
        print(f"\n{'='*60}")
        print(f"  Phase {phase}: {phase_names.get(phase, 'Questions')} ({len(phase_qs)} questions)")
        print(f"{'='*60}\n")

        for q in phase_qs:
            print(f"  {q.question}")
            if q.type == QuestionType.FORCED_CHOICE and q.options:
                for i, opt in enumerate(q.options):
                    print(f"    [{i}] {opt}")
                while True:
                    raw = input("  Your choice (number): ").strip()
                    try:
                        idx = int(raw)
                        if 0 <= idx < len(q.options):
                            answers.append(BootstrapAnswer(
                                question_id=q.id, type=q.type,
                                chosen_option=idx, domain=q.domain, tags=q.tags,
                            ))
                            break
                    except ValueError:
                        pass
                    print(f"  Please enter a number 0-{len(q.options)-1}")

            elif q.type == QuestionType.OPEN_SCENARIO:
                text = input("  Your answer: ").strip()
                answers.append(BootstrapAnswer(
                    question_id=q.id, type=q.type,
                    free_text=text, domain=q.domain, tags=q.tags,
                ))

            print()

    # Run engine (llm already created and verified above)
    print("\nProcessing your answers...")
    engine = BootstrapEngine(llm=llm, questions=questions)
    result = engine.run(answers, user_id=user_id)

    # Save
    store = TwinStore(str(_STORE_DIR))
    store.save_state(result.twin)

    exp_store = ExperienceLibraryStore(str(_STORE_DIR), user_id)
    exp_store.save(result.experience_library)

    # Summary
    print(f"\n{'='*60}")
    print(f"  Bootstrap Complete!")
    print(f"{'='*60}")
    print(f"  Twin version: {result.twin.state_version}")
    print(f"  Valid domains: {[d.value for d in result.twin.valid_domains()]}")
    print(f"  Experience entries: {result.experience_library.size}")
    print(f"  Axis reliability: {result.axis_reliability}")
    print(f"\n  Try: twin-runtime run \"<your question>\" -o \"Option A\" \"Option B\"")

    # Optional mini A/B comparison
    if not getattr(args, "no_comparison", False):
        try:
            _run_bootstrap_comparison(result.twin, args)
        except Exception as e:
            print(f"\n  Mini A/B skipped: {e}")


def _run_bootstrap_comparison(twin, args):
    """Run mini A/B comparison after bootstrap using the orchestrator."""
    from twin_runtime.application.orchestrator.runtime_orchestrator import run as orchestrator_run
    from twin_runtime.interfaces.defaults import DefaultLLM

    n = getattr(args, "comparison_scenarios", 5)
    print(f"\n  Running mini A/B with {n} scenarios...")
    print("  (Use --no-comparison to skip this step)\n")

    # Comparison scenarios — matches onboarding language (Chinese)
    scenarios = [
        ("新工作给了offer，要不要谈薪资？", ["积极谈判争取更高", "直接接受现有条件"]),
        ("同事的项目方案有明显问题，我该怎么办？", ["直接指出问题", "先观望再说"]),
        ("手上有一笔存款，投资风格怎么选？", ["稳健型基金", "高成长型股票"]),
        ("远程工作和坐班工作怎么选？", ["选远程工作", "留在坐班岗位"]),
        ("朋友找我借一大笔钱，怎么处理？", ["借给他", "委婉拒绝"]),
        ("要不要在社交媒体上发表有争议的观点？", ["发出去", "留着不发"]),
        ("要不要换行业追求热爱的方向？", ["立刻转行", "留在原行业慢慢规划"]),
    ][:n]

    llm = DefaultLLM()
    results = []
    for query, options in scenarios:
        try:
            trace = orchestrator_run(query=query, option_set=options, twin=twin, llm=llm)
            mode = trace.decision_mode.value
            unc = trace.uncertainty
            decision = trace.final_decision[:60]
            results.append((query[:40], decision, mode, unc))
            print(f"  [{mode:8s} u={unc:.2f}] {query[:45]}")
            print(f"    → {decision}")
        except Exception as e:
            results.append((query[:40], f"ERROR: {e}", "error", 1.0))
            print(f"  [ERROR] {query[:45]}: {e}")

    # Summary
    direct = sum(1 for _, _, m, _ in results if m == "direct")
    avg_unc = sum(u for _, _, _, u in results) / len(results) if results else 1.0
    print(f"\n  Summary: {direct}/{len(results)} direct answers, avg uncertainty {avg_unc:.2f}")


def cmd_mcp_serve(args):
    """Start MCP server (stdio, blocking)."""
    import asyncio
    from twin_runtime.server.mcp_server import run_server
    asyncio.run(run_server())


# --- Helpers ---

def _build_registry(config: dict):
    from twin_runtime.infrastructure.sources.registry import SourceRegistry
    from twin_runtime.infrastructure.sources.openclaw_adapter import OpenClawAdapter
    from twin_runtime.infrastructure.sources.notion_adapter import NotionAdapter
    from twin_runtime.infrastructure.sources.document_adapter import DocumentAdapter

    registry = SourceRegistry()

    if config.get("openclaw_path"):
        registry.register(OpenClawAdapter(config["openclaw_path"]))

    if config.get("notion_token"):
        registry.register(NotionAdapter(config["notion_token"]))

    doc_files = config.get("document_files", [])
    if doc_files:
        registry.register(DocumentAdapter(doc_files))

    # Gmail and Calendar require google_credentials
    if config.get("google_credentials"):
        try:
            from twin_runtime.infrastructure.sources.gmail_adapter import GmailAdapter
            from twin_runtime.infrastructure.sources.calendar_adapter import CalendarAdapter
            registry.register(GmailAdapter(credentials_path=config["google_credentials"]))
            registry.register(CalendarAdapter(credentials_path=config["google_credentials"]))
        except ImportError:
            pass  # google-api-python-client not installed

    return registry


def _apply_env(config: dict):
    """Set environment variables from config for LLM client."""
    if config.get("api_key"):
        os.environ["ANTHROPIC_API_KEY"] = config["api_key"]
    if config.get("api_base_url"):
        os.environ["ANTHROPIC_BASE_URL"] = config["api_base_url"]
    if config.get("model"):
        os.environ["ANTHROPIC_MODEL"] = config["model"]


def _write_env(config: dict):
    """Write .env file from config."""
    env_path = _CONFIG_DIR / ".env"
    lines = []
    if config.get("api_key"):
        lines.append(f"ANTHROPIC_API_KEY={config['api_key']}")
    if config.get("api_base_url"):
        lines.append(f"ANTHROPIC_BASE_URL={config['api_base_url']}")
    if config.get("model"):
        lines.append(f"ANTHROPIC_MODEL={config['model']}")
    if lines:
        env_path.write_text("\n".join(lines) + "\n")


def _mask(s: str) -> str:
    if not s or len(s) < 8:
        return "***"
    return s[:4] + "..." + s[-4:]


def cmd_compare(args):
    """Run A/B baseline comparison."""
    config = _load_config()
    _apply_env(config)
    demo = getattr(args, 'demo', False)

    from twin_runtime.application.comparison.executor import ComparisonExecutor
    from twin_runtime.application.comparison.runners.vanilla import VanillaRunner
    from twin_runtime.application.comparison.runners.persona import PersonaRunner
    from twin_runtime.application.comparison.runners.rag_persona import RagPersonaRunner
    from twin_runtime.application.comparison.runners.twin_runner import TwinRunner
    from twin_runtime.infrastructure.backends.json_file.evidence_store import JsonFileEvidenceStore
    from twin_runtime.interfaces.defaults import DefaultLLM

    twin = _require_twin(config, demo=demo)
    llm = DefaultLLM()
    if demo:
        # Demo mode: use isolated temp dir so sample twin doesn't mix with real evidence
        import tempfile
        evidence_store = JsonFileEvidenceStore(tempfile.mkdtemp())
    else:
        user_id = config.get("user_id", "default")
        evidence_store = JsonFileEvidenceStore(str(_STORE_DIR / user_id / "evidence"))

    # Build runners
    available = {
        "vanilla": lambda: VanillaRunner(llm),
        "persona": lambda: PersonaRunner(llm),
        "rag_persona": lambda: RagPersonaRunner(llm, evidence_store),
        "twin": lambda: TwinRunner(llm=llm, evidence_store=evidence_store),
    }
    runner_ids = args.runners.split(",") if args.runners else list(available.keys())
    runners = [available[rid]() for rid in runner_ids if rid in available]

    executor = ComparisonExecutor(runners, twin)

    # Load scenarios
    if args.scenarios:
        scenario_path = Path(args.scenarios)
    else:
        import importlib.resources as pkg_resources
        ref = pkg_resources.files("twin_runtime") / "resources" / "fixtures" / "comparison_scenarios.json"
        # Write to a temp path so ScenarioSet.load() works uniformly
        import tempfile
        tmp = Path(tempfile.mktemp(suffix=".json"))
        tmp.write_text(ref.read_text())
        scenario_path = tmp
    scenario_set = executor.load_scenarios(scenario_path)

    # Progress
    try:
        from tqdm import tqdm
        total = len(scenario_set.scenarios) * len(runners)
        bar = tqdm(total=total, desc="Comparing")
        def progress(done, total):
            bar.update(1)
    except ImportError:
        def progress(done, total):
            print(f"\r  [{done}/{total}]", end="", flush=True)

    report = executor.run_all(scenario_set, progress_callback=progress)

    try:
        bar.close()  # type: ignore[name-defined]
    except NameError:
        print()  # newline after progress

    # Output
    if args.output_format == "json":
        output = report.model_dump_json(indent=2)
        if args.output:
            Path(args.output).write_text(output)
            print(f"JSON report written to {args.output}")
        else:
            print(output)
    elif args.output_format == "html":
        from twin_runtime.application.comparison.report import generate_comparison_report
        html = generate_comparison_report(report)
        out_path = args.output or "comparison_report.html"
        Path(out_path).write_text(html)
        print(f"HTML report written to {out_path}")
        if args.open:
            import webbrowser
            webbrowser.open(f"file://{Path(out_path).resolve()}")
    else:
        _print_comparison_table(report)


def _print_comparison_table(report):
    """Print formatted comparison table to stdout."""
    aggs = report.aggregates
    if not aggs:
        print("No results.")
        return

    # Header
    print(f"\n{'Runner':<15} {'CF Score':>10} {'Correct':>10} {'Uncertainty':>12} {'Latency(ms)':>12}")
    print("-" * 62)

    best_cf = max(a.cf_score for a in aggs.values())
    for rid, agg in sorted(aggs.items()):
        marker = " *" if agg.cf_score == best_cf else ""
        unc = f"{agg.mean_uncertainty:.3f}" if agg.mean_uncertainty is not None else "-"
        print(f"{rid:<15} {agg.cf_score:>10.2%} {agg.correct}/{agg.total:>7} {unc:>12} {agg.mean_latency_ms:>12.0f}{marker}")

    # Abstention report (if any REFUSE scenarios)
    has_refuse = any(a.refuse_total > 0 for a in aggs.values())
    if has_refuse:
        print(f"\n{'Abstention (REFUSE scenarios):':}")
        for rid, agg in sorted(aggs.items()):
            if agg.refuse_total > 0:
                print(f"  {rid:<15} {agg.refuse_correct}/{agg.refuse_total} correctly refused")
            else:
                print(f"  {rid:<15} (no REFUSE scenarios scored)")

    # Pairwise deltas
    print(f"\n{'Pairwise Deltas (non-REFUSE only):':}")
    for rid, agg in sorted(aggs.items()):
        for key, delta in sorted(agg.pairwise_deltas.items()):
            print(f"  {key}: {delta:+.4f}")

    # Domain breakdown for best runner
    best_rid = max(aggs, key=lambda k: aggs[k].cf_score)
    if aggs[best_rid].domain_breakdown:
        print(f"\nDomain Breakdown ({best_rid}, non-REFUSE):")
        for d in aggs[best_rid].domain_breakdown:
            print(f"  {d.domain:<20} {d.cf_score:.2%} ({d.correct}/{d.count})")

    print(f"\nCF excludes REFUSE scenarios | * = best | Human test-retest ~0.85")


def main():
    parser = argparse.ArgumentParser(
        prog="twin-runtime",
        description="Calibrated judgment twin runtime",
    )
    sub = parser.add_subparsers(dest="command")

    # init
    sub.add_parser("init", help="Interactive setup")

    # run
    p_run = sub.add_parser("run", help="Run decision pipeline", parents=[_twin_parent])
    p_run.add_argument("query", help="Decision query")
    p_run.add_argument("-o", "--options", nargs="+", required=True, help="Options to evaluate")
    p_run.add_argument("--json", action="store_true", help="Output as JSON")
    p_run.add_argument("--max-rounds", type=int, default=2, help="Max deliberation rounds for S2")

    # scan
    p_scan = sub.add_parser("scan", help="Scan sources for evidence")
    p_scan.add_argument("-v", "--verbose", action="store_true")

    # compile
    sub.add_parser("compile", help="Compile evidence into TwinState")

    # evaluate
    sub.add_parser("evaluate", help="Run batch evaluation")

    # status
    p_status = sub.add_parser("status", help="Show twin state", parents=[_twin_parent])
    p_status.add_argument("--json", action="store_true", help="Full JSON output")

    # sources
    sub.add_parser("sources", help="List configured sources")

    # config
    p_config = sub.add_parser("config", help="Get/set configuration")
    p_config.add_argument("action", choices=["set", "get", "list"])
    p_config.add_argument("key", nargs="?")
    p_config.add_argument("value", nargs="?")

    # dashboard (Phase 3)
    p_dashboard = sub.add_parser("dashboard", help="Generate HTML fidelity dashboard")
    p_dashboard.add_argument("--output", default="fidelity_report.html", help="Output file path")
    p_dashboard.add_argument("--open", action="store_true", help="Open in browser after generating")

    # reflect (Phase 4)
    p_reflect = sub.add_parser("reflect", help="Record what you actually chose (feeds calibration)", parents=[_twin_parent])
    p_reflect.add_argument("--choice", required=True, help="What you actually chose")
    p_reflect.add_argument("--trace-id", help="Link to a specific pipeline trace")
    p_reflect.add_argument("--reasoning", help="Why you chose this")
    p_reflect.add_argument("--feedback-target", choices=["choice", "reasoning", "confidence"],
                           help="Where the twin was off")

    # install-skills (Phase 4)
    p_skills = sub.add_parser("install-skills", help="Install Claude Code skills")
    p_skills.add_argument("--personal", action="store_true", help="Install to ~/.claude/skills/")
    p_skills.add_argument("--force", action="store_true", help="Overwrite existing skills")

    # mcp-serve (Phase 4)
    sub.add_parser("mcp-serve", help="Start MCP server (stdio transport)")

    # compare (A/B baseline)
    p_compare = sub.add_parser("compare", help="Run A/B baseline comparison", parents=[_twin_parent])
    p_compare.add_argument("--scenarios", default=None, help="Scenarios JSON path")
    p_compare.add_argument("--runners", default=None, help="Comma-separated runner IDs (vanilla,persona,rag_persona,twin)")
    p_compare.add_argument("--format", choices=["table", "json", "html"], default="table", dest="output_format")
    p_compare.add_argument("--output", default=None, help="Output file path")
    p_compare.add_argument("--open", action="store_true", help="Open HTML in browser")

    # drift-report (Phase 5c)
    p_drift = sub.add_parser("drift-report", help="Generate drift detection report")
    p_drift.add_argument("--output", help="Output file path")

    # ontology-report (Phase 5c)
    p_ontology = sub.add_parser("ontology-report", help="Generate shadow ontology report")
    p_ontology.add_argument("--output", help="Output file path")

    # bootstrap (Phase B)
    p_bootstrap = sub.add_parser("bootstrap", help="Interactive onboarding: build a usable twin in 15 minutes")
    p_bootstrap.add_argument("--questions", help="Custom questions JSON file")
    p_bootstrap.add_argument("--no-comparison", action="store_true", help="Skip mini A/B comparison")
    p_bootstrap.add_argument("--comparison-scenarios", type=int, default=5, help="Number of A/B scenarios")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    commands = {
        "init": cmd_init,
        "run": cmd_run,
        "scan": cmd_scan,
        "compile": cmd_compile,
        "evaluate": cmd_evaluate,
        "status": cmd_status,
        "sources": cmd_sources,
        "config": cmd_config,
        "dashboard": cmd_dashboard,
        "reflect": cmd_reflect,
        "install-skills": cmd_install_skills,
        "mcp-serve": cmd_mcp_serve,
        "compare": cmd_compare,
        "drift-report": cmd_drift_report,
        "ontology-report": cmd_ontology_report,
        "bootstrap": cmd_bootstrap,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()

"""Pipeline commands: cmd_run, cmd_scan, cmd_compile."""

from __future__ import annotations

import sys

from twin_runtime.cli._main import (
    _STORE_DIR,
    _apply_env,
    _build_registry,
    _load_config,
    _require_twin,
)
from twin_runtime.infrastructure.backends.json_file.twin_store import TwinStore


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

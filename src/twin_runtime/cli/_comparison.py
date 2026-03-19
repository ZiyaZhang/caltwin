"""Comparison command: cmd_compare + _print_comparison_table."""

from __future__ import annotations

from pathlib import Path

from twin_runtime.cli._main import (
    _STORE_DIR,
    _apply_env,
    _load_config,
    _require_twin,
)


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

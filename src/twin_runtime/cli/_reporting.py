"""Reporting commands: cmd_status, cmd_dashboard, cmd_ontology_report."""

from __future__ import annotations

from pathlib import Path

from twin_runtime.cli._main import (
    _STORE_DIR,
    _apply_env,
    _load_config,
    _require_twin,
)


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


def cmd_dashboard(args):
    """Generate HTML fidelity dashboard."""
    config = _load_config()
    user_id = config.get("user_id", "default")
    from twin_runtime.application.dashboard.cli import dashboard_command
    dashboard_command(store_dir=str(_STORE_DIR), user_id=user_id, output=args.output, open_browser=args.open)


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

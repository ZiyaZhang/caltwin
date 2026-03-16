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


def _load_config() -> dict:
    if _CONFIG_FILE.exists():
        return json.loads(_CONFIG_FILE.read_text())
    return {}


def _save_config(config: dict) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(config, indent=2))


def _get_twin(config: dict) -> TwinState:
    user_id = config.get("user_id", "default")
    store = TwinStore(str(_STORE_DIR))

    if store.has_current(user_id):
        return store.load(user_id)

    # Check for fixture
    fixture = config.get("fixture_path")
    if fixture and Path(fixture).exists():
        with open(fixture) as f:
            twin = TwinState(**json.load(f))
        store.save(twin)
        return twin

    print("No twin state found. Run 'twin-runtime init' first.")
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
                store.save(twin)
                print(f"Twin state initialized: {twin.state_version}")
            except Exception as e:
                print(f"Warning: could not load fixture: {e}")

    print("\nSetup complete! Try: twin-runtime status")


def cmd_run(args):
    """Run decision pipeline."""
    config = _load_config()
    _apply_env(config)

    from twin_runtime.application.pipeline.runner import run as run_pipeline

    twin = _get_twin(config)
    trace = run_pipeline(
        query=args.query,
        option_set=args.options,
        twin=twin,
    )

    if args.json:
        print(trace.model_dump_json(indent=2))
    else:
        print(f"\n{'='*60}")
        print(f"Decision: {trace.final_decision}")
        print(f"Mode: {trace.decision_mode.value} | Uncertainty: {trace.uncertainty:.2f}")
        print(f"Domains: {[d.value for d in trace.activated_domains]}")
        if trace.output_text:
            print(f"\n{trace.output_text}")
        print(f"{'='*60}")
        print(f"Trace: {trace.trace_id}")


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
    twin = _get_twin(config)

    compiler = PersonaCompiler(registry)
    updated, graph, fragments = compiler.compile(existing=twin)

    # Save updated state
    store = TwinStore(str(_STORE_DIR))
    store.save(updated)

    print(f"Compiled {len(fragments)} fragments")
    print(f"Twin state: {twin.state_version} → {updated.state_version}")
    print(f"Evidence graph: {len(graph.edges)} edges")
    print(f"Evidence count: {twin.shared_decision_core.evidence_count} → {updated.shared_decision_core.evidence_count}")


def cmd_evaluate(args):
    """Run batch evaluation."""
    config = _load_config()
    _apply_env(config)

    from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore

    twin = _get_twin(config)
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
    print(f"\nChoice similarity: {evaluation.choice_similarity:.3f}")
    print(f"Domain reliability: {evaluation.domain_reliability}")
    print(f"Evaluation ID: {evaluation.evaluation_id}")


def cmd_status(args):
    """Show twin state summary."""
    config = _load_config()
    twin = _get_twin(config)

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


def main():
    parser = argparse.ArgumentParser(
        prog="twin-runtime",
        description="Calibrated judgment twin runtime",
    )
    sub = parser.add_subparsers(dest="command")

    # init
    sub.add_parser("init", help="Interactive setup")

    # run
    p_run = sub.add_parser("run", help="Run decision pipeline")
    p_run.add_argument("query", help="Decision query")
    p_run.add_argument("-o", "--options", nargs="+", required=True, help="Options to evaluate")
    p_run.add_argument("--json", action="store_true", help="Output as JSON")

    # scan
    p_scan = sub.add_parser("scan", help="Scan sources for evidence")
    p_scan.add_argument("-v", "--verbose", action="store_true")

    # compile
    sub.add_parser("compile", help="Compile evidence into TwinState")

    # evaluate
    sub.add_parser("evaluate", help="Run batch evaluation")

    # status
    p_status = sub.add_parser("status", help="Show twin state")
    p_status.add_argument("--json", action="store_true", help="Full JSON output")

    # sources
    sub.add_parser("sources", help="List configured sources")

    # config
    p_config = sub.add_parser("config", help="Get/set configuration")
    p_config.add_argument("action", choices=["set", "get", "list"])
    p_config.add_argument("key", nargs="?")
    p_config.add_argument("value", nargs="?")

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
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()

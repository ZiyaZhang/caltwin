"""CLI entry point: argparse setup, dispatch, and shared helpers.

All shared state (_CONFIG_DIR, _STORE_DIR, etc.) and helper functions
(_load_config, _save_config, _get_twin, etc.) live here so other
submodules can import them.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure src is on path when running directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from twin_runtime.domain.models.primitives import OutcomeSource
from twin_runtime.domain.models.twin_state import TwinState
from twin_runtime.infrastructure.backends.json_file.twin_store import TwinStore

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_CONFIG_DIR = Path.home() / ".twin-runtime"
_CONFIG_FILE = _CONFIG_DIR / "config.json"
_STORE_DIR = _CONFIG_DIR / "store"

_twin_parent = argparse.ArgumentParser(add_help=False)
_twin_parent.add_argument("--demo", action="store_true",
    help="Use bundled sample twin (no data persisted)")

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# main() — argparse + dispatch
# ---------------------------------------------------------------------------

def main():
    from twin_runtime.cli._setup import cmd_init, cmd_config, cmd_sources
    from twin_runtime.cli._pipeline import cmd_run, cmd_scan, cmd_compile
    from twin_runtime.cli._calibration import cmd_evaluate, cmd_reflect, cmd_drift_report
    from twin_runtime.cli._reporting import cmd_status, cmd_dashboard, cmd_ontology_report
    from twin_runtime.cli._onboarding import cmd_bootstrap
    from twin_runtime.cli._comparison import cmd_compare
    from twin_runtime.cli._skills import cmd_install_skills, cmd_mcp_serve
    from twin_runtime.cli._implicit import cmd_heartbeat, cmd_confirm, cmd_mine_patterns

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
    p_reflect.add_argument("--source", default="user_correction",
        choices=[s.value for s in OutcomeSource],
        help="How the outcome was observed")
    p_reflect.add_argument("--confidence", type=float, default=0.8,
        help="Confidence in this reflection (display only, not passed to record_outcome)")

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

    # heartbeat + confirm + mine-patterns (Phase D)
    sub.add_parser("heartbeat", help="Run implicit reflection from local signals")
    p_confirm = sub.add_parser("confirm", help="Confirm pending implicit reflections")
    p_confirm.add_argument("--list", action="store_true", dest="list_only")
    p_confirm.add_argument("--accept-all", action="store_true")
    p_mine = sub.add_parser("mine-patterns", help="Analyze systematic failure patterns")
    p_mine.add_argument("--min-failures", type=int, default=3)
    p_mine.add_argument("--lookback", type=int, default=50)

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
        "heartbeat": cmd_heartbeat,
        "confirm": cmd_confirm,
        "mine-patterns": cmd_mine_patterns,
        "bootstrap": cmd_bootstrap,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()

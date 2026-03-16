"""Interfaces layer – CLI entry point.

Re-exports from twin_runtime.cli so the pyproject.toml entry point
lives logically in the interfaces/ layer.
"""
from pathlib import Path

from twin_runtime.cli import *  # noqa: F401,F403
from twin_runtime.cli import main  # noqa: F401 – explicit for entry point
from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore  # noqa: F401 – used in dashboard_command; also needed for mock patching

# Constants for dashboard CLI
_STORE_DIR = str(Path(__file__).parent.parent.parent.parent / "data" / "store")
_USER_ID = "user-ziya"
_FIXTURE = str(Path(__file__).parent.parent.parent.parent / "tests" / "fixtures" / "sample_twin_state.json")


def dashboard_command(output: str = "fidelity_report.html", open_browser: bool = False):
    """Generate HTML fidelity dashboard."""
    import json
    from twin_runtime.domain.models.twin_state import TwinState
    from twin_runtime.application.dashboard.payload import DashboardPayload
    from twin_runtime.application.dashboard.generator import generate_dashboard

    store = CalibrationStore(_STORE_DIR, _USER_ID)

    scores = store.list_fidelity_scores(limit=10)
    if not scores:
        print("No fidelity scores. Run: python tools/batch_evaluate.py")
        return

    latest_score = scores[0]
    # Find associated evaluation — try evaluation_ids first, fall back to latest
    eval_ids = latest_score.evaluation_ids or []
    evals = store.list_evaluations()
    if eval_ids:
        evaluation = next((e for e in evals if e.evaluation_id == eval_ids[-1]), None)
    else:
        evaluation = evals[-1] if evals else None
    if not evaluation:
        print("No evaluation found. Run: python tools/batch_evaluate.py")
        return

    # Try to load twin matching the score's version from TwinStore,
    # fall back to fixture if not available
    twin = None
    try:
        from twin_runtime.infrastructure.backends.json_file.twin_state_store import TwinStateStore
        twin_store = TwinStateStore(_STORE_DIR, _USER_ID)
        twin = twin_store.load(latest_score.twin_state_version)
    except Exception:
        pass
    if twin is None:
        with open(_FIXTURE) as f:
            twin = TwinState(**json.load(f))

    biases = store.list_detected_biases()
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

"""Dashboard CLI command — lives here to avoid circular imports with interfaces/cli.py."""
from pathlib import Path


# Constants — resolve relative to project structure
_STORE_DIR = str(Path(__file__).parent.parent.parent.parent.parent / "data" / "store")
_USER_ID = "user-ziya"
_FIXTURE = str(Path(__file__).parent.parent.parent.parent.parent / "tests" / "fixtures" / "sample_twin_state.json")


def dashboard_command(output: str = "fidelity_report.html", open_browser: bool = False):
    """Generate HTML fidelity dashboard."""
    import json
    from twin_runtime.domain.models.twin_state import TwinState
    from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore
    from twin_runtime.application.dashboard.payload import DashboardPayload
    from twin_runtime.application.dashboard.generator import generate_dashboard

    store = CalibrationStore(_STORE_DIR, _USER_ID)

    scores = store.list_fidelity_scores(limit=10)
    if not scores:
        print("No fidelity scores. Run: python tools/batch_evaluate.py")
        return

    latest_score = scores[0]
    eval_ids = latest_score.evaluation_ids or []
    evals = store.list_evaluations()
    if eval_ids:
        evaluation = next((e for e in evals if e.evaluation_id == eval_ids[-1]), None)
    else:
        evaluation = evals[-1] if evals else None
    if not evaluation:
        print("No evaluation found. Run: python tools/batch_evaluate.py")
        return

    twin = None
    try:
        from twin_runtime.infrastructure.backends.json_file.twin_store import TwinStore
        twin_store = TwinStore(_STORE_DIR)
        twin = twin_store.load(_USER_ID, latest_score.twin_state_version)
    except (FileNotFoundError, KeyError):
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

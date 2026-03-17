"""Dashboard CLI command — lives here to avoid circular imports with interfaces/cli.py."""


def dashboard_command(
    *,
    store_dir: str,
    user_id: str,
    output: str = "fidelity_report.html",
    open_browser: bool = False,
) -> None:
    """Generate HTML fidelity dashboard from real user data."""
    from pathlib import Path
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

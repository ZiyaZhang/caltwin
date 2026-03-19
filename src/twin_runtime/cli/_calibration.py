"""Calibration commands: cmd_evaluate, cmd_reflect, cmd_drift_report."""

from __future__ import annotations

import sys
from pathlib import Path

from twin_runtime.cli._main import (
    _STORE_DIR,
    TwinNotFoundError,
    _apply_env,
    _get_twin,
    _load_config,
    _require_twin,
)


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
            source = OutcomeSource(args.source)
            outcome, update = record_outcome(
                trace_id=args.trace_id,
                actual_choice=args.choice,
                source=source,
                actual_reasoning=args.reasoning,
                twin=twin,
                trace_store=trace_store,
                calibration_store=cal_store,
            )
            print(f"Outcome recorded: {outcome.outcome_id}")
            print(f"  Choice: {outcome.actual_choice}")
            print(f"  Source: {source.value}")
            print(f"  Confidence: {args.confidence:.2f}")
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
                    from twin_runtime.application.calibration.experience_updater import ExperienceUpdater
                    updater = ExperienceUpdater()
                    result = updater.update(ref_result.new_entry, exp_lib)
                    exp_store.save(exp_lib)
                    print(f"  Experience: [{result.action.value}] {result.reason}")
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

            # Phase D: file counter + pattern mining trigger
            count = _increment_reflect_counter(user_id)
            if count >= 20:
                try:
                    from twin_runtime.application.calibration.hard_case_miner import HardCaseMiner
                    from twin_runtime.interfaces.defaults import DefaultLLM

                    mine_trace_ids = trace_store.list_traces(limit=50)
                    mine_traces = [trace_store.load_trace(tid) for tid in mine_trace_ids]
                    mine_outcomes = cal_store.list_outcomes()
                    miner = HardCaseMiner(DefaultLLM())
                    patterns = miner.mine(mine_traces, mine_outcomes)
                    for p in patterns:
                        exp_lib.add_pattern(p)
                    if patterns:
                        exp_store.save(exp_lib)
                        print(f"  Pattern mining: found {len(patterns)} patterns")
                    _reset_reflect_counter(user_id)
                except Exception as mine_err:
                    print(f"  Pattern mining skipped: {mine_err}", file=sys.stderr)

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


# ---------------------------------------------------------------------------
# Phase D: reflect counter for pattern mining trigger
# ---------------------------------------------------------------------------

def _increment_reflect_counter(user_id: str) -> int:
    """Increment the reflect counter and return the new value."""
    counter_path = _STORE_DIR / user_id / "reflect_count"
    counter_path.parent.mkdir(parents=True, exist_ok=True)
    count = int(counter_path.read_text()) if counter_path.exists() else 0
    count += 1
    counter_path.write_text(str(count))
    return count


def _reset_reflect_counter(user_id: str) -> None:
    """Reset the reflect counter to 0."""
    counter_path = _STORE_DIR / user_id / "reflect_count"
    counter_path.parent.mkdir(parents=True, exist_ok=True)
    counter_path.write_text("0")

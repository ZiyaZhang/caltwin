"""CLI commands for implicit reflection: heartbeat, confirm, mine-patterns."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from twin_runtime.cli._main import (
    _STORE_DIR,
    _apply_env,
    _load_config,
    _require_twin,
)


def cmd_heartbeat(args):
    """Run implicit reflection from local signals."""
    config = _load_config()
    _apply_env(config)
    user_id = config.get("user_id", "default")

    from twin_runtime.infrastructure.backends.json_file.trace_store import JsonFileTraceStore
    from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore
    from twin_runtime.infrastructure.backends.json_file.twin_store import TwinStore
    from twin_runtime.infrastructure.backends.json_file.experience_store import ExperienceLibraryStore
    from twin_runtime.interfaces.defaults import DefaultLLM
    from twin_runtime.application.implicit.heartbeat import HeartbeatReflector

    trace_store = JsonFileTraceStore(str(_STORE_DIR / user_id / "traces"))
    cal_store = CalibrationStore(str(_STORE_DIR), user_id)
    twin_store = TwinStore(str(_STORE_DIR))
    exp_store = ExperienceLibraryStore(str(_STORE_DIR), user_id)
    llm = DefaultLLM()

    # Pending queue path
    queue_path = str(_STORE_DIR / user_id / "pending_reflections.json")

    # Optional adapters
    calendar_adapter = gmail_adapter = None
    if config.get("google_credentials"):
        try:
            from twin_runtime.infrastructure.sources.calendar_adapter import CalendarAdapter
            from twin_runtime.infrastructure.sources.gmail_adapter import GmailAdapter
            calendar_adapter = CalendarAdapter(credentials_path=config["google_credentials"])
            gmail_adapter = GmailAdapter(credentials_path=config["google_credentials"])
        except ImportError:
            pass

    reflector = HeartbeatReflector(
        trace_store=trace_store,
        calibration_store=cal_store,
        twin_store=twin_store,
        experience_store=exp_store,
        llm=llm,
        user_id=user_id,
        pending_queue_path=queue_path,
        calendar_adapter=calendar_adapter,
        gmail_adapter=gmail_adapter,
    )
    report = reflector.run()
    print(
        f"Heartbeat: {report.inferred} inferred, "
        f"{report.auto_reflected} auto-reflected, "
        f"{report.queued} queued"
    )
    if report.errors:
        print(f"  Errors: {report.errors}", file=sys.stderr)


def cmd_confirm(args):
    """Confirm or reject pending implicit reflections."""
    config = _load_config()
    _apply_env(config)
    user_id = config.get("user_id", "default")

    queue_path = _STORE_DIR / user_id / "pending_reflections.json"

    if not queue_path.exists():
        print("No pending reflections.")
        return

    try:
        pending = json.loads(queue_path.read_text())
    except (json.JSONDecodeError, OSError):
        print("No pending reflections (empty or corrupt queue).")
        return

    if not pending:
        print("No pending reflections.")
        return

    list_only = getattr(args, "list_only", False)
    accept_all = getattr(args, "accept_all", False)

    if list_only:
        print(f"{len(pending)} pending reflection(s):")
        for i, item in enumerate(pending, 1):
            print(f"  {i}. [{item['signal_source']}] trace={item['trace_id']} "
                  f"choice={item['inferred_choice']} conf={item['confidence']:.2f}")
        return

    if accept_all:
        from twin_runtime.infrastructure.backends.json_file.trace_store import JsonFileTraceStore
        from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore
        from twin_runtime.infrastructure.backends.json_file.twin_store import TwinStore
        from twin_runtime.infrastructure.backends.json_file.experience_store import ExperienceLibraryStore
        from twin_runtime.interfaces.defaults import DefaultLLM
        from twin_runtime.application.calibration.outcome_tracker import record_outcome
        from twin_runtime.application.calibration.reflection_generator import ReflectionGenerator
        from twin_runtime.application.calibration.experience_updater import ExperienceUpdater
        from twin_runtime.domain.models.primitives import OutcomeSource

        trace_store = JsonFileTraceStore(str(_STORE_DIR / user_id / "traces"))
        cal_store = CalibrationStore(str(_STORE_DIR), user_id)
        twin_store = TwinStore(str(_STORE_DIR))
        exp_store = ExperienceLibraryStore(str(_STORE_DIR), user_id)

        try:
            twin = twin_store.load_state(user_id)
        except Exception:
            print("Twin not initialized. Cannot accept reflections.")
            return

        llm = DefaultLLM()
        accepted = 0
        for item in pending:
            try:
                outcome, _ = record_outcome(
                    trace_id=item["trace_id"],
                    actual_choice=item["inferred_choice"],
                    source=OutcomeSource(item["signal_source"]),
                    twin=twin,
                    trace_store=trace_store,
                    calibration_store=cal_store,
                )

                # Full reflection pipeline (same as _auto_reflect)
                exp_lib = exp_store.load()
                trace = trace_store.load_trace(item["trace_id"])
                reflection = ReflectionGenerator(llm=llm).process(
                    trace, item["inferred_choice"], exp_lib,
                )
                if reflection.new_entry:
                    ExperienceUpdater().update(reflection.new_entry, exp_lib)
                    exp_store.save(exp_lib)
                elif reflection.action == "confirmed":
                    exp_store.save(exp_lib)

                accepted += 1
            except Exception as e:
                print(f"  Failed: {item['trace_id']}: {e}", file=sys.stderr)

        # Clear queue
        queue_path.write_text("[]")
        print(f"Accepted {accepted}/{len(pending)} reflections (with experience updates). Queue cleared.")
        return

    # Interactive mode — accepted items are immediately reflected
    from twin_runtime.infrastructure.backends.json_file.trace_store import JsonFileTraceStore
    from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore
    from twin_runtime.infrastructure.backends.json_file.twin_store import TwinStore
    from twin_runtime.infrastructure.backends.json_file.experience_store import ExperienceLibraryStore
    from twin_runtime.interfaces.defaults import DefaultLLM
    from twin_runtime.application.calibration.outcome_tracker import record_outcome
    from twin_runtime.application.calibration.reflection_generator import ReflectionGenerator
    from twin_runtime.application.calibration.experience_updater import ExperienceUpdater
    from twin_runtime.domain.models.primitives import OutcomeSource

    trace_store = JsonFileTraceStore(str(_STORE_DIR / user_id / "traces"))
    cal_store = CalibrationStore(str(_STORE_DIR), user_id)
    twin_store = TwinStore(str(_STORE_DIR))
    exp_store = ExperienceLibraryStore(str(_STORE_DIR), user_id)

    try:
        twin = twin_store.load_state(user_id)
    except Exception:
        print("Twin not initialized. Cannot accept reflections.")
        return

    llm = DefaultLLM()

    print(f"{len(pending)} pending reflection(s). Accept each? (y/n/q)")
    remaining = []
    accepted = 0
    for idx, item in enumerate(pending):
        print(f"  [{item['signal_source']}] trace={item['trace_id']} "
              f"choice={item['inferred_choice']} conf={item['confidence']:.2f}")
        try:
            answer = input("  Accept? (y/n/q): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            remaining.extend(pending[idx:])
            break
        if answer == "q":
            remaining.extend(pending[idx:])
            break
        elif answer == "y":
            try:
                record_outcome(
                    trace_id=item["trace_id"],
                    actual_choice=item["inferred_choice"],
                    source=OutcomeSource(item["signal_source"]),
                    twin=twin,
                    trace_store=trace_store,
                    calibration_store=cal_store,
                )
                # Reflection + experience update
                exp_lib = exp_store.load()
                trace = trace_store.load_trace(item["trace_id"])
                reflection = ReflectionGenerator(llm=llm).process(
                    trace, item["inferred_choice"], exp_lib,
                )
                if reflection.new_entry:
                    ExperienceUpdater().update(reflection.new_entry, exp_lib)
                    exp_store.save(exp_lib)
                elif reflection.action == "confirmed":
                    exp_store.save(exp_lib)
                accepted += 1
                print(f"  -> Accepted and reflected")
            except Exception as e:
                print(f"  -> Accept failed: {e}", file=sys.stderr)
                remaining.append(item)
        else:
            remaining.append(item)
            print(f"  -> Skipped")

    # Save remaining
    queue_path.write_text(json.dumps(remaining, indent=2, default=str))
    print(f"Done. {accepted} accepted, {len(remaining)} still pending.")


def cmd_mine_patterns(args):
    """Analyze systematic failure patterns."""
    config = _load_config()
    _apply_env(config)
    user_id = config.get("user_id", "default")

    from twin_runtime.infrastructure.backends.json_file.trace_store import JsonFileTraceStore
    from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore
    from twin_runtime.infrastructure.backends.json_file.experience_store import ExperienceLibraryStore
    from twin_runtime.interfaces.defaults import DefaultLLM
    from twin_runtime.application.calibration.hard_case_miner import HardCaseMiner

    trace_store = JsonFileTraceStore(str(_STORE_DIR / user_id / "traces"))
    cal_store = CalibrationStore(str(_STORE_DIR), user_id)
    exp_store = ExperienceLibraryStore(str(_STORE_DIR), user_id)
    llm = DefaultLLM()

    min_failures = getattr(args, "min_failures", 3)
    lookback = getattr(args, "lookback", 50)

    trace_ids = trace_store.list_traces(limit=lookback)
    traces = []
    for tid in trace_ids:
        try:
            traces.append(trace_store.load_trace(tid))
        except Exception:
            continue

    outcomes = cal_store.list_outcomes()

    miner = HardCaseMiner(llm, min_failures=min_failures)
    patterns = miner.mine(traces, outcomes)

    if patterns:
        exp_lib = exp_store.load()
        for p in patterns:
            exp_lib.add_pattern(p)
        exp_store.save(exp_lib)
        print(f"Pattern mining: found {len(patterns)} patterns")
        for p in patterns:
            print(f"  [{', '.join(d.value for d in p.domains)}] {p.pattern_description[:80]}")
    else:
        print("No patterns found (need more failure data).")

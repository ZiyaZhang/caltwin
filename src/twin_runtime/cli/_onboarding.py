"""Onboarding command: cmd_bootstrap + _run_bootstrap_comparison."""

from __future__ import annotations

import sys

from twin_runtime.cli._main import (
    _STORE_DIR,
    _apply_env,
    _load_config,
    _save_config,
)
from twin_runtime.infrastructure.backends.json_file.twin_store import TwinStore


def cmd_bootstrap(args):
    """Interactive bootstrap: build a usable twin in 15 minutes."""
    config = _load_config()
    _apply_env(config)

    from twin_runtime.application.bootstrap.questions import (
        DEFAULT_QUESTIONS,
        QuestionType,
        BootstrapAnswer,
    )
    from twin_runtime.application.bootstrap.engine import BootstrapEngine, validate_bootstrap_questions
    from twin_runtime.infrastructure.backends.json_file.experience_store import (
        ExperienceLibraryStore,
    )
    from twin_runtime.interfaces.defaults import DefaultLLM

    user_id = config.get("user_id", "user-default")
    questions = DEFAULT_QUESTIONS
    # Load custom questions if provided
    if getattr(args, "questions", None):
        import json as _json
        from twin_runtime.application.bootstrap.questions import BootstrapQuestion
        try:
            with open(args.questions) as f:
                raw = _json.load(f)
            if not isinstance(raw, list):
                print(f"Error: questions file must contain a JSON array, got {type(raw).__name__}")
                sys.exit(1)
            questions = [BootstrapQuestion(**q) for q in raw]
        except FileNotFoundError:
            print(f"Error: questions file not found: {args.questions}")
            sys.exit(1)
        except _json.JSONDecodeError as e:
            print(f"Error: invalid JSON in questions file: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"Error: could not load questions file: {e}")
            sys.exit(1)

    # Validate question set before starting interactive session (fail-early)
    try:
        validate_bootstrap_questions(questions)
    except ValueError as e:
        print(f"Error: invalid question set — {e}")
        sys.exit(1)

    # Pre-flight LLM check before starting interactive session
    try:
        llm = DefaultLLM()
        llm.ask_text("ping", "respond with 'ok'", max_tokens=8)
        print("LLM connection verified.\n")
    except Exception as e:
        print(f"Error: LLM connection failed — {e}")
        print("Check your API key (twin-runtime config get api_key) and network.")
        sys.exit(1)

    # Present questions interactively
    answers = []
    phases = sorted(set(q.phase for q in questions))
    phase_names = {1: "Decision Style", 2: "Domain Expertise", 3: "Past Decisions"}

    for phase in phases:
        phase_qs = [q for q in questions if q.phase == phase]
        print(f"\n{'='*60}")
        print(f"  Phase {phase}: {phase_names.get(phase, 'Questions')} ({len(phase_qs)} questions)")
        print(f"{'='*60}\n")

        for q in phase_qs:
            print(f"  {q.question}")
            if q.type == QuestionType.FORCED_CHOICE and q.options:
                for i, opt in enumerate(q.options):
                    print(f"    [{i}] {opt}")
                while True:
                    raw = input("  Your choice (number): ").strip()
                    try:
                        idx = int(raw)
                        if 0 <= idx < len(q.options):
                            answers.append(BootstrapAnswer(
                                question_id=q.id, type=q.type,
                                chosen_option=idx, domain=q.domain, tags=q.tags,
                            ))
                            break
                    except ValueError:
                        pass
                    print(f"  Please enter a number 0-{len(q.options)-1}")

            elif q.type == QuestionType.OPEN_SCENARIO:
                text = input("  Your answer: ").strip()
                answers.append(BootstrapAnswer(
                    question_id=q.id, type=q.type,
                    free_text=text, domain=q.domain, tags=q.tags,
                ))

            print()

    # Run engine (llm already created and verified above)
    print("\nProcessing your answers...")
    engine = BootstrapEngine(llm=llm, questions=questions)
    result = engine.run(answers, user_id=user_id)

    # Save
    store = TwinStore(str(_STORE_DIR))
    store.save_state(result.twin)

    exp_store = ExperienceLibraryStore(str(_STORE_DIR), user_id)
    exp_store.save(result.experience_library)

    # Summary
    print(f"\n{'='*60}")
    print(f"  Bootstrap Complete!")
    print(f"{'='*60}")
    print(f"  Twin version: {result.twin.state_version}")
    print(f"  Valid domains: {[d.value for d in result.twin.valid_domains()]}")
    print(f"  Experience entries: {result.experience_library.size}")
    print(f"  Axis reliability: {result.axis_reliability}")
    print(f"\n  Try: twin-runtime run \"<your question>\" -o \"Option A\" \"Option B\"")

    # Optional mini A/B comparison
    if not getattr(args, "no_comparison", False):
        try:
            _run_bootstrap_comparison(result.twin, args)
        except Exception as e:
            print(f"\n  Mini A/B skipped: {e}")


def _run_bootstrap_comparison(twin, args):
    """Run mini A/B comparison after bootstrap using the orchestrator."""
    from twin_runtime.application.orchestrator.runtime_orchestrator import run as orchestrator_run
    from twin_runtime.interfaces.defaults import DefaultLLM

    n = getattr(args, "comparison_scenarios", 5)
    print(f"\n  Running mini A/B with {n} scenarios...")
    print("  (Use --no-comparison to skip this step)\n")

    # Comparison scenarios — matches onboarding language (Chinese)
    scenarios = [
        ("新工作给了offer，要不要谈薪资？", ["积极谈判争取更高", "直接接受现有条件"]),
        ("同事的项目方案有明显问题，我该怎么办？", ["直接指出问题", "先观望再说"]),
        ("手上有一笔存款，投资风格怎么选？", ["稳健型基金", "高成长型股票"]),
        ("远程工作和坐班工作怎么选？", ["选远程工作", "留在坐班岗位"]),
        ("朋友找我借一大笔钱，怎么处理？", ["借给他", "委婉拒绝"]),
        ("要不要在社交媒体上发表有争议的观点？", ["发出去", "留着不发"]),
        ("要不要换行业追求热爱的方向？", ["立刻转行", "留在原行业慢慢规划"]),
    ][:n]

    llm = DefaultLLM()
    results = []
    for query, options in scenarios:
        try:
            trace = orchestrator_run(query=query, option_set=options, twin=twin, llm=llm)
            mode = trace.decision_mode.value
            unc = trace.uncertainty
            decision = trace.final_decision[:60]
            results.append((query[:40], decision, mode, unc))
            print(f"  [{mode:8s} u={unc:.2f}] {query[:45]}")
            print(f"    → {decision}")
        except Exception as e:
            results.append((query[:40], f"ERROR: {e}", "error", 1.0))
            print(f"  [ERROR] {query[:45]}: {e}")

    # Summary
    direct = sum(1 for _, _, m, _ in results if m == "direct")
    avg_unc = sum(u for _, _, _, u in results) / len(results) if results else 1.0
    print(f"\n  Summary: {direct}/{len(results)} direct answers, avg uncertainty {avg_unc:.2f}")

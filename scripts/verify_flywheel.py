#!/usr/bin/env python3
"""Flywheel effect verification — manual run, not CI.

~60-80 LLM calls (Sonnet ~$0.3-0.5).

Usage: python scripts/verify_flywheel.py [--rounds 3] [--scenarios 10]
"""

from __future__ import annotations

import argparse
import sys
import os

# Add project src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import datetime, timezone

from twin_runtime.domain.models.primitives import OutcomeSource


SCENARIOS = [
    {"query": "用 Redis 还是 Memcached 做缓存？", "options": ["Redis", "Memcached"], "ground_truth": "Redis"},
    {"query": "新项目用 monorepo 还是 multirepo？", "options": ["monorepo", "multirepo"], "ground_truth": "monorepo"},
    {"query": "团队沟通用异步文档还是同步会议？", "options": ["异步文档", "同步会议"], "ground_truth": "异步文档"},
    {"query": "技术债要不要现在还？", "options": ["现在还", "先做需求"], "ground_truth": "现在还"},
    {"query": "新人 onboarding 让他直接上手还是先培训？", "options": ["直接上手", "先培训"], "ground_truth": "直接上手"},
    {"query": "要不要引入新框架替换现有的？", "options": ["引入新框架", "继续用现有的"], "ground_truth": "继续用现有的"},
    {"query": "CI 失败要不要 block merge？", "options": ["严格 block", "允许 override"], "ground_truth": "严格 block"},
    {"query": "API 版本策略用 URL path 还是 header？", "options": ["URL path", "header"], "ground_truth": "URL path"},
    {"query": "数据库选 PostgreSQL 还是 MySQL？", "options": ["PostgreSQL", "MySQL"], "ground_truth": "PostgreSQL"},
    {"query": "部署策略用蓝绿还是滚动？", "options": ["蓝绿部署", "滚动部署"], "ground_truth": "蓝绿部署"},
]


def _extract_top_choice(trace) -> str:
    """Extract the top-ranked option from a trace."""
    if trace.head_assessments:
        best = max(trace.head_assessments, key=lambda h: h.confidence)
        if best.option_ranking:
            return best.option_ranking[0]
    return ""


def run_round(twin, scenarios, round_idx, *, llm, evidence_store):
    """Run all scenarios, return CF score and traces."""
    from twin_runtime.application.orchestrator.runtime_orchestrator import run as orchestrator_run

    correct = 0
    traces = []
    for s in scenarios:
        try:
            trace = orchestrator_run(
                query=s["query"], option_set=s["options"], twin=twin,
                llm=llm, evidence_store=evidence_store,
            )
            traces.append((trace, s))
            top = _extract_top_choice(trace)
            if top.lower().strip() == s["ground_truth"].lower().strip():
                correct += 1
                print(f"    [HIT] {s['query'][:30]}... → {top}")
            else:
                print(f"    [MISS] {s['query'][:30]}... → {top} (expected: {s['ground_truth']})")
        except Exception as e:
            print(f"    [ERR] {s['query'][:30]}...: {e}")
            traces.append((None, s))

    cf = correct / len(scenarios) if scenarios else 0
    print(f"  Round {round_idx}: CF = {cf:.0%} ({correct}/{len(scenarios)})")
    return cf, traces


def reflect_round(traces_with_scenarios, twin, *, trace_store, calibration_store, experience_store, llm):
    """Reflect all outcomes from previous round."""
    from twin_runtime.application.calibration.outcome_tracker import record_outcome
    from twin_runtime.application.calibration.reflection_generator import ReflectionGenerator
    from twin_runtime.application.calibration.experience_updater import ExperienceUpdater

    exp_lib = experience_store.load()
    reflected = 0

    for trace, scenario in traces_with_scenarios:
        if trace is None:
            continue
        try:
            # Save trace first
            trace_store.save_trace(trace)

            outcome, _ = record_outcome(
                trace_id=trace.trace_id,
                actual_choice=scenario["ground_truth"],
                source=OutcomeSource.USER_CORRECTION,
                twin=twin,
                trace_store=trace_store,
                calibration_store=calibration_store,
            )

            # Generate reflection
            rg = ReflectionGenerator(llm=llm)
            ref_result = rg.process(trace, scenario["ground_truth"], exp_lib)
            if ref_result.new_entry:
                ExperienceUpdater().update(ref_result.new_entry, exp_lib)
            reflected += 1
        except Exception as e:
            print(f"    [REFLECT ERR] {scenario['query'][:30]}...: {e}")

    experience_store.save(exp_lib)
    print(f"  Reflected {reflected}/{len(traces_with_scenarios)} outcomes. Experience library: {exp_lib.size} entries.")


def main():
    parser = argparse.ArgumentParser(description="Verify flywheel effect")
    parser.add_argument("--rounds", type=int, default=3, help="Number of rounds")
    parser.add_argument("--scenarios", type=int, default=10, help="Number of scenarios")
    args = parser.parse_args()

    n_rounds = args.rounds
    scenarios = SCENARIOS[:args.scenarios]

    print(f"Flywheel verification: {n_rounds} rounds x {len(scenarios)} scenarios")
    print(f"Estimated LLM calls: ~{n_rounds * len(scenarios) * 3}-{n_rounds * len(scenarios) * 4}")
    print()

    # Setup
    import tempfile
    from twin_runtime.domain.models.twin_state import TwinState
    from twin_runtime.infrastructure.backends.json_file.twin_store import TwinStore
    from twin_runtime.infrastructure.backends.json_file.trace_store import JsonFileTraceStore
    from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore
    from twin_runtime.infrastructure.backends.json_file.experience_store import ExperienceLibraryStore
    from twin_runtime.infrastructure.backends.json_file.evidence_store import JsonFileEvidenceStore
    from twin_runtime.interfaces.defaults import DefaultLLM
    import importlib.resources as pkg_resources

    tmpdir = tempfile.mkdtemp(prefix="flywheel_")
    print(f"Working directory: {tmpdir}")

    # Bootstrap with sample twin
    ref = pkg_resources.files("twin_runtime") / "resources" / "fixtures" / "sample_twin_state.json"
    twin = TwinState.model_validate_json(ref.read_text())
    user_id = twin.user_id

    twin_store = TwinStore(tmpdir)
    twin_store.save_state(twin)
    trace_store = JsonFileTraceStore(f"{tmpdir}/{user_id}/traces")
    cal_store = CalibrationStore(tmpdir, user_id)
    exp_store = ExperienceLibraryStore(tmpdir, user_id)
    evidence_store = JsonFileEvidenceStore(tmpdir, user_id)
    llm = DefaultLLM()

    # Run rounds
    cf_scores = []
    for round_idx in range(n_rounds):
        print(f"\n--- Round {round_idx} ---")
        cf, traces = run_round(twin, scenarios, round_idx, llm=llm, evidence_store=evidence_store)
        cf_scores.append(cf)

        if round_idx < n_rounds - 1:
            print(f"  Reflecting...")
            reflect_round(
                traces, twin,
                trace_store=trace_store,
                calibration_store=cal_store,
                experience_store=exp_store,
                llm=llm,
            )

    # Verdict
    print("\n" + "=" * 50)
    print("FLYWHEEL RESULTS")
    print("=" * 50)
    for i, cf in enumerate(cf_scores):
        print(f"  Round {i}: CF = {cf:.0%}")

    cf_0, cf_last = cf_scores[0], cf_scores[-1]
    if cf_last > cf_0:
        print(f"\nPASS: Flywheel is turning. CF improved {cf_0:.0%} -> {cf_last:.0%}")
        return 0
    elif cf_last == cf_0:
        print(f"\nWARN: CF stagnant at {cf_0:.0%}. Check search/retrieval.")
        return 0
    else:
        print(f"\nFAIL: CF regressed {cf_0:.0%} -> {cf_last:.0%}. Check ExperienceUpdater.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

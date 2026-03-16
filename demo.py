#!/usr/bin/env python3
"""End-to-end demo: load sample twin → run decision pipeline → print trace."""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from twin_runtime.domain.models.twin_state import TwinState
from twin_runtime.application.pipeline.runner import run


def main():
    # 1. Load the sample twin
    fixture = os.path.join(os.path.dirname(__file__), "tests", "fixtures", "sample_twin_state.json")
    with open(fixture) as f:
        twin = TwinState(**json.load(f))
    print(f"[1] Loaded twin: version={twin.state_version}, "
          f"domains={[h.domain.value for h in twin.domain_heads]}")
    print(f"    Reliability: {', '.join(f'{h.domain.value}={h.head_reliability:.2f}' for h in twin.domain_heads)}")
    print()

    # 2. Define a decision scenario
    query = "我在考虑要不要离开现在的大厂，去一个早期AI创业公司。薪资会降30%但有期权，技术方向更有意思。怎么看？"
    options = [
        "留在大厂：稳定薪资，成熟体系，但技术天花板",
        "跳槽AI创业：降薪+期权，技术自由度高，风险大",
    ]
    print(f"[2] Query: {query}")
    print(f"    Options: {options}")
    print()

    # 3. Run the pipeline
    print("[3] Running pipeline...")
    print("    Stage 1: Situation Interpreter (LLM call)...")
    trace = run(query, options, twin)

    # 4. Print results
    print()
    print("=" * 60)
    print("DECISION TRACE")
    print("=" * 60)
    print(f"  Trace ID:       {trace.trace_id[:12]}...")
    print(f"  Decision Mode:  {trace.decision_mode.value}")
    print(f"  Uncertainty:    {trace.uncertainty:.2f}")
    print(f"  Active Domains: {[d.value for d in trace.activated_domains]}")
    print()

    print("  HEAD ASSESSMENTS:")
    for a in trace.head_assessments:
        print(f"    [{a.domain.value}] confidence={a.confidence:.2f}")
        print(f"      Ranking: {a.option_ranking}")
        top_axes = sorted(
            ((k, v) for k, v in a.utility_decomposition.items() if isinstance(v, (int, float))),
            key=lambda x: -x[1],
        )[:3]
        if top_axes:
            print(f"      Top axes: {', '.join(f'{k}={v:.2f}' for k, v in top_axes)}")
    print()

    print(f"  FINAL DECISION: {trace.final_decision}")
    print()

    # 5. Print planner audit
    if trace.memory_access_plan:
        plan = trace.memory_access_plan
        print("  PLANNER AUDIT:")
        print(f"    Rationale: {plan.get('rationale', 'N/A')}")
        print(f"    Queries planned: {len(plan.get('queries', []))}")
        print(f"    Evidence retrieved: {trace.retrieved_evidence_count}")
        if trace.skipped_domains:
            print(f"    Skipped domains: {trace.skipped_domains}")
        print()

    # 6. Surface realization (the twin "speaking")
    print("  TWIN RESPONSE:")
    print(f"  {trace.output_text}")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()

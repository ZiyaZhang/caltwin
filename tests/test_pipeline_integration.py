"""Integration test: run the full runtime pipeline with real API calls."""

import json
import os
import sys

# Ensure src is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twin_runtime.domain.models.twin_state import TwinState
from twin_runtime.application.pipeline.runner import run


def load_twin() -> TwinState:
    fixture = os.path.join(os.path.dirname(__file__), "fixtures", "sample_twin_state.json")
    with open(fixture) as f:
        return TwinState(**json.load(f))


def test_pipeline_work_decision():
    """End-to-end: work domain decision with two options."""
    twin = load_twin()
    trace = run(
        query="I have two projects to choose between: Project A is a high-impact but risky ML infrastructure rewrite, Project B is a safer incremental improvement to existing APIs. Which should I prioritize?",
        option_set=["Project A: ML infrastructure rewrite", "Project B: incremental API improvement"],
        twin=twin,
    )

    # Verify trace structure
    assert trace.trace_id is not None
    assert trace.twin_state_version == "v001"
    assert trace.situation_frame_id is not None
    assert len(trace.activated_domains) > 0
    assert len(trace.head_assessments) > 0
    assert trace.final_decision is not None
    assert trace.output_text is not None
    assert len(trace.output_text) > 10  # Non-trivial output
    assert trace.decision_mode is not None
    assert 0.0 <= trace.uncertainty <= 1.0

    print(f"\n{'='*60}")
    print(f"Trace ID: {trace.trace_id}")
    print(f"Domains: {trace.activated_domains}")
    print(f"Mode: {trace.decision_mode.value}")
    print(f"Uncertainty: {trace.uncertainty}")
    print(f"Decision: {trace.final_decision}")
    print(f"Conflict: {trace.conflict_report_id}")
    print(f"\nHead assessments:")
    for ha in trace.head_assessments:
        print(f"  [{ha.domain.value}] ranking={ha.option_ranking}, conf={ha.confidence:.2f}")
    print(f"\nOutput:\n{trace.output_text}")
    print(f"{'='*60}")


if __name__ == "__main__":
    test_pipeline_work_decision()

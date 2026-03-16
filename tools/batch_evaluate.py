"""Batch evaluation: run twin against all calibration cases, produce fidelity report.

Phase 4 MVP Validation target: choice_fidelity (CF) >= 0.7
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twin_runtime.domain.models.twin_state import TwinState
from twin_runtime.application.calibration.fidelity_evaluator import (
    evaluate_fidelity,
    compute_fidelity_score,
)
from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore

STORE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "store")
USER_ID = "user-ziya"
FIXTURE = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "sample_twin_state.json")


def load_twin() -> TwinState:
    with open(FIXTURE) as f:
        return TwinState(**json.load(f))


def run_batch(with_bias_detection: bool = False) -> None:
    twin = load_twin()
    store = CalibrationStore(STORE_DIR, USER_ID)
    cases = store.list_cases()

    print(f"Twin: {twin.state_version}, {len(twin.domain_heads)} heads")
    print(f"Cases: {len(cases)}")
    if with_bias_detection:
        print("Bias detection: ENABLED")
    print(f"{'='*80}")

    # Run unified fidelity evaluation
    evaluation = evaluate_fidelity(cases, twin)

    # Print per-case results
    print("\nPer-case results:")
    for detail in evaluation.case_details or []:
        rank_str = f"rank={detail.prediction_ranking.index(detail.actual_choice) + 1}" if detail.actual_choice in detail.prediction_ranking else "rank=?"
        top_pred = detail.prediction_ranking[0] if detail.prediction_ranking else "?"
        status = "HIT" if detail.choice_score >= 1.0 else "PARTIAL" if detail.choice_score > 0 else "MISS"
        residual = f" | {detail.residual_direction}" if detail.residual_direction else ""
        print(
            f"  [{detail.domain.value:20s}] {detail.task_type:20s} | "
            f"actual={detail.actual_choice!r:20s} twin_top={top_pred!r:20s} | "
            f"{status} (CF={detail.choice_score:.2f}){residual}"
        )

    # Compute fidelity score (CF/RF/CQ/TS)
    fidelity = compute_fidelity_score(evaluation, historical_evaluations=None)

    print(f"\n{'='*80}")
    print("FIDELITY REPORT")
    print(f"{'='*80}")

    cf = fidelity.choice_fidelity
    rf = fidelity.reasoning_fidelity
    cq = fidelity.calibration_quality
    ts = fidelity.temporal_stability

    print(f"\n  CF (Choice Fidelity):        {cf.value:.3f}  (confidence={cf.confidence_in_metric:.2f}, n={cf.case_count})")
    print(f"  RF (Reasoning Fidelity):     {rf.value:.3f}  (confidence={rf.confidence_in_metric:.2f}, n={rf.case_count})")
    print(f"  CQ (Calibration Quality):    {cq.value:.3f}  (confidence={cq.confidence_in_metric:.2f}, n={cq.case_count})")
    print(f"  TS (Temporal Stability):     {ts.value:.3f}  (confidence={ts.confidence_in_metric:.2f}, n={ts.case_count})")
    print(f"\n  Overall Score: {fidelity.overall_score:.4f}  (confidence={fidelity.overall_confidence:.4f})")
    print(f"  Total cases:   {fidelity.total_cases}")

    print(f"\nPer-domain breakdown:")
    for domain, score in sorted(fidelity.domain_breakdown.items()):
        print(f"  {domain:30s}: {score:.3f}")

    if with_bias_detection:
        print(f"\nBias Detection:")
        domain_scores = fidelity.domain_breakdown
        if domain_scores:
            avg = sum(domain_scores.values()) / len(domain_scores)
            for domain, score in sorted(domain_scores.items()):
                deviation = score - avg
                flag = " [POTENTIAL BIAS]" if abs(deviation) > 0.2 else ""
                print(f"  {domain:30s}: deviation from mean = {deviation:+.3f}{flag}")

    # Persist evaluation and fidelity score to store (for dashboard)
    store.save_evaluation(evaluation)
    store.save_fidelity_score(fidelity)

    # Save report
    report = {
        "twin_version": twin.state_version,
        "total_cases": fidelity.total_cases,
        "choice_fidelity": cf.value,
        "reasoning_fidelity": rf.value,
        "calibration_quality": cq.value,
        "temporal_stability": ts.value,
        "overall_score": fidelity.overall_score,
        "overall_confidence": fidelity.overall_confidence,
        "domain_breakdown": fidelity.domain_breakdown,
    }
    report_path = os.path.join(STORE_DIR, USER_ID, "calibration", "batch_report.json")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nReport saved: {report_path}")

    # MVP gate on CF >= 0.7
    print(f"\n{'='*80}")
    if cf.value >= 0.7:
        print(f"MVP GATE: PASS (CF={cf.value:.3f} >= 0.7)")
    else:
        print(f"MVP GATE: FAIL (CF={cf.value:.3f} < 0.7)")
    print(f"{'='*80}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch fidelity evaluation of the twin against calibration cases."
    )
    parser.add_argument(
        "--with-bias-detection",
        action="store_true",
        default=False,
        help="Enable per-domain bias detection (flags domains deviating >0.2 from mean CF).",
    )
    args = parser.parse_args()
    run_batch(with_bias_detection=args.with_bias_detection)


if __name__ == "__main__":
    main()

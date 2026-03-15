"""Batch evaluation: run twin against all calibration cases, produce reliability report.

Phase 4 MVP Validation target: choice_similarity >= 0.7
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twin_runtime.models.twin_state import TwinState
from twin_runtime.runtime import run as run_pipeline
from twin_runtime.store.calibration_store import CalibrationStore

STORE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "store")
USER_ID = "user-ziya"
FIXTURE = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "sample_twin_state.json")


def load_twin() -> TwinState:
    with open(FIXTURE) as f:
        return TwinState(**json.load(f))


def choice_match(twin_decision: str, twin_rankings: list[str], actual_choice: str) -> tuple[float, int]:
    """Check if twin's prediction matches actual choice.

    Returns (score, rank_position).
    score: 1.0 if top-1 match, 0.5 if top-2, 0.33 if top-3, 0 otherwise.
    """
    actual_lower = actual_choice.lower()

    # Check in rankings first
    for i, opt in enumerate(twin_rankings):
        if actual_lower in opt.lower() or opt.lower() in actual_lower:
            return 1.0 / (i + 1), i + 1

    # Fallback: check in decision text
    if actual_lower in twin_decision.lower():
        return 0.8, 0  # Present but not in rankings

    return 0.0, -1


def run_batch():
    twin = load_twin()
    store = CalibrationStore(STORE_DIR, USER_ID)
    cases = store.list_cases()

    print(f"Twin: {twin.state_version}, {len(twin.domain_heads)} heads")
    print(f"Cases: {len(cases)}")
    print(f"{'='*80}")

    results = []
    domain_results = {}

    for i, case in enumerate(cases):
        print(f"\n[{i+1}/{len(cases)}] {case.task_type}: {case.observed_context[:60]}...")
        print(f"  Actual: {case.actual_choice}")

        try:
            trace = run_pipeline(
                query=case.observed_context,
                option_set=case.option_set,
                twin=twin,
            )

            # Get twin's ranking
            rankings = []
            for ha in trace.head_assessments:
                rankings = ha.option_ranking
                break

            score, rank = choice_match(trace.final_decision, rankings, case.actual_choice)

            results.append({
                "case_id": case.case_id,
                "domain": case.domain_label.value,
                "task_type": case.task_type,
                "actual": case.actual_choice,
                "twin_top": rankings[0] if rankings else "?",
                "twin_decision": trace.final_decision[:80],
                "score": score,
                "rank": rank,
                "uncertainty": trace.uncertainty,
                "mode": trace.decision_mode.value,
            })

            d = case.domain_label.value
            domain_results.setdefault(d, []).append(score)

            status = "HIT" if score >= 0.8 else "PARTIAL" if score > 0 else "MISS"
            print(f"  Twin:   {rankings[0] if rankings else '?'}")
            print(f"  Result: {status} (score={score:.2f}, rank={rank}, uncertainty={trace.uncertainty:.2f})")

        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({
                "case_id": case.case_id,
                "domain": case.domain_label.value,
                "task_type": case.task_type,
                "actual": case.actual_choice,
                "twin_top": "ERROR",
                "score": 0.0,
                "rank": -1,
                "error": str(e),
            })
            domain_results.setdefault(case.domain_label.value, []).append(0.0)

        # Brief pause to avoid rate limiting
        time.sleep(0.5)

    # --- Report ---
    print(f"\n{'='*80}")
    print("RELIABILITY REPORT")
    print(f"{'='*80}")

    all_scores = [r["score"] for r in results]
    avg = sum(all_scores) / len(all_scores) if all_scores else 0

    hits = sum(1 for s in all_scores if s >= 0.8)
    partials = sum(1 for s in all_scores if 0 < s < 0.8)
    misses = sum(1 for s in all_scores if s == 0)

    print(f"\nOverall choice_similarity: {avg:.3f}  (target >= 0.7)")
    print(f"  Hits (top-1):  {hits}/{len(results)} ({hits/len(results)*100:.0f}%)")
    print(f"  Partials:      {partials}/{len(results)}")
    print(f"  Misses:        {misses}/{len(results)}")

    print(f"\nPer-domain:")
    for d, scores in sorted(domain_results.items()):
        d_avg = sum(scores) / len(scores)
        print(f"  {d:20s}: {d_avg:.3f} ({len(scores)} cases)")

    print(f"\nPer-task_type:")
    task_results = {}
    for r in results:
        task_results.setdefault(r.get("task_type", "?"), []).append(r["score"])
    for t, scores in sorted(task_results.items()):
        t_avg = sum(scores) / len(scores)
        print(f"  {t:20s}: {t_avg:.3f} ({len(scores)} cases)")

    # Save report
    report = {
        "twin_version": twin.state_version,
        "total_cases": len(results),
        "choice_similarity": round(avg, 3),
        "hits": hits,
        "partials": partials,
        "misses": misses,
        "domain_reliability": {d: round(sum(s)/len(s), 3) for d, s in domain_results.items()},
        "results": results,
    }
    report_path = os.path.join(STORE_DIR, USER_ID, "calibration", "batch_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nReport saved: {report_path}")

    # MVP gate
    print(f"\n{'='*80}")
    if avg >= 0.7:
        print(f"MVP GATE: PASS (choice_similarity {avg:.3f} >= 0.7)")
    else:
        print(f"MVP GATE: FAIL (choice_similarity {avg:.3f} < 0.7)")
    print(f"{'='*80}")


if __name__ == "__main__":
    run_batch()

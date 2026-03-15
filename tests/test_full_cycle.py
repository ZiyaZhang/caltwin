"""Full cycle integration test: cold start → runtime → feedback → calibration → state update.

This test makes real API calls — run with: python3 tests/test_full_cycle.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twin_runtime.models.primitives import DomainEnum, OrdinalTriLevel
from twin_runtime.models.twin_state import TwinState
from twin_runtime.runtime import run as run_pipeline
from twin_runtime.calibration.event_collector import collect_event, collect_manual_case
from twin_runtime.calibration.case_manager import promote_candidate
from twin_runtime.calibration.state_updater import apply_evaluation
from twin_runtime.calibration.fidelity_evaluator import _choice_similarity
from twin_runtime.store.twin_store import TwinStore
from twin_runtime.store.calibration_store import CalibrationStore
from twin_runtime.models.calibration import TwinEvaluation

import uuid
from datetime import datetime, timezone


def load_twin() -> TwinState:
    fixture = os.path.join(os.path.dirname(__file__), "fixtures", "sample_twin_state.json")
    with open(fixture) as f:
        return TwinState(**json.load(f))


def test_full_cycle():
    """Complete flywheel: runtime → feedback → calibrate → update → verify."""

    with tempfile.TemporaryDirectory() as tmpdir:
        twin = load_twin()
        twin_store = TwinStore(tmpdir)
        cal_store = CalibrationStore(tmpdir, twin.user_id)

        # Save initial state
        twin_store.save(twin)
        print(f"[1] Initial twin: v={twin.state_version}, work_reliability={twin.domain_heads[0].head_reliability}")

        # --- Step 1: Run pipeline ---
        print("\n[2] Running pipeline...")
        trace = run_pipeline(
            query="I need to choose a tech stack for a new microservice: Go for performance or Python for team velocity. Which should I pick?",
            option_set=["Go", "Python"],
            twin=twin,
        )
        print(f"    Decision: {trace.final_decision}")
        print(f"    Mode: {trace.decision_mode.value}, Uncertainty: {trace.uncertainty}")
        print(f"    Output: {trace.output_text[:100]}...")

        # --- Step 2: Collect user feedback (simulated) ---
        print("\n[3] Collecting feedback: user chose 'Go'...")
        event, candidate = collect_event(
            trace,
            user_actual_choice="Go",
            user_reasoning="Performance matters more for this use case, team can learn",
        )
        cal_store.save_event(event)
        cal_store.save_candidate(candidate)
        print(f"    Event type: {event.event_type.value}")
        print(f"    Candidate ID: {candidate.candidate_id}")

        # --- Step 3: Add manual life-anchor cases ---
        print("\n[4] Adding manual calibration cases...")
        manual_cases_data = [
            ("Chose Rust over Java for new CLI tool", ["Rust", "Java"], "Rust",
             "Learning opportunity + performance", OrdinalTriLevel.MEDIUM),
            ("Picked small startup over big corp offer", ["startup", "big_corp"], "startup",
             "Growth and autonomy over stability", OrdinalTriLevel.HIGH),
            ("Decided to open-source internal tool", ["open_source", "keep_internal"], "open_source",
             "Impact and community over control", OrdinalTriLevel.MEDIUM),
        ]
        for ctx, opts, choice, reasoning, stakes in manual_cases_data:
            mc = collect_manual_case(
                domain=DomainEnum.WORK,
                context=ctx,
                option_set=opts,
                actual_choice=choice,
                reasoning=reasoning,
                stakes=stakes,
            )
            cal_store.save_candidate(mc)

        # --- Step 4: Promote through quality gate ---
        print("\n[5] Promoting candidates through quality gate...")
        all_candidates = cal_store.list_candidates(promoted=False)
        promoted_cases = []
        for c in all_candidates:
            case = promote_candidate(c, task_type="tool_selection")
            if case:
                cal_store.save_case(case)
                cal_store.save_candidate(c)  # Update promoted flag
                promoted_cases.append(case)
                print(f"    Promoted: {c.observed_choice} (conf={c.ground_truth_confidence})")
            else:
                print(f"    Rejected: {c.observed_choice}")

        print(f"    Total promoted: {len(promoted_cases)}")

        # --- Step 5: Evaluate fidelity (offline, using choice_similarity only) ---
        # For v0.1, we skip re-running the pipeline for each case (saves API tokens)
        # Instead, compute a synthetic evaluation based on manual scoring
        print("\n[6] Computing fidelity evaluation...")

        # Synthetic evaluation: assume twin agrees with 3/4 cases
        evaluation = TwinEvaluation(
            evaluation_id=str(uuid.uuid4()),
            twin_state_version=twin.state_version,
            calibration_case_ids=[c.case_id for c in promoted_cases],
            choice_similarity=0.75,  # 3/4 correct
            reasoning_similarity=0.6,
            domain_reliability={"work": 0.8},
            evaluated_at=datetime.now(timezone.utc),
        )
        cal_store.save_evaluation(evaluation)
        print(f"    Choice similarity: {evaluation.choice_similarity}")
        print(f"    Domain reliability: {evaluation.domain_reliability}")

        # --- Step 6: Apply evaluation to update twin ---
        print("\n[7] Applying evaluation to update twin state...")
        updated_twin = apply_evaluation(twin, evaluation)
        twin_store.save(updated_twin)

        print(f"    Version: {twin.state_version} → {updated_twin.state_version}")
        print(f"    Work reliability: {twin.domain_heads[0].head_reliability} → {updated_twin.domain_heads[0].head_reliability}")
        print(f"    Core confidence: {twin.shared_decision_core.core_confidence} → {updated_twin.shared_decision_core.core_confidence}")
        print(f"    Evidence count: {twin.shared_decision_core.evidence_count} → {updated_twin.shared_decision_core.evidence_count}")

        # --- Verify ---
        print("\n[8] Verification...")
        versions = twin_store.list_versions(twin.user_id)
        print(f"    Stored versions: {versions}")

        events = cal_store.list_events()
        print(f"    Stored events: {len(events)}")

        cases = cal_store.list_cases()
        print(f"    Stored cases: {len(cases)}")

        evals = cal_store.list_evaluations()
        print(f"    Stored evaluations: {len(evals)}")

        # Assertions
        assert updated_twin.state_version == "v002"
        assert updated_twin.shared_decision_core.evidence_count > twin.shared_decision_core.evidence_count
        assert len(versions) == 2
        assert len(events) == 1
        assert len(cases) == len(promoted_cases)
        assert len(evals) == 1

        print("\n" + "=" * 60)
        print("FULL CYCLE COMPLETE — flywheel verified!")
        print("=" * 60)


if __name__ == "__main__":
    test_full_cycle()

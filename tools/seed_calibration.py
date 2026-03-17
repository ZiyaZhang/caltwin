"""Seed calibration cases from interview data into the calibration store."""

import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twin_runtime.domain.models.primitives import CandidateSourceType, DomainEnum, OrdinalTriLevel
from twin_runtime.application.calibration.event_collector import collect_manual_case
from twin_runtime.application.calibration.case_manager import promote_candidate
from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore

STORE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "store")
USER_ID = "user-ziya"

ORDINAL_MAP = {"low": OrdinalTriLevel.LOW, "medium": OrdinalTriLevel.MEDIUM, "high": OrdinalTriLevel.HIGH}
DOMAIN_MAP = {
    "work": DomainEnum.WORK,
    "life_planning": DomainEnum.LIFE_PLANNING,
    "money": DomainEnum.MONEY,
    "relationships": DomainEnum.RELATIONSHIPS,
    "public_expression": DomainEnum.PUBLIC_EXPRESSION,
}


def seed():
    raw_path = os.path.join(os.path.dirname(__file__), "..", "data", "calibration_cases_raw.json")
    with open(raw_path) as f:
        raw_cases = json.load(f)

    store = CalibrationStore(STORE_DIR, USER_ID)
    promoted = 0
    skipped = 0

    for rc in raw_cases:
        domain = DOMAIN_MAP.get(rc["domain"], DomainEnum.WORK)
        stakes = ORDINAL_MAP.get(rc.get("stakes", "medium"), OrdinalTriLevel.MEDIUM)
        reversibility = ORDINAL_MAP.get(rc.get("reversibility", "medium"), OrdinalTriLevel.MEDIUM)

        # Confidence is lower for inferred cases
        confidence = 0.7 if rc.get("confidence_note") == "inferred_from_notion" else 0.9

        candidate = collect_manual_case(
            domain=domain,
            context=rc["context"],
            option_set=rc["options"],
            actual_choice=rc["choice"],
            reasoning=rc.get("reasoning"),
            stakes=stakes,
            reversibility=reversibility,
            ground_truth_confidence=confidence,
        )
        store.save_candidate(candidate)

        case = promote_candidate(candidate, task_type=rc.get("task_type", "general"))
        if case:
            store.save_case(case)
            store.save_candidate(candidate)  # update promoted flag
            promoted += 1
            print(f"  [OK] {rc['id']}: {rc['choice']}")
        else:
            skipped += 1
            print(f"  [SKIP] {rc['id']}: failed quality gate")

    print(f"\nDone: {promoted} promoted, {skipped} skipped, {len(raw_cases)} total")
    print(f"Store: {STORE_DIR}/{USER_ID}/calibration/")


if __name__ == "__main__":
    seed()

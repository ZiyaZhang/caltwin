"""Calibration Store: persist candidates, cases, evaluations, and events as JSON."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

from ..models.calibration import CalibrationCase, CandidateCalibrationCase, TwinEvaluation
from ..models.runtime import RuntimeEvent


class CalibrationStore:
    """File-based storage for calibration data."""

    def __init__(self, base_dir: str, user_id: str):
        self.base = Path(base_dir) / user_id / "calibration"
        self.base.mkdir(parents=True, exist_ok=True)
        (self.base / "candidates").mkdir(exist_ok=True)
        (self.base / "cases").mkdir(exist_ok=True)
        (self.base / "evaluations").mkdir(exist_ok=True)
        (self.base / "events").mkdir(exist_ok=True)

    # --- Candidates ---

    def save_candidate(self, candidate: CandidateCalibrationCase) -> None:
        path = self.base / "candidates" / f"{candidate.candidate_id}.json"
        path.write_text(candidate.model_dump_json(indent=2))

    def load_candidate(self, candidate_id: str) -> CandidateCalibrationCase:
        path = self.base / "candidates" / f"{candidate_id}.json"
        return CandidateCalibrationCase(**json.loads(path.read_text()))

    def list_candidates(self, promoted: Optional[bool] = None) -> List[CandidateCalibrationCase]:
        candidates = []
        for f in sorted((self.base / "candidates").glob("*.json")):
            c = CandidateCalibrationCase(**json.loads(f.read_text()))
            if promoted is None or c.promoted_to_calibration_case == promoted:
                candidates.append(c)
        return candidates

    # --- Cases ---

    def save_case(self, case: CalibrationCase) -> None:
        path = self.base / "cases" / f"{case.case_id}.json"
        path.write_text(case.model_dump_json(indent=2))

    def load_case(self, case_id: str) -> CalibrationCase:
        path = self.base / "cases" / f"{case_id}.json"
        return CalibrationCase(**json.loads(path.read_text()))

    def list_cases(self, used: Optional[bool] = None) -> List[CalibrationCase]:
        cases = []
        for f in sorted((self.base / "cases").glob("*.json")):
            c = CalibrationCase(**json.loads(f.read_text()))
            if used is None or c.used_for_calibration == used:
                cases.append(c)
        return cases

    # --- Evaluations ---

    def save_evaluation(self, evaluation: TwinEvaluation) -> None:
        path = self.base / "evaluations" / f"{evaluation.evaluation_id}.json"
        path.write_text(evaluation.model_dump_json(indent=2))

    def list_evaluations(self) -> List[TwinEvaluation]:
        evals = []
        for f in sorted((self.base / "evaluations").glob("*.json")):
            evals.append(TwinEvaluation(**json.loads(f.read_text())))
        return evals

    # --- Events ---

    def save_event(self, event: RuntimeEvent) -> None:
        path = self.base / "events" / f"{event.event_id}.json"
        path.write_text(event.model_dump_json(indent=2))

    def list_events(self) -> List[RuntimeEvent]:
        events = []
        for f in sorted((self.base / "events").glob("*.json")):
            events.append(RuntimeEvent(**json.loads(f.read_text())))
        return events

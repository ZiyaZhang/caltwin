"""Calibration Store: persist candidates, cases, evaluations, and events as JSON."""

from __future__ import annotations

import re
from pathlib import Path
from datetime import datetime
from typing import List, Optional

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


def _validate_safe_id(value: str, label: str = "ID") -> str:
    if not value or not _SAFE_ID_RE.match(value):
        raise ValueError(f"Unsafe {label} for filesystem use: {value!r}")
    return value

from twin_runtime.infrastructure.backends.json_file._utils import atomic_write
from twin_runtime.domain.models.calibration import (
    CalibrationCase, CandidateCalibrationCase, TwinEvaluation,
    OutcomeRecord, DetectedBias, TwinFidelityScore,
)
from twin_runtime.domain.models.primitives import DetectedBiasStatus
from twin_runtime.domain.models.runtime import RuntimeEvent


class CalibrationStore:
    """File-based storage for calibration data."""

    def __init__(self, base_dir: str, user_id: str):
        _validate_safe_id(user_id, "user_id")
        self.base = Path(base_dir) / user_id / "calibration"
        self.base.mkdir(parents=True, exist_ok=True)
        (self.base / "candidates").mkdir(exist_ok=True)
        (self.base / "cases").mkdir(exist_ok=True)
        (self.base / "evaluations").mkdir(exist_ok=True)
        (self.base / "events").mkdir(exist_ok=True)
        (self.base / "outcomes").mkdir(exist_ok=True)
        (self.base / "detected_biases").mkdir(exist_ok=True)
        (self.base / "fidelity_scores").mkdir(exist_ok=True)

    # --- Candidates ---

    def save_candidate(self, candidate: CandidateCalibrationCase) -> str:
        path = self.base / "candidates" / f"{candidate.candidate_id}.json"
        atomic_write(path, candidate.model_dump_json(indent=2))
        return candidate.candidate_id

    def load_candidate(self, candidate_id: str) -> CandidateCalibrationCase:
        path = self.base / "candidates" / f"{candidate_id}.json"
        return CandidateCalibrationCase.model_validate_json(path.read_text())

    def list_candidates(self, promoted: Optional[bool] = None) -> List[CandidateCalibrationCase]:
        candidates = []
        for f in sorted((self.base / "candidates").glob("*.json")):
            c = CandidateCalibrationCase.model_validate_json(f.read_text())
            if promoted is None or c.promoted_to_calibration_case == promoted:
                candidates.append(c)
        return candidates

    # --- Cases ---

    def save_case(self, case: CalibrationCase) -> str:
        path = self.base / "cases" / f"{case.case_id}.json"
        atomic_write(path, case.model_dump_json(indent=2))
        return case.case_id

    def load_case(self, case_id: str) -> CalibrationCase:
        path = self.base / "cases" / f"{case_id}.json"
        return CalibrationCase.model_validate_json(path.read_text())

    def list_cases(self, used: Optional[bool] = None) -> List[CalibrationCase]:
        cases = []
        for f in sorted((self.base / "cases").glob("*.json")):
            c = CalibrationCase.model_validate_json(f.read_text())
            if used is None or c.used_for_calibration == used:
                cases.append(c)
        return cases

    # --- Evaluations ---

    def save_evaluation(self, evaluation: TwinEvaluation) -> str:
        path = self.base / "evaluations" / f"{evaluation.evaluation_id}.json"
        atomic_write(path, evaluation.model_dump_json(indent=2))
        return evaluation.evaluation_id

    def list_evaluations(self) -> List[TwinEvaluation]:
        evals = []
        for f in sorted((self.base / "evaluations").glob("*.json")):
            evals.append(TwinEvaluation.model_validate_json(f.read_text()))
        evals.sort(key=lambda e: e.evaluated_at)
        return evals

    # --- Events ---

    def save_event(self, event: RuntimeEvent) -> str:
        path = self.base / "events" / f"{event.event_id}.json"
        atomic_write(path, event.model_dump_json(indent=2))
        return event.event_id

    def list_events(self, since: Optional[datetime] = None) -> List[RuntimeEvent]:
        events = []
        for f in sorted((self.base / "events").glob("*.json")):
            ev = RuntimeEvent.model_validate_json(f.read_text())
            if since is not None and ev.observed_at < since:
                continue
            events.append(ev)
        return events

    # --- Outcomes ---

    def save_outcome(self, outcome: OutcomeRecord) -> str:
        path = self.base / "outcomes" / f"{outcome.outcome_id}.json"
        atomic_write(path, outcome.model_dump_json(indent=2))
        return outcome.outcome_id

    def list_outcomes(self, trace_id: Optional[str] = None) -> List[OutcomeRecord]:
        outcomes = []
        for f in sorted((self.base / "outcomes").glob("*.json")):
            o = OutcomeRecord.model_validate_json(f.read_text())
            if trace_id is not None and o.trace_id != trace_id:
                continue
            outcomes.append(o)
        return outcomes

    # --- Detected Biases ---

    def save_detected_bias(self, bias: DetectedBias) -> str:
        path = self.base / "detected_biases" / f"{bias.bias_id}.json"
        atomic_write(path, bias.model_dump_json(indent=2))
        return bias.bias_id

    def list_detected_biases(self, status: Optional[DetectedBiasStatus] = None) -> List[DetectedBias]:
        biases = []
        for f in sorted((self.base / "detected_biases").glob("*.json")):
            b = DetectedBias.model_validate_json(f.read_text())
            if status is not None and b.status != status:
                continue
            biases.append(b)
        return biases

    # --- Fidelity Scores ---

    def save_fidelity_score(self, score: TwinFidelityScore) -> str:
        path = self.base / "fidelity_scores" / f"{score.score_id}.json"
        atomic_write(path, score.model_dump_json(indent=2))
        return score.score_id

    def list_fidelity_scores(self, limit: int = 10) -> List[TwinFidelityScore]:
        scores = []
        for f in sorted((self.base / "fidelity_scores").glob("*.json")):
            scores.append(TwinFidelityScore.model_validate_json(f.read_text()))
        scores.sort(key=lambda s: s.computed_at, reverse=True)
        return scores[:limit]

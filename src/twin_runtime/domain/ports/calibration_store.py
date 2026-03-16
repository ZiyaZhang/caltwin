"""Port: Calibration data storage."""
from __future__ import annotations
from datetime import datetime
from typing import List, Optional, Protocol, runtime_checkable
from twin_runtime.domain.models.calibration import (
    CalibrationCase, CandidateCalibrationCase, TwinEvaluation,
)
from twin_runtime.domain.models.runtime import RuntimeEvent


@runtime_checkable
class CalibrationStore(Protocol):
    """Store calibration lifecycle objects."""
    def save_candidate(self, candidate: CandidateCalibrationCase) -> str: ...
    def save_case(self, case: CalibrationCase) -> str: ...
    def save_evaluation(self, evaluation: TwinEvaluation) -> str: ...
    def save_event(self, event: RuntimeEvent) -> str: ...
    # save_outcome() deferred to Phase 3 — OutcomeRecord model doesn't exist yet.
    def list_cases(self, used: Optional[bool] = None) -> List[CalibrationCase]: ...
    def list_events(self, since: Optional[datetime] = None) -> List[RuntimeEvent]: ...

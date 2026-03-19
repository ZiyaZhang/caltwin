"""Port: Calibration data storage — focused sub-protocols + composite."""
from __future__ import annotations
from datetime import datetime
from typing import List, Optional, Protocol, runtime_checkable
from twin_runtime.domain.models.calibration import (
    CalibrationCase, CandidateCalibrationCase, TwinEvaluation,
    OutcomeRecord, DetectedBias, TwinFidelityScore,
)
from twin_runtime.domain.models.primitives import DetectedBiasStatus
from twin_runtime.domain.models.runtime import RuntimeEvent


# --- Focused sub-protocols ---


@runtime_checkable
class CandidateStore(Protocol):
    """Store candidates and calibration cases."""
    def save_candidate(self, candidate: CandidateCalibrationCase) -> str: ...
    def save_case(self, case: CalibrationCase) -> str: ...
    def list_cases(self, used: Optional[bool] = None) -> List[CalibrationCase]: ...


@runtime_checkable
class OutcomeStore(Protocol):
    """Store outcome records."""
    def save_outcome(self, outcome: OutcomeRecord) -> str: ...
    def list_outcomes(self, trace_id: Optional[str] = None, *, limit: int = 500) -> List[OutcomeRecord]: ...


@runtime_checkable
class BiasStore(Protocol):
    """Store detected biases."""
    def save_detected_bias(self, bias: DetectedBias) -> str: ...
    def list_detected_biases(self, status: Optional[DetectedBiasStatus] = None) -> List[DetectedBias]: ...


@runtime_checkable
class FidelityStore(Protocol):
    """Store fidelity scores."""
    def save_fidelity_score(self, score: TwinFidelityScore) -> str: ...
    def list_fidelity_scores(self, limit: int = 10) -> List[TwinFidelityScore]: ...


@runtime_checkable
class EvaluationStore(Protocol):
    """Store twin evaluations."""
    def save_evaluation(self, evaluation: TwinEvaluation) -> str: ...
    def list_evaluations(self) -> List[TwinEvaluation]: ...


@runtime_checkable
class EventStore(Protocol):
    """Store runtime events."""
    def save_event(self, event: RuntimeEvent) -> str: ...
    def list_events(self, since: Optional[datetime] = None) -> List[RuntimeEvent]: ...


# --- Composite for backward compatibility ---


@runtime_checkable
class CalibrationStore(
    CandidateStore, OutcomeStore, BiasStore,
    FidelityStore, EvaluationStore, EventStore,
    Protocol,
):
    """Composite store — all calibration lifecycle objects.

    Existing code can continue to depend on this single protocol.
    New code should prefer the narrower sub-protocols above.
    """
    ...

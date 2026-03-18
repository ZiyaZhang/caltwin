from dataclasses import dataclass, field
from typing import List, Optional
from twin_runtime.domain.models.calibration import (
    TwinFidelityScore, TwinEvaluation, DetectedBias,
)
from twin_runtime.domain.models.twin_state import TwinState


@dataclass
class DashboardPayload:
    fidelity_score: TwinFidelityScore  # Primary (weighted when available)
    evaluation: TwinEvaluation
    twin: TwinState
    detected_biases: List[DetectedBias] = field(default_factory=list)
    historical_scores: List[TwinFidelityScore] = field(default_factory=list)
    raw_fidelity_score: Optional[TwinFidelityScore] = None  # Raw (unweighted) for comparison

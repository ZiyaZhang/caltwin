"""Backward-compat shim — real code is in domain.models.*."""
from twin_runtime.domain.models.primitives import *  # noqa: F401,F403
from twin_runtime.domain.models.twin_state import (  # noqa: F401
    BiasCorrectionEntry,
    CausalBeliefModel,
    DomainHead,
    EvidenceWeightProfile,
    PriorBiasPattern,
    ReliabilityProfileEntry,
    RejectionPolicyMap,
    ScopeDeclaration,
    SharedDecisionCore,
    TemporalMetadata,
    TransferCoefficient,
    TwinState,
)
from twin_runtime.domain.models.situation import SituationFeatureVector, SituationFrame  # noqa: F401
from twin_runtime.domain.models.runtime import (  # noqa: F401
    ConflictReport,
    HeadAssessment,
    RuntimeDecisionTrace,
    RuntimeEvent,
)
from twin_runtime.domain.models.calibration import (  # noqa: F401
    CalibrationCase,
    CandidateCalibrationCase,
    TwinEvaluation,
)

"""Shared test helper functions.

Import these in test modules as:
    from tests.helpers import make_situation_frame, make_twin
"""

import json
from pathlib import Path

from twin_runtime.domain.models.twin_state import TwinState
from twin_runtime.domain.models.primitives import (
    DomainEnum,
    OptionStructure,
    OrdinalTriLevel,
    ScopeStatus,
    UncertaintyType,
)
from twin_runtime.domain.models.situation import SituationFeatureVector, SituationFrame

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def make_situation_frame(
    *,
    frame_id="test-frame",
    scope=ScopeStatus.IN_SCOPE,
    stakes="medium",
    ambiguity=0.3,
    domains=None,
):
    """Create a SituationFrame with sensible defaults for testing."""
    return SituationFrame(
        frame_id=frame_id,
        domain_activation_vector=domains if domains is not None else {DomainEnum.WORK: 0.9},
        situation_feature_vector=SituationFeatureVector(
            reversibility=OrdinalTriLevel.MEDIUM,
            stakes=OrdinalTriLevel(stakes),
            uncertainty_type=UncertaintyType.MIXED,
            controllability=OrdinalTriLevel.MEDIUM,
            option_structure=OptionStructure.CHOOSE_EXISTING,
        ),
        ambiguity_score=ambiguity,
        scope_status=scope,
        routing_confidence=0.8,
    )


def make_twin():
    """Load the sample TwinState fixture."""
    return TwinState(**json.loads(
        (FIXTURES_DIR / "sample_twin_state.json").read_text()
    ))

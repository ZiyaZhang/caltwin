"""Tests for head_activator structured output."""
import pytest
import json
from unittest.mock import MagicMock

from twin_runtime.domain.models.primitives import DomainEnum, OrdinalTriLevel, UncertaintyType, OptionStructure
from twin_runtime.domain.models.situation import SituationFrame, SituationFeatureVector
from twin_runtime.domain.models.twin_state import TwinState
from twin_runtime.application.pipeline.head_activator import activate_heads


class TestHeadActivatorStructured:
    def test_calls_ask_structured_not_ask_json(self):
        with open("tests/fixtures/sample_twin_state.json") as f:
            twin = TwinState(**json.load(f))

        llm = MagicMock()
        llm.ask_structured.return_value = {
            "option_ranking": ["Stay", "Leave"],
            "utility_decomposition": {"growth": 0.7},
            "confidence": 0.8,
            "used_core_variables": ["risk_tolerance"],
            "used_evidence_types": [],
        }

        frame = SituationFrame(
            frame_id="test",
            domain_activation_vector={DomainEnum.WORK: 1.0},
            situation_feature_vector=SituationFeatureVector(
                reversibility=OrdinalTriLevel.MEDIUM,
                stakes=OrdinalTriLevel.HIGH,
                uncertainty_type=UncertaintyType.OUTCOME_UNCERTAINTY,
                controllability=OrdinalTriLevel.MEDIUM,
                option_structure=OptionStructure.CHOOSE_EXISTING,
            ),
            ambiguity_score=0.3,
            scope_status="in_scope",
            routing_confidence=0.9,
        )

        assessments = activate_heads("Should I stay?", ["Stay", "Leave"], frame, twin, llm=llm)
        assert len(assessments) >= 1
        llm.ask_structured.assert_called()
        call_kwargs = llm.ask_structured.call_args
        assert "schema" in call_kwargs.kwargs
        assert call_kwargs.kwargs["schema_name"] == "head_assessment"

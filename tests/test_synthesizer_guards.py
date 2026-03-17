"""Tests for synthesizer option guards."""
import pytest
from unittest.mock import MagicMock
from twin_runtime.domain.models.primitives import DomainEnum, DecisionMode, OrdinalTriLevel, UncertaintyType, OptionStructure, ScopeStatus
from twin_runtime.domain.models.runtime import HeadAssessment
from twin_runtime.domain.models.situation import SituationFrame, SituationFeatureVector
from twin_runtime.application.pipeline.decision_synthesizer import _synthesize_decision


def _frame():
    return SituationFrame(
        frame_id="test",
        domain_activation_vector={DomainEnum.WORK: 1.0},
        situation_feature_vector=SituationFeatureVector(
            reversibility=OrdinalTriLevel.MEDIUM,
            stakes=OrdinalTriLevel.MEDIUM,
            uncertainty_type=UncertaintyType.MIXED,
            controllability=OrdinalTriLevel.MEDIUM,
            option_structure=OptionStructure.CHOOSE_EXISTING,
        ),
        ambiguity_score=0.3,
        scope_status=ScopeStatus.IN_SCOPE,
        routing_confidence=0.9,
    )


def _assessment(ranking, confidence=0.8):
    a = MagicMock(spec=HeadAssessment)
    a.domain = DomainEnum.WORK
    a.option_ranking = ranking
    a.confidence = confidence
    a.utility_decomposition = {}
    return a


class TestPhantomOptionGuard:
    def test_phantom_option_excluded(self):
        assessments = [_assessment(["Phantom", "A", "B"])]
        decision, mode, uncertainty, refusal = _synthesize_decision(
            assessments, None, _frame(), option_set=["A", "B"]
        )
        assert "Phantom" not in decision
        assert "A" in decision or "B" in decision

    def test_missing_option_gets_floor_score(self):
        assessments = [_assessment(["A"])]
        decision, mode, uncertainty, refusal = _synthesize_decision(
            assessments, None, _frame(), option_set=["A", "B"]
        )
        assert "A" in decision

    def test_all_options_present_no_change(self):
        assessments = [_assessment(["B", "A"])]
        decision, mode, uncertainty, refusal = _synthesize_decision(
            assessments, None, _frame(), option_set=["A", "B"]
        )
        assert "B" in decision

    def test_all_phantom_triggers_degraded(self):
        assessments = [_assessment(["Ghost1", "Ghost2"])]
        decision, mode, uncertainty, refusal = _synthesize_decision(
            assessments, None, _frame(), option_set=["A", "B"]
        )
        assert mode == DecisionMode.DEGRADED

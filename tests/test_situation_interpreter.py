"""Tests for data-driven keyword routing in situation_interpreter."""
import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone

from twin_runtime.domain.models.primitives import DomainEnum
from twin_runtime.domain.models.twin_state import DomainHead, EvidenceWeightProfile
from twin_runtime.application.pipeline.situation_interpreter import _keyword_scores_from_twin


def _make_head(domain, keywords, reliability=0.8):
    return DomainHead(
        domain=domain, head_version="v1", goal_axes=["test"], keywords=keywords,
        evidence_weight_profile=EvidenceWeightProfile(
            self_report_weight=1.0, historical_behavior_weight=1.0,
            recent_behavior_weight=1.0, outcome_feedback_weight=1.0, weight_confidence=0.8,
        ),
        head_reliability=reliability, supported_task_types=["general"],
        last_recalibrated_at=datetime.now(timezone.utc),
    )


class TestKeywordScoresFromTwin:
    def test_scores_from_domain_head_keywords(self):
        heads = [
            _make_head(DomainEnum.WORK, ["project", "sprint", "项目"]),
            _make_head(DomainEnum.MONEY, ["invest", "budget"]),
        ]
        scores = _keyword_scores_from_twin("I need to review the project budget", heads)
        assert DomainEnum.WORK in scores
        assert DomainEnum.MONEY in scores

    def test_empty_keywords_uses_legacy_fallback(self):
        heads = [_make_head(DomainEnum.WORK, [])]
        scores = _keyword_scores_from_twin("I need to deploy this project", heads)
        assert DomainEnum.WORK in scores  # Legacy fallback has "project" and "deploy"

    def test_new_domain_keywords_no_code_change(self):
        heads = [
            _make_head(DomainEnum.WORK, ["project"]),
            _make_head(DomainEnum.RELATIONSHIPS, ["family", "friend", "家人"]),
        ]
        scores = _keyword_scores_from_twin("family project", heads)
        assert DomainEnum.WORK in scores
        assert DomainEnum.RELATIONSHIPS in scores

    def test_no_match_returns_empty(self):
        heads = [_make_head(DomainEnum.WORK, ["sprint"])]
        scores = _keyword_scores_from_twin("completely unrelated query", heads)
        assert scores == {}


class TestInterpretSituationStructured:
    def test_calls_ask_structured_not_ask_json(self):
        from twin_runtime.application.pipeline.situation_interpreter import interpret_situation
        from twin_runtime.domain.models.twin_state import TwinState
        import json

        with open("tests/fixtures/sample_twin_state.json") as f:
            twin = TwinState(**json.load(f))

        llm = MagicMock()
        llm.ask_structured.return_value = {
            "domain_activation": {"work": 0.9},
            "reversibility": "medium",
            "stakes": "high",
            "uncertainty_type": "outcome_uncertainty",
            "controllability": "medium",
            "option_structure": "choose_existing",
            "ambiguity_score": 0.3,
            "clarification_questions": [],
        }

        frame, _guard = interpret_situation("Should I deploy on Friday?", twin, llm=llm)
        llm.ask_structured.assert_called_once()
        call_kwargs = llm.ask_structured.call_args
        assert "schema" in call_kwargs.kwargs
        assert call_kwargs.kwargs["schema_name"] == "situation_analysis"

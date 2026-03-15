"""Unit tests for runtime components that don't require API calls."""

import pytest
from twin_runtime.models.primitives import ConflictType, DomainEnum, MergeStrategy
from twin_runtime.runtime.conflict_arbiter import (
    _detect_ranking_disagreement,
    _detect_utility_conflict,
    arbitrate,
)
from twin_runtime.models.runtime import HeadAssessment


def _make_assessment(domain, ranking, utility, confidence=0.7):
    return HeadAssessment(
        domain=domain,
        head_version="v001",
        option_ranking=ranking,
        utility_decomposition=utility,
        confidence=confidence,
        used_core_variables=["risk_tolerance"],
        used_evidence_types=["historical_behavior"],
    )


class TestConflictArbiter:
    def test_single_head_no_conflict(self):
        a = _make_assessment(DomainEnum.WORK, ["A", "B"], {"impact": 0.8})
        assert arbitrate([a]) is None

    def test_agreeing_heads_no_conflict(self):
        a1 = _make_assessment(DomainEnum.WORK, ["A", "B"], {"impact": 0.8, "learning": 0.6})
        a2 = _make_assessment(DomainEnum.LIFE_PLANNING, ["A", "B"], {"growth": 0.7, "learning": 0.5})
        result = arbitrate([a1, a2])
        assert result is None

    def test_ranking_disagreement_detected(self):
        a1 = _make_assessment(DomainEnum.WORK, ["A", "B"], {"impact": 0.8})
        a2 = _make_assessment(DomainEnum.LIFE_PLANNING, ["B", "A"], {"growth": 0.9})
        assert _detect_ranking_disagreement([a1, a2]) is True

    def test_utility_conflict_detected(self):
        a1 = _make_assessment(DomainEnum.WORK, ["A", "B"], {"risk": 0.9})
        a2 = _make_assessment(DomainEnum.LIFE_PLANNING, ["A", "B"], {"risk": 0.2})
        axes = _detect_utility_conflict([a1, a2])
        assert "risk" in axes

    def test_mixed_conflict_report(self):
        a1 = _make_assessment(DomainEnum.WORK, ["A", "B"], {"risk": 0.9, "impact": 0.8})
        a2 = _make_assessment(DomainEnum.LIFE_PLANNING, ["B", "A"], {"risk": 0.2, "impact": 0.7})
        report = arbitrate([a1, a2])
        assert report is not None
        assert ConflictType.MIXED in report.conflict_types
        assert report.final_merge_strategy == MergeStrategy.CLARIFY
        assert report.requires_user_clarification is True

    def test_preference_conflict_only(self):
        # Same ranking but different utility scores
        a1 = _make_assessment(DomainEnum.WORK, ["A", "B"], {"stability": 0.9})
        a2 = _make_assessment(DomainEnum.MONEY, ["A", "B"], {"stability": 0.3})
        report = arbitrate([a1, a2])
        assert report is not None
        assert ConflictType.PREFERENCE in report.conflict_types

    def test_belief_conflict_only(self):
        # Different ranking but no utility axis divergence
        a1 = _make_assessment(DomainEnum.WORK, ["A", "B"], {"impact": 0.7})
        a2 = _make_assessment(DomainEnum.LIFE_PLANNING, ["B", "A"], {"growth": 0.7})
        report = arbitrate([a1, a2])
        assert report is not None
        assert ConflictType.BELIEF in report.conflict_types


class TestSituationInterpreterKeywords:
    def test_keyword_scores(self):
        from twin_runtime.runtime.situation_interpreter import _keyword_scores
        scores = _keyword_scores("I need to deploy this project before the deadline")
        assert DomainEnum.WORK in scores
        assert scores[DomainEnum.WORK] > 0

    def test_keyword_scores_empty(self):
        from twin_runtime.runtime.situation_interpreter import _keyword_scores
        scores = _keyword_scores("hello world")
        assert scores == {}

    def test_keyword_scores_multi_domain(self):
        from twin_runtime.runtime.situation_interpreter import _keyword_scores
        scores = _keyword_scores("Should I invest my salary in career growth?")
        assert len(scores) >= 2

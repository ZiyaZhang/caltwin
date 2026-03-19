"""Tests for bootstrap question definitions."""

from __future__ import annotations

import pytest

from twin_runtime.application.bootstrap.questions import (
    BootstrapAnswer,
    BootstrapQuestion,
    DEFAULT_QUESTIONS,
    QuestionType,
)

# ---------------------------------------------------------------------------
# Structural counts
# ---------------------------------------------------------------------------

_PHASE1 = [q for q in DEFAULT_QUESTIONS if q.phase == 1]
_PHASE2 = [q for q in DEFAULT_QUESTIONS if q.phase == 2]
_PHASE3 = [q for q in DEFAULT_QUESTIONS if q.phase == 3]

EXPECTED_AXES = {
    "risk_tolerance",
    "action_threshold",
    "information_threshold",
    "conflict_style_proxy",
    "explore_exploit_balance",
}


def test_total_question_count() -> None:
    assert len(DEFAULT_QUESTIONS) == 20


def test_phase1_count_and_type() -> None:
    assert len(_PHASE1) == 12
    for q in _PHASE1:
        assert q.type == QuestionType.FORCED_CHOICE


def test_phase2_count_and_domains() -> None:
    assert len(_PHASE2) == 5
    for q in _PHASE2:
        assert q.domain is not None, f"Phase 2 question {q.id} must have a domain"


def test_phase3_count_and_type() -> None:
    assert len(_PHASE3) == 3
    for q in _PHASE3:
        assert q.type == QuestionType.OPEN_SCENARIO


# ---------------------------------------------------------------------------
# Axis coverage
# ---------------------------------------------------------------------------


def test_all_axes_covered_by_phase1() -> None:
    covered = set()
    for q in _PHASE1:
        covered.update(q.axes.keys())
    assert covered == EXPECTED_AXES


def test_phase1_axes_mapping_has_two_elements() -> None:
    for q in _PHASE1:
        for axis_name, values in q.axes.items():
            assert len(values) == 2, (
                f"Question {q.id}, axis '{axis_name}' must have exactly 2 push values"
            )


# ---------------------------------------------------------------------------
# QuestionType enum
# ---------------------------------------------------------------------------


def test_no_document_upload_type() -> None:
    members = {m.value for m in QuestionType}
    assert "document_upload" not in members
    assert not hasattr(QuestionType, "DOCUMENT_UPLOAD")


# ---------------------------------------------------------------------------
# BootstrapAnswer validation
# ---------------------------------------------------------------------------


def test_answer_forced_choice() -> None:
    ans = BootstrapAnswer(
        question_id="p1_risk_01",
        type=QuestionType.FORCED_CHOICE,
        chosen_option=0,
    )
    assert ans.chosen_option == 0
    assert ans.free_text is None


def test_answer_slider() -> None:
    ans = BootstrapAnswer(
        question_id="custom",
        type=QuestionType.SLIDER,
        slider_value=0.75,
    )
    assert ans.slider_value == 0.75


def test_answer_open_scenario() -> None:
    ans = BootstrapAnswer(
        question_id="p3_scenario_work",
        type=QuestionType.OPEN_SCENARIO,
        free_text="I chose to switch teams because...",
    )
    assert ans.free_text is not None


def test_answer_with_domain_and_tags() -> None:
    ans = BootstrapAnswer(
        question_id="p2_domain_work",
        type=QuestionType.FORCED_CHOICE,
        chosen_option=1,
        domain="work",
        tags=["work"],
    )
    assert ans.domain == "work"
    assert "work" in ans.tags


# ---------------------------------------------------------------------------
# Uniqueness
# ---------------------------------------------------------------------------


def test_question_ids_are_unique() -> None:
    ids = [q.id for q in DEFAULT_QUESTIONS]
    assert len(ids) == len(set(ids)), "Duplicate question IDs found"

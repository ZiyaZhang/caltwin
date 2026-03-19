"""Tests for BootstrapEngine — all using mock LLM, no real API calls."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from twin_runtime.application.bootstrap.engine import BootstrapEngine, BootstrapResult
from twin_runtime.application.bootstrap.questions import (
    BootstrapAnswer,
    QuestionType,
)
from twin_runtime.domain.models.primitives import ConflictStyle, DomainEnum


# ---------------------------------------------------------------------------
# Mock LLM
# ---------------------------------------------------------------------------


class MockLLM:
    """A mock LLMPort that returns predetermined responses."""

    def __init__(
        self,
        json_response: Optional[Dict[str, Any]] = None,
        text_response: str = "",
    ) -> None:
        self._json_response = json_response or {}
        self._text_response = text_response
        self.calls: List[Dict[str, Any]] = []

    def ask_json(
        self, system: str, user: str, max_tokens: int = 1024
    ) -> Dict[str, Any]:
        self.calls.append(
            {"method": "ask_json", "system": system, "user": user}
        )
        return self._json_response

    def ask_text(
        self, system: str, user: str, max_tokens: int = 1024
    ) -> str:
        self.calls.append(
            {"method": "ask_text", "system": system, "user": user}
        )
        return self._text_response

    def ask_structured(
        self,
        system: str,
        user: str,
        *,
        schema: Dict[str, Any],
        schema_name: str = "structured_output",
        max_tokens: int = 1024,
    ) -> Dict[str, Any]:
        self.calls.append(
            {"method": "ask_structured", "system": system, "user": user}
        )
        return self._json_response



# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_mock_llm() -> MockLLM:
    """Create a MockLLM that returns sensible bootstrap responses.

    The mock returns different responses depending on whether the call is
    for principles (forced-choice synthesis) or narrative extraction.
    """
    # We use a stateful mock that tracks call count to alternate responses.
    class _StatefulMockLLM(MockLLM):
        def __init__(self) -> None:
            super().__init__()
            self._call_count = 0

        def ask_json(
            self, system: str, user: str, max_tokens: int = 1024
        ) -> Dict[str, Any]:
            self.calls.append(
                {"method": "ask_json", "system": system, "user": user}
            )
            self._call_count += 1
            if "principles" in system.lower() or "synthesize" in system.lower():
                return {
                    "principles": [
                        {
                            "insight": "Prefers action over analysis when stakes are moderate",
                            "scenario_type": ["work", "risk"],
                            "applicable_when": "Moderate-stakes decisions with time pressure",
                        },
                        {
                            "insight": "Values team input but makes final call independently",
                            "scenario_type": ["leadership", "collaboration"],
                            "applicable_when": "Team decisions with clear ownership",
                        },
                        {
                            "insight": "Explores new approaches when current ones stagnate",
                            "scenario_type": ["innovation", "learning"],
                            "applicable_when": "Diminishing returns on existing methods",
                        },
                        {
                            "insight": "Risk-tolerant in career but conservative with money",
                            "scenario_type": ["career", "finance"],
                            "applicable_when": "Cross-domain risk decisions",
                        },
                        {
                            "insight": "Seeks minimal viable information before committing",
                            "scenario_type": ["efficiency", "decision"],
                            "applicable_when": "Time-sensitive decisions",
                        },
                    ]
                }
            else:
                # Narrative extraction
                return {
                    "entries": [
                        {
                            "insight": "Past experience confirms bias toward action",
                            "scenario_type": ["narrative", "action"],
                            "applicable_when": "Similar high-pressure situations",
                        }
                    ]
                }

    return _StatefulMockLLM()


def _phase1_answers_consistent() -> List[BootstrapAnswer]:
    """All risk answers choose option 1 (risk-seeking), action answers choose 1, etc."""
    return [
        # Risk: all option 1 (positive push)
        BootstrapAnswer(question_id="p1_risk_01", type=QuestionType.FORCED_CHOICE, chosen_option=1),
        BootstrapAnswer(question_id="p1_risk_02", type=QuestionType.FORCED_CHOICE, chosen_option=1),
        BootstrapAnswer(question_id="p1_risk_03", type=QuestionType.FORCED_CHOICE, chosen_option=1),
        # Action: all option 1 (action-oriented)
        BootstrapAnswer(question_id="p1_action_01", type=QuestionType.FORCED_CHOICE, chosen_option=1),
        BootstrapAnswer(question_id="p1_action_02", type=QuestionType.FORCED_CHOICE, chosen_option=1),
        BootstrapAnswer(question_id="p1_action_03", type=QuestionType.FORCED_CHOICE, chosen_option=1),
        # Info: all option 1 (rely on own judgment)
        BootstrapAnswer(question_id="p1_info_01", type=QuestionType.FORCED_CHOICE, chosen_option=1),
        BootstrapAnswer(question_id="p1_info_02", type=QuestionType.FORCED_CHOICE, chosen_option=1),
        # Conflict: all option 1 (direct)
        BootstrapAnswer(question_id="p1_conflict_01", type=QuestionType.FORCED_CHOICE, chosen_option=1),
        BootstrapAnswer(question_id="p1_conflict_02", type=QuestionType.FORCED_CHOICE, chosen_option=1),
        # Explore: all option 1 (explore new)
        BootstrapAnswer(question_id="p1_explore_01", type=QuestionType.FORCED_CHOICE, chosen_option=1),
        BootstrapAnswer(question_id="p1_explore_02", type=QuestionType.FORCED_CHOICE, chosen_option=1),
    ]


def _phase1_answers_contradictory() -> List[BootstrapAnswer]:
    """Risk answers are mixed: some option 0, some option 1."""
    return [
        BootstrapAnswer(question_id="p1_risk_01", type=QuestionType.FORCED_CHOICE, chosen_option=0),
        BootstrapAnswer(question_id="p1_risk_02", type=QuestionType.FORCED_CHOICE, chosen_option=1),
        BootstrapAnswer(question_id="p1_risk_03", type=QuestionType.FORCED_CHOICE, chosen_option=0),
        BootstrapAnswer(question_id="p1_action_01", type=QuestionType.FORCED_CHOICE, chosen_option=1),
        BootstrapAnswer(question_id="p1_action_02", type=QuestionType.FORCED_CHOICE, chosen_option=1),
        BootstrapAnswer(question_id="p1_action_03", type=QuestionType.FORCED_CHOICE, chosen_option=1),
        BootstrapAnswer(question_id="p1_info_01", type=QuestionType.FORCED_CHOICE, chosen_option=1),
        BootstrapAnswer(question_id="p1_info_02", type=QuestionType.FORCED_CHOICE, chosen_option=1),
        BootstrapAnswer(question_id="p1_conflict_01", type=QuestionType.FORCED_CHOICE, chosen_option=1),
        BootstrapAnswer(question_id="p1_conflict_02", type=QuestionType.FORCED_CHOICE, chosen_option=1),
        BootstrapAnswer(question_id="p1_explore_01", type=QuestionType.FORCED_CHOICE, chosen_option=1),
        BootstrapAnswer(question_id="p1_explore_02", type=QuestionType.FORCED_CHOICE, chosen_option=1),
    ]


def _phase2_answers() -> List[BootstrapAnswer]:
    """Domain self-assessment: work=high, finance=medium, health=low, relationships=high, learning=medium."""
    return [
        BootstrapAnswer(question_id="p2_domain_work", type=QuestionType.FORCED_CHOICE, chosen_option=0, domain="work"),
        BootstrapAnswer(question_id="p2_domain_finance", type=QuestionType.FORCED_CHOICE, chosen_option=1, domain="finance"),
        BootstrapAnswer(question_id="p2_domain_health", type=QuestionType.FORCED_CHOICE, chosen_option=2, domain="health"),
        BootstrapAnswer(question_id="p2_domain_relationships", type=QuestionType.FORCED_CHOICE, chosen_option=0, domain="relationships"),
        BootstrapAnswer(question_id="p2_domain_learning", type=QuestionType.FORCED_CHOICE, chosen_option=1, domain="learning"),
    ]


def _phase3_answers() -> List[BootstrapAnswer]:
    """Open-scenario narrative answers."""
    return [
        BootstrapAnswer(
            question_id="p3_scenario_work",
            type=QuestionType.OPEN_SCENARIO,
            free_text="I recently decided to switch teams at work. I weighed stability vs growth and chose growth.",
        ),
        BootstrapAnswer(
            question_id="p3_scenario_life",
            type=QuestionType.OPEN_SCENARIO,
            free_text="I moved to a new city for better career prospects despite leaving friends behind.",
        ),
        BootstrapAnswer(
            question_id="p3_scenario_money",
            type=QuestionType.OPEN_SCENARIO,
            free_text="I invested in index funds instead of individual stocks after researching for a week.",
        ),
    ]


def _all_answers_consistent() -> List[BootstrapAnswer]:
    return _phase1_answers_consistent() + _phase2_answers() + _phase3_answers()


def _all_answers_contradictory() -> List[BootstrapAnswer]:
    return _phase1_answers_contradictory() + _phase2_answers() + _phase3_answers()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExtractAxes:
    def test_extract_axes(self) -> None:
        """Given answers to Phase 1, axes are correctly extracted."""
        llm = MockLLM()
        engine = BootstrapEngine(llm)
        answers = _phase1_answers_consistent()
        raw = engine._extract_axes(answers)

        assert "risk_tolerance" in raw
        assert len(raw["risk_tolerance"]) == 3
        # All chose option 1 → push = 0.5 each
        assert all(v == 0.5 for v in raw["risk_tolerance"])

        assert "action_threshold" in raw
        assert len(raw["action_threshold"]) == 3

        assert "information_threshold" in raw
        assert len(raw["information_threshold"]) == 2

        assert "conflict_style_proxy" in raw
        assert len(raw["conflict_style_proxy"]) == 2

        assert "explore_exploit_balance" in raw
        assert len(raw["explore_exploit_balance"]) == 2


class TestComputeAxisValues:
    def test_compute_axis_values(self) -> None:
        """0.5 + mean(pushes), clamped."""
        llm = MockLLM()
        engine = BootstrapEngine(llm)

        # All positive pushes of 0.5 → 0.5 + 0.5 = 1.0
        raw = {"risk_tolerance": [0.5, 0.5, 0.5]}
        vals = engine._compute_axis_values(raw)
        assert vals["risk_tolerance"] == 1.0

        # All negative pushes of -0.5 → 0.5 + (-0.5) = 0.0
        raw = {"risk_tolerance": [-0.5, -0.5, -0.5]}
        vals = engine._compute_axis_values(raw)
        assert vals["risk_tolerance"] == 0.0

        # Mixed pushes → 0.5 + mean
        raw = {"risk_tolerance": [0.5, -0.5]}
        vals = engine._compute_axis_values(raw)
        assert vals["risk_tolerance"] == 0.5

        # Clamping: extreme values
        raw = {"risk_tolerance": [0.5, 0.5, 0.5, 0.5]}
        vals = engine._compute_axis_values(raw)
        assert vals["risk_tolerance"] == 1.0  # clamped to 1.0


class TestCheckConsistency:
    def test_check_consistency_consistent(self) -> None:
        """Same-sign pushes → reliability 0.5."""
        llm = MockLLM()
        engine = BootstrapEngine(llm)

        raw = {"risk_tolerance": [0.5, 0.5, 0.5]}
        rel = engine._check_consistency(raw)
        assert rel["risk_tolerance"] == 0.5

    def test_check_consistency_contradictory(self) -> None:
        """Mixed-sign pushes → reliability 0.3."""
        llm = MockLLM()
        engine = BootstrapEngine(llm)

        raw = {"risk_tolerance": [-0.5, 0.5, -0.5]}
        rel = engine._check_consistency(raw)
        assert rel["risk_tolerance"] == 0.3

    def test_check_consistency_single_push(self) -> None:
        """Single push → 0.5 (no contradiction possible)."""
        llm = MockLLM()
        engine = BootstrapEngine(llm)

        raw = {"risk_tolerance": [0.5]}
        rel = engine._check_consistency(raw)
        assert rel["risk_tolerance"] == 0.5


class TestInferConflictStyle:
    def test_strongly_positive(self) -> None:
        """Strongly positive pushes → DIRECT."""
        llm = MockLLM()
        engine = BootstrapEngine(llm)
        raw = {"conflict_style_proxy": [0.5, 0.5]}
        assert engine._infer_conflict_style(raw) == ConflictStyle.DIRECT

    def test_strongly_negative(self) -> None:
        """Strongly negative pushes → AVOIDANT."""
        llm = MockLLM()
        engine = BootstrapEngine(llm)
        raw = {"conflict_style_proxy": [-0.5, -0.5]}
        assert engine._infer_conflict_style(raw) == ConflictStyle.AVOIDANT

    def test_mixed(self) -> None:
        """Mixed pushes → ADAPTIVE."""
        llm = MockLLM()
        engine = BootstrapEngine(llm)
        raw = {"conflict_style_proxy": [0.5, -0.5]}
        assert engine._infer_conflict_style(raw) == ConflictStyle.ADAPTIVE

    def test_no_pushes(self) -> None:
        """No conflict axis data → ADAPTIVE."""
        llm = MockLLM()
        engine = BootstrapEngine(llm)
        raw: Dict[str, List[float]] = {}
        assert engine._infer_conflict_style(raw) == ConflictStyle.ADAPTIVE


class TestBuildDomainHeads:
    def test_declared_vs_undeclared(self) -> None:
        """Declared domains with high confidence get 0.4, undeclared get 0.3."""
        llm = MockLLM()
        engine = BootstrapEngine(llm)
        answers = _phase2_answers()
        heads = engine._build_domain_heads(answers, contradicted_axes=set())

        head_map = {h.domain: h for h in heads}

        # work: chosen_option=0 → high → 0.4
        assert head_map[DomainEnum.WORK].head_reliability == 0.4
        # finance → MONEY: chosen_option=1 → medium → 0.35
        assert head_map[DomainEnum.MONEY].head_reliability == 0.35
        # health → LIFE_PLANNING: chosen_option=2 → low → 0.3
        assert head_map[DomainEnum.LIFE_PLANNING].head_reliability == 0.3
        # relationships: chosen_option=0 → high → 0.4
        assert head_map[DomainEnum.RELATIONSHIPS].head_reliability == 0.4
        # learning → PUBLIC_EXPRESSION: chosen_option=1 → medium → 0.35
        assert head_map[DomainEnum.PUBLIC_EXPRESSION].head_reliability == 0.35

    def test_contradicted_axis_downgrade(self) -> None:
        """If a domain's axis is contradicted, head_reliability downgrades to 0.3."""
        llm = MockLLM()
        engine = BootstrapEngine(llm)
        answers = _phase2_answers()
        # risk_tolerance is contradicted → affects WORK (was 0.4) and MONEY (was 0.35)
        heads = engine._build_domain_heads(
            answers, contradicted_axes={"risk_tolerance"}
        )
        head_map = {h.domain: h for h in heads}

        assert head_map[DomainEnum.WORK].head_reliability == 0.3
        assert head_map[DomainEnum.MONEY].head_reliability == 0.3
        # RELATIONSHIPS not affected by risk_tolerance
        assert head_map[DomainEnum.RELATIONSHIPS].head_reliability == 0.4


class TestValidDomainsMatchesThreshold:
    def test_valid_domains(self) -> None:
        """twin.valid_domains() returns only declared non-contradicted domains."""
        llm = _make_mock_llm()
        engine = BootstrapEngine(llm)
        result = engine.run(_all_answers_consistent(), user_id="test-user")
        twin = result.twin

        # Threshold is 0.35
        valid = twin.valid_domains()
        # work=0.4, finance(money)=0.35, relationships=0.4, learning(public_expr)=0.35
        # health(life_planning)=0.3 → excluded
        assert DomainEnum.WORK in valid
        assert DomainEnum.MONEY in valid
        assert DomainEnum.RELATIONSHIPS in valid
        assert DomainEnum.PUBLIC_EXPRESSION in valid
        assert DomainEnum.LIFE_PLANNING not in valid


class TestFullRunBuildsValidTwin:
    def test_full_run_builds_valid_twin(self) -> None:
        """Mock LLM, run full pipeline, Pydantic accepts result."""
        llm = _make_mock_llm()
        engine = BootstrapEngine(llm)
        result = engine.run(_all_answers_consistent(), user_id="test-user")

        # Result is a valid BootstrapResult
        assert isinstance(result, BootstrapResult)
        assert isinstance(result.twin, object)  # Pydantic validated

        twin = result.twin
        assert twin.user_id == "test-user"
        assert twin.state_version == "v000-bootstrap"
        assert twin.active is True
        assert len(twin.domain_heads) == len(DomainEnum)
        assert len(twin.reliability_profile) == len(DomainEnum)

        # Axis reliability populated
        assert len(result.axis_reliability) > 0

    def test_full_run_contradictory(self) -> None:
        """Full run with contradictory answers still produces valid twin."""
        llm = _make_mock_llm()
        engine = BootstrapEngine(llm)
        result = engine.run(_all_answers_contradictory(), user_id="test-user-2")

        twin = result.twin
        assert twin.state_version == "v000-bootstrap"
        # risk_tolerance should be contradicted → 0.3
        assert result.axis_reliability["risk_tolerance"] == 0.3


class TestExperienceCount:
    def test_experience_count(self) -> None:
        """~5 principles + ~3 narratives (1 per open scenario) = ~8 entries."""
        llm = _make_mock_llm()
        engine = BootstrapEngine(llm)
        result = engine.run(_all_answers_consistent(), user_id="test-user")

        lib = result.experience_library
        principles = [e for e in lib.entries if e.entry_kind == "principle"]
        narratives = [e for e in lib.entries if e.entry_kind == "narrative"]

        assert len(principles) == 5
        assert len(narratives) == 3  # 1 per open scenario
        assert lib.size == 8

        # Check weights
        for p in principles:
            assert p.weight == 0.9
        for n in narratives:
            assert n.weight == 0.8


class TestScopeThreshold:
    def test_scope_threshold(self) -> None:
        """scope_declaration.min_reliability_threshold == 0.35."""
        llm = _make_mock_llm()
        engine = BootstrapEngine(llm)
        result = engine.run(_all_answers_consistent(), user_id="test-user")

        assert result.twin.scope_declaration.min_reliability_threshold == 0.35
        assert "Bootstrap-provisional" in result.twin.scope_declaration.user_facing_summary


class TestFailLoud:
    def test_slider_answer_rejected(self) -> None:
        """SLIDER answers should raise ValueError."""
        llm = _make_mock_llm()
        engine = BootstrapEngine(llm)
        answers = [
            BootstrapAnswer(
                question_id="q1", type=QuestionType.SLIDER,
                slider_value=0.8, tags=["risk"],
            ),
        ]
        with pytest.raises(ValueError, match="SLIDER.*not yet supported"):
            engine.run(answers, user_id="test-user")

    def test_custom_domain_rejected(self) -> None:
        """Custom domain not in DomainEnum should raise ValueError at init."""
        from twin_runtime.application.bootstrap.questions import BootstrapQuestion

        bad_questions = [
            BootstrapQuestion(
                id="custom-q1", phase=2, type=QuestionType.FORCED_CHOICE,
                question="How good?", options=["Good", "Bad"],
                domain="alien_domain", tags=["alien"],
            ),
        ]
        llm = _make_mock_llm()
        with pytest.raises(ValueError, match="not a valid DomainEnum"):
            BootstrapEngine(llm, questions=bad_questions)

    def test_duplicate_question_id_rejected(self) -> None:
        from twin_runtime.application.bootstrap.questions import BootstrapQuestion

        qs = [
            BootstrapQuestion(id="dup", phase=1, type=QuestionType.FORCED_CHOICE,
                              question="Q1?", options=["A", "B"],
                              axes={"risk_tolerance": [-0.5, 0.5]}),
            BootstrapQuestion(id="dup", phase=1, type=QuestionType.FORCED_CHOICE,
                              question="Q2?", options=["C", "D"],
                              axes={"action_threshold": [-0.5, 0.5]}),
        ]
        with pytest.raises(ValueError, match="Duplicate question ID"):
            BootstrapEngine(_make_mock_llm(), questions=qs)

    def test_forced_choice_no_options_rejected(self) -> None:
        from twin_runtime.application.bootstrap.questions import BootstrapQuestion

        qs = [
            BootstrapQuestion(id="no-opts", phase=1, type=QuestionType.FORCED_CHOICE,
                              question="Pick?", options=[],
                              axes={"risk_tolerance": []}),
        ]
        with pytest.raises(ValueError, match="has no options"):
            BootstrapEngine(_make_mock_llm(), questions=qs)

    def test_axes_push_count_mismatch_rejected(self) -> None:
        from twin_runtime.application.bootstrap.questions import BootstrapQuestion

        qs = [
            BootstrapQuestion(id="bad-axes", phase=1, type=QuestionType.FORCED_CHOICE,
                              question="Pick?", options=["A", "B", "C"],
                              axes={"risk_tolerance": [-0.5, 0.5]}),  # 2 pushes, 3 options
        ]
        with pytest.raises(ValueError, match="pushes.*options.*must match"):
            BootstrapEngine(_make_mock_llm(), questions=qs)

    def test_phase1_no_axes_rejected(self) -> None:
        from twin_runtime.application.bootstrap.questions import BootstrapQuestion

        qs = [
            BootstrapQuestion(id="no-axes", phase=1, type=QuestionType.FORCED_CHOICE,
                              question="Pick?", options=["A", "B"],
                              axes={}),  # Phase 1 requires axes
        ]
        with pytest.raises(ValueError, match="Phase 1.*no axes"):
            BootstrapEngine(_make_mock_llm(), questions=qs)

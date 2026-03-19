"""Tests for comparison runners."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from twin_runtime.application.comparison.runners.vanilla import (
    VanillaRunner,
    _build_user_prompt,
    _fuzzy_match,
    parse_choice,
)
from twin_runtime.application.comparison.runners.persona import (
    PersonaRunner,
    build_persona_system_prompt,
)
from twin_runtime.application.comparison.runners.rag_persona import RagPersonaRunner
from twin_runtime.application.comparison.runners.twin_runner import (
    TwinRunner,
    _extract_chosen,
    _is_refusal,
)
from twin_runtime.application.comparison.schemas import ComparisonScenario


def _make_scenario(**kwargs):
    defaults = dict(
        scenario_id="t1",
        domain="work",
        query="Should I take the job?",
        options=["Accept", "Decline"],
        ground_truth="Accept",
    )
    defaults.update(kwargs)
    return ComparisonScenario(**defaults)


class TestBuildUserPrompt:
    def test_includes_query_and_options(self):
        prompt = _build_user_prompt("Pick one", ["A", "B"])
        assert "Pick one" in prompt
        assert "- A" in prompt
        assert "- B" in prompt
        assert '{"chosen"' in prompt


class TestParseChoice:
    def test_json_parse(self):
        assert parse_choice('{"chosen": "Accept"}', ["Accept", "Decline"]) == "Accept"

    def test_json_with_extra_text(self):
        raw = 'Here is my answer: {"chosen": "Decline"}'
        # json.loads will fail, but fuzzy match should find "Decline"
        assert parse_choice(raw, ["Accept", "Decline"]) == "Decline"

    def test_fuzzy_match(self):
        assert parse_choice("I would Accept the offer", ["Accept", "Decline"]) == "Accept"

    def test_fallback_to_first(self):
        assert parse_choice("no clear match here", ["Alpha", "Beta"]) == "Alpha"

    def test_json_value_fuzzy_matched(self):
        raw = '{"chosen": "accept the job"}'
        # "accept the job" not in options, but "Accept" is a substring? No.
        # Actually fuzzy checks if option.lower() in text.lower()
        # "accept" in "accept the job" -> yes
        assert parse_choice(raw, ["Accept", "Decline"]) == "Accept"


class TestFuzzyMatch:
    def test_exact_substring(self):
        assert _fuzzy_match("I choose Accept", ["Accept", "Decline"]) == "Accept"

    def test_case_insensitive(self):
        assert _fuzzy_match("i choose accept", ["Accept", "Decline"]) == "Accept"

    def test_no_match(self):
        assert _fuzzy_match("something else", ["Accept", "Decline"]) is None


class TestVanillaRunner:
    def test_runner_id(self):
        llm = MagicMock()
        r = VanillaRunner(llm)
        assert r.runner_id == "vanilla"

    def test_run_scenario_correct(self):
        llm = MagicMock()
        llm.ask_text.return_value = '{"chosen": "Accept"}'
        r = VanillaRunner(llm)
        scenario = _make_scenario()
        twin = MagicMock()
        out = r.run_scenario(scenario, twin)
        assert out.chosen == "Accept"
        assert out.is_correct is True
        assert out.runner_id == "vanilla"
        assert out.latency_ms >= 0

    def test_run_scenario_incorrect(self):
        llm = MagicMock()
        llm.ask_text.return_value = '{"chosen": "Decline"}'
        r = VanillaRunner(llm)
        scenario = _make_scenario()
        twin = MagicMock()
        out = r.run_scenario(scenario, twin)
        assert out.chosen == "Decline"
        assert out.is_correct is False

    def test_run_scenario_with_fallback(self):
        llm = MagicMock()
        llm.ask_text.return_value = "I think you should Accept this opportunity"
        r = VanillaRunner(llm)
        scenario = _make_scenario()
        twin = MagicMock()
        out = r.run_scenario(scenario, twin)
        assert out.chosen == "Accept"


class TestBuildPersonaPrompt:
    def test_no_raw_numbers(self, sample_twin):
        prompt = build_persona_system_prompt(sample_twin)
        # Should contain labels like "moderate", "high", "low" but NOT raw floats
        assert "risk tolerance" in prompt
        assert "conflict style" in prompt
        # No raw axis numbers should appear (e.g. "0.72")
        import re
        floats = re.findall(r"\b0\.\d+\b", prompt)
        assert floats == [], f"Found raw numbers in prompt: {floats}"

    def test_includes_domains(self, sample_twin):
        prompt = build_persona_system_prompt(sample_twin)
        assert "work" in prompt.lower()

    def test_includes_control_orientation(self, sample_twin):
        prompt = build_persona_system_prompt(sample_twin)
        assert "control orientation" in prompt


class TestPersonaRunner:
    def test_runner_id(self):
        llm = MagicMock()
        r = PersonaRunner(llm)
        assert r.runner_id == "persona"

    def test_run_uses_persona_system(self, sample_twin):
        llm = MagicMock()
        llm.ask_text.return_value = '{"chosen": "Accept"}'
        r = PersonaRunner(llm)
        scenario = _make_scenario()
        out = r.run_scenario(scenario, sample_twin)
        assert out.is_correct is True
        # Verify system prompt was persona-based
        call_args = llm.ask_text.call_args
        system = call_args[0][0]
        assert "decision-making twin" in system


class TestRagPersonaRunner:
    def test_runner_id(self):
        llm = MagicMock()
        store = MagicMock()
        r = RagPersonaRunner(llm, store)
        assert r.runner_id == "rag_persona"

    def test_degradation_when_empty_store(self, sample_twin):
        llm = MagicMock()
        llm.ask_text.return_value = '{"chosen": "Accept"}'
        store = MagicMock()
        store.query.return_value = []
        r = RagPersonaRunner(llm, store)
        scenario = _make_scenario()
        out = r.run_scenario(scenario, sample_twin)
        assert out.notes == "degraded:no_evidence"
        assert out.is_correct is True

    def test_evidence_included_in_prompt(self, sample_twin):
        llm = MagicMock()
        llm.ask_text.return_value = '{"chosen": "Accept"}'
        frag = MagicMock()
        frag.summary = "User previously chose stability over risk"
        store = MagicMock()
        store.query.return_value = [frag]
        r = RagPersonaRunner(llm, store)
        scenario = _make_scenario()
        out = r.run_scenario(scenario, sample_twin)
        assert out.notes == ""
        call_args = llm.ask_text.call_args
        system = call_args[0][0]
        assert "stability over risk" in system


class TestExtractChosen:
    def test_recommended_format(self):
        trace = MagicMock()
        trace.final_decision = "Recommended: Accept (over Decline)"
        assert _extract_chosen(trace, ["Accept", "Decline"]) == "Accept"

    def test_plain_text(self):
        trace = MagicMock()
        trace.final_decision = "I recommend you Accept this opportunity."
        assert _extract_chosen(trace, ["Accept", "Decline"]) == "Accept"

    def test_fallback_first_option(self):
        trace = MagicMock()
        trace.final_decision = "No clear match"
        assert _extract_chosen(trace, ["Alpha", "Beta"]) == "Alpha"


class TestIsRefusal:
    def test_refused_mode(self):
        trace = MagicMock()
        trace.decision_mode.value = "refused"
        trace.refusal_reason_code = None
        assert _is_refusal(trace) is True

    def test_degraded_mode_is_not_refusal(self):
        """DEGRADED still produces a decision (weak signal) — not a true refusal."""
        trace = MagicMock()
        trace.decision_mode.value = "degraded"
        trace.refusal_reason_code = None
        assert _is_refusal(trace) is False

    def test_direct_with_refusal_code(self):
        trace = MagicMock()
        trace.decision_mode.value = "direct"
        trace.refusal_reason_code = "OUT_OF_SCOPE"
        assert _is_refusal(trace) is True

    def test_direct_normal(self):
        trace = MagicMock()
        trace.decision_mode.value = "direct"
        trace.refusal_reason_code = None
        assert _is_refusal(trace) is False


class TestTwinRunner:
    def test_runner_id(self):
        r = TwinRunner()
        assert r.runner_id == "twin"

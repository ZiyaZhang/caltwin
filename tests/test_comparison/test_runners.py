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

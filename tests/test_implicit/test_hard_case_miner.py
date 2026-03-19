"""Tests for HardCaseMiner — systematic failure pattern detection."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from twin_runtime.application.calibration.hard_case_miner import HardCaseMiner
from twin_runtime.domain.models.calibration import OutcomeRecord
from twin_runtime.domain.models.primitives import (
    DecisionMode,
    DomainEnum,
    OutcomeSource,
)
from twin_runtime.domain.models.runtime import HeadAssessment, RuntimeDecisionTrace


def _make_trace(trace_id: str, query: str = "test query") -> RuntimeDecisionTrace:
    return RuntimeDecisionTrace(
        trace_id=trace_id,
        twin_state_version="v1",
        situation_frame_id="f1",
        activated_domains=[DomainEnum.WORK],
        head_assessments=[
            HeadAssessment(
                domain=DomainEnum.WORK,
                head_version="1.0",
                option_ranking=["A", "B"],
                utility_decomposition={"x": 0.5},
                confidence=0.7,
            )
        ],
        final_decision="A",
        decision_mode=DecisionMode.DIRECT,
        uncertainty=0.3,
        option_set=["A", "B"],
        query=query,
        created_at=datetime.now(timezone.utc),
    )


def _make_outcome(
    trace_id: str,
    domain: DomainEnum = DomainEnum.WORK,
    prediction_rank: int = 2,
    actual_choice: str = "B",
) -> OutcomeRecord:
    return OutcomeRecord(
        outcome_id=f"o-{trace_id}",
        trace_id=trace_id,
        user_id="test",
        actual_choice=actual_choice,
        outcome_source=OutcomeSource.USER_CORRECTION,
        prediction_rank=prediction_rank,
        confidence_at_prediction=0.7,
        domain=domain,
        created_at=datetime.now(timezone.utc),
    )


def test_insufficient_failures():
    """Fewer than min_failures → empty result."""
    llm = MagicMock()
    miner = HardCaseMiner(llm, min_failures=3)

    traces = [_make_trace("t1"), _make_trace("t2")]
    outcomes = [_make_outcome("t1"), _make_outcome("t2")]

    patterns = miner.mine(traces, outcomes)
    assert patterns == []
    llm.ask_json.assert_not_called()


def test_group_by_domain():
    """Failures are grouped by domain (P2: independent grouping)."""
    llm = MagicMock()
    llm.ask_json.return_value = {
        "pattern_description": "test pattern",
        "systematic_bias": "test bias",
        "correction_strategy": "test correction",
    }
    miner = HardCaseMiner(llm, min_failures=2)

    traces = [_make_trace(f"t{i}") for i in range(4)]
    outcomes = [
        _make_outcome("t0", domain=DomainEnum.WORK),
        _make_outcome("t1", domain=DomainEnum.WORK),
        _make_outcome("t2", domain=DomainEnum.MONEY),
        _make_outcome("t3", domain=DomainEnum.MONEY),
    ]

    patterns = miner.mine(traces, outcomes)
    assert len(patterns) == 2
    domains = {p.domains[0] for p in patterns}
    assert domains == {DomainEnum.WORK, DomainEnum.MONEY}


def test_single_domain_pattern():
    """Mock LLM → PatternInsight fields complete."""
    llm = MagicMock()
    llm.ask_json.return_value = {
        "pattern_description": "Tends to over-weight stability",
        "systematic_bias": "Status quo bias",
        "correction_strategy": "Add exploration bonus",
    }
    miner = HardCaseMiner(llm, min_failures=2)

    traces = [_make_trace("t1", "use Redis?"), _make_trace("t2", "use Postgres?")]
    outcomes = [_make_outcome("t1"), _make_outcome("t2")]

    patterns = miner.mine(traces, outcomes)
    assert len(patterns) == 1
    p = patterns[0]
    assert p.pattern_description == "Tends to over-weight stability"
    assert p.systematic_bias == "Status quo bias"
    assert p.correction_strategy == "Add exploration bonus"
    assert p.affected_trace_ids == ["t1", "t2"]


def test_uses_llm_port_ask_json():
    """Verify LLM called via ask_json (#5)."""
    llm = MagicMock()
    llm.ask_json.return_value = {
        "pattern_description": "p",
        "systematic_bias": "b",
        "correction_strategy": "c",
    }
    miner = HardCaseMiner(llm, min_failures=2)

    traces = [_make_trace("t1"), _make_trace("t2")]
    outcomes = [_make_outcome("t1"), _make_outcome("t2")]
    miner.mine(traces, outcomes)

    llm.ask_json.assert_called_once()


def test_weight_is_2():
    """PatternInsight weight should be 2.0."""
    llm = MagicMock()
    llm.ask_json.return_value = {
        "pattern_description": "p",
        "systematic_bias": "b",
        "correction_strategy": "c",
    }
    miner = HardCaseMiner(llm, min_failures=2)

    traces = [_make_trace("t1"), _make_trace("t2")]
    outcomes = [_make_outcome("t1"), _make_outcome("t2")]
    patterns = miner.mine(traces, outcomes)

    assert patterns[0].weight == 2.0


def test_hits_excluded():
    """Outcomes with prediction_rank == 1 are not failures."""
    llm = MagicMock()
    miner = HardCaseMiner(llm, min_failures=2)

    traces = [_make_trace("t1"), _make_trace("t2"), _make_trace("t3")]
    outcomes = [
        _make_outcome("t1", prediction_rank=1),  # hit
        _make_outcome("t2", prediction_rank=2),  # miss
        _make_outcome("t3", prediction_rank=1),  # hit
    ]

    patterns = miner.mine(traces, outcomes)
    assert patterns == []  # Only 1 failure, below min_failures=2


def test_none_domain_skipped():
    """Outcomes with domain=None are skipped (Issue 7).

    OutcomeRecord.domain is typed as DomainEnum (required), so None is not
    normally possible. We test the defensive guard by monkey-patching.
    """
    llm = MagicMock()
    miner = HardCaseMiner(llm, min_failures=2)

    traces = [_make_trace("t1"), _make_trace("t2")]
    outcomes = [_make_outcome("t1"), _make_outcome("t2")]
    # Simulate corrupted/legacy data where domain is None
    for o in outcomes:
        object.__setattr__(o, "domain", None)

    patterns = miner.mine(traces, outcomes)
    assert patterns == []
    llm.ask_json.assert_not_called()


# ---------------------------------------------------------------------------
# Counter tests
# ---------------------------------------------------------------------------

def test_counter_increment(tmp_path):
    """Reflect counter increments by 1."""
    from unittest.mock import patch
    from twin_runtime.cli._calibration import _increment_reflect_counter

    with patch("twin_runtime.cli._calibration._STORE_DIR", tmp_path):
        (tmp_path / "test").mkdir()
        assert _increment_reflect_counter("test") == 1
        assert _increment_reflect_counter("test") == 2
        assert _increment_reflect_counter("test") == 3


def test_counter_triggers_at_20(tmp_path):
    """Counter reaches 20 → should trigger mining."""
    from unittest.mock import patch
    from twin_runtime.cli._calibration import _increment_reflect_counter

    with patch("twin_runtime.cli._calibration._STORE_DIR", tmp_path):
        (tmp_path / "test").mkdir()
        counter_path = tmp_path / "test" / "reflect_count"
        counter_path.write_text("19")
        count = _increment_reflect_counter("test")
        assert count == 20


def test_counter_resets_after_mine(tmp_path):
    """Counter resets to 0 after mining."""
    from unittest.mock import patch
    from twin_runtime.cli._calibration import _increment_reflect_counter, _reset_reflect_counter

    with patch("twin_runtime.cli._calibration._STORE_DIR", tmp_path):
        (tmp_path / "test").mkdir()
        counter_path = tmp_path / "test" / "reflect_count"
        counter_path.write_text("19")
        _increment_reflect_counter("test")
        _reset_reflect_counter("test")
        assert counter_path.read_text() == "0"

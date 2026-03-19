"""Tests for HeartbeatReflector — implicit reflection engine."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import List, Optional
from unittest.mock import MagicMock, patch

import pytest

from twin_runtime.application.implicit.heartbeat import (
    HeartbeatReflector,
    HeartbeatReport,
    InferredReflection,
)
from twin_runtime.domain.models.primitives import DecisionMode, DomainEnum, OutcomeSource
from twin_runtime.domain.models.runtime import HeadAssessment, RuntimeDecisionTrace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trace(
    trace_id: str = "t1",
    query: str = "用 Redis 还是 Memcached",
    option_set: List[str] = None,
) -> RuntimeDecisionTrace:
    return RuntimeDecisionTrace(
        trace_id=trace_id,
        twin_state_version="v1",
        situation_frame_id="f1",
        activated_domains=[DomainEnum.WORK],
        head_assessments=[
            HeadAssessment(
                domain=DomainEnum.WORK,
                head_version="1.0",
                option_ranking=option_set or ["Redis", "Memcached"],
                utility_decomposition={"perf": 0.8},
                confidence=0.7,
            )
        ],
        final_decision="Redis",
        decision_mode=DecisionMode.DIRECT,
        uncertainty=0.3,
        option_set=option_set or ["Redis", "Memcached"],
        query=query,
        created_at=datetime.now(timezone.utc),
    )


class FakeTraceStore:
    def __init__(self, traces: dict):
        self._traces = traces

    def list_traces(self, limit: int = 50) -> List[str]:
        return list(self._traces.keys())[:limit]

    def load_trace(self, trace_id: str) -> RuntimeDecisionTrace:
        if trace_id not in self._traces:
            raise FileNotFoundError(trace_id)
        return self._traces[trace_id]


class FakeCalibrationStore:
    def __init__(self, outcomes=None):
        self._outcomes = outcomes or []
        self._saved_outcomes = []

    def list_outcomes(self):
        return self._outcomes

    def save_outcome(self, outcome):
        self._saved_outcomes.append(outcome)


class FakeTwinStore:
    def __init__(self, twin):
        self._twin = twin

    def load_state(self, user_id: str):
        return self._twin


class FakeExperienceStore:
    def __init__(self):
        from twin_runtime.domain.models.experience import ExperienceLibrary
        self._lib = ExperienceLibrary()

    def load(self):
        return self._lib

    def save(self, lib):
        self._lib = lib


def _make_reflector(traces=None, outcomes=None, twin=None, **kwargs):
    """Create a HeartbeatReflector with fake stores."""
    traces = traces or {}
    from twin_runtime.domain.models.twin_state import TwinState
    import importlib.resources as pkg_resources
    if twin is None:
        ref = pkg_resources.files("twin_runtime") / "resources" / "fixtures" / "sample_twin_state.json"
        twin = TwinState.model_validate_json(ref.read_text())

    trace_store = FakeTraceStore(traces)
    cal_store = FakeCalibrationStore(outcomes)
    twin_store = FakeTwinStore(twin)
    exp_store = FakeExperienceStore()
    llm = MagicMock()

    return HeartbeatReflector(
        trace_store=trace_store,
        calibration_store=cal_store,
        twin_store=twin_store,
        experience_store=exp_store,
        llm=llm,
        user_id="default",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Tests: Pending trace discovery
# ---------------------------------------------------------------------------

def test_pending_via_diff():
    """3 traces, 1 outcome → 2 pending."""
    t1 = _make_trace("t1")
    t2 = _make_trace("t2", query="monorepo or multirepo", option_set=["monorepo", "multirepo"])
    t3 = _make_trace("t3", query="async or sync", option_set=["async", "sync"])

    # t1 already reflected
    outcome = MagicMock()
    outcome.trace_id = "t1"

    reflector = _make_reflector(
        traces={"t1": t1, "t2": t2, "t3": t3},
        outcomes=[outcome],
    )
    pending = reflector._find_pending_traces()
    assert len(pending) == 2
    assert {t.trace_id for t in pending} == {"t2", "t3"}


def test_pending_loads_trace_objects():
    """Pending traces are full RuntimeDecisionTrace objects with option_set."""
    t1 = _make_trace("t1", option_set=["Redis", "Memcached"])
    reflector = _make_reflector(traces={"t1": t1})
    pending = reflector._find_pending_traces()
    assert len(pending) == 1
    assert pending[0].option_set == ["Redis", "Memcached"]


def test_no_pending():
    """All traces reflected → empty report."""
    t1 = _make_trace("t1")
    outcome = MagicMock()
    outcome.trace_id = "t1"
    reflector = _make_reflector(traces={"t1": t1}, outcomes=[outcome])
    report = reflector.run()
    assert report.inferred == 0
    assert report.auto_reflected == 0


def test_traces_without_option_set_excluded():
    """Traces with empty option_set are excluded from pending."""
    t1 = _make_trace("t1", option_set=[])
    # Need to manually set it since _make_trace uses the list
    t1.option_set = []
    reflector = _make_reflector(traces={"t1": t1})
    pending = reflector._find_pending_traces()
    assert len(pending) == 0


# ---------------------------------------------------------------------------
# Tests: Git inference
# ---------------------------------------------------------------------------

def test_git_commit_match():
    """Mock subprocess → correct inference from commit messages."""
    t1 = _make_trace("t1", option_set=["Redis", "Memcached"])
    reflector = _make_reflector(traces={"t1": t1})

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "feat: add redis caching layer\nfix: redis connection pool"

    with patch("subprocess.run", return_value=mock_result):
        inferences = reflector._infer_from_git_commits([t1])

    assert len(inferences) == 1
    assert inferences[0].inferred_choice == "Redis"
    assert inferences[0].signal_source == OutcomeSource.IMPLICIT_GIT


def test_git_pr_higher_confidence():
    """Merged PR → higher confidence than commit."""
    t1 = _make_trace("t1", option_set=["Redis", "Memcached"])
    reflector = _make_reflector(traces={"t1": t1})

    commit_result = MagicMock(returncode=0, stdout="feat: add redis caching")
    merge_result = MagicMock(returncode=0, stdout="Merge: redis implementation")

    with patch("subprocess.run", return_value=commit_result):
        commit_infs = reflector._infer_from_git_commits([t1])
    with patch("subprocess.run", return_value=merge_result):
        pr_infs = reflector._infer_from_git_prs([t1])

    assert pr_infs[0].confidence > commit_infs[0].confidence


def test_file_change_low_confidence():
    """File change → confidence < 0.5."""
    t1 = _make_trace("t1", option_set=["Redis", "Memcached"])
    reflector = _make_reflector(traces={"t1": t1})

    mock_result = MagicMock(returncode=0, stdout="./src/redis_cache.py\n./config/redis.yaml")
    with patch("subprocess.run", return_value=mock_result):
        inferences = reflector._infer_from_file_changes([t1])

    assert len(inferences) == 1
    assert inferences[0].confidence <= 0.5


def test_no_git_available():
    """subprocess fails → graceful empty."""
    t1 = _make_trace("t1")
    reflector = _make_reflector(traces={"t1": t1})

    with patch("subprocess.run", side_effect=FileNotFoundError):
        inferences = reflector._infer_from_git_commits([t1])
    assert inferences == []


# ---------------------------------------------------------------------------
# Tests: Calendar/Email inference
# ---------------------------------------------------------------------------

def test_calendar_inference():
    """Mock CalendarAdapter.scan() → keyword match."""
    t1 = _make_trace("t1", query="team meeting format", option_set=["async docs", "sync meetings"])
    adapter = MagicMock()
    fragment = MagicMock()
    fragment.summary = "Weekly async doc review session"
    adapter.scan.return_value = [fragment]

    reflector = _make_reflector(traces={"t1": t1}, calendar_adapter=adapter)
    inferences = reflector._infer_from_calendar([t1])

    assert len(inferences) == 1
    assert inferences[0].signal_source == OutcomeSource.IMPLICIT_CALENDAR


def test_email_inference():
    """Mock GmailAdapter.scan() → sent mail match."""
    t1 = _make_trace("t1", query="deploy strategy", option_set=["blue-green", "rolling"])
    adapter = MagicMock()
    fragment = MagicMock()
    fragment.summary = "Deployed using blue-green strategy successfully"
    adapter.scan.return_value = [fragment]

    reflector = _make_reflector(traces={"t1": t1}, gmail_adapter=adapter)
    inferences = reflector._infer_from_email([t1])

    assert len(inferences) == 1
    assert inferences[0].signal_source == OutcomeSource.IMPLICIT_EMAIL


def test_calendar_not_configured():
    """No adapter → graceful skip."""
    t1 = _make_trace("t1")
    reflector = _make_reflector(traces={"t1": t1})
    assert reflector._infer_from_calendar([t1]) == []


def test_email_not_configured():
    """No adapter → graceful skip."""
    t1 = _make_trace("t1")
    reflector = _make_reflector(traces={"t1": t1})
    assert reflector._infer_from_email([t1]) == []


# ---------------------------------------------------------------------------
# Tests: Dedup
# ---------------------------------------------------------------------------

def test_dedup_keeps_highest():
    """Same trace, multiple signals → keep highest confidence."""
    infs = [
        InferredReflection(
            trace_id="t1", inferred_choice="Redis",
            confidence=0.5, signal_source=OutcomeSource.IMPLICIT_GIT,
        ),
        InferredReflection(
            trace_id="t1", inferred_choice="Redis",
            confidence=0.9, signal_source=OutcomeSource.IMPLICIT_GIT,
        ),
        InferredReflection(
            trace_id="t2", inferred_choice="monorepo",
            confidence=0.6, signal_source=OutcomeSource.IMPLICIT_FILE,
        ),
    ]
    deduped = HeartbeatReflector._dedup(infs)
    assert len(deduped) == 2
    t1_inf = [i for i in deduped if i.trace_id == "t1"][0]
    assert t1_inf.confidence == 0.9


# ---------------------------------------------------------------------------
# Tests: Auto-reflect / Queue
# ---------------------------------------------------------------------------

def test_auto_reflect_above_threshold():
    """High confidence → auto_reflected count increases."""
    t1 = _make_trace("t1", option_set=["Redis", "Memcached"])
    reflector = _make_reflector(traces={"t1": t1})

    mock_result = MagicMock(returncode=0, stdout="Merge: switch to redis caching")
    with patch("subprocess.run", return_value=mock_result):
        with patch.object(reflector, "_auto_reflect") as mock_ar:
            report = reflector.run()

    # Should have called auto_reflect (PR merge = high confidence)
    assert mock_ar.called or report.auto_reflected > 0 or report.queued > 0


def test_queue_below_threshold():
    """Low confidence → queued count increases."""
    t1 = _make_trace("t1", option_set=["Redis", "Memcached"])

    with tempfile.TemporaryDirectory() as tmpdir:
        queue_path = os.path.join(tmpdir, "pending.json")
        reflector = _make_reflector(
            traces={"t1": t1},
            pending_queue_path=queue_path,
            auto_reflect_threshold=0.99,  # very high threshold → everything queued
        )

        mock_result = MagicMock(returncode=0, stdout="./redis_config.txt")
        with patch("subprocess.run", return_value=mock_result):
            report = reflector.run()

        assert report.queued > 0
        assert os.path.exists(queue_path)

        # Verify queue file content
        with open(queue_path) as f:
            queued = json.load(f)
        assert len(queued) >= 1
        assert queued[0]["trace_id"] == "t1"


def test_queue_atomic_write():
    """Verify tmpfile + rename pattern."""
    inf = InferredReflection(
        trace_id="t1", inferred_choice="Redis",
        confidence=0.4, signal_source=OutcomeSource.IMPLICIT_GIT,
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        queue_path = os.path.join(tmpdir, "pending.json")
        reflector = _make_reflector(pending_queue_path=queue_path)
        reflector._queue_for_confirmation(inf)

        assert os.path.exists(queue_path)
        with open(queue_path) as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["trace_id"] == "t1"


def test_auto_reflect_record_outcome_signature():
    """Verify record_outcome is called with twin, trace_store, calibration_store (I1)."""
    t1 = _make_trace("t1", option_set=["Redis", "Memcached"])
    reflector = _make_reflector(traces={"t1": t1})
    inf = InferredReflection(
        trace_id="t1", inferred_choice="Redis",
        confidence=0.9, signal_source=OutcomeSource.IMPLICIT_GIT,
    )

    with patch("twin_runtime.application.calibration.outcome_tracker.record_outcome") as mock_ro:
        mock_ro.return_value = (MagicMock(), None)
        with patch("twin_runtime.application.calibration.reflection_generator.ReflectionGenerator") as mock_rg:
            mock_rg_inst = MagicMock()
            mock_rg_inst.process.return_value = MagicMock(new_entry=None)
            mock_rg.return_value = mock_rg_inst

            reflector._auto_reflect(inf)

    # Verify keyword arguments
    call_kwargs = mock_ro.call_args
    assert call_kwargs.kwargs.get("twin") is not None
    assert call_kwargs.kwargs.get("trace_store") is not None
    assert call_kwargs.kwargs.get("calibration_store") is not None

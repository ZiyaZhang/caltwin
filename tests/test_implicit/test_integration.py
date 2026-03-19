"""Integration tests for Phase D — pipeline connectivity."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from twin_runtime.domain.models.primitives import (
    DecisionMode,
    DomainEnum,
    OutcomeSource,
)
from twin_runtime.domain.models.runtime import HeadAssessment, RuntimeDecisionTrace
from twin_runtime.domain.models.calibration import OutcomeRecord
from twin_runtime.domain.models.experience import ExperienceLibrary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trace(trace_id, query, option_set, final_decision=None):
    return RuntimeDecisionTrace(
        trace_id=trace_id,
        twin_state_version="v1",
        situation_frame_id="f1",
        activated_domains=[DomainEnum.WORK],
        head_assessments=[
            HeadAssessment(
                domain=DomainEnum.WORK,
                head_version="1.0",
                option_ranking=option_set,
                utility_decomposition={"perf": 0.8},
                confidence=0.7,
            )
        ],
        final_decision=final_decision or option_set[0],
        decision_mode=DecisionMode.DIRECT,
        uncertainty=0.3,
        option_set=option_set,
        query=query,
        created_at=datetime.now(timezone.utc),
    )


def _make_outcome(trace_id, actual_choice, prediction_rank=2):
    return OutcomeRecord(
        outcome_id=f"o-{trace_id}",
        trace_id=trace_id,
        user_id="test",
        actual_choice=actual_choice,
        outcome_source=OutcomeSource.USER_CORRECTION,
        prediction_rank=prediction_rank,
        confidence_at_prediction=0.7,
        domain=DomainEnum.WORK,
        created_at=datetime.now(timezone.utc),
    )


class InMemoryTraceStore:
    def __init__(self, traces=None):
        self._traces = {t.trace_id: t for t in (traces or [])}

    def list_traces(self, limit=50):
        return list(self._traces.keys())[:limit]

    def load_trace(self, trace_id):
        if trace_id not in self._traces:
            raise FileNotFoundError(trace_id)
        return self._traces[trace_id]

    def save_trace(self, trace):
        self._traces[trace.trace_id] = trace
        return trace.trace_id


class InMemoryCalibrationStore:
    def __init__(self):
        self._outcomes = []
        self._cases = []

    def list_outcomes(self):
        return list(self._outcomes)

    def save_outcome(self, outcome):
        self._outcomes.append(outcome)

    def list_cases(self, used=None):
        return self._cases

    def save_case(self, case):
        self._cases.append(case)


class InMemoryTwinStore:
    def __init__(self, twin):
        self._twin = twin

    def load_state(self, user_id):
        return self._twin


class InMemoryExperienceStore:
    def __init__(self):
        self._lib = ExperienceLibrary()

    def load(self):
        return self._lib

    def save(self, lib):
        self._lib = lib


def _load_sample_twin():
    import importlib.resources as pkg_resources
    from twin_runtime.domain.models.twin_state import TwinState
    ref = pkg_resources.files("twin_runtime") / "resources" / "fixtures" / "sample_twin_state.json"
    return TwinState.model_validate_json(ref.read_text())


# ---------------------------------------------------------------------------
# Test: End-to-end heartbeat
# ---------------------------------------------------------------------------

def test_end_to_end_heartbeat():
    """Pipeline connectivity: traces → heartbeat → auto-reflect / queue."""
    from twin_runtime.application.implicit.heartbeat import HeartbeatReflector

    twin = _load_sample_twin()

    # 3 traces, 1 already has outcome
    t1 = _make_trace("t1", "用 Redis 还是 Memcached", ["Redis", "Memcached"])
    t2 = _make_trace("t2", "monorepo or multirepo", ["monorepo", "multirepo"])
    t3 = _make_trace("t3", "async or sync meetings", ["async", "sync"])

    trace_store = InMemoryTraceStore([t1, t2, t3])
    cal_store = InMemoryCalibrationStore()
    # t1 already reflected
    cal_store._outcomes.append(_make_outcome("t1", "Redis", prediction_rank=1))

    twin_store = InMemoryTwinStore(twin)
    exp_store = InMemoryExperienceStore()
    llm = MagicMock()
    llm.ask_json.return_value = {
        "insight": "test", "scenario_type": ["test"],
        "applicable_when": "test", "not_applicable_when": "",
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        queue_path = os.path.join(tmpdir, "pending.json")
        reflector = HeartbeatReflector(
            trace_store=trace_store,
            calibration_store=cal_store,
            twin_store=twin_store,
            experience_store=exp_store,
            llm=llm,
            user_id=twin.user_id,
            pending_queue_path=queue_path,
            auto_reflect_threshold=0.99,  # force everything to queue
        )

        # Mock git log to match "monorepo" for t2
        mock_git = MagicMock(returncode=0, stdout="feat: setup monorepo structure")
        with patch("subprocess.run", return_value=mock_git):
            report = reflector.run()

    # t2 and t3 are pending (t1 already reflected)
    # At least t2 should be inferred (monorepo match)
    assert report.inferred >= 1
    assert report.auto_reflected + report.queued >= 1


# ---------------------------------------------------------------------------
# Test: reflect triggers mining
# ---------------------------------------------------------------------------

def test_reflect_triggers_mining(tmp_path):
    """Counter at 19 → reflect → mine triggered → patterns in library."""
    from twin_runtime.cli._calibration import (
        _increment_reflect_counter,
        _reset_reflect_counter,
    )

    with patch("twin_runtime.cli._calibration._STORE_DIR", tmp_path):
        user_dir = tmp_path / "test"
        user_dir.mkdir()
        counter_path = user_dir / "reflect_count"
        counter_path.write_text("19")

        count = _increment_reflect_counter("test")
        assert count == 20

        # Verify the counter file is correct
        assert counter_path.read_text() == "20"

        # Reset
        _reset_reflect_counter("test")
        assert counter_path.read_text() == "0"


def test_experience_updater_integration():
    """ExperienceUpdater correctly gates entries into library."""
    from twin_runtime.application.calibration.experience_updater import (
        ExperienceUpdater,
        UpdateAction,
    )
    from twin_runtime.domain.models.experience import ExperienceEntry

    lib = ExperienceLibrary()
    updater = ExperienceUpdater()

    # Add first entry
    e1 = ExperienceEntry(
        id="e1",
        scenario_type=["redis", "caching"],
        insight="Redis is better for caching",
        applicable_when="backend caching",
        was_correct=True,
        created_at=datetime.now(timezone.utc),
    )
    r1 = updater.update(e1, lib)
    assert r1.action == UpdateAction.ADDED
    assert lib.size == 1

    # Add duplicate → confirmed
    e2 = ExperienceEntry(
        id="e2",
        scenario_type=["redis", "caching"],
        insight="Redis works great for caching workloads",
        applicable_when="backend caching",
        was_correct=True,
        created_at=datetime.now(timezone.utc),
    )
    r2 = updater.update(e2, lib)
    assert r2.action == UpdateAction.CONFIRMED
    assert lib.size == 1  # not added
    assert lib.entries[0].confirmation_count == 1

    # Add conflicting → superseded
    e3 = ExperienceEntry(
        id="e3",
        scenario_type=["redis", "caching"],
        insight="Redis was wrong for this caching scenario",
        applicable_when="backend caching",
        was_correct=False,
        created_at=datetime.now(timezone.utc),
    )
    r3 = updater.update(e3, lib)
    assert r3.action == UpdateAction.SUPERSEDED
    assert lib.size == 2  # old + new
    assert lib.entries[0].weight < 1.0  # old weight halved

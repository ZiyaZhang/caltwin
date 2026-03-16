"""Tests that JsonFile backends satisfy port protocols."""
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from twin_runtime.domain.ports.twin_state_store import TwinStateStore
from twin_runtime.domain.ports.calibration_store import CalibrationStore as CalibrationStorePort
from twin_runtime.domain.ports.evidence_store import EvidenceStore as EvidenceStorePort
from twin_runtime.domain.ports.trace_store import TraceStore as TraceStorePort
from twin_runtime.infrastructure.backends.json_file.twin_store import TwinStore
from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore
from twin_runtime.infrastructure.backends.json_file.evidence_store import JsonFileEvidenceStore
from twin_runtime.infrastructure.backends.json_file.trace_store import JsonFileTraceStore
from twin_runtime.domain.evidence.base import EvidenceFragment, EvidenceType
from twin_runtime.domain.models.runtime import RuntimeDecisionTrace
from twin_runtime.domain.models.primitives import DomainEnum, DecisionMode


def _load_sample_twin():
    """Load the sample twin from fixtures."""
    import json
    fixtures_dir = Path(__file__).parent / "fixtures"
    data = json.loads((fixtures_dir / "sample_twin_state.json").read_text(encoding="utf-8"))
    from twin_runtime.domain.models.twin_state import TwinState as TS
    return TS.model_validate(data)


class TestTwinStoreProtocol:
    def test_implements_protocol(self):
        assert isinstance(TwinStore(tempfile.mkdtemp()), TwinStateStore)

    def test_save_state_method(self, tmp_path):
        store = TwinStore(tmp_path / "twins")
        twin = _load_sample_twin()
        result = store.save_state(twin)
        assert isinstance(result, str)

    def test_load_state_method(self, tmp_path):
        store = TwinStore(tmp_path / "twins")
        twin = _load_sample_twin()
        store.save_state(twin)
        loaded = store.load_state(twin.user_id)
        assert loaded.user_id == twin.user_id


class TestCalibrationStoreProtocol:
    def test_implements_protocol(self, tmp_path):
        store = CalibrationStore(str(tmp_path), "user-test")
        assert isinstance(store, CalibrationStorePort)


class TestEvidenceStoreProtocol:
    def test_implements_protocol(self, tmp_path):
        store = JsonFileEvidenceStore(tmp_path / "evidence")
        assert isinstance(store, EvidenceStorePort)

    def test_store_and_retrieve_fragment(self, tmp_path):
        store = JsonFileEvidenceStore(tmp_path / "evidence")
        now = datetime.now(timezone.utc)
        frag = EvidenceFragment(
            source_type="test",
            source_id="test-001",
            evidence_type=EvidenceType.DECISION,
            user_id="user-1",
            occurred_at=now,
            valid_from=now,
            raw_excerpt="test content",
            summary="test summary",
            confidence=0.8,
        )
        frag_id = store.store_fragment(frag)
        assert isinstance(frag_id, str)
        retrieved = store.get_by_hash(frag.content_hash)
        assert retrieved is not None
        assert retrieved.content_hash == frag.content_hash

    def test_count(self, tmp_path):
        store = JsonFileEvidenceStore(tmp_path / "evidence")
        assert store.count("user-1") == 0


class TestTraceStoreProtocol:
    def test_implements_protocol(self, tmp_path):
        store = JsonFileTraceStore(tmp_path / "traces")
        assert isinstance(store, TraceStorePort)

    def test_save_and_load_trace(self, tmp_path):
        store = JsonFileTraceStore(tmp_path / "traces")
        trace = RuntimeDecisionTrace(
            trace_id="trace-001",
            twin_state_version="v001",
            situation_frame_id="sf-001",
            activated_domains=[DomainEnum.WORK],
            head_assessments=[{
                "domain": DomainEnum.WORK,
                "head_version": "v1",
                "option_ranking": ["A"],
                "utility_decomposition": {"growth": 0.8},
                "confidence": 0.7,
            }],
            final_decision="A",
            decision_mode=DecisionMode.DIRECT,
            uncertainty=0.3,
            created_at=datetime.now(timezone.utc),
        )
        trace_id = store.save_trace(trace)
        assert trace_id == "trace-001"
        loaded = store.load_trace("trace-001")
        assert loaded.trace_id == trace.trace_id

    def test_list_traces(self, tmp_path):
        store = JsonFileTraceStore(tmp_path / "traces")
        assert store.list_traces("user-1") == []

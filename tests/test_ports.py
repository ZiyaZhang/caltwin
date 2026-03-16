"""Tests that verify port protocol definitions are importable and structurally correct."""
from typing import Protocol, runtime_checkable
import pytest


class TestPortProtocols:
    def test_twin_state_store_is_protocol(self):
        from twin_runtime.domain.ports.twin_state_store import TwinStateStore
        assert issubclass(TwinStateStore, Protocol)

    def test_evidence_store_is_protocol(self):
        from twin_runtime.domain.ports.evidence_store import EvidenceStore
        assert issubclass(EvidenceStore, Protocol)

    def test_calibration_store_is_protocol(self):
        from twin_runtime.domain.ports.calibration_store import CalibrationStore
        assert issubclass(CalibrationStore, Protocol)

    def test_trace_store_is_protocol(self):
        from twin_runtime.domain.ports.trace_store import TraceStore
        assert issubclass(TraceStore, Protocol)

    def test_llm_port_is_protocol(self):
        from twin_runtime.domain.ports.llm_port import LLMPort
        assert issubclass(LLMPort, Protocol)

    def test_recall_query_creation(self):
        from twin_runtime.domain.models.recall_query import RecallQuery
        from twin_runtime.domain.models.primitives import DomainEnum
        q = RecallQuery(
            query_type="by_domain",
            user_id="user-test",
            target_domain=DomainEnum.WORK,
        )
        assert q.query_type == "by_domain"
        assert q.limit == 20  # default

    def test_recall_query_by_topic(self):
        from twin_runtime.domain.models.recall_query import RecallQuery
        q = RecallQuery(
            query_type="by_topic",
            user_id="user-test",
            topic_keywords=["career", "decision"],
        )
        assert q.topic_keywords == ["career", "decision"]

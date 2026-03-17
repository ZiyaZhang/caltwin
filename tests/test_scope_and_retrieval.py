"""Tests for scope guard and retrieval."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from twin_runtime.application.pipeline.scope_guard import deterministic_scope_guard, ScopeGuardResult
from twin_runtime.domain.evidence.base import EvidenceFragment, EvidenceType
from twin_runtime.domain.models.primitives import DomainEnum, ScopeStatus
from twin_runtime.domain.models.recall_query import RecallQuery
from twin_runtime.domain.models.twin_state import TwinState
from twin_runtime.infrastructure.backends.json_file.evidence_store import JsonFileEvidenceStore


@pytest.fixture
def sample_scope():
    twin = TwinState(**json.loads(Path("tests/fixtures/sample_twin_state.json").read_text()))
    return twin.scope_declaration


@pytest.fixture
def sample_twin():
    return TwinState(**json.loads(Path("tests/fixtures/sample_twin_state.json").read_text()))


class TestDeterministicScopeGuard:
    def test_restricted_hit_on_medical(self, sample_scope):
        result = deterministic_scope_guard("我最近头疼应该去看什么医疗科室", sample_scope)
        assert result.restricted_hit is True
        assert any("医疗" in t for t in result.matched_terms)

    def test_non_modeled_hit_on_emotion(self, sample_scope):
        result = deterministic_scope_guard("我现在的情绪怎么样", sample_scope)
        assert result.non_modeled_hit is True

    def test_no_match_on_work_query(self, sample_scope):
        result = deterministic_scope_guard("Should I prioritize the refactor?", sample_scope)
        assert not result.triggered

    def test_restricted_short_circuits_interpret(self, sample_twin):
        """Restricted hit should produce OUT_OF_SCOPE frame without LLM call."""
        from twin_runtime.application.pipeline.situation_interpreter import interpret_situation

        llm = MagicMock()

        frame, guard = interpret_situation("I need medical diagnosis help", sample_twin, llm=llm)
        assert frame.scope_status == ScopeStatus.OUT_OF_SCOPE
        assert guard.restricted_hit is True
        # LLM should NOT have been called
        llm.ask_structured.assert_not_called()

    def test_triggered_property(self):
        r = ScopeGuardResult(restricted_hit=True)
        assert r.triggered is True
        r2 = ScopeGuardResult(non_modeled_hit=True)
        assert r2.triggered is True
        r3 = ScopeGuardResult()
        assert r3.triggered is False


class TestRecallQuery:
    def _make_fragment(self, domain, summary, occurred_days_ago=0):
        content = f"{domain}-{summary}"
        return EvidenceFragment(
            fragment_id=f"frag-{abs(hash(content)) % 10000}",
            content_hash=hashlib.sha256(content.encode()).hexdigest()[:16],
            user_id="test-user",
            source_type="test",
            source_id="test-1",
            evidence_type=EvidenceType.BEHAVIOR,
            occurred_at=datetime.now(timezone.utc) - timedelta(days=occurred_days_ago),
            valid_from=datetime.now(timezone.utc) - timedelta(days=occurred_days_ago),
            domain_hint=domain,
            summary=summary,
            confidence=0.8,
        )

    def test_domain_filter(self, tmp_path):
        store = JsonFileEvidenceStore(tmp_path)
        store.store_fragment(self._make_fragment(DomainEnum.WORK, "project deadline"))
        store.store_fragment(self._make_fragment(DomainEnum.MONEY, "investment choice"))

        q = RecallQuery(query_type="by_domain", user_id="test-user", target_domain=DomainEnum.WORK)
        results = store.query(q)
        assert len(results) == 1
        assert results[0].domain_hint == DomainEnum.WORK

    def test_keyword_ranking(self, tmp_path):
        store = JsonFileEvidenceStore(tmp_path)
        store.store_fragment(self._make_fragment(DomainEnum.WORK, "sprint planning meeting"))
        store.store_fragment(self._make_fragment(DomainEnum.WORK, "code review and deploy"))

        q = RecallQuery(query_type="by_topic", user_id="test-user", topic_keywords=["deploy"])
        results = store.query(q)
        assert len(results) == 1  # Only matching fragment returned
        assert "deploy" in results[0].summary

    def test_empty_store_returns_empty(self, tmp_path):
        store = JsonFileEvidenceStore(tmp_path)
        q = RecallQuery(query_type="by_topic", user_id="test-user", topic_keywords=["anything"])
        results = store.query(q)
        assert results == []

    def test_no_keyword_match_returns_empty(self, tmp_path):
        store = JsonFileEvidenceStore(tmp_path)
        store.store_fragment(self._make_fragment(DomainEnum.WORK, "project deadline"))
        q = RecallQuery(query_type="by_topic", user_id="test-user", topic_keywords=["investment"])
        results = store.query(q)
        assert results == []  # Honest: no match = empty

    def test_evidence_type_filter(self, tmp_path):
        store = JsonFileEvidenceStore(tmp_path)
        store.store_fragment(self._make_fragment(DomainEnum.WORK, "project deadline"))
        # The fragment is BEHAVIOR type, so filtering by REFLECTION should return empty
        q = RecallQuery(
            query_type="by_evidence_type", user_id="test-user",
            target_evidence_type=EvidenceType.REFLECTION,
        )
        results = store.query(q)
        assert results == []

    def test_recency_sort_default(self, tmp_path):
        store = JsonFileEvidenceStore(tmp_path)
        store.store_fragment(self._make_fragment(DomainEnum.WORK, "old task", occurred_days_ago=10))
        store.store_fragment(self._make_fragment(DomainEnum.WORK, "new task", occurred_days_ago=0))

        q = RecallQuery(query_type="by_domain", user_id="test-user", target_domain=DomainEnum.WORK)
        results = store.query(q)
        assert len(results) == 2
        assert "new" in results[0].summary  # Most recent first

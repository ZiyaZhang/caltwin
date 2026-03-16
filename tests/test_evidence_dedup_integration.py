"""Tests for two-layer evidence dedup."""
import tempfile
import pytest
from twin_runtime.infrastructure.backends.json_file.evidence_store import JsonFileEvidenceStore
from twin_runtime.domain.evidence.types import DecisionEvidence
from twin_runtime.domain.models.primitives import DomainEnum, OrdinalTriLevel
from datetime import datetime, timezone


class TestStoreWriteTimeDedup:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = JsonFileEvidenceStore(self.tmpdir)

    def _make_decision(self, source_type="interview", confidence=0.8):
        now = datetime.now(timezone.utc)
        return DecisionEvidence(
            fragment_id="frag-1",
            user_id="test-user",
            source_type=source_type,
            source_id="src-1",
            evidence_type="decision",
            occurred_at=now,
            valid_from=now,
            domain_hint=DomainEnum.WORK,
            summary="Chose A over B",
            raw_excerpt="test",
            confidence=confidence,
            extraction_method="manual",
            option_set=["A", "B"],
            chosen="A",
            stakes=OrdinalTriLevel.MEDIUM,
        )

    def test_first_write_stores(self):
        frag = self._make_decision()
        h = self.store.store_fragment(frag)
        assert self.store.get_by_hash(h) is not None

    def test_same_source_keeps_higher_confidence(self):
        frag1 = self._make_decision(confidence=0.7)
        frag2 = self._make_decision(confidence=0.9)
        self.store.store_fragment(frag1)
        self.store.store_fragment(frag2)
        result = self.store.get_by_hash(frag1.content_hash)
        assert result.confidence == 0.9

    def test_different_source_creates_cluster(self):
        frag1 = self._make_decision(source_type="interview")
        frag2 = self._make_decision(source_type="runtime_trace")
        self.store.store_fragment(frag1)
        self.store.store_fragment(frag2)
        from pathlib import Path
        clusters = list(Path(self.tmpdir).rglob("clusters/*.json"))
        assert len(clusters) >= 1


class TestCompilerDedup:
    def test_compiler_deduplicates(self):
        from unittest.mock import patch, MagicMock
        from twin_runtime.application.compiler.persona_compiler import PersonaCompiler

        registry = MagicMock()
        frag1 = MagicMock()
        frag1.content_hash = "abc123"
        frag1.confidence = 0.8
        frag2 = MagicMock()
        frag2.content_hash = "abc123"  # duplicate
        frag2.confidence = 0.6
        frag3 = MagicMock()
        frag3.content_hash = "def456"
        frag3.confidence = 0.9
        registry.scan_all.return_value = [frag1, frag2, frag3]

        compiler = PersonaCompiler(registry, llm=MagicMock())
        # Patch deduplicate at the source module (lazy-imported inside compile())
        with patch(
            "twin_runtime.domain.evidence.clustering.deduplicate",
            return_value=[frag1, frag3],
        ), patch.object(compiler, 'extract_parameters', return_value={}) as mock_extract:
            compiler.compile()
            called_frags = mock_extract.call_args[0][0]
            assert len(called_frags) <= 2

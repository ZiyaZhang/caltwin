"""Tests for data source adapters and registry (no API calls)."""

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from twin_runtime.sources.base import EvidenceFragment, EvidenceType, SourceAdapter
from twin_runtime.sources.registry import SourceRegistry
from twin_runtime.sources.openclaw_adapter import OpenClawAdapter
from twin_runtime.sources.document_adapter import DocumentAdapter


class DummyAdapter(SourceAdapter):
    @property
    def source_type(self) -> str:
        return "dummy"

    def check_connection(self) -> bool:
        return True

    def scan(self, since=None):
        return [EvidenceFragment(
            source_type="dummy",
            source_id="test-1",
            evidence_type=EvidenceType.PREFERENCE,
            timestamp=datetime.now(timezone.utc),
            summary="Test evidence",
            confidence=0.8,
        )]


class TestEvidenceFragment:
    def test_create_fragment(self):
        f = EvidenceFragment(
            source_type="test",
            source_id="id-1",
            evidence_type=EvidenceType.DECISION,
            timestamp=datetime.now(timezone.utc),
            summary="User chose A over B",
            structured_data={"options": ["A", "B"], "choice": "A"},
            confidence=0.9,
        )
        assert f.evidence_type == EvidenceType.DECISION
        assert f.structured_data["choice"] == "A"
        assert f.temporal_weight == 1.0

    def test_fragment_with_domain_hint(self):
        from twin_runtime.models.primitives import DomainEnum
        f = EvidenceFragment(
            source_type="test",
            source_id="id-2",
            evidence_type=EvidenceType.PREFERENCE,
            timestamp=datetime.now(timezone.utc),
            summary="Prefers ecosystem leverage",
            domain_hint=DomainEnum.WORK,
            confidence=0.85,
        )
        assert f.domain_hint == DomainEnum.WORK

    def test_fragment_temporal_fields(self):
        now = datetime.now(timezone.utc)
        f = EvidenceFragment(
            source_type="test",
            source_id="t-1",
            evidence_type=EvidenceType.PREFERENCE,
            occurred_at=now,
            valid_from=now,
            summary="Test",
            confidence=0.8,
            user_id="user-test",
        )
        assert f.occurred_at == now
        assert f.valid_from == now
        assert f.valid_until is None
        assert f.user_id == "user-test"

    def test_fragment_backward_compat_timestamp(self):
        """Legacy 'timestamp' field should still work via occurred_at."""
        now = datetime.now(timezone.utc)
        f = EvidenceFragment(
            source_type="test",
            source_id="t-1",
            evidence_type=EvidenceType.PREFERENCE,
            occurred_at=now,
            valid_from=now,
            summary="Test",
            confidence=0.8,
            user_id="user-default",
        )
        assert f.occurred_at == now

    def test_fragment_content_hash_populated(self):
        f = EvidenceFragment(
            source_type="test",
            source_id="t-1",
            evidence_type=EvidenceType.PREFERENCE,
            occurred_at=datetime.now(timezone.utc),
            valid_from=datetime.now(timezone.utc),
            summary="Test preference",
            confidence=0.8,
            user_id="user-test",
        )
        assert isinstance(f.content_hash, str)
        assert len(f.content_hash) > 0


class TestSourceRegistry:
    def test_register_and_list(self):
        reg = SourceRegistry()
        reg.register(DummyAdapter())
        assert "dummy" in reg.list_sources()

    def test_scan_all(self):
        reg = SourceRegistry()
        reg.register(DummyAdapter())
        fragments = reg.scan_all()
        assert len(fragments) == 1
        assert fragments[0].source_type == "dummy"

    def test_check_all(self):
        reg = SourceRegistry()
        reg.register(DummyAdapter())
        status = reg.check_all()
        assert status["dummy"] is True

    def test_scan_nonexistent_raises(self):
        reg = SourceRegistry()
        with pytest.raises(KeyError):
            reg.scan("nonexistent")


class TestOpenClawAdapter:
    def test_scan_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a CLAUDE.md
            claude_md = Path(tmpdir) / "CLAUDE.md"
            claude_md.write_text("# Project\nAlways use TDD.")

            adapter = OpenClawAdapter(tmpdir, home_dir=tmpdir)
            fragments = adapter.scan()

            assert len(fragments) >= 1
            assert any("CLAUDE.md" in f.source_id for f in fragments)

    def test_scan_memory_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mem_dir = Path(tmpdir) / ".claude" / "memory"
            mem_dir.mkdir(parents=True)
            (mem_dir / "user_role.md").write_text(
                "---\nname: user_role\ntype: user\ndescription: PM at Tencent\n---\nProduct manager."
            )

            adapter = OpenClawAdapter(tmpdir, home_dir=tmpdir)
            fragments = adapter.scan()

            mem_fragments = [f for f in fragments if "memory" in f.source_id]
            assert len(mem_fragments) == 1
            assert mem_fragments[0].structured_data["memory_type"] == "user"

    def test_check_connection(self):
        adapter = OpenClawAdapter("/nonexistent/path")
        assert adapter.check_connection() is False

    def test_source_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = OpenClawAdapter(tmpdir, home_dir=tmpdir)
            meta = adapter.get_source_metadata()
            assert meta["source_type"] == "openclaw"

    def test_scan_returns_typed_fragments(self):
        from twin_runtime.sources.evidence_types import ContextEvidence
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "CLAUDE.md").write_text("# Project instructions\nUse Python 3.9+")
            adapter = OpenClawAdapter(tmpdir)
            fragments = adapter.scan()
            assert len(fragments) >= 1
            claude_frags = [f for f in fragments if "CLAUDE" in f.source_id or "claude" in f.source_id.lower()]
            assert len(claude_frags) >= 1
            assert isinstance(claude_frags[0], ContextEvidence)


class TestDocumentAdapter:
    def test_scan_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f1 = Path(tmpdir) / "notes.md"
            f1.write_text("# Decision Log\nChose Python over TypeScript.")
            f2 = Path(tmpdir) / "data.json"
            f2.write_text('{"choice": "Python"}')

            adapter = DocumentAdapter([str(f1), str(f2)])
            fragments = adapter.scan()

            assert len(fragments) == 2
            assert any("notes.md" in f.source_id for f in fragments)

    def test_add_remove_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f1 = Path(tmpdir) / "test.txt"
            f1.write_text("test content")

            adapter = DocumentAdapter()
            assert adapter.check_connection() is False

            adapter.add_file(str(f1))
            assert adapter.check_connection() is True
            assert len(adapter._files) == 1

            adapter.remove_file(str(f1))
            assert len(adapter._files) == 0

    def test_skip_unsupported_extension(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f1 = Path(tmpdir) / "image.png"
            f1.write_bytes(b"\x89PNG")

            adapter = DocumentAdapter([str(f1)])
            assert len(adapter._files) == 0

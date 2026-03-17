"""Tests for trust boundary: --demo mode and fail-closed behavior."""
import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


class TestDemoMode:
    """CLI --demo flag loads sample twin without persistence."""

    def test_get_twin_demo_returns_sample(self):
        """_get_twin(demo=True) returns bundled sample twin."""
        from twin_runtime.cli import _get_twin
        twin = _get_twin({}, demo=True)
        assert twin is not None
        assert twin.user_id
        assert len(twin.domain_heads) > 0

    def test_get_twin_demo_does_not_touch_store(self, tmp_path):
        """Demo mode must not read from or write to the real store."""
        from twin_runtime.cli import _get_twin
        # No store dir exists — should still work
        twin = _get_twin({"user_id": "nobody"}, demo=True)
        assert twin is not None

    def test_get_twin_no_demo_raises_when_empty(self):
        """Without --demo and no store, must raise TwinNotFoundError."""
        from twin_runtime.cli import _get_twin, TwinNotFoundError
        with pytest.raises(TwinNotFoundError):
            _get_twin({"user_id": "nonexistent-user-xyz"}, demo=False)

    def test_require_twin_demo_returns_twin(self):
        """_require_twin(demo=True) returns sample twin without sys.exit."""
        from twin_runtime.cli import _require_twin
        twin = _require_twin({}, demo=True)
        assert twin is not None

    def test_cmd_reflect_demo_skips_persistence(self, capsys):
        """cmd_reflect with --demo should print banner and return without persisting."""
        from twin_runtime.cli import cmd_reflect
        args = MagicMock()
        args.demo = True
        args.choice = "Option A"
        args.trace_id = None
        args.reasoning = None
        args.feedback_target = None

        cmd_reflect(args)
        captured = capsys.readouterr()
        assert "[DEMO MODE]" in captured.out


class TestFailClosed:
    """MCP server returns errors instead of silent fallbacks."""

    def test_mcp_load_twin_no_fallback(self, tmp_path):
        """_load_twin returns None when store is empty — no fixture fallback."""
        from twin_runtime.infrastructure.backends.json_file.twin_store import TwinStore
        from twin_runtime.server.mcp_server import _load_twin

        store = TwinStore(tmp_path / "empty")
        result = _load_twin(store, "nobody")
        assert result is None

    def test_mcp_decide_error_when_no_twin(self, tmp_path):
        """twin_decide must return error JSON when no twin exists."""
        import asyncio
        from twin_runtime.server.mcp_server import _handle_decide

        env = {"TWIN_STORE_DIR": str(tmp_path / "empty"), "TWIN_USER_ID": "nobody"}
        with patch.dict("os.environ", env):
            result = json.loads(asyncio.get_event_loop().run_until_complete(
                _handle_decide({"query": "test?", "options": ["A", "B"]})
            ))
        assert "error" in result

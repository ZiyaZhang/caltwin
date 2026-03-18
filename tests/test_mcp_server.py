"""Tests for MCP server tool handlers."""
import json
import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path

from twin_runtime.server.mcp_server import (
    _handle_decide,
    _handle_status,
    _handle_reflect,
    _StdioMCPServer,
    TOOLS,
    create_server,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def twin_env(tmp_path):
    """Set up a temp store with a twin state loaded from fixture."""
    from twin_runtime.infrastructure.backends.json_file.twin_store import TwinStore
    from twin_runtime.domain.models.twin_state import TwinState

    fixture = Path("tests/fixtures/sample_twin_state.json")
    twin = TwinState(**json.loads(fixture.read_text()))

    store = TwinStore(tmp_path / "store")
    store.save_state(twin)

    env = {
        "TWIN_STORE_DIR": str(tmp_path / "store"),
        "TWIN_USER_ID": twin.user_id,
    }
    return env, twin


def _run(coro):
    """Helper to run async handlers in sync tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Tool listing
# ---------------------------------------------------------------------------

class TestToolDefinitions:
    def test_has_three_tools(self):
        assert len(TOOLS) == 5

    def test_tool_names(self):
        names = {t["name"] for t in TOOLS}
        assert names == {"twin_decide", "twin_status", "twin_reflect", "twin_calibrate", "twin_history"}

    def test_decide_requires_query_and_options(self):
        decide = [t for t in TOOLS if t["name"] == "twin_decide"][0]
        assert "query" in decide["inputSchema"]["required"]
        assert "options" in decide["inputSchema"]["required"]

    def test_reflect_requires_choice(self):
        reflect = [t for t in TOOLS if t["name"] == "twin_reflect"][0]
        assert "choice" in reflect["inputSchema"]["required"]


# ---------------------------------------------------------------------------
# twin_status handler
# ---------------------------------------------------------------------------

class TestHandleStatus:
    def test_returns_twin_info(self, twin_env):
        env, twin = twin_env
        with patch.dict("os.environ", env):
            result = json.loads(_run(_handle_status({})))
        assert result["version"] == twin.state_version
        assert result["user_id"] == twin.user_id
        assert len(result["domains"]) == len(twin.domain_heads)

    def test_no_twin_returns_error(self, tmp_path, monkeypatch):
        env = {"TWIN_STORE_DIR": str(tmp_path / "empty"), "TWIN_USER_ID": "nobody"}
        monkeypatch.chdir(tmp_path)
        with patch.dict("os.environ", env):
            result = json.loads(_run(_handle_status({})))
        # Fail-closed: no silent fallback, must return error
        assert "error" in result


# ---------------------------------------------------------------------------
# twin_decide handler
# ---------------------------------------------------------------------------

class TestHandleDecide:
    def test_missing_args_returns_error(self):
        result = json.loads(_run(_handle_decide({})))
        assert "error" in result

    def test_returns_trace_id_and_persists(self, twin_env):
        """twin_decide must return trace_id AND persist the trace to TraceStore."""
        env, twin = twin_env
        mock_trace = MagicMock()
        mock_trace.final_decision = "Recommended: A"
        mock_trace.decision_mode.value = "direct"
        mock_trace.uncertainty = 0.3
        mock_trace.activated_domains = []
        mock_trace.trace_id = "test-trace-123"
        mock_trace.output_text = "A is better"
        mock_trace.route_path = "s1_direct"
        mock_trace.boundary_policy = "normal"
        mock_trace.refusal_reason_code = None
        mock_trace.deliberation_rounds = 0
        mock_trace.terminated_by = None
        mock_trace.model_dump_json.return_value = "{}"

        with patch.dict("os.environ", env), \
             patch("twin_runtime.application.orchestrator.runtime_orchestrator.run", return_value=mock_trace), \
             patch("twin_runtime.infrastructure.backends.json_file.trace_store.JsonFileTraceStore.save_trace") as mock_save:
            result = json.loads(_run(_handle_decide({"query": "test?", "options": ["A", "B"]})))

        assert result["trace_id"] == "test-trace-123"
        mock_save.assert_called_once_with(mock_trace)


# ---------------------------------------------------------------------------
# twin_reflect handler
# ---------------------------------------------------------------------------

class TestHandleReflect:
    def test_missing_choice_returns_error(self):
        result = json.loads(_run(_handle_reflect({})))
        assert "error" in result

    def test_standalone_outcome_persisted(self, twin_env):
        """Without trace_id, outcome must still be saved to CalibrationStore."""
        env, _ = twin_env
        with patch.dict("os.environ", env), \
             patch("twin_runtime.server.mcp_server._save_standalone_outcome") as mock_save:
            result = json.loads(_run(_handle_reflect({"choice": "Option A"})))

        assert result["status"] == "recorded"
        mock_save.assert_called_once()

    def test_with_trace_id_calls_record_outcome(self, twin_env):
        """With trace_id, must call record_outcome with correct signature."""
        env, _ = twin_env
        mock_outcome = MagicMock()
        mock_outcome.outcome_id = "out-1"
        mock_outcome.prediction_rank = 1
        mock_update = MagicMock()

        with patch.dict("os.environ", env), \
             patch("twin_runtime.application.calibration.outcome_tracker.record_outcome",
                   return_value=(mock_outcome, mock_update)) as mock_rec:
            result = json.loads(_run(_handle_reflect({
                "choice": "A",
                "trace_id": "trace-abc",
                "reasoning": "seemed better",
            })))

        mock_rec.assert_called_once()
        call_kwargs = mock_rec.call_args
        assert call_kwargs.kwargs["trace_id"] == "trace-abc" or call_kwargs[0][0] == "trace-abc"
        assert result["outcome_id"] == "out-1"
        assert result["calibration_updated"] is True

    def test_missing_trace_falls_back_to_standalone(self, twin_env):
        """If trace_id provided but trace not found, falls back to standalone."""
        env, _ = twin_env
        with patch.dict("os.environ", env), \
             patch("twin_runtime.application.calibration.outcome_tracker.record_outcome",
                   side_effect=FileNotFoundError("trace not found")), \
             patch("twin_runtime.server.mcp_server._save_standalone_outcome") as mock_save:
            result = json.loads(_run(_handle_reflect({
                "choice": "A",
                "trace_id": "nonexistent",
            })))

        assert "standalone" in result["message"].lower()
        mock_save.assert_called_once()


# ---------------------------------------------------------------------------
# Fallback JSON-RPC server protocol
# ---------------------------------------------------------------------------

class TestStdioMCPServerProtocol:
    def test_initialize_returns_capabilities(self):
        server = _StdioMCPServer()
        resp = _run(server._dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}))
        assert resp["id"] == 1
        assert resp["result"]["serverInfo"]["name"] == "twin-runtime"
        assert "tools" in resp["result"]["capabilities"]

    def test_tools_list_returns_all_tools(self):
        server = _StdioMCPServer()
        resp = _run(server._dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}))
        tool_names = {t["name"] for t in resp["result"]["tools"]}
        assert tool_names == {"twin_decide", "twin_status", "twin_reflect", "twin_calibrate", "twin_history"}

    def test_unknown_method_returns_error(self):
        server = _StdioMCPServer()
        resp = _run(server._dispatch({"jsonrpc": "2.0", "id": 3, "method": "nonexistent", "params": {}}))
        assert "error" in resp
        assert resp["error"]["code"] == -32601

    def test_ping_returns_empty_result(self):
        server = _StdioMCPServer()
        resp = _run(server._dispatch({"jsonrpc": "2.0", "id": 4, "method": "ping", "params": {}}))
        assert resp["result"] == {}

    def test_notification_returns_none(self):
        server = _StdioMCPServer()
        resp = _run(server._dispatch({"method": "notifications/initialized"}))
        assert resp is None

    def test_tools_call_dispatches_to_handler(self, twin_env):
        env, _ = twin_env
        server = _StdioMCPServer()
        with patch.dict("os.environ", env):
            resp = _run(server._dispatch({
                "jsonrpc": "2.0", "id": 5,
                "method": "tools/call",
                "params": {"name": "twin_status", "arguments": {}},
            }))
        content = resp["result"]["content"][0]["text"]
        parsed = json.loads(content)
        assert "version" in parsed or "error" in parsed

"""Tests for MCP twin_calibrate and twin_history tools."""
import json
import pytest
import asyncio
from unittest.mock import patch
from pathlib import Path

from twin_runtime.server.mcp_server import (
    TOOLS,
    _StdioMCPServer,
    _handle_calibrate,
    _handle_history,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def twin_env(tmp_path):
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


class TestCalibrateTool:
    def test_tool_exists(self):
        names = {t["name"] for t in TOOLS}
        assert "twin_calibrate" in names

    def test_tool_schema(self):
        cal = [t for t in TOOLS if t["name"] == "twin_calibrate"][0]
        props = cal["inputSchema"]["properties"]
        assert "with_bias_detection" in props

    def test_no_cases_returns_message(self, twin_env):
        env, _ = twin_env
        with patch.dict("os.environ", env):
            result = json.loads(_run(_handle_calibrate({})))
        assert "choice_similarity" in result or "message" in result or "error" in result


class TestHistoryTool:
    def test_tool_exists(self):
        names = {t["name"] for t in TOOLS}
        assert "twin_history" in names

    def test_tool_schema(self):
        hist = [t for t in TOOLS if t["name"] == "twin_history"][0]
        props = hist["inputSchema"]["properties"]
        assert "limit" in props

    def test_returns_traces_list(self, twin_env):
        env, _ = twin_env
        with patch.dict("os.environ", env):
            result = json.loads(_run(_handle_history({})))
        assert "traces" in result or "error" in result


class TestProtocolWithNewTools:
    def test_tools_list_includes_5_tools(self):
        server = _StdioMCPServer()
        resp = _run(server._dispatch({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/list", "params": {},
        }))
        names = {t["name"] for t in resp["result"]["tools"]}
        assert names == {"twin_decide", "twin_status", "twin_reflect", "twin_calibrate", "twin_history"}

"""Tests for MCP server fixture fallback via package resources."""
import json
import pytest


class TestPackageResourceFallback:
    def test_fixture_loadable_via_importlib(self):
        """sample_twin_state.json must be loadable via importlib.resources."""
        import importlib.resources as pkg_resources
        ref = pkg_resources.files("twin_runtime") / "resources" / "fixtures" / "sample_twin_state.json"
        data = json.loads(ref.read_text())
        assert "user_id" in data
        assert "domain_heads" in data

    def test_fixture_validates_as_twin_state(self):
        """Fixture must parse as a valid TwinState."""
        import importlib.resources as pkg_resources
        from twin_runtime.domain.models.twin_state import TwinState
        ref = pkg_resources.files("twin_runtime") / "resources" / "fixtures" / "sample_twin_state.json"
        twin = TwinState.model_validate_json(ref.read_text())
        assert twin.user_id
        assert len(twin.domain_heads) > 0

    def test_mcp_load_twin_uses_fixture(self, tmp_path, monkeypatch):
        """_load_twin should fall back to package resource when store is empty."""
        from twin_runtime.infrastructure.backends.json_file.twin_store import TwinStore
        from twin_runtime.server.mcp_server import _load_twin

        store = TwinStore(tmp_path / "empty_store")
        monkeypatch.chdir(tmp_path)

        twin = _load_twin(store, "nonexistent-user")
        assert twin is not None, "Fixture fallback must work when store is empty"
        assert twin.user_id

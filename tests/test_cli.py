"""Tests for CLI entry point."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from twin_runtime.cli import (
    _load_config,
    _mask,
    _save_config,
    cmd_config,
    cmd_status,
    main,
)


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    """Redirect config to temp directory."""
    config_dir = tmp_path / ".twin-runtime"
    config_dir.mkdir()
    monkeypatch.setattr("twin_runtime.cli._CONFIG_DIR", config_dir)
    monkeypatch.setattr("twin_runtime.cli._CONFIG_FILE", config_dir / "config.json")
    monkeypatch.setattr("twin_runtime.cli._STORE_DIR", config_dir / "store")
    return config_dir


class TestMask:
    def test_short_string(self):
        assert _mask("abc") == "***"

    def test_empty_string(self):
        assert _mask("") == "***"

    def test_normal_string(self):
        result = _mask("sk-1234567890abcdef")
        assert result.startswith("sk-1")
        assert result.endswith("cdef")
        assert "..." in result


class TestConfig:
    def test_save_and_load(self, tmp_config):
        config = {"user_id": "test-user", "model": "test-model"}
        _save_config(config)
        loaded = _load_config()
        assert loaded == config

    def test_load_missing(self, tmp_config):
        assert _load_config() == {}


class TestCLI:
    def test_no_command_shows_help(self, capsys):
        with patch("sys.argv", ["twin-runtime"]):
            main()
        captured = capsys.readouterr()
        assert "twin-runtime" in captured.out

    def test_config_set_and_get(self, tmp_config, capsys):
        # Set
        with patch("sys.argv", ["twin-runtime", "config", "set", "model", "test-model"]):
            main()
        captured = capsys.readouterr()
        assert "test-model" in captured.out

        # Get
        with patch("sys.argv", ["twin-runtime", "config", "get", "model"]):
            main()
        captured = capsys.readouterr()
        assert "test-model" in captured.out

    def test_config_list(self, tmp_config, capsys):
        _save_config({"user_id": "u1", "model": "m1"})
        with patch("sys.argv", ["twin-runtime", "config", "list"]):
            main()
        captured = capsys.readouterr()
        assert "user_id" in captured.out
        assert "model" in captured.out

    def test_status_with_fixture(self, tmp_config, capsys):
        fixture_path = str(Path(__file__).parent / "fixtures" / "sample_twin_state.json")
        _save_config({"user_id": "user-ziya", "fixture_path": fixture_path})
        with patch("sys.argv", ["twin-runtime", "status"]):
            main()
        captured = capsys.readouterr()
        assert "twin-001" in captured.out
        assert "v002" in captured.out

    def test_sources_no_config(self, tmp_config, capsys):
        _save_config({})
        with patch("sys.argv", ["twin-runtime", "sources"]):
            main()
        captured = capsys.readouterr()
        assert "No sources configured" in captured.out

    def test_config_masks_keys(self, tmp_config, capsys):
        _save_config({"api_key": "sk-1234567890abcdef"})
        with patch("sys.argv", ["twin-runtime", "config", "list"]):
            main()
        captured = capsys.readouterr()
        assert "sk-1234567890abcdef" not in captured.out
        assert "..." in captured.out

"""Tests for CLI heartbeat + confirm commands."""

from __future__ import annotations

import json
import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest


def test_heartbeat_argparse():
    """Verify heartbeat subcommand is registered."""
    from twin_runtime.cli._main import main

    with patch("sys.argv", ["twin-runtime", "heartbeat"]):
        with patch("twin_runtime.cli._implicit.cmd_heartbeat") as mock:
            try:
                main()
            except SystemExit:
                pass
            mock.assert_called_once()


def test_confirm_argparse_list():
    """Verify confirm --list subcommand is registered."""
    from twin_runtime.cli._main import main

    with patch("sys.argv", ["twin-runtime", "confirm", "--list"]):
        with patch("twin_runtime.cli._implicit.cmd_confirm") as mock:
            try:
                main()
            except SystemExit:
                pass
            mock.assert_called_once()
            args = mock.call_args[0][0]
            assert args.list_only is True


def test_confirm_argparse_accept_all():
    """Verify confirm --accept-all subcommand is registered."""
    from twin_runtime.cli._main import main

    with patch("sys.argv", ["twin-runtime", "confirm", "--accept-all"]):
        with patch("twin_runtime.cli._implicit.cmd_confirm") as mock:
            try:
                main()
            except SystemExit:
                pass
            mock.assert_called_once()
            args = mock.call_args[0][0]
            assert args.accept_all is True


def test_mine_patterns_argparse():
    """Verify mine-patterns subcommand is registered."""
    from twin_runtime.cli._main import main

    with patch("sys.argv", ["twin-runtime", "mine-patterns", "--min-failures", "5", "--lookback", "100"]):
        with patch("twin_runtime.cli._implicit.cmd_mine_patterns") as mock:
            try:
                main()
            except SystemExit:
                pass
            mock.assert_called_once()
            args = mock.call_args[0][0]
            assert args.min_failures == 5
            assert args.lookback == 100


def test_confirm_empty_queue(tmp_path):
    """No pending → friendly message."""
    import argparse
    from twin_runtime.cli._implicit import cmd_confirm

    args = argparse.Namespace(list_only=False, accept_all=False)

    with patch("twin_runtime.cli._implicit._STORE_DIR", tmp_path):
        with patch("twin_runtime.cli._implicit._load_config", return_value={"user_id": "test"}):
            captured = StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            try:
                cmd_confirm(args)
            finally:
                sys.stdout = old_stdout

    assert "No pending" in captured.getvalue()


def test_confirm_list(tmp_path):
    """Mock pending → verify list output."""
    import argparse
    from twin_runtime.cli._implicit import cmd_confirm

    # Create queue file
    user_dir = tmp_path / "test"
    user_dir.mkdir()
    queue_file = user_dir / "pending_reflections.json"
    pending = [
        {"trace_id": "t1", "inferred_choice": "Redis", "confidence": 0.5,
         "signal_source": "implicit_git", "evidence_summary": ""},
    ]
    queue_file.write_text(json.dumps(pending))

    args = argparse.Namespace(list_only=True, accept_all=False)

    with patch("twin_runtime.cli._implicit._STORE_DIR", tmp_path):
        with patch("twin_runtime.cli._implicit._load_config", return_value={"user_id": "test"}):
            captured = StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            try:
                cmd_confirm(args)
            finally:
                sys.stdout = old_stdout

    output = captured.getvalue()
    assert "1 pending" in output
    assert "t1" in output
    assert "Redis" in output

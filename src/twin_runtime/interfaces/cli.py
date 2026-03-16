"""Interfaces layer – CLI entry point.

Re-exports from twin_runtime.cli so the pyproject.toml entry point
lives logically in the interfaces/ layer.
"""
from twin_runtime.cli import *  # noqa: F401,F403
from twin_runtime.cli import main  # noqa: F401 – explicit for entry point

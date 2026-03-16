"""Backward-compat shim."""
from twin_runtime.application.pipeline.runner import run  # noqa: F401

__all__ = ["run"]

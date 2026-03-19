"""Backward-compat shim."""
from twin_runtime.application.compiler.persona_compiler import *  # noqa: F401,F403
from twin_runtime.infrastructure.llm.client import ask_json  # noqa: F401 — needed for test patching

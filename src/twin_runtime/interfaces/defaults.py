"""Default infrastructure wiring.

The interfaces layer is the correct place to bridge application ports to
infrastructure implementations. Application code imports ports (protocols);
this module provides the concrete defaults.
"""

from __future__ import annotations

from typing import Any, Dict


class DefaultLLM:
    """Adapts infrastructure.llm.client functions to LLMPort protocol."""

    def ask_json(self, system: str, user: str, max_tokens: int = 1024) -> Dict[str, Any]:
        from twin_runtime.infrastructure.llm.client import ask_json
        return ask_json(system, user, max_tokens)

    def ask_text(self, system: str, user: str, max_tokens: int = 1024) -> str:
        from twin_runtime.infrastructure.llm.client import ask_text
        return ask_text(system, user, max_tokens)

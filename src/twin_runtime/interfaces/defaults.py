"""Default infrastructure wiring.

The interfaces layer is the correct place to bridge application ports to
infrastructure implementations. Application code imports ports (protocols);
this module provides the concrete defaults.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class DefaultLLM:
    """Adapts infrastructure.llm.client functions to LLMPort protocol."""

    def ask_json(self, system: str, user: str, max_tokens: int = 1024, *, temperature: Optional[float] = None) -> Dict[str, Any]:
        from twin_runtime.infrastructure.llm.client import ask_json
        return ask_json(system, user, max_tokens=max_tokens, temperature=temperature)

    def ask_text(self, system: str, user: str, max_tokens: int = 1024, *, temperature: Optional[float] = None) -> str:
        from twin_runtime.infrastructure.llm.client import ask_text
        return ask_text(system, user, max_tokens=max_tokens, temperature=temperature)

    def ask_structured(
        self,
        system: str,
        user: str,
        *,
        schema: Dict[str, Any],
        schema_name: str = "structured_output",
        max_tokens: int = 1024,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        from twin_runtime.infrastructure.llm.client import ask_structured
        return ask_structured(system, user, schema=schema, schema_name=schema_name, max_tokens=max_tokens, temperature=temperature)

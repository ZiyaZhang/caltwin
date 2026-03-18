"""Port: LLM interaction."""
from __future__ import annotations
from typing import Any, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class LLMPort(Protocol):
    """Abstract LLM client for testability."""
    def ask_json(self, system: str, user: str, max_tokens: int = 1024, *, temperature: Optional[float] = None) -> Dict[str, Any]: ...
    def ask_text(self, system: str, user: str, max_tokens: int = 1024, *, temperature: Optional[float] = None) -> str: ...
    def ask_structured(
        self,
        system: str,
        user: str,
        *,
        schema: Dict[str, Any],
        schema_name: str = "structured_output",
        max_tokens: int = 1024,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]: ...

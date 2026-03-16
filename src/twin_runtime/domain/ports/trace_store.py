"""Port: Runtime decision trace storage."""
from __future__ import annotations
from typing import List, Protocol, runtime_checkable
from twin_runtime.domain.models.runtime import RuntimeDecisionTrace


@runtime_checkable
class TraceStore(Protocol):
    """Store runtime decision traces for audit."""
    def save_trace(self, trace: RuntimeDecisionTrace) -> str: ...
    def load_trace(self, trace_id: str) -> RuntimeDecisionTrace: ...
    def list_traces(self, user_id: str, limit: int = 50) -> List[str]: ...

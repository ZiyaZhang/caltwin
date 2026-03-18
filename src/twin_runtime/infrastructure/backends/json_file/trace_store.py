"""JSON file implementation of TraceStore protocol."""
from __future__ import annotations

from pathlib import Path
from typing import List

from twin_runtime.domain.models.runtime import RuntimeDecisionTrace


class JsonFileTraceStore:
    """File-based storage for runtime decision traces."""

    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    def save_trace(self, trace: RuntimeDecisionTrace) -> str:
        path = self.base / f"{trace.trace_id}.json"
        path.write_text(trace.model_dump_json(indent=2))
        return trace.trace_id

    def load_trace(self, trace_id: str) -> RuntimeDecisionTrace:
        path = self.base / f"{trace_id}.json"
        return RuntimeDecisionTrace.model_validate_json(path.read_text())

    def list_traces(self, user_id: str = "", limit: int = 50) -> List[str]:
        """List trace IDs sorted by modification time (newest first)."""
        files = sorted(
            self.base.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return [p.stem for p in files[:limit]]

"""JSON file implementation of TraceStore protocol."""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

from twin_runtime.domain.models.runtime import RuntimeDecisionTrace
from twin_runtime.infrastructure.backends.json_file._utils import atomic_write

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


def _validate_safe_id(value: str, label: str = "ID") -> str:
    if not value or not _SAFE_ID_RE.match(value):
        raise ValueError(f"Unsafe {label} for filesystem use: {value!r}")
    return value


class JsonFileTraceStore:
    """File-based storage for runtime decision traces."""

    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    def save_trace(self, trace: RuntimeDecisionTrace) -> str:
        _validate_safe_id(trace.trace_id, "trace_id")
        path = self.base / f"{trace.trace_id}.json"
        atomic_write(path, trace.model_dump_json(indent=2))
        return trace.trace_id

    def load_trace(self, trace_id: str) -> RuntimeDecisionTrace:
        _validate_safe_id(trace_id, "trace_id")
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

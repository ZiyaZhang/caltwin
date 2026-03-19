"""Experience Library Store: persist ExperienceLibrary as a single JSON file."""

from __future__ import annotations

import re
from pathlib import Path

from twin_runtime.domain.models.experience import ExperienceLibrary

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


def _validate_safe_id(value: str, label: str = "ID") -> str:
    if not value or not _SAFE_ID_RE.match(value):
        raise ValueError(f"Unsafe {label} for filesystem use: {value!r}")
    return value


class ExperienceLibraryStore:
    """File-based storage for an ExperienceLibrary."""

    def __init__(self, base_dir: str, user_id: str):
        _validate_safe_id(user_id, "user_id")
        self.base = Path(base_dir) / user_id
        self.base.mkdir(parents=True, exist_ok=True)
        self._path = self.base / "experience_library.json"

    def load(self) -> ExperienceLibrary:
        """Load from JSON; return empty ExperienceLibrary if file doesn't exist."""
        if not self._path.exists():
            return ExperienceLibrary()
        return ExperienceLibrary.model_validate_json(self._path.read_text())

    def save(self, library: ExperienceLibrary) -> None:
        """Write the library to JSON."""
        self._path.write_text(library.model_dump_json(indent=2))

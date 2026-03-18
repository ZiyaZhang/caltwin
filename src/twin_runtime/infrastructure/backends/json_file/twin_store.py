"""Local JSON file store for TwinState with versioning.

Storage layout:
    {base_dir}/{user_id}/
        v001.json
        v002.json
        ...
        current.json   (copy of latest version)
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from twin_runtime.domain.models.twin_state import TwinState

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


def _validate_safe_id(value: str, label: str = "ID") -> str:
    """Validate that an ID is safe for filesystem use (no path traversal)."""
    if not value or not _SAFE_ID_RE.match(value):
        raise ValueError(f"Unsafe {label} for filesystem use: {value!r}")
    return value


class TwinStore:
    """Persist and version TwinState objects as local JSON files."""

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _user_dir(self, user_id: str) -> Path:
        _validate_safe_id(user_id, "user_id")
        d = self.base_dir / user_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _version_path(self, user_id: str, version: str) -> Path:
        return self._user_dir(user_id) / f"{version}.json"

    def _current_path(self, user_id: str) -> Path:
        return self._user_dir(user_id) / "current.json"

    def save_state(self, twin: TwinState) -> str:
        """Save a TwinState version. Also writes current.json. Returns version string."""
        version = twin.state_version
        path = self._version_path(twin.user_id, version)
        data = twin.model_dump_json(indent=2)
        path.write_text(data, encoding="utf-8")

        current = self._current_path(twin.user_id)
        shutil.copy2(path, current)
        return version

    def load_state(self, user_id: str, version: Optional[str] = None) -> TwinState:
        """Load a specific version, or current if version is None."""
        if version is None:
            path = self._current_path(user_id)
        else:
            path = self._version_path(user_id, version)

        if not path.exists():
            raise FileNotFoundError(f"TwinState not found: {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        return TwinState.model_validate(data)

    def list_versions(self, user_id: str) -> List[str]:
        """List all stored versions for a user, sorted."""
        user_dir = self._user_dir(user_id)
        versions = []
        for f in sorted(user_dir.glob("*.json")):
            if f.name != "current.json":
                versions.append(f.stem)
        return versions

    def has_current(self, user_id: str) -> bool:
        return self._current_path(user_id).exists()

    def rollback(self, user_id: str, version: str) -> TwinState:
        """Set current to a previous version. Returns the loaded state."""
        twin = self.load_state(user_id, version)
        current = self._current_path(user_id)
        src = self._version_path(user_id, version)
        shutil.copy2(src, current)
        return twin

    # --- Deprecated aliases (remove in v0.2) ---

    def save(self, twin: TwinState) -> Path:
        """Deprecated: use save_state() instead."""
        import warnings
        warnings.warn("TwinStore.save() is deprecated, use save_state()", DeprecationWarning, stacklevel=2)
        self.save_state(twin)
        return self._version_path(twin.user_id, twin.state_version)

    def load(self, user_id: str, version: Optional[str] = None) -> TwinState:
        """Deprecated: use load_state() instead."""
        import warnings
        warnings.warn("TwinStore.load() is deprecated, use load_state()", DeprecationWarning, stacklevel=2)
        return self.load_state(user_id, version)

    def delete_user(self, user_id: str) -> None:
        """Delete all data for a user."""
        _validate_safe_id(user_id, "user_id")
        user_dir = self.base_dir / user_id
        if user_dir.exists():
            shutil.rmtree(user_dir)

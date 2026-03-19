"""Shared utilities for JSON file stores."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write(path: Path, data: str, encoding: str = "utf-8") -> None:
    """Write data to file atomically using temp file + rename."""
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(data)
        os.replace(tmp_path, str(path))  # atomic on POSIX
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

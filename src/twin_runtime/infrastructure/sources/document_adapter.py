"""Document adapter: extract evidence from user-selected local files.

Supports: .md, .txt, .json, .pdf (text only), .csv
User explicitly selects files to include — no automatic scanning.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from twin_runtime.domain.evidence.base import EvidenceFragment, EvidenceType, SourceAdapter
from twin_runtime.domain.evidence.types import ContextEvidence


# Supported file extensions and their readers
_SUPPORTED_EXTENSIONS = {".md", ".txt", ".json", ".csv", ".log"}


class DocumentAdapter(SourceAdapter):
    """Extract evidence from user-selected local documents."""

    def __init__(self, file_paths: Optional[List[str]] = None):
        self._files: List[Path] = []
        if file_paths:
            for fp in file_paths:
                p = Path(fp).expanduser().resolve()
                if p.exists() and p.suffix in _SUPPORTED_EXTENSIONS:
                    self._files.append(p)

    @property
    def source_type(self) -> str:
        return "document"

    def add_file(self, path: str) -> bool:
        """Add a file to the scan list. Returns True if valid."""
        p = Path(path).expanduser().resolve()
        if p.exists() and p.suffix in _SUPPORTED_EXTENSIONS:
            if p not in self._files:
                self._files.append(p)
            return True
        return False

    def remove_file(self, path: str) -> None:
        p = Path(path).expanduser().resolve()
        self._files = [f for f in self._files if f != p]

    def check_connection(self) -> bool:
        return len(self._files) > 0

    def scan(self, since: Optional[datetime] = None) -> List[EvidenceFragment]:
        fragments: List[EvidenceFragment] = []
        for file_path in self._files:
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
            if since and mtime < since:
                continue

            content = self._read_file(file_path)
            if not content.strip():
                continue

            fragments.append(ContextEvidence(
                source_type=self.source_type,
                source_id=str(file_path),
                occurred_at=mtime,
                valid_from=mtime,
                summary=f"Document: {file_path.name}",
                raw_excerpt=content[:3000],
                confidence=0.75,
                extraction_method="rule_based",
                user_id="user-default",
                context_category="document",
                description=f"Document: {file_path.name}",
                structured_data={
                    "file": str(file_path),
                    "extension": file_path.suffix,
                    "size_bytes": file_path.stat().st_size,
                    "needs_llm_analysis": True,
                },
            ))
        return fragments

    def get_source_metadata(self) -> Dict:
        return {
            "source_type": self.source_type,
            "file_count": len(self._files),
            "files": [str(f) for f in self._files],
        }

    @staticmethod
    def _read_file(path: Path) -> str:
        try:
            if path.suffix == ".json":
                data = json.loads(path.read_text(errors="ignore"))
                return json.dumps(data, indent=2, ensure_ascii=False)[:5000]
            return path.read_text(errors="ignore")[:5000]
        except Exception:
            return ""

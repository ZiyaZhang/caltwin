"""Notion adapter: extract evidence from Notion workspace.

Uses Notion API directly (not MCP) for maximum portability.
Requires an internal integration token.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Import our lightweight Notion reader
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "tools"))

from .base import EvidenceFragment, EvidenceType, SourceAdapter
from .evidence_types import DecisionEvidence, PreferenceEvidence, ReflectionEvidence, ContextEvidence
from ..models.primitives import DomainEnum


class NotionAdapter(SourceAdapter):
    """Extract evidence from Notion workspace."""

    def __init__(self, token: str, max_pages: int = 50):
        self.token = token
        self.max_pages = max_pages
        # Lazy import to avoid circular deps
        self._reader = None

    def _get_reader(self):
        if self._reader is None:
            from tools.notion_reader import (
                search, get_blocks, blocks_to_text,
                extract_page_title, query_database,
            )
            self._reader = type("Reader", (), {
                "search": staticmethod(search),
                "get_blocks": staticmethod(get_blocks),
                "blocks_to_text": staticmethod(blocks_to_text),
                "extract_page_title": staticmethod(extract_page_title),
                "query_database": staticmethod(query_database),
            })
        return self._reader

    @property
    def source_type(self) -> str:
        return "notion"

    def check_connection(self) -> bool:
        try:
            r = self._get_reader()
            results = r.search(self.token, "", page_size=1)
            return True
        except Exception:
            return False

    def scan(self, since: Optional[datetime] = None) -> List[EvidenceFragment]:
        r = self._get_reader()
        fragments: List[EvidenceFragment] = []

        # Search all connected pages
        results = r.search(self.token, "", page_size=self.max_pages)

        for item in results:
            obj_type = item.get("object", "")

            if obj_type == "page":
                fragments.extend(self._process_page(item, r, since))
            elif obj_type == "database":
                fragments.extend(self._process_database(item, r, since))

        return fragments

    def _process_page(self, page: dict, r: Any, since: Optional[datetime]) -> List[EvidenceFragment]:
        page_id = page["id"]
        title = r.extract_page_title(page)

        # Parse timestamps
        created = self._parse_notion_time(page.get("created_time", ""))
        edited = self._parse_notion_time(page.get("last_edited_time", ""))

        if since and edited and edited < since:
            return []

        # Get page content
        try:
            blocks = r.get_blocks(self.token, page_id)
            text = r.blocks_to_text(blocks)
        except Exception:
            text = ""

        if not text.strip() and not title.strip():
            return []

        # Classify evidence type based on content signals
        ev_type = self._classify_content(title, text)

        ts = edited or created or datetime.now(timezone.utc)
        base_kwargs = dict(
            source_type=self.source_type,
            source_id=f"notion-page:{page_id}",
            occurred_at=ts,
            valid_from=ts,
            summary=f"Notion page: {title}",
            raw_excerpt=text[:2000] if text else title,
            confidence=0.7,
            extraction_method="rule_based",
            user_id="user-default",
        )

        if ev_type == EvidenceType.DECISION:
            return [DecisionEvidence(
                **base_kwargs,
                option_set=[],
                chosen="",
                reasoning=text[:200] if text else "",
                structured_data={
                    "page_id": page_id, "title": title,
                    "content_length": len(text),
                    "needs_llm_analysis": len(text) > 200,
                },
            )]
        elif ev_type == EvidenceType.REFLECTION:
            return [ReflectionEvidence(
                **base_kwargs,
                topic=title,
                insight=text[:300] if text else title,
                structured_data={
                    "page_id": page_id, "title": title,
                    "content_length": len(text),
                    "needs_llm_analysis": len(text) > 200,
                },
            )]
        elif ev_type == EvidenceType.PREFERENCE:
            return [PreferenceEvidence(
                **base_kwargs,
                dimension=title[:50],
                direction="expressed",
                structured_data={
                    "page_id": page_id, "title": title,
                    "content_length": len(text),
                    "needs_llm_analysis": len(text) > 200,
                },
            )]
        else:
            return [ContextEvidence(
                **base_kwargs,
                context_category="notion_page",
                description=f"Notion page: {title}",
                structured_data={
                    "page_id": page_id, "title": title,
                    "content_length": len(text),
                    "created": str(created) if created else None,
                    "needs_llm_analysis": len(text) > 200,
                },
            )]

    def _process_database(self, db: dict, r: Any, since: Optional[datetime]) -> List[EvidenceFragment]:
        db_id = db["id"]
        title_parts = db.get("title", [])
        title = title_parts[0].get("plain_text", "(untitled)") if title_parts else "(untitled db)"

        try:
            rows = r.query_database(self.token, db_id, page_size=20)
        except Exception:
            return []

        if not rows:
            return []

        return [ContextEvidence(
            source_type=self.source_type,
            source_id=f"notion-db:{db_id}",
            occurred_at=datetime.now(timezone.utc),
            valid_from=datetime.now(timezone.utc),
            summary=f"Notion database: {title} ({len(rows)} rows)",
            confidence=0.6,
            extraction_method="api_structured",
            user_id="user-default",
            context_category="database",
            description=f"Notion database: {title}",
            structured_data={
                "database_id": db_id,
                "title": title,
                "row_count": len(rows),
                "row_titles": [r.extract_page_title(row) for row in rows[:10]],
                "needs_llm_analysis": True,
            },
        )]

    @staticmethod
    def _classify_content(title: str, text: str) -> EvidenceType:
        """Simple heuristic to classify evidence type from content."""
        combined = (title + " " + text).lower()

        decision_signals = ["选择", "决定", "chose", "decide", "vs", "对比", "优先"]
        preference_signals = ["喜欢", "prefer", "推荐", "建议", "倾向"]
        reflection_signals = ["反思", "复盘", "总结", "learnings", "回顾", "后悔"]

        if any(s in combined for s in decision_signals):
            return EvidenceType.DECISION
        if any(s in combined for s in reflection_signals):
            return EvidenceType.REFLECTION
        if any(s in combined for s in preference_signals):
            return EvidenceType.PREFERENCE
        return EvidenceType.CONTEXT

    @staticmethod
    def _parse_notion_time(time_str: str) -> Optional[datetime]:
        if not time_str:
            return None
        try:
            return datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        except ValueError:
            return None

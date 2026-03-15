"""Gmail adapter: extract decision evidence from email.

Looks for:
- Sent emails with decision language (chose, decided, going with, etc.)
- Email threads showing deliberation patterns
- Labels/folders indicating project or decision categories

Privacy: Only reads subject lines and snippets by default.
Full body reading requires explicit opt-in via read_body=True.
"""

from __future__ import annotations

import base64
import email.utils
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base import EvidenceFragment, EvidenceType, SourceAdapter
from ..models.primitives import DomainEnum


# Decision-signal keywords to filter emails
_DECISION_KEYWORDS_EN = [
    "decided", "going with", "chose", "choosing", "let's go with",
    "my pick", "I'll take", "prefer", "recommendation", "trade-off",
    "versus", "vs", "pros and cons", "option A", "option B",
]
_DECISION_KEYWORDS_ZH = [
    "决定", "选择", "选了", "倾向", "推荐", "建议", "对比",
    "权衡", "优先", "方案", "vs",
]
_ALL_KEYWORDS = _DECISION_KEYWORDS_EN + _DECISION_KEYWORDS_ZH


class GmailAdapter(SourceAdapter):
    """Extract evidence from Gmail (read-only)."""

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        max_results: int = 100,
        read_body: bool = False,
        labels: Optional[List[str]] = None,
    ):
        self._credentials_path = credentials_path
        self._max_results = max_results
        self._read_body = read_body
        self._labels = labels  # e.g. ["SENT", "IMPORTANT"]
        self._service = None

    @property
    def source_type(self) -> str:
        return "gmail"

    def _get_service(self):
        if self._service is None:
            from googleapiclient.discovery import build
            from .google_auth import get_google_credentials, GMAIL_READONLY
            creds = get_google_credentials(
                scopes=[GMAIL_READONLY],
                credentials_path=self._credentials_path,
            )
            self._service = build("gmail", "v1", credentials=creds)
        return self._service

    def check_connection(self) -> bool:
        try:
            from .google_auth import check_google_auth
            return check_google_auth(self._credentials_path)
        except Exception:
            return False

    def scan(self, since: Optional[datetime] = None) -> List[EvidenceFragment]:
        service = self._get_service()
        fragments: List[EvidenceFragment] = []

        # Build query: sent emails with decision signals
        query_parts = ["in:sent"]
        if since:
            date_str = since.strftime("%Y/%m/%d")
            query_parts.append(f"after:{date_str}")

        # Search for decision-related emails
        keyword_query = " OR ".join(f'"{kw}"' for kw in _ALL_KEYWORDS[:10])
        query_parts.append(f"({keyword_query})")

        query = " ".join(query_parts)

        try:
            results = service.users().messages().list(
                userId="me",
                q=query,
                maxResults=self._max_results,
            ).execute()
        except Exception as e:
            print(f"Gmail search failed: {e}")
            return []

        messages = results.get("messages", [])

        for msg_ref in messages:
            try:
                fragment = self._process_message(service, msg_ref["id"])
                if fragment:
                    fragments.append(fragment)
            except Exception as e:
                continue

        return fragments

    def _process_message(self, service, msg_id: str) -> Optional[EvidenceFragment]:
        """Process a single email message."""
        # Get metadata (subject, date, to/from)
        msg = service.users().messages().get(
            userId="me",
            id=msg_id,
            format="metadata" if not self._read_body else "full",
            metadataHeaders=["Subject", "Date", "To", "From"],
        ).execute()

        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        subject = headers.get("Subject", "(no subject)")
        date_str = headers.get("Date", "")
        to_addr = headers.get("To", "")
        snippet = msg.get("snippet", "")

        # Parse date
        timestamp = self._parse_email_date(date_str)

        # Check for decision signals in subject + snippet
        combined = f"{subject} {snippet}".lower()
        has_signal = any(kw.lower() in combined for kw in _ALL_KEYWORDS)

        if not has_signal:
            return None

        # Extract body if opted in
        body_excerpt = ""
        if self._read_body:
            body_excerpt = self._extract_body(msg)[:1000]

        return EvidenceFragment(
            source_type=self.source_type,
            source_id=f"gmail:{msg_id}",
            evidence_type=EvidenceType.DECISION,
            timestamp=timestamp,
            summary=f"Email: {subject[:100]}",
            raw_excerpt=body_excerpt if body_excerpt else snippet[:500],
            structured_data={
                "message_id": msg_id,
                "subject": subject,
                "to": to_addr,
                "snippet": snippet[:200],
                "needs_llm_analysis": True,
            },
            confidence=0.6,  # Email context is noisy
            extraction_method="rule_based",
        )

    @staticmethod
    def _parse_email_date(date_str: str) -> datetime:
        try:
            parsed = email.utils.parsedate_to_datetime(date_str)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except Exception:
            return datetime.now(timezone.utc)

    @staticmethod
    def _extract_body(msg: dict) -> str:
        """Extract plain text body from message payload."""
        payload = msg.get("payload", {})

        # Simple case: single part
        if payload.get("mimeType") == "text/plain":
            data = payload.get("body", {}).get("data", "")
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

        # Multipart: find text/plain
        for part in payload.get("parts", []):
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

        return ""

"""Tests for Gmail and Calendar adapters (mock-based, no real API calls)."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from twin_runtime.infrastructure.sources.gmail_adapter import GmailAdapter, _ALL_KEYWORDS
from twin_runtime.infrastructure.sources.calendar_adapter import CalendarAdapter
from twin_runtime.domain.evidence.base import EvidenceType


class TestGmailAdapter:
    def test_source_type(self):
        adapter = GmailAdapter()
        assert adapter.source_type == "gmail"

    def test_decision_keywords_exist(self):
        assert len(_ALL_KEYWORDS) > 10
        assert "decided" in _ALL_KEYWORDS
        assert "选择" in _ALL_KEYWORDS

    def test_parse_email_date(self):
        dt = GmailAdapter._parse_email_date("Thu, 13 Mar 2026 10:30:00 +0800")
        assert dt.year == 2026
        assert dt.month == 3

    def test_parse_email_date_invalid(self):
        dt = GmailAdapter._parse_email_date("invalid date")
        assert dt.year >= 2026  # Falls back to now

    @patch("twin_runtime.infrastructure.sources.gmail_adapter.GmailAdapter._get_service")
    def test_scan_returns_fragments(self, mock_service):
        # Mock Gmail API response
        mock_svc = MagicMock()
        mock_service.return_value = mock_svc

        mock_svc.users().messages().list().execute.return_value = {
            "messages": [{"id": "msg-001"}]
        }
        mock_svc.users().messages().get().execute.return_value = {
            "id": "msg-001",
            "snippet": "I decided to go with option A for the project",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Re: Project decision"},
                    {"name": "Date", "value": "Thu, 13 Mar 2026 10:30:00 +0800"},
                    {"name": "To", "value": "team@example.com"},
                ]
            }
        }

        adapter = GmailAdapter()
        adapter._service = mock_svc
        fragments = adapter.scan()

        assert len(fragments) == 1
        assert fragments[0].evidence_type == EvidenceType.DECISION
        assert "gmail:" in fragments[0].source_id

    @patch("twin_runtime.infrastructure.sources.gmail_adapter.GmailAdapter._get_service")
    def test_scan_returns_typed_decision_evidence(self, mock_service):
        mock_svc = MagicMock()
        mock_service.return_value = mock_svc
        mock_svc.users().messages().list().execute.return_value = {
            "messages": [{"id": "msg-001"}]
        }
        mock_svc.users().messages().get().execute.return_value = {
            "id": "msg-001",
            "snippet": "I decided to go with option A for the project",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Re: Project decision"},
                    {"name": "Date", "value": "Thu, 13 Mar 2026 10:30:00 +0800"},
                    {"name": "To", "value": "team@example.com"},
                ]
            }
        }
        adapter = GmailAdapter()
        adapter._service = mock_svc
        fragments = adapter.scan()
        assert len(fragments) == 1

        from twin_runtime.domain.evidence.types import DecisionEvidence
        assert isinstance(fragments[0], DecisionEvidence)
        assert fragments[0].occurred_at is not None
        assert fragments[0].valid_from is not None

    def test_extract_body_plain(self):
        import base64
        body_text = "I chose Python over TypeScript."
        encoded = base64.urlsafe_b64encode(body_text.encode()).decode()
        msg = {
            "payload": {
                "mimeType": "text/plain",
                "body": {"data": encoded}
            }
        }
        result = GmailAdapter._extract_body(msg)
        assert "Python" in result


class TestCalendarAdapter:
    def test_source_type(self):
        adapter = CalendarAdapter()
        assert adapter.source_type == "calendar"

    def test_parse_event_time(self):
        dt = CalendarAdapter._parse_event_time({"dateTime": "2026-03-15T14:00:00+08:00"})
        assert dt.year == 2026
        assert dt.month == 3

    def test_event_duration(self):
        event = {
            "start": {"dateTime": "2026-03-15T14:00:00+08:00"},
            "end": {"dateTime": "2026-03-15T15:30:00+08:00"},
        }
        assert CalendarAdapter._event_duration(event) == 90

    @patch("twin_runtime.infrastructure.sources.calendar_adapter.CalendarAdapter._get_service")
    def test_scan_returns_fragments(self, mock_service):
        mock_svc = MagicMock()
        mock_service.return_value = mock_svc

        mock_svc.events().list().execute.return_value = {
            "items": [
                {
                    "id": "evt-001",
                    "summary": "Sprint planning meeting",
                    "start": {"dateTime": "2026-03-15T10:00:00+08:00"},
                    "end": {"dateTime": "2026-03-15T11:00:00+08:00"},
                    "attendees": [{"email": "a@b.com"}, {"email": "c@d.com"}],
                },
                {
                    "id": "evt-002",
                    "summary": "1:1 with manager",
                    "start": {"dateTime": "2026-03-15T14:00:00+08:00"},
                    "end": {"dateTime": "2026-03-15T14:30:00+08:00"},
                    "attendees": [{"email": "manager@b.com"}],
                },
                # Non-decision event (should be filtered)
                {
                    "id": "evt-003",
                    "summary": "Lunch",
                    "start": {"dateTime": "2026-03-15T12:00:00+08:00"},
                    "end": {"dateTime": "2026-03-15T13:00:00+08:00"},
                },
            ] + [  # Add more to trigger pattern extraction
                {
                    "id": f"evt-{i}",
                    "summary": f"Meeting {i}",
                    "start": {"dateTime": f"2026-03-{10+i:02d}T10:00:00+08:00"},
                    "end": {"dateTime": f"2026-03-{10+i:02d}T11:00:00+08:00"},
                } for i in range(4, 10)
            ]
        }

        adapter = CalendarAdapter()
        adapter._service = mock_svc
        fragments = adapter.scan()

        # Should have planning + 1:1 events + pattern aggregate
        event_fragments = [f for f in fragments if f.source_id != "calendar:patterns"]
        pattern_fragments = [f for f in fragments if f.source_id == "calendar:patterns"]

        assert len(event_fragments) == 2  # planning + 1:1
        assert len(pattern_fragments) == 1  # aggregate pattern
        assert pattern_fragments[0].structured_metrics["total_events"] == 9

    def test_extract_patterns_too_few(self):
        adapter = CalendarAdapter()
        result = adapter._extract_patterns([{"start": {}, "end": {}}] * 3)
        assert result is None  # Too few events

    @patch("twin_runtime.infrastructure.sources.calendar_adapter.CalendarAdapter._get_service")
    def test_scan_returns_typed_behavior_evidence(self, mock_service):
        mock_svc = MagicMock()
        mock_service.return_value = mock_svc
        mock_svc.events().list().execute.return_value = {
            "items": [
                {
                    "id": "evt-001",
                    "summary": "Sprint planning meeting",
                    "start": {"dateTime": "2026-03-15T10:00:00+08:00"},
                    "end": {"dateTime": "2026-03-15T11:00:00+08:00"},
                    "attendees": [{"email": "a@b.com"}],
                },
            ] + [
                {
                    "id": f"evt-{i}",
                    "summary": f"Meeting {i}",
                    "start": {"dateTime": f"2026-03-{10+i:02d}T10:00:00+08:00"},
                    "end": {"dateTime": f"2026-03-{10+i:02d}T11:00:00+08:00"},
                } for i in range(2, 10)
            ]
        }
        adapter = CalendarAdapter()
        adapter._service = mock_svc
        fragments = adapter.scan()

        from twin_runtime.domain.evidence.types import BehaviorEvidence
        for f in fragments:
            assert isinstance(f, BehaviorEvidence)

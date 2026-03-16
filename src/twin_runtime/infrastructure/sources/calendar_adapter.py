"""Google Calendar adapter: extract behavioral evidence from calendar events.

Evidence extracted:
- Meeting patterns (frequency, duration, attendees)
- Work schedule signals (early/late, weekends)
- Decision-relevant events (interviews, reviews, planning sessions)
- Time allocation across categories
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from twin_runtime.domain.evidence.base import EvidenceFragment, EvidenceType, SourceAdapter
from twin_runtime.domain.evidence.types import BehaviorEvidence
from twin_runtime.domain.models.primitives import DomainEnum


# Keywords that signal decision-relevant calendar events
_DECISION_EVENT_KEYWORDS = [
    "review", "planning", "decision", "1:1", "interview", "strategy",
    "roadmap", "brainstorm", "retro", "retrospective", "sync",
    "评审", "规划", "面试", "战略", "复盘", "同步",
]


class CalendarAdapter(SourceAdapter):
    """Extract behavioral evidence from Google Calendar."""

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        calendar_id: str = "primary",
        lookback_days: int = 90,
    ):
        self._credentials_path = credentials_path
        self._calendar_id = calendar_id
        self._lookback_days = lookback_days
        self._service = None

    @property
    def source_type(self) -> str:
        return "calendar"

    def _get_service(self):
        if self._service is None:
            from googleapiclient.discovery import build
            from twin_runtime.infrastructure.sources.google_auth import get_google_credentials, CALENDAR_READONLY
            creds = get_google_credentials(
                scopes=[CALENDAR_READONLY],
                credentials_path=self._credentials_path,
            )
            self._service = build("calendar", "v3", credentials=creds)
        return self._service

    def check_connection(self) -> bool:
        try:
            from twin_runtime.infrastructure.sources.google_auth import check_google_auth
            return check_google_auth(self._credentials_path)
        except Exception:
            return False

    def scan(self, since: Optional[datetime] = None) -> List[EvidenceFragment]:
        service = self._get_service()
        fragments: List[EvidenceFragment] = []

        time_min = since or (datetime.now(timezone.utc) - timedelta(days=self._lookback_days))
        time_max = datetime.now(timezone.utc)

        try:
            events_result = service.events().list(
                calendarId=self._calendar_id,
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                maxResults=500,
                singleEvents=True,
                orderBy="startTime",
            ).execute()
        except Exception as e:
            print(f"Calendar fetch failed: {e}")
            return []

        events = events_result.get("items", [])

        if not events:
            return []

        # 1. Extract decision-relevant individual events
        for event in events:
            fragment = self._process_event(event)
            if fragment:
                fragments.append(fragment)

        # 2. Extract behavioral patterns from aggregate
        pattern_fragment = self._extract_patterns(events)
        if pattern_fragment:
            fragments.append(pattern_fragment)

        return fragments

    def _process_event(self, event: dict) -> Optional[EvidenceFragment]:
        """Process a single calendar event for decision evidence."""
        summary = event.get("summary", "")
        description = event.get("description", "")
        combined = f"{summary} {description}".lower()

        # Only keep events with decision signals
        has_signal = any(kw.lower() in combined for kw in _DECISION_EVENT_KEYWORDS)
        if not has_signal:
            return None

        start = self._parse_event_time(event.get("start", {}))
        attendees = [a.get("email", "") for a in event.get("attendees", [])]

        return BehaviorEvidence(
            source_type=self.source_type,
            source_id=f"calendar:{event.get('id', '')}",
            occurred_at=start,
            valid_from=start,
            summary=f"Calendar: {summary[:100]}",
            confidence=0.5,
            extraction_method="api_structured",
            user_id="user-default",
            action_type="calendar_event",
            pattern=summary,
            structured_metrics={
                "event_id": event.get("id", ""),
                "summary": summary,
                "attendee_count": len(attendees),
                "duration_minutes": self._event_duration(event),
                "is_recurring": event.get("recurringEventId") is not None,
            },
        )

    def _extract_patterns(self, events: list) -> Optional[EvidenceFragment]:
        """Extract behavioral patterns from calendar aggregate."""
        if len(events) < 5:
            return None

        # Compute pattern metrics
        total = len(events)
        meeting_counts_by_day = [0] * 7  # Mon=0 ... Sun=6
        total_duration = 0
        recurring_count = 0
        attendee_counts = []

        for event in events:
            start = self._parse_event_time(event.get("start", {}))
            if start:
                meeting_counts_by_day[start.weekday()] += 1

            dur = self._event_duration(event)
            if dur:
                total_duration += dur

            if event.get("recurringEventId"):
                recurring_count += 1

            attendees = event.get("attendees", [])
            attendee_counts.append(len(attendees))

        avg_daily = total / max(1, self._lookback_days)
        avg_duration = total_duration / max(1, total)
        avg_attendees = sum(attendee_counts) / max(1, len(attendee_counts))
        weekend_ratio = (meeting_counts_by_day[5] + meeting_counts_by_day[6]) / max(1, total)

        patterns = {
            "total_events": total,
            "avg_events_per_day": round(avg_daily, 2),
            "avg_duration_minutes": round(avg_duration, 1),
            "avg_attendees": round(avg_attendees, 1),
            "recurring_ratio": round(recurring_count / max(1, total), 2),
            "weekend_work_ratio": round(weekend_ratio, 2),
            "busiest_day": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][
                meeting_counts_by_day.index(max(meeting_counts_by_day))
            ],
        }

        return BehaviorEvidence(
            source_type=self.source_type,
            source_id="calendar:patterns",
            occurred_at=datetime.now(timezone.utc),
            valid_from=datetime.now(timezone.utc) - timedelta(days=self._lookback_days),
            summary=f"Calendar patterns: {total} events over {self._lookback_days} days",
            confidence=0.7,
            extraction_method="rule_based",
            user_id="user-default",
            action_type="calendar_patterns",
            pattern=f"{total} events, avg {avg_duration:.0f}min, busiest: {patterns['busiest_day']}",
            structured_metrics=patterns,
        )

    @staticmethod
    def _parse_event_time(time_obj: dict) -> datetime:
        """Parse event start/end time."""
        dt_str = time_obj.get("dateTime") or time_obj.get("date", "")
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, AttributeError):
            return datetime.now(timezone.utc)

    @staticmethod
    def _event_duration(event: dict) -> int:
        """Calculate event duration in minutes."""
        start = event.get("start", {})
        end = event.get("end", {})
        start_str = start.get("dateTime") or start.get("date", "")
        end_str = end.get("dateTime") or end.get("date", "")
        try:
            s = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            e = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            return int((e - s).total_seconds() / 60)
        except (ValueError, AttributeError):
            return 0

"""HeartbeatReflector — implicit reflection from Git/Calendar/Email/file signals.

Finds pending traces (no outcome recorded), infers what the user chose
from local signals, and either auto-reflects (high confidence) or queues
for manual confirmation (low confidence).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from twin_runtime.domain.models.primitives import OutcomeSource
from twin_runtime.domain.models.runtime import RuntimeDecisionTrace
from twin_runtime.domain.utils.text import extract_keywords

logger = logging.getLogger(__name__)


class InferredReflection(BaseModel):
    """A single inferred outcome from an implicit signal."""

    trace_id: str
    inferred_choice: str
    confidence: float = Field(ge=0.0, le=1.0)
    signal_source: OutcomeSource
    evidence_summary: str = ""


class HeartbeatReport(BaseModel):
    """Summary of a heartbeat run."""

    inferred: int = 0
    auto_reflected: int = 0
    queued: int = 0
    errors: int = 0


class HeartbeatReflector:
    """Implicit reflection engine: scans local signals to infer decision outcomes."""

    def __init__(
        self,
        *,
        trace_store,
        calibration_store,
        twin_store,
        experience_store,
        llm,
        user_id: str,
        auto_reflect_threshold: float = 0.7,
        pending_queue_path: Optional[str] = None,
        calendar_adapter=None,
        gmail_adapter=None,
    ):
        self._trace_store = trace_store
        self._calibration_store = calibration_store
        self._twin_store = twin_store
        self._experience_store = experience_store
        self._llm = llm
        self._user_id = user_id
        self._threshold = auto_reflect_threshold
        self._queue_path = pending_queue_path
        self._calendar_adapter = calendar_adapter
        self._gmail_adapter = gmail_adapter

    def run(self) -> HeartbeatReport:
        """Execute a heartbeat cycle: find pending → infer → auto-reflect or queue."""
        report = HeartbeatReport()

        pending = self._find_pending_traces()
        if not pending:
            return report

        inferences: List[InferredReflection] = []
        inferences.extend(self._infer_from_git_commits(pending))
        inferences.extend(self._infer_from_git_prs(pending))
        inferences.extend(self._infer_from_file_changes(pending))
        inferences.extend(self._infer_from_calendar(pending))
        inferences.extend(self._infer_from_email(pending))

        deduped = self._dedup(inferences)
        report.inferred = len(deduped)

        for inf in deduped:
            if inf.confidence >= self._threshold:
                try:
                    self._auto_reflect(inf)
                    report.auto_reflected += 1
                except Exception:
                    logger.exception("Auto-reflect failed for trace %s", inf.trace_id)
                    report.errors += 1
            else:
                try:
                    self._queue_for_confirmation(inf)
                    report.queued += 1
                except Exception:
                    logger.exception("Queue failed for trace %s", inf.trace_id)
                    report.errors += 1

        return report

    # ---------------------------------------------------------------
    # Pending trace discovery
    # ---------------------------------------------------------------

    def _find_pending_traces(self) -> List[RuntimeDecisionTrace]:
        """Find traces without outcomes that have a non-empty option_set."""
        all_ids = self._trace_store.list_traces(limit=200)
        reflected_ids = {o.trace_id for o in self._calibration_store.list_outcomes()}
        pending = []
        for tid in all_ids:
            if tid not in reflected_ids:
                try:
                    trace = self._trace_store.load_trace(tid)
                    if trace.option_set:
                        pending.append(trace)
                except Exception:
                    logger.warning("Failed to load trace %s", tid)
        return pending

    # ---------------------------------------------------------------
    # Signal inference
    # ---------------------------------------------------------------

    def _infer_from_git_commits(self, pending: List[RuntimeDecisionTrace]) -> List[InferredReflection]:
        """Match git commits from last 24h against pending trace keywords."""
        try:
            result = subprocess.run(
                ["git", "log", "--since=24 hours ago", "--no-merges", "--pretty=format:%s"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return []
        except (subprocess.SubprocessError, FileNotFoundError):
            return []

        commit_messages = result.stdout.strip().lower()
        if not commit_messages:
            return []

        return self._match_signals(
            pending, commit_messages,
            source=OutcomeSource.IMPLICIT_GIT,
            base_confidence=0.3,
            high_confidence=0.85,
            signal_label="git commit",
        )

    def _infer_from_git_prs(self, pending: List[RuntimeDecisionTrace]) -> List[InferredReflection]:
        """Match merged PRs from last 24h — higher confidence than commits."""
        try:
            result = subprocess.run(
                ["git", "log", "--merges", "--since=24 hours ago", "--pretty=format:%s"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return []
        except (subprocess.SubprocessError, FileNotFoundError):
            return []

        merge_messages = result.stdout.strip().lower()
        if not merge_messages:
            return []

        return self._match_signals(
            pending, merge_messages,
            source=OutcomeSource.IMPLICIT_GIT,
            base_confidence=0.5,
            high_confidence=0.9,
            signal_label="git merge/PR",
        )

    def _infer_from_file_changes(self, pending: List[RuntimeDecisionTrace]) -> List[InferredReflection]:
        """Match recently modified files — low confidence."""
        try:
            result = subprocess.run(
                ["find", ".", "-mtime", "-1", "-type", "f", "-not", "-path", "./.git/*"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return []
        except (subprocess.SubprocessError, FileNotFoundError):
            return []

        file_text = result.stdout.strip().lower()
        if not file_text:
            return []

        return self._match_signals(
            pending, file_text,
            source=OutcomeSource.IMPLICIT_FILE,
            base_confidence=0.2,
            high_confidence=0.5,
            signal_label="file change",
        )

    def _infer_from_calendar(self, pending: List[RuntimeDecisionTrace]) -> List[InferredReflection]:
        """Match calendar events from last 24h against pending traces."""
        if not self._calendar_adapter:
            return []
        try:
            since = datetime.now(timezone.utc) - timedelta(hours=24)
            fragments = self._calendar_adapter.scan(since=since)
            event_text = " ".join(
                f.summary.lower() for f in fragments if f.summary
            )
            if not event_text:
                return []
            return self._match_signals(
                pending, event_text,
                source=OutcomeSource.IMPLICIT_CALENDAR,
                base_confidence=0.4,
                high_confidence=0.7,
                signal_label="calendar event",
            )
        except Exception:
            logger.warning("Calendar inference failed", exc_info=True)
            return []

    def _infer_from_email(self, pending: List[RuntimeDecisionTrace]) -> List[InferredReflection]:
        """Match sent emails from last 24h against pending traces."""
        if not self._gmail_adapter:
            return []
        try:
            since = datetime.now(timezone.utc) - timedelta(hours=24)
            fragments = self._gmail_adapter.scan(since=since)
            email_text = " ".join(
                f.summary.lower() for f in fragments if f.summary
            )
            if not email_text:
                return []
            return self._match_signals(
                pending, email_text,
                source=OutcomeSource.IMPLICIT_EMAIL,
                base_confidence=0.3,
                high_confidence=0.6,
                signal_label="email",
            )
        except Exception:
            logger.warning("Email inference failed", exc_info=True)
            return []

    # ---------------------------------------------------------------
    # Signal matching engine
    # ---------------------------------------------------------------

    def _match_signals(
        self,
        pending: List[RuntimeDecisionTrace],
        signal_text: str,
        *,
        source: OutcomeSource,
        base_confidence: float,
        high_confidence: float,
        signal_label: str,
    ) -> List[InferredReflection]:
        """Match pending trace options against signal text."""
        results: List[InferredReflection] = []
        for trace in pending:
            best_option, match_score = self._best_option_match(trace, signal_text)
            if best_option and match_score > 0:
                # Scale confidence based on match quality
                confidence = base_confidence + (high_confidence - base_confidence) * min(match_score, 1.0)
                results.append(InferredReflection(
                    trace_id=trace.trace_id,
                    inferred_choice=best_option,
                    confidence=round(confidence, 2),
                    signal_source=source,
                    evidence_summary=f"Matched via {signal_label}: '{best_option}' found in signals",
                ))
        return results

    def _best_option_match(
        self, trace: RuntimeDecisionTrace, signal_text: str,
    ) -> tuple:
        """Find the best matching option from trace.option_set against signal text.

        Returns (best_option, match_score) where score is 0-1.

        Scoring strategy:
        - Direct option text match → 1.0 (strongest signal)
        - Option-specific keywords weighted 0.7, trace query keywords 0.3.
          This prevents trace keywords (which contain ALL options) from
          giving every option the same baseline score.
        """
        best_option = None
        best_score = 0.0

        trace_keywords = extract_keywords(trace.query)
        # Remove option texts from trace_keywords to avoid cross-contamination:
        # if query is "Redis or Memcached", both are in trace_keywords, so
        # matching against either option gives the same trace_keyword score.
        option_texts_lower = {opt.lower() for opt in trace.option_set}

        for option in trace.option_set:
            option_lower = option.lower()

            # Direct option text match — strongest signal
            if option_lower in signal_text:
                score = 1.0
            else:
                option_keywords = extract_keywords(option)
                # Filter trace_keywords: remove keywords that are substrings of
                # any option text (they don't help discriminate between options)
                filtered_trace_kw = [
                    kw for kw in trace_keywords
                    if not any(kw.lower() in opt for opt in option_texts_lower)
                ]

                # Separate scoring: option keywords (weight 0.7) + context keywords (weight 0.3)
                opt_matches = sum(1 for kw in option_keywords if kw.lower() in signal_text) if option_keywords else 0
                ctx_matches = sum(1 for kw in filtered_trace_kw if kw.lower() in signal_text) if filtered_trace_kw else 0

                opt_score = (opt_matches / len(option_keywords)) if option_keywords else 0.0
                ctx_score = (ctx_matches / len(filtered_trace_kw)) if filtered_trace_kw else 0.0

                score = 0.7 * opt_score + 0.3 * ctx_score

            if score > best_score:
                best_score = score
                best_option = option

        return best_option, best_score

    # ---------------------------------------------------------------
    # Actions
    # ---------------------------------------------------------------

    def _auto_reflect(self, inf: InferredReflection) -> None:
        """Record outcome + generate reflection for high-confidence inferences.

        Loads a fresh exp_lib per call so that a failure in one auto_reflect
        does not leave dirty in-memory state visible to subsequent calls.
        Only saves exp_lib if the update actually mutated it.
        """
        from twin_runtime.application.calibration.outcome_tracker import record_outcome
        from twin_runtime.application.calibration.reflection_generator import ReflectionGenerator
        from twin_runtime.application.calibration.experience_updater import ExperienceUpdater

        twin = self._twin_store.load_state(self._user_id)

        # Step 1: record_outcome (writes to calibration_store — committed on success)
        outcome, _update = record_outcome(
            trace_id=inf.trace_id,
            actual_choice=inf.inferred_choice,
            source=inf.signal_source,
            twin=twin,
            trace_store=self._trace_store,
            calibration_store=self._calibration_store,
        )

        # Step 2: reflection + experience update (load fresh, save only if mutated)
        exp_lib = self._experience_store.load()
        trace = self._trace_store.load_trace(inf.trace_id)
        reflection = ReflectionGenerator(self._llm).process(
            trace, inf.inferred_choice, exp_lib,
        )
        if reflection.new_entry:
            ExperienceUpdater().update(reflection.new_entry, exp_lib)
            self._experience_store.save(exp_lib)
        elif reflection.action == "confirmed":
            # confirmation_count may have been bumped by ReflectionGenerator._handle_hit
            self._experience_store.save(exp_lib)

    def _queue_for_confirmation(self, inf: InferredReflection) -> None:
        """Write inference to pending queue file using atomic write."""
        if self._queue_path is None:
            logger.warning("No pending_queue_path configured, skipping queue for %s", inf.trace_id)
            return

        queue_dir = os.path.dirname(self._queue_path)
        if queue_dir:
            os.makedirs(queue_dir, exist_ok=True)

        # Load existing queue
        pending: List[Dict] = []
        if os.path.exists(self._queue_path):
            try:
                with open(self._queue_path) as f:
                    pending = json.load(f)
            except (json.JSONDecodeError, OSError):
                pending = []

        # Append new inference
        pending.append(inf.model_dump(mode="json"))

        # Atomic write: tmpfile + rename
        fd, tmp_path = tempfile.mkstemp(
            dir=queue_dir or ".", suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(pending, f, indent=2, default=str)
            os.rename(tmp_path, self._queue_path)
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ---------------------------------------------------------------
    # Deduplication
    # ---------------------------------------------------------------

    @staticmethod
    def _dedup(inferences: List[InferredReflection]) -> List[InferredReflection]:
        """Keep only the highest-confidence inference per trace_id."""
        best: Dict[str, InferredReflection] = {}
        for inf in inferences:
            existing = best.get(inf.trace_id)
            if existing is None or inf.confidence > existing.confidence:
                best[inf.trace_id] = inf
        return list(best.values())

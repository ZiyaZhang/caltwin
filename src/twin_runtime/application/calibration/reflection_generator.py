"""Reflection Generator — post-outcome reflection to confirm or create experience entries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import uuid

from pydantic import BaseModel

from twin_runtime.domain.models.experience import ExperienceEntry, ExperienceLibrary
from twin_runtime.domain.models.runtime import RuntimeDecisionTrace
from twin_runtime.domain.ports.llm_port import LLMPort
from twin_runtime.application.calibration.fidelity_evaluator import choice_similarity
from twin_runtime.domain.utils.text import extract_keywords


class ReflectionResult(BaseModel):
    action: str  # "confirmed" | "generated"
    was_correct: bool
    confirmed_entry_id: Optional[str] = None
    new_entry: Optional[ExperienceEntry] = None


class ReflectionGenerator:
    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    def process(
        self,
        trace: RuntimeDecisionTrace,
        ground_truth: str,
        exp_lib: ExperienceLibrary,
    ) -> ReflectionResult:
        was_correct = self._check_correct(trace, ground_truth)

        if was_correct:
            return self._handle_hit(trace, exp_lib)
        else:
            return self._handle_miss(trace, ground_truth)

    def _check_correct(self, trace: RuntimeDecisionTrace, ground_truth: str) -> bool:
        """Use same logic as outcome_tracker: extract prediction_ranking from
        highest-confidence head assessment, then call choice_similarity."""
        head_assessments = sorted(
            trace.head_assessments, key=lambda h: h.confidence, reverse=True
        )
        ranking = head_assessments[0].option_ranking if head_assessments else []
        _score, rank = choice_similarity(ranking, ground_truth)
        return rank == 1  # Hit = rank 1

    def _handle_hit(
        self, trace: RuntimeDecisionTrace, exp_lib: ExperienceLibrary
    ) -> ReflectionResult:
        """CF-hit: search entries, confirm best match. 0 LLM calls."""
        keywords = extract_keywords(trace.query)
        matches = exp_lib.search_entries(keywords, top_k=1)

        if matches:
            best = matches[0]
            best.confirmation_count += 1
            best.last_confirmed = datetime.now(timezone.utc)
            return ReflectionResult(
                action="confirmed",
                was_correct=True,
                confirmed_entry_id=best.id,
            )

        return ReflectionResult(action="confirmed", was_correct=True)

    def _handle_miss(
        self, trace: RuntimeDecisionTrace, ground_truth: str
    ) -> ReflectionResult:
        """CF-miss: extract new ExperienceEntry via LLM. 1 LLM call."""
        new_entry = self._generate_entry(trace, ground_truth)
        return ReflectionResult(
            action="generated",
            was_correct=False,
            new_entry=new_entry,
        )

    def _generate_entry(
        self, trace: RuntimeDecisionTrace, ground_truth: str
    ) -> ExperienceEntry:
        """1 LLM call to extract lesson from the miss."""
        system = (
            "You are analyzing a decision where the twin's recommendation was wrong. "
            "Extract a reusable lesson. Respond with JSON: "
            '{"insight": "...", "scenario_type": ["keyword1", "keyword2", ...], '
            '"applicable_when": "...", "not_applicable_when": "..."}'
        )
        user = (
            f"Query: {trace.query}\n"
            f"Twin recommended: {trace.final_decision}\n"
            f"User actually chose: {ground_truth}\n"
            f"Twin reasoning: {(trace.output_text or '')[:500]}"
        )

        result = self._llm.ask_json(system, user, max_tokens=512)

        domain = trace.activated_domains[0] if trace.activated_domains else None

        return ExperienceEntry(
            id=f"refl-{uuid.uuid4().hex[:8]}",
            scenario_type=result.get("scenario_type", None) or extract_keywords(trace.query),
            insight=result.get("insight", f"Twin chose wrong. Actual: {ground_truth}"),
            applicable_when=result.get("applicable_when", "Similar decisions"),
            not_applicable_when=result.get("not_applicable_when", ""),
            domain=domain,
            source_trace_id=trace.trace_id,
            was_correct=False,
            weight=1.0,
            entry_kind="reflection",
            created_at=datetime.now(timezone.utc),
        )

"""ConsistencyChecker: post-synthesis S2 check against experience library."""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from twin_runtime.domain.models.experience import ExperienceLibrary
from twin_runtime.domain.models.runtime import RuntimeDecisionTrace
from twin_runtime.domain.ports.llm_port import LLMPort


class ConsistencyResult(BaseModel):
    is_consistent: bool
    note: str = ""
    confidence_penalty: float = Field(default=0.0, ge=0.0, le=0.2)
    conflicting_experience_ids: List[str] = Field(default_factory=list)


class ConsistencyChecker:
    def __init__(self, llm: LLMPort):
        self._llm = llm

    def check(
        self,
        trace: RuntimeDecisionTrace,
        exp_lib: ExperienceLibrary,
    ) -> ConsistencyResult:
        # 1. Extract keywords from query
        keywords = trace.query.lower().split()[:10]

        # 2. Search for relevant entries
        matches = exp_lib.search_entries(keywords, top_k=3)
        if not matches:
            return ConsistencyResult(is_consistent=True, note="No relevant experience found.")

        # 3. Deterministic pre-check
        decision_lower = trace.final_decision.lower()
        conflicting: List[str] = []
        for entry in matches:
            if entry.weight >= 0.8 and entry.insight:
                # Check if insight contradicts the decision
                # Simple heuristic: if insight mentions a different option
                insight_lower = entry.insight.lower()
                if self._deterministic_contradiction(decision_lower, insight_lower):
                    conflicting.append(entry.id)

        if not conflicting:
            return ConsistencyResult(is_consistent=True, note="No contradictions found.")

        # 4. LLM fine-grained check for ambiguous cases
        return self._llm_check(trace, matches, conflicting)

    def _deterministic_contradiction(self, decision: str, insight: str) -> bool:
        """Simple check: insight contains negation patterns about the recommended option."""
        negation_patterns = ["avoid", "\u4e0d\u8981", "\u4e0d\u63a8\u8350", "should not", "shouldn't", "don't"]
        for pattern in negation_patterns:
            if pattern in insight:
                return True
        return False

    def _llm_check(
        self,
        trace: RuntimeDecisionTrace,
        matches: list,
        conflicting_ids: List[str],
    ) -> ConsistencyResult:
        """LLM call to check if experience truly contradicts decision."""
        experience_text = "\n".join(
            f"- [{e.id}] {e.insight} (weight={e.weight})"
            for e in matches
        )

        system = (
            "You are checking if a decision is consistent with past experience. "
            "Respond with JSON: {\"is_consistent\": bool, \"note\": \"explanation\", "
            "\"confidence_penalty\": 0.0-0.2}"
        )
        user = (
            f"Decision: {trace.final_decision}\n"
            f"Query: {trace.query}\n\n"
            f"Past experience:\n{experience_text}\n\n"
            "Is the decision consistent with past experience?"
        )

        result = self._llm.ask_json(system, user, max_tokens=256)

        return ConsistencyResult(
            is_consistent=result.get("is_consistent", True),
            note=result.get("note", ""),
            confidence_penalty=min(0.2, max(0.0, float(result.get("confidence_penalty", 0.1)))),
            conflicting_experience_ids=conflicting_ids,
        )

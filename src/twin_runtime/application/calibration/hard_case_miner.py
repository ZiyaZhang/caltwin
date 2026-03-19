"""HardCaseMiner — systematic failure pattern detection.

Analyzes traces where the twin's prediction was wrong,
groups failures by domain, and uses LLM to extract reusable patterns.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import List

from twin_runtime.domain.models.calibration import OutcomeRecord
from twin_runtime.domain.models.experience import PatternInsight
from twin_runtime.domain.models.runtime import RuntimeDecisionTrace
from twin_runtime.domain.ports.llm_port import LLMPort


class HardCaseMiner:
    """Detect systematic failure patterns across evaluation misses."""

    def __init__(self, llm: LLMPort, min_failures: int = 3):
        self._llm = llm
        self._min_failures = min_failures

    def mine(
        self,
        traces: List[RuntimeDecisionTrace],
        outcomes: List[OutcomeRecord],
    ) -> List[PatternInsight]:
        """Analyze failures and extract patterns.

        Joins traces + outcomes by trace_id, filters to failures
        (prediction_rank != 1), groups by domain, and analyzes each
        group with sufficient failures.
        """
        # Build trace lookup
        trace_map = {t.trace_id: t for t in traces}

        # Find failures: outcomes where prediction was wrong
        failures = []
        for outcome in outcomes:
            if outcome.domain is None:
                continue  # standalone outcomes without domain can't be grouped
            if outcome.prediction_rank is not None and outcome.prediction_rank != 1:
                trace = trace_map.get(outcome.trace_id)
                if trace:
                    failures.append((trace, outcome))

        if len(failures) < self._min_failures:
            return []

        # Group by domain (P2: independent grouping)
        groups = defaultdict(list)
        for trace, outcome in failures:
            groups[outcome.domain].append((trace, outcome))

        # Analyze each group with sufficient failures
        patterns: List[PatternInsight] = []
        for domain, group in groups.items():
            if len(group) < 2:  # Need at least 2 failures per domain
                continue
            pattern = self._analyze_group(domain, group)
            if pattern:
                patterns.append(pattern)

        return patterns

    def _analyze_group(self, domain, group) -> PatternInsight | None:
        """Use LLM to extract a pattern from a group of failures."""
        # Build summary for LLM
        case_summaries = []
        trace_ids = []
        for trace, outcome in group[:10]:  # Cap at 10 per group
            case_summaries.append(
                f"- Query: {trace.query[:100]}\n"
                f"  Twin predicted: {trace.final_decision[:100]}\n"
                f"  User chose: {outcome.actual_choice}\n"
                f"  Rank: {outcome.prediction_rank}"
            )
            trace_ids.append(trace.trace_id)

        system = (
            "You are analyzing decision-making failures to find systematic patterns. "
            "Given a set of cases where the twin's prediction was wrong, identify "
            "the common pattern. Respond with JSON: "
            '{"pattern_description": "...", "systematic_bias": "...", '
            '"correction_strategy": "..."}'
        )
        user = (
            f"Domain: {domain.value}\n"
            f"Number of failures: {len(group)}\n\n"
            "Cases:\n" + "\n".join(case_summaries)
        )

        try:
            result = self._llm.ask_json(system, user, max_tokens=512)
        except Exception:
            return None

        return PatternInsight(
            id=f"pat-{uuid.uuid4().hex[:8]}",
            pattern_description=result.get("pattern_description", "Unknown pattern"),
            systematic_bias=result.get("systematic_bias", "Unknown bias"),
            correction_strategy=result.get("correction_strategy", "Review and adjust"),
            affected_trace_ids=trace_ids,
            domains=[domain],
            weight=2.0,
            created_at=datetime.now(timezone.utc),
        )

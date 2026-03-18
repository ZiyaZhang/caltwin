"""Conflict Arbiter: detect and classify inter-head conflicts, produce ConflictReport.

Conflict types:
- preference: heads agree on facts, disagree on value ranking
- belief: heads agree on values, disagree on factual predictions
- evidence_credibility: heads weight same evidence differently
- mixed: multiple conflict types co-occur
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from twin_runtime.domain.models.primitives import ConflictType, DomainEnum, MergeStrategy
from twin_runtime.domain.models.runtime import ConflictReport, HeadAssessment


def _detect_utility_conflict(assessments: List[HeadAssessment]) -> tuple:
    """Returns (axis_conflicts, ranking_divergences) as separate lists."""
    if len(assessments) < 2:
        return [], []

    axis_conflicts = []
    ranking_divergences = []

    # Strategy 1: same-axis score disagreement
    all_axes = set()
    for a in assessments:
        for k, v in a.utility_decomposition.items():
            if isinstance(v, (int, float)):
                all_axes.add(k)
    for axis in all_axes:
        values = []
        for a in assessments:
            v = a.utility_decomposition.get(axis)
            if isinstance(v, (int, float)):
                values.append(float(v))
        if len(values) >= 2 and (max(values) - min(values)) > 0.3:
            axis_conflicts.append(axis)

    # Strategy 2: ranking inversion detection
    for i in range(len(assessments)):
        for j in range(i + 1, len(assessments)):
            r1 = assessments[i].option_ranking
            r2 = assessments[j].option_ranking
            if not r1 or not r2 or len(r1) < 2 or len(r2) < 2:
                continue
            top1, top2 = r1[0], r2[0]
            if top1 != top2:
                try:
                    rank_of_top1_in_r2 = r2.index(top1) + 1
                except ValueError:
                    rank_of_top1_in_r2 = len(r2)
                if rank_of_top1_in_r2 > 1:
                    ranking_divergences.append(
                        f"{assessments[i].domain.value}↔{assessments[j].domain.value}"
                    )

    return axis_conflicts, ranking_divergences


def _classify_conflict(
    axis_conflicts: List[str],
    ranking_divergences: List[str],
) -> List[ConflictType]:
    if axis_conflicts and ranking_divergences:
        return [ConflictType.MIXED]
    elif axis_conflicts:
        return [ConflictType.PREFERENCE]
    elif ranking_divergences:
        return [ConflictType.BELIEF]
    else:
        return [ConflictType.PREFERENCE]


def arbitrate(assessments: List[HeadAssessment]) -> Optional[ConflictReport]:
    if len(assessments) <= 1:
        return None

    axis_conflicts, ranking_divergences = _detect_utility_conflict(assessments)

    if not axis_conflicts and not ranking_divergences:
        return None

    conflict_types = _classify_conflict(axis_conflicts, ranking_divergences)
    activated = [a.domain for a in assessments]

    has_preference = ConflictType.PREFERENCE in conflict_types or ConflictType.MIXED in conflict_types
    has_belief = ConflictType.BELIEF in conflict_types

    resolvable = not has_preference
    needs_clarification = has_preference
    needs_evidence = has_belief

    if needs_clarification:
        strategy = MergeStrategy.CLARIFY
    elif resolvable:
        strategy = MergeStrategy.AUTO_MERGE
    else:
        strategy = MergeStrategy.CLARIFY

    return ConflictReport(
        report_id=str(uuid.uuid4()),
        activated_heads=activated,
        conflict_types=conflict_types,
        utility_conflict_axes=axis_conflicts,
        ranking_divergence_pairs=ranking_divergences,
        belief_conflict_axes=[],
        evidence_conflict_sources=[],
        resolvable_by_system=resolvable,
        requires_user_clarification=needs_clarification,
        requires_more_evidence=needs_evidence,
        final_merge_strategy=strategy,
    )

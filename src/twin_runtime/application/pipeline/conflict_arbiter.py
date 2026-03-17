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


def _detect_ranking_disagreement(assessments: List[HeadAssessment]) -> bool:
    """Check if heads disagree on the top-ranked option."""
    if len(assessments) < 2:
        return False
    tops = [a.option_ranking[0] for a in assessments]
    return len(set(tops)) > 1


def _detect_utility_conflict(assessments: List[HeadAssessment]) -> List[str]:
    """Detect utility conflicts across heads.

    Two detection strategies:
    1. Same-axis disagreement: if heads share an axis name and differ by >0.3
    2. Cross-domain ranking inversion: if heads rank options in significantly
       different order, flag as ranking_divergence conflict
    """
    if len(assessments) < 2:
        return []

    conflict_axes = []

    # Strategy 1: same-axis score disagreement (original logic)
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
            conflict_axes.append(axis)

    # Strategy 2: ranking inversion detection
    for i in range(len(assessments)):
        for j in range(i + 1, len(assessments)):
            r1 = assessments[i].option_ranking
            r2 = assessments[j].option_ranking
            if not r1 or not r2:
                continue
            if len(r1) >= 2 and len(r2) >= 2:
                top1 = r1[0]
                top2 = r2[0]
                if top1 != top2:
                    try:
                        rank_of_top1_in_r2 = r2.index(top1) + 1
                    except ValueError:
                        rank_of_top1_in_r2 = len(r2)
                    if rank_of_top1_in_r2 > 1:
                        conflict_axes.append(
                            f"ranking_divergence({assessments[i].domain.value}↔{assessments[j].domain.value})"
                        )

    return conflict_axes


def _classify_conflict(
    assessments: List[HeadAssessment],
    utility_axes: List[str],
) -> List[ConflictType]:
    """Determine conflict type(s)."""
    # Simple heuristic for v0.1:
    # - If utility axes conflict but rankings partially agree -> preference
    # - If rankings completely differ but utility axes don't -> belief
    # - Default to mixed if both
    ranking_conflict = _detect_ranking_disagreement(assessments)

    if utility_axes and ranking_conflict:
        return [ConflictType.MIXED]
    elif utility_axes:
        return [ConflictType.PREFERENCE]
    elif ranking_conflict:
        return [ConflictType.BELIEF]
    else:
        return [ConflictType.PREFERENCE]


def arbitrate(assessments: List[HeadAssessment]) -> Optional[ConflictReport]:
    """Produce a ConflictReport if there are inter-head conflicts. Returns None if single head or no conflict."""
    if len(assessments) <= 1:
        return None

    ranking_conflict = _detect_ranking_disagreement(assessments)
    utility_axes = _detect_utility_conflict(assessments)

    if not ranking_conflict and not utility_axes:
        return None  # Heads agree

    conflict_types = _classify_conflict(assessments, utility_axes)
    activated = [a.domain for a in assessments]

    # Resolution policy per spec
    has_preference = ConflictType.PREFERENCE in conflict_types or ConflictType.MIXED in conflict_types
    has_belief = ConflictType.BELIEF in conflict_types

    resolvable = not has_preference  # Preference conflicts need user input
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
        utility_conflict_axes=utility_axes,
        belief_conflict_axes=[],  # v0.1: no belief decomposition yet
        evidence_conflict_sources=[],
        resolvable_by_system=resolvable,
        requires_user_clarification=needs_clarification,
        requires_more_evidence=needs_evidence,
        final_merge_strategy=strategy,
    )

"""Top-level runtime pipeline: query → SituationFrame → HeadAssessments → ConflictReport → Trace."""

from __future__ import annotations

from typing import List, Optional

from ..models.runtime import RuntimeDecisionTrace
from ..models.twin_state import TwinState
from .situation_interpreter import interpret_situation
from .head_activator import activate_heads
from .conflict_arbiter import arbitrate
from .decision_synthesizer import synthesize


def run(
    query: str,
    option_set: List[str],
    twin: TwinState,
) -> RuntimeDecisionTrace:
    """Execute the full runtime pipeline.

    Args:
        query: The decision scenario / question
        option_set: Explicit options to evaluate
        twin: The canonical TwinState

    Returns:
        RuntimeDecisionTrace with full audit trail
    """
    # 1. Situation Interpreter
    frame = interpret_situation(query, twin)

    # 2. Head Activation (Step A — structured only)
    assessments = activate_heads(query, option_set, frame, twin)

    # 3. Conflict Arbiter
    conflict = arbitrate(assessments)

    # 4. Decision Synthesis (Step A merge + Step B surface realization)
    trace = synthesize(query, option_set, frame, assessments, conflict, twin)

    return trace

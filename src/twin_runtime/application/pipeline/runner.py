"""Top-level runtime pipeline: query -> decision trace.

Backward-compatible entry point. Delegates to the runtime orchestrator
for full S1/S2 routing semantics.
"""

from __future__ import annotations

from typing import List, Optional

from twin_runtime.domain.models.planner import EnrichedActivationContext
from twin_runtime.domain.models.runtime import RuntimeDecisionTrace
from twin_runtime.domain.models.twin_state import TwinState
from twin_runtime.domain.ports.llm_port import LLMPort
from twin_runtime.domain.ports.evidence_store import EvidenceStore
from twin_runtime.application.pipeline.situation_interpreter import interpret_situation
from twin_runtime.application.pipeline.head_activator import activate_heads
from twin_runtime.application.pipeline.conflict_arbiter import arbitrate
from twin_runtime.application.pipeline.decision_synthesizer import synthesize
from twin_runtime.application.planner.memory_access_planner import plan_memory_access


def run(
    query: str,
    option_set: List[str],
    twin: TwinState,
    *,
    llm: Optional[LLMPort] = None,
    evidence_store: Optional[EvidenceStore] = None,
    micro_calibrate: bool = False,
) -> RuntimeDecisionTrace:
    """Backward-compatible entry point. Delegates to orchestrator for full S1/S2 semantics."""
    from twin_runtime.application.orchestrator.runtime_orchestrator import run as orchestrator_run
    return orchestrator_run(
        query=query, option_set=option_set, twin=twin,
        llm=llm, evidence_store=evidence_store, micro_calibrate=micro_calibrate,
    )

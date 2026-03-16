"""Backward-compat shim."""
from twin_runtime.application.pipeline.situation_interpreter import *  # noqa: F401,F403
from twin_runtime.application.pipeline.situation_interpreter import (  # noqa: F401
    _keyword_scores,
    _llm_interpret,
    _apply_routing_policy,
    _DOMAIN_KEYWORDS,
    _INTERPRET_SYSTEM,
    _DOMINANCE_GAP,
    _MULTI_DOMAIN_GAP,
    _AMBIGUITY_THRESHOLD,
    _CONFIDENCE_THRESHOLD,
)

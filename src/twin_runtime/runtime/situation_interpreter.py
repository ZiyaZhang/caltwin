"""Backward-compat shim."""
from twin_runtime.application.pipeline.situation_interpreter import *  # noqa: F401,F403
from twin_runtime.application.pipeline.situation_interpreter import (  # noqa: F401
    _keyword_scores_from_twin,
    _llm_interpret,
    _apply_routing_policy,
    _LEGACY_KEYWORDS,
    _INTERPRET_SYSTEM,
    _SITUATION_SCHEMA,
    _DOMINANCE_GAP,
    _MULTI_DOMAIN_GAP,
    _AMBIGUITY_THRESHOLD,
    _CONFIDENCE_THRESHOLD,
)

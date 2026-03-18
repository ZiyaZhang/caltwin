"""Deterministic scope guard — pre-LLM boundary check using alias keywords."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from twin_runtime.domain.models.twin_state import ScopeDeclaration


# Alias map: scope label -> query-language keywords (CN + EN)
_SCOPE_ALIASES: Dict[str, List[str]] = {
    # restricted_use_cases
    "simulate_private_conversations": ["private conversation", "impersonate", "pretend to be", "假装", "模拟对话"],
    "make_binding_commitments": ["promise", "commit", "guarantee", "承诺", "保证"],
    "high_confidence_in_unmodeled_domains": ["medical", "legal", "diagnose", "法律", "医疗", "诊断"],
    # non_modeled_capabilities
    "live_emotion_state": ["how do i feel", "my emotions", "我现在的情绪", "心情"],
    "aesthetic_taste_full_fidelity": ["aesthetic", "beauty", "审美"],
    "intimate_tone_replication": ["intimate", "romantic tone", "亲密"],
    "trauma_sensitive_responses": ["trauma", "abuse", "创伤", "虐待"],
    "verbatim_autobiographical_memory": ["remember when i", "recall exactly", "你还记得"],
    "identity_performance_in_private": ["act as me", "pretend you're me", "替我说"],
}


@dataclass
class ScopeGuardResult:
    """Structured result from deterministic scope guard."""
    restricted_hit: bool = False
    non_modeled_hit: bool = False
    matched_terms: List[str] = field(default_factory=list)

    @property
    def triggered(self) -> bool:
        return self.restricted_hit or self.non_modeled_hit


def deterministic_scope_guard(
    query: str,
    scope: ScopeDeclaration,
) -> ScopeGuardResult:
    """Pre-LLM scope check using keyword alias matching.

    Returns structured result distinguishing restricted vs non_modeled hits.
    """
    result = ScopeGuardResult()
    q_lower = query.lower()

    for label in scope.restricted_use_cases:
        aliases = _SCOPE_ALIASES.get(label, [label.replace("_", " ")])
        for alias in aliases:
            if alias.lower() in q_lower:
                result.restricted_hit = True
                result.matched_terms.append(f"restricted:{label}={alias}")
                break

    for label in scope.non_modeled_capabilities:
        aliases = _SCOPE_ALIASES.get(label, [label.replace("_", " ")])
        for alias in aliases:
            if alias.lower() in q_lower:
                result.non_modeled_hit = True
                result.matched_terms.append(f"non_modeled:{label}={alias}")
                break

    return result

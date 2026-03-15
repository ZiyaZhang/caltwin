"""Persona Compiler: evidence fragments → TwinState.

The compiler aggregates EvidenceFragments from multiple sources
and produces/updates a TwinState through LLM-assisted extraction.
"""

from .compiler import PersonaCompiler

__all__ = ["PersonaCompiler"]

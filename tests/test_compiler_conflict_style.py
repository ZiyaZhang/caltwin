"""Tests for ConflictStyle enum/prompt alignment."""
import pytest
from twin_runtime.domain.models.primitives import ConflictStyle


class TestConflictStyleEnum:
    def test_all_prompt_values_are_valid(self):
        prompt_values = ["direct", "avoidant", "collaborative", "competitive", "accommodating", "delayed", "adaptive"]
        for val in prompt_values:
            ConflictStyle(val)

    def test_collaborative(self):
        assert ConflictStyle("collaborative") == ConflictStyle.COLLABORATIVE

    def test_competitive(self):
        assert ConflictStyle("competitive") == ConflictStyle.COMPETITIVE

    def test_accommodating(self):
        assert ConflictStyle("accommodating") == ConflictStyle.ACCOMMODATING

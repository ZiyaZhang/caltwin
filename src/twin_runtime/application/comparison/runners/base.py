"""Base runner interface for A/B comparison."""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from twin_runtime.application.comparison.schemas import RunnerOutput, ComparisonScenario
    from twin_runtime.domain.models.twin_state import TwinState


class BaseRunner(abc.ABC):
    """Abstract base class for comparison runners."""

    @property
    @abc.abstractmethod
    def runner_id(self) -> str:
        """Unique identifier for this runner."""

    @abc.abstractmethod
    def run_scenario(
        self,
        scenario: "ComparisonScenario",
        twin: "TwinState",
    ) -> "RunnerOutput":
        """Run a single scenario and return the output."""

"""Data models for A/B baseline comparison."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class ComparisonScenario(BaseModel):
    """A single decision scenario for comparison."""

    scenario_id: str = Field(min_length=1)
    domain: str
    query: str
    options: List[str] = Field(min_length=2)
    ground_truth: str
    tags: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_ground_truth(self) -> "ComparisonScenario":
        if self.ground_truth != "REFUSE" and self.ground_truth not in self.options:
            raise ValueError(
                f"ground_truth '{self.ground_truth}' must be 'REFUSE' or one of {self.options}"
            )
        return self


class ScenarioSet(BaseModel):
    """A collection of comparison scenarios."""

    name: str = Field(default="default")
    scenarios: List[ComparisonScenario] = Field(min_length=1)

    @classmethod
    def load(cls, path: Path) -> "ScenarioSet":
        """Load scenarios from a JSON file."""
        import json

        data = json.loads(path.read_text())
        if isinstance(data, list):
            return cls(scenarios=data)
        return cls.model_validate(data)


class RunnerOutput(BaseModel):
    """Output from a single runner on a single scenario."""

    runner_id: str
    scenario_id: str
    chosen: str
    is_correct: bool
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    uncertainty: float = Field(default=0.0, ge=0.0, le=1.0)
    latency_ms: float = Field(default=0.0, ge=0.0)
    raw_response: str = Field(default="")
    notes: str = Field(default="")


class DomainBreakdown(BaseModel):
    """Per-domain metrics for a runner."""

    domain: str
    cf_score: float
    count: int
    correct: int


class AggregateMetrics(BaseModel):
    """Aggregate metrics for a single runner across all scenarios.

    cf_score is computed on non-REFUSE scenarios only (same denominator
    for all runners). Abstention performance is reported separately via
    refuse_correct / refuse_total.
    """

    runner_id: str
    cf_score: float = Field(ge=0.0, le=1.0)
    mean_uncertainty: Optional[float] = Field(default=None, description="None when no runner populates uncertainty")
    mean_latency_ms: float = Field(default=0.0, ge=0.0)
    total: int = 0
    correct: int = 0
    refuse_total: int = Field(default=0, description="Number of REFUSE scenarios")
    refuse_correct: int = Field(default=0, description="Correctly refused/abstained")
    domain_breakdown: List[DomainBreakdown] = Field(default_factory=list)
    pairwise_deltas: Dict[str, float] = Field(default_factory=dict)


class ComparisonReport(BaseModel):
    """Full comparison report across all runners and scenarios."""

    report_id: str = Field(default_factory=lambda: f"cmp-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    scenario_set_name: str = Field(default="default")
    runner_outputs: Dict[str, List[RunnerOutput]] = Field(default_factory=dict)
    aggregates: Dict[str, AggregateMetrics] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

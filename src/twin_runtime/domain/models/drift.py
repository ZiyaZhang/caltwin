"""Drift detection models."""
from __future__ import annotations
from datetime import datetime
from typing import List, Literal, Optional, Tuple
from pydantic import BaseModel, Field


class DriftSignal(BaseModel):
    dimension: str
    dimension_type: Literal["domain", "axis"]
    direction: str
    magnitude: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    recent_window: Tuple[datetime, datetime]
    historical_window: Tuple[datetime, datetime]
    metric_used: str


class DriftReport(BaseModel):
    report_id: str
    twin_state_version: str
    as_of: datetime
    recent_window_days: int = 30
    historical_window_days: int = 180
    domain_signals: List[DriftSignal] = Field(default_factory=list)
    axis_signals: List[DriftSignal] = Field(default_factory=list)
    summary: str = ""

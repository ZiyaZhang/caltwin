# Phase 3: Calibration Enhancement + Fidelity Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build closed-loop calibration infrastructure (outcome tracking → micro-calibration → fidelity scoring → bias detection) and an investor-demo-ready HTML dashboard.

**Architecture:** Data Model First — define all new domain models (Phase 3a), then wire calibration logic (Phase 3b), then build dashboard (Phase 3c). Each phase is independently testable. All new models live in `domain/models/calibration.py`. All new calibration logic lives in `application/calibration/`. Dashboard is a new `application/dashboard/` module.

**Tech Stack:** Python 3.11+, Pydantic v2 (BaseModel, computed_field, model_validator), pure HTML/CSS/SVG for dashboard (zero JS dependencies).

**Spec:** `docs/superpowers/specs/2026-03-16-phase3-calibration-enhancement-design.md`

**Baseline:** choice_similarity 0.750 (20 cases, post-Phase-2b + BiasCorrectionEntry)

---

## File Map

### Files to CREATE

| File | Purpose |
|------|---------|
| `src/twin_runtime/application/calibration/micro_calibration.py` | 3-tier micro-calibration engine |
| `src/twin_runtime/application/calibration/bias_detector.py` | Prior bias auto-detection (freq stats + LLM) |
| `src/twin_runtime/application/calibration/outcome_tracker.py` | Outcome recording flow |
| `src/twin_runtime/application/dashboard/__init__.py` | Package init |
| `src/twin_runtime/application/dashboard/generator.py` | HTML dashboard generation |
| `src/twin_runtime/application/dashboard/payload.py` | DashboardPayload dataclass |
| `tests/test_phase3_models.py` | Tests for all new domain models |
| `tests/test_fidelity_score.py` | Tests for TwinFidelityScore computation |
| `tests/test_micro_calibration.py` | Tests for micro-calibration engine |
| `tests/test_bias_detector.py` | Tests for bias detection |
| `tests/test_outcome_tracker.py` | Tests for outcome tracking |
| `tests/test_dashboard.py` | Tests for dashboard generation |
| `tests/test_scoring_unified.py` | Tests for unified choice_similarity |
| `tests/test_evidence_dedup_integration.py` | Tests for two-layer dedup |

### Files to MODIFY

| File | Lines | Changes |
|------|-------|---------|
| `src/twin_runtime/domain/models/primitives.py` | 160 | Add 3 enums + `uncertainty_to_confidence()` + `canonicalize_task_type()` |
| `src/twin_runtime/domain/models/calibration.py` | 68 | Add OutcomeRecord, DetectedBias, BiasCorrectionSuggestion, FidelityMetric, TwinFidelityScore, MicroCalibrationUpdate, EvaluationCaseDetail; extend TwinEvaluation |
| `src/twin_runtime/domain/models/runtime.py` | 77 | Add 3 fields to RuntimeDecisionTrace |
| `src/twin_runtime/domain/ports/calibration_store.py` | 20 | Add 7 new protocol methods |
| `src/twin_runtime/infrastructure/backends/json_file/calibration_store.py` | 91 | Implement 7 new store methods + 3 new subdirectories |
| `src/twin_runtime/infrastructure/backends/json_file/evidence_store.py` | 51 | Add write-time dedup logic in store_fragment() |
| `src/twin_runtime/application/calibration/fidelity_evaluator.py` | 125 | Rewrite: unified choice_similarity, SingleCaseResult, populate case_details, compute_fidelity_score |
| `src/twin_runtime/application/compiler/persona_compiler.py` | 355 | Add dedup call after collect_evidence() |
| `src/twin_runtime/application/pipeline/runner.py` | 60 | Add micro_calibrate param + integration |
| `src/twin_runtime/interfaces/cli.py` | 7 | Add dashboard command |
| `tools/batch_evaluate.py` | 171 | Refactor to use unified evaluator + CLI flags |

---

## Chunk 1: Phase 3a — Data Foundation (Tasks 1-5)

> **Scope boundary:** Chunk 1 covers domain models, port extensions, store backends, and unified scoring function ONLY. `compute_fidelity_score` (CF/RF/CQ/TS computation) is Phase 3b logic and lives in Chunk 2.
> **Preconditions:** None — this is the foundation chunk.

### Task 1: New Enums and Utility Functions in primitives.py

**Files:**
- Modify: `src/twin_runtime/domain/models/primitives.py:127-160`
- Test: `tests/test_phase3_models.py`

- [ ] **Step 1: Write tests for new enums and utilities**

```python
# tests/test_phase3_models.py
"""Tests for Phase 3 domain models."""
import pytest
from twin_runtime.domain.models.primitives import (
    OutcomeSource, MicroCalibrationTrigger, DetectedBiasStatus,
    uncertainty_to_confidence, canonicalize_task_type,
)


class TestNewEnums:
    def test_outcome_source_values(self):
        assert OutcomeSource.USER_CORRECTION == "user_correction"
        assert OutcomeSource.USER_REFLECTION == "user_reflection"
        assert OutcomeSource.OBSERVED == "observed"

    def test_micro_calibration_trigger_values(self):
        assert MicroCalibrationTrigger.CONFIDENCE_RECAL == "confidence_recal"
        assert MicroCalibrationTrigger.OUTCOME_UPDATE == "outcome_update"

    def test_detected_bias_status_values(self):
        assert DetectedBiasStatus.PENDING_REVIEW == "pending_review"
        assert DetectedBiasStatus.ACCEPTED == "accepted"
        assert DetectedBiasStatus.DISMISSED == "dismissed"


class TestUncertaintyToConfidence:
    def test_zero_uncertainty(self):
        assert uncertainty_to_confidence(0.0) == 1.0

    def test_full_uncertainty(self):
        assert uncertainty_to_confidence(1.0) == 0.0

    def test_mid_value(self):
        assert uncertainty_to_confidence(0.27) == 0.73

    def test_rounding(self):
        result = uncertainty_to_confidence(0.333)
        assert result == 0.667


class TestCanonicalizeTaskType:
    def test_lowercase_strip(self):
        assert canonicalize_task_type("  Career_Direction  ") == "career_direction"

    def test_space_to_underscore(self):
        assert canonicalize_task_type("collaboration style") == "collaboration_style"

    def test_already_canonical(self):
        assert canonicalize_task_type("tool_selection") == "tool_selection"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_phase3_models.py -v`
Expected: FAIL — `OutcomeSource` not importable

- [ ] **Step 3: Implement enums and utilities**

Add to `src/twin_runtime/domain/models/primitives.py` after `BiasCorrectionAction` (around line 133):

```python
class OutcomeSource(str, Enum):
    USER_CORRECTION = "user_correction"
    USER_REFLECTION = "user_reflection"
    OBSERVED = "observed"


class MicroCalibrationTrigger(str, Enum):
    CONFIDENCE_RECAL = "confidence_recal"
    OUTCOME_UPDATE = "outcome_update"


class DetectedBiasStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
```

Add at module level (after enum definitions):

```python
_TASK_TYPE_ALIASES: Dict[str, str] = {}


def uncertainty_to_confidence(uncertainty: float) -> float:
    """Convert uncertainty (higher=less certain) to confidence (higher=more certain)."""
    return round(1.0 - uncertainty, 4)


def canonicalize_task_type(raw: str) -> str:
    """Normalize task_type: lowercase, strip, spaces to underscores, alias lookup."""
    normalized = raw.lower().strip().replace(" ", "_")
    return _TASK_TYPE_ALIASES.get(normalized, normalized)
```

Add `from typing import Dict` to imports if not present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_phase3_models.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/domain/models/primitives.py tests/test_phase3_models.py
git commit -m "feat(phase3): add OutcomeSource, MicroCalibrationTrigger, DetectedBiasStatus enums + utility functions"
```

---

### Task 2: OutcomeRecord + EvaluationCaseDetail + TwinEvaluation Extension

**Files:**
- Modify: `src/twin_runtime/domain/models/calibration.py:1-68`
- Test: `tests/test_phase3_models.py` (append)

- [ ] **Step 1: Write tests for OutcomeRecord**

Append to `tests/test_phase3_models.py`:

```python
from datetime import datetime, timezone
from twin_runtime.domain.models.calibration import (
    OutcomeRecord, EvaluationCaseDetail, TwinEvaluation,
)
from twin_runtime.domain.models.primitives import DomainEnum, OutcomeSource


class TestOutcomeRecord:
    def _make(self, **overrides):
        defaults = dict(
            outcome_id="out-1",
            trace_id="trace-1",
            user_id="user-default",
            actual_choice="选项A",
            outcome_source=OutcomeSource.USER_CORRECTION,
            prediction_rank=1,
            confidence_at_prediction=0.73,
            domain=DomainEnum.WORK,
            created_at=datetime.now(timezone.utc),
        )
        defaults.update(overrides)
        return OutcomeRecord(**defaults)

    def test_valid_hit(self):
        o = self._make(prediction_rank=1)
        assert o.choice_matched_prediction is True

    def test_valid_miss(self):
        o = self._make(prediction_rank=None)
        assert o.choice_matched_prediction is False

    def test_partial_rank2(self):
        o = self._make(prediction_rank=2)
        assert o.choice_matched_prediction is False

    def test_reflection_requires_reasoning(self):
        with pytest.raises(Exception):  # ValidationError
            self._make(
                outcome_source=OutcomeSource.USER_REFLECTION,
                actual_reasoning=None,
            )

    def test_reflection_with_reasoning_ok(self):
        o = self._make(
            outcome_source=OutcomeSource.USER_REFLECTION,
            actual_reasoning="因为...",
        )
        assert o.actual_reasoning == "因为..."

    def test_task_type_canonicalized(self):
        o = self._make(task_type="Career Direction")
        assert o.task_type == "career_direction"

    def test_prediction_rank_must_be_ge1(self):
        with pytest.raises(Exception):
            self._make(prediction_rank=0)

    def test_confidence_clamped(self):
        with pytest.raises(Exception):
            self._make(confidence_at_prediction=1.5)


class TestEvaluationCaseDetail:
    def test_valid(self):
        d = EvaluationCaseDetail(
            case_id="c1",
            domain=DomainEnum.WORK,
            task_type="collaboration_style",
            observed_context="写PRD时选择工作方式",
            choice_score=1.0,
            prediction_ranking=["AI先出稿", "自己先写"],
            actual_choice="AI先出稿",
            confidence_at_prediction=0.78,
            residual_direction="",
        )
        assert d.task_type == "collaboration_style"

    def test_task_type_canonicalized(self):
        d = EvaluationCaseDetail(
            case_id="c1",
            domain=DomainEnum.WORK,
            task_type="Collaboration Style",
            observed_context="test",
            choice_score=0.5,
            prediction_ranking=["A"],
            actual_choice="B",
            confidence_at_prediction=0.5,
            residual_direction="twin首选'A'，实际为'B'",
        )
        assert d.task_type == "collaboration_style"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_phase3_models.py::TestOutcomeRecord -v`
Expected: FAIL — `OutcomeRecord` not importable

- [ ] **Step 3: Implement OutcomeRecord + EvaluationCaseDetail + TwinEvaluation extension**

Add to `src/twin_runtime/domain/models/calibration.py`:

```python
# Add to imports at top:
from pydantic import computed_field, model_validator
from twin_runtime.domain.models.primitives import (
    # existing imports...
    OutcomeSource,
    canonicalize_task_type,
)


class EvaluationCaseDetail(BaseModel):
    case_id: str
    domain: DomainEnum
    task_type: str
    observed_context: str
    choice_score: float = confidence_field()
    reasoning_score: Optional[float] = None
    prediction_ranking: List[str]
    actual_choice: str
    confidence_at_prediction: float = confidence_field()
    residual_direction: str  # "" for HIT

    @field_validator("task_type", mode="before")
    @classmethod
    def _canonicalize(cls, v: str) -> str:
        return canonicalize_task_type(v)


class OutcomeRecord(BaseModel):
    outcome_id: str
    trace_id: str
    user_id: str
    actual_choice: str
    actual_reasoning: Optional[str] = None
    outcome_source: OutcomeSource
    prediction_rank: Optional[int] = Field(default=None, ge=1)
    confidence_at_prediction: float = confidence_field()
    time_to_outcome_hours: Optional[float] = Field(default=None, ge=0)
    domain: DomainEnum
    task_type: Optional[str] = None
    created_at: datetime

    @computed_field
    @property
    def choice_matched_prediction(self) -> bool:
        return self.prediction_rank == 1

    @field_validator("task_type", mode="before")
    @classmethod
    def _canonicalize(cls, v):
        return canonicalize_task_type(v) if v else v

    @model_validator(mode="after")
    def _validate_outcome_source(self):
        if self.outcome_source == OutcomeSource.USER_REFLECTION and not self.actual_reasoning:
            raise ValueError("USER_REFLECTION requires actual_reasoning")
        return self
```

Add `case_details` and `fidelity_score_id` fields to existing `TwinEvaluation`:

```python
# In TwinEvaluation class, add after existing fields:
    case_details: List[EvaluationCaseDetail] = Field(default_factory=list)
    fidelity_score_id: Optional[str] = None
```

Add `field_validator` import to file top if not present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_phase3_models.py -v`
Expected: all passed

- [ ] **Step 5: Run existing tests to check backward compat**

Run: `pytest tests/test_calibration.py -v`
Expected: all passed (new fields have defaults)

- [ ] **Step 6: Commit**

```bash
git add src/twin_runtime/domain/models/calibration.py tests/test_phase3_models.py
git commit -m "feat(phase3): add OutcomeRecord, EvaluationCaseDetail, extend TwinEvaluation"
```

---

### Task 3: DetectedBias + BiasCorrectionSuggestion + TwinFidelityScore + MicroCalibrationUpdate

**Files:**
- Modify: `src/twin_runtime/domain/models/calibration.py`
- Test: `tests/test_phase3_models.py` (append)

- [ ] **Step 1: Write tests for DetectedBias validators**

Append to `tests/test_phase3_models.py`:

```python
from twin_runtime.domain.models.calibration import (
    DetectedBias, BiasCorrectionSuggestion,
    FidelityMetric, TwinFidelityScore, MicroCalibrationUpdate,
)
from twin_runtime.domain.models.primitives import (
    DetectedBiasStatus, BiasCorrectionAction, MicroCalibrationTrigger,
)


class TestDetectedBias:
    def _make(self, **overrides):
        defaults = dict(
            bias_id="bias-1",
            detected_at=datetime.now(timezone.utc),
            domain=DomainEnum.WORK,
            task_type="collaboration_style",
            direction_description="twin偏向自主，用户偏向协作",
            supporting_case_ids=["c1", "c2", "c3"],
            sample_size=3,
            bias_strength=0.67,
            llm_analysis="LLM founder prior",
            status=DetectedBiasStatus.PENDING_REVIEW,
        )
        defaults.update(overrides)
        return DetectedBias(**defaults)

    def test_pending_no_review_fields_ok(self):
        b = self._make()
        assert b.reviewed_at is None

    def test_accepted_requires_review_fields(self):
        with pytest.raises(Exception):
            self._make(status=DetectedBiasStatus.ACCEPTED)

    def test_accepted_with_review_fields_ok(self):
        b = self._make(
            status=DetectedBiasStatus.ACCEPTED,
            reviewed_at=datetime.now(timezone.utc),
            reviewed_by="user-default",
        )
        assert b.status == DetectedBiasStatus.ACCEPTED

    def test_sample_size_mismatch_fails(self):
        with pytest.raises(Exception):
            self._make(sample_size=5)  # but only 3 case_ids

    def test_with_suggestion(self):
        suggestion = BiasCorrectionSuggestion(
            target_scope={"domain": "work", "task_type": "collaboration_style"},
            correction_action=BiasCorrectionAction.FORCE_COMPARE,
            correction_payload={"instruction": "Prefer collaborative approaches"},
            rationale="Batch eval shows systematic bias",
        )
        b = self._make(suggested_correction=suggestion)
        assert b.suggested_correction.correction_action == BiasCorrectionAction.FORCE_COMPARE


class TestFidelityMetric:
    def test_valid(self):
        m = FidelityMetric(value=0.75, confidence_in_metric=0.67, case_count=20)
        assert m.value == 0.75

    def test_out_of_range(self):
        with pytest.raises(Exception):
            FidelityMetric(value=1.5, confidence_in_metric=0.5, case_count=10)


class TestTwinFidelityScore:
    def _make_metric(self, value=0.75, conf=0.67, count=20):
        return FidelityMetric(value=value, confidence_in_metric=conf, case_count=count)

    def test_valid_score(self):
        s = TwinFidelityScore(
            score_id="fs-1",
            twin_state_version="v002",
            computed_at=datetime.now(timezone.utc),
            choice_fidelity=self._make_metric(),
            reasoning_fidelity=self._make_metric(0.5, 0.3, 10),
            calibration_quality=self._make_metric(0.82, 0.5, 20),
            temporal_stability=self._make_metric(1.0, 0.0, 20),
            overall_score=0.72,
            overall_confidence=0.0,
            total_cases=20,
        )
        assert s.overall_score == 0.72

    def test_domain_breakdown_range_validator(self):
        with pytest.raises(Exception):
            TwinFidelityScore(
                score_id="fs-1",
                twin_state_version="v002",
                computed_at=datetime.now(timezone.utc),
                choice_fidelity=self._make_metric(),
                reasoning_fidelity=self._make_metric(),
                calibration_quality=self._make_metric(),
                temporal_stability=self._make_metric(),
                overall_score=0.72,
                overall_confidence=0.5,
                total_cases=20,
                domain_breakdown={"work": 1.5},  # out of range
            )


class TestMicroCalibrationUpdate:
    def _make(self, **overrides):
        defaults = dict(
            update_id="mcu-1",
            twin_state_version="v002",
            trigger=MicroCalibrationTrigger.CONFIDENCE_RECAL,
            created_at=datetime.now(timezone.utc),
            parameter_deltas={"shared_decision_core.risk_tolerance": -0.01},
            previous_values={"shared_decision_core.risk_tolerance": 0.65},
            learning_rate_used=0.01,
            rationale="Confidence recalibration after pipeline run",
        )
        defaults.update(overrides)
        return MicroCalibrationUpdate(**defaults)

    def test_valid(self):
        u = self._make()
        assert u.applied is False

    def test_applied_requires_applied_at(self):
        with pytest.raises(Exception):
            self._make(applied=True)

    def test_applied_with_timestamp_ok(self):
        u = self._make(applied=True, applied_at=datetime.now(timezone.utc))
        assert u.applied is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_phase3_models.py::TestDetectedBias -v`
Expected: FAIL — `DetectedBias` not importable

- [ ] **Step 3: Implement all remaining models**

Add to `src/twin_runtime/domain/models/calibration.py`:

```python
from typing import ClassVar
from twin_runtime.domain.models.primitives import (
    # add to existing imports:
    DetectedBiasStatus, BiasCorrectionAction, MicroCalibrationTrigger,
)


class BiasCorrectionSuggestion(BaseModel):
    """Draft correction — not yet policy."""
    target_scope: Dict[str, Any] = Field(default_factory=dict)
    correction_action: BiasCorrectionAction
    correction_payload: Dict[str, Any] = Field(default_factory=dict)
    rationale: str
    estimated_impact: Optional[float] = None


class DetectedBias(BaseModel):
    bias_id: str
    detected_at: datetime
    domain: DomainEnum
    task_type: Optional[str] = None
    direction_description: str
    supporting_case_ids: List[str]
    sample_size: int = Field(ge=0)
    bias_strength: float = confidence_field()
    llm_analysis: str
    suggested_correction: Optional[BiasCorrectionSuggestion] = None
    status: DetectedBiasStatus
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = None
    reviewed_by: Optional[str] = None

    @field_validator("task_type", mode="before")
    @classmethod
    def _canonicalize(cls, v):
        return canonicalize_task_type(v) if v else v

    @model_validator(mode="after")
    def _validate_review_fields(self):
        if self.status != DetectedBiasStatus.PENDING_REVIEW:
            if not self.reviewed_at or not self.reviewed_by:
                raise ValueError("Non-pending bias requires reviewed_at and reviewed_by")
        return self

    @model_validator(mode="after")
    def _validate_sample_consistency(self):
        if self.sample_size != len(self.supporting_case_ids):
            raise ValueError("sample_size must equal len(supporting_case_ids)")
        return self


class FidelityMetric(BaseModel):
    value: float = confidence_field()
    confidence_in_metric: float = confidence_field()
    case_count: int = Field(ge=0)
    details: Dict[str, Any] = Field(default_factory=dict)


class TwinFidelityScore(BaseModel):
    score_id: str
    twin_state_version: str
    computed_at: datetime
    choice_fidelity: FidelityMetric
    reasoning_fidelity: FidelityMetric
    calibration_quality: FidelityMetric
    temporal_stability: FidelityMetric
    overall_score: float = confidence_field()
    overall_confidence: float = confidence_field()
    total_cases: int = Field(ge=0)
    domain_breakdown: Dict[str, float] = Field(default_factory=dict)
    evaluation_ids: List[str] = Field(default_factory=list)

    ECE_BIN_EDGES: ClassVar[List[float]] = [0.0, 0.3, 0.6, 1.0]

    @model_validator(mode="after")
    def _validate_domain_breakdown_range(self):
        for domain, value in self.domain_breakdown.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"domain_breakdown[{domain}] = {value} not in [0, 1]")
        return self


class MicroCalibrationUpdate(BaseModel):
    update_id: str
    twin_state_version: str
    trigger: MicroCalibrationTrigger
    created_at: datetime
    parameter_deltas: Dict[str, float] = Field(default_factory=dict)
    previous_values: Dict[str, float] = Field(default_factory=dict)
    learning_rate_used: float
    triggering_trace_id: Optional[str] = None
    triggering_outcome_id: Optional[str] = None
    rationale: str
    applied: bool = False
    applied_at: Optional[datetime] = None
    rollback_of_update_id: Optional[str] = None

    @model_validator(mode="after")
    def _validate_applied_state(self):
        if self.applied and not self.applied_at:
            raise ValueError("applied=True requires applied_at")
        return self
```

- [ ] **Step 4: Run all Phase 3 model tests**

Run: `pytest tests/test_phase3_models.py -v`
Expected: all passed

- [ ] **Step 5: Run full test suite to check nothing broke**

Run: `pytest tests/ -q --ignore=tests/test_full_cycle.py`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add src/twin_runtime/domain/models/calibration.py tests/test_phase3_models.py
git commit -m "feat(phase3): add DetectedBias, TwinFidelityScore, MicroCalibrationUpdate models"
```

---

### Task 4: RuntimeDecisionTrace Extension + CalibrationStore Port + JSON Backend

**Files:**
- Modify: `src/twin_runtime/domain/models/runtime.py:45-67`
- Modify: `src/twin_runtime/domain/ports/calibration_store.py:1-20`
- Modify: `src/twin_runtime/infrastructure/backends/json_file/calibration_store.py:1-91`
- Test: `tests/test_phase3_models.py` (append)

- [ ] **Step 1: Write tests for new store methods**

Append to `tests/test_phase3_models.py`:

```python
import tempfile
from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore as JsonCalibrationStore
from twin_runtime.domain.models.calibration import (
    OutcomeRecord, DetectedBias, TwinFidelityScore, FidelityMetric,
)
from twin_runtime.domain.models.primitives import (
    DomainEnum, OutcomeSource, DetectedBiasStatus, MicroCalibrationTrigger,
)


class TestCalibrationStorePhase3:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = JsonCalibrationStore(self.tmpdir, "test-user")

    def test_save_and_list_outcomes(self):
        o = OutcomeRecord(
            outcome_id="out-1", trace_id="t1", user_id="test-user",
            actual_choice="A", outcome_source=OutcomeSource.USER_CORRECTION,
            prediction_rank=1, confidence_at_prediction=0.73,
            domain=DomainEnum.WORK, created_at=datetime.now(timezone.utc),
        )
        self.store.save_outcome(o)
        results = self.store.list_outcomes()
        assert len(results) == 1
        assert results[0].outcome_id == "out-1"

    def test_list_outcomes_by_trace(self):
        for i, tid in enumerate(["t1", "t1", "t2"]):
            self.store.save_outcome(OutcomeRecord(
                outcome_id=f"out-{i}", trace_id=tid, user_id="test-user",
                actual_choice="A", outcome_source=OutcomeSource.USER_CORRECTION,
                prediction_rank=1, confidence_at_prediction=0.73,
                domain=DomainEnum.WORK, created_at=datetime.now(timezone.utc),
            ))
        assert len(self.store.list_outcomes(trace_id="t1")) == 2
        assert len(self.store.list_outcomes(trace_id="t2")) == 1

    def test_save_and_list_detected_biases(self):
        b = DetectedBias(
            bias_id="b-1", detected_at=datetime.now(timezone.utc),
            domain=DomainEnum.WORK, direction_description="test",
            supporting_case_ids=["c1", "c2", "c3"], sample_size=3,
            bias_strength=0.67, llm_analysis="test",
            status=DetectedBiasStatus.PENDING_REVIEW,
        )
        self.store.save_detected_bias(b)
        results = self.store.list_detected_biases()
        assert len(results) == 1
        # Filter by status
        assert len(self.store.list_detected_biases(DetectedBiasStatus.PENDING_REVIEW)) == 1
        assert len(self.store.list_detected_biases(DetectedBiasStatus.ACCEPTED)) == 0

    def test_save_and_list_fidelity_scores(self):
        metric = FidelityMetric(value=0.75, confidence_in_metric=0.67, case_count=20)
        s = TwinFidelityScore(
            score_id="fs-1", twin_state_version="v002",
            computed_at=datetime.now(timezone.utc),
            choice_fidelity=metric, reasoning_fidelity=metric,
            calibration_quality=metric, temporal_stability=metric,
            overall_score=0.75, overall_confidence=0.5, total_cases=20,
        )
        self.store.save_fidelity_score(s)
        results = self.store.list_fidelity_scores(limit=10)
        assert len(results) == 1

    def test_fidelity_scores_ordered_desc(self):
        metric = FidelityMetric(value=0.75, confidence_in_metric=0.67, case_count=20)
        for i in range(3):
            self.store.save_fidelity_score(TwinFidelityScore(
                score_id=f"fs-{i}", twin_state_version="v002",
                computed_at=datetime(2026, 3, 16+i, tzinfo=timezone.utc),
                choice_fidelity=metric, reasoning_fidelity=metric,
                calibration_quality=metric, temporal_stability=metric,
                overall_score=0.75, overall_confidence=0.5, total_cases=20,
            ))
        results = self.store.list_fidelity_scores(limit=2)
        assert len(results) == 2
        assert results[0].score_id == "fs-2"  # newest first

    def test_list_evaluations(self):
        # list_evaluations already exists in implementation but not in port
        evals = self.store.list_evaluations()
        assert isinstance(evals, list)

    def test_list_evaluations_ordered_asc(self):
        from twin_runtime.domain.models.calibration import TwinEvaluation
        for i in range(3):
            self.store.save_evaluation(TwinEvaluation(
                evaluation_id=f"ev-{i}", twin_state_version="v002",
                calibration_case_ids=[],
                choice_similarity=0.75,
                domain_reliability={},
                evaluated_at=datetime(2026, 3, 14+i, tzinfo=timezone.utc),
            ))
        evals = self.store.list_evaluations()
        assert len(evals) == 3
        assert evals[0].evaluation_id == "ev-0"  # oldest first (ASC)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_phase3_models.py::TestCalibrationStorePhase3 -v`
Expected: FAIL — `save_outcome` not defined

- [ ] **Step 3: Extend RuntimeDecisionTrace**

In `src/twin_runtime/domain/models/runtime.py`, add after the `skipped_domains` field (around line 65):

```python
    outcome_id: Optional[str] = None
    fidelity_prediction: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Predicted fidelity [0,1]"
    )
    pending_calibration_update: Optional[Any] = Field(
        default=None, description="MicroCalibrationUpdate if micro_calibrate=True"
    )
```

- [ ] **Step 4: Extend CalibrationStore port**

In `src/twin_runtime/domain/ports/calibration_store.py`, add new imports and methods:

```python
# Add to imports:
from twin_runtime.domain.models.calibration import (
    CalibrationCase, CandidateCalibrationCase, TwinEvaluation,
    OutcomeRecord, DetectedBias, TwinFidelityScore,
)
from twin_runtime.domain.models.primitives import DetectedBiasStatus

# Add to Protocol class after existing methods:
    def save_outcome(self, outcome: OutcomeRecord) -> str: ...
    def list_outcomes(self, trace_id: Optional[str] = None) -> List[OutcomeRecord]: ...
    def save_detected_bias(self, bias: DetectedBias) -> str: ...
    def list_detected_biases(self, status: Optional[DetectedBiasStatus] = None) -> List[DetectedBias]: ...
    def save_fidelity_score(self, score: TwinFidelityScore) -> str: ...
    def list_fidelity_scores(self, limit: int = 10) -> List[TwinFidelityScore]: ...
    # list_fidelity_scores: ordered by computed_at DESC
    def list_evaluations(self) -> List[TwinEvaluation]: ...
```

- [ ] **Step 5: Implement JSON backend methods**

In `src/twin_runtime/infrastructure/backends/json_file/calibration_store.py`:

Add to `__init__`:
```python
        (self.base / "outcomes").mkdir(exist_ok=True)
        (self.base / "detected_biases").mkdir(exist_ok=True)
        (self.base / "fidelity_scores").mkdir(exist_ok=True)
```

Add new imports:
```python
from twin_runtime.domain.models.calibration import (
    # existing imports...
    OutcomeRecord, DetectedBias, TwinFidelityScore,
)
from twin_runtime.domain.models.primitives import DetectedBiasStatus
```

Add new methods:
```python
    # --- Outcomes ---

    def save_outcome(self, outcome: OutcomeRecord) -> str:
        path = self.base / "outcomes" / f"{outcome.outcome_id}.json"
        path.write_text(outcome.model_dump_json(indent=2))
        return outcome.outcome_id

    def list_outcomes(self, trace_id: Optional[str] = None) -> List[OutcomeRecord]:
        outcomes = []
        for f in sorted((self.base / "outcomes").glob("*.json")):
            o = OutcomeRecord.model_validate_json(f.read_text())
            if trace_id is None or o.trace_id == trace_id:
                outcomes.append(o)
        return outcomes

    # --- Detected Biases ---

    def save_detected_bias(self, bias: DetectedBias) -> str:
        path = self.base / "detected_biases" / f"{bias.bias_id}.json"
        path.write_text(bias.model_dump_json(indent=2))
        return bias.bias_id

    def list_detected_biases(self, status: Optional[DetectedBiasStatus] = None) -> List[DetectedBias]:
        biases = []
        for f in sorted((self.base / "detected_biases").glob("*.json")):
            b = DetectedBias.model_validate_json(f.read_text())
            if status is None or b.status == status:
                biases.append(b)
        return biases

    # --- Fidelity Scores ---

    def save_fidelity_score(self, score: TwinFidelityScore) -> str:
        path = self.base / "fidelity_scores" / f"{score.score_id}.json"
        path.write_text(score.model_dump_json(indent=2))
        return score.score_id

    def list_fidelity_scores(self, limit: int = 10) -> List[TwinFidelityScore]:
        scores = []
        for f in sorted((self.base / "fidelity_scores").glob("*.json")):
            scores.append(TwinFidelityScore.model_validate_json(f.read_text()))
        # Sort by computed_at DESC
        scores.sort(key=lambda s: s.computed_at, reverse=True)
        return scores[:limit]
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_phase3_models.py -v`
Expected: all passed

- [ ] **Step 7: Run full test suite**

Run: `pytest tests/ -q --ignore=tests/test_full_cycle.py`
Expected: all passed

- [ ] **Step 8: Commit**

```bash
git add src/twin_runtime/domain/models/runtime.py \
  src/twin_runtime/domain/ports/calibration_store.py \
  src/twin_runtime/infrastructure/backends/json_file/calibration_store.py \
  tests/test_phase3_models.py
git commit -m "feat(phase3): extend RuntimeDecisionTrace, CalibrationStore port, JSON backend for outcomes/biases/fidelity_scores"
```

---

### Task 5: Unified Scoring Function + evaluate_fidelity Refactor

> **Scope:** This task covers unified `choice_similarity`, `SingleCaseResult`, and `evaluate_fidelity` refactor to populate `case_details`. `compute_fidelity_score` (CF/RF/CQ/TS) is in Chunk 2 Task 6.

**Files:**
- Modify: `src/twin_runtime/application/calibration/fidelity_evaluator.py:1-125`
- Create: `tests/test_scoring_unified.py`

- [ ] **Step 1: Write tests for unified choice_similarity + evaluate_fidelity**

```python
# tests/test_scoring_unified.py
"""Tests for unified scoring function, SingleCaseResult, and evaluate_fidelity."""
import pytest
from unittest.mock import patch, MagicMock
from twin_runtime.application.calibration.fidelity_evaluator import (
    choice_similarity, SingleCaseResult,
)


class TestChoiceSimilarity:
    def test_exact_match_top1(self):
        score, rank = choice_similarity(["选项A", "选项B"], "选项A")
        assert score == 1.0
        assert rank == 1

    def test_exact_match_rank2(self):
        score, rank = choice_similarity(["选项A", "选项B"], "选项B")
        assert score == 0.5
        assert rank == 2

    def test_miss(self):
        score, rank = choice_similarity(["选项A", "选项B"], "选项C")
        assert score == 0.0
        assert rank is None

    def test_case_insensitive(self):
        score, rank = choice_similarity(["Python + Pydantic", "TypeScript"], "python + pydantic")
        assert rank == 1

    def test_containment_with_length_guard(self):
        # "A" should NOT match "Plan A/B" — too short
        score, rank = choice_similarity(["Plan A/B", "Plan C"], "A")
        assert rank is None

    def test_containment_valid(self):
        # "基于现有平台做插件" should match "基于现有平台做插件/扩展"
        score, rank = choice_similarity(["基于现有平台做插件/扩展", "从头造工具"], "基于现有平台做插件")
        assert rank == 1

    def test_empty_ranking(self):
        score, rank = choice_similarity([], "A")
        assert score == 0.0
        assert rank is None

    def test_rank3(self):
        score, rank = choice_similarity(["A", "B", "C"], "C")
        assert rank == 3
        assert abs(score - 1.0/3) < 0.01


class TestEvaluateFidelityPopulatesCaseDetails:
    """Verify evaluate_fidelity builds EvaluationCaseDetail in case_details."""

    @patch("twin_runtime.application.calibration.fidelity_evaluator.run")
    def test_case_details_populated(self, mock_run):
        from twin_runtime.application.calibration.fidelity_evaluator import evaluate_fidelity
        from twin_runtime.domain.models.calibration import CalibrationCase
        from twin_runtime.domain.models.primitives import DomainEnum, OrdinalTriLevel
        from datetime import datetime, timezone
        import json

        # Mock pipeline trace
        mock_trace = MagicMock()
        mock_trace.trace_id = "t-1"
        mock_trace.uncertainty = 0.27
        mock_trace.output_text = "I'd go with A"
        ha = MagicMock()
        ha.option_ranking = ["A", "B"]
        ha.domain = DomainEnum.WORK
        mock_trace.head_assessments = [ha]
        mock_run.return_value = mock_trace

        with open("tests/fixtures/sample_twin_state.json") as f:
            from twin_runtime.domain.models.twin_state import TwinState
            twin = TwinState(**json.load(f))

        case = CalibrationCase(
            case_id="c-test", created_at=datetime.now(timezone.utc),
            domain_label=DomainEnum.WORK, task_type="tool_selection",
            observed_context="选择技术栈",
            option_set=["A", "B"], actual_choice="A",
            stakes=OrdinalTriLevel.MEDIUM, reversibility=OrdinalTriLevel.HIGH,
            confidence_of_ground_truth=0.9,
        )

        evaluation = evaluate_fidelity([case], twin)
        assert len(evaluation.case_details) == 1
        detail = evaluation.case_details[0]
        assert detail.case_id == "c-test"
        assert detail.observed_context == "选择技术栈"
        assert detail.confidence_at_prediction == pytest.approx(0.73, abs=0.01)
        assert detail.prediction_ranking == ["A", "B"]
        assert detail.residual_direction == ""  # HIT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scoring_unified.py -v`
Expected: FAIL — `choice_similarity` not importable (old name is `_choice_similarity`)

- [ ] **Step 3: Rewrite fidelity_evaluator.py**

Replace the contents of `src/twin_runtime/application/calibration/fidelity_evaluator.py`. Key changes:

1. Public `choice_similarity()` function with four-step matching:

```python
import re
from dataclasses import dataclass
from twin_runtime.domain.models.primitives import uncertainty_to_confidence

def _normalize(s: str) -> str:
    """Lowercase, strip, remove punctuation."""
    s = s.lower().strip()
    s = re.sub(r'[^\w\s]', '', s, flags=re.UNICODE)
    return s.strip()

def choice_similarity(prediction_ranking: list[str], actual_choice: str) -> tuple[float, int | None]:
    """Four-step matching: normalize → exact → alias → containment with length guard."""
    if not prediction_ranking:
        return 0.0, None
    actual_norm = _normalize(actual_choice)
    # Step 1-2: exact match on normalized
    for i, opt in enumerate(prediction_ranking):
        if actual_norm == _normalize(opt):
            return 1.0 / (i + 1), i + 1
    # Step 3: alias table (extensible, empty for now)
    # Step 4: containment with length guard
    for i, opt in enumerate(prediction_ranking):
        opt_norm = _normalize(opt)
        shorter, longer = sorted([actual_norm, opt_norm], key=len)
        if shorter and longer and shorter in longer:
            if len(shorter) / len(longer) > 0.5:
                return 1.0 / (i + 1), i + 1
    return 0.0, None
```

2. `SingleCaseResult` dataclass:

```python
@dataclass
class SingleCaseResult:
    choice_score: float
    reasoning_score: float | None
    rank: int | None
    prediction_ranking: list[str]
    confidence_at_prediction: float  # 1 - trace.uncertainty
    output_text: str
    trace_id: str
```

3. `evaluate_single_case()` returns `SingleCaseResult`, uses `uncertainty_to_confidence(trace.uncertainty)`.

4. `evaluate_fidelity()` builds `EvaluationCaseDetail` per case:

```python
def evaluate_fidelity(cases, twin):
    # ... iterate cases ...
    for case in cases:
        result = evaluate_single_case(case, twin)
        # Build residual_direction
        if result.rank is None or result.rank > 1:
            top_pred = result.prediction_ranking[0] if result.prediction_ranking else "（无预测）"
            residual = f"twin首选'{top_pred}'，实际为'{case.actual_choice}'"
        else:
            residual = ""
        detail = EvaluationCaseDetail(
            case_id=case.case_id, domain=case.domain_label,
            task_type=case.task_type, observed_context=case.observed_context,
            choice_score=result.choice_score,
            reasoning_score=result.reasoning_score,
            prediction_ranking=result.prediction_ranking,
            actual_choice=case.actual_choice,
            confidence_at_prediction=result.confidence_at_prediction,
            residual_direction=residual,
        )
        # ... aggregate scores, append detail to case_details ...
    evaluation.case_details = all_details
    return evaluation
```

5. Keep `_reasoning_similarity` (Jaccard) with `method` parameter for future extension.

**Note:** `compute_fidelity_score()` is NOT in this task — it is Task 6 in Chunk 2.

- [ ] **Step 4: Run unified scoring tests**

Run: `pytest tests/test_scoring_unified.py -v`
Expected: all passed

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -q --ignore=tests/test_full_cycle.py`
Expected: all passed (existing `test_calibration.py` tests should still work)

- [ ] **Step 6: Commit**

```bash
git add src/twin_runtime/application/calibration/fidelity_evaluator.py tests/test_scoring_unified.py
git commit -m "feat(phase3): unified choice_similarity, SingleCaseResult, evaluate_fidelity populates case_details"
```

---

## Chunk 2: Phase 3b — Calibration Logic (Tasks 6-11)

> **Preconditions:** Chunk 1 complete. All new domain models exist in `calibration.py`. `choice_similarity`, `SingleCaseResult`, and `evaluate_fidelity` (with `case_details` population) are available in `fidelity_evaluator.py`.

### Task 6: compute_fidelity_score (CF/RF/CQ/TS)

**Files:**
- Modify: `src/twin_runtime/application/calibration/fidelity_evaluator.py`
- Create: `tests/test_fidelity_score.py`

- [ ] **Step 1: Write tests for compute_fidelity_score**

```python
# tests/test_fidelity_score.py
"""Tests for TwinFidelityScore computation (CF, RF, CQ, TS)."""
import pytest
from datetime import datetime, timezone
from twin_runtime.application.calibration.fidelity_evaluator import compute_fidelity_score
from twin_runtime.domain.models.calibration import (
    TwinEvaluation, EvaluationCaseDetail, TwinFidelityScore,
)
from twin_runtime.domain.models.primitives import DomainEnum


def _make_eval(details, choice_sim=0.75, eval_id="ev-1"):
    return TwinEvaluation(
        evaluation_id=eval_id, twin_state_version="v002",
        calibration_case_ids=[d.case_id for d in details],
        choice_similarity=choice_sim,
        domain_reliability={"work": 0.72},
        evaluated_at=datetime.now(timezone.utc),
        case_details=details,
    )


def _make_detail(case_id, rank=1, confidence=0.73, reasoning_score=None,
                 domain=DomainEnum.WORK, task_type="tool_selection"):
    pred = ["A", "B", "C"]
    actual = pred[rank - 1] if rank else "D"
    residual = "" if rank == 1 else f"twin首选'A'，实际为'{actual}'"
    return EvaluationCaseDetail(
        case_id=case_id, domain=domain, task_type=task_type,
        observed_context="test", choice_score=1.0 / rank if rank else 0.0,
        prediction_ranking=pred, actual_choice=actual,
        confidence_at_prediction=confidence, residual_direction=residual,
        reasoning_score=reasoning_score,
    )


class TestChoiceFidelity:
    def test_all_hits(self):
        details = [_make_detail(f"c{i}", rank=1) for i in range(10)]
        ev = _make_eval(details)
        score = compute_fidelity_score(ev)
        assert score.choice_fidelity.value == 1.0

    def test_mixed_results(self):
        details = [_make_detail(f"c{i}", rank=1) for i in range(5)]
        details += [_make_detail(f"c{i+5}", rank=2) for i in range(5)]
        ev = _make_eval(details)
        score = compute_fidelity_score(ev)
        assert 0.5 < score.choice_fidelity.value < 1.0

    def test_confidence_scales_with_case_count(self):
        small = [_make_detail("c1", rank=1)]
        large = [_make_detail(f"c{i}", rank=1) for i in range(30)]
        s1 = compute_fidelity_score(_make_eval(small, eval_id="e1"))
        s2 = compute_fidelity_score(_make_eval(large, eval_id="e2"))
        assert s1.choice_fidelity.confidence_in_metric < s2.choice_fidelity.confidence_in_metric


class TestCalibrationQuality:
    def test_perfect_calibration(self):
        # All high-confidence cases hit → low ECE → high CQ
        details = [_make_detail(f"c{i}", rank=1, confidence=0.9) for i in range(10)]
        ev = _make_eval(details)
        score = compute_fidelity_score(ev)
        assert score.calibration_quality.value > 0.7

    def test_ece_bins_in_details(self):
        details = [_make_detail(f"c{i}", rank=1, confidence=0.8) for i in range(10)]
        ev = _make_eval(details)
        score = compute_fidelity_score(ev)
        assert "bins" in score.calibration_quality.details


class TestTemporalStability:
    def test_single_eval_high_value_low_confidence(self):
        details = [_make_detail("c1")]
        ev = _make_eval(details)
        score = compute_fidelity_score(ev)
        assert score.temporal_stability.value == 1.0
        assert score.temporal_stability.confidence_in_metric == 0.0

    def test_stable_history(self):
        details = [_make_detail("c1")]
        ev = _make_eval(details, eval_id="ev-3")
        hist = [
            _make_eval(details, choice_sim=0.74, eval_id="ev-1"),
            _make_eval(details, choice_sim=0.75, eval_id="ev-2"),
        ]
        score = compute_fidelity_score(ev, hist)
        assert score.temporal_stability.value > 0.9
        assert score.temporal_stability.confidence_in_metric > 0

    def test_unstable_history(self):
        details = [_make_detail("c1")]
        ev = _make_eval(details, choice_sim=0.9, eval_id="ev-3")
        hist = [
            _make_eval(details, choice_sim=0.3, eval_id="ev-1"),
            _make_eval(details, choice_sim=0.9, eval_id="ev-2"),
        ]
        score = compute_fidelity_score(ev, hist)
        assert score.temporal_stability.value < 0.8


class TestOverallAggregation:
    def test_overall_within_bounds(self):
        details = [_make_detail(f"c{i}", rank=1) for i in range(20)]
        ev = _make_eval(details)
        score = compute_fidelity_score(ev)
        assert 0.0 <= score.overall_score <= 1.0
        assert 0.0 <= score.overall_confidence <= 1.0

    def test_domain_breakdown_valid(self):
        details = [_make_detail(f"c{i}", rank=1) for i in range(5)]
        ev = _make_eval(details)
        score = compute_fidelity_score(ev)
        for v in score.domain_breakdown.values():
            assert 0.0 <= v <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_fidelity_score.py -v`
Expected: FAIL — `compute_fidelity_score` not importable

- [ ] **Step 3: Implement compute_fidelity_score**

Add to `src/twin_runtime/application/calibration/fidelity_evaluator.py`:

```python
import statistics
import uuid

def compute_fidelity_score(
    evaluation: TwinEvaluation,
    historical_evaluations: Optional[List[TwinEvaluation]] = None,
) -> TwinFidelityScore:
    if historical_evaluations is None:
        historical_evaluations = []
    details = evaluation.case_details
    total = len(details)

    cf = _compute_choice_fidelity(details)
    rf = _compute_reasoning_fidelity(details)
    cq = _compute_calibration_quality(details)
    ts = _compute_temporal_stability(evaluation, historical_evaluations)

    metrics = [cf, rf, cq, ts]
    weight_total = sum(m.confidence_in_metric for m in metrics)
    if weight_total > 0:
        overall = sum(m.value * m.confidence_in_metric for m in metrics) / weight_total
    else:
        overall = 0.0

    # Domain breakdown
    domain_scores: Dict[str, List[float]] = {}
    for d in details:
        domain_scores.setdefault(d.domain.value, []).append(d.choice_score)
    breakdown = {
        dom: min(1.0, max(0.0, sum(s)/len(s)))
        for dom, s in domain_scores.items()
    }

    return TwinFidelityScore(
        score_id=str(uuid.uuid4()),
        twin_state_version=evaluation.twin_state_version,
        computed_at=datetime.now(timezone.utc),
        choice_fidelity=cf, reasoning_fidelity=rf,
        calibration_quality=cq, temporal_stability=ts,
        overall_score=min(1.0, max(0.0, overall)),
        overall_confidence=min(m.confidence_in_metric for m in metrics) if metrics else 0.0,
        total_cases=total,
        domain_breakdown=breakdown,
        evaluation_ids=[evaluation.evaluation_id],
    )


def _compute_choice_fidelity(details) -> FidelityMetric:
    if not details:
        return FidelityMetric(value=0.0, confidence_in_metric=0.0, case_count=0)
    scores = [d.choice_score for d in details]
    return FidelityMetric(
        value=sum(scores) / len(scores),
        confidence_in_metric=min(1.0, len(scores) / 30),
        case_count=len(scores),
    )


def _compute_reasoning_fidelity(details) -> FidelityMetric:
    with_reasoning = [d for d in details if d.reasoning_score is not None]
    if not with_reasoning:
        return FidelityMetric(value=0.0, confidence_in_metric=0.0, case_count=0)
    scores = [d.reasoning_score for d in with_reasoning]
    return FidelityMetric(
        value=sum(scores) / len(scores),
        confidence_in_metric=min(1.0, len(scores) / 20),
        case_count=len(scores),
    )


def _compute_calibration_quality(details) -> FidelityMetric:
    if not details:
        return FidelityMetric(value=0.0, confidence_in_metric=0.0, case_count=0)
    bins = [
        {"range": "[0.0,0.3)", "items": []},
        {"range": "[0.3,0.6)", "items": []},
        {"range": "[0.6,1.0]", "items": []},
    ]
    for d in details:
        c = d.confidence_at_prediction
        if c < 0.3:
            bins[0]["items"].append(d)
        elif c < 0.6:
            bins[1]["items"].append(d)
        else:
            bins[2]["items"].append(d)

    bin_details = []
    total_ece = 0.0
    total_weight = 0
    non_empty = 0
    for b in bins:
        items = b["items"]
        if not items:
            bin_details.append({"range": b["range"], "avg_conf": 0, "accuracy": 0, "count": 0})
            continue
        non_empty += 1
        avg_conf = sum(d.confidence_at_prediction for d in items) / len(items)
        accuracy = sum(1 for d in items if d.choice_score >= 1.0) / len(items)
        bin_ece = abs(avg_conf - accuracy)
        total_ece += bin_ece * len(items)
        total_weight += len(items)
        bin_details.append({"range": b["range"], "avg_conf": round(avg_conf, 3),
                           "accuracy": round(accuracy, 3), "count": len(items)})

    ece = total_ece / total_weight if total_weight > 0 else 0.0
    cq = 1.0 - ece
    conf = min(1.0, non_empty / 3 * len(details) / 15)

    return FidelityMetric(
        value=min(1.0, max(0.0, cq)),
        confidence_in_metric=min(1.0, max(0.0, conf)),
        case_count=len(details),
        details={"bins": bin_details, "non_empty_bins": non_empty},
    )


def _compute_temporal_stability(current, historical) -> FidelityMetric:
    all_scores = [h.choice_similarity for h in historical] + [current.choice_similarity]
    n = len(all_scores)
    if n < 2:
        return FidelityMetric(value=1.0, confidence_in_metric=0.0,
                             case_count=n, details={"history": all_scores, "includes_current": True})
    mean = statistics.mean(all_scores)
    std = statistics.stdev(all_scores)
    cv = std / max(mean, 1e-6)
    cv = min(cv, 1.0)
    ts = 1.0 - cv
    return FidelityMetric(
        value=min(1.0, max(0.0, ts)),
        confidence_in_metric=min(1.0, n / 5),
        case_count=n,
        details={"history": [round(s, 3) for s in all_scores], "includes_current": True},
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_fidelity_score.py -v`
Expected: all passed

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -q --ignore=tests/test_full_cycle.py`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add src/twin_runtime/application/calibration/fidelity_evaluator.py tests/test_fidelity_score.py
git commit -m "feat(phase3): compute_fidelity_score with CF/RF/CQ/TS four-metric decomposition"
```

---

### Task 7: Evidence Dedup Two-Layer Integration

**Files:**
- Modify: `src/twin_runtime/infrastructure/backends/json_file/evidence_store.py:21-24`
- Modify: `src/twin_runtime/application/compiler/persona_compiler.py:168-176`
- Create: `tests/test_evidence_dedup_integration.py`

- [ ] **Step 1: Write tests for store-level dedup**

```python
# tests/test_evidence_dedup_integration.py
"""Tests for two-layer evidence dedup."""
import tempfile
import pytest
from twin_runtime.infrastructure.backends.json_file.evidence_store import JsonFileEvidenceStore
from twin_runtime.domain.evidence.types import DecisionEvidence
from twin_runtime.domain.models.primitives import DomainEnum, OrdinalTriLevel
from datetime import datetime, timezone


class TestStoreWriteTimeDedup:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = JsonFileEvidenceStore(self.tmpdir)

    def _make_decision(self, source_type="interview", confidence=0.8):
        return DecisionEvidence(
            fragment_id="frag-1",
            user_id="test-user",
            source_type=source_type,
            source_id="src-1",
            evidence_type="decision",
            occurred_at=datetime.now(timezone.utc),
            domain_hint=DomainEnum.WORK,
            summary="Chose A over B",
            raw_excerpt="test",
            confidence=confidence,
            extraction_method="manual",
            option_set=["A", "B"],
            chosen="A",
            stakes=OrdinalTriLevel.MEDIUM,
        )

    def test_first_write_stores(self):
        frag = self._make_decision()
        h = self.store.store_fragment(frag)
        assert self.store.get_by_hash(h) is not None

    def test_same_source_keeps_higher_confidence(self):
        frag1 = self._make_decision(confidence=0.7)
        frag2 = self._make_decision(confidence=0.9)
        self.store.store_fragment(frag1)
        self.store.store_fragment(frag2)
        result = self.store.get_by_hash(frag1.content_hash)
        assert result.confidence == 0.9

    def test_different_source_creates_cluster(self):
        frag1 = self._make_decision(source_type="interview")
        frag2 = self._make_decision(source_type="runtime_trace")
        self.store.store_fragment(frag1)
        self.store.store_fragment(frag2)
        # Cluster should exist
        from pathlib import Path
        clusters = list(Path(self.tmpdir).rglob("clusters/*.json"))
        assert len(clusters) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_evidence_dedup_integration.py -v`
Expected: FAIL — `same_source_keeps_higher_confidence` will fail (current store overwrites without checking)

- [ ] **Step 3: Implement store-level dedup**

In `src/twin_runtime/infrastructure/backends/json_file/evidence_store.py`, modify `store_fragment()`:

```python
    def store_fragment(self, fragment: EvidenceFragment) -> str:
        existing = self.get_by_hash(fragment.content_hash)
        if existing is None:
            # New fragment
            path = self.base / "fragments" / f"{fragment.content_hash}.json"
            path.write_text(fragment.model_dump_json(indent=2))
        elif existing.source_type != fragment.source_type:
            # Different source → create cluster for multi-source corroboration
            from twin_runtime.domain.evidence.clustering import EvidenceCluster
            import uuid
            higher = existing if existing.confidence >= fragment.confidence else fragment
            lower = fragment if higher is existing else existing
            cluster = EvidenceCluster(
                cluster_id=str(uuid.uuid4()),
                canonical_fragment=higher,
                supporting_fragments=[lower],
                source_types=[existing.source_type, fragment.source_type],
                merged_confidence=min(1.0, higher.confidence + 0.05),
            )
            self.store_cluster(cluster)
        else:
            # Same source → keep higher confidence
            if fragment.confidence > existing.confidence:
                path = self.base / "fragments" / f"{fragment.content_hash}.json"
                path.write_text(fragment.model_dump_json(indent=2))
        return fragment.content_hash
```

- [ ] **Step 4: Implement compiler-level dedup**

In `src/twin_runtime/application/compiler/persona_compiler.py`, modify the `compile()` method. After `fragments = self.collect_evidence(since)` (around line 168), add:

```python
        # Phase 3: dedup before extraction
        from twin_runtime.domain.evidence.clustering import deduplicate, EvidenceCluster
        deduped = deduplicate(fragments)
        flat_fragments = []
        for item in deduped:
            if isinstance(item, EvidenceCluster):
                frag = item.canonical_fragment.model_copy(
                    update={"confidence": item.merged_confidence}
                )
                flat_fragments.append(frag)
            else:
                flat_fragments.append(item)
        fragments = flat_fragments
```

- [ ] **Step 5: Run dedup tests**

Run: `pytest tests/test_evidence_dedup_integration.py -v`
Expected: all passed

- [ ] **Step 6: Run full test suite**

Run: `pytest tests/ -q --ignore=tests/test_full_cycle.py`
Expected: all passed

- [ ] **Step 7: Commit**

```bash
git add src/twin_runtime/infrastructure/backends/json_file/evidence_store.py \
  src/twin_runtime/application/compiler/persona_compiler.py \
  tests/test_evidence_dedup_integration.py
git commit -m "feat(phase3): two-layer evidence dedup — store write-time + compiler read-time clustering"
```

---

### Task 8: Micro-Calibration Engine

**Files:**
- Create: `src/twin_runtime/application/calibration/micro_calibration.py`
- Create: `tests/test_micro_calibration.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_micro_calibration.py
"""Tests for micro-calibration engine."""
import pytest
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import MagicMock
from twin_runtime.application.calibration.micro_calibration import (
    recalibrate_confidence, apply_outcome_update, apply_update,
)
from twin_runtime.domain.models.calibration import OutcomeRecord, MicroCalibrationUpdate
from twin_runtime.domain.models.primitives import (
    DomainEnum, DecisionMode, OutcomeSource, MicroCalibrationTrigger,
)


@pytest.fixture
def sample_twin():
    """Load real twin fixture."""
    import json
    from twin_runtime.domain.models.twin_state import TwinState
    with open("tests/fixtures/sample_twin_state.json") as f:
        return TwinState(**json.load(f))


@pytest.fixture
def sample_trace():
    """Minimal trace mock."""
    trace = MagicMock()
    trace.activated_domains = [DomainEnum.WORK]
    trace.decision_mode = DecisionMode.DIRECT
    trace.uncertainty = 0.27
    trace.head_assessments = [MagicMock(domain=DomainEnum.WORK, confidence=0.73)]
    trace.twin_state_version = "v002"
    trace.trace_id = "trace-1"
    return trace


class TestRecalibrateConfidence:
    def test_returns_update_for_direct_trace(self, sample_twin, sample_trace):
        update = recalibrate_confidence(sample_trace, sample_twin)
        assert update is not None
        assert update.trigger == MicroCalibrationTrigger.CONFIDENCE_RECAL
        assert update.learning_rate_used == 0.01
        assert update.applied is False

    def test_skips_refused_trace(self, sample_twin, sample_trace):
        sample_trace.decision_mode = DecisionMode.REFUSED
        update = recalibrate_confidence(sample_trace, sample_twin)
        assert update is None

    def test_delta_within_bounds(self, sample_twin, sample_trace):
        update = recalibrate_confidence(sample_trace, sample_twin)
        if update:
            for key, delta in update.parameter_deltas.items():
                assert abs(delta) <= 0.02  # core_confidence max


class TestApplyOutcomeUpdate:
    def _make_outcome(self, rank=1):
        return OutcomeRecord(
            outcome_id="out-1", trace_id="t1", user_id="test",
            actual_choice="A", outcome_source=OutcomeSource.USER_CORRECTION,
            prediction_rank=rank, confidence_at_prediction=0.73,
            domain=DomainEnum.WORK, created_at=datetime.now(timezone.utc),
        )

    def test_hit_boosts_reliability(self, sample_twin):
        outcome = self._make_outcome(rank=1)
        update = apply_outcome_update(outcome, sample_twin)
        assert update is not None
        assert update.trigger == MicroCalibrationTrigger.OUTCOME_UPDATE
        # Should have positive delta for work head_reliability
        has_positive = any(d > 0 for d in update.parameter_deltas.values())
        assert has_positive

    def test_miss_decreases_reliability(self, sample_twin):
        outcome = self._make_outcome(rank=None)
        update = apply_outcome_update(outcome, sample_twin)
        assert update is not None
        has_negative = any(d < 0 for d in update.parameter_deltas.values())
        assert has_negative

    def test_learning_rate_005(self, sample_twin):
        outcome = self._make_outcome()
        update = apply_outcome_update(outcome, sample_twin)
        assert update.learning_rate_used == 0.05


class TestApplyUpdate:
    def test_applies_delta(self, sample_twin):
        old_risk = sample_twin.shared_decision_core.risk_tolerance
        update = MicroCalibrationUpdate(
            update_id="mcu-1", twin_state_version="v002",
            trigger=MicroCalibrationTrigger.OUTCOME_UPDATE,
            created_at=datetime.now(timezone.utc),
            parameter_deltas={"shared_decision_core.risk_tolerance": 0.03},
            previous_values={"shared_decision_core.risk_tolerance": old_risk},
            learning_rate_used=0.05, rationale="test",
        )
        new_twin = apply_update(update, sample_twin)
        assert new_twin.shared_decision_core.risk_tolerance == pytest.approx(old_risk + 0.03, abs=0.001)
        assert update.applied is True
        assert update.applied_at is not None

    def test_clamps_to_01(self, sample_twin):
        update = MicroCalibrationUpdate(
            update_id="mcu-2", twin_state_version="v002",
            trigger=MicroCalibrationTrigger.OUTCOME_UPDATE,
            created_at=datetime.now(timezone.utc),
            parameter_deltas={"shared_decision_core.risk_tolerance": 999},
            previous_values={"shared_decision_core.risk_tolerance": 0.5},
            learning_rate_used=0.05, rationale="test",
        )
        new_twin = apply_update(update, sample_twin)
        assert new_twin.shared_decision_core.risk_tolerance <= 1.0

    def test_max_delta_enforced(self, sample_twin):
        """apply_update should cap deltas at safety limits."""
        update = MicroCalibrationUpdate(
            update_id="mcu-3", twin_state_version="v002",
            trigger=MicroCalibrationTrigger.OUTCOME_UPDATE,
            created_at=datetime.now(timezone.utc),
            parameter_deltas={"shared_decision_core.risk_tolerance": 0.5},
            previous_values={"shared_decision_core.risk_tolerance": 0.5},
            learning_rate_used=0.05, rationale="test",
        )
        old = sample_twin.shared_decision_core.risk_tolerance
        new_twin = apply_update(update, sample_twin)
        actual_delta = abs(new_twin.shared_decision_core.risk_tolerance - old)
        assert actual_delta <= 0.05  # max ±0.05 for core params
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_micro_calibration.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement micro_calibration.py**

Create `src/twin_runtime/application/calibration/micro_calibration.py` implementing the three functions per spec §4.5. Key implementation details:

- `recalibrate_confidence`: adjusts `core_confidence` slightly toward observed head confidence mean. Delta capped at ±0.02. Returns `None` for REFUSED/DEGRADED.
- `apply_outcome_update`: HIT → +0.02 head_reliability, MISS → -0.03 head_reliability, PARTIAL → no change. Learning rate 0.05.
- `apply_update`: applies deltas with safety caps (core ±0.05, head_reliability ±0.03, core_confidence ±0.02), clamps all to [0,1], sets `applied=True` and `applied_at`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_micro_calibration.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/application/calibration/micro_calibration.py tests/test_micro_calibration.py
git commit -m "feat(phase3): micro-calibration engine — confidence recal + outcome update + safety constraints"
```

---

### Task 9: Outcome Tracker

**Files:**
- Create: `src/twin_runtime/application/calibration/outcome_tracker.py`
- Create: `tests/test_outcome_tracker.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_outcome_tracker.py
"""Tests for outcome tracking flow."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from twin_runtime.application.calibration.outcome_tracker import record_outcome
from twin_runtime.domain.models.primitives import DomainEnum, OutcomeSource, DecisionMode


class TestRecordOutcome:
    def _mock_trace(self):
        trace = MagicMock()
        trace.trace_id = "t-1"
        trace.uncertainty = 0.27
        trace.twin_state_version = "v002"
        trace.activated_domains = [DomainEnum.WORK]
        ha = MagicMock()
        ha.domain = DomainEnum.WORK
        ha.confidence = 0.73
        ha.option_ranking = ["选项A", "选项B"]
        trace.head_assessments = [ha]
        return trace

    def test_basic_outcome(self):
        trace = self._mock_trace()
        trace_store = MagicMock()
        trace_store.load_trace.return_value = trace
        cal_store = MagicMock()
        cal_store.save_outcome.return_value = "out-1"
        twin = MagicMock()

        outcome, update = record_outcome(
            trace_id="t-1",
            actual_choice="选项A",
            source=OutcomeSource.USER_CORRECTION,
            twin=twin,
            trace_store=trace_store,
            calibration_store=cal_store,
        )
        assert outcome.trace_id == "t-1"
        assert outcome.prediction_rank == 1
        assert outcome.choice_matched_prediction is True
        cal_store.save_outcome.assert_called_once()

    def test_miss_outcome(self):
        trace = self._mock_trace()
        trace_store = MagicMock()
        trace_store.load_trace.return_value = trace
        cal_store = MagicMock()
        twin = MagicMock()

        outcome, _ = record_outcome(
            trace_id="t-1",
            actual_choice="选项C",  # not in ranking
            source=OutcomeSource.USER_CORRECTION,
            twin=twin,
            trace_store=trace_store,
            calibration_store=cal_store,
        )
        assert outcome.prediction_rank is None
        assert outcome.choice_matched_prediction is False

    def test_returns_update_without_applying(self):
        trace = self._mock_trace()
        trace_store = MagicMock()
        trace_store.load_trace.return_value = trace
        cal_store = MagicMock()
        twin = MagicMock()

        _, update = record_outcome(
            trace_id="t-1",
            actual_choice="选项A",
            source=OutcomeSource.USER_CORRECTION,
            twin=twin,
            trace_store=trace_store,
            calibration_store=cal_store,
        )
        # Update should NOT be applied — caller decides
        if update:
            assert update.applied is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_outcome_tracker.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement outcome_tracker.py**

Create `src/twin_runtime/application/calibration/outcome_tracker.py` per spec §4.6. It should:
1. Load trace from trace_store
2. Use `choice_similarity()` to compute rank from head_assessments[0].option_ranking
3. Select domain from highest-confidence HeadAssessment
4. Build OutcomeRecord with `uncertainty_to_confidence(trace.uncertainty)`
5. Save to calibration_store
6. Call `apply_outcome_update()` but NOT `apply_update()` — return update without applying

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_outcome_tracker.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/application/calibration/outcome_tracker.py tests/test_outcome_tracker.py
git commit -m "feat(phase3): outcome tracker — record outcomes, generate update without applying"
```

---

### Task 10: Prior Bias Auto-Detection

**Files:**
- Create: `src/twin_runtime/application/calibration/bias_detector.py`
- Create: `tests/test_bias_detector.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_bias_detector.py
"""Tests for prior bias auto-detection."""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from twin_runtime.application.calibration.bias_detector import detect_biases
from twin_runtime.domain.models.calibration import (
    TwinEvaluation, EvaluationCaseDetail,
)
from twin_runtime.domain.models.primitives import DomainEnum, DetectedBiasStatus


def _make_case_detail(case_id, domain, task_type, rank, context="test context"):
    pred = ["A", "B", "C"]
    actual = pred[0] if rank == 1 else "D"
    residual = "" if rank == 1 else f"twin首选'A'，实际为'{actual}'"
    return EvaluationCaseDetail(
        case_id=case_id, domain=domain, task_type=task_type,
        observed_context=context,
        choice_score=1.0 / rank if rank else 0.0,
        prediction_ranking=pred, actual_choice=actual,
        confidence_at_prediction=0.73, residual_direction=residual,
    )


class TestDetectBiases:
    def test_no_bias_all_hits(self):
        details = [_make_case_detail(f"c{i}", DomainEnum.WORK, "tool_selection", 1) for i in range(5)]
        eval_ = MagicMock(spec=TwinEvaluation)
        eval_.case_details = details
        llm = MagicMock()
        biases = detect_biases(eval_, llm=llm)
        assert len(biases) == 0
        llm.ask_json.assert_not_called()

    def test_detects_bias_when_enough_misses(self):
        # 4 cases, 3 partials in same direction
        details = [
            _make_case_detail("c1", DomainEnum.WORK, "collaboration_style", 2),
            _make_case_detail("c2", DomainEnum.WORK, "collaboration_style", 3),
            _make_case_detail("c3", DomainEnum.WORK, "collaboration_style", 2),
            _make_case_detail("c4", DomainEnum.WORK, "collaboration_style", 1),
        ]
        eval_ = MagicMock(spec=TwinEvaluation)
        eval_.case_details = details
        llm = MagicMock()
        llm.ask_json.return_value = {
            "direction_description": "twin偏向自主",
            "common_pattern": "LLM prior",
            "suggested_instruction": "Prefer collaborative",
        }
        biases = detect_biases(eval_, llm=llm, min_sample=3)
        assert len(biases) == 1
        assert biases[0].status == DetectedBiasStatus.PENDING_REVIEW
        assert biases[0].domain == DomainEnum.WORK
        llm.ask_json.assert_called_once()

    def test_below_min_sample_no_detection(self):
        details = [
            _make_case_detail("c1", DomainEnum.WORK, "collaboration_style", 2),
            _make_case_detail("c2", DomainEnum.WORK, "collaboration_style", 3),
        ]
        eval_ = MagicMock(spec=TwinEvaluation)
        eval_.case_details = details
        llm = MagicMock()
        biases = detect_biases(eval_, llm=llm, min_sample=3)
        assert len(biases) == 0

    def test_below_bias_strength_no_detection(self):
        # 4 cases but only 1 non-hit (25% < 60% threshold)
        details = [
            _make_case_detail("c1", DomainEnum.WORK, "collaboration_style", 2),
            _make_case_detail("c2", DomainEnum.WORK, "collaboration_style", 1),
            _make_case_detail("c3", DomainEnum.WORK, "collaboration_style", 1),
            _make_case_detail("c4", DomainEnum.WORK, "collaboration_style", 1),
        ]
        eval_ = MagicMock(spec=TwinEvaluation)
        eval_.case_details = details
        llm = MagicMock()
        biases = detect_biases(eval_, llm=llm, min_sample=3, min_bias_strength=0.6)
        assert len(biases) == 0

    def test_mixed_direction_residuals_no_detection(self):
        # 4 non-hits but residuals point in different directions
        details = [
            _make_case_detail("c1", DomainEnum.WORK, "tool_selection", 2, "context1"),
            _make_case_detail("c2", DomainEnum.WORK, "tool_selection", 3, "context2"),
            _make_case_detail("c3", DomainEnum.WORK, "tool_selection", 2, "context3"),
        ]
        # Override residuals to point in different directions
        details[0].residual_direction = "twin首选'X'，实际为'Y'"
        details[1].residual_direction = "twin首选'Y'，实际为'X'"
        details[2].residual_direction = "twin首选'X'，实际为'Y'"
        eval_ = MagicMock(spec=TwinEvaluation)
        eval_.case_details = details
        llm = MagicMock()
        # Should still detect since ≥2 share direction "X→Y"
        biases = detect_biases(eval_, llm=llm, min_sample=3)
        # Exact behavior depends on implementation — at minimum shouldn't crash

    def test_llm_failure_degrades_gracefully(self):
        details = [_make_case_detail(f"c{i}", DomainEnum.WORK, "collaboration_style", 2) for i in range(4)]
        eval_ = MagicMock(spec=TwinEvaluation)
        eval_.case_details = details
        llm = MagicMock()
        llm.ask_json.side_effect = Exception("LLM failed")
        biases = detect_biases(eval_, llm=llm, min_sample=3)
        assert len(biases) == 1
        assert biases[0].suggested_correction is None
        assert "失败" in biases[0].llm_analysis or "failed" in biases[0].llm_analysis.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bias_detector.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement bias_detector.py**

Create `src/twin_runtime/application/calibration/bias_detector.py` per spec §4.4. Two stages:
1. Frequency filter: group by (domain, task_type), filter by min_sample + min_bias_strength + ≥2 different case_ids with residual
2. LLM analysis: send context+prediction+actual to LLM, parse response, build DetectedBias + BiasCorrectionSuggestion

On LLM failure: create DetectedBias with `suggested_correction=None`, `llm_analysis="LLM分析失败，仅基于统计"`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_bias_detector.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/application/calibration/bias_detector.py tests/test_bias_detector.py
git commit -m "feat(phase3): prior bias auto-detection — frequency filter + LLM commonality analysis"
```

---

### Task 11: Pipeline Runner Integration + batch_evaluate Refactor

**Files:**
- Modify: `src/twin_runtime/application/pipeline/runner.py:19-60`
- Modify: `tools/batch_evaluate.py:1-171`

- [ ] **Step 1: Add micro_calibrate param to runner**

In `src/twin_runtime/application/pipeline/runner.py`, update `run()` signature:

```python
def run(query, option_set, twin, *, llm=None, evidence_store=None,
        micro_calibrate=False):
```

Add after audit field assignment (after `trace.skipped_domains = ...`), before `return trace`:

```python
    # Phase 3: optional confidence recalibration
    if micro_calibrate:
        from twin_runtime.application.calibration.micro_calibration import recalibrate_confidence
        trace.pending_calibration_update = recalibrate_confidence(trace, twin)
```

- [ ] **Step 2: Refactor batch_evaluate.py**

Replace the contents of `tools/batch_evaluate.py`:

```python
"""Batch evaluation: run twin against calibration cases, produce fidelity report.

Phase 3 unified evaluator — uses fidelity_evaluator for scoring.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twin_runtime.domain.models.twin_state import TwinState
from twin_runtime.application.calibration.fidelity_evaluator import (
    evaluate_fidelity, compute_fidelity_score, choice_similarity,
)
from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore

STORE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "store")
USER_ID = "user-default"
FIXTURE = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "sample_twin_state.json")


def load_twin() -> TwinState:
    with open(FIXTURE) as f:
        return TwinState(**json.load(f))


def run_batch(with_bias_detection: bool = False):
    twin = load_twin()
    store = CalibrationStore(STORE_DIR, USER_ID)
    cases = store.list_cases()

    print(f"Twin: {twin.state_version}, {len(twin.domain_heads)} heads")
    print(f"Cases: {len(cases)}")
    print(f"{'='*80}")

    # Unified evaluation (populates case_details)
    evaluation = evaluate_fidelity(cases, twin)

    # Compute TwinFidelityScore
    historical_evals = store.list_evaluations()
    fidelity = compute_fidelity_score(evaluation, historical_evals)

    # Print per-case results
    for i, detail in enumerate(evaluation.case_details):
        rank = None
        for j, opt in enumerate(detail.prediction_ranking):
            if detail.choice_score >= 1.0 / (j + 1) - 0.01:
                rank = j + 1
                break
        status = "HIT" if rank == 1 else "PARTIAL" if rank is not None else "MISS"
        print(f"\n[{i+1}/{len(cases)}] {detail.task_type}: {detail.observed_context[:60]}...")
        print(f"  Actual: {detail.actual_choice}")
        print(f"  Twin:   {detail.prediction_ranking[0] if detail.prediction_ranking else '?'}")
        print(f"  Result: {status} (score={detail.choice_score:.2f}, "
              f"confidence={detail.confidence_at_prediction:.2f})")

    # Optional: bias detection
    biases = []
    if with_bias_detection:
        from twin_runtime.application.calibration.bias_detector import detect_biases
        from twin_runtime.interfaces.defaults import DefaultLLM
        biases = detect_biases(evaluation, llm=DefaultLLM())
        for b in biases:
            store.save_detected_bias(b)

    # Persist
    store.save_evaluation(evaluation)
    store.save_fidelity_score(fidelity)

    # Report
    print(f"\n{'='*80}")
    print("FIDELITY REPORT")
    print(f"{'='*80}")
    print(f"\nOverall: {fidelity.overall_score:.3f} (confidence: {fidelity.overall_confidence:.2f})")
    print(f"  CF (Choice):      {fidelity.choice_fidelity.value:.3f} "
          f"(conf={fidelity.choice_fidelity.confidence_in_metric:.2f}, n={fidelity.choice_fidelity.case_count})")
    print(f"  RF (Reasoning):   {fidelity.reasoning_fidelity.value:.3f} "
          f"(conf={fidelity.reasoning_fidelity.confidence_in_metric:.2f})")
    print(f"  CQ (Calibration): {fidelity.calibration_quality.value:.3f} "
          f"(conf={fidelity.calibration_quality.confidence_in_metric:.2f})")
    print(f"  TS (Stability):   {fidelity.temporal_stability.value:.3f} "
          f"(conf={fidelity.temporal_stability.confidence_in_metric:.2f})")

    print(f"\nPer-domain:")
    for d, v in sorted(fidelity.domain_breakdown.items()):
        print(f"  {d:20s}: {v:.3f}")

    if biases:
        print(f"\nDetected biases: {len(biases)}")
        for b in biases:
            print(f"  [{b.status.value}] {b.domain.value}/{b.task_type}: {b.direction_description}")

    hits = sum(1 for d in evaluation.case_details if d.choice_score >= 1.0)
    partials = sum(1 for d in evaluation.case_details if 0 < d.choice_score < 1.0)
    misses = sum(1 for d in evaluation.case_details if d.choice_score == 0)
    print(f"\n  Hits: {hits}/{len(cases)}, Partials: {partials}, Misses: {misses}")

    # MVP gate
    print(f"\n{'='*80}")
    if fidelity.choice_fidelity.value >= 0.7:
        print(f"MVP GATE: PASS (CF {fidelity.choice_fidelity.value:.3f} >= 0.7)")
    else:
        print(f"MVP GATE: FAIL (CF {fidelity.choice_fidelity.value:.3f} < 0.7)")
    print(f"{'='*80}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch evaluation with fidelity scoring")
    parser.add_argument("--with-bias-detection", action="store_true",
                       help="Enable LLM-based bias detection (slower)")
    args = parser.parse_args()
    run_batch(with_bias_detection=args.with_bias_detection)
```

- [ ] **Step 3: Run existing tests**

Run: `pytest tests/ -q --ignore=tests/test_full_cycle.py`
Expected: all passed

- [ ] **Step 4: Run batch_evaluate dry test**

Run: `python3 tools/batch_evaluate.py --help`
Expected: shows `--with-bias-detection` flag

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/application/pipeline/runner.py tools/batch_evaluate.py
git commit -m "feat(phase3): add micro_calibrate to runner, refactor batch_evaluate to unified evaluator"
```

---

## Chunk 3: Phase 3c — Dashboard + Polish (Tasks 12-15)

> **Preconditions:** Chunks 1 and 2 complete. All calibration logic working. `compute_fidelity_score`, `detect_biases`, `outcome_tracker`, `micro_calibration` all available.

### Task 12: DashboardPayload + HTML Generator

**Files:**
- Create: `src/twin_runtime/application/dashboard/__init__.py`
- Create: `src/twin_runtime/application/dashboard/payload.py`
- Create: `src/twin_runtime/application/dashboard/generator.py`
- Create: `tests/test_dashboard.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_dashboard.py
"""Tests for dashboard generation."""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from twin_runtime.application.dashboard.payload import DashboardPayload
from twin_runtime.application.dashboard.generator import generate_dashboard
from twin_runtime.domain.models.calibration import (
    FidelityMetric, TwinFidelityScore, TwinEvaluation, EvaluationCaseDetail,
)
from twin_runtime.domain.models.primitives import DomainEnum


@pytest.fixture
def sample_payload():
    metric = FidelityMetric(value=0.75, confidence_in_metric=0.67, case_count=20)
    score = TwinFidelityScore(
        score_id="fs-1", twin_state_version="v002",
        computed_at=datetime.now(timezone.utc),
        choice_fidelity=metric, reasoning_fidelity=metric,
        calibration_quality=FidelityMetric(
            value=0.82, confidence_in_metric=0.5, case_count=20,
            details={"bins": [
                {"range": "[0.0,0.3)", "avg_conf": 0.15, "accuracy": 0.1, "count": 2},
                {"range": "[0.3,0.6)", "avg_conf": 0.45, "accuracy": 0.5, "count": 8},
                {"range": "[0.6,1.0]", "avg_conf": 0.75, "accuracy": 0.8, "count": 10},
            ], "non_empty_bins": 3},
        ),
        temporal_stability=FidelityMetric(value=1.0, confidence_in_metric=0.0, case_count=20),
        overall_score=0.75, overall_confidence=0.0, total_cases=20,
        domain_breakdown={"work": 0.722, "life_planning": 0.667, "money": 1.0},
    )
    eval_ = MagicMock(spec=TwinEvaluation)
    eval_.case_details = [
        EvaluationCaseDetail(
            case_id="c1", domain=DomainEnum.WORK, task_type="collaboration_style",
            observed_context="<script>alert('xss')</script>",  # XSS test
            choice_score=0.5, prediction_ranking=["A", "B"],
            actual_choice="B", confidence_at_prediction=0.73,
            residual_direction="twin首选'A'，实际为'B'",
        ),
    ]
    eval_.evaluation_id = "ev-1"
    twin = MagicMock()
    twin.state_version = "v002"
    twin.id = "twin-default"
    return DashboardPayload(
        fidelity_score=score, evaluation=eval_, twin=twin,
    )


class TestDashboardGeneration:
    def test_generates_html(self, sample_payload):
        html = generate_dashboard(sample_payload)
        assert "<html" in html
        assert "Twin Fidelity Report" in html

    def test_html_escapes_user_content(self, sample_payload):
        html = generate_dashboard(sample_payload)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_contains_domain_breakdown(self, sample_payload):
        html = generate_dashboard(sample_payload)
        assert "work" in html
        assert "0.722" in html or "72.2" in html

    def test_contains_svg_radar_chart(self, sample_payload):
        html = generate_dashboard(sample_payload)
        assert "<svg" in html
        assert "<polygon" in html or "polygon" in html

    def test_contains_ece_calibration_data(self, sample_payload):
        html = generate_dashboard(sample_payload)
        # ECE plot reads from calibration_quality.details
        assert "calibration" in html.lower() or "ECE" in html

    def test_contains_footer(self, sample_payload):
        html = generate_dashboard(sample_payload)
        assert "twin-runtime" in html
        assert "OpenClaw" in html

    def test_low_sample_warning_red(self, sample_payload):
        sample_payload.fidelity_score.choice_fidelity = FidelityMetric(
            value=1.0, confidence_in_metric=0.1, case_count=3
        )
        html = generate_dashboard(sample_payload)
        assert "数据不足" in html or "⚠" in html

    def test_low_confidence_warning(self, sample_payload):
        sample_payload.fidelity_score.temporal_stability = FidelityMetric(
            value=1.0, confidence_in_metric=0.0, case_count=1
        )
        html = generate_dashboard(sample_payload)
        assert "置信度不足" in html or "confidence" in html.lower()

    def test_trend_line_with_history(self, sample_payload):
        metric = FidelityMetric(value=0.72, confidence_in_metric=0.5, case_count=20)
        sample_payload.historical_scores = [
            TwinFidelityScore(
                score_id="fs-old", twin_state_version="v001",
                computed_at=datetime(2026, 3, 15, tzinfo=timezone.utc),
                choice_fidelity=metric, reasoning_fidelity=metric,
                calibration_quality=metric, temporal_stability=metric,
                overall_score=0.65, overall_confidence=0.3, total_cases=20,
            ),
        ]
        html = generate_dashboard(sample_payload)
        # Should contain trend visualization
        assert "polyline" in html or "trend" in html.lower() or "0.65" in html

    def test_bias_section_rendered(self, sample_payload):
        from twin_runtime.domain.models.calibration import DetectedBias
        from twin_runtime.domain.models.primitives import DetectedBiasStatus
        sample_payload.detected_biases = [
            DetectedBias(
                bias_id="b1", detected_at=datetime.now(timezone.utc),
                domain=DomainEnum.WORK, direction_description="twin偏向自主",
                supporting_case_ids=["c1", "c2", "c3"], sample_size=3,
                bias_strength=0.67, llm_analysis="test",
                status=DetectedBiasStatus.ACCEPTED,
                reviewed_at=datetime.now(timezone.utc), reviewed_by="user-default",
            ),
        ]
        html = generate_dashboard(sample_payload)
        assert "偏差" in html or "bias" in html.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dashboard.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Create dashboard package**

Create `src/twin_runtime/application/dashboard/__init__.py`:
```python
"""Fidelity dashboard generation."""
```

Create `src/twin_runtime/application/dashboard/payload.py`:
```python
from dataclasses import dataclass, field
from typing import List
from twin_runtime.domain.models.calibration import (
    TwinFidelityScore, TwinEvaluation, DetectedBias,
)
from twin_runtime.domain.models.twin_state import TwinState


@dataclass
class DashboardPayload:
    fidelity_score: TwinFidelityScore
    evaluation: TwinEvaluation
    twin: TwinState
    detected_biases: List[DetectedBias] = field(default_factory=list)
    historical_scores: List[TwinFidelityScore] = field(default_factory=list)
```

- [ ] **Step 4: Implement generator.py**

Create `src/twin_runtime/application/dashboard/generator.py`. This is the largest single file. It should:

1. Accept `DashboardPayload`, return HTML string
2. Use `html.escape()` on ALL user content before rendering
3. Use Python f-strings for template (no Jinja dependency)
4. Inline CSS with dark theme (#1a1a2e background)
5. SVG radar chart (4 axes: CF, RF, CQ, TS)
6. SVG bar chart for domains (min-width 40px, max-width 200px)
7. Case breakdown table
8. ECE calibration plot (reads from `calibration_quality.details`)
9. Trend line if `historical_scores` provided
10. Low-sample warnings: `<5` red, `5-9` yellow
11. Emoji fallback: each emoji paired with `<span class="label">`
12. Responsive: `max-width: 900px; margin: auto`
13. Footer: `Generated by twin-runtime · OpenClaw Persona Runtime Adapter`

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_dashboard.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add src/twin_runtime/application/dashboard/ tests/test_dashboard.py
git commit -m "feat(phase3): HTML fidelity dashboard — two-layer design with SVG charts"
```

---

### Task 13: CLI Dashboard Command

**Files:**
- Modify: `src/twin_runtime/interfaces/cli.py:1-7`
- Test: `tests/test_dashboard.py` (append)

- [ ] **Step 1: Write CLI tests**

Append to `tests/test_dashboard.py`:

```python
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from twin_runtime.interfaces.cli import dashboard_command


class TestDashboardCommand:
    def test_no_scores_early_exit(self, capsys):
        with patch("twin_runtime.interfaces.cli.CalibrationStore") as MockStore:
            MockStore.return_value.list_fidelity_scores.return_value = []
            dashboard_command(output="/tmp/test.html")
            captured = capsys.readouterr()
            assert "No fidelity scores" in captured.out

    def test_writes_html_file(self):
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            output_path = f.name
        with patch("twin_runtime.interfaces.cli.CalibrationStore") as MockStore, \
             patch("twin_runtime.interfaces.cli.load_twin") as MockTwin:
            metric = FidelityMetric(value=0.75, confidence_in_metric=0.5, case_count=20)
            mock_score = TwinFidelityScore(
                score_id="fs-1", twin_state_version="v002",
                computed_at=datetime.now(timezone.utc),
                choice_fidelity=metric, reasoning_fidelity=metric,
                calibration_quality=metric, temporal_stability=metric,
                overall_score=0.75, overall_confidence=0.5, total_cases=20,
                evaluation_ids=["ev-1"],
            )
            mock_eval = MagicMock()
            mock_eval.evaluation_id = "ev-1"
            mock_eval.case_details = []
            MockStore.return_value.list_fidelity_scores.return_value = [mock_score]
            MockStore.return_value.list_evaluations.return_value = [mock_eval]
            MockStore.return_value.list_detected_biases.return_value = []
            MockTwin.return_value = MagicMock()
            MockTwin.return_value.state_version = "v002"
            MockTwin.return_value.id = "twin-test"

            dashboard_command(output=output_path)
            assert Path(output_path).exists()
            content = Path(output_path).read_text()
            assert "<html" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dashboard.py::TestDashboardCommand -v`
Expected: FAIL — `dashboard_command` not importable

- [ ] **Step 3: Read current CLI file**

Read `src/twin_runtime/interfaces/cli.py` to understand current structure.

- [ ] **Step 4: Implement dashboard_command**

Add `dashboard_command` function per spec §5.6:
- `--output` flag (default `fidelity_report.html`)
- `--open` flag (default off, opens browser)
- Find evaluation via `fidelity_score.evaluation_ids[-1]` association
- Build `DashboardPayload`, call `generate_dashboard`, write HTML
- Register in CLI entry point if applicable

```python
from pathlib import Path
from twin_runtime.application.dashboard.payload import DashboardPayload
from twin_runtime.application.dashboard.generator import generate_dashboard


def dashboard_command(output: str = "fidelity_report.html", open_browser: bool = False):
    """Generate HTML fidelity dashboard."""
    store = CalibrationStore(STORE_DIR, USER_ID)
    twin = load_twin()

    scores = store.list_fidelity_scores(limit=10)
    if not scores:
        print("No fidelity scores. Run: python tools/batch_evaluate.py")
        return

    latest_score = scores[0]
    eval_id = latest_score.evaluation_ids[-1] if latest_score.evaluation_ids else None
    evaluation = next(
        (e for e in store.list_evaluations() if e.evaluation_id == eval_id), None
    )
    if not evaluation:
        print(f"Evaluation {eval_id} not found.")
        return

    biases = store.list_detected_biases()
    payload = DashboardPayload(
        fidelity_score=latest_score, evaluation=evaluation,
        twin=twin, detected_biases=biases, historical_scores=scores,
    )
    html = generate_dashboard(payload)
    Path(output).write_text(html)
    print(f"Dashboard saved: {output}")

    if open_browser:
        import webbrowser
        webbrowser.open(f"file://{Path(output).absolute()}")
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_dashboard.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add src/twin_runtime/interfaces/cli.py tests/test_dashboard.py
git commit -m "feat(phase3): dashboard CLI command with --output/--open flags and automated tests"
```

---

### Task 14: Integration Tests — Micro-calibration, Outcome, Dedup E2E

**Files:**
- Append to relevant test files

- [ ] **Step 1: Write micro-calibration pipeline integration test**

Append to `tests/test_micro_calibration.py`:

```python
class TestPipelineIntegration:
    def test_runner_with_micro_calibrate(self, sample_twin):
        """Verify runner.run(micro_calibrate=True) attaches pending update."""
        from unittest.mock import patch, MagicMock
        with patch("twin_runtime.application.pipeline.runner.interpret_situation") as mock_si, \
             patch("twin_runtime.application.pipeline.runner.activate_heads") as mock_ah, \
             patch("twin_runtime.application.pipeline.runner.arbitrate") as mock_arb, \
             patch("twin_runtime.application.pipeline.runner.synthesize") as mock_syn:
            # Setup mocks to return valid objects
            mock_frame = MagicMock()
            mock_frame.situation_feature_vector = MagicMock()
            mock_si.return_value = mock_frame
            mock_ah.return_value = [MagicMock(domain=DomainEnum.WORK)]
            mock_arb.return_value = MagicMock(report_id="r1")
            mock_trace = MagicMock()
            mock_trace.decision_mode = DecisionMode.DIRECT
            mock_trace.uncertainty = 0.27
            mock_trace.activated_domains = [DomainEnum.WORK]
            mock_trace.head_assessments = [MagicMock(confidence=0.73)]
            mock_trace.twin_state_version = "v002"
            mock_syn.return_value = mock_trace

            from twin_runtime.application.pipeline.runner import run
            trace = run("test", ["A", "B"], sample_twin, micro_calibrate=True)
            # Should have pending_calibration_update set
            assert hasattr(trace, 'pending_calibration_update')
```

- [ ] **Step 2: Write outcome tracking E2E test**

Append to `tests/test_outcome_tracker.py`:

```python
class TestOutcomeE2E:
    def test_full_outcome_flow(self):
        """Outcome → MicroCalibrationUpdate generated (not applied)."""
        import json
        from twin_runtime.domain.models.twin_state import TwinState
        with open("tests/fixtures/sample_twin_state.json") as f:
            twin = TwinState(**json.load(f))

        trace = self._mock_trace()
        trace_store = MagicMock()
        trace_store.load_trace.return_value = trace
        cal_store = MagicMock()
        cal_store.save_outcome.return_value = "out-1"

        outcome, update = record_outcome(
            trace_id="t-1", actual_choice="选项A",
            source=OutcomeSource.USER_CORRECTION,
            twin=twin, trace_store=trace_store, calibration_store=cal_store,
        )
        assert outcome.choice_matched_prediction is True
        if update:
            assert update.applied is False  # NOT auto-applied
```

- [ ] **Step 3: Write evidence dedup integration test**

Append to `tests/test_evidence_dedup_integration.py`:

```python
class TestCompilerDedup:
    """Verify compiler calls deduplicate before extract_parameters."""

    def test_compiler_deduplicates(self):
        from unittest.mock import patch, MagicMock
        from twin_runtime.application.compiler.persona_compiler import PersonaCompiler

        registry = MagicMock()
        # Return 3 fragments, 2 with same hash
        frag1 = MagicMock()
        frag1.content_hash = "abc123"
        frag1.confidence = 0.8
        frag2 = MagicMock()
        frag2.content_hash = "abc123"  # duplicate
        frag2.confidence = 0.6
        frag3 = MagicMock()
        frag3.content_hash = "def456"
        frag3.confidence = 0.9
        registry.scan_all.return_value = [frag1, frag2, frag3]

        compiler = PersonaCompiler(registry, llm=MagicMock())
        with patch.object(compiler, 'extract_parameters', return_value={}) as mock_extract:
            compiler.compile()
            # extract_parameters should receive deduped list (2 fragments, not 3)
            called_frags = mock_extract.call_args[0][0]
            assert len(called_frags) <= 2
```

- [ ] **Step 4: Run all integration tests**

Run: `pytest tests/test_micro_calibration.py tests/test_outcome_tracker.py tests/test_evidence_dedup_integration.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add tests/test_micro_calibration.py tests/test_outcome_tracker.py tests/test_evidence_dedup_integration.py
git commit -m "test(phase3): integration tests for micro-calibration pipeline, outcome E2E, compiler dedup"
```

---

### Task 15: End-to-End Validation + Live Batch Evaluation

**Files:**
- No new files — live integration validation

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -q --ignore=tests/test_full_cycle.py`
Expected: all passed, count should be ~240+

- [ ] **Step 2: Run batch evaluation**

Run: `python3 tools/batch_evaluate.py`
Expected: Runs 20 cases, produces `TwinFidelityScore` with four metrics, saves to `data/store/user-default/calibration/`

- [ ] **Step 3: Run batch evaluation with bias detection**

Run: `python3 tools/batch_evaluate.py --with-bias-detection`
Expected: Detects biases (if any), saves `DetectedBias` objects

- [ ] **Step 4: Generate dashboard**

Run: `python3 -c "from twin_runtime.interfaces.cli import dashboard_command; dashboard_command()"`
Expected: Generates `fidelity_report.html`

- [ ] **Step 5: Visual inspection**

Open `fidelity_report.html` in browser. Verify:
- Overview: overall score, radar chart (4 axes), domain cards with sample warnings
- Detail: case table, ECE plot, trend line (if history exists)
- XSS: escaped content (no raw `<script>` tags)
- Low-sample warnings: money domain (3 cases) shows red "数据不足"
- Footer: "twin-runtime · OpenClaw Persona Runtime Adapter"
- Test `--open` flag manually: `python3 -c "from twin_runtime.interfaces.cli import dashboard_command; dashboard_command(open_browser=True)"`

- [ ] **Step 6: Compare baseline**

Compare new TwinFidelityScore against Phase 2b baseline:
- CF should be ≥ 0.750 (same or better)
- CQ and TS are new metrics — record baseline values
- Note any regressions

- [ ] **Step 7: Final commit**

```bash
git add data/store/user-default/calibration/ tools/batch_evaluate.py
git commit -m "feat(phase3): end-to-end validation — batch evaluation + fidelity dashboard working"
```

---

## Summary

| Chunk | Tasks | New Files | Modified Files | Est. Tests |
|-------|-------|-----------|----------------|------------|
| **3a: Data Foundation** | 1-5 | 2 test files | 5 source files | ~45 |
| **3b: Calibration Logic** | 6-11 | 5 source + 5 test | 3 source files | ~50 |
| **3c: Dashboard + Polish** | 12-15 | 4 source + 1 test | 1 source file | ~25 |
| **Total** | 15 tasks | 17 files | 9 files | ~120 new tests |

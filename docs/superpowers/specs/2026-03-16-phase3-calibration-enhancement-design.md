# Phase 3: Calibration Enhancement + Fidelity Dashboard — Design Spec

**Date:** 2026-03-16
**Status:** Approved (brainstorming complete)
**Predecessor:** Phase 2b (Memory Access Planner + Pipeline DI)
**Baseline:** choice_similarity 0.750 (post-Phase-2b + BiasCorrectionEntry)
**Target:** Investor-demo-ready dashboard + closed-loop calibration infrastructure

## 1. Goals & Priorities

**B+C as primary, A as secondary:**

- **B (Investor demo ready):** Two-layer HTML dashboard — overview for non-technical, detail for technical
- **C (Closed-loop calibration infrastructure):** OutcomeRecord → micro-calibration → fidelity score pipeline
- **A (Maximize choice_similarity):** Bias auto-detection, case_count weighting, ECE

**Post-Phase-3 launch plan:** Open source community + investor outreach + 朋友圈/司内论坛 product launching.

## 2. Execution Strategy: Data Model First (方案 B)

Three sub-phases with clear dependency ordering:

| Sub-phase | Scope | Duration |
|-----------|-------|----------|
| **3a — Data Foundation** | All new domain models + existing model extensions + port updates | 2-3 days |
| **3b — Calibration Logic** | Dedup wiring, fidelity evaluator, bias detection, micro-calibration, outcome tracking | 4-5 days |
| **3c — Dashboard + Polish** | HTML dashboard generation, CLI command, visual design | 3-4 days |

## 3. Phase 3a — New Domain Models

### 3.1 New Enums (in `domain/models/primitives.py`)

```python
class OutcomeSource(str, Enum):
    USER_CORRECTION = "user_correction"   # "你选错了，我选了X"
    USER_REFLECTION = "user_reflection"   # 事后反思
    OBSERVED = "observed"                 # 系统推断 (Phase 5)

class MicroCalibrationTrigger(str, Enum):
    CONFIDENCE_RECAL = "confidence_recal"  # 每次 run
    OUTCOME_UPDATE = "outcome_update"      # outcome 到达时

class DetectedBiasStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
```

### 3.2 Confidence/Uncertainty Unification

**Rule:** All new models use `confidence` semantics (higher = more certain). `RuntimeDecisionTrace.uncertainty` preserved for backward compat.

```python
# domain/models/primitives.py
def uncertainty_to_confidence(uncertainty: float) -> float:
    return round(1.0 - uncertainty, 4)
```

### 3.3 Task Type Canonicalization

```python
# domain/models/primitives.py
_TASK_TYPE_ALIASES: Dict[str, str] = {}  # populated as needed

def canonicalize_task_type(raw: str) -> str:
    normalized = raw.lower().strip().replace(" ", "_")
    return _TASK_TYPE_ALIASES.get(normalized, normalized)
```

Applied via `@field_validator` on all models with `task_type` field.

### 3.4 OutcomeRecord

File: `domain/models/calibration.py`

```python
class OutcomeRecord(BaseModel):
    outcome_id: str
    trace_id: str
    user_id: str
    actual_choice: str
    actual_reasoning: Optional[str] = None
    outcome_source: OutcomeSource
    choice_matched_prediction: bool
    prediction_rank: Optional[int] = Field(default=None, ge=1)  # None = miss
    confidence_at_prediction: float = confidence_field()  # 1 - trace.uncertainty
    time_to_outcome_hours: Optional[float] = Field(default=None, ge=0)
    domain: DomainEnum
    task_type: Optional[str] = None  # @field_validator → canonicalize
    created_at: datetime

    @model_validator(mode="after")
    def _validate_consistency(self):
        # prediction_rank is None → choice_matched_prediction must be False
        if self.prediction_rank is None and self.choice_matched_prediction:
            raise ValueError("prediction_rank is None but choice_matched_prediction is True")
        # prediction_rank == 1 → choice_matched_prediction must be True
        if self.prediction_rank == 1 and not self.choice_matched_prediction:
            raise ValueError("prediction_rank is 1 but choice_matched_prediction is False")
        # USER_REFLECTION → actual_reasoning required
        if self.outcome_source == OutcomeSource.USER_REFLECTION and not self.actual_reasoning:
            raise ValueError("USER_REFLECTION requires actual_reasoning")
        return self
```

### 3.5 BiasCorrectionSuggestion + DetectedBias

File: `domain/models/calibration.py`

```python
class BiasCorrectionSuggestion(BaseModel):
    """Draft correction — not yet policy. Becomes BiasCorrectionEntry on accept."""
    target_scope: Dict[str, Any]
    correction_action: BiasCorrectionAction
    correction_payload: Dict[str, Any]
    rationale: str
    estimated_impact: Optional[float] = None

class DetectedBias(BaseModel):
    bias_id: str
    detected_at: datetime
    domain: DomainEnum
    task_type: Optional[str] = None  # @field_validator → canonicalize
    direction_description: str
    supporting_case_ids: List[str]
    sample_size: int = Field(ge=0)
    bias_strength: float = confidence_field()
    llm_analysis: str
    suggested_correction: Optional[BiasCorrectionSuggestion] = None
    status: DetectedBiasStatus
    # Audit fields (human-in-the-loop traceability)
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = None
    reviewed_by: Optional[str] = None  # user_id or "system"

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
```

### 3.6 TwinFidelityScore

File: `domain/models/calibration.py`

```python
class FidelityMetric(BaseModel):
    value: float = confidence_field()
    confidence_in_metric: float = confidence_field()
    case_count: int = Field(ge=0)
    details: Dict[str, Any] = Field(default_factory=dict)

class TwinFidelityScore(BaseModel):
    score_id: str
    twin_state_version: str
    computed_at: datetime

    choice_fidelity: FidelityMetric       # CF
    reasoning_fidelity: FidelityMetric    # RF
    calibration_quality: FidelityMetric   # CQ: ECE bins [0.0,0.3), [0.3,0.6), [0.6,1.0]
    temporal_stability: FidelityMetric    # TS

    overall_score: float = confidence_field()
    overall_confidence: float = confidence_field()  # min(four confidence_in_metric)

    total_cases: int = Field(ge=0)
    domain_breakdown: Dict[str, float] = Field(default_factory=dict)
    evaluation_ids: List[str] = Field(default_factory=list)

    ECE_BIN_EDGES: ClassVar[List[float]] = [0.0, 0.3, 0.6, 1.0]
```

### 3.7 MicroCalibrationUpdate

File: `domain/models/calibration.py`

```python
class MicroCalibrationUpdate(BaseModel):
    update_id: str
    twin_state_version: str
    trigger: MicroCalibrationTrigger
    created_at: datetime

    parameter_deltas: Dict[str, float]
    previous_values: Dict[str, float]
    learning_rate_used: float

    triggering_trace_id: Optional[str] = None
    triggering_outcome_id: Optional[str] = None
    rationale: str

    # Application state
    applied: bool = False
    applied_at: Optional[datetime] = None
    rollback_of_update_id: Optional[str] = None

    @model_validator(mode="after")
    def _validate_applied_state(self):
        if self.applied and not self.applied_at:
            raise ValueError("applied=True requires applied_at")
        return self
```

### 3.8 EvaluationCaseDetail + TwinEvaluation Extension

File: `domain/models/calibration.py`

```python
class EvaluationCaseDetail(BaseModel):
    case_id: str
    domain: DomainEnum
    task_type: str  # @field_validator → canonicalize
    choice_score: float = confidence_field()
    reasoning_score: Optional[float] = None
    prediction_ranking: List[str]
    actual_choice: str
    confidence_at_prediction: float = confidence_field()
    residual_direction: str  # "" for HIT

# TwinEvaluation additions:
class TwinEvaluation(BaseModel):
    # ... existing fields ...
    case_details: List[EvaluationCaseDetail] = Field(default_factory=list)
    fidelity_score_id: Optional[str] = None
```

### 3.9 RuntimeDecisionTrace Extension

File: `domain/models/runtime.py`

```python
# New fields on RuntimeDecisionTrace:
outcome_id: Optional[str] = None
fidelity_prediction: Optional[float] = None
pending_calibration_update: Optional[Any] = None  # MicroCalibrationUpdate if micro_calibrate=True
```

### 3.10 CalibrationStore Port Extension

File: `domain/ports/calibration_store.py`

```python
@runtime_checkable
class CalibrationStore(Protocol):
    # Existing methods preserved ...

    # Phase 3 additions:
    def save_outcome(self, outcome: OutcomeRecord) -> str: ...
    def list_outcomes(self, trace_id: Optional[str] = None) -> List[OutcomeRecord]: ...
    def save_detected_bias(self, bias: DetectedBias) -> str: ...
    def list_detected_biases(self, status: Optional[DetectedBiasStatus] = None) -> List[DetectedBias]: ...
    def save_fidelity_score(self, score: TwinFidelityScore) -> str: ...
    def list_fidelity_scores(self, limit: int = 10) -> List[TwinFidelityScore]: ...
    # list_fidelity_scores: ordered by computed_at DESC, limit truncates
    def list_evaluations(self) -> List[TwinEvaluation]: ...
    # list_evaluations: ordered by evaluated_at ASC (append order)
```

JSON backend: each new object type gets a subdirectory (`outcomes/`, `detected_biases/`, `fidelity_scores/`).

## 4. Phase 3b — Calibration Logic

### 4.1 Scoring Function Unification

**Problem:** Two independent scoring functions exist (`batch_evaluate.py:choice_match` and `fidelity_evaluator.py:_choice_similarity`) with subtly different algorithms.

**Solution:** Single source of truth in `fidelity_evaluator.py`:

```python
def choice_similarity(prediction_ranking: List[str], actual_choice: str) -> tuple[float, Optional[int]]:
    """Returns (score, rank). rank=None means miss.

    Three-tier matching:
    1. Normalize: lowercase + strip + remove punctuation
    2. Exact match on normalized strings
    3. Alias table match (if CalibrationCase provides aliases)
    4. Containment match with length guard: len(shorter)/len(longer) > 0.5
    """
```

`batch_evaluate.py` imports and uses this function. The `0.8` fallback branch is removed.

**HIT/PARTIAL/MISS definition:**
- HIT: `rank == 1`
- PARTIAL: `rank is not None and rank > 1`
- MISS: `rank is None`

**rank type:** `Optional[int]` everywhere. No `-1` or `0` sentinel values.

### 4.2 Enhanced Fidelity Evaluator

File: `application/calibration/fidelity_evaluator.py`

**evaluate_single_case return type change:**

```python
@dataclass
class SingleCaseResult:
    choice_score: float
    reasoning_score: Optional[float]
    rank: Optional[int]
    prediction_ranking: List[str]
    confidence_at_prediction: float  # 1 - trace.uncertainty
    output_text: str
    trace_id: str
```

**residual_direction generation (with empty ranking guard):**
```python
if rank is None or rank > 1:
    top_pred = prediction_ranking[0] if prediction_ranking else "（无预测）"
    residual_direction = f"twin首选'{top_pred}'，实际为'{actual_choice}'"
else:
    residual_direction = ""
```

**evaluate_fidelity() refactoring (CRITICAL):**
`evaluate_fidelity()` must be updated to:
1. Call `evaluate_single_case()` which now returns `SingleCaseResult` (with full trace info)
2. Build `EvaluationCaseDetail` from each `SingleCaseResult` (including `confidence_at_prediction`, `prediction_ranking`, `residual_direction`)
3. Populate `TwinEvaluation.case_details` before returning
Without this, `compute_fidelity_score` and `detect_biases` will receive empty `case_details` lists and produce zero-value metrics.

**Domain selection for OutcomeRecord:** When building an OutcomeRecord from a trace with multiple `activated_domains`, use the domain of the highest-confidence HeadAssessment as the primary domain.

**compute_fidelity_score:**

```python
def compute_fidelity_score(
    evaluation: TwinEvaluation,
    historical_evaluations: List[TwinEvaluation] = [],
) -> TwinFidelityScore:
```

**CF (Choice Fidelity):**
- Per-domain averages, then case_count-weighted merge
- `confidence_in_metric = min(1.0, total_cases / 30)`

**RF (Reasoning Fidelity):**
- Current: Jaccard word overlap on cases with reasoning_score
- Extension point: `_reasoning_similarity()` accepts an optional `method` parameter (`"jaccard"` | `"embedding"`). When `method="embedding"`, use cosine similarity on sentence embeddings. This is the "Enhanced reasoning similarity (optional embedding-based)" from the evolution spec — deferred to Phase 3 late or Phase 4 as an optional dependency (`twin-runtime[embedding]`). The interface is designed now so that switching methods requires no architectural change.
- `confidence_in_metric = min(1.0, cases_with_reasoning / 20)`
- 0 cases with reasoning → value=0, confidence=0

**CQ (Calibration Quality — ECE):**
- Bins: `[0.0, 0.3)`, `[0.3, 0.6)`, `[0.6, 1.0]` (boundaries written as `ClassVar`)
- Per bin: `bin_ece = |avg_confidence - accuracy|` where accuracy = fraction with rank==1
- `ECE = weighted_avg(bin_ece, weights=bin_size)`
- `CQ = 1.0 - ECE`
- `confidence_in_metric = min(1.0, non_empty_bins/3 * total_cases/15)`
- `details`: `{"bins": [{"range": "...", "avg_conf": ..., "accuracy": ..., "count": ...}], "non_empty_bins": N}`

**TS (Temporal Stability):**
- Requires ≥2 evaluations (including current)
- `cv = std / max(mean, 1e-6)` then `min(cv, 1.0)`
- `TS = 1.0 - cv`
- `confidence_in_metric = min(1.0, len(evaluations) / 5)`
- 1 evaluation → value=1.0 (assume stable), confidence=0.0
- `details`: `{"history": [0.650, 0.725, 0.750, ...]}`

**Overall aggregation:**
```python
metrics = [CF, RF, CQ, TS]
weighted_sum = sum(m.value * m.confidence_in_metric for m in metrics)
weight_total = sum(m.confidence_in_metric for m in metrics)
overall_score = weighted_sum / weight_total if weight_total > 0 else 0.0
overall_confidence = min(m.confidence_in_metric for m in metrics)
```

### 4.3 Evidence Dedup — Two-Layer Integration

**Layer 1: Store write-time dedup (prevent storage bloat)**

`EvidenceStore.store_fragment()` behavior change in JSON backend:
```
1. Compute fragment.content_hash
2. existing = get_by_hash(content_hash)  # O(1), filename-based
3. if existing is None → write new file, return hash
4. if existing is not None:
   - Different source_type → upgrade to cluster (confidence boost)
   - Same source_type → keep higher confidence, discard duplicate
   Return hash
```

Port interface unchanged. Behavior change is transparent to callers.

**Layer 2: Compiler read-time clustering (multi-source confidence boost)**

In `PersonaCompiler.compile()`, after `collect_evidence()`, before `extract_parameters()`:

```python
from twin_runtime.domain.evidence.clustering import deduplicate

fragments = self.collect_evidence(since)
deduped = deduplicate(fragments)

flat_fragments = []
for item in deduped:
    if isinstance(item, EvidenceCluster):
        # Shallow copy to avoid mutating the original fragment
        frag = item.canonical_fragment.model_copy(update={"confidence": item.merged_confidence})
        flat_fragments.append(frag)
    else:
        flat_fragments.append(item)

extracted = self.extract_parameters(flat_fragments)
```

### 4.4 Prior Bias Auto-Detection

File: `application/calibration/bias_detector.py`

```python
def detect_biases(
    evaluation: TwinEvaluation,
    *,
    llm: LLMPort,
    min_sample: int = 3,
    min_bias_strength: float = 0.6,
) -> List[DetectedBias]:
```

**Stage 1 — Frequency filter:**
- Group `evaluation.case_details` by `(domain, task_type)`
- For each group with `len >= min_sample`:
  - Count cases where `residual_direction != ""` (non-HIT)
  - Require ≥2 different case_ids with same-direction residual
  - If `non_hit_ratio >= min_bias_strength` → pass to Stage 2

**Stage 2 — LLM commonality analysis:**
- Send group's contexts + predictions + actuals + residuals to LLM
- LLM outputs JSON: `{"direction_description", "common_pattern", "suggested_instruction"}`
- Pydantic parse + retry on failure
- On LLM failure: degrade to stats-only DetectedBias with `suggested_correction=None`, `llm_analysis="LLM分析失败，仅基于统计"`

**Invocation:** CLI flag `--with-bias-detection` on `batch_evaluate.py`. Default off.

### 4.5 Micro-Calibration Engine

File: `application/calibration/micro_calibration.py`

**Three functions:**

```python
def recalibrate_confidence(trace: RuntimeDecisionTrace, twin: TwinState) -> Optional[MicroCalibrationUpdate]:
    """Every pipeline run. Only adjusts head_reliability + core_confidence.
    learning_rate = 0.01. Skips REFUSED/DEGRADED traces."""

def apply_outcome_update(outcome: OutcomeRecord, twin: TwinState) -> Optional[MicroCalibrationUpdate]:
    """On outcome arrival. Can adjust core variables.
    learning_rate = 0.05.
    HIT → slight reliability boost. PARTIAL → record residual only. MISS → reliability decrease.
    USER_CORRECTION with reasoning → extract core parameter delta."""

def apply_update(update: MicroCalibrationUpdate, twin: TwinState) -> TwinState:
    """Execute parameter modification. Sets update.applied=True, update.applied_at=now.
    Safety constraints:
    - Core parameter: max ±0.05 per update
    - head_reliability: max ±0.03 per update
    - core_confidence: max ±0.02 per update
    - All values clamped to [0, 1]"""
```

**Three-tier learning rate isolation:** 0.01 (confidence recal) / 0.05 (outcome update) / 0.2 (batch compiler)

**Pipeline integration:**

Updated `run()` signature:
```python
def run(query, option_set, twin, *, llm=None, evidence_store=None,
        micro_calibrate=False) -> RuntimeDecisionTrace:
```

Insertion point: after step 6 (audit field assignment), before return:
```python
    # ... existing: trace.skipped_domains = ...

    # Phase 3: optional confidence recalibration
    if micro_calibrate:
        from twin_runtime.application.calibration.micro_calibration import recalibrate_confidence
        trace.pending_calibration_update = recalibrate_confidence(trace, twin)

    return trace
```

Runner does NOT apply the update — caller decides. `micro_calibrate=False` by default; batch evaluation never enables it.

### 4.6 Outcome Tracking

File: `application/calibration/outcome_tracker.py`

```python
def record_outcome(
    trace_id: str,
    actual_choice: str,
    source: OutcomeSource,
    actual_reasoning: Optional[str] = None,
    *,
    twin: TwinState,
    trace_store: TraceStore,
    calibration_store: CalibrationStore,
) -> tuple[OutcomeRecord, Optional[MicroCalibrationUpdate]]:
    """Full outcome recording flow:
    1. Load original trace from trace_store
    2. Build OutcomeRecord (with confidence_at_prediction, prediction_rank)
       - Domain: highest-confidence HeadAssessment's domain from trace
    3. Save to calibration_store
    4. Call apply_outcome_update → MicroCalibrationUpdate (generates, does NOT apply)
    5. Return (outcome, update) — caller decides whether to apply_update()

    Consistent with pipeline principle: functions generate updates, callers apply them.
    """
```

### 4.7 batch_evaluate.py Refactoring

```python
def run_batch(with_bias_detection: bool = False):
    twin = load_twin()
    store = CalibrationStore(STORE_DIR, USER_ID)
    cases = store.list_cases()

    # Unified evaluation
    evaluation = evaluate_fidelity(cases, twin)

    # Compute TwinFidelityScore
    historical_evals = store.list_evaluations()
    fidelity = compute_fidelity_score(evaluation, historical_evals)

    # Optional: bias detection
    biases = []
    if with_bias_detection:
        biases = detect_biases(evaluation, llm=DefaultLLM())

    # Persist
    store.save_evaluation(evaluation)
    store.save_fidelity_score(fidelity)
    for b in biases:
        store.save_detected_bias(b)

    print_report(evaluation, fidelity, biases)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-bias-detection", action="store_true")
    args = parser.parse_args()
    run_batch(with_bias_detection=args.with_bias_detection)
```

## 5. Phase 3c — HTML Fidelity Dashboard

### 5.1 Technical Approach

- **Pure static HTML + inline CSS/JS**, zero runtime dependencies
- `twin-runtime dashboard` CLI generates `.html` file
- Charts: inline SVG (radar, bar, trend line, ECE calibration plot)
- Fallback: if SVG proves too costly, single-file CDN Chart.js

### 5.2 DashboardPayload

```python
@dataclass
class DashboardPayload:
    fidelity_score: TwinFidelityScore
    evaluation: TwinEvaluation  # linked via fidelity_score.evaluation_ids[-1]
    twin: TwinState
    detected_biases: List[DetectedBias] = field(default_factory=list)
    historical_scores: List[TwinFidelityScore] = field(default_factory=list)
    # Future-proof: evidence stats, additional metadata
```

### 5.3 Two-Layer Information Architecture

**Layer 1 — Overview (first screen, non-technical audience):**
- Overall fidelity score with percentage bar + natural language summary
- Radar chart (4 axes: CF, RF, CQ, TS — overall displayed separately as headline number)
- Per-domain cards: score, case count, sample size warning
- Calibration quality summary
- Bias detection summary with status badges

**Layer 2 — Detail (scroll down, technical audience):**
- Per-case breakdown table
- Fidelity trend chart (historical scores as polyline + target threshold)
- ECE calibration plot (reads from `calibration_quality.details`, no recomputation)
- Bias detection timeline
- Evidence & dedup statistics

### 5.4 Visual Design

- **Theme:** Dark background (#1a1a2e) + bright data colors (green #4ade80 HIT, yellow #facc15 PARTIAL, red #f87171 MISS)
- **Radar:** 4-axis SVG `<polygon>` (CF, RF, CQ, TS), semi-transparent blue fill; overall as separate headline
- **Bar chart:** Width proportional to case_count with min-width 40px, max-width 200px. Color saturation + dashed border for low-sample domains
- **Trend line:** SVG `<polyline>` + dashed target threshold
- **ECE plot:** Diagonal (perfect calibration) + actual points, deviation → redder
- **Layout:** `max-width: 900px; margin: auto` — desktop and mobile screenshot friendly
- **Footer:** `Generated by twin-runtime v0.x · OpenClaw Persona Runtime Adapter`
- **Emoji fallback:** Every emoji paired with `<span class="label">` text; graceful degradation cross-platform
- **Font stack:** `system-ui, -apple-system, sans-serif` with monospace for numbers

### 5.5 Low-Sample Warnings (Two-tier)

| Condition | Visual | Label |
|-----------|--------|-------|
| `case_count < 5` | Red badge, dashed bar border | "数据不足" |
| `5 ≤ case_count < 10` | Yellow badge, lighter bar | "样本偏少" |
| `case_count ≥ 10` | Normal display | — |

For `confidence_in_metric < 0.3`: value in gray, footnote "置信度不足，需要更多数据"

### 5.6 CLI Command

```python
def dashboard_command(output: str = "fidelity_report.html", open_browser: bool = False):
    """twin-runtime dashboard [--output path] [--open]"""
    store = CalibrationStore(STORE_DIR, USER_ID)
    twin = load_twin()

    scores = store.list_fidelity_scores(limit=10)
    if not scores:
        print("No fidelity scores. Run: python tools/batch_evaluate.py")
        return

    latest_score = scores[0]
    # Find evaluation by association, not list position
    eval_id = latest_score.evaluation_ids[-1] if latest_score.evaluation_ids else None
    evaluation = next((e for e in store.list_evaluations() if e.evaluation_id == eval_id), None)
    if not evaluation:
        print(f"Evaluation {eval_id} not found.")
        return

    biases = store.list_detected_biases()

    payload = DashboardPayload(
        fidelity_score=latest_score,
        evaluation=evaluation,
        twin=twin,
        detected_biases=biases,
        historical_scores=scores,
    )
    html = generate_dashboard(payload)

    Path(output).write_text(html)
    print(f"Dashboard saved: {output}")
    if open_browser:
        import webbrowser
        webbrowser.open(f"file://{Path(output).absolute()}")
```

### 5.7 Security

All user-originated content (`observed_context`, `actual_choice`, `task_type`, `output_text`) passed through `html.escape()` before HTML rendering. No raw string interpolation in template.

## 6. Data Pipeline Fixes (Pre-existing Issues)

These must be resolved as part of Phase 3 implementation:

1. **Dual scoring functions** → unified `choice_similarity()` in fidelity_evaluator (§4.1)
2. **rank sentinel values** → `Optional[int]` throughout, no `-1`/`0` (§4.1)
3. **`evaluate_single_case` missing trace data** → returns `SingleCaseResult` with full info (§4.2)
4. **Compiler missing dedup call** → two-layer integration (§4.3)
5. **`EvidenceStore.get_by_hash()` already O(1)** — no index needed, filename-based

## 7. Key Design Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Fidelity metric confidence | `min(1.0, case_count / threshold)` per metric | Small-sample domains auto-downweighted |
| Overall aggregation | Confidence-weighted average | 3-case money domain doesn't inflate score |
| Micro-calibration triggers | 3-tier: 0.01/0.05/0.2 | High-freq low-amplitude to low-freq high-amplitude |
| Pipeline purity | `run()` never mutates twin | Caller decides whether to apply updates |
| Bias detection | Human-in-the-loop | DetectedBias → review → BiasCorrectionEntry |
| Dashboard tech | Static HTML, zero deps | CI/SSH compatible, shareable, screenshot-friendly |
| ECE bins | [0.0,0.3), [0.3,0.6), [0.6,1.0] fixed | Written as ClassVar, dashboard reads from details |
| Confidence vs uncertainty | New models use confidence; trace.uncertainty preserved | Conversion: `1 - uncertainty` |

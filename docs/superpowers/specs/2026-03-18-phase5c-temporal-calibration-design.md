# Phase 5c: Temporal Calibration & Shadow Ontology — Design Spec

**Date:** 2026-03-18
**Status:** Approved (brainstorming complete)
**Predecessor:** Phase 5b (Structured Deliberation & Abstention Router)
**Baseline:** 403 tests, 10 golden traces, S1/S2 routing, INSUFFICIENT_EVIDENCE production
**Target:** Add time decay to evidence/calibration weighting, detect preference/reliability drift, generate offline shadow ontology suggestions — all without modifying runtime control flow.

## North Star

> Build a calibrated judgment twin that learns from evidence and feedback to increasingly judge like you, while knowing when it should not judge on your behalf at all.

## Invariants

1. Never impersonate a missing twin.
2. Prefer abstention over unsafe overreach.
3. Every decision must be traceable to evidence, routing signals, and reliability scores.
4. Online learning must not silently mutate ontology/control topology.

## Quantifiable Gate

| Metric | Requirement |
|--------|-------------|
| Time decay | Decayed weights observable, explainable, testable; old case weight < new case weight |
| Weighted fidelity | weighted_choice_similarity computed and stored; differs from raw when case ages vary |
| Drift detection | Constructed drift fixture: stable hit rate; stable fixture: low false positive |
| Shadow ontology | Only produces offline suggestions; 403 offline tests unchanged; 10 golden traces unchanged |
| Runtime impact | Zero — no routing, planning, or scoring behavior changes from 5c additions |

---

## 1. Goals

**Primary goal:** Make the calibration system time-aware. Recent decisions and evidence should matter more than old ones. When preferences drift over time, the system should detect and report it.

**Secondary goal:** Produce a visible "shadow ontology" report showing emergent subdomain clusters — proof that the system can discover structure the designer didn't pre-define.

**Non-goals:**
- Modifying runtime routing, planning, or scoring based on decay/drift
- Promoting shadow ontology clusters to DomainHead
- Adding embedding models or external NLP dependencies beyond scikit-learn
- Contradiction-based multiplier (interface reserved, not implemented)

## 2. Two-Level Deliverable

| Level | Name | Contents | Depends On |
|-------|------|----------|------------|
| **5c-core** | Temporal Calibration | Time decay functions + weighted fidelity metrics + drift detection | Nothing (foundation) |
| **5c-report** | Shadow Ontology | Offline subdomain clustering + suggestion report + CLI command | 5c-core (uses decayed data) |

## 3. 5c-core: Time Decay

### 3.1 Decay Function

```python
def time_decay_weight(
    age_days: float,
    half_life: float,
    floor: float,
) -> float:
    """Exponential decay with minimum floor.

    weight = floor + (1 - floor) * exp(-ln(2) * age_days / half_life)
    """
    import math
    return floor + (1.0 - floor) * math.exp(-math.log(2) * age_days / half_life)
```

### 3.2 Default Parameters

| Object | half_life (days) | floor | Rationale |
|--------|-----------------|-------|-----------|
| EvidenceFragment | 60 | 0.1 | Evidence changes faster; old evidence is weak background prior |
| CalibrationCase | 120 | 0.25 | Decision patterns are more stable; old cases retain moderate value |

Parameters stored in **app config** (not TwinState). First version uses fixed defaults. Future versions can make per-user configurable.

### 3.3 CalibrationCase Temporal Field

Add to both `CalibrationCase` and `CandidateCalibrationCase`:

```python
decision_occurred_at: Optional[datetime] = Field(
    default=None,
    description="When the original decision was made (not when it was recorded). "
    "Decay uses this if available, falls back to created_at.",
)
```

Adding to `CandidateCalibrationCase` ensures the temporal signal survives promotion to `CalibrationCase`.

Age computation:
```python
def case_age_days(case: CalibrationCase, as_of: datetime) -> float:
    reference = case.decision_occurred_at or case.created_at
    return (as_of - reference).total_seconds() / 86400.0
```

For EvidenceFragment, age uses `occurred_at` (already exists).

### 3.4 Contradiction Multiplier (Reserved)

```python
contradiction_discount: Optional[float] = Field(
    default=None, ge=0.0, le=1.0,
    description="Additional discount when newer evidence contradicts this item. Reserved for future use.",
)
```

Added to CalibrationCase only. **Not computed in 5c** — always None.

**Relationship to existing `EvidenceFragment.temporal_weight`:** The existing `temporal_weight` field on EvidenceFragment (evidence/base.py:73-77) is a compiler-assigned static weight, not a decay function output. 5c's time decay is computed dynamically from `occurred_at` and `as_of`, producing a separate value. These two weights are independent:
- `temporal_weight`: static, set at evidence ingestion time by compiler
- `time_decay_weight()`: dynamic, computed at analysis time from age

5c does NOT modify or deprecate `temporal_weight`. Future phases that want a combined weight can define `final_weight = temporal_weight * time_decay_weight(age) * (contradiction_discount or 1.0)`.

### 3.5 as_of_time

All **offline** decay, drift, and ontology computations accept `as_of: datetime` parameter. Default: `datetime.now(timezone.utc)`. This enables reproducible replay and testing.

Since decay is not applied in runtime retrieval (§3.6), `RecallQuery` and `evidence_store.query()` do NOT need an `as_of` parameter. The `as_of` contract applies to: `evaluate_fidelity(as_of=...)`, `detect_drift(as_of=...)`, `generate_ontology_report(as_of=...)`.

### 3.6 Where Decay Is Consumed

**5c decay is OFFLINE ONLY — zero runtime impact.**

Decay is NOT applied in `evidence_store.query()` or any runtime retrieval path. This preserves the "zero runtime impact" gate. Runtime retrieval continues to use `RecallQuery.sort_by` and `RecallQuery.time_range` without decay weighting.

Decay is consumed in these offline paths only:

1. **Fidelity evaluator (weighted metrics):** `evaluate_fidelity()` computes both raw and weighted metrics. Weighted metrics use `time_decay_weight(case_age_days(case, as_of), half_life, floor)` per case. All raw metrics remain unchanged for backward compat.

2. **Drift detector:** Uses decay weights to compute weighted distributions for JSD/effect-size comparison.

3. **Shadow ontology stability assessment:** Uses `time_decay_weight()` on CalibrationCase ages to compute `decayed_support` per cluster. This is the primary consumer of case decay in 5c.

**Evidence decay:** The `time_decay_weight()` API supports both evidence and calibration objects, but in 5c v1, evidence decay has no active consumer. The document builder uses CalibrationCase fields only (§5.2), and runtime retrieval is not modified (§3.6). Evidence decay parameters (half_life=60, floor=0.1) are defined and tested for API correctness, ready for future phases that add evidence-weighted retrieval or evidence-aware clustering.

Future phases may introduce decay into runtime retrieval, but that would be a deliberate "runtime impact" change with its own gate and golden trace regression.

### 3.7 Weighted Fidelity Metrics

Add to `TwinEvaluation`:

```python
weighted_choice_similarity: Optional[float] = Field(default=None)
weighted_reasoning_similarity: Optional[float] = Field(default=None)
weighted_domain_reliability: Optional[Dict[str, float]] = Field(default=None)
decay_params_used: Optional[Dict[str, Any]] = Field(default=None,
    description="Decay parameters used for this evaluation: {half_life, floor, as_of}")
```

Computation: weighted average using `weight_i / sum(weights)` instead of `1/N`.

## 4. 5c-core: Drift Detection

### 4.1 Drift Model

```python
class DriftSignal(BaseModel):
    dimension: str  # domain name or axis name
    dimension_type: Literal["domain", "axis"]
    direction: str  # e.g., "preference shifted from A to B"
    magnitude: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    recent_window: Tuple[datetime, datetime]
    historical_window: Tuple[datetime, datetime]
    metric_used: str  # "jsd" or "total_variation" or "weighted_mean_delta"

class DriftReport(BaseModel):
    report_id: str
    twin_state_version: str
    as_of: datetime
    recent_window_days: int = 30
    historical_window_days: int = 180
    domain_signals: List[DriftSignal] = Field(default_factory=list)
    axis_signals: List[DriftSignal] = Field(default_factory=list)
    summary: str = ""
```

### 4.2 Domain-Level Preference Drift

For each `(domain, task_type)` pair with sufficient cases:
1. Split cases into recent window (last N days) and historical window
2. Build choice distribution: `P(choice | domain, task_type)` for each window
3. Compute **Jensen-Shannon Divergence** between the two distributions
4. If JSD > threshold (e.g., 0.15) → flag as drift signal

**Why (domain, task_type)?** Choice labels are only comparable within the same task type. "Stay vs Leave" (career decisions) is incomparable with "Refactor vs Ship" (tech decisions), even if both are in the `work` domain. Domain-level summary is derived by aggregating task_type-level signals (e.g., "3 of 5 work task_types show drift").

### 4.3 Axis-Level Confidence Drift

**Data source:** Offline analysis of `RuntimeDecisionTrace` loaded from TraceStore (not TwinEvaluation). Each trace contains `head_assessments` with `utility_decomposition` per axis per domain. This is the only place axis-level scores are stored.

For each goal_axis appearing across traces:
1. Load traces from TraceStore, group by time window
2. Compute weighted mean utility score per axis in recent vs historical window
3. Compute **absolute mean delta**
4. If delta > threshold (e.g., 0.1) → flag as drift signal

Note: `TwinEvaluation` and `EvaluationCaseDetail` do not store per-axis utility scores. Axis drift detection must go through traces, not evaluation summaries.

### 4.4 Drift Detection Interface

```python
def detect_drift(
    cases: List[CalibrationCase],
    traces: List[RuntimeDecisionTrace],  # for axis-level drift via utility_decomposition
    twin: TwinState,
    *,
    as_of: datetime,
    recent_window_days: int = 30,
    historical_window_days: int = 180,
    domain_jsd_threshold: float = 0.15,
    axis_delta_threshold: float = 0.1,
) -> DriftReport:
```

**Input contract:**
- `cases`: for domain-level preference drift (grouped by domain + task_type)
- `traces`: for axis-level confidence drift (via `head_assessments[].utility_decomposition`)
- `evaluations` removed — it was misleading since TwinEvaluation lacks per-axis scores and per-case timestamps

### 4.5 Storage

Drift reports stored at `{store_dir}/{user_id}/drift/{report_id}.json`. Path is injected from CLI config (composition root pattern, same as 5a dashboard fix). Application layer does NOT hardcode `~/.twin-runtime/`.

### 4.6 CLI Command

`twin-runtime drift-report` — generates and saves a drift report, prints summary.

## 5. 5c-report: Shadow Ontology

### 5.1 Clustering Boundary

Cluster **within each parent domain** separately. work cases cluster into work subdomains, money cases into money subdomains. No cross-domain mixing. This preserves DomainEnum stability.

### 5.2 Document Construction

For each CalibrationCase, build a text document:

```
{case.observed_context}
{case.actual_reasoning_if_known or ""}
stakes:{case.stakes.value} reversibility:{case.reversibility.value}
domain:{case.domain_label.value} task_type:{case.task_type}
```

**No trace enrichment in 5c v1.** CalibrationCase currently has no `trace_id` field (linkage is lost during promotion from CandidateCalibrationCase). Text-matching on `observed_context` is too fragile and risks polluting clusters with wrong trace data.

**First version:** Document builder uses CalibrationCase fields only. The document is sufficient for meaningful clustering — `observed_context`, `actual_reasoning`, structural tokens all come from the case itself. Future phases can add `trace_id` to CalibrationCase and enable trace enrichment when explicit linkage exists.

Structural tokens (stakes, domain, task_type, etc.) are appended as words to participate in TF-IDF.

### 5.3 Vectorization

- **TF-IDF** with:
  - Word unigrams and bigrams
  - CJK character bigrams (no jieba dependency)
  - Sublinear TF scaling
  - Max features: 500 (small corpus)
- Uses `sklearn.feature_extraction.text.TfidfVectorizer`
- Custom tokenizer handles mixed Chinese/English

### 5.4 Clustering Algorithm

- **Agglomerative Clustering** with:
  - Metric: cosine distance
  - Linkage: average
  - Distance threshold: configurable (default 0.7)
  - No pre-specified K
- Clusters with < `min_support` cases (default 3) are discarded

### 5.5 Stability Assessment

A candidate subdomain must pass stability checks:

```python
class StabilityCheck(BaseModel):
    min_support: int  # >= 3 cases
    decayed_support: float  # sum of decay weights >= 1.5
    window_stability: float  # top terms overlap between sliding windows >= 0.5
    exemplar_overlap: float  # representative cases overlap between runs >= 0.3
```

### 5.6 Naming

1. **Deterministic fallback**: top-3 TF-IDF terms joined by underscore (e.g., `project_deadline_deploy`)
2. **Optional LLM labeling**: if LLM available, pass top terms + exemplar case summaries, ask for human-readable label (e.g., `project_scoping`)
3. LLM labeling is optional — deterministic name is always produced

### 5.7 Output Models

```python
class OntologySuggestion(BaseModel):
    suggested_subdomain: str
    parent_domain: DomainEnum
    deterministic_label: str
    llm_label: Optional[str] = None
    support_count: int
    decayed_support: float
    stability_score: float
    representative_terms: List[str]
    representative_case_ids: List[str]
    drift_relation: Optional[str] = None  # e.g., "emerging", "stable", "declining"

class OntologyReport(BaseModel):
    report_id: str
    twin_state_version: str
    as_of: datetime
    decay_params: Dict[str, Any]
    suggestions: List[OntologySuggestion]
    domains_analyzed: List[str]
    total_cases_analyzed: int
    clustering_params: Dict[str, Any]
```

### 5.8 CLI Command

`twin-runtime ontology-report [--output report.json] [--llm-labels]`

- Generates `OntologyReport`, saves as JSON
- `--llm-labels` enables optional LLM naming (requires API key)
- If `scikit-learn` not installed: fail-closed with message `"This command requires: pip install twin-runtime[analysis]"`

### 5.9 Dependency

`scikit-learn` added to `pyproject.toml` under `[analysis]` optional extra:

```toml
[project.optional-dependencies]
analysis = ["scikit-learn>=1.3"]
```

Not in main dependencies — only needed for `ontology-report` and advanced drift analysis.

## 6. File Structure

```
src/twin_runtime/application/calibration/time_decay.py          # decay function + weighted scoring
src/twin_runtime/application/calibration/drift_detector.py       # drift detection
src/twin_runtime/application/ontology/__init__.py
src/twin_runtime/application/ontology/document_builder.py        # case → document
src/twin_runtime/application/ontology/clusterer.py               # TF-IDF + Agglomerative
src/twin_runtime/application/ontology/stability.py               # stability assessment
src/twin_runtime/application/ontology/report_generator.py        # OntologyReport assembly
src/twin_runtime/domain/models/drift.py                          # DriftSignal, DriftReport
src/twin_runtime/domain/models/ontology.py                       # OntologySuggestion, OntologyReport
```

## 7. Test Strategy

**5c-core tests (~15):**
- Time decay function: boundary values, half_life variation, floor behavior
- Weighted fidelity: decayed CF differs from raw when ages differ
- CalibrationCase decision_occurred_at fallback logic
- Drift detection: constructed drift fixture hits; stable fixture no false positive
- as_of reproducibility: same inputs + same as_of = same outputs

**5c-report tests (~10):**
- Document builder: structural tokens present in output
- TF-IDF vectorizer: handles mixed CN/EN
- Agglomerative clustering: known fixture produces expected clusters
- Stability check: below-threshold clusters filtered
- OntologyReport: typed model validates
- CLI fail-closed without scikit-learn

**Regression:**
- All 403 existing tests unchanged
- All 10 golden traces unchanged (5c adds no runtime behavior changes)

## 8. Explicitly NOT in This Phase

- Decay/drift affecting runtime routing, planning, or scoring decisions
- Promoting shadow ontology clusters to DomainHead
- Contradiction-based decay multiplier (interface only, not computed)
- Local embedding models
- jieba or other Chinese NLP tokenizers
- Per-user decay parameter tuning
- Automatic ontology migration

## 9. What 5c Unlocks

- **Future phases can promote shadow scores to control** based on accumulated drift/ontology evidence
- **Future phases can add contradiction multiplier** using drift signals as triggers
- **Dashboard can show temporal fidelity trends** using weighted vs raw metric comparison
- **Future phases can conditionally activate subdomain heads** when ontology suggestions reach stability thresholds + human approval

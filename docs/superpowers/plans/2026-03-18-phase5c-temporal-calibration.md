# Phase 5c: Temporal Calibration & Shadow Ontology — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add time decay to calibration weighting, detect preference/reliability drift, and generate offline shadow ontology suggestions — all without modifying runtime control flow.

**Architecture:** (1) Build time decay function + add `decision_occurred_at` field; (2) Integrate weighted metrics into fidelity evaluator; (3) Build drift detector using cases + traces; (4) Build shadow ontology pipeline (document builder → TF-IDF → Agglomerative clustering → stability → report); (5) Add CLI commands + wire storage.

**Tech Stack:** Python 3.9+, Pydantic v2, pytest, scikit-learn (optional `[analysis]`), math (stdlib)

**Spec:** `docs/superpowers/specs/2026-03-18-phase5c-temporal-calibration-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `src/twin_runtime/application/calibration/time_decay.py` | Decay function + case age computation |
| Modify | `src/twin_runtime/domain/models/calibration.py` | Add `decision_occurred_at` to CalibrationCase + CandidateCalibrationCase, `contradiction_discount`, weighted metrics to TwinEvaluation |
| Modify | `src/twin_runtime/application/calibration/fidelity_evaluator.py` | Compute weighted CF/RF/domain_reliability alongside raw |
| Create | `src/twin_runtime/domain/models/drift.py` | DriftSignal, DriftReport models |
| Create | `src/twin_runtime/application/calibration/drift_detector.py` | Domain drift (JSD) + axis drift (mean delta) |
| Create | `src/twin_runtime/domain/models/ontology.py` | OntologySuggestion, OntologyReport, StabilityCheck models |
| Create | `src/twin_runtime/application/ontology/__init__.py` | Package marker |
| Create | `src/twin_runtime/application/ontology/document_builder.py` | CalibrationCase → text document |
| Create | `src/twin_runtime/application/ontology/clusterer.py` | TF-IDF vectorization + Agglomerative clustering |
| Create | `src/twin_runtime/application/ontology/stability.py` | Cluster stability assessment |
| Create | `src/twin_runtime/application/ontology/report_generator.py` | Assemble OntologyReport from clusters |
| Modify | `src/twin_runtime/cli.py` | Add `drift-report` and `ontology-report` commands |
| Modify | `pyproject.toml` | Add `[analysis]` optional dependency for scikit-learn |

---

## Chunk 0: Time Decay Foundation

### Task 1: Create time_decay.py + add model fields

**Files:**
- Create: `src/twin_runtime/application/calibration/time_decay.py`
- Modify: `src/twin_runtime/domain/models/calibration.py`
- Create: `tests/test_time_decay.py`

- [ ] **Step 1: Create time_decay.py**

```python
"""Time decay functions for temporal calibration."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional


def time_decay_weight(
    age_days: float,
    half_life: float,
    floor: float,
) -> float:
    """Exponential decay with minimum floor.

    weight = floor + (1 - floor) * exp(-ln(2) * age_days / half_life)
    """
    if age_days <= 0:
        return 1.0
    decay = math.exp(-math.log(2) * age_days / half_life)
    return floor + (1.0 - floor) * decay


# Default parameters
EVIDENCE_HALF_LIFE = 60.0
EVIDENCE_FLOOR = 0.1
CALIBRATION_HALF_LIFE = 120.0
CALIBRATION_FLOOR = 0.25


def evidence_decay_weight(age_days: float) -> float:
    return time_decay_weight(age_days, EVIDENCE_HALF_LIFE, EVIDENCE_FLOOR)


def calibration_decay_weight(age_days: float) -> float:
    return time_decay_weight(age_days, CALIBRATION_HALF_LIFE, CALIBRATION_FLOOR)


def case_age_days(
    case,  # CalibrationCase
    as_of: Optional[datetime] = None,
) -> float:
    """Compute age in days, preferring decision_occurred_at over created_at."""
    if as_of is None:
        as_of = datetime.now(timezone.utc)
    reference = getattr(case, 'decision_occurred_at', None) or case.created_at
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    return max(0.0, (as_of - reference).total_seconds() / 86400.0)


def evidence_age_days(fragment, as_of: Optional[datetime] = None) -> float:
    """Compute evidence age from occurred_at."""
    if as_of is None:
        as_of = datetime.now(timezone.utc)
    ref = fragment.occurred_at
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    return max(0.0, (as_of - ref).total_seconds() / 86400.0)
```

- [ ] **Step 2: Add model fields**

In `calibration.py`, add to both `CalibrationCase` and `CandidateCalibrationCase`:
```python
decision_occurred_at: Optional[datetime] = Field(
    default=None,
    description="When the original decision was made. Decay uses this if available, falls back to created_at.",
)
```

Add `contradiction_discount` to `CalibrationCase` only:
```python
contradiction_discount: Optional[float] = Field(
    default=None, ge=0.0, le=1.0,
    description="Reserved for future use. Additional discount when newer evidence contradicts.",
)
```

Add weighted metrics to `TwinEvaluation`:
```python
weighted_choice_similarity: Optional[float] = Field(default=None)
weighted_reasoning_similarity: Optional[float] = Field(default=None)
weighted_domain_reliability: Optional[Dict[str, float]] = Field(default=None)
decay_params_used: Optional[Dict[str, Any]] = Field(default=None)
```

- [ ] **Step 3: Write tests**

Create `tests/test_time_decay.py`:
```python
"""Tests for time decay functions."""
import pytest
import math
from datetime import datetime, timezone, timedelta
from twin_runtime.application.calibration.time_decay import (
    time_decay_weight, calibration_decay_weight, evidence_decay_weight, case_age_days,
)


class TestTimeDecayWeight:
    def test_zero_age_returns_one(self):
        assert time_decay_weight(0, 60, 0.1) == 1.0

    def test_negative_age_returns_one(self):
        assert time_decay_weight(-5, 60, 0.1) == 1.0

    def test_at_half_life_approximately_half(self):
        w = time_decay_weight(60, 60, 0.0)
        assert abs(w - 0.5) < 0.01

    def test_floor_prevents_zero(self):
        w = time_decay_weight(10000, 60, 0.1)
        assert w >= 0.1

    def test_very_old_approaches_floor(self):
        w = time_decay_weight(365 * 5, 60, 0.1)
        assert abs(w - 0.1) < 0.01

    def test_newer_has_higher_weight(self):
        w_new = time_decay_weight(10, 60, 0.1)
        w_old = time_decay_weight(100, 60, 0.1)
        assert w_new > w_old

    def test_evidence_defaults(self):
        w = evidence_decay_weight(60)
        # At half-life, weight should be floor + (1-floor)*0.5 = 0.1 + 0.45 = 0.55
        assert abs(w - 0.55) < 0.01

    def test_calibration_defaults(self):
        w = calibration_decay_weight(120)
        # At half-life: 0.25 + 0.75*0.5 = 0.625
        assert abs(w - 0.625) < 0.01


class TestCaseAgeDays:
    def test_uses_decision_occurred_at_when_present(self):
        from unittest.mock import MagicMock
        case = MagicMock()
        case.decision_occurred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        case.created_at = datetime(2026, 3, 1, tzinfo=timezone.utc)
        as_of = datetime(2026, 3, 18, tzinfo=timezone.utc)
        age = case_age_days(case, as_of)
        # Should use Jan 1, not Mar 1
        assert age > 70  # ~77 days from Jan 1

    def test_falls_back_to_created_at(self):
        from unittest.mock import MagicMock
        case = MagicMock()
        case.decision_occurred_at = None
        case.created_at = datetime(2026, 3, 1, tzinfo=timezone.utc)
        as_of = datetime(2026, 3, 18, tzinfo=timezone.utc)
        age = case_age_days(case, as_of)
        assert abs(age - 17) < 0.1
```

- [ ] **Step 4: Wire decision_occurred_at into data production chain**

In `src/twin_runtime/application/calibration/event_collector.py`, when creating `CandidateCalibrationCase`:
- Set `decision_occurred_at = trace.created_at` (the trace timestamp IS when the decision happened)
- This ensures promoted cases have accurate temporal data

In `src/twin_runtime/application/calibration/case_manager.py` (or wherever promotion happens):
- Ensure `decision_occurred_at` is copied from CandidateCalibrationCase to CalibrationCase during promotion
- Check the promotion code and add explicit field mapping if it's doing selective copy

- [ ] **Step 5: Run tests and commit**

```bash
python3 -m pytest tests/test_time_decay.py -v
python3 -m pytest tests/ -q -m "not requires_llm" --tb=short
git add src/twin_runtime/application/calibration/time_decay.py \
  src/twin_runtime/domain/models/calibration.py \
  src/twin_runtime/application/calibration/event_collector.py \
  src/twin_runtime/application/calibration/case_manager.py \
  tests/test_time_decay.py
git commit -m "feat: time decay function + decision_occurred_at wired through event_collector and promotion"
```

---

## Chunk 1: Weighted Fidelity Metrics

### Task 2: Integrate time-decayed weighting into fidelity evaluator

**Files:**
- Modify: `src/twin_runtime/application/calibration/fidelity_evaluator.py`
- Modify: `tests/test_time_decay.py`

- [ ] **Step 1: Add weighted computation to evaluate_fidelity**

**Do NOT use parallel list slicing** — reasoning_scores is already filtered (Nones skipped), so indices don't align with cases. Instead, collect per-case records during the main loop:

```python
from twin_runtime.application.calibration.time_decay import (
    calibration_decay_weight, case_age_days,
    CALIBRATION_HALF_LIFE, CALIBRATION_FLOOR,
)
from dataclasses import dataclass

@dataclass
class _CaseRecord:
    choice_score: float
    reasoning_score: Optional[float]
    domain: str
    weight: float

# Inside the per-case loop, after computing result:
as_of = datetime.now(timezone.utc)
case_records: list[_CaseRecord] = []

# ... in the loop body, after appending to choice_scores:
    decay_w = calibration_decay_weight(case_age_days(case, as_of))
    case_records.append(_CaseRecord(
        choice_score=result.choice_score,
        reasoning_score=result.reasoning_score,
        domain=case.domain_label.value,
        weight=decay_w,
    ))

# After the loop, compute weighted metrics from case_records:
total_w = sum(r.weight for r in case_records)
if total_w > 0:
    weighted_choice = sum(r.choice_score * r.weight for r in case_records) / total_w
    reasoning_records = [r for r in case_records if r.reasoning_score is not None]
    reasoning_w = sum(r.weight for r in reasoning_records)
    weighted_reasoning = (
        sum(r.reasoning_score * r.weight for r in reasoning_records) / reasoning_w
    ) if reasoning_w > 0 else None
    weighted_domain_rel = {}
    for d in set(r.domain for r in case_records):
        d_records = [r for r in case_records if r.domain == d]
        d_w = sum(r.weight for r in d_records)
        if d_w > 0:
            weighted_domain_rel[d] = sum(r.choice_score * r.weight for r in d_records) / d_w
else:
    weighted_choice = avg_choice
    weighted_reasoning = avg_reasoning
    weighted_domain_rel = domain_reliability
```

This avoids the index-alignment bug entirely — each record carries its own weight.

Pass to TwinEvaluation constructor:
```python
weighted_choice_similarity=round(weighted_choice, 3),
weighted_reasoning_similarity=round(weighted_reasoning, 3) if weighted_reasoning else None,
weighted_domain_reliability=weighted_domain_rel,
decay_params_used={"half_life": CALIBRATION_HALF_LIFE, "floor": CALIBRATION_FLOOR, "as_of": as_of.isoformat()},
```

- [ ] **Step 2: Write test for weighted vs raw divergence**

```python
class TestWeightedFidelity:
    def test_weighted_differs_from_raw_when_ages_differ(self):
        """Old cases should contribute less to weighted CF than to raw CF."""
        # Create cases: one recent (high score), one old (low score)
        # Weighted CF should be closer to the recent case's score
        ...
```

- [ ] **Step 3: Add time_decay_weight to EvaluationCaseDetail**

`EvaluationCaseDetail` needs the decay weight stored at evaluation time so `compute_fidelity_score` can use it later without needing the original cases:

In `calibration.py:EvaluationCaseDetail`, add:
```python
time_decay_weight: float = Field(default=1.0, description="Decay weight at evaluation time")
```

In `fidelity_evaluator.py`, when building each `EvaluationCaseDetail`, set:
```python
detail = EvaluationCaseDetail(
    ...,
    time_decay_weight=decay_w,
)
```

- [ ] **Step 4: Extend compute_fidelity_score with weighted mode**

`compute_fidelity_score(evaluation, *, weighted=False)`:
- When `weighted=False`: current behavior (uniform averaging)
- When `weighted=True`: use `detail.time_decay_weight` from each `EvaluationCaseDetail`
- Returns `TwinFidelityScore` with weighted values

- [ ] **Step 5: Wire weighted score into cmd_evaluate and dashboard**

In `cli.py:cmd_evaluate()`, after saving evaluation:
```python
from twin_runtime.application.calibration.fidelity_evaluator import compute_fidelity_score
score = compute_fidelity_score(evaluation, weighted=True)
cal_store.save_fidelity_score(score)
print(f"Weighted CF: {score.choice_fidelity.value:.3f} (raw: {evaluation.choice_similarity:.3f})")
```

In `cli.py:cmd_dashboard()`, pass `weighted=True` context to dashboard_command. Dashboard displays both raw and weighted side by side (or weighted as primary with raw as footnote).

**Default:** CLI evaluate shows weighted as primary metric. Dashboard shows both.

- [ ] **Step 6: Run and commit**

```bash
git commit -m "feat: time-decayed weighted fidelity — EvaluationCaseDetail carries weight, compute_fidelity_score supports weighted, CLI/dashboard wired"
```

---

## Chunk 2: Drift Detection

### Task 3: Create drift models + detector

**Files:**
- Create: `src/twin_runtime/domain/models/drift.py`
- Create: `src/twin_runtime/application/calibration/drift_detector.py`
- Create: `tests/test_drift_detector.py`

- [ ] **Step 1: Create drift.py models**

DriftSignal and DriftReport as specified in spec §4.1.

- [ ] **Step 2: Create drift_detector.py**

Implement `detect_drift(cases, traces, twin, *, as_of, ...)`:
- Domain drift: group cases by (domain, task_type), compute JSD per pair, min_support gates (recent≥3, historical≥5)
- Axis drift: load traces (exclude REFUSED, require non-empty assessments), compute mean delta per axis
- Return DriftReport

JSD implementation (no scipy dependency):
```python
def _jsd(p: list, q: list) -> float:
    """Jensen-Shannon Divergence between two distributions."""
    import math
    m = [(pi + qi) / 2 for pi, qi in zip(p, q)]
    def kl(a, b):
        return sum(ai * math.log(ai / bi) for ai, bi in zip(a, b) if ai > 0 and bi > 0)
    return (kl(p, m) + kl(q, m)) / 2
```

- [ ] **Step 3: Write tests**

```python
class TestDomainDrift:
    def test_detects_choice_shift(self):
        # Historical: 80% chose A. Recent: 80% chose B. JSD should be high.
    def test_no_drift_on_stable_data(self):
        # Both windows have same distribution.
    def test_skips_insufficient_data(self):
        # < min_support cases → no signal generated

class TestAxisDrift:
    def test_detects_axis_confidence_shift(self):
        # Historical traces: axis "growth" avg 0.8. Recent: avg 0.4.
    def test_excludes_refused_traces(self):
        # REFUSED traces should not participate
```

- [ ] **Step 4: Run and commit**

```bash
git commit -m "feat: drift detection — domain JSD + axis mean delta with min_support gates"
```

---

## Chunk 3: Shadow Ontology Pipeline

### Task 4: Document builder

**Files:**
- Create: `src/twin_runtime/application/ontology/__init__.py`
- Create: `src/twin_runtime/application/ontology/document_builder.py`
- Create: `tests/test_ontology.py`

- [ ] **Step 1: Implement document_builder.py**

```python
def build_document(case: CalibrationCase) -> str:
    """Build text document from CalibrationCase for TF-IDF vectorization."""
    parts = [case.observed_context]
    if case.actual_reasoning_if_known:
        parts.append(case.actual_reasoning_if_known)
    # Structural tokens
    parts.append(f"stakes:{case.stakes.value}")
    parts.append(f"reversibility:{case.reversibility.value}")
    parts.append(f"domain:{case.domain_label.value}")
    parts.append(f"task_type:{case.task_type}")
    return " ".join(parts)
```

- [ ] **Step 2: Test and commit**

### Task 5: Clusterer (TF-IDF + Agglomerative)

**Files:**
- Create: `src/twin_runtime/application/ontology/clusterer.py`

- [ ] **Step 1: Implement with scikit-learn guard**

```python
def cluster_cases(
    documents: List[str],
    case_ids: List[str],
    distance_threshold: float = 0.7,
    min_cluster_size: int = 3,
) -> List[Dict]:
    """TF-IDF + Agglomerative clustering. Requires scikit-learn."""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.cluster import AgglomerativeClustering
        from sklearn.metrics.pairwise import cosine_distances
    except ImportError:
        raise ImportError("Shadow ontology requires: pip install twin-runtime[analysis]")

    # Custom tokenizer: word unigrams/bigrams + CJK char bigrams
    import re
    def mixed_tokenizer(text):
        """Tokenize mixed CN/EN: word tokens + CJK character bigrams."""
        # Word tokens (EN words + structural tokens like stakes:high)
        words = re.findall(r'[a-zA-Z_:]+|\d+', text)
        # CJK character bigrams
        cjk = [c for c in text if '\u4e00' <= c <= '\u9fff']
        bigrams = [cjk[i] + cjk[i+1] for i in range(len(cjk) - 1)]
        return words + bigrams

    vectorizer = TfidfVectorizer(
        tokenizer=mixed_tokenizer,
        ngram_range=(1, 2),  # word unigrams and bigrams
        max_features=500,
        sublinear_tf=True,
    )
    tfidf = vectorizer.fit_transform(documents)
    distance_matrix = cosine_distances(tfidf)

    clustering = AgglomerativeClustering(
        metric='precomputed',
        linkage='average',
        distance_threshold=distance_threshold,
        n_clusters=None,
    )
    labels = clustering.fit_predict(distance_matrix)

    # Group by cluster, filter by min size
    clusters = {}
    for idx, label in enumerate(labels):
        clusters.setdefault(label, []).append(idx)

    result = []
    feature_names = vectorizer.get_feature_names_out()
    for label, indices in clusters.items():
        if len(indices) < min_cluster_size:
            continue
        # Top terms
        cluster_tfidf = tfidf[indices].mean(axis=0).A1
        top_indices = cluster_tfidf.argsort()[-5:][::-1]
        top_terms = [feature_names[i] for i in top_indices]
        result.append({
            "label": label,
            "case_ids": [case_ids[i] for i in indices],
            "top_terms": top_terms,
            "size": len(indices),
        })
    return result
```

- [ ] **Step 2: Test and commit**

### Task 6: Stability assessment + report generator

**Files:**
- Create: `src/twin_runtime/domain/models/ontology.py`
- Create: `src/twin_runtime/application/ontology/stability.py`
- Create: `src/twin_runtime/application/ontology/report_generator.py`

- [ ] **Step 1: Create ontology models**

OntologySuggestion, OntologyReport, StabilityCheck as specified in spec §5.5-5.7.

- [ ] **Step 2: Implement stability.py**

Assess each cluster: min_support, decayed_support (using calibration_decay_weight), deterministic label from top-3 terms.

- [ ] **Step 3: Implement report_generator.py**

```python
def generate_ontology_report(
    cases: List[CalibrationCase],
    twin: TwinState,
    *,
    as_of: datetime,
    distance_threshold: float = 0.7,
    min_support: int = 3,
    min_decayed_support: float = 1.5,
) -> OntologyReport:
```

Groups cases by parent domain, clusters within each, assesses stability, assembles report.

- [ ] **Step 4: Tests and commit**

---

## Chunk 4: CLI Commands + Wiring

### Task 7: Add `drift-report` and `ontology-report` CLI commands

**Files:**
- Modify: `src/twin_runtime/cli.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add `[analysis]` optional dependency**

```toml
[project.optional-dependencies]
analysis = ["scikit-learn>=1.3"]
```

- [ ] **Step 2: Add `drift-report` command**

```python
def cmd_drift_report(args):
    config = _load_config()
    user_id = config.get("user_id", "default")
    twin = _require_twin(config)
    # Load cases and traces
    cal_store = CalibrationStore(str(_STORE_DIR), user_id)
    trace_store = JsonFileTraceStore(str(_STORE_DIR / user_id / "traces"))
    cases = cal_store.list_cases(used=None)
    traces = [trace_store.load_trace(tid) for tid in trace_store.list_traces(limit=10000)]  # Read all traces for drift analysis, not default 50
    # Detect drift
    from twin_runtime.application.calibration.drift_detector import detect_drift
    report = detect_drift(cases, traces, twin)

    # Persist report
    import json
    report_dir = _STORE_DIR / user_id / "reports" / "drift"
    report_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output if hasattr(args, 'output') and args.output else str(report_dir / f"{report.as_of.strftime('%Y%m%d_%H%M%S')}.json")
    Path(output_path).write_text(report.model_dump_json(indent=2))
    print(f"Drift report saved: {output_path}")
    print(f"Domain signals: {len(report.domain_signals)}, Axis signals: {len(report.axis_signals)}")
    for sig in report.domain_signals:
        print(f"  [{sig.dimension}] {sig.direction} (magnitude={sig.magnitude:.2f})")
    for sig in report.axis_signals:
        print(f"  [{sig.dimension}] {sig.direction} (magnitude={sig.magnitude:.2f})")
```

- [ ] **Step 3: Add `ontology-report` command**

```python
def cmd_ontology_report(args):
    try:
        from twin_runtime.application.ontology.report_generator import generate_ontology_report
    except ImportError:
        print("This command requires: pip install twin-runtime[analysis]")
        return

    config = _load_config()
    user_id = config.get("user_id", "default")
    twin = _require_twin(config)
    cal_store = CalibrationStore(str(_STORE_DIR), user_id)
    cases = cal_store.list_cases(used=None)

    report = generate_ontology_report(cases, twin)

    # Persist report
    report_dir = _STORE_DIR / user_id / "reports" / "ontology"
    report_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output if hasattr(args, 'output') and args.output else str(report_dir / f"{report.as_of.strftime('%Y%m%d_%H%M%S')}.json")
    Path(output_path).write_text(report.model_dump_json(indent=2))
    print(f"Ontology report saved: {output_path}")
    print(f"Domains analyzed: {report.domains_analyzed}")
    print(f"Suggestions: {len(report.suggestions)}")
    for s in report.suggestions:
        label = s.llm_label or s.deterministic_label
        print(f"  [{s.parent_domain.value}] {label} (support={s.support_count}, stability={s.stability_score:.2f})")
```

- [ ] **Step 4: Register commands in main()**

- [ ] **Step 5: Run full suite and commit**

```bash
python3 -m pytest tests/ -q -m "not requires_llm" --tb=short
git commit -m "feat: drift-report and ontology-report CLI commands"
```

---

## Final Verification

- [ ] **Full test suite**: `python3 -m pytest tests/ -q -m "not requires_llm" --tb=short` — all 403+ pass
- [ ] **10 golden traces unchanged**: `python3 -m pytest tests/test_golden_traces.py -v`
- [ ] **Time decay**: `python3 -m pytest tests/test_time_decay.py -v`
- [ ] **Drift detection**: `python3 -m pytest tests/test_drift_detector.py -v`
- [ ] **Ontology** (requires sklearn): `python3 -m pytest tests/test_ontology.py -v`
- [ ] **Runtime impact zero**: no changes to runner, orchestrator, route_decision, deliberation, single_pass

**Ontology test strategy:** `tests/test_ontology.py` must use `pytest.importorskip("sklearn")` at module level. Tests skip gracefully when scikit-learn is not installed. CI can optionally install `[analysis]` extra for full coverage. This matches the "optional dependency" contract — tests don't fail, they skip.

---

## Notes

- **scikit-learn is optional** — only `ontology-report` needs it. All other 5c features work without it.
- **Evidence decay API is built and tested but has no active consumer in 5c v1.** Document builder uses CalibrationCase only.
- **contradiction_discount** field is added but always None — reserved for future phases.
- **Drift detector excludes REFUSED traces** for axis drift. Includes DEGRADED/DIRECT/CLARIFIED.
- **Shadow ontology clusters within parent domain only** — no cross-domain mixing.

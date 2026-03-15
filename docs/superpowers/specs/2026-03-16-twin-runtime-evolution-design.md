# twin-runtime Evolution Design Spec

## Strategic Context

### One-Line Positioning

> **twin-runtime is not a memory system — it's a calibrated judgment engine built on top of memory.**

Memory infrastructure (Mem0, OmniMemory, MemOS) solves "AI should remember things."
twin-runtime solves "AI should make decisions **like you** — and know when it can't."

### Relationship to Memory Ecosystem

twin-runtime is a **consumer** of memory infrastructure, not a competitor.

```
┌──────────────────────────────────────────────────┐
│           twin-runtime (judgment layer)           │
│  ┌───────────┐  ┌─────────────┐  ┌────────────┐  │
│  │Calibration│  │ Constrained │  │  Fidelity  │  │
│  │   Loop    │  │  Pipeline   │  │  Metrics   │  │
│  └─────┬─────┘  └──────┬──────┘  └──────┬─────┘  │
│        └────────────────┼────────────────┘        │
│              Evidence Abstraction Layer            │
├───────────────────────────────────────────────────┤
│           Memory Backend (pluggable)              │
│  ┌───────┐  ┌────────┐  ┌──────────┐  ┌───────┐  │
│  │ JSON  │  │  Mem0  │  │OmniMemory│  │ MemOS │  │
│  │(default)│ │(opt.)  │  │  (opt.)  │  │(opt.) │  │
│  └───────┘  └────────┘  └──────────┘  └───────┘  │
│         (+ LanceDB, Neo4j, etc.)                  │
├───────────────────────────────────────────────────┤
│             Data Sources (adapters)               │
│   OpenClaw · Notion · Gmail · Calendar · Docs     │
└───────────────────────────────────────────────────┘
```

### What We Are NOT

1. **Not RAG** — We don't "retrieve and stuff into prompt." We compile memory into structured personality parameters, then run decisions through a constrained pipeline.
2. **Not a Persona Prompt** — We have quantified decision variables, per-domain reliability scores, a calibration loop, and bias correction.
3. **Not a Memory Plugin** — Memory is our input layer. Judgment calibration is our output.

### Competitive Moat

| Capability | Mem0 / OmniMemory / MemOS | twin-runtime |
|---|---|---|
| Persistent memory storage | Core competency | Plugs into theirs |
| Cross-session recall | Core competency | Via their backends |
| Structured persona modeling | Not offered | **Core competency** |
| Constrained decision pipeline | Not offered | **Core competency** |
| Calibration loop + fidelity metrics | Not offered | **Core competency** |
| "Knows what it doesn't know" | Not offered | **Core competency** |
| Multi-domain conflict arbitration | Not offered | **Core competency** |

### Go-To-Market

1. **Phase: OpenClaw Plugin** — Distribute as OpenClaw MCP server for ecosystem leverage
2. **Phase: Independent SDK** — Abstract into standalone SDK (Cursor, Windsurf, custom agents)
3. **Phase: Platform** — Multi-twin collaboration, team memory, enterprise controls

---

## Architecture Evolution: 5 Dimensions

### Overview

Five dimensions of evolution, each building on the previous:

1. **Evidence Structuring** — From flat text fragments to typed, temporal, deduplicated evidence objects
2. **Memory Backend Abstraction** — Pluggable storage/recall protocols with fine-grained interfaces
3. **Memory Access Planner** — Runtime evidence scheduling based on situation context
4. **Calibration Enhancement** — Online micro-calibration, outcome tracking, dedup fusion
5. **OpenClaw Plugin + Open Source Release** — Distribution and adoption

### Infrastructure Philosophy

- **Core engine**: Zero external dependencies beyond Pydantic + Anthropic SDK
- **Optional backends**: `twin-runtime[mem0]`, `twin-runtime[graph]`, `twin-runtime[vector]`
- **B-path architecture**: Start lightweight, allow progressive enhancement

---

## Dimension 1: Evidence Layer Structuring

### Problem

Current `EvidenceFragment` is a flat structure. All evidence types share one schema with `structured_data: Dict[str, Any]`. This means:
- Compiler cannot distinguish structural differences between evidence types
- Temporal information is a single `timestamp` with no validity window
- Cross-source deduplication is impossible without semantic fingerprinting

### Design

#### 1.1 Typed Evidence Fragments

```python
class EvidenceFragment(BaseModel):
    """Base class — common fields for all evidence."""
    fragment_id: str
    user_id: str                  # Owner — required for multi-user isolation
    source_type: str
    source_id: str
    evidence_type: EvidenceType
    occurred_at: datetime         # When the event happened
    valid_from: datetime          # When this evidence starts being relevant
    valid_until: Optional[datetime] = None  # When it stops (None = still valid)
    domain_hint: Optional[DomainEnum] = None
    summary: str
    confidence: float
    extraction_method: str
    content_hash: str             # For cross-source dedup

class DecisionEvidence(EvidenceFragment):
    """User made or described a decision."""
    evidence_type: Literal[EvidenceType.DECISION] = EvidenceType.DECISION
    option_set: List[str]
    chosen: str
    reasoning: Optional[str] = None
    stakes: Optional[OrdinalTriLevel] = None
    outcome_known: bool = False

class PreferenceEvidence(EvidenceFragment):
    """User expressed a preference along some dimension."""
    evidence_type: Literal[EvidenceType.PREFERENCE] = EvidenceType.PREFERENCE
    dimension: str                # e.g. "risk_tolerance", "work_environment"
    direction: str                # e.g. "prefers_low", "prefers_high", "prefers_X_over_Y"
    strength: float               # 0.0-1.0
    context: Optional[str] = None

class BehaviorEvidence(EvidenceFragment):
    """Observed behavioral pattern."""
    evidence_type: Literal[EvidenceType.BEHAVIOR] = EvidenceType.BEHAVIOR
    action_type: str              # e.g. "meeting_pattern", "tool_usage", "schedule"
    pattern: str                  # Description of the pattern
    frequency: Optional[str] = None
    structured_metrics: Dict[str, Any] = {}

class ReflectionEvidence(EvidenceFragment):
    """User's self-reflection or retrospective."""
    evidence_type: Literal[EvidenceType.REFLECTION] = EvidenceType.REFLECTION
    topic: str
    sentiment: Optional[str] = None    # "positive", "negative", "mixed", "neutral"
    insight: str
    references_decision: Optional[str] = None  # Links to a DecisionEvidence

class InteractionStyleEvidence(EvidenceFragment):
    """How the user communicates and collaborates."""
    evidence_type: Literal[EvidenceType.INTERACTION_STYLE] = EvidenceType.INTERACTION_STYLE
    style_markers: List[str]      # e.g. ["direct", "concise", "uses_analogies"]
    context: str                  # "in emails", "in meetings", "with reports"

class ContextEvidence(EvidenceFragment):
    """Background context: role, environment, tools, relationships.

    Migrated from the existing EvidenceType.CONTEXT. Captures information
    that isn't a decision, preference, behavior, or reflection, but provides
    important background for interpreting other evidence.
    """
    evidence_type: Literal[EvidenceType.CONTEXT] = EvidenceType.CONTEXT
    context_category: str         # "role", "environment", "tools", "relationship", "project"
    description: str
    structured_data: Dict[str, Any] = {}  # Flexible payload for varied context types
```

Note: `OrdinalTriLevel` is an existing enum in `models/primitives.py` with values: `LOW`, `MEDIUM`, `HIGH`.

#### 1.2 Temporal Semantics

The three timestamps serve distinct purposes:
- `occurred_at`: When did this happen? (For ordering and recency)
- `valid_from`: When did this preference/state start being true? (For applicability)
- `valid_until`: When did it stop? (For filtering stale evidence)

Example: User said on March 1 "I've been risk-averse since joining Tencent in September."
- `occurred_at = 2026-03-01` (when they said it)
- `valid_from = 2025-09-01` (when they joined Tencent)
- `valid_until = None` (still true)

#### 1.3 Content Hash and Deduplication

```python
def compute_content_hash(fragment: EvidenceFragment) -> str:
    """Compute semantic fingerprint for cross-source dedup.

    Based on: evidence_type + domain_hint + core content fields.
    Excludes: source_type, source_id, confidence, extraction_method, user_id.
    This means the same decision seen in Gmail and Notion produces the same hash.

    Per-subclass hash inputs:
      DecisionEvidence:          hash(DECISION + domain_hint + sorted(option_set) + chosen)
      PreferenceEvidence:        hash(PREFERENCE + domain_hint + dimension + direction)
      BehaviorEvidence:          hash(BEHAVIOR + domain_hint + action_type + pattern)
      ReflectionEvidence:        hash(REFLECTION + domain_hint + topic + insight[:100])
      InteractionStyleEvidence:  hash(INTERACTION_STYLE + sorted(style_markers) + context)
      ContextEvidence:           hash(CONTEXT + domain_hint + context_category + description[:100])
    """
```

#### 1.4 Evidence Clustering

When dedup detects fragments with matching `content_hash` from different sources:

```python
class EvidenceCluster(BaseModel):
    """Multiple fragments describing the same underlying event."""
    cluster_id: str
    canonical_fragment: EvidenceFragment  # Highest confidence one
    supporting_fragments: List[EvidenceFragment]  # All others
    source_types: List[str]       # Which sources corroborated
    merged_confidence: float      # Boosted by multi-source corroboration
```

Multi-source corroboration *increases* confidence — if Gmail AND Notion AND Calendar all reference the same decision, we're more certain it happened.

#### 1.5 Cold Start Path

`PersonaCompiler._create_initial()` currently raises `NotImplementedError`. Design:

1. If zero evidence: create a **minimal TwinState** with:
   - All core parameters at population median (risk_tolerance=0.5, etc.)
   - All domain head reliabilities at 0.3 (below threshold — twin will DEGRADE/REFUSE)
   - ScopeDeclaration: everything marked `weakly_modeled`
   - state_version: `v000-cold-start`

2. If some evidence but insufficient for full compilation:
   - Set parameters where evidence exists
   - Leave others at median with low confidence
   - Mark domains with <3 evidence fragments as `unmodeled`

This means a new user gets a twin that **mostly refuses or degrades**, which is the correct behavior — the twin knows it doesn't know you yet.

---

## Dimension 2: Memory Backend Abstraction

### Problem

`TwinStore` and `CalibrationStore` directly write JSON files. No abstraction for plugging in Mem0, OmniMemory, or other backends. Also, a single `MemoryBackend` interface is too coarse — different consumers need different capabilities.

### Design

#### 2.1 Fine-Grained Backend Protocols

Split into focused protocols rather than one monolithic interface:

```python
class TwinStateStore(Protocol):
    """Store and retrieve versioned TwinState snapshots."""
    def save_state(self, state: TwinState) -> str: ...
    def load_state(self, user_id: str, version: Optional[str] = None) -> TwinState: ...
    def list_versions(self, user_id: str) -> List[str]: ...
    def has_current(self, user_id: str) -> bool: ...
    def rollback(self, user_id: str, version: str) -> TwinState: ...

class EvidenceStore(Protocol):
    """Store and query evidence fragments."""
    def store_fragment(self, fragment: EvidenceFragment) -> str: ...
    def store_cluster(self, cluster: EvidenceCluster) -> str: ...
    def query(self, query: RecallQuery) -> List[EvidenceFragment]: ...
    def get_by_hash(self, content_hash: str) -> Optional[EvidenceFragment]: ...
    def count(self, user_id: str, filters: Optional[Dict] = None) -> int: ...

class CalibrationStore(Protocol):
    """Store calibration lifecycle objects."""
    def save_candidate(self, candidate: CandidateCalibrationCase) -> str: ...
    def save_case(self, case: CalibrationCase) -> str: ...
    def save_evaluation(self, evaluation: TwinEvaluation) -> str: ...
    def save_event(self, event: RuntimeEvent) -> str: ...
    def save_outcome(self, outcome: OutcomeRecord) -> str: ...
    def list_cases(self, used: Optional[bool] = None) -> List[CalibrationCase]: ...
    def list_events(self, since: Optional[datetime] = None) -> List[RuntimeEvent]: ...

class TraceStore(Protocol):
    """Store runtime decision traces for audit."""
    def save_trace(self, trace: RuntimeDecisionTrace) -> str: ...
    def load_trace(self, trace_id: str) -> RuntimeDecisionTrace: ...
    def list_traces(self, user_id: str, limit: int = 50) -> List[str]: ...
```

#### 2.2 RecallQuery Types

```python
class RecallQuery(BaseModel):
    """Typed query for evidence retrieval."""
    query_type: Literal[
        "by_topic",           # Keyword/semantic search
        "by_timeline",        # Time-range scan
        "by_domain",          # All evidence for a domain
        "by_evidence_type",   # All evidence of a specific type
        "decisions_about",    # Decision history on a topic
        "preference_on_axis", # Preference evolution along a dimension
        "state_trajectory",   # How a state variable changed over time
        "similar_situations", # Past situations similar to current
    ]
    user_id: str
    time_range: Optional[Tuple[datetime, datetime]] = None
    domain_filter: Optional[List[DomainEnum]] = None
    evidence_type_filter: Optional[List[EvidenceType]] = None
    limit: int = 20
    sort_by: Literal["recency", "relevance", "confidence"] = "recency"

    # Query-type-specific parameters (use the one matching query_type):
    topic_keywords: Optional[List[str]] = None       # for "by_topic"
    target_domain: Optional[DomainEnum] = None        # for "by_domain"
    target_evidence_type: Optional[EvidenceType] = None  # for "by_evidence_type"
    decision_topic: Optional[str] = None              # for "decisions_about"
    preference_dimension: Optional[str] = None        # for "preference_on_axis"
    state_variable: Optional[str] = None              # for "state_trajectory"
    situation_description: Optional[str] = None       # for "similar_situations"
```

Expected parameters per query_type:

| query_type | Required parameters |
|-----------|-------------------|
| `by_topic` | `topic_keywords` |
| `by_timeline` | `time_range` |
| `by_domain` | `target_domain` |
| `by_evidence_type` | `target_evidence_type` |
| `decisions_about` | `decision_topic` |
| `preference_on_axis` | `preference_dimension` |
| `state_trajectory` | `state_variable`, `time_range` |
| `similar_situations` | `situation_description` |

#### 2.3 Default Implementation

`JsonFileBackend` implements all four protocols using the existing JSON file storage pattern. Behavior unchanged from current `TwinStore` + `CalibrationStore` — this is a pure refactor.

#### 2.4 Optional Backend Adapters (Future)

Each optional backend only needs to implement the protocols it supports:

| Backend | TwinStateStore | EvidenceStore | CalibrationStore | TraceStore |
|---------|---------------|---------------|-----------------|------------|
| JsonFile (default) | Yes | Yes | Yes | Yes |
| Mem0 | No | Yes (recall) | No | No |
| LanceDB | No | Yes (vector query) | No | No |
| NetworkX/rustworkx | No | Yes (graph query) | No | No |

The system composes backends: e.g., JsonFile for TwinState + Mem0 for EvidenceStore.

---

## Dimension 3: Memory Access Planner

### Problem

Currently the runtime pipeline only uses the pre-compiled TwinState. It doesn't dynamically retrieve raw evidence at decision time. For complex decisions, the twin would benefit from accessing "what did I actually do last time in a similar situation" — but the pipeline has no mechanism to decide what to retrieve, how much, or in what order.

### Design

#### 3.1 Planner Position in Pipeline

```
Query → Situation Interpreter → Memory Access Planner → Head Activator → ...
                                       │
                                       ├─ Decides which RecallQueries to issue
                                       ├─ Retrieves relevant evidence
                                       ├─ Filters, ranks, truncates to budget
                                       └─ Injects into Head Activator context
```

#### 3.2 MemoryAccessPlan

```python
class MemoryAccessPlan(BaseModel):
    """Output of the planner: what evidence to retrieve and how."""
    queries: List[RecallQuery]        # Ordered by priority
    execution_strategy: Literal["parallel", "sequential", "conditional"]
    total_evidence_budget: int        # Max fragments to inject into pipeline
    per_query_limit: int              # Max per individual query
    freshness_preference: Literal["recent_first", "historical_first", "balanced"]
    disabled_evidence_types: List[EvidenceType]  # Types to skip for this scenario
    rationale: str                    # Human-readable explanation (auditable)
```

#### 3.3 Planning Logic

**Rule-based primary, LLM fallback** — consistent with Situation Interpreter's three-stage pattern.

Decision table (core rules):

| Situation Signal | Planner Action |
|-----------------|----------------|
| High stakes + low uncertainty | `decisions_about` same topic — verify consistency with past choices |
| High ambiguity | `preference_on_axis` — check if user has expressed relevant preferences |
| Multiple domains activated | Per-domain `by_domain` queries + `state_trajectory` for cross-domain patterns |
| Unmodeled domain | Disable `BehaviorEvidence` (no data), prioritize `ReflectionEvidence` |
| Time-sensitive decision | `freshness_preference = "recent_first"`, limit to 30 days |
| Recurring decision type | `similar_situations` — find past instances of same decision pattern |
| Low routing confidence | Expand evidence budget, add `by_timeline` for broader context |

LLM fallback triggers only when: rule-based planner produces zero queries AND situation frame has ambiguity > 0.7.

#### 3.4 Evidence Injection

Retrieved evidence is injected into Head Activator as structured context:

```python
class EnrichedActivationContext(BaseModel):
    """What Head Activator receives after Planner enrichment."""
    twin: TwinState                    # Compiled persona parameters
    frame: SituationFrame              # Situation interpretation
    retrieved_evidence: List[EvidenceFragment]  # Dynamic evidence from Planner
    retrieval_rationale: str           # Why this evidence was selected
```

Head Activator's LLM prompt includes both the compiled TwinState parameters AND the raw evidence fragments, allowing it to reason with specific examples rather than just aggregate parameters.

---

## Dimension 4: Calibration Enhancement

### Problem

Current calibration is batch-only, has no dedup, no outcome tracking, and reasoning similarity is keyword-based.

### Design

#### 4.1 Online Micro-Calibration

After each runtime decision, if user provides immediate feedback:

```python
class MicroCalibrationUpdate(BaseModel):
    """Lightweight parameter adjustment from single observation."""
    trace_id: str
    agreed: bool                      # Did user agree with twin's recommendation?
    user_choice: Optional[str]        # What user actually chose (if different)

    # Only these parameters are touched:
    affected_domain: DomainEnum
    head_reliability_delta: float     # Small adjustment (learning_rate = 0.05)
    core_confidence_delta: float      # Small adjustment
```

Key constraints:
- Learning rate = 0.05 (vs batch calibration's 0.3)
- Only updates `head_reliability` and `core_confidence`
- Does NOT touch goal_axes, causal_belief_model, or evidence_weight_profile
- Those require batch calibration with sufficient evidence (minimum 3 cases)
- All micro-updates are logged and reversible

#### 4.2 Outcome Tracking

```python
class OutcomeRecord(BaseModel):
    """Track what happened after a decision."""
    outcome_id: str
    decision_trace_id: str
    outcome_observed_at: datetime
    outcome_quality: Literal["positive", "neutral", "negative"]
    outcome_description: str
    user_retrospective: Optional[str] = None  # "Looking back, I think I chose right/wrong"
    affects_calibration: bool = True   # Should this feed into next batch eval?
```

This upgrades calibration from "did the twin guess right?" to "did the twin guess right AND was the outcome good?" — enabling the system to learn from consequential feedback, not just choice matching.

#### 4.3 Evidence Dedup and Fusion

During `PersonaCompiler.collect_evidence()`:

1. Compute `content_hash` for each new fragment
2. Check EvidenceStore for existing fragments with same hash
3. If match found: create `EvidenceCluster`, boost confidence
4. If no match: store as standalone fragment

Dedup is **deterministic** (hash-based), not LLM-based. The hash function uses: `evidence_type + domain_hint + normalized(core_content_fields)`.

#### 4.4 Enhanced Fidelity Metrics

```python
class TwinFidelityScore(BaseModel):
    """Comprehensive fidelity measurement."""

    # Choice Fidelity
    top1_accuracy: float              # Twin's #1 pick matches user's actual choice
    ranking_correlation: float         # Kendall's tau between twin ranking and user preference
    per_domain_accuracy: Dict[str, float]

    # Reasoning Fidelity
    axis_alignment: float             # Did twin activate the right goal_axes?
    weight_alignment: float           # Did twin weight axes in the right order?
    semantic_similarity: Optional[float]  # Embedding cosine (optional dependency)

    # Calibration Quality
    expected_calibration_error: float  # ECE: when twin says 80% confident, is it 80% right?
    scope_accuracy: float             # REFUSED/DEGRADED cases were indeed hard cases?

    # Temporal Stability
    consistency_score: float          # Same question asked multiple times → same ranking?
    fidelity_trend: Literal["improving", "stable", "degrading"]

    # Aggregate
    overall_tfs: float                # Weighted combination
    evaluated_at: datetime
    case_count: int
```

#### 4.5 Prior Bias Auto-Detection

During batch evaluation, automatically detect systematic patterns:

```python
class DetectedBias(BaseModel):
    """Automatically discovered bias pattern."""
    pattern_id: str
    description: str                   # "Twin consistently over-estimates risk tolerance in money domain"
    affected_domain: DomainEnum
    detection_method: str              # "calibration_residual_analysis"
    severity: float                    # 0.0-1.0
    supporting_case_ids: List[str]
    suggested_correction: str          # "Apply reweight correction to money.risk_tolerance"
```

Detection method: After batch evaluation, compute per-domain residuals. If residuals are consistently biased in one direction (>2 standard deviations), flag as potential prior bias. This is deterministic statistical analysis, not LLM-based.

---

## Dimension 5: OpenClaw Plugin + Open Source Release

### 5.1 OpenClaw MCP Server

Expose twin-runtime as tools that OpenClaw agents can call:

| Tool | Description |
|------|------------|
| `twin_decide` | Given a decision query and options, return twin's recommendation with reasoning |
| `twin_reflect` | Feed a user reflection/observation back to the twin for evidence collection |
| `twin_calibrate` | Provide feedback on a past decision (agree/disagree/chose differently) |
| `twin_status` | Show current twin fidelity, domain reliability, and scope |
| `twin_history` | Show recent decision traces and their outcomes |

### 5.2 Auto-Inject Mode (Optional)

Similar to Mem0's auto-recall: before the agent responds to decision-like queries, automatically invoke `twin_decide` and inject the twin's perspective into the agent's context.

Detection: keyword-based (same decision keywords used in Gmail adapter), not LLM-based. User can disable.

### 5.3 Open Source Package

- PyPI: `pip install twin-runtime`
- Console entry: `twin-runtime` command
- Optional extras: `twin-runtime[mem0]`, `twin-runtime[graph]`, `twin-runtime[vector]`
- License: Apache 2.0 (permissive, enterprise-friendly)
- README: positioning + 30-second quickstart + architecture diagram + demo GIF

---

## Target Architecture: 4-Layer Package Structure

### Layer Design

```
src/twin_runtime/
├── domain/                          # Pure objects and rules — ZERO side effects
│   ├── models/                      # TwinState, SituationFrame, HeadAssessment, etc.
│   │   ├── twin_state.py
│   │   ├── primitives.py
│   │   ├── runtime_trace.py
│   │   └── calibration.py
│   ├── evidence/                    # Typed EvidenceFragment subclasses
│   │   ├── fragments.py            # DecisionEvidence, PreferenceEvidence, etc.
│   │   ├── clustering.py           # EvidenceCluster, dedup logic
│   │   └── temporal.py             # Temporal filtering, validity checks
│   ├── fidelity/                    # TwinFidelityScore, DetectedBias definitions
│   │   └── metrics.py
│   ├── ports/                       # Abstract protocols (Ports & Adapters pattern)
│   │   ├── twin_state_store.py     # TwinStateStore Protocol
│   │   ├── evidence_store.py       # EvidenceStore Protocol
│   │   ├── calibration_store.py    # CalibrationStore Protocol
│   │   ├── trace_store.py          # TraceStore Protocol
│   │   └── llm_port.py             # LLMClient Protocol (for testability)
│   └── rules/                       # Pure rule functions (no IO, no LLM)
│       ├── conflict_rules.py        # Conflict detection and classification
│       ├── routing_rules.py         # Domain routing policy
│       ├── planner_rules.py         # Memory access planning rules
│       └── calibration_rules.py     # Micro-calibration math, EMA formulas
│
├── application/                     # Orchestration — coordinates domain + infrastructure
│   ├── pipeline/                    # 4-stage runtime pipeline
│   │   ├── situation_interpreter.py
│   │   ├── head_activator.py
│   │   ├── conflict_arbiter.py
│   │   ├── decision_synthesizer.py
│   │   └── runner.py               # Pipeline orchestrator
│   ├── planner/                     # Memory Access Planner
│   │   └── memory_access_planner.py
│   ├── calibration/                 # Calibration loop orchestration
│   │   ├── event_collector.py
│   │   ├── case_manager.py
│   │   ├── fidelity_evaluator.py
│   │   ├── state_updater.py
│   │   ├── micro_calibrator.py
│   │   └── bias_detector.py
│   └── compiler/                    # Evidence → TwinState compilation
│       └── persona_compiler.py
│
├── infrastructure/                  # IO, external systems, side effects
│   ├── backends/                    # Storage backend implementations (adapters for ports)
│   │   ├── json_file/              # Default JSON file backend
│   │   │   ├── twin_store.py       # Implements domain.ports.TwinStateStore
│   │   │   ├── evidence_store.py   # Implements domain.ports.EvidenceStore
│   │   │   ├── calibration_store.py # Implements domain.ports.CalibrationStore
│   │   │   └── trace_store.py      # Implements domain.ports.TraceStore
│   │   └── __init__.py
│   ├── sources/                     # Data source adapters
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── openclaw_adapter.py
│   │   ├── notion_adapter.py
│   │   ├── gmail_adapter.py
│   │   ├── calendar_adapter.py
│   │   ├── document_adapter.py
│   │   └── google_auth.py
│   └── llm/                         # LLM client (implements domain.ports.LLMClient)
│       └── client.py
│
└── interfaces/                      # Entry points — CLI, MCP server, API
    ├── cli.py                       # twin-runtime CLI
    └── server/                      # OpenClaw MCP server (Phase 4)
        └── mcp_server.py
```

### Layer Rules (Ports & Adapters / Hexagonal Architecture)

| Layer | Can depend on | Cannot depend on | Contains |
|-------|--------------|-----------------|----------|
| **domain/** | Nothing (only stdlib + pydantic) | application, infrastructure, interfaces | Models, enums, pure functions, rules, **port definitions (protocols)** |
| **application/** | domain/ (including ports) | infrastructure, interfaces | Orchestration logic, pipeline stages, calibration loops. Uses port protocols for IO — never imports infrastructure directly. |
| **infrastructure/** | domain/ (including ports) | application/, interfaces/ | IO implementations (adapters) that satisfy domain port protocols. |
| **interfaces/** | domain/, application/, infrastructure/ | — | CLI, MCP server, HTTP API. Wires infrastructure adapters into application orchestrators. |

**Key principle:** Protocols (ports) live in `domain/ports/`. `application/` depends on these protocols only. `infrastructure/` implements them. `interfaces/` wires concrete implementations into the application layer via dependency injection. This means the entire pipeline and calibration logic can be tested with in-memory mocks — no IO required.

### LLM Determinism Principle

Precise statement of where LLM calls are permitted vs prohibited:

| Component | LLM Allowed? | Rationale |
|-----------|-------------|-----------|
| Situation Interpreter (internal LLM sub-stage) | Yes | Understanding intent requires language comprehension |
| Head Activator | Yes | Per-domain evaluation requires reasoning over persona parameters |
| Decision Synthesizer Step B | Yes (optional) | Surface realization is pure language generation |
| PersonaCompiler parameter extraction | Yes | Extracting structured parameters from unstructured evidence |
| Conflict Arbiter | **No** | Classification is rule-based on structured HeadAssessment data |
| Decision Synthesizer Step A | **No** | Weighted merge is deterministic math |
| Memory Access Planner (primary) | **No** | Rule-based decision table covers 80%+ of cases |
| Memory Access Planner (fallback) | Yes, gated | Only when rule-based produces zero queries AND ambiguity > 0.7 |
| Micro-Calibration | **No** | EMA parameter update is pure math |
| Evidence Dedup | **No** | Hash comparison is deterministic |
| Fidelity Metrics | **No** | Statistical computation on structured data |
| Bias Detection | **No** | Residual analysis on calibration results |

**Principle: LLM calls are confined to the "understanding" boundary (parsing intent, evaluating options, generating prose) and the "extraction" boundary (evidence → parameters). Everything between — routing, merging, calibrating, storing, planning — is deterministic.**

---

## Migration Strategy: Flat → Typed Evidence

Existing evidence fragments (from current adapters and 20 calibration cases) use the flat `EvidenceFragment` with `structured_data: Dict[str, Any]`. Migration approach:

### Lazy Migration (On-Read)

```python
def migrate_fragment(old: dict) -> EvidenceFragment:
    """Convert a legacy flat fragment to a typed subclass.

    Strategy:
    1. Read evidence_type field to determine target subclass
    2. Map structured_data keys to typed fields
    3. Set occurred_at = old.timestamp, valid_from = old.timestamp, valid_until = None
    4. Compute content_hash from migrated fields
    5. Set user_id from context (config or store path)
    6. Fall back to ContextEvidence if mapping fails
    """
```

### Backward Compatibility

- `raw_excerpt` field retained on base class for adapters that haven't been updated yet
- `structured_data` retained on `BehaviorEvidence` and `ContextEvidence` as escape hatch for varied payloads
- Adapters are updated incrementally — each adapter can be migrated independently
- Existing test fixtures remain valid through the migration function

### Migration Order

1. Update `EvidenceFragment` base class (add user_id, temporal triple, content_hash)
2. Define typed subclasses alongside existing base
3. Update adapters one at a time to produce typed fragments
4. Update PersonaCompiler to prefer typed fields, fall back to structured_data
5. Once all adapters are migrated, deprecate flat constructor

---

## Failure Modes

### LLM Unavailable

| Component | Behavior |
|-----------|----------|
| Situation Interpreter | Falls back to keyword-only routing (stage 1 only). Lower quality but functional. |
| Head Activator | Pipeline returns DEGRADED decision with explanation "LLM unavailable, using cached parameters only" |
| Decision Synthesizer Step B | Skip prose generation, return structured decision only |
| PersonaCompiler | Fail with clear error — compilation requires LLM. User retries later. |

### Backend Failure

| Failure | Behavior |
|---------|----------|
| EvidenceStore.query() raises | Memory Access Planner returns empty evidence set. Pipeline proceeds with TwinState only (current behavior). Logged as warning. |
| TwinStateStore.load_state() raises | Fatal — cannot proceed without TwinState. Clear error message. |
| CalibrationStore write fails | Micro-calibration update is lost. Logged. Pipeline decision is unaffected. |
| TraceStore write fails | Decision is returned to user but not persisted for audit. Logged as error. |

### Evidence Quality Issues

| Issue | Behavior |
|-------|----------|
| content_hash collision (different events, same hash) | Accepted risk. Hash uses type + domain + core fields — collision rate should be negligible. If detected via user feedback, add discriminating field to hash. |
| Planner retrieves stale/contradictory evidence | Head Activator sees both TwinState (compiled, recent) and raw evidence (possibly stale). TwinState takes priority for parameter values; raw evidence provides context only. |
| Dedup merges fragments that shouldn't be merged | EvidenceCluster retains all original fragments. If user reports incorrect merge, cluster can be split by removing the canonical_fragment link. |

### Calibration Edge Cases

| Issue | Behavior |
|-------|----------|
| Micro-calibration oscillation (user agrees then disagrees repeatedly) | Learning rate 0.05 limits swing. If >5 micro-updates in same session flip direction, pause micro-calibration and flag for batch eval. |
| Batch evaluation with <3 cases | State updater skips parameter update, only bumps timestamps. Documented as minimum threshold. |
| Outcome contradicts calibration (twin was "wrong" but outcome was good) | OutcomeRecord is stored but does not automatically override calibration. Flagged for manual review. |

---

## Fidelity as Core Metric System

### Twin Fidelity Score (TFS)

```
Twin Fidelity Score (TFS)
├── Choice Fidelity (CF)        — Does the twin rank options like the user?
│   ├── top-1 accuracy          — First choice matches: proportion
│   ├── ranking correlation     — Kendall's tau between twin vs user rankings
│   └── per-domain breakdown    — work: 0.75, money: 0.60, ...
│
├── Reasoning Fidelity (RF)     — Does the twin reason like the user?
│   ├── axis alignment          — Activated goal_axes match user's stated reasons
│   ├── weight alignment        — Axis priority ordering matches
│   └── semantic similarity     — Embedding cosine (optional: twin-runtime[vector])
│
├── Calibration Quality (CQ)    — Does the twin know what it knows?
│   ├── ECE                     — Expected Calibration Error
│   ├── reliability diagram     — Confidence vs actual accuracy curve
│   └── scope accuracy          — REFUSED/DEGRADED on genuinely hard cases?
│
└── Temporal Stability (TS)     — Is the twin consistent over time?
    ├── consistency score       — Same question repeated → same ranking?
    ├── drift detection         — Fidelity trend: improving / stable / degrading
    └── update responsiveness   — New evidence → relevant decisions improve?
```

### Why This Matters

- **For investors:** "Choice Fidelity 0.75, ECE 0.08" is concrete, not vibes
- **For users:** "Your work domain reliability is 0.72, money is 0.50 — trust money decisions less"
- **For differentiation:** Memory products compare recall accuracy. We compare judgment fidelity. Different axis entirely.

---

## Evolution Roadmap

### Phase 0: Current State (Complete)

- Canonical TwinState, 4-stage pipeline, 5 source adapters
- PersonaCompiler, calibration flywheel, CLI
- 86 unit tests, 20 real calibration cases, choice_similarity 0.650

### Phase 1: Evidence Foundation (~2 weeks)

**Goal:** Evidence layer goes from "runs" to "reliable"

- [ ] Typed EvidenceFragment subclasses (Decision/Preference/Behavior/Reflection/InteractionStyle/Context)
- [ ] Temporal triple (occurred_at / valid_from / valid_until)
- [ ] content_hash for cross-source dedup
- [ ] EvidenceCluster for multi-source fusion
- [ ] Cold-start path (PersonaCompiler._create_initial)
- [ ] Update all source adapters to produce typed fragments
- [ ] Update PersonaCompiler to consume typed fragments

**Demo milestone:** New user cold-starts → twin refuses most decisions (correct behavior) → scan + compile → twin starts deciding

### Phase 2a: Package Restructure + Backend Protocols (~2 weeks)

**Goal:** Clean architecture foundation, pluggable storage

- [ ] 4-layer package restructure (domain / application / infrastructure / interfaces)
- [ ] Move all models to domain/, all IO to infrastructure/, all orchestration to application/
- [ ] Update all imports, ensure 86+ tests still pass
- [ ] Define 4 port protocols in domain/ports/ (TwinStateStore, EvidenceStore, CalibrationStore, TraceStore)
- [ ] Implement JsonFileBackend adapters (refactor existing stores to implement ports)
- [ ] RecallQuery type system in domain/

**Demo milestone:** All tests pass with new package structure, backends are swappable

### Phase 2b: Memory Access Planner (~2 weeks)

**Goal:** Runtime gains dynamic evidence retrieval

- [ ] MemoryAccessPlanner (rule-based) in application/planner/
- [ ] Planner integration into pipeline (Interpreter → Planner → Activator)
- [ ] EnrichedActivationContext for Head Activator
- [ ] Planner audit output (which evidence was retrieved and why)

**Demo milestone:** `twin-runtime run` shows which evidence the Planner retrieved and why

### Phase 3: Calibration Enhancement + Fidelity Dashboard (~3 weeks)

**Goal:** Calibration becomes continuous, fidelity becomes quantifiable

- [ ] MicroCalibrationUpdate (online, learning_rate=0.05)
- [ ] OutcomeRecord + outcome tracking
- [ ] Evidence dedup in compiler (content_hash based)
- [ ] TwinFidelityScore (CF + RF + CQ + TS)
- [ ] Prior bias auto-detection (residual analysis)
- [ ] HTML fidelity dashboard (`twin-runtime dashboard`)
- [ ] Enhanced reasoning similarity (optional embedding-based)

**Demo milestone:** Dashboard showing fidelity curves, per-domain reliability, bias flags — investor-ready

### Phase 4: OpenClaw Plugin + Open Source Release (~2 weeks)

**Goal:** First users, public presence

- [ ] MCP server with twin_decide / twin_reflect / twin_calibrate / twin_status / twin_history
- [ ] Auto-inject mode (keyword-based trigger, optional)
- [ ] PyPI package + console_scripts
- [ ] README with positioning, quickstart, architecture diagram, demo GIF
- [ ] Apache 2.0 license
- [ ] GitHub Actions CI (tests + linting)

**Demo milestone:** OpenClaw user installs plugin → 30-second setup → agent starts using twin for decisions

### Phase 5: Ecosystem Expansion (Ongoing)

- [ ] `twin-runtime[mem0]` — Mem0 as EvidenceStore backend
- [ ] `twin-runtime[graph]` — NetworkX/rustworkx for evidence graph queries
- [ ] `twin-runtime[vector]` — LanceDB for semantic similarity recall
- [ ] Multi-twin collaboration (team memory pool, shared skills)
- [ ] Simulation environment adapters (OASIS / Concordia / Sotopia)
- [ ] Chinese documentation and community (WeChat group, Zhihu articles)

### Timeline

```
Now        Phase 1       Phase 2a      Phase 2b      Phase 3       Phase 4      Phase 5
 │  Evidence    │  Package    │  Access    │  Calibrate  │  OpenClaw  │  Ecosystem
 │  Foundation  │  Restructure│  Planner   │  + Fidelity │  + Release │  Expansion
 │  ~2 weeks    │  ~2 weeks   │  ~2 weeks  │  ~3 weeks   │  ~2 weeks  │  Ongoing
 ▼              ▼            ▼           ▼            ▼           ▼
MVP ──→ Reliable ──→ Pluggable ──→ Dynamic ──→ Quantifiable ──→ Adoptable ──→ Extensible
        evidence    architecture   recall      fidelity       distribution   ecosystem
```

**Key milestones:**
- Phase 1 complete → can write "how I built a calibrated judgment twin" blog post
- Phase 3 complete → investor demo ready (dashboard + real fidelity data)
- Phase 4 complete → HN / Reddit / V2EX launch, first external users

---

## Appendix: Lessons from Memory Infrastructure Landscape

### What We Absorb

1. **Structured memory objects** (from all players) → Our typed EvidenceFragment subclasses
2. **Temporal anchoring** (from OmniMemory STKG) → Our temporal triple (occurred_at / valid_from / valid_until)
3. **Tool-based memory access** (from OmniMemory ADK) → Our RecallQuery types + Memory Access Planner
4. **Auto-recall/capture pattern** (from Mem0) → Our OpenClaw plugin auto-inject + evidence collection
5. **Team memory pools** (from MemOS/ClawForce) → Future multi-twin collaboration (Phase 5)
6. **Memory isolation + permissions** (from ClawForce) → Our backend protocol design supports per-user isolation

### What We Don't Absorb

1. **Vector-first retrieval** — We don't make vector search a core dependency. It's optional enhancement.
2. **Memory as product** — We don't sell memory storage. We sell judgment calibration.
3. **"Skill deposition"** — MemOS's skill extraction is interesting but orthogonal to judgment fidelity. A twin that knows your skills doesn't necessarily decide like you.
4. **Token optimization as primary metric** — Memory companies measure token reduction. We measure judgment fidelity. Different game.

### The Key Insight

> The memory infrastructure wave validated that "AI should know you" is a real need.
> But "knows you" ≠ "decides like you."
> The gap between memory and judgment is where twin-runtime lives.
> No one else is building there.

# Twin Runtime Substrate Spec v0.1

**Status:** Draft
**Date:** 2026-03-15
**Schema:** `../schema/twin-runtime-core-v0.1.1.schema.json`

---

## 1. Product Thesis

twin-runtime is a calibration-first judgment twin that sits between **real user context** (local files, workspace memory, connected APIs) and **simulation / agent social environments** (OASIS, Concordia, Sotopia, AgentSociety, agent-native networks).

It does not attempt to replicate a complete person. It constructs a **calibrated judgment twin** — a structured runtime that can approximate a specific person's decision-making behavior within known confidence bounds.

**One-line definition:** A system that compiles real-world high-privilege context into a calibrated, auditable, portable judgment twin, and safely injects it into simulation and agent environments.

### Why now

Claude Code / OpenClaw provides, for the first time:
- Local file read access without cloud upload
- Persistent workspace and long-term memory
- Tool calling and browser control
- Multi-agent isolation with per-agent credentials
- Continuous behavioral observation (not one-time upload)

This makes twin construction possible from **longitudinal behavioral evidence** rather than self-reported surveys or uploaded documents.

---

## 2. Goals

1. Construct a structured twin state from observable decision behavior
2. Run the twin as a constrained decision simulator in multiple environments
3. Provide calibrated reliability profiles so users know where the twin is trustworthy
4. Build a flywheel where runtime usage feeds back into calibration
5. Maintain privacy by default: local extraction, derived features only, no raw data in simulation

## Non-Goals

1. Replicate a complete human personality (emotions, aesthetics, humor, trauma responses)
2. Build a new simulation world (adapter to existing ecosystems, not a new world)
3. Replace human decision-making (the twin is a rehearsal tool, not an autonomous agent)
4. Compete with memory-focused products (Mem0, Letta, Rewind) — we build personas, not memory stores
5. Full-model personality fine-tuning in v0.1

---

## 3. Core Architecture

Three layers, each with a distinct responsibility.

### 3.1 Layer 1: Canonical Twin State

The single source of truth for the twin. A structured JSON object, not prose.

Contains:

| Component | Purpose |
|---|---|
| **SharedDecisionCore** | Cross-domain latent decision variables (risk tolerance, ambiguity tolerance, action threshold, regret sensitivity, etc.) |
| **CausalBeliefModel** | How this person models causality — what they believe drives outcomes, which variables are controllable, whether they shape or adapt to systems. Determines the person's default option set. |
| **DomainHeads** | Domain-specific decision heads (work, life_planning, money, relationships, public_expression), each with its own goal axes, evidence weights, reliability score |
| **TransferCoefficients** | Measured strength of decision-style transfer between domains (e.g., work → life_planning: 0.6) |
| **ReliabilityProfile** | Per-domain, per-task confidence intervals — what the twin knows it knows vs. doesn't |
| **ScopeDeclaration** | Explicit boundary: what the twin models, what it doesn't, and what it refuses |
| **PriorBiasProfile** | Known patterns where the base LLM's priors systematically distort this specific twin |
| **BiasCorrectionPolicy** | Active correction rules with validation windows and expiry conditions |
| **TemporalMetadata** | Variable classification (fast/slow/irreversible), major life events, version validity windows |

**Key design principle:** The twin state is versioned. Every calibration cycle produces a new version. Old versions are retained for replay and audit.

### 3.2 Layer 2: Hierarchical Runtime

This is where the LLM actually "acts as" the twin. The critical architectural decision:

> **The LLM is not the twin. The TwinState is the twin. The LLM is a constrained execution engine.**

The runtime operates in two steps:

**Step A — Structured Evaluation:** The LLM receives the twin state + situation frame and outputs a structured intermediate representation: activated domains, head assessments, conflict report, decision with uncertainty. No free-form prose at this stage.

**Step B — Surface Realization:** A separate pass converts the structured evaluation into natural language output. This separation prevents the LLM's language generation priors from contaminating the decision layer.

Runtime components:

```
Input Query
    ↓
[Situation Interpreter] → SituationFrame
    ↓
[Domain Head Activation] → HeadAssessment[]
    ↓
[Conflict Arbiter] → ConflictReport
    ↓
[Decision Synthesizer] → Structured Decision
    ↓
[Surface Realizer] → Natural Language Output
    ↓
[Trace Recorder] → RuntimeDecisionTrace
```

### 3.3 Layer 3: Calibration Engine

The system's soul. Not a data pipeline — a calibration loop.

```
Observe micro-decisions / Collect life-anchor retrospectives
    ↓
Build CalibrationCase
    ↓
Run twin against same scenario
    ↓
Compute fidelity metrics (choice, reasoning, style, social similarity)
    ↓
Estimate transfer coefficients
    ↓
Update TwinState + ReliabilityProfile
    ↓
Runtime produces decisions + traces
    ↓
Collect RuntimeEvents (user corrections, real outcomes, divergences)
    ↓
Generate CandidateCalibrationCases
    ↓
Promote high-value candidates → back to calibration
```

---

## 4. Situation Interpreter

### 4.1 Design Principle

The Situation Interpreter is a **multi-domain router**, not a single-label classifier. Real decisions almost always involve multiple domains simultaneously.

### 4.2 Output: SituationFrame

Three components:

1. **Domain Activation Vector** — Weighted map of which domains are relevant (e.g., `{work: 0.42, money: 0.27, relationships: 0.21, life_planning: 0.10}`)
2. **Situation Feature Vector** — Structured features of the situation: reversibility, stakes, time pressure, identity load, social exposure, dependency scope, uncertainty type, controllability, option structure, situation conflict type
3. **Routing Metadata** — ambiguity score, clarification questions, scope status, routing confidence

### 4.3 Three-Stage Hybrid Routing (v0.1)

**Stage 1: Rule-Based Feature Extraction**
Deterministic extraction of hard features: geographic movement, job change, financial amounts, relationship references, time constraints, irreversible commitments. Goal: stability over cleverness.

**Stage 2: LLM-Assisted Interpretation**
Given the twin's scope and schema, the LLM generates:
- Domain activation draft
- Feature vector draft
- Ambiguity flags
- Candidate clarification questions

This is a candidate, not a final answer.

**Stage 3: Constrained Routing Policy**
Fixed rules determine the final routing:
- Single domain weight clearly dominant (>0.5 gap) → single-domain path
- Top two domains close (<0.15 gap) → multi-domain fusion
- Ambiguity score > threshold → trigger clarification
- Scope status = out_of_scope → apply rejection policy
- Routing confidence < threshold → degrade or clarify

### 4.4 Scope Gate

Before any domain activation, the Situation Interpreter checks the ScopeDeclaration:
- If the query falls into `non_modeled_capabilities` → refuse or degrade per `rejection_policy.out_of_scope`
- If the query is borderline → apply `rejection_policy.borderline`
- Only `in_scope` queries proceed to domain activation

---

## 5. Merger as Conflict Arbiter

### 5.1 Head Assessment Output (v0.1)

Each activated domain head outputs three blocks:

1. **Option ranking** — ordered preference over available options
2. **Utility decomposition** — why it prefers this ranking, broken down by value axes (income, stability, relationship cost, identity alignment, time cost, reversibility)
3. **Confidence + evidence sources** — how certain, based on what

v0.1 does NOT include belief decomposition (probability estimates for outcomes). This requires domain-specific prediction calibration that doesn't exist yet. Deferred to v0.2.

### 5.2 Conflict Typing

When multiple heads are activated, the merger first produces a **ConflictReport** before attempting any merge. Four conflict types:

| Type | Definition | Resolution |
|---|---|---|
| **Preference** | Heads agree on what will happen but disagree on what matters more | Check SharedDecisionCore for stable value rankings. If insufficient, trigger user clarification. System should NOT auto-resolve value conflicts. |
| **Belief** | Heads agree on values but disagree on factual predictions | Use domain reliability scores, historical calibration cases, available evidence to arbitrate. Can often be resolved by system. |
| **Evidence Credibility** | Heads weight the same evidence differently (e.g., work head trusts self-report at face value, relationship head discounts it based on follow-through history) | Use domain-specific evidence discount factors from EvidenceWeightProfile. |
| **Mixed** | Multiple conflict types co-occur | Decompose into separate axes. Resolve belief/evidence conflicts first. Expose remaining preference conflicts to user. |

### 5.3 Merger Flow

```
HeadAssessment[]
    → Conflict Detection (compare option rankings + utility axes)
    → Conflict Typing (preference / belief / evidence_credibility / mixed)
    → Type-Specific Resolution Policy
    → ConflictReport output
    → Final merge or clarification trigger
```

### 5.4 Early-Stage Limitation

In v0.1, SharedDecisionCore is primarily calibrated from work-domain micro-decisions. Its value ranking data for life-domain preference conflicts will be sparse. Expected consequence: **most preference conflicts in non-work domains will fall through to user clarification.** This is correct behavior, not a bug. The spec explicitly acknowledges this.

---

## 6. LLM Prior Contamination

### 6.1 The Problem

When the LLM "plays" the twin, its training-data priors about "what a person like this would do" can override the actual twin state parameters. This is especially dangerous when the real person's profile is counter-stereotypical (e.g., financially conservative entrepreneur, risk-averse in relationships but aggressive in career).

### 6.2 Mitigation Strategy (v0.1)

**Structural separation:** Step A (structured evaluation) forces the LLM to output decisions grounded in explicit TwinState fields before generating prose. This reduces the surface area for prior contamination.

**PriorBiasProfile:** A list of known bias patterns with trigger conditions and severity. Populated through calibration when systematic divergences between twin predictions and actual user behavior are detected.

**BiasCorrectionPolicy:** Active correction rules that modify runtime behavior:

| Action | Effect |
|---|---|
| `reweight` | Adjust domain head weights when specific heads are co-activated |
| `dimension_split` | Force separate evaluation of dimensions the LLM tends to merge (e.g., career risk vs. financial risk) |
| `force_compare` | Require explicit comparison between twin state value and LLM default |
| `block_automerge` | Prevent auto-resolution of specific conflict patterns |
| `force_clarification` | Always ask user in specific trigger conditions |

**Counter-stereotype test cases:** Calibration explicitly includes cases designed to test for prior contamination — scenarios where the twin's actual behavior contradicts the LLM's stereotype of "people like this."

### 6.3 Three-Level Correction Escalation

| Level | Mechanism | When |
|---|---|---|
| L1: Runtime | Structural constraints, reweighting, dimension splits | Default for all detected biases |
| L2: Policy | Write bias pattern + correction entry into TwinState | When same bias appears N≥3 times over T≥7 days with severity >0.5 |
| L3: Model adaptation | Domain-specific LoRA or delta | Only when L1+L2 fail at cohort level. Not in v0.1. |

### 6.4 Option Set Generation

In v0.1, for high-stakes calibration tasks, option sets are provided externally or generated by a neutral option generator separate from the twin runtime. The twin runtime should NOT simultaneously generate options and choose among them — this maximizes prior contamination.

---

## 7. Calibration Engine

### 7.1 Two Sources of Ground Truth

**Source A: Micro-Decision Extraction (abundant)**

Observable from Claude Code / OpenClaw local workspace:
- Which tasks the user prioritizes
- How they respond to messages (tone, delay, content choices)
- What they research vs. skip
- Which code paths they choose
- Document structure and editing patterns
- Meeting scheduling patterns
- File organization decisions

These are observed behaviors, not self-reports. The calibration agent runs locally, in a sandboxed process separate from the twin runtime.

**Source B: Life-Anchor Retrospectives (sparse, high-value)**

User actively describes 3-5 major past decisions:
- The context and constraints at the time
- The options they considered
- What they chose and why
- What happened after

These provide ground truth for exactly the high-stakes, cross-domain decisions that micro-observations can't capture.

### 7.2 CalibrationCase Lifecycle

```
Raw signal (micro-observation, user retrospective, runtime event)
    ↓
CandidateCalibrationCase (tagged with domain, stakes, reversibility)
    ↓
Quality gate: ground_truth_confidence > threshold?
    ↓
Promotion to CalibrationCase
    ↓
Twin runs against same scenario → predicted choice
    ↓
Compare predicted vs. actual → fidelity metrics
    ↓
Update TwinState parameters + ReliabilityProfile
```

### 7.3 Fidelity Metrics

| Metric | What it measures | How |
|---|---|---|
| **Choice similarity** | Does the twin pick the same option? | Direct match rate across calibration cases |
| **Reasoning similarity** | Does the twin cite similar reasons? | Structural comparison of utility decompositions |
| **Style similarity** | Does the twin sound like this person? | Linguistic feature comparison (sentence structure, vocabulary, directness) |
| **Social similarity** | Does the twin interact like this person? | Response pattern matching in multi-agent scenarios |

v0.1 requires `choice_similarity`. Others are optional and progressively added as calibration data grows.

### 7.4 Transfer Coefficient Estimation

For each domain pair (e.g., work → life_planning):
1. Collect calibration cases in both domains
2. Measure SharedDecisionCore fit in source domain
3. Predict target-domain choices using source-domain calibrated core
4. Compare prediction accuracy vs. domain-specific calibration
5. The ratio = transfer coefficient

A high transfer coefficient means work-domain calibration reliably predicts life-domain behavior for this specific user. A low one means the domains operate somewhat independently.

**This coefficient is per-user, not universal.** Some people are highly consistent across domains; others are not.

### 7.5 Runtime → Calibration Flywheel

The calibration engine is not a one-time setup. Runtime usage continuously generates new calibration signal:

| Signal Type | Source | Priority |
|---|---|---|
| **High-divergence** | Twin predicted A, user chose B | Highest — directly reveals calibration error |
| **User correction** | User says "this isn't what I'd do" or rephrases | High — explicit ground truth |
| **Observed outcome** | User actually sent the email / accepted the offer / made the change | High — behavioral confirmation |
| **Low-confidence + high-stakes** | Twin was uncertain on an important decision | Medium — reveals calibration gaps |
| **Clarification invoked** | System asked for user input, got structured response | Medium — new evidence for preference/belief parameters |

These flow through `RuntimeEvent` → `CandidateCalibrationCase` → quality gate → `CalibrationCase` → recalibration.

---

## 8. Scope Declaration Protocol

### 8.1 What the Twin Models

- `preference_selection` — choosing between options based on stable preferences
- `decision_style` — how fast, how much information, how much risk
- `reasoning_frame` — what factors get weighted, what gets ignored
- `limited_social_response` — response patterns in structured interactions

### 8.2 What the Twin Does NOT Model

- `live_emotion_state` — real-time emotional fluctuations
- `aesthetic_taste_full_fidelity` — nuanced aesthetic judgment
- `intimate_tone_replication` — private conversational voice
- `verbatim_autobiographical_memory` — specific recalled experiences
- `identity_performance_in_private` — how the person presents in close relationships
- `trauma_sensitive_responses` — reactions to triggers or deep emotional patterns

### 8.3 Restricted Use Cases

Even within modeled capabilities, the twin should NOT:
- Simulate private conversations for realism assessment
- Make binding commitments on behalf of the user
- Provide high-confidence advice in unmodeled or weakly_modeled domains
- Simulate uncalibrated relationship counterparts

### 8.4 Rejection Behavior

The `RejectionPolicyMap` specifies behavior per scope status:
- `out_of_scope` → default `refuse` (return explicit "I don't model this")
- `borderline` → default `degrade` (answer with heavy caveats and low confidence flag)

### 8.5 Scope Drives Valid Domains

There is no explicit `valid_domains` list. A domain is valid at runtime if and only if its `DomainHead.head_reliability >= ScopeDeclaration.min_reliability_threshold`. This prevents semantic drift between multiple lists.

---

## 9. Temporal Versioning

### 9.1 Variable Classification

| Class | Examples | Behavior |
|---|---|---|
| **Fast variables** | Recent interest focus, current project priorities, active relationships | High recency weight, short evidence window, frequent updates |
| **Slow variables** | Risk tolerance, core values, conflict style | Long evidence window, high inertia, change only with significant evidence |
| **Irreversible shifts** | Major career change, parenthood, significant loss, identity shift | One-directional, triggered by major life events, permanently alter the twin state |

### 9.2 Version Management

- Every calibration cycle that changes TwinState creates a new `state_version`
- `temporal_metadata.state_valid_from` marks when this version became active
- `temporal_metadata.state_valid_to` is null for the current version, set when superseded
- Old versions are retained for:
  - Historical replay (testing what the twin would have said at time T)
  - Calibration comparison (measuring improvement over time)
  - Rollback (if a calibration cycle introduces regression)

### 9.3 Drift Detection

The calibration engine monitors for drift between the twin's slow variables and recent behavior. If slow variables start diverging from observed behavior consistently, this triggers either:
- A recalibration of the slow variable (with high evidence threshold)
- A check for potential irreversible shift (flagged for user confirmation)

---

## 10. Privacy and Data Boundaries

### 10.1 Agent Separation

Three agents with strict isolation:

| Agent | Permissions | Cannot Do |
|---|---|---|
| **Identity Ingestion Agent** | Read local files, browser control, API connectors | Send messages externally, access simulation, write to shared state |
| **Persona Compiler Agent** | Read structured summaries and evidence graphs | Access raw files, access social sessions, access credentials |
| **Simulation Agent** | Read published twin snapshots only | Access raw data, access workspace, access ingestion agent's state |

### 10.2 Data Layer Boundaries

| Layer | Contents | Policy |
|---|---|---|
| **Layer 0: Never collect** | Passwords, 2FA codes, private keys, API keys, session cookies, payment info, password manager contents, full browsing history | Hard-coded exclusion, not configurable |
| **Layer 1: Local-only raw data** | File contents, email bodies, chat messages, calendar details, social media posts | Can be read locally for feature extraction. Raw data never leaves the machine. |
| **Layer 2: Publishable derived features** | SharedDecisionCore parameters, domain head weights, evidence weight profiles, reliability scores, style vectors | This is what TwinState contains. Can be published to simulation environments. |
| **Layer 3: Session context** | Current simulation goal, active role, time window, recent event summaries | Temporary, per-session only. Never enters long-term twin state. |

### 10.3 User Control

Users must be able to:
- See what sources are connected and what data was accessed
- Pause or revoke any source
- See what was published in each twin version
- Roll back to any previous twin version
- Delete the entire twin state
- Switch to fully-offline mode at any time

---

## 11. MVP Scope

### 11.1 Target Users

Digitally-intensive knowledge workers:
- Developers
- Product managers
- Researchers
- Founders

### 11.2 Domains in v0.1

| Domain | Status | Ground Truth |
|---|---|---|
| **work** | Primary, fully calibrated | Micro-decision observation from local workspace |
| **life_planning** | Secondary, explicitly low-reliability | 3-5 user retrospective life-anchor cases + transfer from work |

### 11.3 MVP Outputs

1. **Twin Reliability Profile** — Per-domain, per-task confidence map showing where the twin is calibrated and where it isn't
2. **Decision simulation with uncertainty** — Given a scenario, the twin's predicted choice + reasoning + explicit uncertainty band + scope caveats

### 11.4 What MVP Does NOT Do

- Full-model personality fine-tuning
- Open social network for twin interaction
- Full-domain coverage (money, relationships, public_expression deferred)
- Collective simulation / parallel universe
- Automated option set generation by twin

### 11.5 MVP Success Criteria

- Choice similarity ≥ 0.7 in work domain across 20+ calibration cases
- Transfer coefficient confidence > 0.5 for work → life_planning
- User can identify twin's output vs. generic LLM output at >70% accuracy in blind test
- Reliability profile correctly flags low-confidence domains (no false-high-confidence failures)

---

## 12. Architectural Red Lines

These are non-negotiable constraints for the entire project.

### Red Line 1: Situation Interpreter must be a multi-domain router

No single-label classification. Every query gets a domain activation vector. Multi-domain fusion is the default, not the exception.

### Red Line 2: The LLM is a constrained executor, not the twin

TwinState is the twin. The LLM executes under hard constraints from TwinState fields. No valid output exists without explicit grounding in TwinState. Step A (structured) always precedes Step B (prose).

### Red Line 3: Scope Declaration is an architectural object

It lives in TwinState as a first-class field. It drives runtime rejection behavior, reliability profile boundaries, and user expectation management. It is not documentation.

### Red Line 4: Calibration is continuous, not one-time

Runtime must produce RuntimeEvents. RuntimeEvents must flow into CandidateCalibrationCases. The flywheel is a core system requirement, not a nice-to-have.

### Red Line 5: High-privilege collection and public interaction are isolated

The ingestion agent and the simulation agent must never share a process, credentials, or direct data access. Raw context never enters simulation.

---

## 13. Open Questions

### 13.1 Deferred to v0.2

- **Belief decomposition in HeadAssessment** — requires domain-specific prediction calibration
- **Model-side adaptation (L3 correction)** — requires sufficient cohort data
- **money / relationships / public_expression domain heads** — need dedicated calibration strategies
- **Collective simulation** — requires N users, population bias handling, minimum viable twin pool
- **Population scope declaration** — how to characterize and disclose selection bias in twin pools

### 13.2 Needs Further Design

- **Merger conflict resolution for mixed conflicts** — decomposition algorithm not yet specified
- **Micro-decision extraction heuristics** — what counts as a "decision moment" in a work session? Detection algorithm needed.
- **Calibration case promotion thresholds** — exact values for ground_truth_confidence cutoff, information gain scoring
- **Temporal drift detection algorithm** — how to distinguish slow-variable drift from noise vs. irreversible shift
- **Evidence weight profile calibration** — how does EvidenceWeightProfile itself get calibrated? (meta-calibration problem)
- **Inter-twin interaction protocol** — how two twins interact in simulation, what state they share, how conflicts between twins are handled

### 13.3 Known Risks

- **LLM prior contamination ceiling** — there may be a fidelity ceiling that runtime corrections cannot break through, requiring model-level intervention
- **Preference conflict resolution rate in v0.1** — expected to be low for non-work domains, could frustrate early users
- **Cold start quality** — twin quality on day 1 may be too low to demonstrate value, requiring careful onboarding design
- **Behavioral observation consent** — "always-on calibration agent" creates tension with privacy-first principles, needs explicit UX design

---

## 14. Schema Reference

All core objects are defined in `twin-runtime-core-v0.1.1.schema.json`.

| Object | Purpose |
|---|---|
| `TwinState` | Canonical twin, single source of truth |
| `SituationFrame` | Situation Interpreter output |
| `HeadAssessment` | Per-domain head evaluation |
| `ConflictReport` | Merger conflict analysis |
| `RuntimeDecisionTrace` | Full trace of one decision cycle |
| `RuntimeEvent` | Post-decision observation |
| `CandidateCalibrationCase` | Raw calibration signal |
| `CalibrationCase` | Promoted, validated calibration data |
| `TwinEvaluation` | Batch calibration results |

---

*Spec authored: 2026-03-15*
*Schema version: v0.1.1*
*Next step: Implementation plan for MVP (work domain calibration + basic runtime)*

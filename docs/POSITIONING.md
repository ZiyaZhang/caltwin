# twin-runtime: Strategic Positioning

## One-Line Positioning

> **twin-runtime is not a memory system — it's a calibrated judgment engine built on top of memory.**

Memory infrastructure (Mem0, OmniMemory, MemOS) solves "AI should remember things."
twin-runtime solves "AI should make decisions **like you** — and know when it can't."

## What We Are

A **calibrated judgment twin runtime** that:

1. **Compiles** evidence from multiple sources (OpenClaw, Notion, Gmail, Calendar, documents) into a structured, versioned persona model (TwinState)
2. **Runs** decisions through a constrained pipeline — not a single LLM call, but a multi-stage engine (situation interpretation → domain head activation → conflict arbitration → decision synthesis) that separates structured evaluation from language generation
3. **Calibrates** continuously — every decision the twin makes can be compared against what the user actually chose, closing a feedback loop that measurably improves fidelity over time
4. **Knows its own limits** — per-domain reliability scores, explicit scope declarations, and the ability to DEGRADE or REFUSE when confidence is too low

## What We Are NOT

### Not RAG
We don't "retrieve relevant memories and stuff them into a prompt." We compile memory into structured personality parameters, then run decisions through a constrained pipeline. The LLM fills structured forms — it doesn't freestyle.

### Not a Persona Prompt
We're not `"You are a risk-averse PM who prefers building on existing platforms."` We have quantified decision variables (`risk_tolerance: 0.65`), per-domain reliability scores (`work: 0.72, money: 0.50`), a calibration loop that updates these numbers based on real observed decisions, and bias correction policies.

### Not a Memory Plugin
We don't compete with Mem0, OmniMemory, or MemOS on memory storage and retrieval. Memory is our **input layer** — judgment calibration is our **output**. We consume memory infrastructure; we don't replicate it.

## Relationship to the Memory Ecosystem

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
├───────────────────────────────────────────────────┤
│             Data Sources (adapters)               │
│   OpenClaw · Notion · Gmail · Calendar · Docs     │
└───────────────────────────────────────────────────┘
```

## Competitive Moat

| Capability | Mem0 / OmniMemory / MemOS | twin-runtime |
|---|---|---|
| Persistent memory storage | Core competency | Plugs into theirs |
| Cross-session recall | Core competency | Via their backends |
| Structured persona modeling | Not offered | **Core competency** |
| Constrained decision pipeline | Not offered | **Core competency** |
| Calibration loop + fidelity metrics | Not offered | **Core competency** |
| "Knows what it doesn't know" | Not offered | **Core competency** |
| Multi-domain conflict arbitration | Not offered | **Core competency** |

## Go-To-Market Strategy

### Phase 1: OpenClaw Plugin (Adoption)
- Distribute as an OpenClaw plugin for maximum ecosystem leverage
- Zero-config `pip install`, 30-second setup
- Users experience their "judgment twin" inside OpenClaw immediately

### Phase 2: Independent SDK (Expansion)
- Abstract into a standalone SDK that integrates with any LLM agent framework
- OpenClaw becomes one of many supported platforms (alongside Cursor, Windsurf, custom agents)

### Phase 3: Platform (Scale)
- Multi-twin collaboration, team memory pools, enterprise controls
- Natural evolution once single-twin engine is proven

### Distribution Philosophy
- **Core engine**: Zero external dependencies, `pip install` and run
- **Optional backends**: `twin-runtime[graph]`, `twin-runtime[vector]`, `twin-runtime[mem0]`
- **Open source first**: Build technical reputation and community, then monetize enterprise features

## Core Thesis

The memory infrastructure wave (triggered by OpenClaw's mainstream adoption) has turned "AI should remember" from a niche concern into a universal expectation. But memory alone doesn't create a digital twin — it creates a well-informed chatbot.

**The gap between "remembers you" and "decides like you" is where twin-runtime lives.**

No one else is building a system that:
- Models decision-making as structured, quantified parameters (not vibes)
- Separates structured evaluation from language generation (preventing LLM prior contamination)
- Maintains per-domain reliability scores with explicit uncertainty bounds
- Closes a calibration loop that measurably improves fidelity
- Refuses to act when it knows its confidence is too low

This is our moat. Memory is table stakes. Calibrated judgment is the product.

# Twin Runtime — 7-Minute Demo Script

> Repeatable, self-contained demo showing the full calibration flywheel.
> Total time: ~7 minutes. Each step produces visible metric change.

## Prerequisites

```bash
pip install twin-runtime    # or: pip install -e ".[dev]" (from source)
```

## Step 1: Initialize (30s)

```bash
twin-runtime init
```

When prompted:
- User ID: `demo-user`
- API Key: (your Anthropic key)
- Initial TwinState fixture: `tests/fixtures/sample_twin_state.json`

**What to say:** "First, we initialize the twin with a real decision profile — 5 domain heads covering work, money, life planning, relationships, and public expression."

## Step 2: First Decision — See the Twin Think (60s)

```bash
twin-runtime run "I have two offers: a big-company role at Tencent (stable, good pay) vs a startup CTO role (equity, risk, growth). Which should I take?" \
  -o "Tencent大厂" "创业CTO"
```

**Expected output:**
- Recommended choice with ranking
- Activated domains: work, money, life_planning
- Uncertainty score (~0.3-0.5)
- Natural language reasoning as the twin

**What to say:** "The twin activates multiple domain heads — work priorities, financial analysis, life planning. Notice the uncertainty level: it's honest about what it doesn't know."

## Step 3: Reflect — Feed the Calibration Loop (30s)

```bash
twin-runtime reflect \
  --trace-id <trace_id from step 2> \
  --choice "创业CTO" \
  --reasoning "I value growth and ownership over stability at this career stage"
```

**What to say:** "Now I tell the twin what I actually chose and why. This is the calibration signal — the difference between what it predicted and what I decided. Over time, this narrows."

## Step 4: Check Twin State (30s)

```bash
twin-runtime status
```

**What to say:** "The twin's state shows each domain's reliability score. Domains with more calibration data become more reliable. This is the data moat — every decision makes the model harder to replicate."

## Step 5: Test the Boundary — Abstention (60s)

```bash
twin-runtime run "我最近头疼视力模糊，应该看什么科？" \
  -o "神经内科" "眼科" "全科体检"
```

**Expected output:**
- Mode: REFUSED or DEGRADED
- High uncertainty (>0.7)
- Refusal reason: out of scope

**What to say:** "This is the trust signal investors care about most. The twin REFUSES medical decisions because it's outside its calibrated domains. An AI that can say 'I don't know' is fundamentally more trustworthy than one that guesses."

## Step 6: Batch Evaluation — Quantified Fidelity (120s)

```bash
twin-runtime evaluate
```

**Expected output:**
- Choice Fidelity (CF): ~0.758
- Domain reliability per domain
- Abstention accuracy (if OOS cases present)

**What to say:** "0.758 choice fidelity means the twin's #1 pick matches my actual choice 76% of the time, across 20 real decisions. This is our core KPI — it only goes up with more data."

## Step 7: Visual Dashboard (30s)

```bash
twin-runtime dashboard --output fidelity_report.html --open
```

**What to say:** "The dashboard shows the full fidelity decomposition: choice accuracy, calibration quality, and per-domain breakdown. Every metric has a confidence interval — we don't hide uncertainty."

> To capture screenshot for docs: save as `docs/dashboard-screenshot.png`

## Step 8: Platform Integration — MCP in Claude Code (120s)

```bash
claude mcp add --transport stdio twin-runtime -- twin-runtime mcp-serve
```

Then in Claude Code:
- Use the `twin_decide` tool to make a decision
- Use the `twin_reflect` tool to record what you actually chose
- Use `twin_history` to see past decisions

**What to say:** "The twin runs as an MCP server inside Claude Code. Every AI conversation can invoke calibrated judgment — not generic LLM advice, but YOUR decision model trained on YOUR outcomes."

---

## Key Metrics to Highlight

| Metric | Value | What It Means |
|--------|-------|---------------|
| Choice Fidelity (CF) | 0.758 | 76% top-1 accuracy across 20 real decisions |
| Calibration Quality (CQ) | 0.807 | Stated confidence matches actual accuracy |
| Abstention Correctness | ≥0.9 (target) | Correctly refuses out-of-scope decisions |
| Test Coverage | 329+ tests | Production-grade reliability |

## The Story Arc

1. **Problem:** Base LLMs give generic advice. They don't know YOUR decision patterns.
2. **Solution:** A calibration-first judgment twin that learns from YOUR actual choices.
3. **Evidence:** Real metrics, real decisions, honest uncertainty.
4. **Moat:** Every calibration cycle produces unique assets that can't be replicated by prompt engineering.
5. **Platform:** Runs everywhere — CLI, Claude Code (Skills + MCP), any MCP client.

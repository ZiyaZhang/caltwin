# Phase 4: Launch-Ready Release — Design Spec

**Date:** 2026-03-17
**Status:** Approved (brainstorming complete)
**Predecessor:** Phase 3 (Calibration Enhancement + Fidelity Dashboard)
**Baseline:** CF=0.758, 275 tests, MVP Gate PASS
**Target:** Open source release with Skills + MCP + PyPI + README — investor-demo-ready

## 1. Goals & Narrative

**Primary narrative:** "Not another memory plugin — a calibration-first judgment twin."

**Tagline:** Memory is input. Calibrated judgment is output.

**Alpha boundary (must appear everywhere):**
> v0.1 is an alpha release focused on work-domain calibrated judgment.

**Audience funnel:**
1. **See** → README first screen (B+A+C: problem → positioning → evidence)
2. **Try** → `/twin-decide` skill or `pip install twin-runtime && twin-runtime init`
3. **Stay** → MCP deep integration, calibration loop, dashboard

**Distribution channels:**
- GitHub (primary)
- PyPI (`pip install twin-runtime`)
- OpenClaw Skills (`.claude/skills/` in repo + `install-skills` CLI)
- MCP registry (`.mcp.json` + `claude mcp add`)

## 2. OpenClaw Skills

### Structure

```
.claude/skills/
├── twin-decide/
│   └── SKILL.md
├── twin-reflect/
│   └── SKILL.md
├── twin-calibrate/
│   └── SKILL.md
├── twin-dashboard/
│   └── SKILL.md
└── twin-status/
    └── SKILL.md
```

Mirror copy in `src/twin_runtime/resources/skills/` for PyPI distribution via `importlib.resources`.

### Frontmatter Convention

All skills are task skills with `disable-model-invocation: true`. Per-skill `allowed-tools`:

| Skill | allowed-tools |
|-------|---------------|
| twin-decide | Bash, Read |
| twin-reflect | Bash, Read |
| twin-status | Bash, Read |
| twin-calibrate | Bash, Read |
| twin-dashboard | Bash, Read, Write |

### twin-decide/SKILL.md

```markdown
---
name: twin-decide
description: Run your calibrated judgment twin on a decision scenario
disable-model-invocation: true
argument-hint: "<decision context>"
allowed-tools: Bash, Read
---

# Twin Decide

Help the user run a calibrated judgment twin on a decision scenario.

## Process

1. If the user hasn't provided a clear context + options, ask:
   - "What's the decision situation?"
   - "What are the options to evaluate?"

2. Format and run:
   ```bash
   twin-runtime run "<context>" -o "<option1>" "<option2>" ...
   ```

3. Present the result clearly:
   - **Recommended choice** and full ranking
   - **Key reasoning** from activated domain heads
   - **Uncertainty level** (0-1 scale)
   - **Activated domains** (work, life_planning, money, etc.)

4. If uncertainty > 0.4:
   > "Twin confidence is low here — treat this as a weak signal, not a strong recommendation."

5. Suggest: "Use `/twin-reflect` later to tell the twin what you actually chose — this helps it calibrate."
```

### twin-reflect/SKILL.md

```markdown
---
name: twin-reflect
description: Tell your twin what you actually chose — feeds the calibration loop
disable-model-invocation: true
argument-hint: "<what you chose>"
allowed-tools: Bash, Read
---

# Twin Reflect

Record what the user actually decided — this feeds the calibration flywheel.

## Process

1. Ask three things:
   - "What did you end up choosing?"
   - "Why?" (optional but valuable)
   - "Where do you think the twin was off — the choice itself, the reasoning, or the confidence level?"

2. If a recent `/twin-decide` was run, retrieve the trace_id from that output.

3. Run:
   ```bash
   twin-runtime reflect --choice "<choice>" --reasoning "<why>" \
     --trace-id "<trace_id>" --feedback-target "<choice|reasoning|confidence>"
   ```
   If no trace_id available, omit it (graceful degradation).

4. Confirm: "Got it. This will improve the twin's calibration over time."
```

### twin-status/SKILL.md

```markdown
---
name: twin-status
description: Show twin state — domains, reliability, known biases, fidelity summary
disable-model-invocation: true
allowed-tools: Bash, Read
---

# Twin Status

Show the current state of the user's judgment twin.

## Process

1. Run:
   ```bash
   twin-runtime status
   ```

2. Present in a clear summary:
   - **Twin version** and last calibrated date
   - **Available domains** with per-domain reliability scores
   - **Known biases** (if any bias corrections are active)
   - **Fidelity summary** (at minimum CF; later RF/CQ/TS)
   - **Scope declaration** — what the twin can and cannot do

3. If any domain has reliability < 0.5:
   > "This domain needs more calibration data."
```

### twin-calibrate/SKILL.md and twin-dashboard/SKILL.md

Retained in full but not featured in README first screen. `twin-calibrate` calls `twin-runtime evaluate [--with-bias-detection]`. `twin-dashboard` calls `twin-runtime dashboard --output fidelity_report.html` and asks before opening.

### Installation

**Developer path:** `git clone` → `.claude/skills/` auto-available

**PyPI path:**
```bash
pip install twin-runtime
twin-runtime install-skills           # project-level .claude/skills/
twin-runtime install-skills --personal  # ~/.claude/skills/
```

**install-skills behavior:**
- Default: does NOT overwrite existing skills. `--force` to overwrite.
- Prints target path + list of installed skills on completion.
- Reads from `importlib.resources` (`twin_runtime.resources.skills`).

## 3. MCP Server

### Architecture

New module: `src/twin_runtime/server/`

```
server/
├── __init__.py
├── transport.py    # Transport protocol + StdioTransport
└── mcp_server.py   # TwinMCPServer + tool handlers
```

### Transport Abstraction

```python
class Transport(Protocol):
    def read_message(self) -> dict: ...
    def write_message(self, msg: dict) -> None: ...

class StdioTransport:
    """v0.1: stdin/stdout JSON-RPC."""
```

> v0.1 ships with stdio MCP transport for Claude Code. SSE/HTTP transports are intentionally deferred.

### MCP Tools

**Launch gate (must be stable):**

| Tool | Input | Output |
|------|-------|--------|
| `twin_decide` | `query: str, options: list[str]` | decision + uncertainty + reasoning + domains |
| `twin_reflect` | `choice: str, reasoning?: str, trace_id?: str, feedback_target?: str` | confirmation + calibration status |
| `twin_status` | (none) | twin version + domains + reliability + biases + fidelity summary |

**Ship if ready (not blocking launch):**

| Tool | Input | Output |
|------|-------|--------|
| `twin_calibrate` | `with_bias_detection?: bool` | fidelity report (CF/RF/CQ/TS) |
| `twin_history` | `limit?: int` | recent traces list |

### Protocol Support

- `initialize` / `initialized` handshake
- `tools/list` → returns tool definitions with JSON Schema
- `tools/call` → dispatches to handler, returns result
- `notifications/tools/list_changed` → sent when tools update
- Graceful shutdown on EOF / SIGINT

### .mcp.json

```json
{
  "mcpServers": {
    "twin-runtime": {
      "command": "twin-runtime",
      "args": ["mcp-serve"]
    }
  }
}
```

Alternative installation:
```bash
claude mcp add --transport stdio twin-runtime -- twin-runtime mcp-serve
```

### CLI New Commands

**`twin-runtime mcp-serve`** — Start MCP server (stdio, blocking). Added as argparse subcommand `mcp-serve`.

**`twin-runtime reflect`** — Record an outcome for a previous decision.
```
Arguments:
  --choice CHOICE        What the user actually chose (required)
  --trace-id ID          Link to specific pipeline trace (optional)
  --reasoning TEXT       Why the user chose this (optional)
  --feedback-target TYPE Where twin was off: choice|reasoning|confidence (optional)
```
Handler `cmd_reflect(args)` flow:
1. If `--trace-id` provided: load trace from TraceStore, call `record_outcome()` from `outcome_tracker.py`
2. If no `--trace-id`: create a standalone OutcomeRecord (trace_id="manual") and save to CalibrationStore
3. Storage: uses existing `CalibrationStore.save_outcome()` (OutcomeRecord model from Phase 3)
4. Output: prints confirmation + calibration update summary (if micro-calibration generated)

**`twin-runtime install-skills`** — Copy skills to Claude Code skills directory.
```
Arguments:
  --personal    Install to ~/.claude/skills/ instead of project-level
  --force       Overwrite existing skills
```
Path resolution:
- Default (project): `Path.cwd() / ".claude" / "skills"`
- `--personal`: `Path.home() / ".claude" / "skills"`
- Creates target directories if they don't exist
- Reads skill files from `importlib.resources` (`twin_runtime.resources.skills`)
- Does NOT overwrite existing files unless `--force`
- On completion: prints target path + list of installed skill names

**`twin-runtime dashboard`** — Generate HTML fidelity dashboard.
```
Arguments:
  --output PATH    Output file (default: fidelity_report.html)
  --open           Open in browser after generating
```
NOTE: `dashboard_command()` currently exists in `interfaces/cli.py` but is NOT wired into the main argparse dispatcher in `cli.py`. Implementation must add `dashboard` as a subcommand to the argparse tree and delegate to `dashboard_command()`.

### Narrative Positioning

MCP does NOT appear in README first screen. Placed in "Integration" section:
> **Deep integration: MCP Server for Claude Code**

## 4. README + Distribution Assets

### README Structure (B+A+C)

**First screen:**
1. Problem (B): "Your AI remembers. But does it judge like you?"
2. Positioning (A): "calibration-first judgment twin" + "Memory is input. Calibrated judgment is output."
3. Evidence (C): "0.758 choice fidelity across 20 real work-domain decisions (alpha)" + dashboard screenshot

**Then:**
- Quick Start (pip install + twin-runtime init + run example)
- Best results today: work-domain. Other domains are early/experimental.
- Claude Code Integration (install-skills + claude mcp add)
- What Makes This Different (comparison table, prefaced by "Most memory systems optimize recall. twin-runtime optimizes calibrated judgment.")
- Architecture diagram (Mermaid)
- Fidelity Metrics table (CF/CQ with values, TS as "experimental | insufficient history", RF as "v0.2")
- License: Apache 2.0

### Distribution Files

| File | Status | Content |
|------|--------|---------|
| `README.md` | Create | B+A+C first screen + quickstart + integration + metrics |
| `LICENSE` | Create | Apache 2.0 full text |
| `CONTRIBUTING.md` | Create | How to test (with/without API key), PR process, calibration case contribution |
| `CHANGELOG.md` | Create | v0.2.0 release notes |
| `docs/quickstart.md` | Create | Detailed install, Claude Code setup, MCP config, common errors |
| `docs/dashboard-screenshot.png` | Create | Screenshot of fidelity_report.html |
| `pyproject.toml` | Modify | See below |

### pyproject.toml Final

```toml
[project]
name = "twin-runtime"
version = "0.2.0"
description = "Calibration-first judgment twin — memory is input, calibrated judgment is output"
readme = "README.md"
license = {text = "Apache-2.0"}
requires-python = ">=3.9"
keywords = ["agent", "memory", "decision-making", "calibration", "claude-code", "mcp"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "License :: OSI Approved :: Apache Software License",
    "Programming Language :: Python :: 3",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
]
dependencies = [
    "pydantic>=2.0",
    "anthropic>=0.20.0",
    "python-dotenv>=1.0.0",
    "requests>=2.28.0",
]

[project.optional-dependencies]
dev = ["pytest>=7.0", "pytest-cov>=4.0", "ruff>=0.1.0"]
google = ["google-api-python-client", "google-auth-oauthlib"]

[project.scripts]
twin-runtime = "twin_runtime.interfaces.cli:main"

[project.urls]
Homepage = "https://github.com/ziya/twin-runtime"
Repository = "https://github.com/ziya/twin-runtime"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
twin_runtime = ["resources/skills/**/SKILL.md"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
markers = [
    "requires_llm: tests that need ANTHROPIC_API_KEY (deselect with -m 'not requires_llm')",
]
```

## 5. GitHub Actions CI

### ci.yml — Every push/PR (no API key needed)

```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.9", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e ".[dev]"
      - run: pytest tests/ -q -m "not requires_llm"
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install ruff
      - run: ruff check src/ tests/
```

### integration.yml — Manual/weekly (needs API key secret)

```yaml
name: Integration
on:
  workflow_dispatch:
  schedule:
    - cron: "0 6 * * 1"
jobs:
  full-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -e ".[dev]"
      - run: pytest tests/ -q
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

## 6. Launch Checklist

### Preparation (Day 1-6)

```
Skills:
- [ ] 5 SKILL.md files written
- [ ] src/twin_runtime/resources/skills/ mirror created
- [ ] install-skills CLI command implemented
- [ ] install-skills packaging test (wheel + importlib.resources)

MCP Server:
- [ ] Transport protocol + StdioTransport
- [ ] TwinMCPServer with initialize/tools_list/tools_call/list_changed
- [ ] twin_decide handler (launch gate)
- [ ] twin_reflect handler (launch gate)
- [ ] twin_status handler (launch gate)
- [ ] twin_calibrate handler (ship if ready)
- [ ] twin_history handler (ship if ready)
- [ ] mcp-serve CLI command

CLI:
- [ ] reflect command
- [ ] install-skills command (--personal, --force)
- [ ] dashboard command (--output, --open)
- [ ] status command enhanced (fidelity summary)

Documentation:
- [ ] README.md (B+A+C first screen)
- [ ] LICENSE (Apache 2.0)
- [ ] CONTRIBUTING.md
- [ ] CHANGELOG.md
- [ ] docs/quickstart.md
- [ ] docs/dashboard-screenshot.png
- [ ] .mcp.json (example config at repo root)

CI/Packaging:
- [ ] .github/workflows/ci.yml
- [ ] .github/workflows/integration.yml
- [ ] pyproject.toml finalized
- [ ] pytest markers: requires_llm on all LLM-dependent tests
- [ ] ruff check passes
```

### Pre-launch Verification (Day 7)

```
- [ ] pytest -m "not requires_llm" passes (all Python versions)
- [ ] ruff check clean
- [ ] pip install twin-runtime (from test PyPI or local wheel)
- [ ] twin-runtime init (no API key) → clear error pointing to setup
- [ ] twin-runtime status → works with fixture
- [ ] twin-runtime install-skills → skills appear in .claude/skills/
- [ ] twin-runtime install-skills --personal → skills in ~/.claude/skills/
- [ ] claude mcp add twin-runtime -- twin-runtime mcp-serve → MCP works
- [ ] /twin-decide in Claude Code → end-to-end decision
- [ ] /twin-reflect → records outcome
- [ ] Batch eval: CF >= 0.7
- [ ] Dashboard generates and displays correctly
- [ ] No API key path: user gets readable errors + next steps
```

### Publish (Day 8)

```
- [ ] git tag v0.2.0
- [ ] PyPI publish (twine upload)
- [ ] GitHub Release with changelog
- [ ] 朋友圈 post (dashboard screenshot + positioning)
- [ ] 司内论坛 post (quickstart + architecture)
- [ ] 即刻/Twitter/community post
```

## 7. Explicitly NOT in v0.1

- SSE/HTTP MCP transport (README states: deferred)
- Auto-inject mode (keyword-based trigger)
- Embedding-based reasoning similarity (RF is "v0.2")
- Multi-user security hardening (path traversal, file permissions)
- Notion/Gmail adapter timeout/retry
- Skills marketplace submission (repo + README is primary distribution)
- npm/node packaging

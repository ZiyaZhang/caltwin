# Quick Start Guide

## Installation

### From PyPI

```bash
pip install twin-runtime
```

### From source (development)

```bash
git clone https://github.com/ZiyaZhang/twin-runtime.git
cd twin-runtime
pip install -e ".[dev]"
```

### Verify installation

```bash
twin-runtime --help
```

## Initial Setup

```bash
twin-runtime init
```

This creates a twin state file in the default location. The twin starts with baseline domain weights and no calibration history.

## Your First Decision

```bash
twin-runtime run "Should I prioritize the refactor or the new feature?" \
  -o "Refactor first" "New feature first" "Split the sprint"
```

The twin will return:
- A recommended choice with full ranking
- Key reasoning from activated domain heads
- An uncertainty score (0-1)
- Which domains were activated

## Record What You Chose

After making your actual decision:

```bash
twin-runtime reflect --choice "Refactor first" --reasoning "Tech debt was blocking velocity"
```

This feeds the calibration flywheel. Over time, the twin learns your decision patterns.

You can also specify how the outcome was observed:

```bash
twin-runtime reflect --choice "Refactor first" --source user_correction --confidence 0.9
```

## Automatic Reflection (Heartbeat)

The twin can infer outcomes from your local activity — git commits, file changes, calendar events, and email:

```bash
twin-runtime heartbeat
```

Low-confidence inferences are queued for your confirmation:

```bash
# See what's pending
twin-runtime confirm --list

# Accept all pending reflections
twin-runtime confirm --accept-all

# Or review one by one (interactive)
twin-runtime confirm
```

Run `heartbeat` periodically (e.g., via cron or shell hook) for passive calibration.

## Check Twin Status

```bash
twin-runtime status
```

Shows domain reliability scores, known biases, and fidelity summary.

## Claude Code Integration

### Install Skills

```bash
# Project-level (recommended for team use)
twin-runtime install-skills

# Personal (available in all projects)
twin-runtime install-skills --personal
```

After installing, use these in Claude Code:
- `/twin-decide <context>` -- get a calibrated decision recommendation
- `/twin-reflect <what you chose>` -- record outcomes
- `/twin-status` -- check twin state

### MCP Server

Add the twin as an MCP tool source for Claude Code:

```bash
claude mcp add --transport stdio twin-runtime -- twin-runtime mcp-serve
```

Or manually add to your project's `.mcp.json`:

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

## Fidelity Dashboard

Generate an HTML report of the twin's calibration quality:

```bash
twin-runtime dashboard --output fidelity_report.html --open
```

## Common Errors

### `ANTHROPIC_API_KEY not set`

The twin needs an Anthropic API key for LLM-backed reasoning:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Or create a `.env` file in your project root:

```
ANTHROPIC_API_KEY=sk-ant-...
```

### `Twin state not found`

Run `twin-runtime init` to create the initial twin state.

### `No calibration data available`

The fidelity dashboard and evaluation commands need at least one completed decision-reflect cycle. Run a decision with `twin-runtime run`, then reflect on it with `twin-runtime reflect`.

### `ModuleNotFoundError: twin_runtime`

Ensure you installed the package:

```bash
pip install twin-runtime
# or for development:
pip install -e ".[dev]"
```

### MCP server not connecting

1. Verify `twin-runtime mcp-serve` runs without errors when executed directly.
2. Check that the `twin-runtime` command is on your PATH.
3. If using a virtualenv, ensure Claude Code can access the same Python environment.

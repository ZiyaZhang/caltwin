# Changelog

## v0.1.0 (2026-03-17)

Initial open source alpha release.

> v0.1.0 is an alpha release focused on work-domain calibrated judgment.

### Calibration Pipeline

- Multi-head reasoning with domain-specific judgment patterns
- Calibrated scoring with per-domain reliability weights
- Uncertainty estimation with honest confidence reporting
- Bias detection and correction from real outcome data
- Outcome tracking and reflection loop (calibration flywheel)
- Batch fidelity evaluation: Choice Fidelity 0.758, Calibration Quality 0.807

### CLI

- `twin-runtime init` -- initialize twin state
- `twin-runtime run` -- run a decision through the calibrated twin
- `twin-runtime reflect` -- record actual outcomes for calibration
- `twin-runtime status` -- show twin state, domains, reliability, fidelity summary
- `twin-runtime evaluate` -- batch fidelity evaluation with bias detection
- `twin-runtime dashboard` -- generate HTML fidelity report
- `twin-runtime install-skills` -- install Claude Code skills (project or personal)
- `twin-runtime mcp-serve` -- start MCP server (stdio transport)

### Claude Code Skills

- `/twin-decide` -- run calibrated judgment on a decision
- `/twin-reflect` -- record what you actually chose
- `/twin-status` -- show twin state and metrics
- `/twin-calibrate` -- run fidelity evaluation
- `/twin-dashboard` -- generate and view fidelity report

### MCP Server

- stdio transport for Claude Code integration
- `twin_decide`, `twin_reflect`, `twin_status` tools
- JSON Schema tool definitions
- Graceful shutdown on EOF/SIGINT

### Fidelity Dashboard

- HTML report with Choice Fidelity, Calibration Quality, domain breakdown
- Per-domain reliability visualization
- Bias correction tracking

### Testing

- 295+ tests covering pipeline, calibration, CLI, MCP, and skills
- `requires_llm` marker for tests needing API key
- Offline test suite runs without any external dependencies

### Packaging

- PyPI distribution: `pip install twin-runtime`
- Apache 2.0 license
- Python 3.9, 3.11, 3.12 support
- GitHub Actions CI (lint, test, packaging smoke test)

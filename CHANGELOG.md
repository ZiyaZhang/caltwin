# Changelog

## Unreleased

### Phase D: Implicit Reflection + Experience Gating

- **HeartbeatReflector**: implicit outcome inference from Git commits/PRs, file changes, Calendar events, and Email
  - Trace-outcome diff for automatic pending discovery
  - High-confidence inferences auto-reflected; low-confidence queued for manual confirmation
  - Atomic write for pending queue (tmpfile + rename)
- **ExperienceUpdater**: conflict-aware gating replaces direct `exp_lib.add()`
  - Four outcomes: ADDED / CONFIRMED / SUPERSEDED / REJECTED
  - Jaccard + keyword overlap for duplicate detection; was_correct divergence for conflict detection
- **HardCaseMiner**: systematic failure pattern detection via LLM
  - Groups failures by domain, extracts PatternInsight with correction strategies
  - File-based reflect counter triggers mining every 20 reflections
- **OpenClaw Skill**: SKILL.md + heartbeat script + install check + calibration reference

### CLI

- `twin-runtime heartbeat` — run implicit reflection from local signals
- `twin-runtime confirm` — confirm/reject pending implicit reflections (`--list`, `--accept-all`)
- `twin-runtime mine-patterns` — analyze systematic failure patterns (`--min-failures`, `--lookback`)
- `twin-runtime reflect` — added `--source` and `--confidence` parameters

### Prerequisites (Phase D)

- `RuntimeDecisionTrace.option_set` — records options on all trace paths (S1/S2/refusal/error)
- `OutcomeSource` — 4 implicit variants: `implicit_git`, `implicit_file`, `implicit_calendar`, `implicit_email`
- `extract_keywords()` — promoted to `domain/utils/text.py` shared utility (3 consumers migrated)
- `ExperienceLibrary.add_pattern()` — supports PatternInsight insertion

### Code Quality & Bug Fixes

- **TransferCoefficient**: added `@model_validator` rejecting self-referential transfers (from_domain == to_domain)
- **PatternInsight.weight**: added upper bound `le=10.0` to prevent numerical overflow
- **BiasCorrectionEntry.instruction**: added typed property accessor, eliminating implicit dict contract in head_activator
- **TwinStore**: `current.json` now uses `atomic_write()` instead of `shutil.copy2()` for crash safety
- **TwinStore.rollback**: also switched to `atomic_write()` for consistency
- **CalibrationStore**: all `list_*()` methods now have `limit` parameter + corrupt file error handling
- **ExperienceLibraryStore.load**: graceful fallback on corrupt JSON (returns empty library)
- **MicroCalibration.apply_update**: returns immutable `UpdateResult` instead of mutating `update` in-place (safe retries)
- **SourceRegistry**: replaced `print()` with `logging.warning()` for production readiness
- **CalibrationStore**: added `_validate_safe_id()` to `load_candidate()` and `load_case()` for path traversal protection

### Project

- Renamed all references from `caltwin` to `twin-runtime` (skill directory, docs, URLs)
- 624+ tests (54 new for Phase D + code quality), ruff clean

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

- 570+ tests covering pipeline, calibration, CLI, MCP, and skills
- `requires_llm` marker for tests needing API key
- Offline test suite runs without any external dependencies

### Packaging

- PyPI distribution: `pip install twin-runtime`
- Apache 2.0 license
- Python 3.9, 3.11, 3.12 support
- GitHub Actions CI (lint, test, packaging smoke test)

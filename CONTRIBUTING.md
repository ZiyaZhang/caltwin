# Contributing to twin-runtime

## Getting Started

```bash
git clone https://github.com/ZiyaZhang/caltwin.git
cd twin-runtime
pip install -e ".[dev]"
```

## Running Tests

### Without an API key (fast, offline)

```bash
pytest tests/ -q -m "not requires_llm"
```

This runs the full test suite except tests that call the Anthropic API. All CI checks use this mode.

### With an API key (full integration)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
pytest tests/ -q
```

This includes LLM-dependent tests (calibration pipeline, decision quality). These run weekly in CI and on manual trigger.

### Linting

```bash
ruff check src/ tests/
```

## Pull Request Process

1. Fork the repo and create a feature branch from `main`.
2. Write tests for new functionality. Mark any test that needs an API key with `@pytest.mark.requires_llm`.
3. Ensure `pytest tests/ -q -m "not requires_llm"` passes.
4. Ensure `ruff check src/ tests/` passes.
5. Open a PR with a clear description of the change and its motivation.

## Contributing Calibration Cases

Calibration cases improve the twin's judgment accuracy. To contribute:

1. Add cases to `data/calibration_cases_raw.json` following the existing format.
2. Each case needs: a decision context, 2+ options, the ground-truth choice, and reasoning.
3. Focus on work-domain decisions (project prioritization, technical trade-offs, resource allocation).
4. Run `twin-runtime evaluate` to verify fidelity does not regress.

**Important:** Do not include personally identifiable information in calibration cases. Anonymize all names, companies, and specific details.

## Scope

v0.1.0 is an alpha focused on work-domain calibrated judgment. Contributions that improve calibration quality, test coverage, or documentation are especially welcome.

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.

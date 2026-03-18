# Phase 4 Code Quality Refactor — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 4 architectural issues + 4 critical bugs — hardcoded domain keywords, fragile JSON parsing, circular dependency, redundant store API, ConflictStyle enum mismatch, dead utility conflict detection, phantom option vulnerability, and unsafe goal_axes merge — to make the codebase correct and production-ready for v0.1.0.

**Architecture:** (1) Make domain keywords data-driven from TwinState's DomainHead; (2) Replace prompt-based JSON extraction with Anthropic tool_use structured outputs; (3) Inject pipeline runner into fidelity evaluator to break circular import; (4) Unify TwinStore's save/load API with deprecation; (5) Fix ConflictStyle enum/prompt mismatch; (6) Fix utility conflict detection for cross-domain axes; (7) Guard synthesizer against phantom/missing options; (8) Make goal_axes merge order-preserving with priority cap.

**Tech Stack:** Python 3.9+, Pydantic v2, Anthropic SDK (tool_use), pytest

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `src/twin_runtime/domain/models/twin_state.py` | Add `keywords` field to `DomainHead` |
| Modify | `src/twin_runtime/domain/ports/llm_port.py` | Add `ask_structured` method to `LLMPort` |
| Modify | `src/twin_runtime/infrastructure/llm/client.py` | Implement `ask_structured` via Anthropic tool_use |
| Modify | `src/twin_runtime/interfaces/defaults.py` | Wire `ask_structured` in `DefaultLLM` |
| Modify | `src/twin_runtime/application/pipeline/situation_interpreter.py` | Use DomainHead.keywords + tool_use schema |
| Modify | `src/twin_runtime/application/pipeline/head_activator.py` | Use tool_use schema |
| Modify | `src/twin_runtime/application/calibration/fidelity_evaluator.py` | Inject runner via callable parameter |
| Modify | `src/twin_runtime/infrastructure/backends/json_file/twin_store.py` | Unify save/load API |
| Modify | `src/twin_runtime/runtime/situation_interpreter.py` | Update backward-compat shim (remove deleted names) |
| Modify | `tests/fixtures/sample_twin_state.json` | Add keywords to DomainHead fixtures |
| Create | `tests/test_structured_llm.py` | Tests for ask_structured |
| Create | `tests/test_situation_interpreter.py` | Tests for data-driven keywords |
| Create | `tests/test_head_activator.py` | Tests for structured output in head activation |
| Create | `tests/test_fidelity_evaluator_unit.py` | Tests for injectable runner |
| Modify | `tests/test_runtime_units.py:73-88` | Update 3 `_keyword_scores` tests → `_keyword_scores_from_twin` |
| Modify | `tests/test_defaults.py` | Add `test_has_ask_structured` |
| Modify | `tests/test_store.py` | Update `.save()`/`.load()` → `.save_state()`/`.load_state()` |
| Modify | `src/twin_runtime/cli.py:56,63,144,234` | Update `.save()`/`.load()` → `.save_state()`/`.load_state()` |
| Modify | `src/twin_runtime/application/dashboard/cli.py:41` | Update `.load()` → `.load_state()` |
| Modify | `tests/test_full_cycle.py:46,131` | Update `.save()` → `.save_state()` |
| Modify | `src/twin_runtime/application/compiler/persona_compiler.py:70` | Fix ConflictStyle enum values in prompt |
| Modify | `src/twin_runtime/application/compiler/persona_compiler.py:249-253` | Order-preserving goal_axes merge |
| Modify | `src/twin_runtime/application/pipeline/conflict_arbiter.py:27-49` | Cross-domain semantic conflict detection |
| Modify | `src/twin_runtime/application/pipeline/decision_synthesizer.py:46-54` | Guard against phantom/missing options |
| Modify | `src/twin_runtime/domain/models/calibration.py` | Add `failed_case_count` field to `TwinEvaluation` |
| Create | `tests/test_compiler_conflict_style.py` | ConflictStyle prompt → enum alignment tests |
| Create | `tests/test_synthesizer_guards.py` | Phantom option and missing option tests |

---

## Chunk 1: Data-Driven Domain Keywords (OCP Fix)

### Task 1: Add `keywords` field to DomainHead

**Files:**
- Modify: `src/twin_runtime/domain/models/twin_state.py:80-89`
- Modify: `tests/fixtures/sample_twin_state.json`

- [ ] **Step 1: Add keywords field to DomainHead model**

In `src/twin_runtime/domain/models/twin_state.py`, add a `keywords` field to `DomainHead`:

```python
class DomainHead(BaseModel):
    domain: DomainEnum
    head_version: str
    goal_axes: List[str]
    default_priority_order: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(
        default_factory=list,
        description="Domain-specific keywords for rule-based routing. Supports any language."
    )
    evidence_weight_profile: EvidenceWeightProfile
    head_reliability: float = confidence_field()
    supported_task_types: List[str]
    unsupported_task_types: List[str] = Field(default_factory=list)
    last_recalibrated_at: datetime
```

- [ ] **Step 2: Update fixture JSON with keywords**

In `tests/fixtures/sample_twin_state.json`, add `keywords` arrays to each domain head. The keywords come from the current hardcoded `_DOMAIN_KEYWORDS` dict:

For "work" head:
```json
"keywords": ["project", "task", "deadline", "code", "team", "meeting", "sprint", "deploy", "review", "hire", "product", "feature", "bug", "工作", "项目", "任务", "代码", "团队", "会议"]
```

For "life_planning" head:
```json
"keywords": ["career", "move", "city", "life", "future", "direction", "quit", "start", "long-term", "purpose", "职业", "搬家", "城市", "未来", "方向", "人生"]
```

For "money" head:
```json
"keywords": ["salary", "invest", "cost", "budget", "price", "income", "equity", "薪资", "投资", "成本", "预算", "收入"]
```

For "relationships" head (if present):
```json
"keywords": ["partner", "friend", "family", "relationship", "social", "伴侣", "朋友", "家人", "关系"]
```

For "public_expression" head (if present):
```json
"keywords": ["post", "publish", "tweet", "blog", "public", "audience", "发布", "公开", "受众"]
```

- [ ] **Step 3: Run existing tests to verify no regression**

Run: `pytest tests/ -q -m "not requires_llm" --tb=short`
Expected: All existing tests pass (keywords field has a default so no breakage).

- [ ] **Step 4: Commit**

```bash
git add src/twin_runtime/domain/models/twin_state.py tests/fixtures/sample_twin_state.json
git commit -m "feat: add keywords field to DomainHead for data-driven routing"
```

### Task 2: Refactor situation_interpreter to use DomainHead.keywords

**Files:**
- Modify: `src/twin_runtime/application/pipeline/situation_interpreter.py`
- Create: `tests/test_situation_interpreter.py`

- [ ] **Step 1: Write the failing test for data-driven keyword scoring**

Create `tests/test_situation_interpreter.py`:

```python
"""Tests for data-driven keyword routing in situation_interpreter."""
import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone

from twin_runtime.domain.models.primitives import DomainEnum
from twin_runtime.domain.models.twin_state import TwinState, DomainHead
from twin_runtime.application.pipeline.situation_interpreter import _keyword_scores_from_twin


def _make_minimal_head(domain: DomainEnum, keywords: list[str], reliability: float = 0.8) -> DomainHead:
    """Create a minimal DomainHead for testing."""
    from twin_runtime.domain.models.twin_state import EvidenceWeightProfile
    return DomainHead(
        domain=domain,
        head_version="v1",
        goal_axes=["test"],
        keywords=keywords,
        evidence_weight_profile=EvidenceWeightProfile(
            self_report_weight=1.0,
            historical_behavior_weight=1.0,
            recent_behavior_weight=1.0,
            outcome_feedback_weight=1.0,
            weight_confidence=0.8,
        ),
        head_reliability=reliability,
        supported_task_types=["general"],
        last_recalibrated_at=datetime.now(timezone.utc),
    )


class TestKeywordScoresFromTwin:
    def test_scores_from_domain_head_keywords(self):
        """Keywords come from DomainHead, not hardcoded dict."""
        heads = [
            _make_minimal_head(DomainEnum.WORK, ["project", "sprint", "项目"]),
            _make_minimal_head(DomainEnum.MONEY, ["invest", "budget"]),
        ]
        scores = _keyword_scores_from_twin("I need to review the project budget", heads)
        assert DomainEnum.WORK in scores
        assert DomainEnum.MONEY in scores

    def test_empty_keywords_returns_empty(self):
        """Heads with no keywords produce no scores."""
        heads = [_make_minimal_head(DomainEnum.WORK, [])]
        scores = _keyword_scores_from_twin("anything here", heads)
        assert scores == {}

    def test_new_domain_keywords_work(self):
        """Adding a new domain's keywords requires NO code change."""
        heads = [
            _make_minimal_head(DomainEnum.WORK, ["project"]),
            _make_minimal_head(DomainEnum.RELATIONSHIPS, ["family", "friend", "家人"]),
        ]
        scores = _keyword_scores_from_twin("family project", heads)
        assert DomainEnum.WORK in scores
        assert DomainEnum.RELATIONSHIPS in scores

    def test_no_match_returns_empty(self):
        heads = [_make_minimal_head(DomainEnum.WORK, ["sprint"])]
        scores = _keyword_scores_from_twin("completely unrelated query", heads)
        assert scores == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_situation_interpreter.py -v`
Expected: FAIL — `_keyword_scores_from_twin` does not exist yet.

- [ ] **Step 3: Implement data-driven keyword scoring**

In `src/twin_runtime/application/pipeline/situation_interpreter.py`, replace the hardcoded `_DOMAIN_KEYWORDS` dict and `_keyword_scores` function:

Remove:
```python
_DOMAIN_KEYWORDS: Dict[DomainEnum, List[str]] = {
    DomainEnum.WORK: [...],
    ...
}

def _keyword_scores(query: str) -> Dict[DomainEnum, float]:
    ...
```

Add:
```python
_LEGACY_KEYWORDS: Dict[DomainEnum, List[str]] = {
    DomainEnum.WORK: ["project", "task", "deadline", "code", "team", "meeting", "sprint",
                       "deploy", "review", "hire", "product", "feature", "bug",
                       "工作", "项目", "任务", "代码", "团队", "会议"],
    DomainEnum.LIFE_PLANNING: ["career", "move", "city", "life", "future", "direction",
                                "quit", "start", "long-term", "purpose",
                                "职业", "搬家", "城市", "未来", "方向", "人生"],
    DomainEnum.MONEY: ["salary", "invest", "cost", "budget", "price", "income", "equity",
                        "薪资", "投资", "成本", "预算", "收入"],
    DomainEnum.RELATIONSHIPS: ["partner", "friend", "family", "relationship", "social",
                                "伴侣", "朋友", "家人", "关系"],
    DomainEnum.PUBLIC_EXPRESSION: ["post", "publish", "tweet", "blog", "public", "audience",
                                    "发布", "公开", "受众"],
}


def _keyword_scores_from_twin(query: str, domain_heads: list) -> Dict[DomainEnum, float]:
    """Count keyword hits per domain using DomainHead.keywords, return normalized scores.

    Falls back to _LEGACY_KEYWORDS for heads with empty keywords (pre-migration TwinState).
    """
    q = query.lower()
    hits: Dict[DomainEnum, int] = {}
    for head in domain_heads:
        keywords = head.keywords or _LEGACY_KEYWORDS.get(head.domain, [])
        if not keywords:
            continue
        hits[head.domain] = sum(1 for kw in keywords if kw in q)
    total = sum(hits.values())
    if total == 0:
        return {}
    return {d: c / total for d, c in hits.items() if c > 0}
```

Update `interpret_situation()` — change the Stage 1 call from:
```python
keyword_hints = _keyword_scores(query)
```
to:
```python
keyword_hints = _keyword_scores_from_twin(query, twin.domain_heads)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_situation_interpreter.py -v`
Expected: PASS

- [ ] **Step 5: Update backward-compat shim**

In `src/twin_runtime/runtime/situation_interpreter.py`, replace the explicit import list — `_keyword_scores` and `_DOMAIN_KEYWORDS` no longer exist:

```python
"""Backward-compat shim."""
from twin_runtime.application.pipeline.situation_interpreter import *  # noqa: F401,F403
from twin_runtime.application.pipeline.situation_interpreter import (  # noqa: F401
    _keyword_scores_from_twin,
    _llm_interpret,
    _apply_routing_policy,
    _INTERPRET_SYSTEM,
    _DOMINANCE_GAP,
    _MULTI_DOMAIN_GAP,
    _AMBIGUITY_THRESHOLD,
    _CONFIDENCE_THRESHOLD,
)
```

- [ ] **Step 6: Update existing tests in test_runtime_units.py**

The 3 tests in `TestSituationInterpreterKeywords` (lines 73-88) import deleted `_keyword_scores`. Update them to use `_keyword_scores_from_twin` with DomainHead objects:

```python
class TestSituationInterpreterKeywords:
    def test_keyword_scores(self):
        from twin_runtime.application.pipeline.situation_interpreter import _keyword_scores_from_twin
        heads = [_make_minimal_head(DomainEnum.WORK, ["project", "deploy", "deadline"])]
        scores = _keyword_scores_from_twin("I need to deploy this project before the deadline", heads)
        assert DomainEnum.WORK in scores
        assert scores[DomainEnum.WORK] > 0

    def test_keyword_scores_empty(self):
        from twin_runtime.application.pipeline.situation_interpreter import _keyword_scores_from_twin
        heads = [_make_minimal_head(DomainEnum.WORK, ["sprint"])]
        scores = _keyword_scores_from_twin("hello world", heads)
        assert scores == {}

    def test_keyword_scores_multi_domain(self):
        from twin_runtime.application.pipeline.situation_interpreter import _keyword_scores_from_twin
        heads = [
            _make_minimal_head(DomainEnum.MONEY, ["salary", "invest"]),
            _make_minimal_head(DomainEnum.LIFE_PLANNING, ["career", "growth"]),
        ]
        scores = _keyword_scores_from_twin("Should I invest my salary in career growth?", heads)
        assert len(scores) >= 2
```

Add the `_make_minimal_head` helper to `test_runtime_units.py` (same as in `test_situation_interpreter.py`).

- [ ] **Step 7: Run full test suite**

Run: `pytest tests/ -q -m "not requires_llm" --tb=short`
Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/twin_runtime/application/pipeline/situation_interpreter.py \
  src/twin_runtime/runtime/situation_interpreter.py \
  tests/test_situation_interpreter.py \
  tests/test_runtime_units.py
git commit -m "refactor: derive domain keywords from TwinState instead of hardcoded dict"
```

---

## Chunk 2: Structured Outputs via Tool Use

### Task 3: Add `ask_structured` to LLMPort

**Files:**
- Modify: `src/twin_runtime/domain/ports/llm_port.py`
- Modify: `src/twin_runtime/infrastructure/llm/client.py`
- Modify: `src/twin_runtime/interfaces/defaults.py`
- Create: `tests/test_structured_llm.py`

- [ ] **Step 1: Write the failing test for ask_structured**

Create `tests/test_structured_llm.py`:

```python
"""Tests for LLMPort.ask_structured via tool_use."""
import pytest
from unittest.mock import MagicMock, patch
from twin_runtime.interfaces.defaults import DefaultLLM


class TestAskStructured:
    def test_protocol_has_ask_structured(self):
        """DefaultLLM must expose ask_structured."""
        llm = DefaultLLM()
        assert hasattr(llm, "ask_structured")

    def test_ask_structured_returns_dict(self):
        """ask_structured returns parsed dict matching the schema."""
        schema = {
            "type": "object",
            "properties": {
                "confidence": {"type": "number"},
                "option_ranking": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["confidence", "option_ranking"],
        }
        expected = {"confidence": 0.8, "option_ranking": ["A", "B"]}

        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.type = "tool_use"
        mock_content.input = expected
        mock_response.content = [mock_content]
        mock_response.stop_reason = "tool_use"

        with patch("twin_runtime.infrastructure.llm.client.get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_get.return_value = mock_client
            llm = DefaultLLM()
            result = llm.ask_structured("system msg", "user msg", schema=schema, schema_name="test_output")
            assert result == expected

    def test_ask_structured_fallback_to_ask_json(self):
        """If tool_use call fails, falls back to ask_json text parsing.

        Uses RuntimeError (in the catch list) to avoid constructing
        anthropic SDK exceptions whose __init__ signature varies by version.
        """
        schema = {
            "type": "object",
            "properties": {"value": {"type": "number"}},
            "required": ["value"],
        }

        with patch("twin_runtime.infrastructure.llm.client.get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = RuntimeError("tool_use not supported")
            mock_get.return_value = mock_client

            with patch("twin_runtime.infrastructure.llm.client.ask_json") as mock_ask_json:
                mock_ask_json.return_value = {"value": 42}
                llm = DefaultLLM()
                result = llm.ask_structured("sys", "usr", schema=schema, schema_name="test")
                assert result == {"value": 42}
                mock_ask_json.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_structured_llm.py -v`
Expected: FAIL — `ask_structured` does not exist.

**Note:** `tests/test_defaults.py::test_implements_protocol` will also fail once the protocol is updated (Step 3) until `DefaultLLM` is wired (Step 5). This is expected — all three files are committed together in Step 7.

- [ ] **Step 3: Add ask_structured to LLMPort protocol**

In `src/twin_runtime/domain/ports/llm_port.py`:

```python
"""Port: LLM interaction."""
from __future__ import annotations
from typing import Any, Dict, Protocol, runtime_checkable


@runtime_checkable
class LLMPort(Protocol):
    """Abstract LLM client for testability."""
    def ask_json(self, system: str, user: str, max_tokens: int = 1024) -> Dict[str, Any]: ...
    def ask_text(self, system: str, user: str, max_tokens: int = 1024) -> str: ...
    def ask_structured(
        self,
        system: str,
        user: str,
        *,
        schema: Dict[str, Any],
        schema_name: str = "structured_output",
        max_tokens: int = 1024,
    ) -> Dict[str, Any]: ...
```

- [ ] **Step 4: Implement ask_structured in infrastructure client**

In `src/twin_runtime/infrastructure/llm/client.py`, add after the `ask_text` function:

```python
def ask_structured(
    system: str,
    user: str,
    *,
    schema: Dict[str, Any],
    schema_name: str = "structured_output",
    model: str | None = None,
    max_tokens: int = 2048,
) -> Dict[str, Any]:
    """Send a prompt and get structured output via Anthropic tool_use.

    Uses tool_use with tool_choice={"type": "tool", "name": schema_name}
    to force the model to return a response matching the given JSON Schema.
    Falls back to ask_json if tool_use is unavailable.
    """
    client = get_client()

    tool_def = {
        "name": schema_name,
        "description": f"Output structured data matching the {schema_name} schema.",
        "input_schema": schema,
    }

    combined_user = f"""<instructions>
{system}
</instructions>

{user}"""

    try:
        resp = client.messages.create(
            model=model or _DEFAULT_MODEL,
            max_tokens=max_tokens,
            tools=[tool_def],
            tool_choice={"type": "tool", "name": schema_name},
            messages=[{"role": "user", "content": combined_user}],
        )
        # Extract tool_use block
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use":
                return block.input
        # Shouldn't reach here with tool_choice forcing
        raise RuntimeError("No tool_use block in response despite forced tool_choice")
    except (anthropic.BadRequestError, anthropic.APIStatusError, RuntimeError) as exc:
        # Fallback: proxy/model doesn't support tool_use
        import logging
        logging.getLogger(__name__).warning("tool_use failed (%s), falling back to ask_json", exc)
        return ask_json(system, user, model=model, max_tokens=max_tokens)
```

- [ ] **Step 5: Wire ask_structured in DefaultLLM**

In `src/twin_runtime/interfaces/defaults.py`:

```python
class DefaultLLM:
    """Adapts infrastructure.llm.client functions to LLMPort protocol."""

    def ask_json(self, system: str, user: str, max_tokens: int = 1024) -> Dict[str, Any]:
        from twin_runtime.infrastructure.llm.client import ask_json
        return ask_json(system, user, max_tokens=max_tokens)

    def ask_text(self, system: str, user: str, max_tokens: int = 1024) -> str:
        from twin_runtime.infrastructure.llm.client import ask_text
        return ask_text(system, user, max_tokens=max_tokens)

    def ask_structured(
        self,
        system: str,
        user: str,
        *,
        schema: Dict[str, Any],
        schema_name: str = "structured_output",
        max_tokens: int = 1024,
    ) -> Dict[str, Any]:
        from twin_runtime.infrastructure.llm.client import ask_structured
        return ask_structured(system, user, schema=schema, schema_name=schema_name, max_tokens=max_tokens)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_structured_llm.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/twin_runtime/domain/ports/llm_port.py \
  src/twin_runtime/infrastructure/llm/client.py \
  src/twin_runtime/interfaces/defaults.py \
  tests/test_structured_llm.py
git commit -m "feat: add ask_structured to LLMPort using Anthropic tool_use"
```

### Task 4: Migrate situation_interpreter to use ask_structured

**Files:**
- Modify: `src/twin_runtime/application/pipeline/situation_interpreter.py`
- Modify: `tests/test_situation_interpreter.py`

- [ ] **Step 1: Write the failing test for structured interpretation**

Add to `tests/test_situation_interpreter.py`:

```python
class TestInterpretSituationStructured:
    """Verify interpret_situation calls ask_structured with proper schema."""

    def test_calls_ask_structured_with_schema(self, sample_twin):
        """interpret_situation should use ask_structured, not ask_json."""
        llm = MagicMock()
        llm.ask_structured.return_value = {
            "domain_activation": {"work": 0.9},
            "reversibility": "medium",
            "stakes": "high",
            "uncertainty_type": "outcome_uncertainty",
            "controllability": "medium",
            "option_structure": "choose_existing",
            "ambiguity_score": 0.3,
            "clarification_questions": [],
        }

        from twin_runtime.application.pipeline.situation_interpreter import interpret_situation
        frame = interpret_situation("Should I deploy on Friday?", sample_twin, llm=llm)

        llm.ask_structured.assert_called_once()
        call_kwargs = llm.ask_structured.call_args
        assert "schema" in call_kwargs.kwargs
        assert "schema_name" in call_kwargs.kwargs
        assert call_kwargs.kwargs["schema_name"] == "situation_analysis"
```

This test requires a `sample_twin` fixture — add to `conftest.py` if not already present, or use a `@pytest.fixture` in the test file that loads from `tests/fixtures/sample_twin_state.json`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_situation_interpreter.py::TestInterpretSituationStructured -v`
Expected: FAIL — still calls `ask_json`.

- [ ] **Step 3: Define the situation analysis schema and switch to ask_structured**

In `src/twin_runtime/application/pipeline/situation_interpreter.py`, replace the `_INTERPRET_SYSTEM` prompt and `_llm_interpret` function:

Replace:
```python
_INTERPRET_SYSTEM = """You are a situation analysis engine for a decision-twin system.
...
Only include domains from the provided list. Output ONLY valid JSON, no explanation."""


def _llm_interpret(query: str, valid_domains: List[str], llm: LLMPort) -> dict:
    user_msg = f"Valid domains: {valid_domains}\n\nQuery: {query}"
    return llm.ask_json(_INTERPRET_SYSTEM, user_msg, max_tokens=512)
```

With:
```python
_INTERPRET_SYSTEM = """You are a situation analysis engine for a decision-twin system.
Given a user query and the twin's valid domains, analyze the situation and provide:
- domain activation weights (0.0-1.0 for each relevant domain)
- situational features (reversibility, stakes, uncertainty, controllability)
- option structure and ambiguity assessment
Only include domains from the provided valid domains list."""

_SITUATION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "domain_activation": {
            "type": "object",
            "description": "Domain name to activation weight (0.0-1.0)",
            "additionalProperties": {"type": "number"},
        },
        "reversibility": {"type": "string", "enum": ["low", "medium", "high"], "description": "How reversible is this decision"},
        "stakes": {"type": "string", "enum": ["low", "medium", "high"], "description": "How high are the stakes"},
        "uncertainty_type": {
            "type": "string",
            "enum": ["missing_info", "outcome_uncertainty", "value_conflict", "mixed"],
            "description": "Primary source of uncertainty in this decision",
        },
        "controllability": {"type": "string", "enum": ["low", "medium", "high"], "description": "How much control the decision-maker has over the outcome"},
        "option_structure": {
            "type": "string",
            "enum": ["choose_existing", "generate_new", "mixed"],
            "description": "Whether options are given or need to be generated",
        },
        "ambiguity_score": {"type": "number", "minimum": 0.0, "maximum": 1.0, "description": "How ambiguous the situation is (0=clear, 1=very ambiguous)"},
        "clarification_questions": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "domain_activation", "reversibility", "stakes", "uncertainty_type",
        "controllability", "option_structure", "ambiguity_score", "clarification_questions",
    ],
}


def _llm_interpret(query: str, valid_domains: List[str], llm: LLMPort) -> dict:
    user_msg = f"Valid domains: {valid_domains}\n\nQuery: {query}"
    return llm.ask_structured(
        _INTERPRET_SYSTEM, user_msg,
        schema=_SITUATION_SCHEMA,
        schema_name="situation_analysis",
        max_tokens=512,
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_situation_interpreter.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -q -m "not requires_llm" --tb=short`
Expected: All pass. Any tests that mock `ask_json` for situation_interpreter must be updated to mock `ask_structured`.

- [ ] **Step 6: Commit**

```bash
git add src/twin_runtime/application/pipeline/situation_interpreter.py \
  tests/test_situation_interpreter.py
git commit -m "refactor: situation_interpreter uses ask_structured for schema-validated output"
```

### Task 5: Migrate head_activator to use ask_structured

**Files:**
- Modify: `src/twin_runtime/application/pipeline/head_activator.py`
- Create: `tests/test_head_activator.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_head_activator.py`:

```python
"""Tests for head_activator structured output migration."""
import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone

from twin_runtime.domain.models.primitives import DomainEnum, OrdinalTriLevel, UncertaintyType, OptionStructure
from twin_runtime.domain.models.situation import SituationFrame, SituationFeatureVector
from twin_runtime.domain.models.twin_state import TwinState, DomainHead
from twin_runtime.application.pipeline.head_activator import activate_heads


class TestHeadActivatorStructured:
    def test_calls_ask_structured_not_ask_json(self, sample_twin):
        """activate_heads should use ask_structured with a proper schema."""
        llm = MagicMock()
        llm.ask_structured.return_value = {
            "option_ranking": ["Stay", "Leave"],
            "utility_decomposition": {"growth": 0.7},
            "confidence": 0.8,
            "used_core_variables": ["risk_tolerance"],
            "used_evidence_types": [],
        }

        frame = SituationFrame(
            frame_id="test",
            domain_activation_vector={DomainEnum.WORK: 1.0},
            situation_feature_vector=SituationFeatureVector(
                reversibility=OrdinalTriLevel.MEDIUM,
                stakes=OrdinalTriLevel.HIGH,
                uncertainty_type=UncertaintyType.OUTCOME_UNCERTAINTY,
                controllability=OrdinalTriLevel.MEDIUM,
                option_structure=OptionStructure.CHOOSE_EXISTING,
            ),
            ambiguity_score=0.3,
        )

        assessments = activate_heads("Should I stay?", ["Stay", "Leave"], frame, sample_twin, llm=llm)

        assert len(assessments) >= 1
        llm.ask_structured.assert_called()
        call_kwargs = llm.ask_structured.call_args
        assert "schema" in call_kwargs.kwargs
        assert call_kwargs.kwargs["schema_name"] == "head_assessment"
```

This test needs a `sample_twin` fixture — load from fixture JSON or construct inline.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_head_activator.py -v`
Expected: FAIL — still calls `ask_json`.

- [ ] **Step 3: Define head assessment schema and switch**

In `src/twin_runtime/application/pipeline/head_activator.py`:

Add schema definition after imports:

```python
_HEAD_ASSESSMENT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "option_ranking": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Options ranked from best to worst",
        },
        "utility_decomposition": {
            "type": "object",
            "description": "Goal axis name to score (0.0-1.0)",
            "additionalProperties": {"type": "number"},
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
        },
        "used_core_variables": {
            "type": "array",
            "items": {"type": "string"},
        },
        "used_evidence_types": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["option_ranking", "utility_decomposition", "confidence",
                  "used_core_variables", "used_evidence_types"],
}
```

In `_build_head_prompt`, remove the "Output ONLY a JSON object:" block from the system prompt. Replace with a simpler instruction — the schema enforcement comes from tool_use, not the prompt:

Replace in system prompt:
```
Output ONLY a JSON object:
{{
  "option_ranking": ["best_option", "second", ...],
  ...
}}
Use the goal axes as utility decomposition keys. Output ONLY valid JSON.
```
With:
```
Use the goal axes as utility decomposition keys when scoring.
```

In `activate_heads`, change the LLM call from:
```python
raw = llm.ask_json(system, user, max_tokens=2048)
```
to:
```python
raw = llm.ask_structured(
    system, user,
    schema=_HEAD_ASSESSMENT_SCHEMA,
    schema_name="head_assessment",
    max_tokens=2048,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_head_activator.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -q -m "not requires_llm" --tb=short`
Expected: All pass.

- [ ] **Step 6: Update backward-compat shim**

In `src/twin_runtime/runtime/head_activator.py` — no changes needed (wildcard re-export).

- [ ] **Step 7: Commit**

```bash
git add src/twin_runtime/application/pipeline/head_activator.py \
  tests/test_head_activator.py
git commit -m "refactor: head_activator uses ask_structured for schema-validated output"
```

---

## Chunk 3: Circular Dependency Fix + Store API Cleanup

### Task 6: Break circular dependency in fidelity_evaluator

**Files:**
- Modify: `src/twin_runtime/application/calibration/fidelity_evaluator.py`
- Create: `tests/test_fidelity_evaluator_unit.py`

The problem: `fidelity_evaluator.py` imports `runner.run` at module level, creating a circular dependency with `pipeline`. The fix: accept a `runner` callable as a parameter.

- [ ] **Step 1: Write the failing test for injectable runner**

Create `tests/test_fidelity_evaluator_unit.py`:

```python
"""Tests for fidelity_evaluator with injected runner."""
import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone

from twin_runtime.domain.models.primitives import DomainEnum
from twin_runtime.domain.models.calibration import CalibrationCase
from twin_runtime.domain.models.runtime import RuntimeDecisionTrace, HeadAssessment
from twin_runtime.application.calibration.fidelity_evaluator import evaluate_single_case


def _make_case():
    return CalibrationCase(
        case_id="test-1",
        observed_context="Should I deploy?",
        option_set=["Deploy", "Wait"],
        actual_choice="Deploy",
        domain_label=DomainEnum.WORK,
        task_type="deployment",
    )


def _make_trace(ranking=None):
    ha = MagicMock(spec=HeadAssessment)
    ha.domain = DomainEnum.WORK
    ha.option_ranking = ranking or ["Deploy", "Wait"]
    ha.confidence = 0.8
    trace = MagicMock(spec=RuntimeDecisionTrace)
    trace.head_assessments = [ha]
    trace.output_text = "Deploy is better"
    trace.uncertainty = 0.2
    trace.trace_id = "trace-1"
    return trace


class TestEvaluateSingleCaseInjection:
    def test_uses_injected_runner(self):
        """evaluate_single_case should use the provided runner callable."""
        mock_runner = MagicMock(return_value=_make_trace())
        case = _make_case()
        twin = MagicMock()

        result = evaluate_single_case(case, twin, runner=mock_runner)

        mock_runner.assert_called_once()
        assert result.choice_score == 1.0
        assert result.rank == 1

    def test_default_runner_uses_pipeline_run(self):
        """Without explicit runner, should use pipeline.runner.run."""
        # This just verifies the import doesn't crash (no circular import)
        from twin_runtime.application.calibration.fidelity_evaluator import evaluate_single_case
        assert callable(evaluate_single_case)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fidelity_evaluator_unit.py -v`
Expected: FAIL — `evaluate_single_case` doesn't accept `runner` parameter.

- [ ] **Step 3: Refactor fidelity_evaluator to accept injectable runner**

In `src/twin_runtime/application/calibration/fidelity_evaluator.py`:

Remove the top-level lazy import block:
```python
# DELETE THIS:
try:
    from twin_runtime.application.pipeline.runner import run
except ImportError:
    run = None
```

Change `evaluate_single_case` signature:
```python
from typing import Callable

# Type alias for the runner function
PipelineRunner = Callable[..., "RuntimeDecisionTrace"]


def _get_default_runner() -> PipelineRunner:
    """Lazy import of pipeline runner to avoid circular dependency."""
    from twin_runtime.application.pipeline.runner import run
    return run


def evaluate_single_case(
    case: CalibrationCase,
    twin: TwinState,
    *,
    runner: Optional[PipelineRunner] = None,
) -> SingleCaseResult:
    """Run twin against a single calibration case."""
    if runner is None:
        runner = _get_default_runner()

    trace = runner(
        query=case.observed_context,
        option_set=case.option_set,
        twin=twin,
    )
    # ... rest unchanged
```

Also update `evaluate_fidelity` to pass `runner` through:
```python
def evaluate_fidelity(
    cases: List[CalibrationCase],
    twin: TwinState,
    *,
    strict: bool = False,
    runner: Optional[PipelineRunner] = None,
) -> TwinEvaluation:
    ...
    for case in cases:
        try:
            result = evaluate_single_case(case, twin, runner=runner)
        ...
```

Add the necessary import at the top:
```python
from twin_runtime.domain.models.runtime import RuntimeDecisionTrace
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fidelity_evaluator_unit.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -q -m "not requires_llm" --tb=short`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/twin_runtime/application/calibration/fidelity_evaluator.py \
  tests/test_fidelity_evaluator_unit.py
git commit -m "refactor: inject pipeline runner into fidelity_evaluator, remove circular import"
```

### Task 7: Unify TwinStore API surface

**Files:**
- Modify: `src/twin_runtime/infrastructure/backends/json_file/twin_store.py`
- Modify: `tests/test_store.py`
- Modify: Any callers that use `store.save()` or `store.load()`

The problem: `TwinStore` has both `save/load` (internal) and `save_state/load_state` (protocol wrapper) doing nearly the same thing. Fix: make `save_state/load_state` the primary API, keep `save/load` as deprecated aliases with `DeprecationWarning` (remove in v0.2).

- [ ] **Step 1: Find all callers of save() and load()**

Run: `grep -rn "\.save(" src/ tests/ --include="*.py" | grep -i twin`
Run: `grep -rn "\.load(" src/ tests/ --include="*.py" | grep -i twin`

Document which files call `store.save(twin)` vs `store.save_state(twin)` and `store.load(user_id)` vs `store.load_state(user_id)`.

- [ ] **Step 2: Write a test that validates the unified API**

Add to `tests/test_store.py` or update existing tests:

```python
class TestTwinStoreUnifiedAPI:
    def test_save_state_returns_version(self, tmp_path):
        store = TwinStore(tmp_path)
        twin = _make_twin()
        version = store.save_state(twin)
        assert version == twin.state_version

    def test_load_state_returns_twin(self, tmp_path):
        store = TwinStore(tmp_path)
        twin = _make_twin()
        store.save_state(twin)
        loaded = store.load_state(twin.user_id)
        assert loaded.user_id == twin.user_id

    def test_old_save_emits_deprecation(self, tmp_path):
        """Old .save() should emit DeprecationWarning."""
        store = TwinStore(tmp_path)
        twin = _make_twin()
        with pytest.warns(DeprecationWarning, match="save_state"):
            store.save(twin)

    def test_old_load_emits_deprecation(self, tmp_path):
        """Old .load() should emit DeprecationWarning."""
        store = TwinStore(tmp_path)
        twin = _make_twin()
        store.save_state(twin)
        with pytest.warns(DeprecationWarning, match="load_state"):
            store.load(twin.user_id)
```

- [ ] **Step 3: Refactor TwinStore**

In `src/twin_runtime/infrastructure/backends/json_file/twin_store.py`:

Rename `save` → `save_state` (making it return `str`), rename `load` → `load_state`. Remove the old protocol-compliant wrapper methods at the bottom.

```python
class TwinStore:
    """Persist and version TwinState objects as local JSON files."""

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _user_dir(self, user_id: str) -> Path:
        d = self.base_dir / user_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _version_path(self, user_id: str, version: str) -> Path:
        return self._user_dir(user_id) / f"{version}.json"

    def _current_path(self, user_id: str) -> Path:
        return self._user_dir(user_id) / "current.json"

    def save_state(self, state: TwinState) -> str:
        """Save a TwinState version. Also writes current.json. Returns version string."""
        version = state.state_version
        path = self._version_path(state.user_id, version)
        data = state.model_dump_json(indent=2)
        path.write_text(data, encoding="utf-8")

        current = self._current_path(state.user_id)
        shutil.copy2(path, current)
        return version

    def load_state(self, user_id: str, version: Optional[str] = None) -> TwinState:
        """Load a specific version, or current if version is None."""
        if version is None:
            path = self._current_path(user_id)
        else:
            path = self._version_path(user_id, version)

        if not path.exists():
            raise FileNotFoundError(f"TwinState not found: {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        return TwinState.model_validate(data)

    def list_versions(self, user_id: str) -> List[str]:
        """List all stored versions for a user, sorted."""
        user_dir = self._user_dir(user_id)
        versions = []
        for f in sorted(user_dir.glob("*.json")):
            if f.name != "current.json":
                versions.append(f.stem)
        return versions

    def has_current(self, user_id: str) -> bool:
        return self._current_path(user_id).exists()

    def rollback(self, user_id: str, version: str) -> TwinState:
        """Set current to a previous version. Returns the loaded state."""
        twin = self.load_state(user_id, version)
        current = self._current_path(user_id)
        src = self._version_path(user_id, version)
        shutil.copy2(src, current)
        return twin

    def delete_user(self, user_id: str) -> None:
        """Delete all data for a user."""
        user_dir = self.base_dir / user_id
        if user_dir.exists():
            shutil.rmtree(user_dir)

    # --- Deprecated aliases (remove in v0.2) ---

    def save(self, twin: TwinState) -> Path:
        """Deprecated: use save_state() instead."""
        import warnings
        warnings.warn("TwinStore.save() is deprecated, use save_state()", DeprecationWarning, stacklevel=2)
        self.save_state(twin)
        return self._version_path(twin.user_id, twin.state_version)

    def load(self, user_id: str, version: Optional[str] = None) -> TwinState:
        """Deprecated: use load_state() instead."""
        import warnings
        warnings.warn("TwinStore.load() is deprecated, use load_state()", DeprecationWarning, stacklevel=2)
        return self.load_state(user_id, version)
```

- [ ] **Step 4: Update all callers (exhaustive list)**

Replace `.save(` → `.save_state(` and `.load(` → `.load_state(` in these files:

**Source files:**
- `src/twin_runtime/cli.py` — lines 56 (`.load(user_id)`), 63 (`.save(twin)`), 144 (`.save(twin)`), 234 (`.save(updated)`)
- `src/twin_runtime/application/dashboard/cli.py` — line 41 (`.load(_USER_ID, version)`)

**Test files:**
- `tests/test_store.py` — 9 `.save()` calls (lines 12, 21, 29, 36, 42, 55, 62, 75, 85) and 5 `.load()` calls (lines 14, 24, 49, 68, 81)
- `tests/test_full_cycle.py` — lines 46, 131 (`.save(twin)`)

**Already uses protocol methods (no change needed):**
- `tests/test_backend_protocols.py` — uses `save_state`/`load_state`

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -q -m "not requires_llm" --tb=short`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/twin_runtime/infrastructure/backends/json_file/twin_store.py \
  src/twin_runtime/cli.py \
  src/twin_runtime/application/dashboard/cli.py \
  tests/test_store.py \
  tests/test_full_cycle.py
git commit -m "refactor: unify TwinStore API to match TwinStateStore protocol"
```

---

## Chunk 4: Critical Bug Fixes — Enum Mismatch + Dead Code + Phantom Options + Unsafe Merge

### Task 8: Fix ConflictStyle enum/prompt mismatch (🚨 crash bug)

**Files:**
- Modify: `src/twin_runtime/domain/models/primitives.py:46-50`
- Modify: `src/twin_runtime/application/compiler/persona_compiler.py:70`
- Create: `tests/test_compiler_conflict_style.py`

The LLM prompt tells the model to output `"collaborative"|"competitive"|"accommodating"` but `ConflictStyle` only has `avoidant|direct|delayed|adaptive`. If LLM returns "collaborative", Pydantic crash on `persona_compiler.py:223` where `core_params["conflict_style"]` is assigned directly.

**Fix strategy:** Align the enum to real conflict styles AND add a safe mapping in the compiler.

- [ ] **Step 1: Write the failing test**

Create `tests/test_compiler_conflict_style.py`:

```python
"""Tests for ConflictStyle enum/prompt alignment."""
import pytest
from twin_runtime.domain.models.primitives import ConflictStyle


class TestConflictStyleEnum:
    def test_all_prompt_values_are_valid(self):
        """Every value the LLM prompt can produce must be a valid ConflictStyle."""
        prompt_values = ["direct", "avoidant", "collaborative", "competitive", "accommodating", "delayed", "adaptive"]
        for val in prompt_values:
            # Should not raise
            ConflictStyle(val)

    def test_collaborative_maps_correctly(self):
        assert ConflictStyle("collaborative") == ConflictStyle.COLLABORATIVE

    def test_competitive_maps_correctly(self):
        assert ConflictStyle("competitive") == ConflictStyle.COMPETITIVE

    def test_accommodating_maps_correctly(self):
        assert ConflictStyle("accommodating") == ConflictStyle.ACCOMMODATING
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_compiler_conflict_style.py -v`
Expected: FAIL — "collaborative" is not a valid ConflictStyle.

- [ ] **Step 3: Expand ConflictStyle enum**

In `src/twin_runtime/domain/models/primitives.py`, expand the enum:

```python
class ConflictStyle(str, Enum):
    AVOIDANT = "avoidant"
    DIRECT = "direct"
    DELAYED = "delayed"
    ADAPTIVE = "adaptive"
    COLLABORATIVE = "collaborative"
    COMPETITIVE = "competitive"
    ACCOMMODATING = "accommodating"
```

- [ ] **Step 4: Add safe mapping in persona_compiler**

In `src/twin_runtime/application/compiler/persona_compiler.py`, replace the raw assignment at line 223:

Replace:
```python
        if core_params.get("conflict_style") is not None:
            updated.shared_decision_core.conflict_style = core_params["conflict_style"]
```

With:
```python
        if core_params.get("conflict_style") is not None:
            try:
                updated.shared_decision_core.conflict_style = ConflictStyle(core_params["conflict_style"])
            except ValueError:
                pass  # LLM returned unknown value, keep existing
```

Add import at top: `from twin_runtime.domain.models.primitives import ConflictStyle`

- [ ] **Step 5: Update prompt to match expanded enum**

In `persona_compiler.py:70`, update:

```python
    "conflict_style": "direct"|"avoidant"|"collaborative"|"competitive"|"accommodating"|"delayed"|"adaptive" or null,
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_compiler_conflict_style.py tests/ -q -m "not requires_llm" --tb=short`
Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add src/twin_runtime/domain/models/primitives.py \
  src/twin_runtime/application/compiler/persona_compiler.py \
  tests/test_compiler_conflict_style.py
git commit -m "fix: expand ConflictStyle enum to match LLM prompt values, prevent crash"
```

### Task 9: Fix dead utility conflict detection (🚨 logic defect)

**Files:**
- Modify: `src/twin_runtime/application/pipeline/conflict_arbiter.py:27-49`
- Modify: `tests/test_runtime_units.py` (existing conflict tests)

The current `_detect_utility_conflict` only fires when two heads output the **exact same axis name**. Since work uses "impact/growth" and money uses "roi/cost_savings", they never share axis names → detection is dead code.

**Fix:** Detect semantic conflict via **cross-domain assessment comparison** — if two heads rank the same options in significantly different order, that IS a utility conflict regardless of axis names.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_runtime_units.py` or a new test file:

```python
class TestUtilityConflictCrossDomain:
    def test_detects_conflict_across_different_axes(self):
        """Two heads with different axis names but opposing rankings must produce ranking_divergence."""
        a1 = _make_assessment(DomainEnum.WORK, ["A", "B", "C"], {"impact": 0.9, "growth": 0.8})
        a2 = _make_assessment(DomainEnum.MONEY, ["C", "B", "A"], {"roi": 0.9, "cost_savings": 0.8})
        from twin_runtime.application.pipeline.conflict_arbiter import _detect_utility_conflict
        axes = _detect_utility_conflict([a1, a2])
        # Must contain a ranking_divergence entry — this is the NEW detection path
        assert any("ranking_divergence" in a for a in axes), (
            f"Expected ranking_divergence conflict but got: {axes}"
        )

    def test_no_conflict_when_rankings_agree(self):
        """Same top choice = no utility conflict despite different axes."""
        a1 = _make_assessment(DomainEnum.WORK, ["A", "B"], {"impact": 0.9})
        a2 = _make_assessment(DomainEnum.MONEY, ["A", "B"], {"roi": 0.8})
        from twin_runtime.application.pipeline.conflict_arbiter import _detect_utility_conflict
        axes = _detect_utility_conflict([a1, a2])
        assert len(axes) == 0
```

- [ ] **Step 2: Implement cross-domain conflict detection**

Replace `_detect_utility_conflict` in `conflict_arbiter.py`:

```python
def _detect_utility_conflict(assessments: List[HeadAssessment]) -> List[str]:
    """Detect utility conflicts across heads.

    Two detection strategies:
    1. Same-axis disagreement: if heads share an axis name and differ by >0.3
    2. Cross-domain ranking inversion: if heads rank options in significantly
       different order, flag as "ranking_divergence" conflict
    """
    if len(assessments) < 2:
        return []

    conflict_axes = []

    # Strategy 1: same-axis score disagreement (original logic)
    all_axes = set()
    for a in assessments:
        for k, v in a.utility_decomposition.items():
            if isinstance(v, (int, float)):
                all_axes.add(k)
    for axis in all_axes:
        values = []
        for a in assessments:
            v = a.utility_decomposition.get(axis)
            if isinstance(v, (int, float)):
                values.append(float(v))
        if len(values) >= 2 and (max(values) - min(values)) > 0.3:
            conflict_axes.append(axis)

    # Strategy 2: ranking inversion detection
    # Compare pairwise ranking order — if top-N options differ significantly
    for i in range(len(assessments)):
        for j in range(i + 1, len(assessments)):
            r1 = assessments[i].option_ranking
            r2 = assessments[j].option_ranking
            if not r1 or not r2:
                continue
            # Check if top choice is ranked last (or near-last) by the other head
            if len(r1) >= 2 and len(r2) >= 2:
                top1 = r1[0]
                top2 = r2[0]
                if top1 != top2:
                    # Check how badly they disagree
                    try:
                        rank_of_top1_in_r2 = r2.index(top1) + 1
                    except ValueError:
                        rank_of_top1_in_r2 = len(r2)
                    if rank_of_top1_in_r2 > 1:
                        conflict_axes.append(
                            f"ranking_divergence({assessments[i].domain.value}↔{assessments[j].domain.value})"
                        )

    return conflict_axes
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/ -q -m "not requires_llm" --tb=short`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add src/twin_runtime/application/pipeline/conflict_arbiter.py tests/test_runtime_units.py
git commit -m "fix: detect cross-domain utility conflicts via ranking inversion"
```

### Task 10: Guard synthesizer against phantom/missing options (🔴 logic defect)

**Files:**
- Modify: `src/twin_runtime/application/pipeline/decision_synthesizer.py:46-60`
- Create: `tests/test_synthesizer_guards.py`

The synthesizer trusts LLM-returned option names blindly. If LLM hallucinates an option, it gets ranked. If LLM drops a valid option, it gets 0 score.

**Fix:** Filter scores to only include options from the original `option_set`. Pass `option_set` into `_synthesize_decision`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_synthesizer_guards.py`:

```python
"""Tests for synthesizer option guards."""
import pytest
from unittest.mock import MagicMock
from twin_runtime.domain.models.primitives import DomainEnum, DecisionMode, OrdinalTriLevel, UncertaintyType, OptionStructure, ScopeStatus
from twin_runtime.domain.models.runtime import HeadAssessment
from twin_runtime.domain.models.situation import SituationFrame, SituationFeatureVector
from twin_runtime.application.pipeline.decision_synthesizer import _synthesize_decision


def _frame():
    return SituationFrame(
        frame_id="test",
        domain_activation_vector={DomainEnum.WORK: 1.0},
        situation_feature_vector=SituationFeatureVector(
            reversibility=OrdinalTriLevel.MEDIUM,
            stakes=OrdinalTriLevel.MEDIUM,
            uncertainty_type=UncertaintyType.MIXED,
            controllability=OrdinalTriLevel.MEDIUM,
            option_structure=OptionStructure.CHOOSE_EXISTING,
        ),
        ambiguity_score=0.3,
        scope_status=ScopeStatus.IN_SCOPE,
    )


def _assessment(ranking, confidence=0.8):
    a = MagicMock(spec=HeadAssessment)
    a.domain = DomainEnum.WORK
    a.option_ranking = ranking
    a.confidence = confidence
    a.utility_decomposition = {}
    return a


class TestPhantomOptionGuard:
    def test_phantom_option_excluded(self):
        """LLM-hallucinated options must not appear in final ranking."""
        assessments = [_assessment(["Phantom", "A", "B"])]
        decision, mode, uncertainty, refusal = _synthesize_decision(
            assessments, None, _frame(), option_set=["A", "B"]
        )
        assert "Phantom" not in decision
        assert "A" in decision or "B" in decision

    def test_missing_option_gets_floor_score(self):
        """Options the LLM forgot still get a minimum score, not 0."""
        assessments = [_assessment(["A"])]  # LLM forgot "B"
        decision, mode, uncertainty, refusal = _synthesize_decision(
            assessments, None, _frame(), option_set=["A", "B"]
        )
        # B should still appear in the output (as a lower-ranked option)
        assert "A" in decision

    def test_all_options_present_no_change(self):
        """Normal case: all options present, no filtering needed."""
        assessments = [_assessment(["B", "A"])]
        decision, mode, uncertainty, refusal = _synthesize_decision(
            assessments, None, _frame(), option_set=["A", "B"]
        )
        assert "B" in decision

    def test_all_phantom_triggers_degraded(self):
        """If ALL LLM options are phantom (none match option_set), degrade."""
        assessments = [_assessment(["Ghost1", "Ghost2"])]
        decision, mode, uncertainty, refusal = _synthesize_decision(
            assessments, None, _frame(), option_set=["A", "B"]
        )
        # When no real option got a real score, mode should degrade
        assert mode == DecisionMode.DEGRADED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_synthesizer_guards.py -v`
Expected: FAIL — `_synthesize_decision` doesn't accept `option_set` parameter.

- [ ] **Step 3: Add option_set guard to _synthesize_decision**

In `src/twin_runtime/application/pipeline/decision_synthesizer.py`, update `_synthesize_decision`:

```python
def _synthesize_decision(
    assessments: List[HeadAssessment],
    conflict: Optional[ConflictReport],
    frame: SituationFrame,
    *,
    option_set: Optional[List[str]] = None,
) -> tuple[str, DecisionMode, float, Optional[str]]:
```

After computing `option_scores`, add the guard before ranking:

```python
    # Guard: filter to valid options only (prevent phantom options)
    if option_set:
        valid_options = {o.lower().strip(): o for o in option_set}
        filtered_scores: dict[str, float] = {}
        for opt, score in option_scores.items():
            normalized = opt.lower().strip()
            if normalized in valid_options:
                canonical = valid_options[normalized]
                filtered_scores[canonical] = filtered_scores.get(canonical, 0.0) + score
        # If NO real option got a real score, all LLM output was phantom → degrade
        _all_phantom = not filtered_scores
        if _all_phantom:
            for opt in option_set:
                filtered_scores[opt] = 0.01
            mode = DecisionMode.DEGRADED
        else:
            # Ensure all valid options have at least a floor score
            for opt in option_set:
                if opt not in filtered_scores:
                    filtered_scores[opt] = 0.01
        option_scores = filtered_scores
```

After the existing uncertainty calculation (line 63-66 in original), add the all-phantom boost:

```python
    if _all_phantom:
        uncertainty = min(1.0, uncertainty + 0.3)
```

Also update the `synthesize()` function to pass `option_set` through:

```python
    decision, mode, uncertainty, refusal = _synthesize_decision(
        assessments, conflict, frame, option_set=option_set
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_synthesizer_guards.py tests/ -q -m "not requires_llm" --tb=short`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/application/pipeline/decision_synthesizer.py \
  tests/test_synthesizer_guards.py
git commit -m "fix: guard synthesizer against phantom options and missing options"
```

### Task 11: Fix unsafe goal_axes merge in persona_compiler (🟡 data loss)

**Files:**
- Modify: `src/twin_runtime/application/compiler/persona_compiler.py:249-253`
- Add test to `tests/test_compiler_typed_extraction.py` or create new file

The current `set()` union + `[:8]` loses ordering. Existing axes should be preserved first, new ones appended, with the cap applied only to overflow.

- [ ] **Step 1: Write failing test**

```python
class TestGoalAxesMerge:
    def test_preserves_existing_order(self):
        """Existing axes must keep their order; new axes append at end."""
        existing = ["growth", "impact", "autonomy"]
        new = ["salary", "impact"]  # "impact" is duplicate
        result = _merge_goal_axes(existing, new, max_axes=8)
        assert result[:3] == ["growth", "impact", "autonomy"]
        assert "salary" in result
        assert len(result) == 4  # 3 existing + 1 new (impact deduplicated)

    def test_cap_drops_new_not_existing(self):
        """When capping, drop newest additions first, never existing."""
        existing = ["a", "b", "c", "d", "e", "f"]
        new = ["g", "h", "i", "j"]  # Would make 10, cap at 8
        result = _merge_goal_axes(existing, new, max_axes=8)
        assert result[:6] == existing  # All existing preserved
        assert len(result) == 8
        assert result[6:] == ["g", "h"]  # Only first 2 new ones fit

    def test_empty_new_returns_existing(self):
        existing = ["x", "y"]
        result = _merge_goal_axes(existing, [], max_axes=8)
        assert result == ["x", "y"]

    def test_existing_already_over_cap_preserved(self):
        """If existing already exceeds max_axes, keep all existing, add nothing new."""
        existing = ["a", "b", "c", "d", "e", "f", "g", "h", "i"]  # 9 items, cap=8
        result = _merge_goal_axes(existing, ["j", "k"], max_axes=8)
        assert result == existing  # All existing preserved, nothing new added
```

- [ ] **Step 2: Extract merge logic into a testable function**

In `persona_compiler.py`, add:

```python
def _merge_goal_axes(existing: List[str], new: List[str], max_axes: int = 8) -> List[str]:
    """Merge new goal axes into existing, preserving order.

    Existing axes always keep their position and are never truncated.
    New axes that aren't duplicates are appended, up to the cap.
    If existing already exceeds max_axes, no new axes are added.
    """
    seen = set(existing)
    merged = list(existing)
    # How many new slots are available?
    slots = max(0, max_axes - len(existing))
    added = 0
    for axis in new:
        if axis not in seen and added < slots:
            merged.append(axis)
            seen.add(axis)
            added += 1
    return merged
```

Update the merge site (line 249-253):

Replace:
```python
                existing_axes = set(head.goal_axes)
                new_axes = set(signals["goal_axes"])
                combined = list(existing_axes | new_axes)
                head.goal_axes = combined[:8]
```

With:
```python
                head.goal_axes = _merge_goal_axes(head.goal_axes, signals["goal_axes"])
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/ -q -m "not requires_llm" --tb=short`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add src/twin_runtime/application/compiler/persona_compiler.py \
  tests/test_compiler_typed_extraction.py
git commit -m "fix: order-preserving goal_axes merge, cap drops new axes not existing"
```

---

## Chunk 5: Fidelity Evaluator Error Isolation (P1)

### Task 12: Separate system failures from model misses in fidelity scoring

**Files:**
- Modify: `src/twin_runtime/domain/models/calibration.py` — add `failed_case_count` field to `TwinEvaluation`
- Modify: `src/twin_runtime/application/calibration/fidelity_evaluator.py:197-210`

Currently, when `evaluate_single_case` throws, the case gets `choice_score=0.0` and is counted toward CF/CQ. This pollutes the KPI — a network timeout shouldn't lower Choice Fidelity.

- [ ] **Step 1: Write failing test**

```python
class TestFidelityErrorIsolation:
    def test_failed_cases_excluded_from_cf(self):
        """System errors should not count toward CF denominator."""
        mock_runner = MagicMock(side_effect=Exception("API timeout"))
        case = _make_case()
        twin = MagicMock()

        from twin_runtime.application.calibration.fidelity_evaluator import evaluate_fidelity
        eval_ = evaluate_fidelity([case], twin, runner=mock_runner)

        # The error case should be tracked but NOT in choice_similarity
        assert eval_.choice_similarity == 0.0  # No valid cases
        assert eval_.failed_case_count == 1

    def test_mixed_success_and_failure(self):
        """CF should only count valid cases; failed cases excluded from denominator."""
        good_trace = _make_trace(["Deploy", "Wait"])
        mock_runner = MagicMock(side_effect=[good_trace, Exception("timeout")])
        cases = [_make_case(), _make_case()]
        cases[1].case_id = "test-2"
        twin = MagicMock()

        eval_ = evaluate_fidelity(cases, twin, runner=mock_runner)
        assert eval_.choice_similarity == 1.0  # Only the successful case counts
        assert eval_.failed_case_count == 1
```

- [ ] **Step 2: Add `failed_case_count` to TwinEvaluation model**

In `src/twin_runtime/domain/models/calibration.py`, add to `TwinEvaluation`:

```python
    failed_case_count: int = Field(default=0, description="Cases that failed due to system error, excluded from metrics")
```

- [ ] **Step 3: Modify evaluate_fidelity to exclude failed cases from aggregation**

In `fidelity_evaluator.py`, change the error handling in `evaluate_fidelity`:

```python
        except Exception as e:
            if strict:
                raise
            error_count += 1
            failed_case_ids.append(case.case_id)
            print(f"  ERROR on case {case.case_id}: {e}")
            continue  # Skip this case entirely — don't add 0.0 to scores
```

And pass `failed_case_count` to the `TwinEvaluation` constructor:

```python
    return TwinEvaluation(
        ...
        failed_case_count=error_count,
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/ -q -m "not requires_llm" --tb=short`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/twin_runtime/domain/models/calibration.py \
  src/twin_runtime/application/calibration/fidelity_evaluator.py \
  tests/test_fidelity_evaluator_unit.py
git commit -m "fix: exclude system errors from fidelity metrics, track failed_case_count"
```

---

## Final Verification

- [ ] **Run full test suite**: `pytest tests/ -q -m "not requires_llm" --tb=short`
- [ ] **Run ruff lint**: `ruff check src/ tests/`
- [ ] **Verify no circular imports**: `python -c "from twin_runtime.application.calibration.fidelity_evaluator import evaluate_fidelity; print('OK')"`
- [ ] **Verify structured output wiring**: `python -c "from twin_runtime.interfaces.defaults import DefaultLLM; llm = DefaultLLM(); assert hasattr(llm, 'ask_structured'); print('OK')"`
- [ ] **Verify ConflictStyle enum coverage**: `python -c "from twin_runtime.domain.models.primitives import ConflictStyle; [ConflictStyle(v) for v in ['collaborative','competitive','accommodating']]; print('OK')"`
- [ ] **Verify deprecation warnings**: `pytest tests/test_store.py::TestTwinStoreUnifiedAPI::test_old_save_emits_deprecation tests/test_store.py::TestTwinStoreUnifiedAPI::test_old_load_emits_deprecation -v`

---

## Architectural Notes

**Dual-directory rule (post Phase 4):** New capabilities go ONLY into `application/`. The `runtime/` directory is frozen — it contains only backward-compat shims. No new re-exports. Future phases should plan to remove `runtime/` entirely.

**Legacy keyword fallback:** `_LEGACY_KEYWORDS` in `situation_interpreter.py` exists for pre-migration TwinState compatibility. Remove after v0.2 when all states have been recompiled with `keywords` populated.

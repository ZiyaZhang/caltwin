"""Golden trace regression tests — control plane behavior verification.

Tests the orchestrator end-to-end using scripted LLM responses.
Only asserts stable, product-relevant control plane fields.
Does NOT assert trace_id, created_at, output_text, or full plan.
"""
import json
import pytest
from pathlib import Path

GOLDEN_DIR = Path("tests/fixtures/golden_traces")


def _load_golden_cases():
    cases = []
    for f in sorted(GOLDEN_DIR.glob("*.json")):
        case = json.loads(f.read_text())
        cases.append(pytest.param(case, id=case["name"]))
    return cases


class ScriptedLLM:
    """Mock LLM with key-based dispatch for golden traces.

    Dispatch contract:
    - ask_structured(schema_name="situation_analysis") → script["interpret"]
    - ask_structured(schema_name="head_assessment") → script["round_N"]["head_assess_DOMAIN"]
      Falls back to top-level script["head_assess_DOMAIN"] if no round key.
    - ask_text → script["synthesize"]

    Auto-advances round when all head_assess keys for current round are consumed.
    """

    def __init__(self, script: dict):
        self._script = script
        self._current_round = 0
        self._heads_served_this_round = set()

    def ask_structured(self, system, user, *, schema, schema_name="", max_tokens=1024):
        if schema_name == "situation_analysis":
            return self._script["interpret"]
        if schema_name == "head_assessment":
            domain = self._extract_domain(system)
            round_key = f"round_{self._current_round}"
            head_key = f"head_assess_{domain}"
            # Try round-specific first, then top-level fallback
            if round_key in self._script and head_key in self._script[round_key]:
                result = self._script[round_key][head_key]
            elif head_key in self._script:
                result = self._script[head_key]
            else:
                # Generic fallback for unexpected domain calls
                result = {
                    "option_ranking": ["A", "B"],
                    "utility_decomposition": {"default": 0.5},
                    "confidence": 0.3,
                    "used_core_variables": [],
                    "used_evidence_types": [],
                }
            self._heads_served_this_round.add(domain)
            self._maybe_advance_round()
            return result
        return {}

    def ask_text(self, system, user, max_tokens=1024):
        return self._script.get("synthesize", "Mock decision.")

    def ask_json(self, system, user, max_tokens=1024):
        return {}

    def _maybe_advance_round(self):
        """Auto-advance round when all head_assess keys for current round are consumed."""
        round_key = f"round_{self._current_round}"
        if round_key not in self._script:
            return
        expected_heads = {k for k in self._script[round_key] if k.startswith("head_assess_")}
        if expected_heads and self._heads_served_this_round >= expected_heads:
            self._current_round += 1
            self._heads_served_this_round.clear()

    @staticmethod
    def _extract_domain(system_prompt: str) -> str:
        """Extract domain name from system prompt for head assessment dispatch."""
        for domain in ["work", "money", "life_planning", "relationships", "public_expression"]:
            if domain in system_prompt.lower():
                return domain
        return "unknown"


@pytest.mark.parametrize("case", _load_golden_cases())
def test_golden_trace(case, tmp_path):
    from twin_runtime.domain.models.twin_state import TwinState
    from twin_runtime.application.orchestrator.runtime_orchestrator import run
    from twin_runtime.application.orchestrator.models import ExecutionPath

    twin = TwinState(**json.loads(Path(case["twin_fixture"]).read_text()))

    # Load evidence fixture if provided
    evidence_store = None
    if case.get("evidence_fixture"):
        from twin_runtime.infrastructure.backends.json_file.evidence_store import JsonFileEvidenceStore
        from twin_runtime.domain.evidence.base import EvidenceFragment
        evidence_store = JsonFileEvidenceStore(tmp_path / "evidence")
        for frag_data in json.loads(Path(case["evidence_fixture"]).read_text()):
            frag = EvidenceFragment.model_validate(frag_data)
            evidence_store.store_fragment(frag)

    llm = ScriptedLLM(case["llm_script"])

    force_path = None
    if case.get("force_path"):
        force_path = ExecutionPath(case["force_path"])

    trace = run(
        query=case["query"],
        option_set=case["option_set"],
        twin=twin,
        llm=llm,
        evidence_store=evidence_store,
        force_path=force_path,
    )

    expected = case["expected"]

    # Control plane assertions
    if "decision_mode" in expected:
        assert trace.decision_mode.value == expected["decision_mode"], \
            f"Expected decision_mode={expected['decision_mode']}, got {trace.decision_mode.value}"
    if "refusal_reason_code" in expected:
        assert trace.refusal_reason_code == expected["refusal_reason_code"], \
            f"Expected refusal_reason_code={expected['refusal_reason_code']}, got {trace.refusal_reason_code}"
    if "route_path" in expected:
        assert trace.route_path == expected["route_path"], \
            f"Expected route_path={expected['route_path']}, got {trace.route_path}"
    if "boundary_policy" in expected:
        assert trace.boundary_policy == expected["boundary_policy"], \
            f"Expected boundary_policy={expected['boundary_policy']}, got {trace.boundary_policy}"
    if "deliberation_rounds" in expected:
        assert trace.deliberation_rounds == expected["deliberation_rounds"], \
            f"Expected deliberation_rounds={expected['deliberation_rounds']}, got {trace.deliberation_rounds}"
    if "terminated_by" in expected:
        assert trace.terminated_by == expected["terminated_by"], \
            f"Expected terminated_by={expected['terminated_by']}, got {trace.terminated_by}"
    if "activated_domains_contains" in expected:
        actual_domains = [d.value for d in trace.activated_domains]
        for d in expected["activated_domains_contains"]:
            assert d in actual_domains, f"Expected domain {d} in {actual_domains}"
    if "situation_frame.scope_status" in expected:
        assert trace.situation_frame["scope_status"] == expected["situation_frame.scope_status"]
    if "expected_top_choice" in expected and expected["expected_top_choice"]:
        if "Recommended: " in trace.final_decision:
            actual_top = trace.final_decision.split("Recommended: ")[1].split(" (over")[0].strip()
            assert actual_top == expected["expected_top_choice"], \
                f"Expected top_choice={expected['expected_top_choice']}, got {actual_top}"

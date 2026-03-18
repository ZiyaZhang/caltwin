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
        """Auto-advance round when all head_assess domains for current round are consumed."""
        round_key = f"round_{self._current_round}"
        if round_key not in self._script:
            return
        # Extract domain names from keys like "head_assess_work" → "work"
        expected_domains = {
            k.replace("head_assess_", "")
            for k in self._script[round_key]
            if k.startswith("head_assess_")
        }
        if expected_domains and self._heads_served_this_round >= expected_domains:
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


# ---------------------------------------------------------------------------
# Aggregate S1/S2 baseline comparison gate
# ---------------------------------------------------------------------------

def _extract_top_choice(trace) -> str:
    """Extract top choice from trace.final_decision."""
    if "Recommended: " in trace.final_decision:
        return trace.final_decision.split("Recommended: ")[1].split(" (over")[0].strip()
    return ""


def _find_baseline_pairs():
    """Find golden cases that have a matching _s1_baseline counterpart."""
    cases = {c["name"]: c for f in sorted(GOLDEN_DIR.glob("*.json"))
             for c in [json.loads(f.read_text())]}
    pairs = []
    for name, case in cases.items():
        baseline_name = f"{name}_s1_baseline"
        if baseline_name in cases:
            pairs.append((case, cases[baseline_name]))
    return pairs


class TestS2VsS1BaselineGate:
    """Spec gate: S2 accuracy >= S1 accuracy on overlapping case set."""

    def test_s2_at_least_as_good_as_s1(self, tmp_path):
        """For each S2 case with an S1 baseline, S2 top_choice must match
        expected at least as often as S1 does."""
        from twin_runtime.domain.models.twin_state import TwinState
        from twin_runtime.application.orchestrator.runtime_orchestrator import run
        from twin_runtime.application.orchestrator.models import ExecutionPath

        pairs = _find_baseline_pairs()
        if not pairs:
            pytest.skip("No S2/S1 baseline pairs found")

        s2_hits = 0
        s1_hits = 0

        for s2_case, s1_case in pairs:
            twin = TwinState(**json.loads(Path(s2_case["twin_fixture"]).read_text()))

            # Run S2 (natural routing)
            s2_llm = ScriptedLLM(s2_case["llm_script"])
            s2_trace = run(query=s2_case["query"], option_set=s2_case["option_set"],
                           twin=twin, llm=s2_llm)
            s2_top = _extract_top_choice(s2_trace)
            s2_expected = s2_case["expected"].get("expected_top_choice")

            # Run S1 baseline (forced path)
            s1_llm = ScriptedLLM(s1_case["llm_script"])
            s1_trace = run(query=s1_case["query"], option_set=s1_case["option_set"],
                           twin=twin, llm=s1_llm,
                           force_path=ExecutionPath.S1_DIRECT)
            s1_top = _extract_top_choice(s1_trace)
            s1_expected = s1_case["expected"].get("expected_top_choice")

            if s2_expected and s2_top == s2_expected:
                s2_hits += 1
            if s1_expected and s1_top == s1_expected:
                s1_hits += 1

        assert s2_hits >= s1_hits, \
            f"S2 accuracy ({s2_hits}) must be >= S1 accuracy ({s1_hits})"


# ---------------------------------------------------------------------------
# S2 micro_calibrate regression
# ---------------------------------------------------------------------------

class TestS2MicroCalibrate:
    """Verify deliberation path produces pending_calibration_update when micro_calibrate=True."""

    def test_s2_micro_calibrate_produces_update(self):
        from twin_runtime.domain.models.twin_state import TwinState
        from twin_runtime.application.orchestrator.runtime_orchestrator import run

        twin = TwinState(**json.loads(
            Path("tests/fixtures/sample_twin_state.json").read_text()
        ))

        # Use the S2 high-stakes case script
        s2_case = json.loads(
            (GOLDEN_DIR / "s2_deliberate_high_stakes.json").read_text()
        )
        llm = ScriptedLLM(s2_case["llm_script"])

        trace = run(
            query=s2_case["query"],
            option_set=s2_case["option_set"],
            twin=twin,
            llm=llm,
            micro_calibrate=True,
        )

        # S2 path with micro_calibrate=True must produce pending_calibration_update
        assert trace.route_path == "s2_deliberate"
        assert trace.pending_calibration_update is not None, \
            "S2 path with micro_calibrate=True must produce pending_calibration_update"


# ---------------------------------------------------------------------------
# Output consistency tests for post-policy mode changes
# ---------------------------------------------------------------------------

class TestDegradedOutputConsistency:
    """FORCE_DEGRADE must sync final_decision AND output_text with degraded mode."""

    def test_degraded_final_decision_has_caveat(self):
        """final_decision must include degraded caveat when FORCE_DEGRADE applied."""
        from twin_runtime.domain.models.twin_state import TwinState
        from twin_runtime.application.orchestrator.runtime_orchestrator import run

        twin = TwinState(**json.loads(
            Path("tests/fixtures/sample_twin_state.json").read_text()
        ))
        # Use the low_reliability case which triggers BORDERLINE → FORCE_DEGRADE
        case = json.loads(
            (GOLDEN_DIR / "degrade_non_modeled_partial.json").read_text()
        )
        llm = ScriptedLLM(case["llm_script"])
        trace = run(query=case["query"], option_set=case["option_set"], twin=twin, llm=llm)

        assert trace.decision_mode.value == "degraded"
        assert "[Degraded confidence]" in trace.final_decision, \
            "final_decision must include degraded caveat"
        assert trace.output_text is not None
        assert "[Degraded confidence]" in trace.output_text, \
            "output_text must include degraded caveat"

    def test_non_modeled_partial_has_specific_reason(self):
        """non_modeled_partial route should produce NON_MODELED_PARTIAL reason code."""
        from twin_runtime.domain.models.twin_state import TwinState
        from twin_runtime.application.orchestrator.runtime_orchestrator import run
        from twin_runtime.application.pipeline.scope_guard import ScopeGuardResult
        from unittest.mock import patch

        twin = TwinState(**json.loads(
            Path("tests/fixtures/sample_twin_state.json").read_text()
        ))
        case = json.loads(
            (GOLDEN_DIR / "s1_direct_simple.json").read_text()
        )
        llm = ScriptedLLM(case["llm_script"])

        # Patch scope guard to return non_modeled_hit with activation present
        mock_guard = ScopeGuardResult(non_modeled_hit=True, matched_terms=["non_modeled:x=y"])
        with patch("twin_runtime.application.orchestrator.runtime_orchestrator.interpret_situation") as mock_interp:
            from twin_runtime.domain.models.situation import SituationFrame, SituationFeatureVector
            from twin_runtime.domain.models.primitives import (
                DomainEnum, ScopeStatus, OrdinalTriLevel, UncertaintyType, OptionStructure,
            )
            frame = SituationFrame(
                frame_id="test",
                domain_activation_vector={DomainEnum.WORK: 0.9},
                situation_feature_vector=SituationFeatureVector(
                    reversibility=OrdinalTriLevel.MEDIUM, stakes=OrdinalTriLevel.MEDIUM,
                    uncertainty_type=UncertaintyType.MIXED, controllability=OrdinalTriLevel.MEDIUM,
                    option_structure=OptionStructure.CHOOSE_EXISTING,
                ),
                ambiguity_score=0.3, scope_status=ScopeStatus.IN_SCOPE, routing_confidence=0.8,
            )
            mock_interp.return_value = (frame, mock_guard)
            trace = run(query=case["query"], option_set=case["option_set"], twin=twin, llm=llm)

        assert trace.decision_mode.value == "degraded"
        assert trace.refusal_reason_code == "NON_MODELED_PARTIAL"
        assert trace.refusal_or_degrade_reason == "non_modeled_partial"


class TestInsufficientEvidenceOutputConsistency:
    """INSUFFICIENT_EVIDENCE must have uncertainty=1.0 and honest output_text."""

    def test_insufficient_evidence_uncertainty_is_max(self):
        case = json.loads(
            (GOLDEN_DIR / "refuse_insufficient_evidence.json").read_text()
        )
        from twin_runtime.domain.models.twin_state import TwinState
        from twin_runtime.application.orchestrator.runtime_orchestrator import run

        twin = TwinState(**json.loads(Path(case["twin_fixture"]).read_text()))
        llm = ScriptedLLM(case["llm_script"])
        trace = run(query=case["query"], option_set=case["option_set"], twin=twin, llm=llm)

        assert trace.decision_mode.value == "refused"
        assert trace.refusal_reason_code == "INSUFFICIENT_EVIDENCE"
        assert trace.uncertainty == 1.0, \
            f"INSUFFICIENT_EVIDENCE must have uncertainty=1.0, got {trace.uncertainty}"
        assert "enough evidence" in trace.output_text.lower(), \
            "output_text must explain insufficient evidence"

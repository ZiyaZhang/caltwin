"""Bootstrap Engine: convert bootstrap answers into initial TwinState + ExperienceLibrary.

Step 3 of Phase B bootstrap plan.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from pydantic import BaseModel, Field

from twin_runtime.application.bootstrap.questions import (
    BootstrapAnswer,
    BootstrapQuestion,
    DEFAULT_QUESTIONS,
    QuestionType,
)
from twin_runtime.domain.models.experience import ExperienceEntry, ExperienceLibrary
from twin_runtime.domain.models.primitives import (
    ConflictStyle,
    ControlOrientation,
    DomainEnum,
    MergeStrategy,
    ReliabilityScopeStatus,
)
from twin_runtime.domain.models.twin_state import (
    CausalBeliefModel,
    DomainHead,
    EvidenceWeightProfile,
    ReliabilityProfileEntry,
    RejectionPolicyMap,
    ScopeDeclaration,
    SharedDecisionCore,
    TemporalMetadata,
    TwinState,
)
from twin_runtime.domain.ports.llm_port import LLMPort


# ---------------------------------------------------------------------------
# Domain mapping: Phase 2 question domain strings → DomainEnum
# ---------------------------------------------------------------------------

_DEFAULT_DOMAIN_MAP: Dict[str, DomainEnum] = {
    "work": DomainEnum.WORK,
    "finance": DomainEnum.MONEY,
    "health": DomainEnum.LIFE_PLANNING,
    "relationships": DomainEnum.RELATIONSHIPS,
    "learning": DomainEnum.PUBLIC_EXPRESSION,
}


_SUPPORTED_QUESTION_TYPES = {QuestionType.FORCED_CHOICE, QuestionType.OPEN_SCENARIO}


def validate_bootstrap_questions(questions: List[BootstrapQuestion]) -> None:
    """Validate a question set before starting bootstrap.

    Checks:
    1. All question types are supported (no SLIDER etc.)
    2. All domain strings map to valid DomainEnum values or known aliases
    3. No duplicate question IDs
    4. FORCED_CHOICE questions must have options
    5. Axes push counts must match options count
    6. Phase 1 FORCED_CHOICE must have axes

    Raises ValueError with a clear message on first failure.
    Call this at the CLI entry point (before interactive session) and
    again at engine init (defense-in-depth).
    """
    seen_ids: set = set()
    for q in questions:
        # Duplicate ID check
        if q.id in seen_ids:
            raise ValueError(f"Duplicate question ID '{q.id}'")
        seen_ids.add(q.id)

        # Unsupported type
        if q.type not in _SUPPORTED_QUESTION_TYPES:
            raise ValueError(
                f"Question '{q.id}' uses unsupported type '{q.type.value}'. "
                f"Supported: {[t.value for t in _SUPPORTED_QUESTION_TYPES]}"
            )

        # Invalid domain
        if q.domain and q.domain not in _DEFAULT_DOMAIN_MAP:
            try:
                DomainEnum(q.domain)
            except ValueError:
                raise ValueError(
                    f"Question '{q.id}' uses domain '{q.domain}' which is not a valid "
                    f"DomainEnum value. Valid: {[d.value for d in DomainEnum]}. "
                    f"Aliases: {list(_DEFAULT_DOMAIN_MAP.keys())}"
                )

        # FORCED_CHOICE structural checks
        if q.type == QuestionType.FORCED_CHOICE:
            if not q.options:
                raise ValueError(
                    f"Question '{q.id}' is FORCED_CHOICE but has no options"
                )
            for axis_name, pushes in q.axes.items():
                if len(pushes) != len(q.options):
                    raise ValueError(
                        f"Question '{q.id}' axis '{axis_name}' has {len(pushes)} pushes "
                        f"but {len(q.options)} options — must match"
                    )
            if q.phase == 1 and not q.axes:
                raise ValueError(
                    f"Question '{q.id}' is Phase 1 FORCED_CHOICE but has no axes mapping"
                )


def _build_domain_map(questions: List[BootstrapQuestion]) -> Dict[str, DomainEnum]:
    """Build domain mapping from question set.

    Uses _DEFAULT_DOMAIN_MAP for known domains, and attempts DomainEnum(value)
    for custom domain strings. Raises ValueError for unrecognized domains
    so custom question sets fail loud instead of silently producing empty twins.
    """
    result = dict(_DEFAULT_DOMAIN_MAP)
    for q in questions:
        if q.domain and q.domain not in result:
            try:
                result[q.domain] = DomainEnum(q.domain)
            except ValueError:
                raise ValueError(
                    f"Custom question '{q.id}' uses domain '{q.domain}' which is not a valid "
                    f"DomainEnum value. Valid domains: {[d.value for d in DomainEnum]}. "
                    f"Known aliases: {list(_DEFAULT_DOMAIN_MAP.keys())}"
                )
    return result


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class BootstrapResult(BaseModel):
    """Output of the bootstrap engine."""

    twin: TwinState
    experience_library: ExperienceLibrary
    axis_reliability: Dict[str, float]


# ---------------------------------------------------------------------------
# LLM prompt templates
# ---------------------------------------------------------------------------

_PRINCIPLES_SYSTEM = """You are a decision-style analyst. Given a user's forced-choice answers and computed axis values, synthesize 3-5 reusable decision principles that capture this person's decision-making tendencies.

Output JSON:
{
  "principles": [
    {
      "insight": "string — the principle",
      "scenario_type": ["tag1", "tag2"],
      "applicable_when": "string — when this principle applies"
    }
  ]
}"""

_NARRATIVE_SYSTEM = """You are a decision-style analyst. Given a person's narrative about a past decision, extract the key insight, scenario type tags, and when this insight applies.

Output JSON:
{
  "entries": [
    {
      "insight": "string — the key takeaway",
      "scenario_type": ["tag1", "tag2"],
      "applicable_when": "string — when this insight applies"
    }
  ]
}"""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class BootstrapEngine:
    """Convert bootstrap answers into an initial TwinState + ExperienceLibrary."""

    def __init__(
        self,
        llm: LLMPort,
        questions: Optional[List[BootstrapQuestion]] = None,
    ) -> None:
        self._llm = llm
        self._questions = questions if questions is not None else DEFAULT_QUESTIONS
        validate_bootstrap_questions(self._questions)
        self._question_map: Dict[str, BootstrapQuestion] = {
            q.id: q for q in self._questions
        }
        self._domain_map = _build_domain_map(self._questions)

    # -- public API ---------------------------------------------------------

    def run(self, answers: List[BootstrapAnswer], user_id: str) -> BootstrapResult:
        """Execute the full bootstrap pipeline."""
        # Validate: reject unsupported answer types early
        for ans in answers:
            if ans.type == QuestionType.SLIDER:
                raise ValueError(
                    f"SLIDER questions are not yet supported by BootstrapEngine "
                    f"(question_id={ans.question_id}). Use FORCED_CHOICE or OPEN_SCENARIO."
                )

        # 1. Extract axes from Phase 1 forced-choice
        raw_axes = self._extract_axes(answers)
        axis_values = self._compute_axis_values(raw_axes)
        axis_reliability = self._check_consistency(raw_axes)
        contradicted_axes: Set[str] = {
            k for k, v in axis_reliability.items() if v < 0.4
        }

        # 2. Build core
        conflict_style = self._infer_conflict_style(raw_axes)
        core = self._build_shared_decision_core(axis_values, axis_reliability)
        core.conflict_style = conflict_style

        # 3. Build domain heads
        heads = self._build_domain_heads(answers, contradicted_axes)

        # 4. Build experiences
        exp_lib = self._build_initial_experiences(answers, axis_values)

        # 5. Build TwinState
        twin = self._build_twin_state(core, heads, user_id)

        return BootstrapResult(
            twin=twin,
            experience_library=exp_lib,
            axis_reliability=axis_reliability,
        )

    # -- axis extraction (Phase 1) -----------------------------------------

    def _extract_axes(
        self, answers: List[BootstrapAnswer]
    ) -> Dict[str, List[float]]:
        """For each FORCED_CHOICE answer, look up the question's axes mapping
        and apply the push for the chosen_option index.

        Returns a dict mapping axis name → list of raw push values.
        """
        raw: Dict[str, List[float]] = {}
        for ans in answers:
            if ans.type != QuestionType.FORCED_CHOICE:
                continue
            question = self._question_map.get(ans.question_id)
            if question is None or ans.chosen_option is None:
                continue
            for axis_name, pushes in question.axes.items():
                idx = ans.chosen_option
                if 0 <= idx < len(pushes):
                    raw.setdefault(axis_name, []).append(pushes[idx])
        return raw

    def _compute_axis_values(
        self, raw_axes: Dict[str, List[float]]
    ) -> Dict[str, float]:
        """For each axis, value = 0.5 + mean(pushes), clamped [0.0, 1.0]."""
        result: Dict[str, float] = {}
        for axis, pushes in raw_axes.items():
            if not pushes:
                result[axis] = 0.5
                continue
            mean_push = sum(pushes) / len(pushes)
            result[axis] = max(0.0, min(1.0, 0.5 + mean_push))
        return result

    def _check_consistency(
        self, raw_axes: Dict[str, List[float]]
    ) -> Dict[str, float]:
        """For each axis with 2+ pushes, if signs are mixed → 0.3, else → 0.5.
        Axes with fewer than 2 pushes get 0.5 (no contradiction possible).
        """
        result: Dict[str, float] = {}
        for axis, pushes in raw_axes.items():
            if len(pushes) < 2:
                result[axis] = 0.5
                continue
            has_positive = any(p > 0 for p in pushes)
            has_negative = any(p < 0 for p in pushes)
            if has_positive and has_negative:
                result[axis] = 0.3
            else:
                result[axis] = 0.5
        return result

    # -- conflict style inference -------------------------------------------

    def _infer_conflict_style(
        self, raw_axes: Dict[str, List[float]]
    ) -> ConflictStyle:
        """Look at conflict_style_proxy axis pushes.
        Strongly positive → DIRECT, strongly negative → AVOIDANT,
        mixed → ADAPTIVE. Default ADAPTIVE.
        """
        pushes = raw_axes.get("conflict_style_proxy", [])
        if not pushes:
            return ConflictStyle.ADAPTIVE

        mean_push = sum(pushes) / len(pushes)
        if mean_push > 0.2:
            return ConflictStyle.DIRECT
        elif mean_push < -0.2:
            return ConflictStyle.AVOIDANT
        else:
            return ConflictStyle.ADAPTIVE

    # -- core construction --------------------------------------------------

    def _build_shared_decision_core(
        self,
        axis_values: Dict[str, float],
        axis_reliability: Dict[str, float],
    ) -> SharedDecisionCore:
        """Map axis_values to SharedDecisionCore fields.

        risk_tolerance, action_threshold, information_threshold,
        explore_exploit_balance map directly.
        core_confidence = mean of axis_reliability values.
        """
        now = datetime.now(timezone.utc)
        reliability_vals = list(axis_reliability.values()) if axis_reliability else [0.3]
        core_confidence = sum(reliability_vals) / len(reliability_vals)

        return SharedDecisionCore(
            risk_tolerance=axis_values.get("risk_tolerance", 0.5),
            ambiguity_tolerance=0.5,
            action_threshold=axis_values.get("action_threshold", 0.5),
            information_threshold=axis_values.get("information_threshold", 0.5),
            reversibility_preference=0.5,
            regret_sensitivity=0.5,
            explore_exploit_balance=axis_values.get(
                "explore_exploit_balance", 0.5
            ),
            conflict_style=ConflictStyle.ADAPTIVE,  # overwritten by caller
            decision_latency_hours_p50=None,
            social_proof_dependence=None,
            evidence_count=0,
            core_confidence=round(core_confidence, 3),
            last_recalibrated_at=now,
        )

    # -- domain heads (Phase 2) --------------------------------------------

    def _build_domain_heads(
        self,
        answers: List[BootstrapAnswer],
        contradicted_axes: Set[str],
    ) -> List[DomainHead]:
        """Build domain heads from Phase 2 answers.

        Declared domains with high confidence → head_reliability=0.4,
        medium → 0.35, low/undeclared → 0.3.
        If any of the domain's related axes is contradicted, downgrade to 0.3.
        """
        now = datetime.now(timezone.utc)

        # Collect Phase 2 answers by domain
        domain_confidence: Dict[str, int] = {}
        for ans in answers:
            if ans.domain is not None and ans.chosen_option is not None:
                domain_confidence[ans.domain] = ans.chosen_option

        # Axes that map to domains (for contradiction check)
        _domain_axis_map: Dict[DomainEnum, List[str]] = {
            DomainEnum.WORK: ["action_threshold", "risk_tolerance"],
            DomainEnum.MONEY: ["risk_tolerance", "information_threshold"],
            DomainEnum.LIFE_PLANNING: ["explore_exploit_balance", "risk_tolerance"],
            DomainEnum.RELATIONSHIPS: ["conflict_style_proxy"],
            DomainEnum.PUBLIC_EXPRESSION: ["explore_exploit_balance"],
        }

        all_domains = list(DomainEnum)
        heads: List[DomainHead] = []

        for domain in all_domains:
            # Determine domain string key for Phase 2 answer lookup
            domain_key: Optional[str] = None
            for key, mapped in self._domain_map.items():
                if mapped == domain:
                    domain_key = key
                    break

            # Determine reliability from Phase 2 answer
            if domain_key is not None and domain_key in domain_confidence:
                chosen = domain_confidence[domain_key]
                if chosen == 0:
                    head_reliability = 0.4  # high confidence
                elif chosen == 1:
                    head_reliability = 0.35  # medium
                else:
                    head_reliability = 0.3  # low
            else:
                head_reliability = 0.3  # undeclared

            # Downgrade if any related axis is contradicted
            related_axes = _domain_axis_map.get(domain, [])
            if any(ax in contradicted_axes for ax in related_axes):
                head_reliability = 0.3

            heads.append(
                DomainHead(
                    domain=domain,
                    head_version="v000-bootstrap",
                    goal_axes=["unknown"],
                    default_priority_order=["unknown"],
                    evidence_weight_profile=EvidenceWeightProfile(
                        self_report_weight=0.5,
                        historical_behavior_weight=0.5,
                        recent_behavior_weight=0.5,
                        outcome_feedback_weight=0.5,
                        weight_confidence=0.2,
                    ),
                    head_reliability=head_reliability,
                    supported_task_types=["general"],
                    last_recalibrated_at=now,
                )
            )

        return heads

    # -- experience extraction (Phase 3 + LLM) -----------------------------

    def _aggregate_bootstrap_principles(
        self,
        answers: List[BootstrapAnswer],
        axis_values: Dict[str, float],
    ) -> List[ExperienceEntry]:
        """One LLM call: synthesize 3-5 reusable decision principles from
        forced-choice answers and computed axis values.
        """
        now = datetime.now(timezone.utc)

        # Build prompt with all forced-choice Q&A
        qa_lines: List[str] = []
        for ans in answers:
            if ans.type != QuestionType.FORCED_CHOICE:
                continue
            question = self._question_map.get(ans.question_id)
            if question is None or ans.chosen_option is None:
                continue
            chosen_text = (
                question.options[ans.chosen_option]
                if 0 <= ans.chosen_option < len(question.options)
                else "unknown"
            )
            qa_lines.append(f"Q: {question.question}\nA: {chosen_text}")

        axis_summary = ", ".join(
            f"{k}={v:.2f}" for k, v in axis_values.items()
        )
        user_msg = (
            f"Forced-choice answers:\n\n"
            + "\n\n".join(qa_lines)
            + f"\n\nComputed axis values: {axis_summary}"
        )

        result = self._llm.ask_json(_PRINCIPLES_SYSTEM, user_msg, max_tokens=1024)
        principles_raw = result.get("principles", [])

        entries: List[ExperienceEntry] = []
        for p in principles_raw:
            entries.append(
                ExperienceEntry(
                    id=f"bootstrap-principle-{uuid.uuid4().hex[:8]}",
                    scenario_type=p.get("scenario_type", ["general"]),
                    insight=p.get("insight", ""),
                    applicable_when=p.get("applicable_when", "general decisions"),
                    entry_kind="principle",
                    weight=0.9,
                    created_at=now,
                )
            )
        return entries

    def _extract_from_narrative(
        self, answer: BootstrapAnswer
    ) -> List[ExperienceEntry]:
        """One LLM call per OPEN_SCENARIO answer. Extract insight, scenario_type,
        applicable_when. Returns List[ExperienceEntry] with entry_kind='narrative'.
        """
        now = datetime.now(timezone.utc)
        if not answer.free_text:
            return []

        user_msg = f"Narrative:\n{answer.free_text}"
        result = self._llm.ask_json(_NARRATIVE_SYSTEM, user_msg, max_tokens=1024)
        entries_raw = result.get("entries", [])

        entries: List[ExperienceEntry] = []
        for e in entries_raw:
            entries.append(
                ExperienceEntry(
                    id=f"bootstrap-narrative-{uuid.uuid4().hex[:8]}",
                    scenario_type=e.get("scenario_type", ["narrative"]),
                    insight=e.get("insight", ""),
                    applicable_when=e.get("applicable_when", "similar situations"),
                    entry_kind="narrative",
                    weight=0.8,
                    created_at=now,
                )
            )
        return entries

    def _build_initial_experiences(
        self,
        answers: List[BootstrapAnswer],
        axis_values: Dict[str, float],
    ) -> ExperienceLibrary:
        """Build initial experience library from principles + narratives."""
        lib = ExperienceLibrary()

        # Aggregate principles from forced-choice answers
        principles = self._aggregate_bootstrap_principles(answers, axis_values)
        for entry in principles:
            lib.add(entry)

        # Extract from each Phase 3 open-scenario answer
        for ans in answers:
            if ans.type == QuestionType.OPEN_SCENARIO and ans.free_text:
                narratives = self._extract_from_narrative(ans)
                for entry in narratives:
                    lib.add(entry)

        return lib

    # -- TwinState assembly -------------------------------------------------

    def _build_twin_state(
        self,
        core: SharedDecisionCore,
        heads: List[DomainHead],
        user_id: str,
    ) -> TwinState:
        """Build the final TwinState following persona_compiler._create_initial pattern.

        Key differences from cold-start:
        - state_version = "v000-bootstrap"
        - min_reliability_threshold = 0.35
        - user_facing_summary is bootstrap-specific
        - modeled/non_modeled split based on head_reliability >= 0.35
        """
        now = datetime.now(timezone.utc)

        modeled = [
            h.domain.value
            for h in heads
            if h.head_reliability >= 0.35
        ]
        non_modeled = [
            h.domain.value
            for h in heads
            if h.head_reliability < 0.35
        ]

        all_domains = list(DomainEnum)

        return TwinState(
            id=f"twin-{user_id}",
            created_at=now,
            user_id=user_id,
            state_version="v000-bootstrap",
            active=True,
            shared_decision_core=core,
            causal_belief_model=CausalBeliefModel(
                control_orientation=ControlOrientation.MIXED,
                effort_vs_system_weight=0.0,
                relationship_model=None,
                change_strategy=None,
                preferred_levers=[],
                ignored_levers=[],
                option_visibility_bias=[],
                causal_confidence=0.2,
                anchor_cases=[],
            ),
            domain_heads=heads,
            transfer_coefficients=[],
            reliability_profile=[
                ReliabilityProfileEntry(
                    domain=d,
                    task_type="general",
                    reliability_score=0.3,
                    uncertainty_band="0.1-0.5",
                    evidence_strength=0.2,
                    scope_status=ReliabilityScopeStatus.WEAKLY_MODELED,
                    last_updated_at=now,
                )
                for d in all_domains
            ],
            scope_declaration=ScopeDeclaration(
                modeled_capabilities=modeled,
                non_modeled_capabilities=non_modeled,
                restricted_use_cases=[
                    "financial advice",
                    "medical decisions",
                    "legal counsel",
                ],
                min_reliability_threshold=0.35,
                rejection_policy=RejectionPolicyMap(
                    out_of_scope=MergeStrategy.REFUSE,
                    borderline=MergeStrategy.DEGRADE,
                ),
                user_facing_summary=(
                    "Bootstrap-provisional twin. "
                    "Reliability will improve with calibration data."
                ),
            ),
            temporal_metadata=TemporalMetadata(
                state_valid_from=now,
                fast_variables=["core_confidence"],
                slow_variables=["risk_tolerance", "conflict_style"],
                irreversible_shifts=[],
                major_life_events=[],
            ),
        )

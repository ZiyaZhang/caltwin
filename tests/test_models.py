"""Tests for Pydantic model validation against schema expectations."""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from twin_runtime.domain.models import (
    TwinState,
    SharedDecisionCore,
    CausalBeliefModel,
    DomainHead,
    EvidenceWeightProfile,
    ScopeDeclaration,
    RejectionPolicyMap,
    ReliabilityProfileEntry,
    TemporalMetadata,
    SituationFrame,
    SituationFeatureVector,
    HeadAssessment,
    ConflictReport,
    RuntimeDecisionTrace,
    RuntimeEvent,
    CalibrationCase,
    CandidateCalibrationCase,
    TwinEvaluation,
    DomainEnum,
    ConflictStyle,
    ControlOrientation,
    OrdinalTriLevel,
    MergeStrategy,
    DecisionMode,
    ScopeStatus,
    ReliabilityScopeStatus,
    ConflictType,
    CandidateSourceType,
    RuntimeEventType,
    UncertaintyType,
    OptionStructure,
)
from twin_runtime.domain.models.twin_state import TransferCoefficient
from twin_runtime.domain.models.experience import PatternInsight


class TestTwinStateFromFixture:
    def test_loads_from_fixture(self, sample_twin):
        assert sample_twin.id == "twin-001"
        assert sample_twin.user_id == "user-default"
        assert sample_twin.state_version == "v002"
        assert sample_twin.active is True

    def test_shared_decision_core(self, sample_twin):
        core = sample_twin.shared_decision_core
        assert core.risk_tolerance == 0.65
        assert core.conflict_style == ConflictStyle.AVOIDANT
        assert core.evidence_count == 62

    def test_causal_belief_model(self, sample_twin):
        cbm = sample_twin.causal_belief_model
        assert cbm.control_orientation == ControlOrientation.INTERNAL
        assert cbm.effort_vs_system_weight == 0.3
        assert "technology" in cbm.preferred_levers

    def test_domain_heads(self, sample_twin):
        assert len(sample_twin.domain_heads) == 3
        work = sample_twin.domain_heads[0]
        assert work.domain == DomainEnum.WORK
        assert work.head_reliability == 0.72
        life = sample_twin.domain_heads[1]
        assert life.domain == DomainEnum.LIFE_PLANNING
        assert life.head_reliability == 0.55
        money = sample_twin.domain_heads[2]
        assert money.domain == DomainEnum.MONEY
        assert money.head_reliability == 0.5

    def test_valid_domains(self, sample_twin):
        valid = sample_twin.valid_domains()
        assert DomainEnum.WORK in valid
        assert DomainEnum.LIFE_PLANNING in valid  # 0.55 >= 0.5 threshold
        assert DomainEnum.MONEY in valid  # 0.5 >= 0.5 threshold

    def test_transfer_coefficients(self, sample_twin):
        assert len(sample_twin.transfer_coefficients) == 2
        tc = sample_twin.transfer_coefficients[0]
        assert tc.from_domain == DomainEnum.WORK
        assert tc.to_domain == DomainEnum.LIFE_PLANNING
        assert tc.coefficient == 0.65

    def test_scope_declaration(self, sample_twin):
        sd = sample_twin.scope_declaration
        assert sd.min_reliability_threshold == 0.5
        assert sd.rejection_policy.out_of_scope == MergeStrategy.REFUSE
        assert sd.rejection_policy.borderline == MergeStrategy.DEGRADE

    def test_temporal_metadata(self, sample_twin):
        tm = sample_twin.temporal_metadata
        assert "risk_tolerance" in tm.slow_variables
        assert "explore_exploit_balance" in tm.fast_variables
        assert tm.state_valid_to is None

    def test_roundtrip_json(self, sample_twin):
        json_str = sample_twin.model_dump_json()
        restored = TwinState.model_validate_json(json_str)
        assert restored.id == sample_twin.id
        assert restored.shared_decision_core.risk_tolerance == sample_twin.shared_decision_core.risk_tolerance


class TestModelValidation:
    def test_confidence_score_out_of_range(self):
        with pytest.raises(ValidationError):
            SharedDecisionCore(
                risk_tolerance=1.5,  # out of range
                ambiguity_tolerance=0.5,
                action_threshold=0.5,
                information_threshold=0.5,
                reversibility_preference=0.5,
                regret_sensitivity=0.5,
                explore_exploit_balance=0.5,
                conflict_style="direct",
                core_confidence=0.5,
                evidence_count=0,
                last_recalibrated_at=datetime.now(timezone.utc),
            )

    def test_empty_domain_heads_rejected(self, sample_twin_dict):
        sample_twin_dict["domain_heads"] = []
        with pytest.raises(ValidationError):
            TwinState.model_validate(sample_twin_dict)

    def test_empty_reliability_profile_rejected(self, sample_twin_dict):
        sample_twin_dict["reliability_profile"] = []
        with pytest.raises(ValidationError):
            TwinState.model_validate(sample_twin_dict)

    def test_invalid_domain_enum(self):
        with pytest.raises(ValidationError):
            ReliabilityProfileEntry(
                domain="invalid_domain",
                task_type="test",
                reliability_score=0.5,
                evidence_strength=0.5,
                scope_status="modeled",
                last_updated_at=datetime.now(timezone.utc),
            )

    def test_transfer_coefficient_self_referential_rejected(self):
        with pytest.raises(ValidationError, match="self-referential"):
            TransferCoefficient(
                from_domain=DomainEnum.WORK,
                to_domain=DomainEnum.WORK,
                coefficient=0.5,
                confidence=0.8,
                supporting_case_count=5,
                last_validated_at=datetime.now(timezone.utc),
            )

    def test_transfer_coefficient_different_domains_ok(self):
        tc = TransferCoefficient(
            from_domain=DomainEnum.WORK,
            to_domain=DomainEnum.MONEY,
            coefficient=0.6,
            confidence=0.7,
            supporting_case_count=3,
            last_validated_at=datetime.now(timezone.utc),
        )
        assert tc.from_domain != tc.to_domain

    def test_pattern_insight_weight_upper_bound(self):
        with pytest.raises(ValidationError):
            PatternInsight(
                id="p-1",
                pattern_description="test",
                systematic_bias="test",
                correction_strategy="test",
                weight=11.0,  # exceeds le=10.0
                created_at=datetime.now(timezone.utc),
            )

    def test_pattern_insight_weight_valid(self):
        p = PatternInsight(
            id="p-1",
            pattern_description="test",
            systematic_bias="test",
            correction_strategy="test",
            weight=10.0,
            created_at=datetime.now(timezone.utc),
        )
        assert p.weight == 10.0


class TestSituationFrame:
    def test_basic_creation(self):
        frame = SituationFrame(
            frame_id="sf-001",
            domain_activation_vector={DomainEnum.WORK: 0.8, DomainEnum.MONEY: 0.2},
            situation_feature_vector=SituationFeatureVector(
                reversibility=OrdinalTriLevel.HIGH,
                stakes=OrdinalTriLevel.MEDIUM,
                uncertainty_type=UncertaintyType.MISSING_INFO,
                controllability=OrdinalTriLevel.HIGH,
                option_structure=OptionStructure.CHOOSE_EXISTING,
            ),
            ambiguity_score=0.2,
            scope_status=ScopeStatus.IN_SCOPE,
            routing_confidence=0.85,
        )
        assert frame.domain_activation_vector[DomainEnum.WORK] == 0.8

    def test_empty_activation_vector_allowed(self):
        """Phase 5a: empty activation vector is now valid (scope-guard may refuse)."""
        frame = SituationFrame(
            frame_id="sf-empty",
            domain_activation_vector={},
            situation_feature_vector=SituationFeatureVector(
                reversibility=OrdinalTriLevel.LOW,
                stakes=OrdinalTriLevel.HIGH,
                uncertainty_type=UncertaintyType.VALUE_CONFLICT,
                controllability=OrdinalTriLevel.LOW,
                option_structure=OptionStructure.GENERATE_NEW,
            ),
            ambiguity_score=0.9,
            scope_status=ScopeStatus.BORDERLINE,
            routing_confidence=0.3,
        )
        assert frame.domain_activation_vector == {}


class TestRuntimeModels:
    def test_head_assessment(self):
        ha = HeadAssessment(
            domain=DomainEnum.WORK,
            head_version="v001",
            option_ranking=["A", "B", "C"],
            utility_decomposition={"impact": 0.8, "cost": 0.3},
            confidence=0.75,
        )
        assert ha.option_ranking[0] == "A"

    def test_conflict_report(self):
        cr = ConflictReport(
            report_id="cr-001",
            activated_heads=[DomainEnum.WORK, DomainEnum.LIFE_PLANNING],
            conflict_types=[ConflictType.PREFERENCE],
            resolvable_by_system=False,
            requires_user_clarification=True,
            requires_more_evidence=False,
            final_merge_strategy=MergeStrategy.CLARIFY,
        )
        assert not cr.resolvable_by_system

    def test_runtime_decision_trace(self):
        trace = RuntimeDecisionTrace(
            trace_id="rt-001",
            twin_state_version="v001",
            situation_frame_id="sf-001",
            activated_domains=[DomainEnum.WORK],
            head_assessments=[
                HeadAssessment(
                    domain=DomainEnum.WORK,
                    head_version="v001",
                    option_ranking=["A"],
                    utility_decomposition={"impact": 0.9},
                    confidence=0.8,
                )
            ],
            final_decision="Choose A",
            decision_mode=DecisionMode.DIRECT,
            uncertainty=0.2,
            created_at=datetime.now(timezone.utc),
        )
        assert trace.decision_mode == DecisionMode.DIRECT


class TestCalibrationModels:
    def test_calibration_case(self):
        cc = CalibrationCase(
            case_id="cc-001",
            created_at=datetime.now(timezone.utc),
            domain_label=DomainEnum.WORK,
            task_type="prioritization",
            observed_context="User chose to work on feature X over bug Y",
            option_set=["feature_x", "bug_y", "refactor_z"],
            actual_choice="feature_x",
            stakes=OrdinalTriLevel.MEDIUM,
            reversibility=OrdinalTriLevel.HIGH,
            confidence_of_ground_truth=0.9,
            used_for_calibration=False,
        )
        assert cc.actual_choice == "feature_x"

    def test_candidate_calibration_case(self):
        ccc = CandidateCalibrationCase(
            candidate_id="cand-001",
            created_at=datetime.now(timezone.utc),
            source_type=CandidateSourceType.USER_CORRECTION,
            domain_label=DomainEnum.WORK,
            observed_context="User said 'I would not have chosen B'",
            option_set=["A", "B"],
            observed_choice="A",
            stakes=OrdinalTriLevel.LOW,
            reversibility=OrdinalTriLevel.HIGH,
            ground_truth_confidence=0.95,
            promoted_to_calibration_case=False,
        )
        assert not ccc.promoted_to_calibration_case

    def test_twin_evaluation(self):
        te = TwinEvaluation(
            evaluation_id="eval-001",
            twin_state_version="v001",
            calibration_case_ids=["cc-001", "cc-002"],
            choice_similarity=0.75,
            domain_reliability={"work": 0.7, "life_planning": 0.35},
            evaluated_at=datetime.now(timezone.utc),
        )
        assert te.choice_similarity == 0.75
        assert te.domain_reliability["work"] == 0.7

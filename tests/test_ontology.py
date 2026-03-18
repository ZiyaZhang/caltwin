"""Tests for shadow ontology pipeline. Requires scikit-learn."""
import pytest
sklearn = pytest.importorskip("sklearn")

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from twin_runtime.domain.models.calibration import CalibrationCase
from twin_runtime.domain.models.primitives import DomainEnum
from twin_runtime.application.ontology.document_builder import build_document
from twin_runtime.application.ontology.clusterer import cluster_cases
from twin_runtime.application.ontology.stability import assess_stability
from twin_runtime.application.ontology.report_generator import generate_ontology_report


def _case(case_id, domain, task_type, context, days_ago=10):
    return CalibrationCase(
        case_id=case_id, created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        domain_label=domain, task_type=task_type,
        observed_context=context, option_set=["A", "B"],
        actual_choice="A", stakes="medium", reversibility="medium",
        confidence_of_ground_truth=0.9,
    )


class TestDocumentBuilder:
    def test_includes_context_and_structural_tokens(self):
        case = _case("c1", DomainEnum.WORK, "prioritization", "Should I ship or refactor?")
        doc = build_document(case)
        assert "ship" in doc
        assert "stakes:medium" in doc
        assert "task_type:prioritization" in doc


class TestClusterer:
    def test_clusters_similar_documents(self):
        docs = [
            "project deadline deploy sprint task_type:deployment stakes:high",
            "project release deploy ship task_type:deployment stakes:high",
            "project deploy pipeline ci task_type:deployment stakes:medium",
            "invest portfolio allocation risk task_type:investment stakes:high",
            "invest stocks bonds return task_type:investment stakes:medium",
            "invest crypto market analysis task_type:investment stakes:high",
        ]
        ids = [f"c{i}" for i in range(len(docs))]
        clusters = cluster_cases(docs, ids, distance_threshold=0.8, min_cluster_size=2)
        assert len(clusters) >= 1  # Should find at least one cluster

    def test_returns_empty_for_few_docs(self):
        assert cluster_cases(["one doc"], ["c1"], min_cluster_size=3) == []


class TestStability:
    def test_stable_recent_cluster(self):
        cases = [_case(f"c{i}", DomainEnum.WORK, "test", "test context", days_ago=i*5) for i in range(5)]
        result = assess_stability([c.case_id for c in cases], cases, min_support=3, min_decayed_support=1.5)
        assert result["stable"] is True
        assert result["support_count"] == 5

    def test_unstable_insufficient_support(self):
        cases = [_case("c1", DomainEnum.WORK, "test", "test")]
        result = assess_stability(["c1"], cases, min_support=3)
        assert result["stable"] is False


class TestReportGenerator:
    def test_generates_report(self):
        from unittest.mock import MagicMock
        twin = MagicMock()
        twin.state_version = "v1"
        # Create enough similar cases to form a cluster
        cases = [
            _case(f"w{i}", DomainEnum.WORK, "deployment", f"deploy project sprint release {i}", days_ago=i*3)
            for i in range(6)
        ]
        report = generate_ontology_report(cases, twin, min_support=3, distance_threshold=0.9)
        assert report.total_cases_analyzed == 6
        assert "work" in report.domains_analyzed

    def test_empty_cases_returns_empty_report(self):
        from unittest.mock import MagicMock
        twin = MagicMock()
        twin.state_version = "v1"
        report = generate_ontology_report([], twin)
        assert report.suggestions == []

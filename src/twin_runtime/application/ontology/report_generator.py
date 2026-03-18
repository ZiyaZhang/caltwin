"""Assemble OntologyReport from clustering + stability results."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from twin_runtime.application.calibration.time_decay import CALIBRATION_HALF_LIFE, CALIBRATION_FLOOR
from twin_runtime.application.ontology.document_builder import build_document
from twin_runtime.application.ontology.stability import assess_stability
from twin_runtime.domain.models.calibration import CalibrationCase
from twin_runtime.domain.models.ontology import OntologyReport, OntologySuggestion
from twin_runtime.domain.models.twin_state import TwinState


def generate_ontology_report(
    cases: List[CalibrationCase],
    twin: TwinState,
    *,
    as_of: Optional[datetime] = None,
    distance_threshold: float = 0.7,
    min_support: int = 3,
    min_decayed_support: float = 1.5,
) -> OntologyReport:
    """Generate shadow ontology report. Clusters within each parent domain."""
    if as_of is None:
        as_of = datetime.now(timezone.utc)

    try:
        from twin_runtime.application.ontology.clusterer import cluster_cases
    except ImportError:
        raise ImportError("Shadow ontology requires: pip install twin-runtime[analysis]")

    # Group cases by parent domain
    domain_groups: Dict[str, List[CalibrationCase]] = {}
    for c in cases:
        domain_groups.setdefault(c.domain_label.value, []).append(c)

    suggestions: List[OntologySuggestion] = []
    domains_analyzed = []

    for domain_name, domain_cases in sorted(domain_groups.items()):
        if len(domain_cases) < min_support:
            continue
        domains_analyzed.append(domain_name)

        documents = [build_document(c) for c in domain_cases]
        case_ids = [c.case_id for c in domain_cases]

        clusters = cluster_cases(documents, case_ids, distance_threshold, min_support)

        for cluster in clusters:
            stability = assess_stability(cluster["case_ids"], cases, as_of, min_support, min_decayed_support)
            if not stability["stable"]:
                continue

            deterministic_label = "_".join(cluster["top_terms"][:3])

            from twin_runtime.domain.models.primitives import DomainEnum
            suggestions.append(OntologySuggestion(
                suggested_subdomain=deterministic_label,
                parent_domain=DomainEnum(domain_name),
                deterministic_label=deterministic_label,
                support_count=stability["support_count"],
                decayed_support=stability["decayed_support"],
                stability_score=stability["stability_score"],
                representative_terms=cluster["top_terms"],
                representative_case_ids=cluster["case_ids"][:5],
            ))

    return OntologyReport(
        report_id=str(uuid.uuid4()),
        twin_state_version=twin.state_version,
        as_of=as_of,
        decay_params={"half_life": CALIBRATION_HALF_LIFE, "floor": CALIBRATION_FLOOR},
        suggestions=suggestions,
        domains_analyzed=domains_analyzed,
        total_cases_analyzed=len(cases),
        clustering_params={"distance_threshold": distance_threshold, "min_support": min_support},
    )

from __future__ import annotations

from src.benchmark_v1 import CaseEvaluation, phase6_frozen_protocol_v1
from scripts.evaluate_ahoj_geometry_static_development import decompose_case_evaluation


def _evaluation(
    dcc: tuple[float, ...],
    dca: tuple[float, ...],
) -> CaseEvaluation:
    protocol = phase6_frozen_protocol_v1()
    return CaseEvaluation(
        case_id="case-1",
        structure_id="1ABC",
        detector="biovoid_static",
        status="completed",
        dcc_by_rank=dcc,
        dca_by_rank=dca,
        top_k_dcc_hits={
            key: any(value <= protocol.dcc_tolerance_angstrom for value in dcc[:key])
            for key in protocol.top_k
        },
        top_k_dca_hits={
            key: any(value <= protocol.dca_tolerance_angstrom for value in dca[:key])
            for key in protocol.top_k
        },
        false_pockets=0,
        residue_precision=None,
        residue_recall=None,
        error=None,
        ground_truth_quality="exact",
    )


def test_decomposition_distinguishes_late_ranking_from_universe_miss() -> None:
    protocol = phase6_frozen_protocol_v1()

    late = decompose_case_evaluation(
        _evaluation(
            (9.0, 8.0, 7.0, 6.0, 5.0, 3.0),
            (9.0, 8.0, 7.0, 6.0, 5.0, 3.0),
        ),
        protocol,
    )
    assert late["candidate_universe"]["joint_hit"] is True
    assert late["best_rank"]["joint"] == 6
    assert late["taxonomy"] == "A_candidate_present_ranking_miss"

    miss = decompose_case_evaluation(
        _evaluation((9.0, 8.0), (9.0, 8.0)),
        protocol,
    )
    assert miss["candidate_universe"]["joint_hit"] is False
    assert miss["taxonomy"] == "C_candidate_universe_miss"


def test_decomposition_preserves_metric_disagreement() -> None:
    protocol = phase6_frozen_protocol_v1()
    result = decompose_case_evaluation(
        _evaluation((3.0, 9.0), (9.0, 3.0)),
        protocol,
    )
    assert result["candidate_universe"] == {
        "dcc_hit": True,
        "dca_hit": True,
        "joint_hit": False,
    }
    assert result["taxonomy"] == "B_metric_disagreement"


def test_decomposition_keeps_unavailable_case_visible() -> None:
    protocol = phase6_frozen_protocol_v1()
    evaluation = CaseEvaluation(
        case_id="case-1",
        structure_id="1ABC",
        detector="biovoid_static",
        status="unavailable",
        dcc_by_rank=(),
        dca_by_rank=(),
        top_k_dcc_hits={key: False for key in protocol.top_k},
        top_k_dca_hits={key: False for key in protocol.top_k},
        false_pockets=None,
        residue_precision=None,
        residue_recall=None,
        error="alignment unavailable",
        ground_truth_quality="exact",
    )
    result = decompose_case_evaluation(evaluation, protocol)
    assert result["status"] == "unavailable"
    assert result["taxonomy"] == "alignment_or_detector_unavailable"

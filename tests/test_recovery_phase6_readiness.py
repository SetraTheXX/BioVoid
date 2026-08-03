"""Offline readiness gates required before Phase 6 benchmark execution."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import pytest


def _frozen_protocol():
    from src.benchmark_v1 import BenchmarkProtocol

    return BenchmarkProtocol("synthetic-readiness-only").freeze(
        dcc_tolerance_angstrom=4.0,
        dca_tolerance_angstrom=3.0,
        false_pocket_tolerance_angstrom=5.0,
        false_pocket_scope_k=5,
        bootstrap_replicates=1000,
        bootstrap_seed=20260729,
        minimum_motion_improvement=0.0,
        false_pocket_noninferiority_margin=0.1,
        failure_rate_noninferiority_margin=0.1,
    )


def _case(
    structure_id: str,
    *,
    case_id: str | None = None,
    family_id: str = "family-a",
    split: str = "development",
):
    from src.benchmark_v1 import BenchmarkCase

    return BenchmarkCase(
        case_id=case_id or f"{structure_id}:site-1",
        structure_id=structure_id,
        family_id=family_id,
        split=split,
        prepared_structure_sha256="1" * 64,
        preparation_config_sha256="2" * 64,
    )


def _truth(structure_id: str, *, case_id: str | None = None):
    from src.benchmark_v1 import EvaluatorGroundTruth

    return EvaluatorGroundTruth(
        case_id=case_id or f"{structure_id}:site-1",
        structure_id=structure_id,
        coordinate_frame_sha256="1" * 64,
        alignment_sha256="a" * 64,
        ligand_center=(0.0, 0.0, 0.0),
        ligand_atoms=((1.0, 0.0, 0.0), (-1.0, 0.0, 0.0)),
        ligand_residues=("A:10", "A:11"),
        provenance="synthetic-readiness-ground-truth",
    )


def test_protocol_cannot_freeze_with_implicit_endpoint_decisions() -> None:
    from src.benchmark_v1 import BenchmarkContractError, BenchmarkProtocol

    draft = BenchmarkProtocol("phase6-draft")

    with pytest.raises(BenchmarkContractError, match="missing"):
        replace(draft, state="frozen")

    frozen = _frozen_protocol()
    assert frozen.state == "frozen"
    assert len(frozen.protocol_sha256) == 64
    assert frozen.to_manifest()["primary_endpoint"] == "top_3_dcc_localization_recall"


def test_phase6_protocol_v1_is_explicit_and_frozen() -> None:
    from src.benchmark_v1 import phase6_frozen_protocol_v1

    protocol = phase6_frozen_protocol_v1()

    assert protocol.protocol_id == "phase6-cryptobench-v1"
    assert protocol.state == "frozen"
    assert protocol.dcc_tolerance_angstrom == 4.0
    assert protocol.dca_tolerance_angstrom == 4.0
    assert protocol.false_pocket_scope_k == 5
    assert protocol.minimum_motion_improvement == 0.0
    assert protocol.false_pocket_noninferiority_margin == 0.0
    assert protocol.failure_rate_noninferiority_margin == 0.0


def test_motion_gate_requires_strict_primary_improvement_and_complete_references() -> None:
    from src.benchmark_v1 import assess_motion_integration, phase6_frozen_protocol_v1

    protocol = phase6_frozen_protocol_v1()
    common = {
        "protocol_sha256": protocol.protocol_sha256,
        "manifest_sha256": "1" * 64,
        "split": "development",
        "target_denominator": 10,
        "structure_denominator": 8,
        "failure_rate": 0.0,
        "false_pocket_metric_status": "complete_annotations",
        "false_pockets_per_completed_protein": 2.0,
        "resource_reporting_complete": True,
    }
    static = {
        **common,
        "detector": "biovoid_static",
        "top_k_dcc_recall": {1: 0.1, 3: 0.4, 5: 0.5},
    }
    improved_motion = {
        **common,
        "detector": "biovoid_motion",
        "top_k_dcc_recall": {1: 0.1, 3: 0.5, 5: 0.6},
    }

    accepted = assess_motion_integration(static, improved_motion, protocol)
    equal = assess_motion_integration(
        static,
        {**improved_motion, "top_k_dcc_recall": {1: 0.1, 3: 0.4, 5: 0.6}},
        protocol,
    )
    incomplete = assess_motion_integration(
        static,
        {
            **improved_motion,
            "false_pocket_metric_status": "unavailable",
            "false_pockets_per_completed_protein": None,
        },
        protocol,
    )

    assert accepted["canonical_integration_eligible"] is True
    assert equal["canonical_integration_eligible"] is False
    assert "primary_endpoint_not_strictly_improved" in equal["reasons"]
    assert incomplete["canonical_integration_eligible"] is False
    assert "complete_binding_site_references_required" in incomplete["reasons"]


def test_detector_payload_rejects_nested_holo_or_ligand_leakage() -> None:
    from src.evaluator_format import (
        DetectorLeakageError,
        adapt_biovoid_pockets,
    )

    with pytest.raises(DetectorLeakageError, match="ligand_center"):
        adapt_biovoid_pockets(
            "TEST",
            [
                {
                    "center": [1.0, 2.0, 3.0],
                    "metadata": {"ligand_center": [1.0, 2.0, 3.0]},
                }
            ],
        )

    with pytest.raises(DetectorLeakageError, match=r"ground[-_]truth"):
        adapt_biovoid_pockets(
            "TEST",
            [{"center": [1.0, 2.0, 3.0], "ground-truth": {"hit": True}}],
        )


def test_detector_input_is_target_blind_by_construction() -> None:
    detector_input = _case("1ABC").detector_input()

    assert set(detector_input) == {
        "structure_id",
        "prepared_structure_sha256",
        "preparation_config_sha256",
    }
    assert not any("ligand" in key or "holo" in key for key in detector_input)


def test_manifest_rejects_duplicates_and_family_split_leakage() -> None:
    from src.benchmark_v1 import BenchmarkContractError, BenchmarkManifest

    with pytest.raises(BenchmarkContractError, match="Duplicate"):
        BenchmarkManifest(
            (
                _case("1AAA", case_id="duplicate"),
                _case("2BBB", case_id="duplicate"),
            )
        )

    with pytest.raises(BenchmarkContractError, match="crosses"):
        BenchmarkManifest(
            (
                _case("1AAA", family_id="shared", split="development"),
                _case("2BBB", family_id="shared", split="sealed"),
            )
        )


def test_one_structure_can_have_multiple_blind_targets_without_double_counting() -> None:
    from src.benchmark_v1 import (
        BenchmarkManifest,
        EvaluatorGroundTruth,
        evaluate_split,
    )
    from src.evaluator_format import adapt_biovoid_pockets

    manifest = BenchmarkManifest(
        (
            _case("1AAA", case_id="1AAA:site-1"),
            _case("1AAA", case_id="1AAA:site-2"),
        )
    )
    records = {
        "1AAA": adapt_biovoid_pockets(
            "1AAA",
            [
                {"rank": 1, "center": [0.0, 0.0, 0.0]},
                {"rank": 2, "center": [20.0, 0.0, 0.0]},
                {"rank": 3, "center": [100.0, 0.0, 0.0]},
            ],
            provenance={"runtime_seconds": 2.0, "peak_rss_bytes": 2000},
        )
    }
    truths = {
        "1AAA:site-1": _truth("1AAA", case_id="1AAA:site-1"),
        "1AAA:site-2": EvaluatorGroundTruth(
            case_id="1AAA:site-2",
            structure_id="1AAA",
            coordinate_frame_sha256="1" * 64,
            alignment_sha256="b" * 64,
            ligand_center=(20.0, 0.0, 0.0),
            ligand_atoms=((19.0, 0.0, 0.0), (21.0, 0.0, 0.0)),
            provenance="synthetic-readiness-ground-truth",
        ),
    }

    summary = evaluate_split(
        detector="biovoid_static",
        split="development",
        records=records,
        ground_truth=truths,
        binding_site_reference_centers={
            "1AAA": ((0.0, 0.0, 0.0), (20.0, 0.0, 0.0)),
        },
        manifest=manifest,
        protocol=_frozen_protocol(),
    )

    assert summary["target_denominator"] == 2
    assert summary["structure_denominator"] == 1
    assert summary["top_k_dcc_recall"][3] == 1.0
    assert summary["mean_best_dcc_angstrom"] == 0.0
    assert summary["false_pockets_per_completed_protein"] == 1.0
    assert summary["runtime_seconds_total"] == 2.0
    assert len(summary["results"]) == 2
    assert {result["case_id"] for result in summary["results"]} == {
        "1AAA:site-1",
        "1AAA:site-2",
    }


def test_false_pocket_metric_requires_complete_binding_site_references() -> None:
    from src.benchmark_v1 import BenchmarkManifest, evaluate_split
    from src.evaluator_format import adapt_biovoid_pockets

    manifest = BenchmarkManifest((_case("1AAA"),))
    records = {
        "1AAA": adapt_biovoid_pockets(
            "1AAA",
            [
                {"rank": 1, "center": [0.0, 0.0, 0.0]},
                {"rank": 2, "center": [20.0, 0.0, 0.0]},
            ],
        )
    }
    truths = {"1AAA:site-1": _truth("1AAA")}

    unavailable = evaluate_split(
        detector="biovoid_static",
        split="development",
        records=records,
        ground_truth=truths,
        manifest=manifest,
        protocol=_frozen_protocol(),
    )
    annotated = evaluate_split(
        detector="biovoid_static",
        split="development",
        records=records,
        ground_truth=truths,
        binding_site_reference_centers={
            "1AAA": ((0.0, 0.0, 0.0), (20.0, 0.0, 0.0)),
        },
        manifest=manifest,
        protocol=_frozen_protocol(),
    )

    assert unavailable["false_pocket_metric_status"] == "unavailable"
    assert unavailable["false_pockets_per_completed_protein"] is None
    assert annotated["false_pocket_metric_status"] == "complete_annotations"
    assert annotated["false_pockets_per_completed_protein"] == 0.0


def test_cryptobench_adapter_merges_observations_into_unique_target_sites() -> None:
    from src.cryptobench_adapter import build_target_sites

    dataset = {
        "1abc": [
            {
                "uniprot_id": "P00001",
                "holo_pdb_id": "2abc",
                "holo_chain": "A",
                "apo_chain": "A",
                "ligand": "L1",
                "ligand_index": "101",
                "ligand_chain": "A",
                "apo_pocket_selection": ["A_10", "A_11", "A_12", "A_13"],
                "holo_pocket_selection": ["A_10", "A_11", "A_12", "A_13"],
                "pRMSD": 2.2,
                "is_main_holo_structure": True,
            },
            {
                "uniprot_id": "P00001",
                "holo_pdb_id": "3abc",
                "holo_chain": "B",
                "apo_chain": "A",
                "ligand": "L2",
                "ligand_index": "202",
                "ligand_chain": "B",
                "apo_pocket_selection": ["A_10", "A_11", "A_12"],
                "holo_pocket_selection": ["B_10", "B_11", "B_12"],
                "pRMSD": 3.1,
                "is_main_holo_structure": False,
            },
            {
                "uniprot_id": "P00001",
                "holo_pdb_id": "4abc",
                "holo_chain": "C",
                "apo_chain": "A",
                "ligand": "L3",
                "ligand_index": "303",
                "ligand_chain": "C",
                "apo_pocket_selection": ["A_80", "B_81", "B_82"],
                "holo_pocket_selection": ["C_80", "D_81", "D_82"],
                "pRMSD": 2.8,
                "is_main_holo_structure": False,
            },
        ]
    }

    sites = build_target_sites(dataset, dataset_id="cryptobench-2025", split="development")

    assert len(sites) == 2
    first = next(site for site in sites if "A_10" in site.apo_pocket_residues)
    second = next(site for site in sites if "A_80" in site.apo_pocket_residues)
    assert first.observation_count == 2
    assert first.representative.holo_pdb_id == "3ABC"
    assert first.representative.pocket_rmsd_angstrom == 3.1
    assert second.required_apo_chains == ("A", "B")
    assert len({site.case_id for site in sites}) == 2


def test_approximate_ground_truth_requires_quality_provenance() -> None:
    from src.benchmark_v1 import BenchmarkContractError, EvaluatorGroundTruth

    with pytest.raises(BenchmarkContractError, match="provenance"):
        EvaluatorGroundTruth(
            case_id="TEST:site-1",
            structure_id="TEST",
            coordinate_frame_sha256="1" * 64,
            alignment_sha256="a" * 64,
            ligand_center=(0.0, 0.0, 0.0),
            ligand_atoms=((0.0, 0.0, 0.0),),
            quality="approximate",
        )


def test_ground_truth_must_match_prepared_apo_coordinate_frame() -> None:
    from src.benchmark_v1 import (
        BenchmarkContractError,
        BenchmarkManifest,
        evaluate_split,
    )
    from src.evaluator_format import adapt_biovoid_pockets

    manifest = BenchmarkManifest((_case("1AAA"),))
    mismatched_truth = replace(
        _truth("1AAA"),
        coordinate_frame_sha256="9" * 64,
    )

    with pytest.raises(BenchmarkContractError, match="coordinate frame mismatch"):
        evaluate_split(
            detector="biovoid_static",
            split="development",
            records={
                "1AAA": adapt_biovoid_pockets(
                    "1AAA",
                    [{"center": [0.0, 0.0, 0.0]}],
                )
            },
            ground_truth={"1AAA:site-1": mismatched_truth},
            manifest=manifest,
            protocol=_frozen_protocol(),
        )


def test_evaluator_uses_ranked_geometry_not_bioscore() -> None:
    from src.benchmark_v1 import evaluate_case
    from src.evaluator_format import adapt_biovoid_pockets

    pockets = [
        {
            "pocket_id": "near",
            "rank": 1,
            "center": [4.0, 0.0, 0.0],
            "bio_score": 0.01,
            "residues": ["A:10", "A:99"],
        },
        {
            "pocket_id": "far",
            "rank": 2,
            "center": [20.0, 0.0, 0.0],
            "bio_score": 0.99,
        },
    ]
    reversed_scores = [
        {**pockets[0], "bio_score": 0.99},
        {**pockets[1], "bio_score": 0.01},
    ]

    first = evaluate_case(
        adapt_biovoid_pockets("TEST", pockets),
        _truth("TEST"),
        _frozen_protocol(),
        false_pocket_reference_centers=((0.0, 0.0, 0.0),),
    )
    second = evaluate_case(
        adapt_biovoid_pockets("TEST", reversed_scores),
        _truth("TEST"),
        _frozen_protocol(),
        false_pocket_reference_centers=((0.0, 0.0, 0.0),),
    )

    assert first == second
    assert first.dcc_by_rank == (4.0, 20.0)
    assert first.dca_by_rank == (3.0, 19.0)
    assert first.top_k_dcc_hits[1]
    assert first.top_k_dca_hits[1]
    assert first.false_pockets == 1
    assert first.residue_precision == 0.5
    assert first.residue_recall == 0.5
    assert first.score_used is False


def test_residue_metrics_normalize_dataset_and_detector_identifiers() -> None:
    from src.benchmark_v1 import evaluate_case
    from src.evaluator_format import adapt_biovoid_pockets

    truth = replace(_truth("TEST"), ligand_residues=("A_10", "A_11"))
    record = adapt_biovoid_pockets(
        "TEST",
        [
            {
                "pocket_id": "near",
                "rank": 1,
                "center": [0.0, 0.0, 0.0],
                "residues": ["A:ASP:10", "A:THR:11", "A:GLY:99"],
            }
        ],
    )

    result = evaluate_case(record, truth, _frozen_protocol())

    assert result.residue_precision == pytest.approx(2 / 3)
    assert result.residue_recall == 1.0


def test_failed_and_missing_results_remain_in_recall_denominator() -> None:
    from src.benchmark_v1 import BenchmarkManifest, evaluate_split
    from src.evaluator_format import adapt_biovoid_pockets

    manifest = BenchmarkManifest(
        (
            _case("1AAA", family_id="family-a"),
            _case("2BBB", family_id="family-b"),
        )
    )
    records = {
        "1AAA": adapt_biovoid_pockets(
            "1AAA",
            [{"rank": 1, "center": [0.0, 0.0, 0.0], "bio_score": 0.2}],
            provenance={"runtime_seconds": 1.25, "peak_rss_bytes": 1000},
        )
    }
    truths = {
        "1AAA:site-1": _truth("1AAA"),
        "2BBB:site-1": _truth("2BBB"),
    }

    summary = evaluate_split(
        detector="biovoid_static",
        split="development",
        records=records,
        ground_truth=truths,
        binding_site_reference_centers={
            "1AAA": ((0.0, 0.0, 0.0),),
            "2BBB": ((0.0, 0.0, 0.0),),
        },
        manifest=manifest,
        protocol=_frozen_protocol(),
    )

    assert summary["denominator"] == 2
    assert summary["completed"] == 1
    assert summary["failed_or_unavailable"] == 1
    assert summary["failure_rate"] == 0.5
    assert summary["top_k_dcc_recall"][3] == 0.5
    assert summary["top_k_dca_recall"][3] == 0.5
    assert summary["false_pocket_denominator"] == 1
    assert summary["false_pockets_per_completed_protein"] == 0.0
    assert summary["runtime_seconds_total"] == 1.25
    assert summary["peak_rss_bytes_max"] == 1000
    assert summary["resource_reporting_complete"] is True
    assert summary["score_used"] is False


def test_recall_uncertainty_uses_deterministic_family_cluster_bootstrap() -> None:
    from src.benchmark_v1 import BenchmarkManifest, evaluate_split
    from src.evaluator_format import adapt_biovoid_pockets

    manifest = BenchmarkManifest(
        (
            _case("1AAA", family_id="family-a"),
            _case("2BBB", family_id="family-b"),
            _case("3CCC", family_id="family-c"),
        )
    )
    records = {
        "1AAA": adapt_biovoid_pockets("1AAA", [{"center": [0.0, 0.0, 0.0]}]),
        "2BBB": adapt_biovoid_pockets("2BBB", [{"center": [0.0, 0.0, 0.0]}]),
        "3CCC": adapt_biovoid_pockets("3CCC", [{"center": [20.0, 0.0, 0.0]}]),
    }
    truths = {
        "1AAA:site-1": _truth("1AAA"),
        "2BBB:site-1": _truth("2BBB"),
        "3CCC:site-1": _truth("3CCC"),
    }

    first = evaluate_split(
        detector="biovoid_static",
        split="development",
        records=records,
        ground_truth=truths,
        manifest=manifest,
        protocol=_frozen_protocol(),
    )
    second = evaluate_split(
        detector="biovoid_static",
        split="development",
        records=records,
        ground_truth=truths,
        manifest=manifest,
        protocol=_frozen_protocol(),
    )

    assert first["bootstrap"] == second["bootstrap"]
    assert first["bootstrap"]["resampling_unit"] == "family"
    assert first["bootstrap"]["replicates"] == 1000
    lower, upper = first["bootstrap"]["top_k_dcc_recall_95_ci"][3]
    assert lower <= first["top_k_dcc_recall"][3] <= upper


def test_all_detector_adapters_share_the_blind_schema() -> None:
    from src.evaluator_format import (
        adapt_biovoid_motion_pockets,
        adapt_biovoid_pockets,
        adapt_fpocket_pockets,
        adapt_p2rank_rows,
        failed_record,
        unavailable_record,
    )

    records = [
        adapt_biovoid_pockets("TEST", [{"center": [0, 0, 0]}]),
        adapt_biovoid_motion_pockets(
            "TEST",
            [{"motion_pocket_id": "M-1", "center": [0, 0, 0]}],
        ),
        adapt_fpocket_pockets("TEST", [{"id": 1, "center": [0, 0, 0]}]),
        adapt_p2rank_rows(
            "TEST",
            [{"rank": 1, "center_x": 0, "center_y": 0, "center_z": 0}],
        ),
        unavailable_record("fpocket", "TEST", "tool_missing"),
        failed_record("p2rank", "TEST", "parse_failed"),
    ]

    assert {record.detector for record in records} == {
        "biovoid_static",
        "biovoid_motion",
        "fpocket",
        "p2rank",
    }
    assert all(record.schema_version == "pocket-evaluator-input-v1" for record in records)
    assert records[-2].status == "unavailable"
    assert records[-1].status == "failed"


def test_sealed_holdout_ledger_requires_authorization_and_opens_once(
    tmp_path: Path,
) -> None:
    from src.benchmark_v1 import (
        BenchmarkManifest,
        SealedHoldoutError,
        SealedHoldoutLedger,
        evaluate_split,
    )
    from src.evaluator_format import adapt_biovoid_pockets

    manifest = BenchmarkManifest((_case("1AAA", split="sealed"),))
    ledger = SealedHoldoutLedger(tmp_path / "sealed-ledger.json")
    records = {
        "1AAA": adapt_biovoid_pockets(
            "1AAA",
            [{"rank": 1, "center": [0.0, 0.0, 0.0]}],
        )
    }
    truths = {"1AAA:site-1": _truth("1AAA")}

    with pytest.raises(SealedHoldoutError, match="ledger"):
        evaluate_split(
            detector="biovoid_static",
            split="sealed",
            records=records,
            ground_truth=truths,
            manifest=manifest,
            protocol=_frozen_protocol(),
        )

    with pytest.raises(SealedHoldoutError, match="authorization"):
        ledger.authorize_once(
            protocol=_frozen_protocol(),
            manifest=manifest,
            explicit_user_authorization=False,
        )

    payload = ledger.authorize_once(
        protocol=_frozen_protocol(),
        manifest=manifest,
        explicit_user_authorization=True,
    )
    assert payload["opened"] is True
    summary = evaluate_split(
        detector="biovoid_static",
        split="sealed",
        records=records,
        ground_truth=truths,
        manifest=manifest,
        protocol=_frozen_protocol(),
        sealed_ledger_path=ledger.path,
    )
    assert summary["denominator"] == 1

    with pytest.raises(SealedHoldoutError, match="already"):
        ledger.authorize_once(
            protocol=_frozen_protocol(),
            manifest=manifest,
            explicit_user_authorization=True,
        )


def _cache_identity(policy: str):
    from src.cache import CacheIdentity

    return CacheIdentity(
        source_identifier="TEST",
        raw_input_sha256="1" * 64,
        prepared_structure_sha256="2" * 64,
        preparation_config_sha256="3" * 64,
        detector_config_sha256="4" * 64,
        motion_config_sha256="5" * 64,
        model_sha256="6" * 64,
        code_identity_sha256="7" * 64,
        environment_identity_sha256="8" * 64,
        benchmark_cache_policy=policy,
    )


def test_benchmark_cache_policy_enforces_disabled_and_sealed_read_only(
    tmp_path: Path,
) -> None:
    from src.cache import AnalysisCache, CacheWriteError

    cache = AnalysisCache(tmp_path / "cache")
    disabled = _cache_identity("disabled")
    sealed = _cache_identity("sealed_read_only")
    development = _cache_identity("development_only")

    assert cache.get(disabled) is None
    assert cache.last_event["status"] == "disabled"
    with pytest.raises(CacheWriteError):
        cache.put(disabled, {"result": 1})
    with pytest.raises(CacheWriteError):
        cache.put(sealed, {"result": 1})
    cache.put(development, {"result": 1})
    assert cache.get(development) == {"result": 1}


def test_safe_16gb_preflight_accepts_bounded_serial_plan() -> None:
    from src.benchmark_v1 import (
        BenchmarkResourceRequest,
        preflight_benchmark_resources,
    )

    result = preflight_benchmark_resources(
        BenchmarkResourceRequest(
            case_count=20,
            batch_size=5,
            analysis_workers=1,
            maximum_ca_atoms=500,
            include_motion=True,
            motion_modes=4,
            samples_per_mode=2,
        ),
        available_memory_bytes=12 * 1024**3,
    )

    assert result["safe_to_start_bounded_pilot"] is True
    assert result["full_benchmark_approved"] is False
    assert result["recommended_workers"] == 1
    assert result["checkpoint_required"] is True
    assert result["runtime_estimate"] == "requires_bounded_pilot"
    assert result["memory_estimate_scope"] == "nma_hessian_only"


@pytest.mark.parametrize(
    "request_kwargs,available_memory",
    [
        (
            {
                "case_count": 20,
                "batch_size": 11,
                "analysis_workers": 1,
                "maximum_ca_atoms": 500,
                "include_motion": False,
            },
            12 * 1024**3,
        ),
        (
            {
                "case_count": 20,
                "batch_size": 5,
                "analysis_workers": 2,
                "maximum_ca_atoms": 500,
                "include_motion": True,
                "motion_modes": 4,
                "samples_per_mode": 2,
            },
            12 * 1024**3,
        ),
        (
            {
                "case_count": 20,
                "batch_size": 5,
                "analysis_workers": 1,
                "maximum_ca_atoms": 500,
                "include_motion": False,
            },
            2 * 1024**3,
        ),
    ],
)
def test_safe_16gb_preflight_rejects_unsafe_plans(
    request_kwargs: dict,
    available_memory: int,
) -> None:
    from src.benchmark_v1 import (
        BenchmarkResourceRequest,
        preflight_benchmark_resources,
    )
    from src.resources import ResourceLimitError

    with pytest.raises(ResourceLimitError):
        preflight_benchmark_resources(
            BenchmarkResourceRequest(**request_kwargs),
            available_memory_bytes=available_memory,
        )


@pytest.mark.parametrize(
    "script",
    [
        "build_blind_holdout_set.py",
        "prepare_benchmark_set.py",
        "repair_benchmark_centers.py",
    ],
)
def test_historical_benchmark_scripts_are_disabled_by_default(script: str) -> None:
    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(project_root / "scripts" / script)],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 2
    assert "[DISABLED]" in result.stdout

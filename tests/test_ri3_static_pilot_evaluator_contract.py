from __future__ import annotations

from scripts.evaluate_ri3_static_pilot import _diagnostic_summary, build_pilot_evaluator_scope
from scripts.run_ri3_static_pilot import _stable_hash
from src.benchmark_v1 import phase6_frozen_protocol_v1
from src.cryptobench_adapter import build_target_sites
from src.cryptobench_manifest import _opaque_case_id


def _record() -> dict:
    return {
        "uniprot_id": "P12345",
        "holo_pdb_id": "9ZZZ",
        "holo_chain": "A",
        "apo_chain": "A",
        "ligand": "ATP",
        "ligand_index": "1",
        "ligand_chain": "A",
        "apo_pocket_selection": ["A_10", "A_11", "A_12"],
        "holo_pocket_selection": ["A_10", "A_11", "A_12"],
        "pRMSD": 2.1,
        "is_main_holo_structure": True,
    }


def test_evaluator_scope_reuses_pilot_structure_boundary() -> None:
    dataset = {"1abc": [_record()]}
    site = build_target_sites(dataset, dataset_id="cryptobench", split="development")[0]
    opaque_case_id = _opaque_case_id(site)
    pilot_manifest = {
        "schema_version": "biovoid-ri3-target-blind-static-pilot-manifest-v1",
        "manifest_kind": "metadata_only_target_blind_static_pilot",
        "materialization_status": "prepared_local_only",
        "dataset_id": "cryptobench",
        "snapshot_id": "cryptobench-osf-pz4a9-test",
        "split": "development",
        "protocol": phase6_frozen_protocol_v1().to_manifest(),
        "scope": {
            "structure_ids": ["1ABC"],
            "max_structures": 10,
            "selection_rule": "test",
            "structure_ids_sha256": _stable_hash(["1ABC"]),
        },
        "structures": [
            {
                "structure_id": "1ABC",
                "prepared_path": "data/runtime/ri3/1abc/prepared_detector.pdb",
                "prepared_structure_sha256": "a" * 64,
                "preparation_config_sha256": "b" * 64,
                "preparation_report_sha256": "c" * 64,
                "protein_atom_count": 100,
                "protein_residue_count": 10,
                "warnings": [],
            }
        ],
        "cases": [
            {
                "case_id": opaque_case_id,
                "structure_id": "1ABC",
                "family_id": site.family_id,
                "split": "development",
                "dataset_snapshot_id": "cryptobench-osf-pz4a9-test",
            }
        ],
        "structure_count": 1,
        "case_count": 1,
        "detector_boundary": {
            "target_blind": True,
            "evaluator_fields_in_manifest": False,
            "detector_receives": [],
        },
    }
    pilot_manifest["manifest_sha256"] = _stable_hash(
        {key: value for key, value in pilot_manifest.items() if key != "manifest_sha256"}
    )

    benchmark_manifest, sites = build_pilot_evaluator_scope(
        pilot_manifest=pilot_manifest,
        dataset=dataset,
    )

    assert len(benchmark_manifest.cases) == 1
    assert tuple(sites) == (opaque_case_id,)
    assert sites[opaque_case_id].case_id == site.case_id
    assert sites[opaque_case_id].apo_pdb_id == "1ABC"


def test_diagnostic_summary_accepts_dataclass_integer_hit_keys() -> None:
    report = {
        "records": {
            "case": {
                "status": "completed_ground_truth",
                "case_evaluation": {
                    "top_k_dcc_hits": {1: True, 3: False, 5: True},
                    "top_k_dca_hits": {1: False, 3: True, 5: True},
                },
            }
        }
    }

    summary = _diagnostic_summary(report)

    assert summary["ground_truth_available_case_count"] == 1
    assert summary["top_k_dcc_recall_on_available_ground_truth"] == {
        "1": 1.0,
        "3": 0.0,
        "5": 1.0,
    }
    assert summary["top_k_dca_recall_on_available_ground_truth"] == {
        "1": 0.0,
        "3": 1.0,
        "5": 1.0,
    }

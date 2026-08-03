"""Validate the source-only RI-1 research contract without downloading data."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
LOCAL_PRIVATE = ROOT / "local-private"
LOCK_PATH = LOCAL_PRIVATE / "research" / "ri-1-lock-v1.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.benchmark_v1 import phase6_frozen_protocol_v1


def fail(message: str) -> None:
    raise SystemExit(f"RI-1 contract: FAIL - {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def main() -> int:
    required_files = (
        LOCAL_PRIVATE / "specs" / "benchmark-protocol-v2.md",
        LOCAL_PRIVATE / "specs" / "baseline-lock-v1.md",
        LOCAL_PRIVATE / "specs" / "benchmark-case-manifest-v1.md",
        LOCK_PATH,
    )
    for path in required_files:
        require(path.is_file(), f"missing required file: {path.relative_to(ROOT)}")

    try:
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON lock: {exc}")

    require(lock["schema_version"] == "biovoid-ri1-lock-v1", "unexpected lock schema")
    require(lock["status"] == "locked_for_protocol_and_data_access", "lock is not RI-1 status")
    require(lock["sealed_evaluation_authorized"] is False, "sealed evaluation is authorized")

    dataset = lock["dataset"]
    require(dataset["snapshot_id"] == "cryptobench-osf-pz4a9-20260801", "dataset snapshot drift")
    require(dataset["osf_node_id"] == "pz4a9", "unexpected OSF node")
    require(dataset["raw_structures_in_repository"] is False, "raw structures are in repository")
    require(dataset["generated_outputs_in_repository"] is False, "generated outputs are in repository")
    require(
        dataset["structure_archive"]["file_id"] == "672a0171eae0bff252ba9ea3",
        "structure archive file ID drift",
    )
    require(
        dataset["structure_archive"]["sha256"]
        == "8d15f897bfdfdf61c7d97a29f5f6ca2c5e03d73d8fb89be7da5bbc245cf56ae4",
        "structure archive hash drift",
    )
    require(dataset["structure_archive"]["size"] == 1145203712, "structure archive size drift")
    require(
        dataset["metadata_files"]["dataset.json"]["sha256"]
        == "79519369a1d32b63efd86b907013cacb5e02a68e4d711cdde20a23cdfe16ba7c",
        "dataset metadata hash drift",
    )
    require(
        dataset["metadata_files"]["folds.json"]["sha256"]
        == "ced97a50b55504007216165167a1b3995312434ee50f7f93f8728fca3c6ac67d",
        "fold metadata hash drift",
    )

    endpoints = lock["endpoints"]
    require(endpoints["primary"] == "top_3_dcc_localization_recall", "DCC primary endpoint drift")
    require(endpoints["dcc_tolerance_angstrom"] == 4.0, "DCC tolerance drift")
    require(endpoints["dca_tolerance_angstrom"] == 4.0, "DCA tolerance drift")
    require("top_3_dca_localization_recall" in endpoints["secondary"], "DCA is not secondary")
    require(endpoints["rank_scope"] == [1, 3, 5], "rank scope drift")

    preparation = lock["preparation"]
    require(
        preparation["profile_id"] == "cryptobench-apo-file-v1",
        "benchmark preparation profile drift",
    )
    require(
        preparation["representation"] == "dataset_apo_coordinate_file",
        "benchmark source representation drift",
    )
    require(
        preparation["assembly_policy"] == "no_post_download_assembly_reconstruction",
        "implicit assembly conversion enabled",
    )

    baselines = lock["baselines"]
    require(
        baselines["fpocket"]["commit"] == "4bb0d8447f62fee77e2c3c29f54b5fcaf5e2c066",
        "fpocket pin drift",
    )
    require(
        baselines["p2rank"]["commit"] == "9808a7723be9a94e2ffc21ab5f724cb6ae4ba01e",
        "P2Rank pin drift",
    )
    require(
        baselines["pocketminer"]["commit"] == "187062df3c94127e991669768009141a08fd5d8b",
        "PocketMiner pin drift",
    )

    denominator = lock["denominator"]
    require(denominator["primary_recall_denominator"] == "all_eligible_cases", "denominator drift")
    require(denominator["silent_case_drop"] is False, "silent case drop is enabled")
    require(preparation["holo_or_ligand_visible_to_detector"] is False, "detector leakage")
    require(lock["resource_policy"]["bulk_crawl"] == "disabled", "bulk crawl is enabled")
    runtime_manifest = phase6_frozen_protocol_v1().to_manifest()
    require(
        lock["runtime_contract"]["manifest"] == runtime_manifest,
        "executable protocol differs from runtime lock",
    )

    print("RI-1 contract: PASS")
    print(f"  Snapshot: {dataset['snapshot_id']}")
    print(f"  Primary: {endpoints['primary']} @ {endpoints['dcc_tolerance_angstrom']} A")
    print("  Sealed evaluation: blocked")
    return 0


if __name__ == "__main__":
    sys.exit(main())

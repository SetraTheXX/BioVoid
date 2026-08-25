"""Materialize evaluator-only labels for the pre-sealed held-out rows.

The validation and temporal/test apo structures must already have a completed
target-blind static artifact before this command is run. It opens only the
private holo/contact arm, applies the same uniformly declared PocketMiner v2
alignment policy as development, and never reruns or feeds the detector.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.materialize_pocketminer_development_labels import (  # noqa: E402
    LABEL_SOURCE,
    POCKETMINER_ALIGNMENT_POLICY,
    _read_json,
    _stable_hash,
    _write_report,
    build_pair_payload_for_splits,
)
from scripts.materialize_target_family_contact_labels import (  # noqa: E402
    MAX_DISK_BYTES,
    _enforce_disk_quota,
    _run_pair,
    build_contact_label_report,
)


DEFAULT_COHORT = (
    REPO_ROOT / "local-private/research/ranking-study-source-catalog/pocketminer-v1/"
    "pocketminer-cohort-v1.json"
)
DEFAULT_STATIC_RUN = (
    REPO_ROOT / "data/runtime/ranking-study/pocketminer-v1/heldout-static-v1/"
    "pocketminer-heldout-static-v1.json"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT / "local-private/research/ranking-study-source-catalog/pocketminer-v1/"
    "heldout-labels-v2"
)
DEFAULT_REPORT = DEFAULT_OUTPUT_ROOT / "pocketminer-heldout-labels-v2.json"
DEFAULT_SOURCE_CACHE = (
    REPO_ROOT / "data/runtime/ranking-study/pocketminer-v1/heldout-materialization-v1/raw_apo"
)
HELDOUT_SPLITS = frozenset({"validation", "test"})
EXPECTED_CASES = 4


class PocketMinerHoldoutLabelError(RuntimeError):
    """Raised when the held-out evaluator-only label contract is invalid."""


def materialize_pocketminer_holdout_labels(
    *,
    cohort_path: Path = DEFAULT_COHORT,
    static_run_path: Path = DEFAULT_STATIC_RUN,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    report_path: Path = DEFAULT_REPORT,
    source_cache: Path = DEFAULT_SOURCE_CACHE,
    max_disk_bytes: int = MAX_DISK_BYTES,
    allow_network: bool = False,
) -> dict[str, Any]:
    if not allow_network:
        raise PocketMinerHoldoutLabelError(
            "held-out label materialization requires --allow-network"
        )
    static_run = _read_json(static_run_path.resolve())
    if (
        static_run.get("status") != "completed"
        or static_run.get("retention") != "full_final_pocket_list"
    ):
        raise PocketMinerHoldoutLabelError(
            "held-out static run is not a completed full-list artifact"
        )
    if static_run.get("boundary", {}).get("target_blind") is not True:
        raise PocketMinerHoldoutLabelError("held-out static run target-blind boundary is invalid")
    if output_root.exists():
        raise PocketMinerHoldoutLabelError(
            f"refusing to overwrite existing label output: {output_root}"
        )
    cohort = _read_json(cohort_path.resolve())
    pairs = build_pair_payload_for_splits(
        cohort, splits=HELDOUT_SPLITS, expected_cases=EXPECTED_CASES
    )
    static_case_ids = {
        str(case.get("case_id"))
        for case in static_run.get("records", [])
        if isinstance(case, Mapping)
    }
    if {str(pair["case_id"]) for pair in pairs} != static_case_ids:
        raise PocketMinerHoldoutLabelError("held-out static and evaluator case sets differ")
    output_root.resolve().mkdir(parents=True, exist_ok=False)
    report = build_contact_label_report(
        family_id=str(cohort.get("family_id") or "POCKETMINER-NOVEL-CRYPTIC"),
        pairs=pairs,
        output_root=output_root.resolve(),
        max_cases=EXPECTED_CASES,
        max_disk_bytes=max_disk_bytes,
        alignment_policy=POCKETMINER_ALIGNMENT_POLICY,
    )
    report.update(
        {
            "schema_version": "biovoid-pocketminer-heldout-labels-v2",
            "label_source": LABEL_SOURCE,
            "source_dataset_id": "pocketminer-novel-cryptic-pocket-set-v1",
            "cohort_manifest_sha256": _stable_hash(cohort),
            "static_run_sha256": _stable_hash(static_run),
            "heldout_only": True,
            "development_only": False,
            "evaluator_only": True,
            "detector_started": False,
            "benchmark_started": False,
            "motion_enabled": False,
            "ml_training_started": False,
        }
    )
    report["execution"]["source_cache"] = str(source_cache)
    report["execution"]["workers"] = 1
    report["status"] = "running"
    _write_report(report_path.resolve(), report)
    source_cache.resolve().mkdir(parents=True, exist_ok=True)
    for pair in pairs:
        record = _run_pair(
            pair,
            output_root=output_root.resolve(),
            source_cache=source_cache.resolve(),
            max_disk_bytes=max_disk_bytes,
            alignment_policy=POCKETMINER_ALIGNMENT_POLICY,
            preferred_apo_chain_id=pair.get("apo_chain_id") or None,
            preferred_ligand_chain_id=pair.get("holo_chain_id") or None,
            provenance_label="pocketminer-rcsb-contact-label-only-v2",
            run_id_suffix="pocketminer-heldout-contact-label-v2",
        )
        report["records"][pair["case_id"]] = record
        if record.get("status") == "completed_ground_truth":
            report["counts"]["completed"] += 1
        else:
            report["counts"]["failed"] += 1
        report["execution"]["coordinates_downloaded"] = True
        report["coordinates_downloaded"] = True
        _enforce_disk_quota(output_root.resolve(), max_disk_bytes)
        _write_report(report_path.resolve(), report)
    report["status"] = (
        "completed_review_required"
        if report["counts"]["completed"] == len(pairs)
        else "completed_with_failures"
    )
    report["execution"]["final_disk_bytes"] = _enforce_disk_quota(
        output_root.resolve(), max_disk_bytes
    )
    report["execution"]["detector_started"] = False
    report["execution"]["benchmark_started"] = False
    report["execution"]["ml_training_started"] = False
    _write_report(report_path.resolve(), report)
    print(
        f"PocketMiner held-out labels: status={report['status']} "
        f"completed={report['counts']['completed']} failed={report['counts']['failed']}"
    )
    print(f"label report: {report_path}")
    print("detector/benchmark/NMA/ML started: no")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    parser.add_argument("--static-run", type=Path, default=DEFAULT_STATIC_RUN)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--source-cache", type=Path, default=DEFAULT_SOURCE_CACHE)
    parser.add_argument("--max-disk-bytes", type=int, default=MAX_DISK_BYTES)
    parser.add_argument("--allow-network", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        materialize_pocketminer_holdout_labels(
            cohort_path=args.cohort,
            static_run_path=args.static_run,
            output_root=args.output_root,
            report_path=args.report,
            source_cache=args.source_cache,
            max_disk_bytes=args.max_disk_bytes,
            allow_network=args.allow_network,
        )
    except (PocketMinerHoldoutLabelError, OSError, ValueError) as exc:
        print(f"PocketMiner held-out label error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

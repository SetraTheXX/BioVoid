"""Materialize evaluator-only holo ligand labels for development cases.

The PocketMiner source supplies curated apo--holo/ligand provenance. This
bounded command downloads only the six pre-sealed development pairs, derives
aligned holo ligand geometry in private ignored storage, and never passes holo
coordinates or labels to the static detector. Validation/test rows, NMA,
external baselines, and ML remain sealed.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.materialize_target_family_contact_labels import (  # noqa: E402
    MAX_DISK_BYTES,
    _enforce_disk_quota,
    _run_pair,
    build_contact_label_report,
)
from src.ground_truth_alignment import AlignmentPolicy  # noqa: E402


DEFAULT_COHORT = (
    REPO_ROOT / "local-private/research/ranking-study-source-catalog/pocketminer-v1/"
    "pocketminer-cohort-v1.json"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT / "local-private/research/ranking-study-source-catalog/pocketminer-v1/"
    "development-labels-v2"
)
DEFAULT_REPORT = DEFAULT_OUTPUT_ROOT / "pocketminer-development-labels-v2.json"
DEFAULT_SOURCE_CACHE = (
    REPO_ROOT / "data/runtime/ranking-study/pocketminer-v1/development-materialization-v1/raw_apo"
)
MAX_DEVELOPMENT_CASES = 6
LABEL_SOURCE = "holo_ligand_contact_v2"
POCKETMINER_ALIGNMENT_POLICY = AlignmentPolicy(
    policy_version="ground-truth-alignment-pocketminer-v2",
    ambiguous_sequence_policy="structural_fit",
)


class PocketMinerDevelopmentLabelError(RuntimeError):
    """Raised when the evaluator-only development label boundary is invalid."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PocketMinerDevelopmentLabelError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PocketMinerDevelopmentLabelError(f"JSON must be an object: {path}")
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _pdb_id(value: Any, field: str) -> str:
    normalized = str(value or "").strip().upper()
    if re.fullmatch(r"[A-Z0-9]{4}", normalized) is None:
        raise PocketMinerDevelopmentLabelError(f"{field} must be a four-character PDB ID")
    return normalized


def build_development_pair_payload(
    cohort: Mapping[str, Any], *, expected_cases: int = MAX_DEVELOPMENT_CASES
) -> list[dict[str, Any]]:
    """Build deterministic private development pair inputs."""

    return build_pair_payload_for_splits(
        cohort, splits=frozenset({"development"}), expected_cases=expected_cases
    )


def build_pair_payload_for_splits(
    cohort: Mapping[str, Any],
    *,
    splits: frozenset[str],
    expected_cases: int,
) -> list[dict[str, Any]]:
    """Build deterministic private pair inputs for pre-sealed split rows."""

    raw_cases = cohort.get("cases")
    if not isinstance(raw_cases, list):
        raise PocketMinerDevelopmentLabelError("cohort cases are missing")
    development = [
        case for case in raw_cases if isinstance(case, Mapping) and case.get("split") in splits
    ]
    if len(development) != expected_cases:
        raise PocketMinerDevelopmentLabelError(
            f"expected {expected_cases} development cases, found {len(development)}"
        )
    pairs: list[dict[str, Any]] = []
    for case in sorted(development, key=lambda item: str(item.get("apo_structure_id"))):
        ligand_code = str(case.get("ligand_code") or "").strip()
        components = []
        seen: set[str] = set()
        for value in re.split(r"[,;]", ligand_code):
            comp_id = value.strip().upper()
            if comp_id and comp_id not in seen:
                components.append({"comp_id": comp_id})
                seen.add(comp_id)
        if not components:
            raise PocketMinerDevelopmentLabelError(
                f"development case lacks an independent ligand code: {case.get('case_id')}"
            )
        pairs.append(
            {
                "case_id": str(case.get("case_id")),
                "family_id": str(case.get("family_id") or "POCKETMINER-NOVEL-CRYPTIC"),
                "uniprot_group": str(case.get("uniprot_group_id") or ""),
                "sequence_cluster_id": str(case.get("sequence_cluster_id") or ""),
                "apo_pdb_id": _pdb_id(case.get("apo_structure_id"), "case.apo_structure_id"),
                "holo_pdb_id": _pdb_id(case.get("holo_structure_id"), "case.holo_structure_id"),
                "apo_chain_id": str(case.get("apo_chain_id") or ""),
                "holo_chain_id": str(case.get("holo_chain_id") or ""),
                "holo_components": components,
                "label_source": LABEL_SOURCE,
                "source_dataset_id": str(case.get("source_dataset_id") or ""),
            }
        )
    return pairs


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    payload = dict(report)
    payload["report_sha256"] = _stable_hash(
        {key: value for key, value in payload.items() if key != "report_sha256"}
    )
    _write_json(path, payload)


def materialize_pocketminer_development_labels(
    *,
    cohort_path: Path = DEFAULT_COHORT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    report_path: Path = DEFAULT_REPORT,
    source_cache: Path = DEFAULT_SOURCE_CACHE,
    max_disk_bytes: int = MAX_DISK_BYTES,
    allow_network: bool = False,
) -> dict[str, Any]:
    if not allow_network:
        raise PocketMinerDevelopmentLabelError(
            "development label materialization requires --allow-network"
        )
    if output_root.exists():
        raise PocketMinerDevelopmentLabelError(
            f"refusing to overwrite existing label output: {output_root}"
        )
    cohort = _read_json(cohort_path.resolve())
    pairs = build_development_pair_payload(cohort)
    output_root.resolve().mkdir(parents=True, exist_ok=False)
    report = build_contact_label_report(
        family_id=str(cohort.get("family_id") or "POCKETMINER-NOVEL-CRYPTIC"),
        pairs=pairs,
        output_root=output_root.resolve(),
        max_cases=MAX_DEVELOPMENT_CASES,
        max_disk_bytes=max_disk_bytes,
        alignment_policy=POCKETMINER_ALIGNMENT_POLICY,
    )
    report.update(
        {
            "source_dataset_id": "pocketminer-novel-cryptic-pocket-set-v1",
            "cohort_manifest_sha256": _stable_hash(cohort),
            "development_only": True,
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
            run_id_suffix="pocketminer-contact-label-v2",
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
        f"PocketMiner development labels: status={report['status']} "
        f"completed={report['counts']['completed']} failed={report['counts']['failed']}"
    )
    print(f"label report: {report_path}")
    print(f"disk_bytes={report['execution'].get('final_disk_bytes', 0)}")
    print("detector/benchmark/NMA/ML started: no")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--source-cache", type=Path, default=DEFAULT_SOURCE_CACHE)
    parser.add_argument("--max-disk-bytes", type=int, default=MAX_DISK_BYTES)
    parser.add_argument("--allow-network", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        materialize_pocketminer_development_labels(
            cohort_path=args.cohort,
            output_root=args.output_root,
            report_path=args.report,
            source_cache=args.source_cache,
            max_disk_bytes=args.max_disk_bytes,
            allow_network=args.allow_network,
        )
    except (PocketMinerDevelopmentLabelError, OSError, ValueError) as exc:
        print(f"PocketMiner development label error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

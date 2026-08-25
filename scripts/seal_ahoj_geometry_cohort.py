"""Seal a target-blind full-structure AHoJ cohort after metadata PASS.

The private cohort keeps evaluator-side apo/holo/ligand provenance.  The
detector manifest contains only apo structure IDs, split IDs, and immutable
metadata hashes; it deliberately does not select one chain because BioVoid's
canonical input is the prepared full-heavy-atom structure.
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

from scripts.resolve_ahoj_geometry_metadata import (  # noqa: E402
    AhojMetadataResolutionError,
    _read_json,
    _write_json,
)

SOURCE_REPORT = (
    REPO_ROOT / "local-private/research/geometry-data-source-catalog/ahoj-v1/"
    "ahoj-geometry-metadata-resolution-v1.json"
)
DEFAULT_PRIVATE_OUTPUT = (
    REPO_ROOT / "local-private/research/geometry-data-source-catalog/ahoj-v1/"
    "ahoj-geometry-cohort-v1.json"
)
DEFAULT_DETECTOR_OUTPUT = (
    REPO_ROOT / "data/runtime/target-family/cohort-ahoj-geometry-v1/"
    "ahoj-geometry-detector-manifest-v1.json"
)
FAMILY_ID = "AHOJ-GEOMETRY-V1"
TEMPORAL_SPLIT = "temporal"
TARGET_COUNTS = {"development": 6, "validation": 2, TEMPORAL_SPLIT: 2}
PDB_PATTERN = re.compile(r"^[A-Z0-9]{4}$")
FORBIDDEN_DETECTOR_TOKENS = ("holo", "ligand", "evaluator", "ground_truth", "bio_score")


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _pdb_id(value: Any, field: str) -> str:
    text = str(value or "").strip().upper()
    if PDB_PATTERN.fullmatch(text) is None:
        raise AhojMetadataResolutionError(f"{field} must be a four-character PDB ID")
    return text


def _required_case_map(
    resolution: Mapping[str, Any],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, str]]:
    if resolution.get("decision") != "PASS":
        raise AhojMetadataResolutionError("AHoJ resolution must be PASS before cohort sealing")
    label_policy = resolution.get("label_policy")
    if not isinstance(label_policy, Mapping) or label_policy.get("accepted") is not True:
        raise AhojMetadataResolutionError("external AHoJ/BioLiP2 label policy is not accepted")
    cases = resolution.get("cases")
    assignments = resolution.get("allocation", {}).get("assignments")
    if not isinstance(cases, list) or not isinstance(assignments, list):
        raise AhojMetadataResolutionError("resolution cases or allocation is missing")
    by_case_id = {str(case.get("case_id")): case for case in cases if isinstance(case, Mapping)}
    split_by_case: dict[str, str] = {}
    for assignment in assignments:
        if not isinstance(assignment, Mapping):
            raise AhojMetadataResolutionError("allocation assignment must be an object")
        case_id = str(assignment.get("case_id", ""))
        split = str(assignment.get("split", ""))
        if case_id not in by_case_id or split not in TARGET_COUNTS:
            raise AhojMetadataResolutionError("allocation assignment references an invalid case")
        if case_id in split_by_case:
            raise AhojMetadataResolutionError("allocation contains a duplicate case")
        split_by_case[case_id] = split
    if {
        split: sum(value == split for value in split_by_case.values()) for split in TARGET_COUNTS
    } != TARGET_COUNTS:
        raise AhojMetadataResolutionError("allocation is not exactly 6/2/2")
    return by_case_id, split_by_case


def build_ahoj_cohort_payload(resolution: Mapping[str, Any]) -> dict[str, Any]:
    by_case_id, split_by_case = _required_case_map(resolution)
    private_cases: list[dict[str, Any]] = []
    seen_apo: set[str] = set()
    seen_holo: set[str] = set()
    seen_uniprot: dict[str, str] = {}
    seen_cluster: dict[str, str] = {}
    for case_id in sorted(split_by_case):
        case = by_case_id[case_id]
        split = split_by_case[case_id]
        apo_id = _pdb_id(case.get("apo_structure_id"), "case.apo_structure_id")
        holo_id = _pdb_id(case.get("holo_structure_id"), "case.holo_structure_id")
        if apo_id in seen_apo or holo_id in seen_holo or apo_id == holo_id:
            raise AhojMetadataResolutionError("cohort structure IDs must be unique")
        seen_apo.add(apo_id)
        seen_holo.add(holo_id)
        uniprot = str(case.get("uniprot_id", "")).strip().upper()
        cluster = str(case.get("sequence_cluster_id", "")).strip()
        if not uniprot or not cluster:
            raise AhojMetadataResolutionError("cohort case lacks UniProt or sequence cluster")
        if uniprot in seen_uniprot and seen_uniprot[uniprot] != split:
            raise AhojMetadataResolutionError("UniProt group crosses cohort splits")
        if cluster in seen_cluster and seen_cluster[cluster] != split:
            raise AhojMetadataResolutionError("sequence cluster crosses cohort splits")
        seen_uniprot[uniprot] = split
        seen_cluster[cluster] = split
        apo_entity = case.get("apo_entity")
        holo_entity = case.get("holo_entity")
        if not isinstance(apo_entity, Mapping) or not isinstance(holo_entity, Mapping):
            raise AhojMetadataResolutionError("resolved entity metadata is missing")
        apo_chain_ids = apo_entity.get("chain_ids")
        ligand_chain_ids = case.get("holo_ligand_chain_ids")
        if not isinstance(apo_chain_ids, list) or not apo_chain_ids:
            raise AhojMetadataResolutionError("apo full-structure chain metadata is missing")
        if not isinstance(ligand_chain_ids, list) or not ligand_chain_ids:
            raise AhojMetadataResolutionError("holo ligand chain metadata is missing")
        private_cases.append(
            {
                "case_id": case_id,
                "family_id": FAMILY_ID,
                "split": split,
                "apo_structure_id": apo_id,
                "holo_structure_id": holo_id,
                "apo_chain_ids": sorted(str(value).upper() for value in apo_chain_ids),
                "holo_ligand_chain_ids": sorted(str(value).upper() for value in ligand_chain_ids),
                "uniprot_group_id": uniprot,
                "sequence_cluster_id": cluster,
                "apo_release_date": case.get("apo_release_date"),
                "holo_release_date": case.get("holo_release_date"),
                "ligand_code": str(case.get("ligand_code", "")).upper(),
                "label_source": "independent_annotation_v1",
                "label_source_detail": "AHoJ-DB precomputed BioLiP2 apo/holo site assignment",
                "label_policy_version": "ahoj-biolip2-site-assignment-v1",
            }
        )
    return {
        "schema_version": "biovoid-ahoj-geometry-cohort-v1",
        "manifest_kind": "private_apo_holo_evaluator_cohort",
        "family_id": FAMILY_ID,
        "source_catalog_id": "ahoj-db-v1-subset1",
        "source_resolution_sha256": _stable_hash(resolution),
        "split_strategy": "sequence_cluster_temporal_holdout_ahoj_v1",
        "development_cutoff": resolution["allocation"]["development_cutoff"],
        "temporal_cutoff": resolution["allocation"]["temporal_cutoff"],
        "coordinates_downloaded": False,
        "detector_started": False,
        "evaluator_started": False,
        "nma_started": False,
        "ml_training_started": False,
        "cases": private_cases,
        "cohort_sha256": None,
    }


def build_target_blind_detector_manifest(cohort: Mapping[str, Any]) -> dict[str, Any]:
    cases = cohort.get("cases")
    if not isinstance(cases, list) or len(cases) != 10:
        raise AhojMetadataResolutionError("detector manifest requires exactly 10 sealed cases")
    redacted_cases = []
    for case in cases:
        if not isinstance(case, Mapping):
            raise AhojMetadataResolutionError("cohort case must be an object")
        split = str(case.get("split", ""))
        detector_split = "test" if split == TEMPORAL_SPLIT else split
        redacted_cases.append(
            {
                "case_id": str(case["case_id"]),
                "structure_id": _pdb_id(case["apo_structure_id"], "case.apo_structure_id"),
                "family_id": FAMILY_ID,
                "split": detector_split,
            }
        )
    manifest: dict[str, Any] = {
        "schema_version": "biovoid-ahoj-geometry-detector-manifest-v1",
        "manifest_kind": "target_blind_apo_full_structure_manifest",
        "materialization_status": "metadata_only",
        "family_id": FAMILY_ID,
        "source_catalog_id": str(cohort["source_catalog_id"]),
        "source_resolution_sha256": str(cohort["source_resolution_sha256"]),
        "split_strategy": "sequence_cluster_temporal_holdout_ahoj_v1",
        "temporal_cutoff": str(cohort["temporal_cutoff"]),
        "constraints": {
            "case_count": len(redacted_cases),
            "max_case_count": 10,
            "analysis_workers": 1,
            "include_motion": False,
            "safe_profile": "safe-16gb",
            "full_heavy_atom_structure": True,
        },
        "boundary": "apo_full_structure_only_v1",
        "cases": sorted(redacted_cases, key=lambda case: case["case_id"]),
        "manifest_sha256": None,
    }
    serialized = json.dumps(manifest, ensure_ascii=True, sort_keys=True).casefold()
    if any(token in serialized for token in FORBIDDEN_DETECTOR_TOKENS):
        raise AhojMetadataResolutionError("detector manifest contains evaluator-side metadata")
    manifest["manifest_sha256"] = _stable_hash(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    return manifest


def seal_ahoj_geometry_cohort(
    *,
    resolution_path: Path = SOURCE_REPORT,
    private_output: Path = DEFAULT_PRIVATE_OUTPUT,
    detector_output: Path = DEFAULT_DETECTOR_OUTPUT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolution = _read_json(resolution_path)
    cohort = build_ahoj_cohort_payload(resolution)
    cohort["cohort_sha256"] = _stable_hash(
        {key: value for key, value in cohort.items() if key != "cohort_sha256"}
    )
    detector_manifest = build_target_blind_detector_manifest(cohort)
    _write_json(private_output, cohort)
    _write_json(detector_output, detector_manifest)
    print(f"AHoJ cohort sealed: cases={len(cohort['cases'])} split=6/2/2")
    print(f"private evaluator cohort: {private_output}")
    print(f"target-blind detector manifest: {detector_output}")
    print("coordinates/ligands/detector/evaluator/NMA/ML: no")
    return cohort, detector_manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolution", type=Path, default=SOURCE_REPORT)
    parser.add_argument("--private-output", type=Path, default=DEFAULT_PRIVATE_OUTPUT)
    parser.add_argument("--detector-output", type=Path, default=DEFAULT_DETECTOR_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        seal_ahoj_geometry_cohort(
            resolution_path=args.resolution,
            private_output=args.private_output,
            detector_output=args.detector_output,
        )
    except (AhojMetadataResolutionError, OSError, ValueError) as exc:
        print(f"AHoJ cohort sealing error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

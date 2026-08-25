"""Build a versioned AHoJ cohort amendment with an explicit alignment proxy.

The original AHoJ v1 metadata gate did not require apo/holo entity-length
compatibility.  The held-out `6J6F`/`5FB7` pair consequently reached the
evaluator and remained E-status under the frozen structural fit.  This script
does not rewrite that result or tune on DCC/DCA.  It creates a separate v2
cohort whose only new selection rule is a metadata-only alignment feasibility
proxy, then chooses the earliest unused validation candidate deterministically.
Coordinates and labels are not opened by this command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.seal_ahoj_geometry_cohort import _read_json, _write_json  # noqa: E402


DEFAULT_RESOLUTION = (
    REPO_ROOT / "local-private/research/geometry-data-source-catalog/ahoj-v1/"
    "ahoj-geometry-metadata-resolution-v1.json"
)
DEFAULT_V1_COHORT = (
    REPO_ROOT
    / "local-private/research/geometry-data-source-catalog/ahoj-v1/ahoj-geometry-cohort-v1.json"
)
DEFAULT_PRIVATE_OUTPUT = (
    REPO_ROOT / "local-private/research/geometry-data-source-catalog/ahoj-v2-alignment-quality/"
    "ahoj-geometry-cohort-v2.json"
)
DEFAULT_DETECTOR_OUTPUT = (
    REPO_ROOT / "data/runtime/target-family/cohort-ahoj-geometry-v2-alignment-quality/"
    "ahoj-geometry-detector-manifest-v2.json"
)
FAMILY_ID = "AHOJ-GEOMETRY-V2-ALIGNMENT-QUALITY"
TARGET_COUNTS = {"development": 6, "validation": 2, "temporal": 2}
PDB_PATTERN = re.compile(r"^[A-Z0-9]{4}$")
MIN_ENTITY_LENGTH_RATIO = 0.90
FORBIDDEN_DETECTOR_TOKENS = ("holo", "ligand", "evaluator", "ground_truth", "bio_score")


class AhojAlignmentAmendmentError(RuntimeError):
    """Raised when the versioned alignment-quality amendment is invalid."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _pdb_id(value: Any, field: str) -> str:
    text = str(value or "").strip().upper()
    if PDB_PATTERN.fullmatch(text) is None:
        raise AhojAlignmentAmendmentError(f"{field} must be a four-character PDB ID")
    return text


def _ratio(case: Mapping[str, Any]) -> float:
    apo = case.get("apo_entity", {})
    holo = case.get("holo_entity", {})
    try:
        apo_length = int(apo["sequence_length"])
        holo_length = int(holo["sequence_length"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AhojAlignmentAmendmentError(
            f"entity sequence lengths are missing for {case.get('case_id')}"
        ) from exc
    if min(apo_length, holo_length) <= 0:
        raise AhojAlignmentAmendmentError(
            f"entity sequence length is non-positive: {case.get('case_id')}"
        )
    return min(apo_length, holo_length) / max(apo_length, holo_length)


def _metadata_alignment_pass(case: Mapping[str, Any]) -> bool:
    apo = case.get("apo_entity")
    holo = case.get("holo_entity")
    resource = case.get("resource_proxy")
    if (
        not isinstance(apo, Mapping)
        or not isinstance(holo, Mapping)
        or not isinstance(resource, Mapping)
    ):
        return False
    if apo.get("status") != "resolved" or holo.get("status") != "resolved":
        return False
    if case.get("chain_mapping_status") != "resolved":
        return False
    if not str(case.get("label_status", "")).startswith("independent"):
        return False
    if case.get("overlap_reasons"):
        return False
    if not case.get("holo_ligand_chain_ids"):
        return False
    if resource.get("status") != "likely_within_static_atom_cap":
        return False
    return _ratio(case) >= MIN_ENTITY_LENGTH_RATIO


def _amendment_case_id(case: Mapping[str, Any]) -> str:
    return (
        "ahoj-geometry-v2:"
        + _stable_hash(
            {
                "apo": _pdb_id(case.get("apo_structure_id"), "case.apo_structure_id"),
                "holo": _pdb_id(case.get("holo_structure_id"), "case.holo_structure_id"),
                "uniprot": str(case.get("uniprot_id", "")).upper(),
                "family": FAMILY_ID,
            }
        )[:16]
    )


def _private_case(case: Mapping[str, Any], split: str) -> dict[str, Any]:
    apo_entity = case["apo_entity"]
    ligand_chains = case.get("holo_ligand_chain_ids")
    if not isinstance(apo_entity, Mapping) or not isinstance(ligand_chains, list):
        raise AhojAlignmentAmendmentError("resolved chain metadata is incomplete")
    return {
        "case_id": _amendment_case_id(case),
        "family_id": FAMILY_ID,
        "split": split,
        "apo_structure_id": _pdb_id(case.get("apo_structure_id"), "case.apo_structure_id"),
        "holo_structure_id": _pdb_id(case.get("holo_structure_id"), "case.holo_structure_id"),
        "apo_chain_ids": sorted(str(value).upper() for value in apo_entity["chain_ids"]),
        "holo_ligand_chain_ids": sorted(str(value).upper() for value in ligand_chains),
        "uniprot_group_id": str(case.get("uniprot_id", "")).upper(),
        "sequence_cluster_id": str(case.get("sequence_cluster_id", "")),
        "apo_release_date": case.get("apo_release_date"),
        "holo_release_date": case.get("holo_release_date"),
        "ligand_code": str(case.get("ligand_code", "")).upper(),
        "label_source": "independent_annotation_v1",
        "label_source_detail": "AHoJ-DB precomputed BioLiP2 apo/holo site assignment",
        "label_policy_version": "ahoj-biolip2-site-assignment-v1",
        "metadata_alignment_length_ratio": round(_ratio(case), 8),
    }


def build_alignment_amendment(
    resolution: Mapping[str, Any], v1_cohort: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    if resolution.get("decision") != "PASS":
        raise AhojAlignmentAmendmentError("source resolution must remain PASS")
    raw_cases = resolution.get("cases")
    v1_cases = v1_cohort.get("cases")
    if not isinstance(raw_cases, list) or not isinstance(v1_cases, list):
        raise AhojAlignmentAmendmentError("resolution or v1 cohort cases are missing")
    by_apo: dict[str, Mapping[str, Any]] = {}
    for case in raw_cases:
        if not isinstance(case, Mapping):
            continue
        apo_id = _pdb_id(case.get("apo_structure_id"), "case.apo_structure_id")
        if apo_id in by_apo:
            raise AhojAlignmentAmendmentError(f"duplicate apo structure in resolution: {apo_id}")
        by_apo[apo_id] = case
    v1_by_split: dict[str, list[Mapping[str, Any]]] = {split: [] for split in TARGET_COUNTS}
    v1_apo_ids: set[str] = set()
    for case in v1_cases:
        if isinstance(case, Mapping) and str(case.get("split")) in v1_by_split:
            apo_id = _pdb_id(case.get("apo_structure_id"), "case.apo_structure_id")
            if apo_id in v1_apo_ids:
                raise AhojAlignmentAmendmentError(f"duplicate apo structure in v1 cohort: {apo_id}")
            v1_apo_ids.add(apo_id)
            original = by_apo.get(apo_id)
            if original is None:
                raise AhojAlignmentAmendmentError("v1 case is absent from resolution")
            v1_by_split[str(case["split"])].append(original)
    if any(len(v1_by_split[split]) != count for split, count in TARGET_COUNTS.items()):
        raise AhojAlignmentAmendmentError(
            "v1 cohort does not contain the expected 6/2/2 allocation"
        )
    # Keep the original development and temporal rows.  Replace only the
    # alignment-incompatible validation row through a metadata-only rule.
    original_validation = [
        case
        for case in v1_by_split["validation"]
        if _pdb_id(case["apo_structure_id"], "case.apo") != "6J6F"
    ]
    if len(original_validation) != 1:
        raise AhojAlignmentAmendmentError(
            "v1 validation amendment expects exactly one 6J6F replacement"
        )
    replaced_case = next(
        case
        for case in v1_by_split["validation"]
        if _pdb_id(case["apo_structure_id"], "case.apo") == "6J6F"
    )
    if _pdb_id(replaced_case.get("holo_structure_id"), "case.holo") != "5FB7":
        raise AhojAlignmentAmendmentError("v1 validation replacement must target 6J6F/5FB7")
    used_apo = {
        _pdb_id(case["apo_structure_id"], "case.apo_structure_id")
        for split_cases in v1_by_split.values()
        for case in split_cases
    }
    validation_candidates = [
        case
        for case in raw_cases
        if isinstance(case, Mapping)
        and _pdb_id(case.get("apo_structure_id"), "candidate.apo_structure_id") not in used_apo
        and str(case.get("apo_release_date", "")) >= "2018-01-01"
        and str(case.get("apo_release_date", "")) < "2021-01-01"
        and _metadata_alignment_pass(case)
    ]
    if not validation_candidates:
        raise AhojAlignmentAmendmentError(
            "no deterministic metadata-compatible validation replacement exists"
        )
    replacement = min(
        validation_candidates,
        key=lambda case: (
            str(case.get("apo_release_date", "")),
            _pdb_id(case.get("apo_structure_id"), "candidate.apo_structure_id"),
        ),
    )
    split_cases = {
        "development": v1_by_split["development"],
        "validation": original_validation + [replacement],
        "temporal": v1_by_split["temporal"],
    }
    private_cases = [
        _private_case(case, split)
        for split in ("development", "validation", "temporal")
        for case in sorted(split_cases[split], key=lambda item: str(item["apo_structure_id"]))
    ]
    seen_clusters: dict[str, str] = {}
    seen_uniprot: dict[str, str] = {}
    for case in private_cases:
        cluster = case["sequence_cluster_id"]
        uniprot = case["uniprot_group_id"]
        if cluster in seen_clusters and seen_clusters[cluster] != case["split"]:
            raise AhojAlignmentAmendmentError("sequence cluster crosses amendment splits")
        if uniprot in seen_uniprot and seen_uniprot[uniprot] != case["split"]:
            raise AhojAlignmentAmendmentError("UniProt group crosses amendment splits")
        seen_clusters[cluster] = case["split"]
        seen_uniprot[uniprot] = case["split"]
    cohort: dict[str, Any] = {
        "schema_version": "biovoid-ahoj-geometry-cohort-v2",
        "manifest_kind": "private_apo_holo_evaluator_cohort",
        "family_id": FAMILY_ID,
        "source_catalog_id": "ahoj-db-v1-subset1-alignment-quality-v2",
        "source_resolution_sha256": _stable_hash(resolution),
        "split_strategy": "sequence_cluster_temporal_holdout_ahoj_alignment_quality_v2",
        "amendment_rule": {
            "version": "ahoj-alignment-quality-proxy-v1",
            "minimum_entity_length_ratio": MIN_ENTITY_LENGTH_RATIO,
            "required_status": ["resolved", "independent_label", "likely_within_static_atom_cap"],
            "selection_tie_break": "earliest_apo_release_then_apo_structure_id",
            "replaced_v1_apo": "6J6F",
            "replacement_apo": _pdb_id(replacement.get("apo_structure_id"), "replacement.apo"),
        },
        "development_cutoff": "2018-01-01",
        "temporal_cutoff": "2021-01-01",
        "coordinates_downloaded": False,
        "detector_started": False,
        "evaluator_started": False,
        "nma_started": False,
        "ml_training_started": False,
        "cases": private_cases,
        "cohort_sha256": None,
    }
    cohort["cohort_sha256"] = _stable_hash(
        {key: value for key, value in cohort.items() if key != "cohort_sha256"}
    )
    redacted_cases = []
    for case in private_cases:
        redacted_cases.append(
            {
                "case_id": case["case_id"],
                "structure_id": case["apo_structure_id"],
                "family_id": FAMILY_ID,
                "split": "test" if case["split"] == "temporal" else case["split"],
            }
        )
    manifest: dict[str, Any] = {
        "schema_version": "biovoid-ahoj-geometry-detector-manifest-v2",
        "manifest_kind": "target_blind_apo_full_structure_manifest",
        "materialization_status": "metadata_only",
        "family_id": FAMILY_ID,
        "source_catalog_id": cohort["source_catalog_id"],
        "source_resolution_sha256": cohort["source_resolution_sha256"],
        "split_strategy": cohort["split_strategy"],
        "temporal_cutoff": cohort["temporal_cutoff"],
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
    serialized = json.dumps(manifest, ensure_ascii=True).casefold()
    if any(token in serialized for token in FORBIDDEN_DETECTOR_TOKENS):
        raise AhojAlignmentAmendmentError("amendment detector manifest contains evaluator metadata")
    manifest["manifest_sha256"] = _stable_hash(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    return cohort, manifest


def seal_alignment_amendment(
    *,
    resolution_path: Path = DEFAULT_RESOLUTION,
    v1_cohort_path: Path = DEFAULT_V1_COHORT,
    private_output: Path = DEFAULT_PRIVATE_OUTPUT,
    detector_output: Path = DEFAULT_DETECTOR_OUTPUT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolution = _read_json(resolution_path.resolve())
    v1_cohort = _read_json(v1_cohort_path.resolve())
    cohort, manifest = build_alignment_amendment(resolution, v1_cohort)
    _write_json(private_output.resolve(), cohort)
    _write_json(detector_output.resolve(), manifest)
    print(
        "AHoJ alignment-quality amendment sealed: "
        f"replacement={cohort['amendment_rule']['replacement_apo']} split=6/2/2"
    )
    print(f"private amendment cohort: {private_output}")
    print(f"target-blind amendment manifest: {detector_output}")
    print("coordinates/ligands/detector/evaluator/NMA/ML: no")
    return cohort, manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolution", type=Path, default=DEFAULT_RESOLUTION)
    parser.add_argument("--v1-cohort", type=Path, default=DEFAULT_V1_COHORT)
    parser.add_argument("--private-output", type=Path, default=DEFAULT_PRIVATE_OUTPUT)
    parser.add_argument("--detector-output", type=Path, default=DEFAULT_DETECTOR_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        seal_alignment_amendment(
            resolution_path=args.resolution,
            v1_cohort_path=args.v1_cohort,
            private_output=args.private_output,
            detector_output=args.detector_output,
        )
    except (AhojAlignmentAmendmentError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"AHoJ alignment amendment error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

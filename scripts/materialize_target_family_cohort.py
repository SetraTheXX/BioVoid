"""Materialize a private, independently labelled target-family cohort.

This command joins the already-local evaluator report, metadata inventory and
sequence-cluster review.  It does not download coordinates, run a detector,
run a benchmark, or train ML.  Holo-derived ligand geometry is written only to
the ignored private cohort; callers must pass it through the redaction
contract before any detector-facing work.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.target_family_cohort import (  # noqa: E402
    ALLOWED_SPLITS,
    COHORT_SCHEMA_VERSION,
    SPLIT_STRATEGY,
    CohortContractError,
    validate_cohort_manifest,
)


DEFAULT_PAIRS = REPO_ROOT / "local-private/research/target-family/pilot-pairs-pfam-v1.json"
DEFAULT_INVENTORY = (
    REPO_ROOT / "local-private/research/target-family/metadata-inventory-pfam-v1.json"
)
DEFAULT_SEQUENCE_CLUSTERS = (
    REPO_ROOT / "data/runtime/target-family/sequence-clusters-pfam-v1/"
    "target-family-sequence-clusters-pfam-v1.json"
)
DEFAULT_EVALUATOR = (
    REPO_ROOT / "data/runtime/target-family/static-evaluation-pfam-v1-rerun-v2/"
    "target-family-static-evaluation-pfam-v1.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "local-private/research/target-family/cohort-pfam-v1.json"
MAX_CASES = 10
LABEL_SOURCE = "holo_ligand_contact_v1"
AUTO_TEMPORAL_SPLIT = "auto_temporal"
SPLIT_OPTIONS = tuple(sorted((*ALLOWED_SPLITS, AUTO_TEMPORAL_SPLIT)))
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class TargetFamilyCohortMaterializationError(RuntimeError):
    """Raised when independent labels cannot satisfy the private cohort contract."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TargetFamilyCohortMaterializationError(f"{field} must be a non-empty string")
    return value.strip()


def _family_id(payload: Mapping[str, Any]) -> str:
    value = payload.get("family_id")
    if not isinstance(value, str) or not value.strip():
        source = payload.get("source")
        value = source.get("family_id") if isinstance(source, Mapping) else None
    return _required_text(value, "family_id").upper()


def _records(payload: Mapping[str, Any], field: str) -> list[Mapping[str, Any]]:
    raw_records = payload.get(field)
    if not isinstance(raw_records, list) or not raw_records:
        raise TargetFamilyCohortMaterializationError(f"{field} must be a non-empty list")
    if any(not isinstance(record, Mapping) for record in raw_records):
        raise TargetFamilyCohortMaterializationError(f"{field} entries must be objects")
    return [record for record in raw_records if isinstance(record, Mapping)]


def _sha256(value: Any, field: str) -> str:
    text = _required_text(value, field)
    if _SHA256_RE.fullmatch(text) is None:
        raise TargetFamilyCohortMaterializationError(f"{field} must be a SHA-256 hex digest")
    return text.lower()


def _pdb_id(value: Any, field: str) -> str:
    normalized = _required_text(value, field).upper()
    if re.fullmatch(r"[A-Z0-9]{4}", normalized) is None:
        raise TargetFamilyCohortMaterializationError(f"{field} must be a four-character PDB ID")
    return normalized


def _iso_date(value: Any, field: str) -> date:
    text = _required_text(value, field)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise TargetFamilyCohortMaterializationError(
            f"{field} must be an ISO/RFC3339 timestamp"
        ) from exc


def _uniprot_ids(record: Mapping[str, Any], field: str) -> set[str]:
    raw_values = record.get(field)
    if not isinstance(raw_values, list) or not raw_values:
        raise TargetFamilyCohortMaterializationError(f"{field} must be a non-empty list")
    return {_required_text(value, f"{field}[]").upper() for value in raw_values}


def _index_metadata(payload: Mapping[str, Any], family_id: str) -> dict[str, Mapping[str, Any]]:
    if payload.get("schema_version") != "biovoid-target-family-metadata-inventory-v1":
        raise TargetFamilyCohortMaterializationError("metadata inventory schema is unsupported")
    indexed: dict[str, Mapping[str, Any]] = {}
    for record in _records(payload, "records"):
        pdb_id = _pdb_id(record.get("pdb_id"), "metadata.pdb_id")
        if pdb_id in indexed:
            raise TargetFamilyCohortMaterializationError(
                "metadata inventory contains duplicate PDB IDs"
            )
        if _required_text(record.get("family_id"), "metadata.family_id").upper() != family_id:
            raise TargetFamilyCohortMaterializationError("metadata inventory family drifted")
        _uniprot_ids(record, "uniprot_ids")
        _required_text(record.get("release_date"), "metadata.release_date")
        indexed[pdb_id] = record
    return indexed


def _index_clusters(payload: Mapping[str, Any], family_id: str) -> dict[str, Mapping[str, Any]]:
    if payload.get("schema_version") != "biovoid-target-family-sequence-clusters-v1":
        raise TargetFamilyCohortMaterializationError(
            "sequence-cluster report schema is unsupported"
        )
    if payload.get("status") != "sequence_materialized_review_required":
        raise TargetFamilyCohortMaterializationError(
            "sequence-cluster report is not review-required metadata"
        )
    if _family_id(payload) != family_id:
        raise TargetFamilyCohortMaterializationError("sequence-cluster report family drifted")
    indexed: dict[str, Mapping[str, Any]] = {}
    for record in _records(payload, "records"):
        pdb_id = _pdb_id(record.get("pdb_id"), "sequence_cluster.pdb_id")
        if pdb_id in indexed:
            raise TargetFamilyCohortMaterializationError(
                "sequence-cluster report contains duplicate PDB IDs"
            )
        _required_text(record.get("sequence_cluster_id"), "sequence_cluster.sequence_cluster_id")
        indexed[pdb_id] = record
    return indexed


def _index_pairs(
    payload: Mapping[str, Any], family_id: str, *, max_cases: int
) -> list[Mapping[str, Any]]:
    if payload.get("schema_version") != "biovoid-target-family-pilot-pairs-v1":
        raise TargetFamilyCohortMaterializationError("pilot-pairs schema is unsupported")
    pairs = _records(payload, "pairs")
    if len(pairs) > max_cases:
        raise TargetFamilyCohortMaterializationError(
            f"pair count exceeds maximum bound ({max_cases})"
        )
    seen_case_ids: set[str] = set()
    for pair in pairs:
        case_id = _required_text(pair.get("case_id"), "pair.case_id")
        if case_id.casefold() in seen_case_ids:
            raise TargetFamilyCohortMaterializationError("pair case IDs must be unique")
        seen_case_ids.add(case_id.casefold())
        if _required_text(pair.get("family_id"), "pair.family_id").upper() != family_id:
            raise TargetFamilyCohortMaterializationError("pilot pair family drifted")
        _pdb_id(pair.get("apo_pdb_id"), "pair.apo_pdb_id")
        _pdb_id(pair.get("holo_pdb_id"), "pair.holo_pdb_id")
        _required_text(pair.get("uniprot_group"), "pair.uniprot_group")
        components = pair.get("holo_components")
        if not isinstance(components, list) or not components:
            raise TargetFamilyCohortMaterializationError("pair has no declared holo components")
    return sorted(pairs, key=lambda pair: str(pair["case_id"]))


def _numeric_vector(value: Any, field: str, *, length: int | None = None) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TargetFamilyCohortMaterializationError(f"{field} must be a numeric vector")
    values: list[float] = []
    for item in value:
        if isinstance(item, bool):
            raise TargetFamilyCohortMaterializationError(f"{field} contains a boolean")
        try:
            parsed = float(item)
        except (TypeError, ValueError) as exc:
            raise TargetFamilyCohortMaterializationError(f"{field} contains a non-number") from exc
        if not math.isfinite(parsed):
            raise TargetFamilyCohortMaterializationError(f"{field} contains a non-finite number")
        values.append(parsed)
    if length is not None and len(values) != length:
        raise TargetFamilyCohortMaterializationError(f"{field} must have length {length}")
    return values


def _finite_float(
    value: Any,
    field: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError) as exc:
        raise TargetFamilyCohortMaterializationError(f"{field} must be numeric") from exc
    if (
        not math.isfinite(parsed)
        or (minimum is not None and parsed < minimum)
        or (maximum is not None and parsed > maximum)
    ):
        raise TargetFamilyCohortMaterializationError(f"{field} is outside the allowed range")
    return parsed


def _component_ids(pair: Mapping[str, Any]) -> set[str]:
    components = pair.get("holo_components")
    if not isinstance(components, list):
        raise TargetFamilyCohortMaterializationError("pair holo components are invalid")
    values: set[str] = set()
    for component in components:
        if isinstance(component, Mapping) and component.get("comp_id"):
            values.add(str(component["comp_id"]).strip().upper())
    if not values:
        raise TargetFamilyCohortMaterializationError("pair has no usable holo component IDs")
    return values


def _ground_truth_sha256(ground_truth: Mapping[str, Any]) -> str:
    value = ground_truth.get("ground_truth_sha256")
    if not value:
        provenance = ground_truth.get("provenance")
        if isinstance(provenance, str) and provenance.strip():
            try:
                provenance_payload = json.loads(provenance)
            except json.JSONDecodeError:
                provenance_payload = None
            if isinstance(provenance_payload, Mapping):
                value = provenance_payload.get("ground_truth_sha256")
    return _sha256(value, "ground_truth.ground_truth_sha256")


def _label_from_evaluator(
    record: Mapping[str, Any], pair: Mapping[str, Any], *, case_id: str, holo_id: str
) -> dict[str, Any]:
    if record.get("status") != "completed_ground_truth":
        raise TargetFamilyCohortMaterializationError(f"evaluator case is not completed: {case_id}")
    evaluation = record.get("case_evaluation")
    if not isinstance(evaluation, Mapping) or evaluation.get("status") != "completed":
        raise TargetFamilyCohortMaterializationError(
            f"evaluator case has no completed evaluation: {case_id}"
        )
    if evaluation.get("score_used") is not False:
        raise TargetFamilyCohortMaterializationError(
            f"evaluator case does not prove score-independent labels: {case_id}"
        )
    ground_truth = record.get("ground_truth")
    if not isinstance(ground_truth, Mapping):
        raise TargetFamilyCohortMaterializationError(
            f"evaluator ground truth is missing: {case_id}"
        )
    if ground_truth.get("quality") != "exact":
        raise TargetFamilyCohortMaterializationError(
            f"evaluator ground truth is not exact: {case_id}"
        )
    if _required_text(ground_truth.get("case_id"), "ground_truth.case_id") != case_id:
        raise TargetFamilyCohortMaterializationError("ground-truth case ID does not match pair")
    if _pdb_id(ground_truth.get("structure_id"), "ground_truth.structure_id") != _pdb_id(
        pair.get("apo_pdb_id"), "pair.apo_pdb_id"
    ):
        raise TargetFamilyCohortMaterializationError(
            "ground-truth apo structure does not match pair"
        )
    ground_truth_sha256 = _ground_truth_sha256(ground_truth)
    alignment = record.get("alignment")
    if not isinstance(alignment, Mapping):
        raise TargetFamilyCohortMaterializationError(f"evaluator alignment is missing: {case_id}")
    alignment_sha256 = _sha256(alignment.get("alignment_sha256"), "alignment.alignment_sha256")
    coordinate_frame_sha256 = _sha256(
        ground_truth.get("coordinate_frame_sha256"), "ground_truth.coordinate_frame_sha256"
    )
    selector = record.get("ligand_selector")
    if not isinstance(selector, Mapping):
        raise TargetFamilyCohortMaterializationError(f"ligand selector is missing: {case_id}")
    ligand_name = _required_text(
        selector.get("residue_name"), "ligand_selector.residue_name"
    ).upper()
    if ligand_name not in _component_ids(pair):
        raise TargetFamilyCohortMaterializationError(
            f"selected ligand is not declared by pair metadata: {case_id}"
        )
    ligand_center = _numeric_vector(
        ground_truth.get("ligand_center"), "ground_truth.ligand_center", length=3
    )
    raw_atoms = ground_truth.get("ligand_atoms")
    if not isinstance(raw_atoms, list) or not raw_atoms:
        raise TargetFamilyCohortMaterializationError(f"ground truth has no ligand atoms: {case_id}")
    ligand_atoms = [
        _numeric_vector(atom, "ground_truth.ligand_atoms[]", length=3) for atom in raw_atoms
    ]
    raw_residues = ground_truth.get("ligand_residues", [])
    if not isinstance(raw_residues, list):
        raise TargetFamilyCohortMaterializationError("ground_truth.ligand_residues must be a list")
    return {
        "label_source": LABEL_SOURCE,
        "label_kind": "ligand_geometry_v1",
        "holo_structure_id": holo_id,
        "holo_ligand_component_id": ligand_name,
        "ground_truth_sha256": ground_truth_sha256,
        "alignment_sha256": alignment_sha256,
        "coordinate_frame_sha256": coordinate_frame_sha256,
        "quality": "exact",
        "ligand_center": ligand_center,
        "ligand_atoms": ligand_atoms,
        "ligand_residues": [str(value) for value in raw_residues],
        "alignment_status": _required_text(alignment.get("status"), "alignment.status"),
        "sequence_identity": _finite_float(
            alignment.get("sequence_identity"),
            "alignment.sequence_identity",
            minimum=0.0,
            maximum=1.0,
        ),
        "fit_rmsd_angstrom": _finite_float(
            alignment.get("fit_rmsd_angstrom"), "alignment.fit_rmsd_angstrom", minimum=0.0
        ),
        "warnings": [str(value) for value in alignment.get("warnings", [])],
    }


def _unavailable_evaluator_reason(record: Mapping[str, Any], case_id: str) -> str:
    status = _required_text(record.get("status"), "evaluator.status")
    error = record.get("error")
    if isinstance(error, str) and error.strip():
        return f"evaluator status {status}: {error.strip()}"[:500]
    return f"evaluator status {status}: independent label unavailable for {case_id}"


def materialize_private_cohort(
    pairs_payload: Mapping[str, Any],
    inventory_payload: Mapping[str, Any],
    sequence_cluster_payload: Mapping[str, Any],
    evaluator_payload: Mapping[str, Any],
    *,
    temporal_cutoff: str,
    split: str = "development",
    max_cases: int = MAX_CASES,
    allow_unavailable_labels: bool = False,
    validation_cutoff: str | None = None,
) -> dict[str, Any]:
    """Join local evaluator evidence into a validated private cohort.

    When ``allow_unavailable_labels`` is enabled, pairs whose independent
    evaluator record is unavailable are excluded from the usable cohort and
    retained in ``excluded_cases`` with their reason.  This keeps ambiguous
    alignments fail-closed without hiding the selection outcome.
    """

    if not 1 <= max_cases <= MAX_CASES:
        raise ValueError(f"max_cases must be between 1 and {MAX_CASES}")
    if split not in ALLOWED_SPLITS and split != AUTO_TEMPORAL_SPLIT:
        raise ValueError(f"unsupported split: {split}")
    cutoff_date = _iso_date(temporal_cutoff, "temporal_cutoff")
    validation_date = (
        _iso_date(validation_cutoff, "validation_cutoff") if validation_cutoff is not None else None
    )
    if validation_date is not None and split != AUTO_TEMPORAL_SPLIT:
        raise ValueError("validation_cutoff requires split=auto_temporal")
    if validation_date is not None and validation_date >= cutoff_date:
        raise ValueError("validation_cutoff must precede temporal_cutoff")
    family_id = _family_id(inventory_payload)
    metadata = _index_metadata(inventory_payload, family_id)
    sequence_clusters = _index_clusters(sequence_cluster_payload, family_id)
    pairs = _index_pairs(pairs_payload, family_id, max_cases=max_cases)
    evaluator_records = evaluator_payload.get("records")
    if not isinstance(evaluator_records, Mapping):
        raise TargetFamilyCohortMaterializationError("evaluator report records are missing")

    auto_split_by_case: dict[str, str] = {}
    if split == AUTO_TEMPORAL_SPLIT:
        for pair in pairs:
            case_id = _required_text(pair.get("case_id"), "pair.case_id")
            apo_id = _pdb_id(pair.get("apo_pdb_id"), "pair.apo_pdb_id")
            apo_metadata = metadata.get(apo_id)
            if apo_metadata is None:
                raise TargetFamilyCohortMaterializationError(
                    f"pair metadata is missing for {case_id}"
                )
            apo_date = _iso_date(apo_metadata.get("release_date"), "apo.release_date")
            if apo_date >= cutoff_date:
                auto_split_by_case[case_id] = "test"
            elif validation_date is not None and apo_date >= validation_date:
                auto_split_by_case[case_id] = "validation"
            else:
                auto_split_by_case[case_id] = "development"

    cases: list[dict[str, Any]] = []
    excluded_cases: list[dict[str, str]] = []
    for pair in pairs:
        case_id = _required_text(pair.get("case_id"), "pair.case_id")
        apo_id = _pdb_id(pair.get("apo_pdb_id"), "pair.apo_pdb_id")
        holo_id = _pdb_id(pair.get("holo_pdb_id"), "pair.holo_pdb_id")
        apo_metadata = metadata.get(apo_id)
        holo_metadata = metadata.get(holo_id)
        if apo_metadata is None or holo_metadata is None:
            raise TargetFamilyCohortMaterializationError(f"pair metadata is missing for {case_id}")
        expected_group = _required_text(pair.get("uniprot_group"), "pair.uniprot_group").upper()
        if expected_group not in _uniprot_ids(
            apo_metadata, "uniprot_ids"
        ) or expected_group not in _uniprot_ids(holo_metadata, "uniprot_ids"):
            raise TargetFamilyCohortMaterializationError(
                f"pair UniProt group does not match metadata: {case_id}"
            )
        cluster_record = sequence_clusters.get(apo_id)
        if cluster_record is None:
            raise TargetFamilyCohortMaterializationError(
                f"sequence cluster is missing for {apo_id}"
            )
        sequence_cluster_id = _required_text(
            cluster_record.get("sequence_cluster_id"), "sequence_cluster.sequence_cluster_id"
        )
        evaluator_record = evaluator_records.get(case_id)
        if not isinstance(evaluator_record, Mapping):
            reason = "evaluator case is missing"
            if not allow_unavailable_labels:
                raise TargetFamilyCohortMaterializationError(f"{reason}: {case_id}")
            excluded_cases.append({"case_id": case_id, "reason": reason})
            continue
        if allow_unavailable_labels and evaluator_record.get("status") != "completed_ground_truth":
            excluded_cases.append(
                {
                    "case_id": case_id,
                    "reason": _unavailable_evaluator_reason(evaluator_record, case_id),
                }
            )
            continue
        try:
            contact_label = _label_from_evaluator(
                evaluator_record, pair, case_id=case_id, holo_id=holo_id
            )
        except TargetFamilyCohortMaterializationError as exc:
            if not allow_unavailable_labels:
                raise
            excluded_cases.append({"case_id": case_id, "reason": str(exc)[:500]})
            continue
        cases.append(
            {
                "case_id": case_id,
                "apo_structure_id": apo_id,
                "holo_structure_id": holo_id,
                "family_id": family_id,
                "uniprot_group_id": expected_group,
                "sequence_cluster_id": sequence_cluster_id,
                "split": auto_split_by_case.get(case_id, split),
                "apo_release_date": _required_text(
                    apo_metadata.get("release_date"), "apo.release_date"
                ),
                "holo_release_date": _required_text(
                    holo_metadata.get("release_date"), "holo.release_date"
                ),
                "label_source": LABEL_SOURCE,
                "contact_label": contact_label,
            }
        )

    if not cases:
        raise TargetFamilyCohortMaterializationError(
            "no independent labels are available for the private cohort"
        )
    partial = bool(excluded_cases)
    cohort: dict[str, Any] = {
        "schema_version": COHORT_SCHEMA_VERSION,
        "manifest_kind": "private_target_family_cohort",
        "status": (
            "private_contact_labels_partial_review_required"
            if partial
            else "private_contact_labels_materialized_review_required"
        ),
        "family_id": family_id,
        "split_strategy": SPLIT_STRATEGY,
        "temporal_cutoff": _required_text(temporal_cutoff, "temporal_cutoff"),
        "validation_cutoff": (
            _required_text(validation_cutoff, "validation_cutoff")
            if validation_cutoff is not None
            else None
        ),
        "split_assignment_policy": (
            "temporal_three_way_v1" if validation_date is not None else "temporal_test_holdout_v1"
        ),
        "sequence_clusters": "materialized_review_required",
        "contact_labels": (
            "materialized_partial_review_required" if partial else "materialized_review_required"
        ),
        "excluded_cases": excluded_cases,
        "materialization_policy": (
            "exclude_unavailable_with_audit_v1"
            if allow_unavailable_labels
            else "require_all_pairs_v1"
        ),
        "claims_authorized": False,
        "coordinates_downloaded": False,
        "detector_started": False,
        "benchmark_started": False,
        "ml_training_started": False,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": {
            "label_source": LABEL_SOURCE,
            "pairs_inventory_sha256": _stable_hash(pairs_payload),
            "metadata_inventory_sha256": _stable_hash(inventory_payload),
            "sequence_cluster_report_sha256": _stable_hash(sequence_cluster_payload),
            "evaluator_report_sha256": _stable_hash(evaluator_payload),
            "raw_holo_files_public": False,
        },
        "cases": cases,
    }
    try:
        validate_cohort_manifest(cohort)
    except CohortContractError as exc:
        raise TargetFamilyCohortMaterializationError(str(exc)) from exc
    cohort["cohort_sha256"] = _stable_hash(
        {key: value for key, value in cohort.items() if key != "cohort_sha256"}
    )
    return cohort


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TargetFamilyCohortMaterializationError(f"cannot read JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise TargetFamilyCohortMaterializationError(f"JSON root must be an object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def run_private_cohort_materializer(
    *,
    pairs_path: Path = DEFAULT_PAIRS,
    inventory_path: Path = DEFAULT_INVENTORY,
    sequence_clusters_path: Path = DEFAULT_SEQUENCE_CLUSTERS,
    evaluator_path: Path = DEFAULT_EVALUATOR,
    output_path: Path = DEFAULT_OUTPUT,
    temporal_cutoff: str = "2021-01-01",
    split: str = "development",
    max_cases: int = MAX_CASES,
    allow_unavailable_labels: bool = False,
    validation_cutoff: str | None = None,
) -> dict[str, Any]:
    cohort = materialize_private_cohort(
        _read_json(pairs_path.resolve()),
        _read_json(inventory_path.resolve()),
        _read_json(sequence_clusters_path.resolve()),
        _read_json(evaluator_path.resolve()),
        temporal_cutoff=temporal_cutoff,
        split=split,
        max_cases=max_cases,
        allow_unavailable_labels=allow_unavailable_labels,
        validation_cutoff=validation_cutoff,
    )
    _write_json(output_path.resolve(), cohort)
    print(
        f"target-family private cohort: cases={len(cohort['cases'])} "
        f"excluded={len(cohort['excluded_cases'])} split={split} "
        f"labels={cohort['contact_labels']}"
    )
    print(f"private cohort: {output_path}")
    print("coordinates downloaded by materializer: no")
    print("detector/benchmark/NMA/ML started by materializer: no")
    return cohort


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=Path, default=DEFAULT_PAIRS)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--sequence-clusters", type=Path, default=DEFAULT_SEQUENCE_CLUSTERS)
    parser.add_argument("--evaluator", type=Path, default=DEFAULT_EVALUATOR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--temporal-cutoff", default="2021-01-01")
    parser.add_argument(
        "--validation-cutoff",
        default=None,
        help="optional earlier cutoff for the validation split with auto_temporal",
    )
    parser.add_argument("--split", choices=SPLIT_OPTIONS, default="development")
    parser.add_argument("--max-cases", type=int, default=MAX_CASES)
    parser.add_argument(
        "--allow-unavailable-labels",
        action="store_true",
        help="exclude unavailable/ambiguous evaluator cases with an explicit audit trail",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        run_private_cohort_materializer(
            pairs_path=args.pairs,
            inventory_path=args.inventory,
            sequence_clusters_path=args.sequence_clusters,
            evaluator_path=args.evaluator,
            output_path=args.output,
            temporal_cutoff=args.temporal_cutoff,
            split=args.split,
            max_cases=args.max_cases,
            allow_unavailable_labels=args.allow_unavailable_labels,
            validation_cutoff=args.validation_cutoff,
        )
    except (TargetFamilyCohortMaterializationError, ValueError) as exc:
        print(f"target-family cohort materialization error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

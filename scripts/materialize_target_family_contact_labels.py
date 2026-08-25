"""Materialize bounded evaluator-only holo-ligand labels for a private cohort.

The command derives strict pair candidates from an ignored metadata inventory,
downloads at most ten apo/holo mmCIF files into ignored local storage, prepares
the apo side for alignment, and writes independent ligand-geometry labels. It
does not run canonical-static-v1, any benchmark, NMA or ML. The resulting
report is intentionally not a detector manifest; pass it through
``materialize_target_family_cohort.py`` for the redaction/readiness contract.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.audit_target_family_metadata_candidates import audit_metadata_candidates  # noqa: E402
from scripts.evaluate_target_family_static_pilot import (  # noqa: E402
    EVALUATOR_POLICY,
    _chain_pairs,
    _ligand_selector,
)
from src.fetcher import FetchError, fetch_structure_input  # noqa: E402
from src.ground_truth_alignment import (  # noqa: E402
    AlignmentPolicy,
    GroundTruthAlignmentError,
    build_aligned_ground_truth_from_files,
)
from src.structure_preparation import (  # noqa: E402
    PreparationConfig,
    StructureSource,
    prepare_structure,
)


DEFAULT_INVENTORY = (
    REPO_ROOT / "local-private/research/target-family/metadata-inventory-pfam-v1.json"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "local-private/research/target-family/contact-labels-pfam-v1"
DEFAULT_PAIRS_OUTPUT = REPO_ROOT / "local-private/research/target-family/pilot-pairs-pfam-v1.json"
DEFAULT_REPORT = DEFAULT_OUTPUT_ROOT / "target-family-contact-labels-pfam-v1.json"
MAX_CASES = 10
MAX_DISK_BYTES = 1_000_000_000
REPORT_SCHEMA_VERSION = "biovoid-target-family-contact-labels-v1"
LABEL_SOURCE = "holo_ligand_contact_v1"
SEQUENCE_CLUSTER_SCHEMA_VERSION = "biovoid-target-family-sequence-clusters-v1"
SEQUENCE_COMPATIBLE_SELECTION_POLICY = "xray-180-350aa-resolution-2.8-sequence-compatible-v1"


class TargetFamilyContactLabelError(RuntimeError):
    """Raised when a private contact-label run violates its boundary."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TargetFamilyContactLabelError(f"cannot read JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise TargetFamilyContactLabelError(f"JSON root must be an object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _directory_size_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    for directory, _, filenames in os.walk(root, followlinks=False):
        for filename in filenames:
            path = Path(directory) / filename
            try:
                if not path.is_symlink():
                    total += path.stat().st_size
            except FileNotFoundError:
                continue
    return total


def _enforce_disk_quota(root: Path, max_disk_bytes: int) -> int:
    if not 1 <= max_disk_bytes <= MAX_DISK_BYTES:
        raise ValueError(f"max_disk_bytes must be between 1 and {MAX_DISK_BYTES}")
    used = _directory_size_bytes(root)
    if used > max_disk_bytes:
        raise TargetFamilyContactLabelError(
            f"contact-label disk quota exceeded: {used} bytes > {max_disk_bytes}"
        )
    return used


def _family_id(payload: Mapping[str, Any]) -> str:
    value = payload.get("family_id")
    if not isinstance(value, str) or not value.strip():
        source = payload.get("source")
        value = source.get("family_id") if isinstance(source, Mapping) else None
    if not isinstance(value, str) or not value.strip():
        raise TargetFamilyContactLabelError("inventory family_id is missing")
    return value.strip().upper()


def _pdb_id(value: Any, field: str) -> str:
    text = str(value or "").strip().upper()
    if re.fullmatch(r"[A-Z0-9]{4}", text) is None:
        raise TargetFamilyContactLabelError(f"{field} must be a four-character PDB ID")
    return text


def _case_id(family_id: str, apo_id: str, uniprot_group: str) -> str:
    suffix = _stable_hash(
        {"family_id": family_id, "pdb_id": apo_id, "uniprot_group": uniprot_group}
    )[:16]
    return f"{family_id}:{apo_id}:{suffix}"


def _holo_components(value: Any, field: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise TargetFamilyContactLabelError(f"{field} must be a non-empty list")
    components: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise TargetFamilyContactLabelError(f"{field} entries must be objects")
        comp_id = str(item.get("comp_id") or "").strip().upper()
        if not comp_id or comp_id in seen:
            continue
        seen.add(comp_id)
        name = str(item.get("name") or "").strip()
        components.append({"comp_id": comp_id, **({"name": name} if name else {})})
    if not components:
        raise TargetFamilyContactLabelError(f"{field} has no usable component IDs")
    return components


def _sequence_cluster_index(
    payload: Mapping[str, Any] | None, *, family_id: str, records: Sequence[Mapping[str, Any]]
) -> dict[str, str] | None:
    """Validate and index a complete metadata-only sequence-cluster report."""

    if payload is None:
        return None
    if payload.get("schema_version") != SEQUENCE_CLUSTER_SCHEMA_VERSION:
        raise TargetFamilyContactLabelError("sequence-cluster report schema is unsupported")
    if payload.get("status") != "sequence_materialized_review_required":
        raise TargetFamilyContactLabelError("sequence-cluster report is not review-required")
    report_family = payload.get("family_id")
    if not isinstance(report_family, str) or report_family.strip().upper() != family_id:
        source = payload.get("source")
        report_family = source.get("family_id") if isinstance(source, Mapping) else report_family
    if not isinstance(report_family, str) or report_family.strip().upper() != family_id:
        raise TargetFamilyContactLabelError("sequence-cluster report family drifted")
    raw_cluster_records = payload.get("records")
    if not isinstance(raw_cluster_records, list):
        raise TargetFamilyContactLabelError("sequence-cluster report records are missing")
    indexed: dict[str, str] = {}
    for raw_record in raw_cluster_records:
        if not isinstance(raw_record, Mapping):
            raise TargetFamilyContactLabelError("sequence-cluster report records are invalid")
        pdb_id = _pdb_id(raw_record.get("pdb_id"), "sequence_cluster.pdb_id")
        if pdb_id in indexed:
            raise TargetFamilyContactLabelError(
                "sequence-cluster report contains duplicate PDB IDs"
            )
        cluster_id = str(raw_record.get("sequence_cluster_id") or "").strip()
        if not cluster_id:
            raise TargetFamilyContactLabelError(
                "sequence_cluster.sequence_cluster_id must be non-empty"
            )
        indexed[pdb_id] = cluster_id
    missing = [
        _pdb_id(record.get("pdb_id"), "inventory.pdb_id")
        for record in records
        if _pdb_id(record.get("pdb_id"), "inventory.pdb_id") not in indexed
    ]
    if missing:
        raise TargetFamilyContactLabelError(
            "sequence-cluster report is incomplete for inventory: " + ", ".join(sorted(missing))
        )
    return indexed


def _strict_quality_passes(record: Mapping[str, Any]) -> bool:
    method = str(record.get("experimental_method", "")).casefold()
    try:
        length = int(record["sequence_length"])
        resolution = float(record["resolution_angstrom"])
    except (KeyError, TypeError, ValueError):
        return False
    return "x-ray" in method and 180 <= length <= 350 and resolution <= 2.8


def _sequence_compatible_candidates(
    records: Sequence[Mapping[str, Any]],
    *,
    sequence_clusters: Mapping[str, str],
    max_cases: int,
) -> list[dict[str, Any]]:
    """Select one quality-passing, same-cluster apo/holo pair per group."""

    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        group_values = record.get("uniprot_ids")
        if not isinstance(group_values, list) or not group_values:
            raise TargetFamilyContactLabelError("inventory record has no UniProt group")
        group = "+".join(sorted(str(value).strip().upper() for value in group_values))
        grouped.setdefault(group, []).append(record)

    candidates: list[dict[str, Any]] = []
    for group in sorted(grouped):
        eligible = [record for record in grouped[group] if _strict_quality_passes(record)]
        apo_records = [record for record in eligible if not record.get("likely_ligand_components")]
        holo_records = [record for record in eligible if record.get("likely_ligand_components")]
        compatible: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
        for apo in apo_records:
            apo_id = _pdb_id(apo.get("pdb_id"), "candidate.apo_structure_id")
            for holo in holo_records:
                holo_id = _pdb_id(holo.get("pdb_id"), "candidate.holo_structure_id")
                if sequence_clusters[apo_id] == sequence_clusters[holo_id]:
                    compatible.append((apo, holo))
        if not compatible:
            continue
        apo, holo = min(
            compatible,
            key=lambda pair: (
                float(pair[0]["resolution_angstrom"]),
                float(pair[1]["resolution_angstrom"]),
                -len(pair[1].get("likely_ligand_components", [])),
                str(pair[0]["pdb_id"]),
                str(pair[1]["pdb_id"]),
            ),
        )
        candidates.append(
            {
                "uniprot_group": group,
                "apo_structure_id": _pdb_id(apo.get("pdb_id"), "candidate.apo_structure_id"),
                "holo_structure_id": _pdb_id(holo.get("pdb_id"), "candidate.holo_structure_id"),
                "sequence_cluster_id": sequence_clusters[
                    _pdb_id(apo.get("pdb_id"), "candidate.apo_structure_id")
                ],
            }
        )
    if len(candidates) > max_cases:
        raise TargetFamilyContactLabelError(
            f"strict sequence-compatible pair count exceeds maximum bound ({max_cases})"
        )
    return candidates


def build_strict_pair_payload(
    inventory_payload: Mapping[str, Any],
    *,
    max_cases: int = MAX_CASES,
    sequence_clusters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic private pair metadata from the strict audit policy."""

    if not 1 <= max_cases <= MAX_CASES:
        raise ValueError(f"max_cases must be between 1 and {MAX_CASES}")
    family_id = _family_id(inventory_payload)
    raw_records = inventory_payload.get("records")
    if not isinstance(raw_records, list):
        raise TargetFamilyContactLabelError("inventory records are missing")
    by_pdb = {
        _pdb_id(record.get("pdb_id"), "inventory.pdb_id"): record
        for record in raw_records
        if isinstance(record, Mapping)
    }
    audit = audit_metadata_candidates(inventory_payload)
    inventory_records = [record for record in raw_records if isinstance(record, Mapping)]
    sequence_cluster_index = _sequence_cluster_index(
        sequence_clusters, family_id=family_id, records=inventory_records
    )
    if sequence_cluster_index is None:
        candidates = audit["strict"]["pairs"]
        selection_policy = "xray-180-350aa-resolution-2.8-v1"
    else:
        candidates = _sequence_compatible_candidates(
            inventory_records,
            sequence_clusters=sequence_cluster_index,
            max_cases=max_cases,
        )
        selection_policy = SEQUENCE_COMPATIBLE_SELECTION_POLICY
    if not isinstance(candidates, list):
        raise TargetFamilyContactLabelError("strict candidate audit pairs are invalid")
    if len(candidates) > max_cases:
        raise TargetFamilyContactLabelError(
            f"strict pair count exceeds maximum bound ({max_cases})"
        )
    pairs: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise TargetFamilyContactLabelError("strict candidate pair is invalid")
        apo_id = _pdb_id(candidate.get("apo_structure_id"), "candidate.apo_structure_id")
        holo_id = _pdb_id(candidate.get("holo_structure_id"), "candidate.holo_structure_id")
        group = str(candidate.get("uniprot_group") or "").strip().upper()
        holo_record = by_pdb.get(holo_id)
        apo_record = by_pdb.get(apo_id)
        if holo_record is None or apo_record is None:
            raise TargetFamilyContactLabelError(
                f"candidate metadata is missing: {apo_id}/{holo_id}"
            )
        components = _holo_components(
            holo_record.get("likely_ligand_components"),
            f"holo ligand components ({holo_id})",
        )
        if group not in {
            str(value).strip().upper() for value in apo_record.get("uniprot_ids", [])
        } or group not in {
            str(value).strip().upper() for value in holo_record.get("uniprot_ids", [])
        }:
            raise TargetFamilyContactLabelError(
                f"candidate UniProt group does not match metadata: {group}"
            )
        pairs.append(
            {
                "case_id": _case_id(family_id, apo_id, group),
                "family_id": family_id,
                "uniprot_group": group,
                "apo_pdb_id": apo_id,
                "holo_pdb_id": holo_id,
                "holo_components": components,
                **(
                    {"sequence_cluster_id": sequence_cluster_index[apo_id]}
                    if sequence_cluster_index is not None
                    else {}
                ),
            }
        )
    return {
        "schema_version": "biovoid-target-family-pilot-pairs-v1",
        "status": "private_contact_label_review_required",
        "family_id": family_id,
        "label_source": LABEL_SOURCE,
        "selection_policy": selection_policy,
        "pairs": pairs,
        "source_inventory_sha256": _stable_hash(inventory_payload),
    }


def build_contact_label_report(
    *,
    family_id: str,
    pairs: Sequence[Mapping[str, Any]],
    output_root: str | Path,
    max_cases: int,
    max_disk_bytes: int,
    alignment_policy: AlignmentPolicy = EVALUATOR_POLICY,
) -> dict[str, Any]:
    """Build the sealed-boundary skeleton before any coordinate request."""

    if not 1 <= max_cases <= MAX_CASES:
        raise ValueError(f"max_cases must be between 1 and {MAX_CASES}")
    if not 1 <= max_disk_bytes <= MAX_DISK_BYTES:
        raise ValueError(f"max_disk_bytes must be between 1 and {MAX_DISK_BYTES}")
    if not pairs or len(pairs) > max_cases:
        raise TargetFamilyContactLabelError("contact-label pair count is outside the bound")
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "not_started",
        "family_id": family_id,
        "label_source": LABEL_SOURCE,
        "evaluator_only": True,
        "detector_target_blind": True,
        "claim_boundary": "independent_label_curation_only",
        "alignment_policy": asdict(alignment_policy),
        "execution": {
            "workers": 1,
            "max_cases": max_cases,
            "max_disk_bytes": max_disk_bytes,
            "disk_quota_enforced": True,
            "coordinates_downloaded": False,
            "detector_started": False,
            "benchmark_started": False,
            "motion_enabled": False,
            "ml_training_started": False,
        },
        "source": {
            "provider": "RCSB files.rcsb.org",
            "holo_role": "evaluator_only",
            "raw_structures_ignored": True,
        },
        "pairs": [dict(pair) for pair in pairs],
        "records": {},
        "counts": {"completed": 0, "failed": 0},
        "coordinates_downloaded": False,
        "detector_started": False,
        "benchmark_started": False,
        "ml_training_started": False,
        "claims_authorized": False,
        "output_root": str(output_root).replace("\\", "/"),
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "report_sha256": None,
    }


def _seal(report: dict[str, Any]) -> None:
    report["updated_at_utc"] = _utc_now()
    report["report_sha256"] = _stable_hash(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )


def _source_summary(fetched: Any) -> dict[str, Any]:
    path = Path(fetched.path)
    return {
        "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _alignment_record(
    *,
    pair: Mapping[str, Any],
    selector: Any,
    alignment: Any,
    prepared_path: Path,
) -> dict[str, Any]:
    ground_truth = asdict(alignment.ground_truth)
    return {
        "case_id": str(pair["case_id"]),
        "structure_id": str(pair["apo_pdb_id"]).upper(),
        "status": "completed_ground_truth",
        "detector_arm": "unavailable",
        "ligand_selector": asdict(selector),
        "alignment": {
            "status": alignment.status,
            "matched_residue_count": alignment.matched_residue_count,
            "sequence_identity": alignment.sequence_identity,
            "fit_rmsd_angstrom": alignment.fit_rmsd_angstrom,
            "alignment_sha256": alignment.alignment_sha256,
            "ground_truth_sha256": alignment.ground_truth_sha256,
            "warnings": list(alignment.warnings),
        },
        "ground_truth": ground_truth,
        "case_evaluation": {
            "status": "completed",
            "detector": "not_run",
            "score_used": False,
            "label_only": True,
        },
        "prepared_path": str(prepared_path.relative_to(REPO_ROOT)).replace("\\", "/"),
    }


def _run_pair(
    pair: Mapping[str, Any],
    *,
    output_root: Path,
    source_cache: Path,
    max_disk_bytes: int,
    alignment_policy: AlignmentPolicy = EVALUATOR_POLICY,
    preferred_apo_chain_id: str | None = None,
    preferred_holo_chain_id: str | None = None,
    preferred_ligand_chain_id: str | None = None,
    provenance_label: str = "target-family-rcsb-contact-label-only-v1",
    run_id_suffix: str = "contact-label-v1",
) -> dict[str, Any]:
    apo_id = _pdb_id(pair.get("apo_pdb_id"), "pair.apo_pdb_id")
    holo_id = _pdb_id(pair.get("holo_pdb_id"), "pair.holo_pdb_id")
    case_dir = output_root / "cases" / apo_id
    preparation_dir = case_dir / "preparation"
    started = time.perf_counter()
    try:
        _enforce_disk_quota(output_root, max_disk_bytes)
        apo_source = StructureSource(
            provider="rcsb", identifier=apo_id, representation="asymmetric_unit"
        )
        holo_source = StructureSource(
            provider="rcsb", identifier=holo_id, representation="asymmetric_unit"
        )
        apo_fetched = fetch_structure_input(apo_source, cache_dir=source_cache)
        holo_fetched = fetch_structure_input(holo_source, cache_dir=source_cache)
        _enforce_disk_quota(output_root, max_disk_bytes)
        preparation = prepare_structure(
            apo_fetched.path,
            apo_source,
            PreparationConfig(),
            preparation_dir,
            run_id=f"target-family-{apo_id.lower()}-{run_id_suffix}",
            source_metadata={
                "provider": "RCSB PDB",
                "entry_id": apo_id,
                "representation": "asymmetric_unit",
                "purpose": "independent_contact_label_curation",
            },
            analysis_config={
                "purpose": "independent_contact_label_curation",
                "workers": 1,
                "detector_started": False,
                "benchmark_started": False,
                "motion_enabled": False,
            },
        )
        _enforce_disk_quota(output_root, max_disk_bytes)
        chain_pairs = _chain_pairs(preparation.prepared_path, holo_fetched.path)
        if preferred_apo_chain_id or preferred_holo_chain_id:
            declared_apo = str(preferred_apo_chain_id or "").strip()
            declared_holo = str(preferred_holo_chain_id or "").strip()
            chain_pairs = tuple(
                pair
                for pair in chain_pairs
                if (not declared_apo or pair.apo_chain_id == declared_apo)
                and (not declared_holo or pair.holo_chain_id == declared_holo)
            )
            if not chain_pairs:
                raise GroundTruthAlignmentError(
                    "Declared apo/holo chains are not a common alignment pair"
                )
        component_ids = tuple(
            str(component.get("comp_id", "")).strip().upper()
            for component in pair.get("holo_components", [])
            if isinstance(component, Mapping) and str(component.get("comp_id", "")).strip()
        )
        selector = _ligand_selector(
            holo_fetched.path,
            component_ids,
            preferred_chain_id=(
                preferred_ligand_chain_id or preferred_holo_chain_id or chain_pairs[0].holo_chain_id
            ),
        )
        alignment = build_aligned_ground_truth_from_files(
            case_id=str(pair["case_id"]),
            structure_id=apo_id,
            prepared_apo_path=preparation.prepared_path,
            holo_path=holo_fetched.path,
            ligand=selector,
            chain_pairs=chain_pairs,
            provenance_label=provenance_label,
            policy=alignment_policy,
        )
        record = _alignment_record(
            pair=pair,
            selector=selector,
            alignment=alignment,
            prepared_path=preparation.prepared_path,
        )
        record.update(
            {
                "apo_source": _source_summary(apo_fetched),
                "holo_source": _source_summary(holo_fetched),
                "chain_pairs": [asdict(value) for value in chain_pairs],
                "chain_selection_policy": "representative-common-chain-v1",
                "runtime_seconds": round(time.perf_counter() - started, 6),
            }
        )
        return record
    except (FetchError, GroundTruthAlignmentError, OSError, ValueError, KeyError) as exc:
        return {
            "case_id": str(pair["case_id"]),
            "structure_id": apo_id,
            "status": "alignment_unavailable",
            "detector_arm": "unavailable",
            "error": f"{type(exc).__name__}: {exc}"[:500],
            "case_evaluation": None,
            "runtime_seconds": round(time.perf_counter() - started, 6),
        }


def run_contact_label_materializer(
    *,
    inventory_path: Path = DEFAULT_INVENTORY,
    sequence_clusters_path: Path | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    pairs_output: Path = DEFAULT_PAIRS_OUTPUT,
    report_path: Path = DEFAULT_REPORT,
    max_cases: int = MAX_CASES,
    max_disk_bytes: int = MAX_DISK_BYTES,
) -> dict[str, Any]:
    inventory = _read_json(inventory_path.resolve())
    sequence_clusters = (
        _read_json(sequence_clusters_path.resolve()) if sequence_clusters_path is not None else None
    )
    pairs_payload = build_strict_pair_payload(
        inventory,
        max_cases=max_cases,
        sequence_clusters=sequence_clusters,
    )
    pairs_output.parent.mkdir(parents=True, exist_ok=True)
    _write_json(pairs_output.resolve(), pairs_payload)
    pairs = pairs_payload["pairs"]
    report = build_contact_label_report(
        family_id=_family_id(inventory),
        pairs=pairs,
        output_root=output_root,
        max_cases=max_cases,
        max_disk_bytes=max_disk_bytes,
    )
    output_root.resolve().mkdir(parents=True, exist_ok=True)
    _enforce_disk_quota(output_root.resolve(), max_disk_bytes)
    report["status"] = "running"
    _seal(report)
    _write_json(report_path.resolve(), report)
    source_cache = output_root.resolve() / "source-cache"
    for pair in pairs:
        case_id = str(pair["case_id"])
        record = _run_pair(
            pair,
            output_root=output_root.resolve(),
            source_cache=source_cache,
            max_disk_bytes=max_disk_bytes,
        )
        report["records"][case_id] = record
        if record.get("status") == "completed_ground_truth":
            report["counts"]["completed"] += 1
        else:
            report["counts"]["failed"] += 1
        report["execution"]["coordinates_downloaded"] = True
        report["coordinates_downloaded"] = True
        _enforce_disk_quota(output_root.resolve(), max_disk_bytes)
        _seal(report)
        _write_json(report_path.resolve(), report)
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
    _seal(report)
    _write_json(report_path.resolve(), report)
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument(
        "--sequence-clusters",
        type=Path,
        default=None,
        help="optional complete metadata-only sequence-cluster report",
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--pairs-output", type=Path, default=DEFAULT_PAIRS_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-cases", type=int, default=MAX_CASES)
    parser.add_argument("--max-disk-bytes", type=int, default=MAX_DISK_BYTES)
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="required acknowledgement before downloading private evaluator structures",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.allow_network:
        print("contact-label materialization requires --allow-network", file=sys.stderr)
        return 2
    try:
        report = run_contact_label_materializer(
            inventory_path=args.inventory,
            sequence_clusters_path=args.sequence_clusters,
            output_root=args.output_root,
            pairs_output=args.pairs_output,
            report_path=args.report,
            max_cases=args.max_cases,
            max_disk_bytes=args.max_disk_bytes,
        )
    except (TargetFamilyContactLabelError, ValueError, OSError) as exc:
        print(f"target-family contact-label error: {exc}", file=sys.stderr)
        return 2
    print(
        f"target-family contact labels: status={report['status']} "
        f"completed={report['counts']['completed']} failed={report['counts']['failed']}"
    )
    print(f"contact-label report: {args.report}")
    print(f"private pairs: {args.pairs_output}")
    print(f"disk_bytes={report['execution'].get('final_disk_bytes', 0)}")
    print("detector/benchmark/NMA/ML started: no")
    return 0 if report["status"] == "completed_review_required" else 2


if __name__ == "__main__":
    raise SystemExit(main())

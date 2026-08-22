"""Audit metadata-only target-family candidate capacity.

This command reads an ignored RCSB metadata inventory and reports deterministic
apo/holo pair candidates under strict and relaxed quality policies. It never
downloads coordinates, computes a sequence cluster, assigns contact labels, or
starts a detector/benchmark/ML job.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


INVENTORY_SCHEMA_VERSION = "biovoid-target-family-metadata-inventory-v1"
AUDIT_SCHEMA_VERSION = "biovoid-target-family-metadata-candidate-audit-v1"
DEFAULT_INPUT = REPO_ROOT / "local-private/research/target-family/metadata-inventory-pfam-v1.json"
DEFAULT_OUTPUT = (
    REPO_ROOT / "data/runtime/target-family/pfam-metadata-candidate-audit-v1/"
    "target-family-pfam-metadata-candidate-audit-v1.json"
)
MAX_RECORDS = 100


class MetadataCandidateAuditError(RuntimeError):
    """Raised when a metadata inventory violates the candidate-audit contract."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MetadataCandidateAuditError(f"{field} must be a non-empty string")
    return value.strip()


def _family_id(payload: Mapping[str, Any]) -> str:
    value = payload.get("family_id")
    if not isinstance(value, str) or not value.strip():
        source = payload.get("source")
        value = source.get("family_id") if isinstance(source, Mapping) else None
    return _required_text(value, "family_id").upper()


def _records(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if payload.get("schema_version") != INVENTORY_SCHEMA_VERSION:
        raise MetadataCandidateAuditError("metadata inventory schema is unsupported")
    raw_records = payload.get("records")
    if not isinstance(raw_records, list) or not 1 <= len(raw_records) <= MAX_RECORDS:
        raise MetadataCandidateAuditError("metadata inventory record count is outside the bound")
    if any(not isinstance(record, Mapping) for record in raw_records):
        raise MetadataCandidateAuditError("metadata inventory records must be objects")
    records = [record for record in raw_records if isinstance(record, Mapping)]
    declared_count = payload.get("record_count")
    if declared_count is not None and declared_count != len(records):
        raise MetadataCandidateAuditError("metadata inventory record count does not match records")
    family_id = _family_id(payload)
    seen_ids: set[str] = set()
    for record in records:
        structure_id = _required_text(record.get("pdb_id"), "record.pdb_id").upper()
        if structure_id in seen_ids:
            raise MetadataCandidateAuditError("metadata inventory structure IDs must be unique")
        seen_ids.add(structure_id)
        if _required_text(record.get("family_id"), "record.family_id").upper() != family_id:
            raise MetadataCandidateAuditError("metadata inventory contains another family")
        uniprots = record.get("uniprot_ids")
        if not isinstance(uniprots, list) or not uniprots:
            raise MetadataCandidateAuditError("metadata inventory record has no UniProt group")
        try:
            float(str(record.get("resolution_angstrom")))
            int(str(record.get("sequence_length")))
        except (TypeError, ValueError) as exc:
            raise MetadataCandidateAuditError(
                "metadata inventory quality fields are invalid"
            ) from exc
        if not isinstance(record.get("likely_ligand_components"), list):
            raise MetadataCandidateAuditError("metadata inventory ligand metadata is invalid")
    return records


def _quality_passes(
    record: Mapping[str, Any],
    *,
    min_sequence_length: int,
    max_sequence_length: int,
    max_resolution_angstrom: float,
) -> bool:
    method = str(record.get("experimental_method", "")).casefold()
    try:
        length = int(record["sequence_length"])
        resolution = float(record["resolution_angstrom"])
    except (KeyError, TypeError, ValueError):
        return False
    return (
        "x-ray" in method
        and min_sequence_length <= length <= max_sequence_length
        and resolution <= max_resolution_angstrom
    )


def _group_id(record: Mapping[str, Any]) -> str:
    values = sorted(
        {_required_text(value, "record.uniprot_id").upper() for value in record["uniprot_ids"]}
    )
    return "+".join(values)


def _pair_candidate(record_group: list[Mapping[str, Any]]) -> dict[str, Any] | None:
    apo = [record for record in record_group if not record["likely_ligand_components"]]
    holo = [record for record in record_group if record["likely_ligand_components"]]
    if not apo or not holo:
        return None
    selected_apo = min(
        apo, key=lambda item: (float(item["resolution_angstrom"]), str(item["pdb_id"]))
    )
    selected_holo = min(
        holo,
        key=lambda item: (
            float(item["resolution_angstrom"]),
            -len(item["likely_ligand_components"]),
            str(item["pdb_id"]),
        ),
    )
    return {
        "uniprot_group": _group_id(selected_apo),
        "apo_structure_id": str(selected_apo["pdb_id"]).upper(),
        "holo_structure_id": str(selected_holo["pdb_id"]).upper(),
        "apo_candidate_count": len(apo),
        "holo_candidate_count": len(holo),
        "sequence_cluster_status": "not_materialized",
        "contact_label_status": "not_materialized",
    }


def _policy_report(
    records: list[Mapping[str, Any]],
    *,
    policy_id: str,
    min_sequence_length: int,
    max_sequence_length: int = 350,
    max_resolution_angstrom: float = 2.8,
) -> dict[str, Any]:
    eligible = [
        record
        for record in records
        if _quality_passes(
            record,
            min_sequence_length=min_sequence_length,
            max_sequence_length=max_sequence_length,
            max_resolution_angstrom=max_resolution_angstrom,
        )
    ]
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for record in eligible:
        grouped.setdefault(_group_id(record), []).append(record)
    pairs = [
        candidate
        for group in sorted(grouped)
        if (candidate := _pair_candidate(grouped[group])) is not None
    ]
    return {
        "policy_id": policy_id,
        "min_sequence_length": min_sequence_length,
        "max_sequence_length": max_sequence_length,
        "max_resolution_angstrom": max_resolution_angstrom,
        "eligible_record_count": len(eligible),
        "eligible_group_count": len(grouped),
        "paired_group_count": len(pairs),
        "selected_pair_count": len(pairs),
        "pairs": pairs,
    }


def audit_metadata_candidates(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a metadata-only capacity report for the next cohort gate."""

    records = _records(payload)
    report: dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "status": "candidate_inventory_only",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "family_id": _family_id(payload),
        "input_inventory_sha256": _stable_hash(payload),
        "record_count": len(records),
        "strict": _policy_report(
            records,
            policy_id="xray-180-350aa-resolution-2.8-v1",
            min_sequence_length=180,
        ),
        "relaxed_length_120": _policy_report(
            records,
            policy_id="xray-120-350aa-resolution-2.8-v1",
            min_sequence_length=120,
        ),
        "sequence_clusters": "not_materialized",
        "contact_labels": "not_materialized",
        "coordinates_downloaded": False,
        "detector_started": False,
        "benchmark_started": False,
        "ml_training_started": False,
        "next_gate": "sequence_cluster_and_contact_label_curation",
        "claims_authorized": False,
    }
    report["report_sha256"] = _stable_hash(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    return report


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MetadataCandidateAuditError(f"cannot read metadata inventory: {path}") from exc
    if not isinstance(payload, dict):
        raise MetadataCandidateAuditError("metadata inventory must be a JSON object")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def run_metadata_candidate_audit(
    *, input_path: Path = DEFAULT_INPUT, output_path: Path = DEFAULT_OUTPUT
) -> dict[str, Any]:
    report = audit_metadata_candidates(_read_json(input_path.resolve()))
    _write_json(output_path.resolve(), report)
    print(
        f"target-family metadata candidates: strict_pairs={report['strict']['selected_pair_count']} "
        f"relaxed_pairs={report['relaxed_length_120']['selected_pair_count']}"
    )
    print(f"candidate audit report: {output_path}")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        run_metadata_candidate_audit(input_path=args.input, output_path=args.output)
    except MetadataCandidateAuditError as exc:
        print(f"target-family metadata candidate error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

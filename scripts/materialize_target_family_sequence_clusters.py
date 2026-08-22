"""Materialize a bounded, metadata-only sequence-cluster review artifact.

The command reads the ignored RCSB metadata inventory and fetches only RCSB
entry/polymer-entity JSON.  It never downloads a coordinate file, opens a
structure, starts the pocket detector, runs a benchmark, or trains ML.  The
cluster rule is deliberately an explicit review parameter rather than a
scientific conclusion: global pairwise identity is connected into
single-linkage components and the result is marked ``review_required``.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence

import requests
from Bio.Align import PairwiseAligner

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DATA_URL = "https://data.rcsb.org/rest/v1/core"
INVENTORY_SCHEMA_VERSION = "biovoid-target-family-metadata-inventory-v1"
CLUSTER_SCHEMA_VERSION = "biovoid-target-family-sequence-clusters-v1"
DEFAULT_INPUT = REPO_ROOT / "local-private/research/target-family/metadata-inventory-pfam-v1.json"
DEFAULT_OUTPUT = (
    REPO_ROOT / "data/runtime/target-family/sequence-clusters-pfam-v1/"
    "target-family-sequence-clusters-pfam-v1.json"
)
MAX_RECORDS = 100
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_IDENTITY_THRESHOLD = 0.90
_PDB_ID_RE = re.compile(r"^[A-Z0-9]{4}$")


class SequenceClusterMaterializationError(RuntimeError):
    """Raised when metadata cannot satisfy the sequence-cluster contract."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SequenceClusterMaterializationError(f"{field} must be a non-empty string")
    return value.strip()


def _family_id(payload: Mapping[str, Any]) -> str:
    value = payload.get("family_id")
    if not isinstance(value, str) or not value.strip():
        source = payload.get("source")
        value = source.get("family_id") if isinstance(source, Mapping) else None
    return _required_text(value, "family_id").upper()


def _inventory_records(
    payload: Mapping[str, Any], *, max_records: int
) -> tuple[str, list[Mapping[str, Any]]]:
    if payload.get("schema_version") != INVENTORY_SCHEMA_VERSION:
        raise SequenceClusterMaterializationError("metadata inventory schema is unsupported")
    if not 1 <= max_records <= MAX_RECORDS:
        raise ValueError(f"max_records must be between 1 and {MAX_RECORDS}")
    raw_records = payload.get("records")
    if not isinstance(raw_records, list) or not 1 <= len(raw_records) <= MAX_RECORDS:
        raise SequenceClusterMaterializationError(
            "metadata inventory record count is outside the bound"
        )
    declared_count = payload.get("record_count")
    if declared_count is not None and declared_count != len(raw_records):
        raise SequenceClusterMaterializationError(
            "metadata inventory record count does not match records"
        )
    if len(raw_records) > max_records:
        raise SequenceClusterMaterializationError(
            f"metadata inventory exceeds maximum record bound ({max_records})"
        )
    if any(not isinstance(record, Mapping) for record in raw_records):
        raise SequenceClusterMaterializationError("metadata inventory records must be objects")

    family_id = _family_id(payload)
    records: list[Mapping[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_record in raw_records:
        if not isinstance(raw_record, Mapping):
            continue
        pdb_id = _required_text(raw_record.get("pdb_id"), "record.pdb_id").upper()
        if _PDB_ID_RE.fullmatch(pdb_id) is None:
            raise SequenceClusterMaterializationError(
                "record.pdb_id must be a four-character PDB ID"
            )
        if pdb_id in seen_ids:
            raise SequenceClusterMaterializationError(
                "metadata inventory structure IDs must be unique"
            )
        seen_ids.add(pdb_id)
        record_family = _required_text(raw_record.get("family_id"), "record.family_id").upper()
        if record_family != family_id:
            raise SequenceClusterMaterializationError("metadata inventory contains another family")
        raw_uniprots = raw_record.get("uniprot_ids")
        if not isinstance(raw_uniprots, list) or not raw_uniprots:
            raise SequenceClusterMaterializationError("record.uniprot_ids must be a non-empty list")
        for value in raw_uniprots:
            _required_text(value, "record.uniprot_ids[]")
        try:
            declared_length = int(str(raw_record.get("sequence_length")))
        except (TypeError, ValueError) as exc:
            raise SequenceClusterMaterializationError(
                "record.sequence_length must be an integer"
            ) from exc
        if declared_length <= 0:
            raise SequenceClusterMaterializationError("record.sequence_length must be positive")
        records.append(raw_record)
    return family_id, records


def _api_json(session: requests.Session, url: str, *, timeout: int) -> Mapping[str, Any]:
    if ".pdb" in url.casefold() or ".cif" in url.casefold() or ".mmcif" in url.casefold():
        raise SequenceClusterMaterializationError("coordinate URL is outside the metadata boundary")
    try:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise SequenceClusterMaterializationError(f"RCSB metadata request failed: {url}") from exc
    except (TypeError, ValueError) as exc:
        raise SequenceClusterMaterializationError(f"RCSB metadata JSON is invalid: {url}") from exc
    if not isinstance(payload, Mapping):
        raise SequenceClusterMaterializationError(f"RCSB metadata response is not an object: {url}")
    return payload


def _polymer_entity_ids(entry: Mapping[str, Any], *, pdb_id: str) -> list[str]:
    identifiers = entry.get("rcsb_entry_container_identifiers")
    if not isinstance(identifiers, Mapping):
        raise SequenceClusterMaterializationError(
            f"entry {pdb_id} has no polymer entity identifiers"
        )
    values = identifiers.get("polymer_entity_ids")
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise SequenceClusterMaterializationError(
            f"entry {pdb_id} has invalid polymer entity identifiers"
        )
    entity_ids = sorted({str(value).strip() for value in values if str(value).strip()})
    if not entity_ids:
        raise SequenceClusterMaterializationError(f"entry {pdb_id} has no polymer entities")
    return entity_ids


def _uniprot_ids(entity: Mapping[str, Any]) -> tuple[str, ...]:
    identifiers = entity.get("rcsb_polymer_entity_container_identifiers")
    if not isinstance(identifiers, Mapping):
        return ()
    values: set[str] = set()
    for value in identifiers.get("uniprot_ids", []):
        if value:
            values.add(str(value).strip().upper())
    for item in identifiers.get("reference_sequence_identifiers", []):
        if (
            isinstance(item, Mapping)
            and str(item.get("database_name", "")).casefold() == "uniprot"
            and item.get("database_accession")
        ):
            values.add(str(item["database_accession"]).strip().upper())
    return tuple(sorted(value for value in values if value))


def _normalize_sequence(value: Any) -> str:
    normalized = "".join(str(value or "").split()).upper()
    if normalized.endswith("*"):
        normalized = normalized.rstrip("*")
    if not normalized:
        raise SequenceClusterMaterializationError("polymer entity has no canonical sequence")
    if any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" for character in normalized):
        raise SequenceClusterMaterializationError(
            "polymer entity sequence contains unexpected characters"
        )
    return normalized


def _protein_sequence(entity: Mapping[str, Any], *, pdb_id: str, entity_id: str) -> str | None:
    entity_poly = entity.get("entity_poly")
    if not isinstance(entity_poly, Mapping):
        return None
    polymer_type = str(entity_poly.get("rcsb_entity_polymer_type", "")).casefold()
    if polymer_type != "protein":
        return None
    raw_sequence = entity_poly.get("pdbx_seq_one_letter_code_can") or entity_poly.get(
        "pdbx_seq_one_letter_code"
    )
    try:
        return _normalize_sequence(raw_sequence)
    except SequenceClusterMaterializationError as exc:
        raise SequenceClusterMaterializationError(
            f"protein entity {pdb_id}_{entity_id} has no usable sequence"
        ) from exc


def _fetch_record_sequence(
    session: requests.Session,
    record: Mapping[str, Any],
    *,
    timeout: int,
) -> dict[str, Any]:
    pdb_id = _required_text(record.get("pdb_id"), "record.pdb_id").upper()
    expected_uniprots = {
        _required_text(value, "record.uniprot_ids[]").upper()
        for value in record.get("uniprot_ids", [])
    }
    entry = _api_json(session, f"{DATA_URL}/entry/{pdb_id}", timeout=timeout)
    candidates: list[tuple[str, tuple[str, ...], str]] = []
    for entity_id in _polymer_entity_ids(entry, pdb_id=pdb_id):
        entity = _api_json(
            session,
            f"{DATA_URL}/polymer_entity/{pdb_id}/{entity_id}",
            timeout=timeout,
        )
        entity_uniprots = _uniprot_ids(entity)
        if not expected_uniprots.intersection(entity_uniprots):
            continue
        sequence = _protein_sequence(entity, pdb_id=pdb_id, entity_id=entity_id)
        if sequence is not None:
            candidates.append((entity_id, entity_uniprots, sequence))
    if not candidates:
        raise SequenceClusterMaterializationError(
            f"entry {pdb_id} has no matching protein entity for the inventory UniProt group"
        )

    declared_length = int(str(record["sequence_length"]))
    candidates.sort(key=lambda item: (abs(len(item[2]) - declared_length), item[0]))
    best_distance = abs(len(candidates[0][2]) - declared_length)
    best = [item for item in candidates if abs(len(item[2]) - declared_length) == best_distance]
    if len({hashlib.sha256(item[2].encode("ascii")).hexdigest() for item in best}) > 1:
        raise SequenceClusterMaterializationError(
            f"entry {pdb_id} has ambiguous matching protein entity sequences"
        )
    entity_id, entity_uniprots, sequence = best[0]
    return {
        "pdb_id": pdb_id,
        "family_id": _required_text(record.get("family_id"), "record.family_id").upper(),
        "uniprot_ids": sorted(expected_uniprots),
        "entity_id": entity_id,
        "entity_uniprot_ids": list(entity_uniprots),
        "declared_sequence_length": declared_length,
        "sequence_length": len(sequence),
        "sequence_sha256": hashlib.sha256(sequence.encode("ascii")).hexdigest(),
        "sequence": sequence,
    }


def _aligner() -> PairwiseAligner:
    aligner = PairwiseAligner()
    aligner.mode = "global"
    aligner.match_score = 1
    aligner.mismatch_score = 0
    aligner.open_gap_score = -1
    aligner.extend_gap_score = -0.1
    return aligner


def global_sequence_identity(sequence_a: str, sequence_b: str) -> float:
    """Return global identity divided by the longer input sequence length."""

    first = _normalize_sequence(sequence_a)
    second = _normalize_sequence(sequence_b)
    alignment = _aligner().align(first, second)[0]
    counts = alignment.counts()
    return float(counts.identities) / float(max(len(first), len(second)))


def _union_find(size: int) -> tuple[list[int], Any, Any]:
    parents = list(range(size))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root != second_root:
            parents[second_root] = first_root

    return parents, find, union


def cluster_sequence_records(
    records: Sequence[Mapping[str, Any]], *, identity_threshold: float = DEFAULT_IDENTITY_THRESHOLD
) -> dict[str, Any]:
    """Cluster sequence-bearing records with a deterministic review method."""

    if not 0 < identity_threshold <= 1:
        raise ValueError("identity_threshold must be in (0, 1]")
    prepared: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_record in records:
        if not isinstance(raw_record, Mapping):
            raise SequenceClusterMaterializationError("sequence records must be objects")
        pdb_id = _required_text(raw_record.get("pdb_id"), "sequence_record.pdb_id").upper()
        if pdb_id in seen_ids:
            raise SequenceClusterMaterializationError("sequence record PDB IDs must be unique")
        seen_ids.add(pdb_id)
        sequence = _normalize_sequence(raw_record.get("sequence"))
        sequence_hash = hashlib.sha256(sequence.encode("ascii")).hexdigest()
        prepared.append(
            {
                **dict(raw_record),
                "pdb_id": pdb_id,
                "sequence": sequence,
                "sequence_sha256": sequence_hash,
            }
        )
    prepared.sort(key=lambda item: str(item["pdb_id"]))

    parents, find, union = _union_find(len(prepared))
    comparisons = 0
    threshold_edges = 0
    identity_cache: dict[tuple[str, str], float] = {}
    for first in range(len(prepared)):
        for second in range(first + 1, len(prepared)):
            first_hash = str(prepared[first]["sequence_sha256"])
            second_hash = str(prepared[second]["sequence_sha256"])
            cache_key = (
                (first_hash, second_hash)
                if first_hash <= second_hash
                else (second_hash, first_hash)
            )
            identity = identity_cache.get(cache_key)
            if identity is None:
                identity = (
                    1.0
                    if first_hash == second_hash
                    else global_sequence_identity(
                        str(prepared[first]["sequence"]), str(prepared[second]["sequence"])
                    )
                )
                identity_cache[cache_key] = identity
            comparisons += 1
            if identity >= identity_threshold:
                threshold_edges += 1
                union(first, second)

    groups: dict[int, list[dict[str, Any]]] = {}
    for index, record in enumerate(prepared):
        groups.setdefault(find(index), []).append(record)
    cluster_members = sorted(
        (
            sorted(member["pdb_id"] for member in members),
            members,
        )
        for members in groups.values()
    )

    cluster_id_by_root: dict[int, str] = {}
    clusters: list[dict[str, Any]] = []
    for member_ids, members in cluster_members:
        hashes = sorted(str(member["sequence_sha256"]) for member in members)
        cluster_id = f"scv1-{_stable_hash(hashes)[:16]}"
        root = find(prepared.index(members[0]))
        cluster_id_by_root[root] = cluster_id
        clusters.append(
            {
                "sequence_cluster_id": cluster_id,
                "member_count": len(members),
                "member_pdb_ids": member_ids,
                "member_uniprot_groups": sorted(
                    {uniprot for member in members for uniprot in member.get("uniprot_ids", [])}
                ),
                "member_sequence_sha256": hashes,
            }
        )

    output_records: list[dict[str, Any]] = []
    for index, record in enumerate(prepared):
        output = {key: value for key, value in record.items() if key != "sequence"}
        output["sequence_cluster_id"] = cluster_id_by_root[find(index)]
        output["sequence_cluster_size"] = len(groups[find(index)])
        output_records.append(output)
    output_records.sort(key=lambda item: str(item["pdb_id"]))
    clusters.sort(key=lambda item: str(item["sequence_cluster_id"]))
    return {
        "method": {
            "id": "global_pairwise_identity_v1",
            "mode": "global",
            "identity_denominator": "max_sequence_length",
            "match_score": 1,
            "mismatch_score": 0,
            "open_gap_score": -1,
            "extend_gap_score": -0.1,
            "identity_threshold": identity_threshold,
            "linkage": "single_linkage_connected_components",
        },
        "cluster_count": len(clusters),
        "pairwise_comparison_count": comparisons,
        "threshold_edge_count": threshold_edges,
        "clusters": clusters,
        "records": output_records,
        "review_required": True,
    }


def materialize_sequence_clusters(
    payload: Mapping[str, Any],
    *,
    session: requests.Session,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_records: int = MAX_RECORDS,
    identity_threshold: float = DEFAULT_IDENTITY_THRESHOLD,
) -> dict[str, Any]:
    """Fetch bounded sequence metadata and return a local review report."""

    if timeout <= 0:
        raise ValueError("timeout must be positive")
    family_id, records = _inventory_records(payload, max_records=max_records)
    fetched = [_fetch_record_sequence(session, record, timeout=timeout) for record in records]
    clustered = cluster_sequence_records(fetched, identity_threshold=identity_threshold)
    report: dict[str, Any] = {
        "schema_version": CLUSTER_SCHEMA_VERSION,
        "status": "sequence_materialized_review_required",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "family_id": family_id,
        "input_inventory_sha256": str(payload.get("inventory_sha256") or _stable_hash(payload)),
        "record_count": len(records),
        "materialized_record_count": len(fetched),
        "worker_count": 1,
        "source": {
            "provider": "RCSB PDB Data API",
            "data_url": DATA_URL,
            "entry_endpoint": f"{DATA_URL}/entry/{{pdb_id}}",
            "polymer_entity_endpoint": f"{DATA_URL}/polymer_entity/{{pdb_id}}/{{entity_id}}",
            "coordinate_files_downloaded": False,
        },
        "cluster_method": clustered["method"],
        "cluster_count": clustered["cluster_count"],
        "pairwise_comparison_count": clustered["pairwise_comparison_count"],
        "threshold_edge_count": clustered["threshold_edge_count"],
        "clusters": clustered["clusters"],
        "records": clustered["records"],
        "sequence_clusters": "materialized_review_required",
        "contact_labels": "not_materialized",
        "coordinates_downloaded": False,
        "detector_started": False,
        "benchmark_started": False,
        "ml_training_started": False,
        "claims_authorized": False,
        "next_gate": "independent_contact_label_curation_and_leakage_audited_cohort",
    }
    report["report_sha256"] = _stable_hash(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    return report


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SequenceClusterMaterializationError(
            f"cannot read metadata inventory: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise SequenceClusterMaterializationError("metadata inventory must be a JSON object")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def run_sequence_cluster_materializer(
    *,
    input_path: Path = DEFAULT_INPUT,
    output_path: Path = DEFAULT_OUTPUT,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_records: int = MAX_RECORDS,
    identity_threshold: float = DEFAULT_IDENTITY_THRESHOLD,
) -> dict[str, Any]:
    session = requests.Session()
    session.headers.update({"User-Agent": "BioVoid/0.1 target-family sequence review"})
    try:
        report = materialize_sequence_clusters(
            _read_json(input_path.resolve()),
            session=session,
            timeout=timeout,
            max_records=max_records,
            identity_threshold=identity_threshold,
        )
    finally:
        session.close()
    _write_json(output_path.resolve(), report)
    print(
        f"target-family sequence clusters: records={report['record_count']} "
        f"clusters={report['cluster_count']} threshold={identity_threshold:.2f}"
    )
    print(f"sequence-cluster report: {output_path}")
    print("coordinate files downloaded: no")
    print("detector/benchmark/NMA/ML started: no")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-records", type=int, default=MAX_RECORDS)
    parser.add_argument("--identity-threshold", type=float, default=DEFAULT_IDENTITY_THRESHOLD)
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="required acknowledgement before requesting RCSB metadata JSON",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.allow_network:
        print("sequence-cluster materialization requires --allow-network", file=sys.stderr)
        return 2
    try:
        run_sequence_cluster_materializer(
            input_path=args.input,
            output_path=args.output,
            timeout=args.timeout,
            max_records=args.max_records,
            identity_threshold=args.identity_threshold,
        )
    except (SequenceClusterMaterializationError, ValueError) as exc:
        print(f"target-family sequence-cluster error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Materialize and prepare a bounded, ligand-blind RI-3 development set.

The script reads only the selected ZIP members through HTTP Range requests. It
never downloads the full CryptoBench archive, reads evaluator metadata, starts
a detector, runs NMA, or opens the sealed split. Generated structures and
reports are written below ignored ``data/runtime/ri3`` storage.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_ri2_manifest import (  # noqa: E402
    DEFAULT_API_ROOT,
    enumerate_osf_files,
    resolve_osf_download_link,
)
from scripts.check_ri3_readiness import (  # noqa: E402
    _read_range,
    _sha256,
    _verified_local_json,
)
from src.cryptobench_archive import (  # noqa: E402
    ZipMember,
    decode_member_payload,
    member_map,
    parse_local_file_header,
)
from src.structure_preparation import (  # noqa: E402
    PreparationConfig,
    PreparationError,
    StructureSource,
    prepare_structure,
)


DEFAULT_LOCK = REPO_ROOT / "local-private/research/ri-1-lock-v1.json"
DEFAULT_METADATA_DIR = REPO_ROOT / "data/runtime/cryptobench-source/metadata"
DEFAULT_MEMBER_INDEX = REPO_ROOT / "data/runtime/ri3/cryptobench-cif-member-index-v1.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data/runtime/ri3"
DEFAULT_MEMBER_DIR = DEFAULT_OUTPUT_DIR / "materialized-members"
DEFAULT_PREPARED_DIR = DEFAULT_OUTPUT_DIR / "prepared-development"
DEFAULT_REPORT = DEFAULT_OUTPUT_DIR / "cryptobench-preparation-preflight-v1.json"
MAX_LOCAL_HEADER_RANGE = 256 * 1024
MAX_MEMBER_RANGE = 64 * 1024 * 1024
MAX_UNCOMPRESSED_MEMBER = 128 * 1024 * 1024
DEFAULT_MAX_COMPRESSED_BYTES = 256 * 1024 * 1024


class MaterializationError(RuntimeError):
    """Raised when a selected source member cannot be verified safely."""


def _resolve_repo_path(value: Path) -> Path:
    """Resolve CLI paths relative to the BioVoid repository, not the shell cwd."""

    candidate = value if value.is_absolute() else REPO_ROOT / value
    return candidate.resolve()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    content = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at_utc", "preflight_sha256"}
    }
    return hashlib.sha256(
        json.dumps(content, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _normalize_structure_id(value: str) -> str:
    normalized = str(value).strip().lower()
    if len(normalized) != 4 or not normalized.isalnum():
        raise MaterializationError(f"Invalid structure ID: {value!r}")
    return normalized


def _chain_ids(records: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    chains: set[str] = set()
    for record in records:
        for raw_chain in str(record.get("apo_chain", "")).split("-"):
            chain = raw_chain.strip()
            if chain:
                chains.add(chain)
    if not chains:
        raise MaterializationError("No apo chains are declared for structure")
    return tuple(sorted(chains))


def _split_structure_ids(folds: Mapping[str, Sequence[str]]) -> tuple[str, ...]:
    values = [
        _normalize_structure_id(value)
        for fold_name in ("train-0", "train-1", "train-2")
        for value in folds.get(fold_name, [])
    ]
    if len(values) != len(set(values)):
        raise MaterializationError("Development folds contain duplicate structure IDs")
    return tuple(sorted(values))


def _load_archive_context(
    session: requests.Session,
    lock: Mapping[str, Any],
    member_index_path: Path,
) -> tuple[str, int, Mapping[str, Any], Mapping[str, ZipMember]]:
    if not member_index_path.is_file():
        raise MaterializationError(
            f"Member index is missing; run scripts/check_ri3_readiness.py first: "
            f"{member_index_path}"
        )
    index = json.loads(member_index_path.read_text(encoding="utf-8"))
    archive_lock = lock["dataset"]["structure_archive"]
    archive = index.get("archive", {})
    for key in ("path", "file_id", "sha256", "size"):
        if archive.get(key) != archive_lock[key]:
            raise MaterializationError(f"Member index archive {key} differs from RI-1 lock")
    members = member_map(
        tuple(
            ZipMember(
                name=str(member["name"]),
                compression_method=int(member["compression_method"]),
                flags=int(member["flags"]),
                crc32=int(str(member["crc32"]), 16),
                compressed_size=int(member["compressed_size"]),
                uncompressed_size=int(member["uncompressed_size"]),
                local_header_offset=int(member["local_header_offset"]),
            )
            for member in index.get("members", [])
        )
    )
    inventory = enumerate_osf_files(DEFAULT_API_ROOT, session=session)
    archive_record = next(
        (
            record
            for record in inventory
            if str(record.get("path", "")).casefold().endswith("/cif-files.zip")
        ),
        None,
    )
    if archive_record is None or archive_record.get("file_id") != archive_lock["file_id"]:
        raise MaterializationError("Locked OSF CIF archive is unavailable")
    download_url = resolve_osf_download_link(session, str(archive_record["api_locator"]))
    response = session.head(download_url, allow_redirects=True, timeout=60)
    response.raise_for_status()
    remote_size = int(response.headers.get("Content-Length", "0"))
    if remote_size != int(archive_lock["size"]):
        raise MaterializationError("OSF archive size changed before member materialization")
    return response.url, remote_size, archive_lock, members


def _materialize_member(
    session: requests.Session,
    download_url: str,
    archive_size: int,
    member: ZipMember,
    destination: Path,
) -> tuple[str, int]:
    if member.compressed_size > MAX_MEMBER_RANGE:
        raise MaterializationError(
            f"Member compressed size exceeds safety limit: {member.name}"
        )
    combined_end = min(
        archive_size - 1,
        member.local_header_offset
        + MAX_LOCAL_HEADER_RANGE
        + member.compressed_size
        - 1,
    )
    combined = _read_range(
        session,
        download_url,
        start=member.local_header_offset,
        end=combined_end,
        max_range_bytes=MAX_LOCAL_HEADER_RANGE + MAX_MEMBER_RANGE,
    )
    data_offset = parse_local_file_header(combined, member=member)
    data_end = data_offset + member.compressed_size
    if data_end > len(combined):
        raise MaterializationError(f"Member data range is incomplete: {member.name}")
    if member.local_header_offset + data_end > archive_size:
        raise MaterializationError(f"Member data exceeds archive boundary: {member.name}")
    compressed = combined[data_offset:data_end]
    content = decode_member_payload(compressed, member=member)
    if len(content) > MAX_UNCOMPRESSED_MEMBER:
        raise MaterializationError(f"Member uncompressed size exceeds safety limit: {member.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(destination)
    return _sha256(content), len(compressed)


def _reuse_preparation(
    member_path: Path,
    prepared_root: Path,
    structure_id: str,
    member: ZipMember,
) -> dict[str, Any] | None:
    """Reuse a complete ignored preparation created by an earlier pass."""

    output_dir = prepared_root / structure_id
    report_path = output_dir / "preparation_report.json"
    manifest_path = output_dir / "run_manifest.json"
    prepared_path = output_dir / "prepared_detector.pdb"
    if not (member_path.is_file() and report_path.is_file() and manifest_path.is_file() and prepared_path.is_file()):
        return None
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hashes = report.get("hashes", {})
    manifest_hashes = manifest.get("hashes", {})
    input_sha256 = _sha256(member_path.read_bytes())
    if input_sha256 != hashes.get("input_sha256"):
        return None
    if manifest_hashes.get("input_sha256") != input_sha256:
        return None
    if report.get("status") != "valid" or manifest.get("preparation_status") != "valid":
        return None
    return {
        "status": "eligible",
        "structure_id": structure_id.upper(),
        "selected_chains": report.get("selected_chains", []),
        "member_path": member_path.relative_to(REPO_ROOT).as_posix(),
        "prepared_path": prepared_path.relative_to(REPO_ROOT).as_posix(),
        "input_sha256": input_sha256,
        "prepared_sha256": hashes.get("prepared_sha256"),
        "preparation_config_sha256": hashes.get("preparation_config_sha256"),
        "preparation_report_sha256": _sha256(report_path.read_bytes()),
        "protein_residue_count": report["counts"]["protein_residues_selected"],
        "protein_atom_count": report["counts"]["protein_atoms_selected"],
        "missing_backbone_residues": report["counts"]["missing_backbone_residues"],
        "warnings": report.get("warnings", []),
        "reused_local": True,
    }


def _prepare_member(
    member_path: Path,
    prepared_root: Path,
    structure_id: str,
    records: Sequence[Mapping[str, Any]],
    *,
    snapshot_id: str,
    archive: Mapping[str, Any],
    member: ZipMember,
) -> dict[str, Any]:
    chain_ids = _chain_ids(records)
    output_dir = prepared_root / structure_id
    if output_dir.exists():
        raise MaterializationError(f"Preparation output already exists: {output_dir}")
    source = StructureSource(
        provider="local",
        identifier=structure_id,
        representation="local",
        local_path=member_path,
    )
    config = PreparationConfig(chain_ids=chain_ids)
    result = prepare_structure(
        member_path,
        source,
        config,
        output_dir,
        f"ri3-preflight-{structure_id}",
        source_metadata={
            "dataset_snapshot_id": snapshot_id,
            "archive_path": archive["path"],
            "archive_file_id": archive["file_id"],
            "archive_member_name": member.name,
            "archive_member_crc32": f"{member.crc32:08x}",
            "archive_member_uncompressed_size": member.uncompressed_size,
        },
        analysis_config={
            "protocol_id": "phase6-cryptobench-v1",
            "preparation_profile_id": "cryptobench-apo-file-v1",
            "resource_profile": "safe-16gb",
        },
    )
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    return {
        "status": "eligible",
        "structure_id": structure_id.upper(),
        "selected_chains": list(chain_ids),
        "member_path": member_path.relative_to(REPO_ROOT).as_posix(),
        "prepared_path": result.prepared_path.relative_to(REPO_ROOT).as_posix(),
        "input_sha256": result.input_sha256,
        "prepared_sha256": result.prepared_sha256,
        "preparation_config_sha256": result.config_sha256,
        "preparation_report_sha256": result.report_sha256,
        "protein_residue_count": report["counts"]["protein_residues_selected"],
        "protein_atom_count": report["counts"]["protein_atoms_selected"],
        "missing_backbone_residues": report["counts"]["missing_backbone_residues"],
        "warnings": report["warnings"],
    }


def _select_ids(
    development_ids: Sequence[str],
    requested_ids: Sequence[str],
    *,
    limit: int,
    all_development: bool,
) -> tuple[str, ...]:
    normalized_development = {
        _normalize_structure_id(value) for value in development_ids
    }
    if requested_ids and all_development:
        raise MaterializationError("Use either --structure-id or --all-development, not both")
    if all_development:
        return tuple(sorted(normalized_development))
    if requested_ids:
        selected = tuple(dict.fromkeys(_normalize_structure_id(value) for value in requested_ids))
        missing = sorted(set(selected) - normalized_development)
        if missing:
            raise MaterializationError(f"Requested structures are not in development: {missing}")
        return tuple(sorted(selected))
    if limit < 1:
        raise MaterializationError("--limit must be positive")
    return tuple(sorted(normalized_development)[:limit])


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--metadata-dir", type=Path, default=DEFAULT_METADATA_DIR)
    parser.add_argument("--member-index", type=Path, default=DEFAULT_MEMBER_INDEX)
    parser.add_argument("--member-dir", type=Path, default=DEFAULT_MEMBER_DIR)
    parser.add_argument("--prepared-dir", type=Path, default=DEFAULT_PREPARED_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--structure-id", action="append", default=[])
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--all-development", action="store_true")
    parser.add_argument(
        "--max-compressed-bytes",
        type=int,
        default=DEFAULT_MAX_COMPRESSED_BYTES,
        help="Safety budget for selected compressed member bytes.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--retrieved-utc", default=None)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    args.lock = _resolve_repo_path(args.lock)
    args.metadata_dir = _resolve_repo_path(args.metadata_dir)
    args.member_index = _resolve_repo_path(args.member_index)
    args.member_dir = _resolve_repo_path(args.member_dir)
    args.prepared_dir = _resolve_repo_path(args.prepared_dir)
    args.report = _resolve_repo_path(args.report)
    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    metadata_lock = lock["dataset"]["metadata_files"]
    dataset = _verified_local_json(
        args.metadata_dir / "dataset.json", metadata_lock["dataset.json"]["sha256"]
    )
    folds = _verified_local_json(
        args.metadata_dir / "folds.json", metadata_lock["folds.json"]["sha256"]
    )
    development_ids = _split_structure_ids(folds)
    selected_ids = _select_ids(
        development_ids,
        args.structure_id,
        limit=args.limit,
        all_development=args.all_development,
    )
    member_index = json.loads(args.member_index.read_text(encoding="utf-8"))
    lookup = member_map(
        tuple(
            ZipMember(
                name=str(member["name"]),
                compression_method=int(member["compression_method"]),
                flags=int(member["flags"]),
                crc32=int(str(member["crc32"]), 16),
                compressed_size=int(member["compressed_size"]),
                uncompressed_size=int(member["uncompressed_size"]),
                local_header_offset=int(member["local_header_offset"]),
            )
            for member in member_index.get("members", [])
        )
    )
    selected_members: dict[str, ZipMember] = {}
    for structure_id in selected_ids:
        member = lookup.get(f"cif-files/{structure_id}.cif")
        if member is None:
            raise MaterializationError(f"CIF member is missing from index: {structure_id}")
        selected_members[structure_id] = member
    compressed_budget = sum(member.compressed_size for member in selected_members.values())
    if compressed_budget > args.max_compressed_bytes:
        raise MaterializationError(
            f"Selected compressed bytes exceed safety budget: {compressed_budget} > "
            f"{args.max_compressed_bytes}"
        )
    print(
        f"selected structures: {len(selected_ids)}; compressed member budget: "
        f"{compressed_budget / (1024 * 1024):.1f} MiB"
    )
    if args.dry_run:
        print("dry-run: no network request, structure extraction, or preparation started")
        return 0

    session = requests.Session()
    session.headers.update({"User-Agent": "BioVoid/0.1 RI-3 materialization"})
    records: list[dict[str, Any]] = []
    try:
        download_url, archive_size, archive, _ = _load_archive_context(
            session,
            lock,
            args.member_index,
        )
        for index, structure_id in enumerate(selected_ids, start=1):
            member = selected_members[structure_id]
            member_path = args.member_dir / f"{structure_id}.cif"
            base = {
                "structure_id": structure_id.upper(),
                "split": "development",
                "member": {
                    "name": member.name,
                    "crc32": f"{member.crc32:08x}",
                    "compressed_size": member.compressed_size,
                    "uncompressed_size": member.uncompressed_size,
                },
            }
            try:
                prepared = _reuse_preparation(
                    member_path,
                    args.prepared_dir,
                    structure_id,
                    member,
                )
                if prepared is not None:
                    compressed_bytes = 0
                else:
                    input_sha256, compressed_bytes = _materialize_member(
                        session,
                        download_url,
                        archive_size,
                        member,
                        member_path,
                    )
                    prepared = _prepare_member(
                        member_path,
                        args.prepared_dir,
                        structure_id,
                        dataset[structure_id],
                        snapshot_id=lock["dataset"]["snapshot_id"],
                        archive=archive,
                        member=member,
                    )
                base.update(
                    {
                        "status": "eligible",
                        "compressed_bytes_read": compressed_bytes,
                        "source_file_sha256": prepared["input_sha256"],
                        "preparation": prepared,
                    }
                )
            except (PreparationError, ValueError) as exc:
                base.update(
                    {
                        "status": "ineligible",
                        "reason_code": "structure_preparation_rejected",
                        "error": str(exc),
                    }
                )
            except (MaterializationError, OSError, requests.RequestException) as exc:
                base.update(
                    {
                        "status": "unavailable",
                        "reason_code": "member_materialization_failed",
                        "error": str(exc),
                    }
                )
            records.append(base)
            print(f"processed {index}/{len(selected_ids)}: {structure_id.upper()} ({base['status']})")
    finally:
        session.close()

    counts = Counter(record["status"] for record in records)
    report: dict[str, Any] = {
        "schema_version": "biovoid-ri3-preparation-preflight-v1",
        "status": "pass" if counts.get("eligible", 0) == len(records) else "completed_with_failures",
        "snapshot_id": lock["dataset"]["snapshot_id"],
        "split": "development",
        "selection": {
            "structure_count": len(selected_ids),
            "structure_ids_sha256": _sha256("\n".join(selected_ids).encode("utf-8")),
            "all_development_requested": args.all_development,
            "selection_limit": args.limit,
        },
        "archive": {
            "path": lock["dataset"]["structure_archive"]["path"],
            "file_id": lock["dataset"]["structure_archive"]["file_id"],
            "sha256": lock["dataset"]["structure_archive"]["sha256"],
            "size": lock["dataset"]["structure_archive"]["size"],
            "materialization_mode": "http-range-local-header-and-member-data",
            "full_archive_downloaded": False,
        },
        "materialization": {
            "selected_member_compressed_bytes": sum(
                record["member"]["compressed_size"] for record in records
            ),
            "selected_member_uncompressed_bytes": sum(
                record["member"]["uncompressed_size"] for record in records
            ),
            "compressed_bytes_read_current_run": sum(
                int(record.get("compressed_bytes_read", 0)) for record in records
            ),
            "network_materialized_count_current_run": sum(
                int(record.get("compressed_bytes_read", 0)) > 0 for record in records
            ),
            "local_reuse_count_current_run": sum(
                bool(record.get("preparation", {}).get("reused_local", False))
                for record in records
            ),
        },
        "coverage": {
            "selected_structures": len(records),
            "eligible": counts.get("eligible", 0),
            "ineligible": counts.get("ineligible", 0),
            "unavailable": counts.get("unavailable", 0),
        },
        "detector_started": False,
        "nma_started": False,
        "sealed_evaluation_authorized": False,
        "records": records,
        "generated_at_utc": args.retrieved_utc or datetime.now(timezone.utc).isoformat(),
        "preflight_sha256": None,
    }
    report["preflight_sha256"] = _canonical_hash(report)
    _write_json(args.report, report)
    print(f"preparation preflight: {report['status']}")
    print(
        "eligible/ineligible/unavailable: "
        f"{counts.get('eligible', 0)}/{counts.get('ineligible', 0)}/"
        f"{counts.get('unavailable', 0)}"
    )
    print(f"report: {args.report}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

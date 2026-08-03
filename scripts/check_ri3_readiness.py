"""Run the lightweight RI-3 entry preflight.

This command checks the locked OSF archive through HEAD and HTTP Range
requests, validates its ZIP member inventory, checks protocol parity, and
records available baseline-overlap metadata. It never downloads the full CIF
archive, extracts a structure, installs a tool, or starts a benchmark.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Mapping

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_ri2_manifest import (  # noqa: E402
    DEFAULT_API_ROOT,
    enumerate_osf_files,
    resolve_osf_download_link,
)
from src.benchmark_v1 import phase6_frozen_protocol_v1  # noqa: E402
from src.cryptobench_adapter import family_group_id  # noqa: E402
from src.cryptobench_archive import (  # noqa: E402
    ZipMember,
    member_map,
    parse_central_directory,
    parse_end_of_central_directory,
)


DEFAULT_METADATA_DIR = REPO_ROOT / "data/runtime/cryptobench-source/metadata"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data/runtime/ri3"
DEFAULT_LOCK = REPO_ROOT / "local-private/research/ri-1-lock-v1.json"
DEFAULT_TAIL_BYTES = 4 * 1024 * 1024
MAX_RANGE_BYTES = 16 * 1024 * 1024
POCKETMINER_REFERENCE_PATH = "src/F-statistics/dataset-similarity/pocketminer-train-set.csv"
POCKETMINER_REFERENCE_URL = (
    "https://raw.githubusercontent.com/skrhakv/CryptoBench/"
    "9a3432f479325ca3c9fdc3b8612715ab5b6edecc/"
    + POCKETMINER_REFERENCE_PATH
)


class ReadinessError(RuntimeError):
    """Raised when a mandatory RI-3 source or contract check fails."""


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _get_json(session: requests.Session, url: str) -> Mapping[str, Any]:
    response = session.get(url, timeout=60)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise ReadinessError(f"Expected JSON object from {url}")
    return payload


def _verified_local_json(path: Path, expected_sha256: str) -> Any:
    content = path.read_bytes()
    actual = _sha256(content)
    if actual != expected_sha256:
        raise ReadinessError(f"Metadata hash mismatch for {path.name}: {actual}")
    return json.loads(content.decode("utf-8"))


def _read_range(
    session: requests.Session,
    url: str,
    *,
    start: int,
    end: int,
    max_range_bytes: int = MAX_RANGE_BYTES,
) -> bytes:
    expected_length = end - start + 1
    if expected_length <= 0 or expected_length > max_range_bytes:
        raise ReadinessError(f"Unsafe HTTP Range size: {expected_length}")
    response = session.get(
        url,
        headers={"Range": f"bytes={start}-{end}"},
        allow_redirects=True,
        stream=True,
        timeout=120,
    )
    if response.status_code != 206:
        response.close()
        raise ReadinessError(
            f"Archive server did not honor Range request: HTTP {response.status_code}"
        )
    content_range = response.headers.get("Content-Range", "")
    if not re.fullmatch(rf"bytes {start}-{end}/\d+", content_range):
        response.close()
        raise ReadinessError(f"Unexpected Content-Range: {content_range!r}")
    chunks: list[bytes] = []
    received = 0
    try:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            received += len(chunk)
            if received > expected_length:
                raise ReadinessError("Range response exceeded requested length")
            chunks.append(chunk)
    finally:
        response.close()
    content = b"".join(chunks)
    if len(content) != expected_length:
        raise ReadinessError(
            f"Range response length mismatch: expected {expected_length}, got {len(content)}"
        )
    return content


def _head_archive(session: requests.Session, download_url: str) -> tuple[str, int]:
    response = session.head(download_url, allow_redirects=True, timeout=60)
    response.raise_for_status()
    length = response.headers.get("Content-Length")
    if not length or not length.isdigit():
        raise ReadinessError("Archive HEAD response has no usable Content-Length")
    return response.url, int(length)


def _archive_index(
    session: requests.Session,
    download_url: str,
    *,
    archive_size: int,
) -> tuple[dict[str, Any], tuple[ZipMember, ...], int]:
    tail_size = min(DEFAULT_TAIL_BYTES, archive_size)
    tail_start = archive_size - tail_size
    tail = _read_range(session, download_url, start=tail_start, end=archive_size - 1)
    directory = parse_end_of_central_directory(tail, archive_size=archive_size)
    central_start = directory.central_directory_offset
    central_end = central_start + directory.central_directory_size - 1
    if central_start >= tail_start and central_end < archive_size:
        central = tail[central_start - tail_start : central_end - tail_start + 1]
        central_range_bytes = 0
    else:
        central = _read_range(session, download_url, start=central_start, end=central_end)
        central_range_bytes = len(central)
    members = parse_central_directory(central, expected_entry_count=directory.entry_count)
    metadata = {
        "entry_count": directory.entry_count,
        "central_directory_size": directory.central_directory_size,
        "central_directory_offset": directory.central_directory_offset,
        "comment_length": directory.comment_length,
        "tail_range": {"start": tail_start, "end": archive_size - 1, "bytes": len(tail)},
        "additional_central_range_bytes": central_range_bytes,
    }
    return metadata, members, len(tail) + central_range_bytes


def _dataset_chain_keys(dataset: Mapping[str, list[Mapping[str, Any]]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for apo_id, records in dataset.items():
        keys: set[str] = set()
        for record in records:
            for chain_id in str(record.get("apo_chain", "")).upper().split("-"):
                if chain_id.strip():
                    keys.add(f"{str(apo_id).upper()}.{chain_id.strip()}")
        result[str(apo_id).upper()] = keys
    return result


def _split_ids(folds: Mapping[str, list[str]], allocation: Mapping[str, list[str]]) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for split, fold_names in allocation.items():
        values = tuple(str(value).strip().lower() for fold in fold_names for value in folds[fold])
        if len(values) != len(set(values)):
            raise ReadinessError(f"Duplicate structure ID in {split} allocation")
        result[split] = values
    return result


def _check_family_split(
    dataset: Mapping[str, list[Mapping[str, Any]]],
    split_ids: Mapping[str, tuple[str, ...]],
) -> dict[str, list[str]]:
    family_to_splits: dict[str, set[str]] = {}
    for split, structure_ids in split_ids.items():
        for structure_id in structure_ids:
            records = dataset.get(structure_id)
            if records is None:
                raise ReadinessError(f"Structure missing from dataset metadata: {structure_id}")
            family = family_group_id(str(record.get("uniprot_id", "")) for record in records)
            family_to_splits.setdefault(family, set()).add(split)
    return {
        family: sorted(splits)
        for family, splits in family_to_splits.items()
        if len(splits) > 1
    }


def _pocketminer_overlap(
    session: requests.Session,
    dataset: Mapping[str, list[Mapping[str, Any]]],
    split_ids: Mapping[str, tuple[str, ...]],
) -> dict[str, Any]:
    response = session.get(POCKETMINER_REFERENCE_URL, timeout=60)
    response.raise_for_status()
    content = response.content
    if len(content) > 1024 * 1024:
        raise ReadinessError("PocketMiner overlap reference is unexpectedly large")
    reference_ids = {
        line.strip().upper()
        for line in content.decode("utf-8").splitlines()
        if line.strip()
    }
    chain_keys = _dataset_chain_keys(dataset)
    overlap: dict[str, list[str]] = {}
    for split, structure_ids in split_ids.items():
        available = {
            key for structure_id in structure_ids for key in chain_keys[structure_id.upper()]
        }
        overlap[split] = sorted(reference_ids & available)
    return {
        "reference_path": POCKETMINER_REFERENCE_PATH,
        "reference_url": POCKETMINER_REFERENCE_URL,
        "reference_sha256": _sha256(content),
        "reference_entry_count": len(reference_ids),
        "overlap_count_by_split": {split: len(values) for split, values in overlap.items()},
        "overlap_ids_sha256_by_split": {
            split: _sha256("\n".join(values).encode("utf-8")) for split, values in overlap.items()
        },
        "interpretation": "available_reference_only;_not_a_complete_model_training_audit",
    }


def _baseline_source_checks(session: requests.Session, lock: Mapping[str, Any]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for name in ("fpocket", "p2rank", "pocketminer"):
        baseline = lock["baselines"][name]
        repository = str(baseline["repository"])
        match = re.match(r"https://github\.com/([^/]+)/([^/]+)", repository)
        if not match:
            results[name] = {"commit_status": "invalid_repository_url"}
            continue
        owner, repo = match.groups()
        api_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{baseline['commit']}"
        response = session.get(
            api_url,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "BioVoid-ri3-readiness"},
            timeout=60,
        )
        resolved_sha = response.json().get("sha") if response.status_code == 200 else None
        results[name] = {
            "commit_status": "verified" if resolved_sha == baseline["commit"] else "unverified",
            "resolved_sha": resolved_sha,
            "pinned_sha": baseline["commit"],
        }
    results["local_executables"] = {
        "fpocket": shutil.which("fpocket"),
        "p2rank": shutil.which("p2rank"),
        "java": shutil.which("java"),
    }
    results["execution_status"] = (
        "ready_for_probe"
        if results["local_executables"]["fpocket"] and results["local_executables"]["p2rank"]
        else "external_tools_not_installed"
    )
    return results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-root", default=DEFAULT_API_ROOT)
    parser.add_argument("--metadata-dir", type=Path, default=DEFAULT_METADATA_DIR)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--retrieved-utc", default=None)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    metadata_lock = lock["dataset"]["metadata_files"]
    dataset = _verified_local_json(
        args.metadata_dir / "dataset.json", metadata_lock["dataset.json"]["sha256"]
    )
    folds = _verified_local_json(
        args.metadata_dir / "folds.json", metadata_lock["folds.json"]["sha256"]
    )
    session = requests.Session()
    session.headers.update({"User-Agent": "BioVoid/0.1 RI-3 readiness"})
    try:
        inventory = enumerate_osf_files(args.api_root, session=session)
        archive = next(
            (
                record
                for record in inventory
                if str(record.get("path", "")).casefold().endswith("/cif-files.zip")
            ),
            None,
        )
        if archive is None:
            raise ReadinessError("Locked OSF CIF archive is missing from inventory")
        archive_lock = lock["dataset"]["structure_archive"]
        if archive.get("path") != archive_lock["path"]:
            raise ReadinessError("OSF archive path drift detected")
        if archive.get("file_id") != archive_lock["file_id"]:
            raise ReadinessError("OSF archive file ID drift detected")
        if archive.get("sha256") != archive_lock["sha256"]:
            raise ReadinessError("OSF archive SHA-256 drift detected")
        if int(archive.get("size") or 0) != int(archive_lock["size"]):
            raise ReadinessError("OSF archive size drift detected")
        archive_hash_status = "locked"
        download_url = resolve_osf_download_link(session, str(archive["api_locator"]))
        final_url, archive_size = _head_archive(session, download_url)
        if archive_size != int(archive["size"]):
            raise ReadinessError("OSF archive size changed between metadata and HEAD")
        directory, members, range_bytes = _archive_index(
            session,
            final_url,
            archive_size=archive_size,
        )
        lookup = member_map(members)
        allocation = lock["dataset"]["split_allocation"]
        split_ids = _split_ids(folds, allocation)
        all_structure_ids = set().union(*split_ids.values())
        expected_members = {f"cif-files/{structure_id}.cif" for structure_id in all_structure_ids}
        expected_lookup = {name.casefold() for name in expected_members}
        missing_members = sorted(expected_lookup - set(lookup))
        if missing_members:
            raise ReadinessError(f"CIF members missing from archive: {missing_members[:5]}")
        family_leakage = _check_family_split(dataset, split_ids)
        if family_leakage:
            raise ReadinessError(f"Family split leakage detected: {list(family_leakage)[:5]}")
        runtime_manifest = phase6_frozen_protocol_v1().to_manifest()
        expected_runtime = lock.get("runtime_contract", {}).get("manifest")
        protocol_parity = runtime_manifest == expected_runtime
        if not protocol_parity:
            raise ReadinessError("Executable benchmark protocol differs from RI-1 runtime lock")
        pocketminer_overlap = _pocketminer_overlap(session, dataset, split_ids)
        baseline_sources = _baseline_source_checks(session, lock)
        retrieved_utc = args.retrieved_utc or datetime.now(timezone.utc).isoformat()
        member_index = {
            "schema_version": "biovoid-ri3-cif-member-index-v1",
            "snapshot_id": lock["dataset"]["snapshot_id"],
            "archive": {
                "path": archive["path"],
                "file_id": archive["file_id"],
                "sha256": archive["sha256"],
                "size": archive_size,
                "hash_status": archive_hash_status,
            },
            "directory": directory,
            "member_count": len(members),
            "members": [member.to_dict() for member in members],
            "generated_at_utc": retrieved_utc,
        }
        member_index["member_index_sha256"] = _sha256(
            json.dumps(
                {key: value for key, value in member_index.items() if key != "generated_at_utc"},
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        _write_json(args.output_dir / "cryptobench-cif-member-index-v1.json", member_index)
        readiness = {
            "schema_version": "biovoid-ri3-readiness-v1",
            "status": "source_preflight_ready_baselines_pending",
            "snapshot_id": lock["dataset"]["snapshot_id"],
            "retrieved_at_utc": retrieved_utc,
            "archive": {
                "path": archive["path"],
                "sha256": archive["sha256"],
                "size": archive_size,
                "member_count": len(members),
                "cif_member_count": sum(member.name.casefold().endswith(".cif") for member in members),
                "expected_apo_structure_count": len(all_structure_ids),
                "expected_apo_members_found": len(expected_members) - len(missing_members),
                "missing_apo_members": missing_members,
                "range_bytes_read": range_bytes,
                "full_archive_downloaded": False,
            },
            "splits": {
                split: {"structure_count": len(values), "structure_ids_sha256": _sha256("\n".join(values).encode("utf-8"))}
                for split, values in split_ids.items()
            },
            "family_split_leakage": family_leakage,
            "runtime_protocol": {
                "parity": protocol_parity,
                "protocol_sha256": runtime_manifest["protocol_sha256"],
                "factory": lock["runtime_contract"]["factory"],
            },
            "pocketminer_overlap": pocketminer_overlap,
            "baseline_sources": baseline_sources,
            "external_baseline_training_overlap": "partial_pocketminer_reference;_p2rank_unknown",
            "scientific_execution_started": False,
            "sealed_evaluation_authorized": False,
            "next_gate": "RI-3 exact member materialization and preparation preflight",
        }
        _write_json(args.output_dir / "ri3-readiness-v1.json", readiness)
    finally:
        session.close()
    print("RI-3 readiness: PASS for source metadata preflight")
    print(f"archive members: {len(members)} ({readiness['archive']['cif_member_count']} CIF)")
    print(f"apo members verified: {readiness['archive']['expected_apo_members_found']}/{len(expected_members)}")
    print(f"range bytes read: {readiness['archive']['range_bytes_read']}")
    print(f"runtime protocol parity: {protocol_parity}")
    print(f"PocketMiner reference overlap: {pocketminer_overlap['overlap_count_by_split']}")
    print(f"external baseline execution: {baseline_sources['execution_status']}")
    print("full archive downloaded: no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

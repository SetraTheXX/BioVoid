"""Build the local, ignored RI-2 CryptoBench metadata manifest.

The command enumerates OSF metadata and downloads only the small dataset and
fold JSON files needed to derive opaque case identity. It never downloads the
CryptoBench structure archive or starts a BioVoid detector run.
"""

from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.cryptobench_manifest import (
    build_manifest_payload,
    stable_sha256,
    validate_manifest_payload,
)


DEFAULT_API_ROOT = "https://api.osf.io/v2/nodes/pz4a9/files/osfstorage/"
MAX_METADATA_BYTES = 20 * 1024 * 1024


def _json_response(session: requests.Session, url: str) -> Mapping[str, Any]:
    response = session.get(url, timeout=60)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise RuntimeError(f"OSF response is not an object: {url}")
    return payload


def resolve_osf_download_link(
    session: requests.Session,
    api_locator: str,
) -> str:
    """Resolve a file's current OSF Waterbutler download link."""

    payload = _json_response(session, api_locator)
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise RuntimeError(f"OSF file response has no data object: {api_locator}")
    links = data.get("links")
    if not isinstance(links, Mapping) or not links.get("download"):
        raise RuntimeError(f"OSF file response has no download link: {api_locator}")
    return str(links["download"])


def enumerate_osf_files(
    api_root: str,
    *,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """Enumerate OSF file metadata without downloading file contents."""

    own_session = session is None
    client = session or requests.Session()
    client.headers.update({"User-Agent": "BioVoid/0.1 RI-2 metadata manifest"})
    queue: deque[str] = deque([api_root])
    visited: set[str] = set()
    records: list[dict[str, Any]] = []
    try:
        while queue:
            url = queue.popleft()
            if not url or url in visited:
                continue
            visited.add(url)
            payload = _json_response(client, url)
            for item in payload.get("data", []):
                attributes = item.get("attributes", {})
                if not isinstance(attributes, Mapping):
                    continue
                extra = attributes.get("extra") or {}
                hashes = extra.get("hashes") if isinstance(extra, Mapping) else {}
                hashes = hashes if isinstance(hashes, Mapping) else {}
                links = item.get("links") or {}
                record = {
                    "file_id": item.get("id"),
                    "kind": attributes.get("kind"),
                    "name": attributes.get("name"),
                    "path": attributes.get("materialized_path"),
                    "size": attributes.get("size"),
                    "sha256": hashes.get("sha256"),
                    "date_modified": attributes.get("date_modified"),
                    "api_locator": links.get("self"),
                }
                if record["kind"] == "file":
                    records.append(record)
                elif record["kind"] == "folder":
                    relationships = item.get("relationships") or {}
                    files_relation = relationships.get("files") or {}
                    relation_links = files_relation.get("links") or {}
                    related = relation_links.get("related") or {}
                    queue.append(related.get("href"))
            next_url = (payload.get("links") or {}).get("next")
            if isinstance(next_url, Mapping):
                next_url = next_url.get("href")
            if next_url:
                queue.append(str(next_url))
    finally:
        if own_session:
            client.close()
    records.sort(key=lambda record: str(record.get("path", "")))
    if not records:
        raise RuntimeError("OSF API enumeration returned no files")
    return records


def _download_small_metadata(
    metadata_dir: Path,
    *,
    session: requests.Session,
    name: str,
    url: str,
    expected_sha256: str,
) -> Path:
    destination = metadata_dir / name
    response = session.get(url, timeout=120)
    response.raise_for_status()
    content = response.content
    if len(content) > MAX_METADATA_BYTES:
        raise RuntimeError(f"Refusing metadata file larger than safety limit: {name}")
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != expected_sha256:
        raise RuntimeError(f"SHA-256 mismatch for {name}: {actual_sha256}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return destination


def _load_verified_json(path: Path, expected_sha256: str) -> Any:
    content = path.read_bytes()
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != expected_sha256:
        raise RuntimeError(f"SHA-256 mismatch for local metadata file {path}: {actual_sha256}")
    return json.loads(content.decode("utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-root", default=DEFAULT_API_ROOT)
    parser.add_argument(
        "--metadata-dir",
        type=Path,
        default=REPO_ROOT / "data/runtime/cryptobench-source/metadata",
    )
    parser.add_argument(
        "--lock",
        type=Path,
        default=REPO_ROOT / "local-private/research/ri-1-lock-v1.json",
    )
    parser.add_argument(
        "--inventory-output",
        type=Path,
        default=REPO_ROOT / "data/runtime/ri2/cryptobench-source-file-inventory-v1.json",
    )
    parser.add_argument(
        "--manifest-output",
        type=Path,
        default=REPO_ROOT / "data/runtime/ri2/cryptobench-development-manifest-v1.json",
    )
    parser.add_argument(
        "--retrieved-utc",
        default=None,
        help="Explicit metadata retrieval timestamp for reproducible reruns.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    lock_payload = json.loads(args.lock.read_text(encoding="utf-8"))
    metadata_lock = lock_payload["dataset"]["metadata_files"]
    session = requests.Session()
    session.headers.update({"User-Agent": "BioVoid/0.1 RI-2 metadata manifest"})
    try:
        inventory = enumerate_osf_files(args.api_root, session=session)
        inventory_by_path = {record["path"]: record for record in inventory}
        required_paths = {
            "/cryptobench/cryptobench-dataset/dataset.json": "dataset.json",
            "/cryptobench/cryptobench-dataset/folds.json": "folds.json",
        }
        for source_path, name in required_paths.items():
            record = inventory_by_path.get(source_path)
            if not record:
                raise RuntimeError(f"Required OSF metadata path is missing: {source_path}")
            if record.get("sha256") != metadata_lock[name]["sha256"]:
                raise RuntimeError(f"OSF metadata hash drift detected for {name}")
            local_path = args.metadata_dir / name
            if not local_path.exists():
                download_url = resolve_osf_download_link(session, str(record["api_locator"]))
                _download_small_metadata(
                    args.metadata_dir,
                    session=session,
                    name=name,
                    url=download_url,
                    expected_sha256=metadata_lock[name]["sha256"],
                )
        dataset = _load_verified_json(
            args.metadata_dir / "dataset.json",
            metadata_lock["dataset.json"]["sha256"],
        )
        folds = _load_verified_json(
            args.metadata_dir / "folds.json",
            metadata_lock["folds.json"]["sha256"],
        )
        retrieved_utc = args.retrieved_utc or datetime.now(timezone.utc).isoformat()
        inventory_payload = {
            "schema_version": "biovoid-ri2-osf-file-inventory-v1",
            "snapshot_id": lock_payload["dataset"]["snapshot_id"],
            "api_root": args.api_root,
            "api_retrieved_utc": retrieved_utc,
            "file_count": len(inventory),
            "total_bytes": sum(int(record.get("size") or 0) for record in inventory),
            "inventory_sha256": stable_sha256(inventory),
            "files": inventory,
        }
        _write_json(args.inventory_output, inventory_payload)
        manifest = build_manifest_payload(
            lock_payload=lock_payload,
            dataset=dataset,
            folds=folds,
            source_inventory=inventory,
            api_root=args.api_root,
            api_retrieved_utc=retrieved_utc,
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
        )
        validate_manifest_payload(manifest)
        _write_json(args.manifest_output, manifest)
    finally:
        session.close()
    split_summary = manifest["split_summaries"]
    print("RI-2 manifest: PASS")
    print(f"source files: {manifest['source_inventory']['file_count']}")
    print(f"source bytes: {manifest['source_inventory']['total_bytes']}")
    print(f"development cases: {split_summary['development']['case_count']}")
    print(f"validation cases: {split_summary['validation']['case_count']}")
    print(f"sealed structures recorded, case rows closed: {split_summary['sealed']['structure_count']}")
    print(f"manifest sha256: {manifest['manifest_sha256']}")
    print("raw structure archive downloaded: no")
    print(f"manifest path: {args.manifest_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Run a bounded, non-canonical representative-chain sensitivity arm.

This runner is deliberately separate from ``run_target_family_static_pilot``.
It consumes only a redacted apo manifest and local apo coordinate files, uses a
single fixed chain and the opt-in ``RI3_STATIC_RECOVERY`` profile, and never
promotes its result to the canonical full-heavy-atom method.  It is useful for
diagnosing whether an asymmetric-unit resource block is the only reason a
target-family pilot cannot be exercised on a small local machine.
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
import tempfile
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.resources import RI3_STATIC_RECOVERY, ResourceLimitError  # noqa: E402
from src.static_detector import detect_static_pockets  # noqa: E402
from src.structure_preparation import (  # noqa: E402
    PreparationConfig,
    StructureSource,
    prepare_structure,
)
from src.target_family_manifest import (  # noqa: E402
    MAX_PILOT_CASES,
    validate_detector_manifest,
)


DEFAULT_MANIFEST = (
    REPO_ROOT / "data/runtime/target-family/cohort-detector-pfam-v1/"
    "target-family-cohort-detector-pfam-v1.json"
)
DEFAULT_SOURCE_ROOT = (
    REPO_ROOT / "local-private/research/target-family/static-pilot-pfam-v1-full/source-cache"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "local-private/research/target-family/static-sensitivity-pfam-v1"
MAX_DISK_BYTES = 1_000_000_000
SENSITIVITY_SCHEMA_VERSION = "biovoid-target-family-static-sensitivity-v1"
CHAIN_POLICY = "fixed-chain-id-v1"
FORBIDDEN_OUTPUT_TOKENS = ("holo", "ligand", "evaluator", "ground_truth")
_PDB_ID_RE = re.compile(r"^[A-Z0-9]{4}$")


class ChainSensitivityError(RuntimeError):
    """Raised when the secondary sensitivity contract is invalid."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ChainSensitivityError(f"cannot read JSON input: {path}") from exc
    if not isinstance(payload, dict):
        raise ChainSensitivityError(f"JSON input must be an object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def directory_size_bytes(root: Path) -> int:
    """Measure regular-file bytes without following symlinks."""

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
    used = directory_size_bytes(root)
    if used > max_disk_bytes:
        raise ChainSensitivityError(
            f"sensitivity output exceeds disk quota: {used} bytes > {max_disk_bytes} bytes"
        )
    return used


def _normalise_chain_id(value: str) -> str:
    chain_id = str(value).strip()
    if not chain_id or len(chain_id) > 8:
        raise ValueError("chain_id must contain 1-8 non-whitespace characters")
    return chain_id


def _safe_error(value: Any) -> str:
    message = str(value)
    for token in FORBIDDEN_OUTPUT_TOKENS:
        message = message.replace(token, "[redacted]")
        message = message.replace(token.upper(), "[redacted]")
    return message[:500]


def build_sensitivity_run_skeleton(
    manifest: Mapping[str, Any],
    *,
    chain_id: str = "A",
    max_disk_bytes: int = MAX_DISK_BYTES,
) -> dict[str, Any]:
    """Build the target-blind secondary-run record before reading coordinates."""

    validate_detector_manifest(manifest)
    normalized_chain = _normalise_chain_id(chain_id)
    if not 1 <= max_disk_bytes <= MAX_DISK_BYTES:
        raise ValueError(f"max_disk_bytes must be between 1 and {MAX_DISK_BYTES}")
    case_count = int(manifest["constraints"]["case_count"])
    if not 1 <= case_count <= MAX_PILOT_CASES:
        raise ChainSensitivityError("manifest case count is outside the bounded range")
    payload: dict[str, Any] = {
        "schema_version": SENSITIVITY_SCHEMA_VERSION,
        "status": "not_started",
        "family_id": manifest["family_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "target_blind": True,
        "canonical_static_result": False,
        "claim_boundary": "secondary_resource_recovery_only",
        "chain_selection_policy": CHAIN_POLICY,
        "chain_id": normalized_chain,
        "execution": {
            "profile": RI3_STATIC_RECOVERY.name,
            "profile_sha256": _stable_hash(asdict(RI3_STATIC_RECOVERY)),
            "workers": 1,
            "motion_enabled": False,
            "nma_started": False,
            "candidate_retention": "full",
            "max_disk_bytes": max_disk_bytes,
            "disk_quota_enforced": True,
        },
        "counts": {"completed": 0, "resource_blocked": 0, "failed": 0},
        "cases": {},
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
    }
    payload["run_sha256"] = _stable_hash(
        {key: value for key, value in payload.items() if key != "run_sha256"}
    )
    return payload


def validate_sensitivity_run(payload: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    """Validate resource, target-blind and non-canonical invariants."""

    validate_detector_manifest(manifest)
    if payload.get("schema_version") != SENSITIVITY_SCHEMA_VERSION:
        raise ChainSensitivityError("unexpected chain-sensitivity schema")
    if payload.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise ChainSensitivityError("run is not bound to the target-blind manifest")
    if payload.get("target_blind") is not True:
        raise ChainSensitivityError("sensitivity run is not target-blind")
    if payload.get("canonical_static_result") is not False:
        raise ChainSensitivityError("sensitivity result cannot be canonical")
    if payload.get("claim_boundary") != "secondary_resource_recovery_only":
        raise ChainSensitivityError("sensitivity claim boundary is unsafe")
    execution = payload.get("execution")
    if not isinstance(execution, Mapping):
        raise ChainSensitivityError("sensitivity execution metadata is missing")
    if execution.get("profile") != RI3_STATIC_RECOVERY.name:
        raise ChainSensitivityError("unexpected sensitivity resource profile")
    if execution.get("workers") != 1 or execution.get("motion_enabled") is not False:
        raise ChainSensitivityError("sensitivity arm must remain single-worker and static")
    if execution.get("nma_started") is not False:
        raise ChainSensitivityError("sensitivity arm cannot start NMA")
    if execution.get("candidate_retention") != "full":
        raise ChainSensitivityError("sensitivity arm must retain full candidates")
    cases = payload.get("cases")
    if not isinstance(cases, Mapping):
        raise ChainSensitivityError("sensitivity cases are missing")
    expected_case_ids = {
        str(case["case_id"]): str(case["structure_id"]).upper() for case in manifest["cases"]
    }
    if not set(cases).issubset(expected_case_ids):
        raise ChainSensitivityError("sensitivity cases do not match the manifest")
    if payload.get("status") in {"completed", "completed_with_failures"} and set(cases) != set(
        expected_case_ids
    ):
        raise ChainSensitivityError("completed sensitivity run is missing case records")
    counts = payload.get("counts")
    if not isinstance(counts, Mapping):
        raise ChainSensitivityError("sensitivity counts are missing")
    observed = {status: 0 for status in ("completed", "resource_blocked", "failed")}
    for case_id, record in cases.items():
        if not isinstance(record, Mapping):
            raise ChainSensitivityError(f"invalid sensitivity record: {case_id}")
        status = record.get("status")
        if status not in observed:
            raise ChainSensitivityError(f"invalid sensitivity status: {status}")
        observed[status] += 1
        if str(record.get("structure_id", "")).upper() != expected_case_ids[case_id]:
            raise ChainSensitivityError(f"structure mismatch for case: {case_id}")
    if {key: int(counts.get(key, -1)) for key in observed} != observed:
        raise ChainSensitivityError("sensitivity counts do not match case records")
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True).casefold()
    for token in FORBIDDEN_OUTPUT_TOKENS:
        if token in serialized:
            raise ChainSensitivityError(f"sensitivity output contains forbidden token: {token}")
    expected_hash = _stable_hash(
        {key: value for key, value in payload.items() if key != "run_sha256"}
    )
    if payload.get("run_sha256") != expected_hash:
        raise ChainSensitivityError("sensitivity run hash mismatch")


def _seal(payload: dict[str, Any]) -> None:
    payload["updated_at_utc"] = _utc_now()
    payload["run_sha256"] = _stable_hash(
        {key: value for key, value in payload.items() if key != "run_sha256"}
    )


def run_chain_sensitivity(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    source_root: Path = DEFAULT_SOURCE_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    chain_id: str = "A",
    max_disk_bytes: int = MAX_DISK_BYTES,
    user_approved: bool = False,
) -> dict[str, Any]:
    """Run the explicitly approved, local-only sensitivity arm."""

    if not user_approved:
        raise ChainSensitivityError("sensitivity arm requires explicit approval")
    manifest = _read_json(manifest_path.resolve())
    validate_detector_manifest(manifest)
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    if not source_root.is_dir():
        raise ChainSensitivityError(f"source root is missing: {source_root}")
    if output_root.exists() and any(output_root.iterdir()):
        raise ChainSensitivityError(f"output root is not empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    _enforce_disk_quota(output_root, max_disk_bytes)

    run = build_sensitivity_run_skeleton(manifest, chain_id=chain_id, max_disk_bytes=max_disk_bytes)
    run["status"] = "running"
    run["execution"]["source_root"] = str(source_root.relative_to(REPO_ROOT)).replace("\\", "/")
    run["execution"]["started_disk_bytes"] = directory_size_bytes(output_root)
    _seal(run)
    run_path = output_root / "target-family-static-sensitivity-v1.json"
    _write_json(run_path, run)

    for case in manifest["cases"]:
        case_id = str(case["case_id"])
        structure_id = str(case["structure_id"]).upper()
        source_path = source_root / f"{structure_id.lower()}.cif"
        record: dict[str, Any] = {
            "case_id": case_id,
            "structure_id": structure_id,
            "split": str(case["split"]),
            "chain_id": run["chain_id"],
            "status": "not_started",
            "profile": RI3_STATIC_RECOVERY.name,
            "canonical_static_result": False,
            "target_blind": True,
            "motion_enabled": False,
            "nma_started": False,
        }
        try:
            if not _PDB_ID_RE.fullmatch(structure_id):
                raise ChainSensitivityError(f"invalid structure ID: {structure_id}")
            if not source_path.is_file():
                raise ChainSensitivityError(f"local apo coordinate file is missing: {source_path}")
            with tempfile.TemporaryDirectory(prefix=f"biovoid-chain-{structure_id.lower()}-") as td:
                preparation = prepare_structure(
                    source_path,
                    StructureSource(
                        provider="local",
                        identifier=structure_id,
                        representation="local",
                        local_path=source_path,
                    ),
                    PreparationConfig(chain_ids=(run["chain_id"],)),
                    Path(td) / "preparation",
                    f"target-family-chain-sensitivity-{structure_id}",
                )
                prepared_sha256 = hashlib.sha256(preparation.prepared_path.read_bytes()).hexdigest()
                detection = detect_static_pockets(
                    preparation.prepared_path,
                    prepared_sha256=prepared_sha256,
                    resource_profile=RI3_STATIC_RECOVERY,
                )
                record.update(
                    {
                        "status": "completed",
                        "prepared_structure_sha256": prepared_sha256,
                        "protein_atom_count": detection.protein_atom_count,
                        "candidate_count": detection.candidate_count,
                        "pocket_count": len(detection.pockets),
                        "detector_version": detection.detector_version,
                        "detector_config_sha256": detection.config_sha256,
                        "warnings": list(detection.warnings),
                        "pockets": [pocket.to_portable_dict() for pocket in detection.pockets],
                    }
                )
        except ResourceLimitError as exc:
            record.update({"status": "resource_blocked", "error": _safe_error(exc)})
        except Exception as exc:  # noqa: BLE001 - bounded case record
            record.update(
                {"status": "failed", "error": _safe_error(f"{type(exc).__name__}: {exc}")}
            )
        run["cases"][case_id] = record
        for status in ("completed", "resource_blocked", "failed"):
            run["counts"][status] = sum(
                1 for value in run["cases"].values() if value.get("status") == status
            )
        _seal(run)
        validate_sensitivity_run(run, manifest)
        _write_json(run_path, run)
        _enforce_disk_quota(output_root, max_disk_bytes)

    run["status"] = (
        "completed"
        if run["counts"]["resource_blocked"] == 0 and run["counts"]["failed"] == 0
        else "completed_with_failures"
    )
    run["execution"]["final_disk_bytes"] = directory_size_bytes(output_root)
    _seal(run)
    validate_sensitivity_run(run, manifest)
    _write_json(run_path, run)
    return run


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--chain-id", default="A")
    parser.add_argument("--max-disk-bytes", type=int, default=MAX_DISK_BYTES)
    parser.add_argument("--approve-sensitivity", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.approve_sensitivity:
        print("chain sensitivity requires --approve-sensitivity", file=sys.stderr)
        return 2
    try:
        run = run_chain_sensitivity(
            manifest_path=args.manifest,
            source_root=args.source_root,
            output_root=args.output_root,
            chain_id=args.chain_id,
            max_disk_bytes=args.max_disk_bytes,
            user_approved=True,
        )
    except (ChainSensitivityError, ValueError, OSError) as exc:
        print(f"chain sensitivity error: {exc}", file=sys.stderr)
        return 2
    print(f"status={run['status']}")
    print(f"counts={json.dumps(run['counts'], sort_keys=True)}")
    print(f"disk_bytes={run['execution']['final_disk_bytes']}")
    print(f"run_sha256={run['run_sha256']}")
    return 0 if run["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

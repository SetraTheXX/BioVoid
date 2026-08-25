"""Check PocketMiner held-out fpocket/P2Rank readiness without running tools.

The checker creates an ignored, target-blind prepared-apo manifest and probes
the local Docker daemon/images in read-only mode. It never pulls images,
starts containers, opens holo labels, or authorizes a scientific claim.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_ri3_external_baseline import BASELINE_CONFIG  # noqa: E402


DEFAULT_STATIC_RUN = (
    REPO_ROOT / "data/runtime/ranking-study/pocketminer-v1/heldout-static-v1/"
    "pocketminer-heldout-static-v1.json"
)
DEFAULT_PREFLIGHT = (
    REPO_ROOT / "data/runtime/ranking-study/pocketminer-v1/heldout-materialization-v1/"
    "heldout-preflight-v1.json"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT / "data/runtime/ranking-study/pocketminer-v1/external-baseline-readiness-v1"
)
DEFAULT_MANIFEST = DEFAULT_OUTPUT_ROOT / "pocketminer-heldout-baseline-input-v1.json"
DEFAULT_REPORT = DEFAULT_OUTPUT_ROOT / "pocketminer-external-baseline-readiness-v1.json"
MAX_CASES = 10
MAX_DISK_BYTES = 1_000_000_000
FORBIDDEN_TOKENS = ("holo", "ligand", "evaluator", "ground_truth")


class PocketMinerBaselineReadinessError(RuntimeError):
    """Raised when a target-blind baseline readiness input is invalid."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PocketMinerBaselineReadinessError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PocketMinerBaselineReadinessError(f"JSON root must be an object: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError as exc:
        raise PocketMinerBaselineReadinessError(
            f"prepared path escapes repository: {path}"
        ) from exc


def _build_manifest(static_run: Mapping[str, Any], preflight: Mapping[str, Any]) -> dict[str, Any]:
    boundary = static_run.get("boundary")
    if not isinstance(boundary, Mapping):
        raise PocketMinerBaselineReadinessError("held-out static boundary is missing")
    if (
        static_run.get("status") != "completed"
        or static_run.get("retention") != "full_final_pocket_list"
    ):
        raise PocketMinerBaselineReadinessError("held-out static run is not complete/full-list")
    if boundary.get("target_blind") is not True:
        raise PocketMinerBaselineReadinessError("held-out static run is not target-blind")
    if any(
        boundary.get(flag) is not False
        for flag in (
            "evaluator_started",
            "external_baseline_started",
            "holo_coordinates_opened",
            "ml_training_started",
        )
    ):
        raise PocketMinerBaselineReadinessError(
            "held-out static run crossed a target-blind boundary"
        )
    records = static_run.get("records")
    if not isinstance(records, list) or not records:
        raise PocketMinerBaselineReadinessError("held-out static records are missing")
    static_by_case: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping) or record.get("status") != "completed":
            raise PocketMinerBaselineReadinessError("held-out static contains incomplete records")
        case_id = str(record.get("case_id", ""))
        if not case_id or case_id in static_by_case:
            raise PocketMinerBaselineReadinessError(
                "held-out static case IDs are invalid/duplicated"
            )
        static_by_case[case_id] = record
    if preflight.get("status") != "ready_for_static_detector_gate":
        raise PocketMinerBaselineReadinessError("held-out preflight is not ready")
    cases = preflight.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        raise PocketMinerBaselineReadinessError("held-out preflight case count is invalid")
    structures: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, Mapping) or case.get("status") != "prepared":
            raise PocketMinerBaselineReadinessError("held-out preflight contains blocked cases")
        case_id = str(case.get("case_id", ""))
        static_record = static_by_case.get(case_id)
        if static_record is None:
            raise PocketMinerBaselineReadinessError(
                f"static run is missing preflight case: {case_id}"
            )
        prepared = Path(str(case.get("prepared_path", ""))).resolve()
        if not prepared.is_file():
            raise PocketMinerBaselineReadinessError(f"prepared input is missing: {prepared}")
        observed_sha = _sha256_file(prepared)
        detector = static_record.get("detector")
        detector_sha = (
            detector.get("prepared_structure_sha256") if isinstance(detector, Mapping) else None
        )
        for expected_sha in (case.get("prepared_sha256"), detector_sha):
            if not isinstance(expected_sha, str) or expected_sha != observed_sha:
                raise PocketMinerBaselineReadinessError(
                    f"prepared input hash binding failed: {case_id}"
                )
        structure_id = str(case["structure_id"]).upper()
        if str(static_record.get("structure_id", "")).upper() != structure_id:
            raise PocketMinerBaselineReadinessError(f"structure binding failed: {case_id}")
        structures.append(
            {
                "case_id": case_id,
                "structure_id": structure_id,
                "prepared_path": _relative_path(prepared),
                "prepared_structure_sha256": observed_sha,
                "split": str(case.get("split", "")),
            }
        )
    if set(static_by_case) != {item["case_id"] for item in structures}:
        raise PocketMinerBaselineReadinessError("static/preflight case sets differ")
    if any(item["split"] not in {"validation", "test"} for item in structures):
        raise PocketMinerBaselineReadinessError(
            "external baseline manifest contains non-held-out split"
        )
    payload: dict[str, Any] = {
        "schema_version": "biovoid-target-family-baseline-input-v1",
        "manifest_kind": "target_blind_external_baseline",
        "status": "ready",
        "family_id": "POCKETMINER-HELDOUT",
        "source_static_run_sha256": _stable_hash(static_run),
        "source_preflight_sha256": _stable_hash(preflight),
        "boundary": "prepared_apo_only_v1",
        "detector_boundary": {
            "target_blind": True,
            "target_annotations_present": False,
            "motion_enabled": False,
            "external_tools_receive_prepared_apo_only": True,
        },
        "constraints": {
            "case_count": len(structures),
            "max_case_count": MAX_CASES,
            "analysis_workers": 1,
            "motion_enabled": False,
            "max_disk_bytes": MAX_DISK_BYTES,
        },
        "structures": structures,
        "created_at_utc": _utc_now(),
    }
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    if any(token in serialized.casefold() for token in FORBIDDEN_TOKENS):
        raise PocketMinerBaselineReadinessError(
            "baseline manifest contains forbidden evaluator token"
        )
    payload["manifest_sha256"] = _stable_hash(payload)
    return payload


def _probe_docker(image: str) -> dict[str, Any]:
    try:
        version = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"daemon": "unavailable", "image": image, "error": str(exc)[:300]}
    if version.returncode != 0 or not version.stdout.strip():
        return {"daemon": "unavailable", "image": image, "error": version.stderr.strip()[:300]}
    try:
        inspect = subprocess.run(
            ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "daemon": "available",
            "server_version": version.stdout.strip(),
            "image": image,
            "image_status": "unknown",
            "error": str(exc)[:300],
        }
    if inspect.returncode != 0 or not inspect.stdout.strip():
        return {
            "daemon": "available",
            "server_version": version.stdout.strip(),
            "image": image,
            "image_status": "missing",
            "error": inspect.stderr.strip()[:300],
        }
    return {
        "daemon": "available",
        "server_version": version.stdout.strip(),
        "image": image,
        "image_status": "available",
        "image_id": inspect.stdout.strip(),
    }


def check_pocketminer_external_baseline_readiness(
    *,
    static_run_path: Path = DEFAULT_STATIC_RUN,
    preflight_path: Path = DEFAULT_PREFLIGHT,
    manifest_path: Path = DEFAULT_MANIFEST,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, Any]:
    static_run = _read_json(static_run_path.resolve())
    preflight = _read_json(preflight_path.resolve())
    manifest = _build_manifest(static_run, preflight)
    manifest_path.resolve().parent.mkdir(parents=True, exist_ok=True)
    manifest_path.resolve().write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tool_checks = {
        name: _probe_docker(str(config["image"])) for name, config in BASELINE_CONFIG.items()
    }
    ready = all(
        check.get("daemon") == "available" and check.get("image_status") == "available"
        for check in tool_checks.values()
    )
    report: dict[str, Any] = {
        "schema_version": "biovoid-pocketminer-external-baseline-readiness-v1",
        "status": "ready_for_explicit_baseline_approval" if ready else "blocked_tool_runtime",
        "decision": "PASS" if ready else "WAIT_DOCKER_AND_IMAGES",
        "manifest_sha256": manifest["manifest_sha256"],
        "manifest_path": str(manifest_path),
        "static_run_sha256": _sha256_file(static_run_path.resolve()),
        "preflight_sha256": _sha256_file(preflight_path.resolve()),
        "tool_checks": tool_checks,
        "constraints": {
            "case_count": len(manifest["structures"]),
            "workers": 1,
            "max_disk_bytes": MAX_DISK_BYTES,
            "images_pulled": False,
            "containers_started": False,
        },
        "boundary": {
            "prepared_apo_only": True,
            "evaluator_opened": False,
            "nma_started": False,
            "ml_training_started": False,
            "claims_authorized": False,
        },
        "created_at_utc": _utc_now(),
    }
    report["report_sha256"] = _stable_hash(report)
    report_path.resolve().parent.mkdir(parents=True, exist_ok=True)
    report_path.resolve().write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"PocketMiner external readiness: {report['status']} "
        f"decision={report['decision']} cases={len(manifest['structures'])}"
    )
    print(f"readiness report: {report_path}")
    print("image pull/container/evaluator/NMA/ML: no")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-run", type=Path, default=DEFAULT_STATIC_RUN)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        report = check_pocketminer_external_baseline_readiness(
            static_run_path=args.static_run,
            preflight_path=args.preflight,
            manifest_path=args.manifest,
            report_path=args.report,
        )
    except (PocketMinerBaselineReadinessError, OSError, ValueError) as exc:
        print(f"PocketMiner external readiness error: {exc}", file=sys.stderr)
        return 2
    return 0 if report["status"] == "ready_for_explicit_baseline_approval" else 2


if __name__ == "__main__":
    raise SystemExit(main())

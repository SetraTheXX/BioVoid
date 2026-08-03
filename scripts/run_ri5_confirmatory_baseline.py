"""Run one pinned external baseline on the target-blind RI-5 confirmatory inputs."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_ri3_external_baseline import (  # noqa: E402
    BASELINE_CONFIG,
    BaselineRunError,
    _docker_image_id,
    _record_for_case,
    _safe_child,
)
from src.evaluator_v3 import stable_hash  # noqa: E402


DEFAULT_ROOT = REPO_ROOT / "data/runtime/ri5-confirmatory"
DEFAULT_MANIFEST = DEFAULT_ROOT / "confirmatory-runtime-manifest-v1.json"
DEFAULT_WORK_ROOT = DEFAULT_ROOT / "external-baselines-v1"
REPORT_SCHEMA = "biovoid-ri5-confirmatory-external-baseline-v1"


class ConfirmatoryBaselineError(RuntimeError):
    """Raised when a confirmatory baseline violates input or identity locks."""


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ConfirmatoryBaselineError(f"Expected JSON object: {path}")
    return payload


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def validate_manifest(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != "biovoid-ri5-confirmatory-runtime-manifest-v1":
        raise ConfirmatoryBaselineError("Unexpected confirmatory manifest schema")
    if payload.get("status") != "target_blind_ready":
        raise ConfirmatoryBaselineError("Confirmatory manifest is not ready")
    if payload.get("structure_count") != 222 or len(payload.get("structures", [])) != 222:
        raise ConfirmatoryBaselineError("Confirmatory structure count drifted")
    boundary = payload.get("detector_boundary", {})
    if boundary.get("target_blind") is not True or boundary.get("evaluator_fields_present") is not False:
        raise ConfirmatoryBaselineError("Confirmatory baseline manifest is not target-blind")
    encoded = json.dumps(payload, ensure_ascii=True).lower()
    for key in ("holo_pdb_id", "ligand", "apo_pocket_selection", "target_center"):
        if f'"{key}"' in encoded:
            raise ConfirmatoryBaselineError(f"Evaluator field leaked into baseline manifest: {key}")
    expected = stable_hash({key: value for key, value in payload.items() if key != "manifest_sha256"})
    if payload.get("manifest_sha256") != expected:
        raise ConfirmatoryBaselineError("Confirmatory manifest hash mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", choices=tuple(BASELINE_CONFIG), required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--all-confirmatory", action="store_true")
    parser.add_argument("--max-cases", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=5)
    args = parser.parse_args()
    if args.max_cases < 1 or args.max_cases > 222:
        raise ConfirmatoryBaselineError("max-cases must be between 1 and 222")
    if args.batch_size < 1 or args.batch_size > 10:
        raise ConfirmatoryBaselineError("batch-size must be between 1 and 10")
    manifest = _read(args.manifest)
    validate_manifest(manifest)
    config = BASELINE_CONFIG[args.baseline]
    image_id = _docker_image_id(str(config["image"]))
    work_root = _safe_child(DEFAULT_ROOT, args.work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    report_path = args.report or work_root / f"{args.baseline}-confirmatory-v1.json"
    report = _read(report_path) if report_path.is_file() else {
        "schema_version": REPORT_SCHEMA,
        "status": "not_started",
        "tool": args.baseline,
        "tool_version": config["version"],
        "tool_commit": config["commit"],
        "container_image": config["image"],
        "container_image_id": image_id,
        "manifest_sha256": manifest["manifest_sha256"],
        "target_blind": True,
        "evaluator_opened": False,
        "resource_limits": {"workers": 1, "cpus": 1, "memory": config["memory"]},
        "records": {},
        "counts": {"completed": 0, "failed": 0},
    }
    if report.get("schema_version") != REPORT_SCHEMA or report.get("tool") != args.baseline:
        raise ConfirmatoryBaselineError("Existing baseline checkpoint identity mismatch")
    if report.get("manifest_sha256") != manifest["manifest_sha256"]:
        raise ConfirmatoryBaselineError("Existing baseline belongs to another manifest")
    if report.get("container_image_id") != image_id:
        raise ConfirmatoryBaselineError("Baseline container image changed after checkpoint")
    structures = sorted(manifest["structures"], key=lambda item: str(item["structure_id"]))
    pending = [item for item in structures if str(item["structure_id"]) not in report["records"]]
    selected = pending if args.all_confirmatory else pending[: args.max_cases]
    run_root = _safe_child(work_root, work_root / args.baseline)
    run_root.mkdir(parents=True, exist_ok=True)
    for index, structure in enumerate(selected, start=1):
        structure_id = str(structure["structure_id"])
        print(f"[{index}/{len(selected)}] {args.baseline} {structure_id}", flush=True)
        record, execution = _record_for_case(
            tool=args.baseline,
            config=config,
            image_id=image_id,
            structure=structure,
            work_root=run_root,
        )
        report["records"][structure_id] = {
            **execution,
            "structure_id": structure_id,
            "detector_status": record.status,
            "detector_record": execution.get("detector_record"),
        }
        report["counts"] = dict(
            Counter(str(item.get("detector_status", "failed")) for item in report["records"].values())
        )
        if index % args.batch_size == 0 or index == len(selected):
            report["updated_at_utc"] = _utc_now()
            _write(report_path, report)
            print(f"baseline checkpoint counts={report['counts']}", flush=True)
    report["status"] = "complete" if len(report["records"]) == len(structures) else "partial"
    report["updated_at_utc"] = _utc_now()
    report["report_sha256"] = stable_hash(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    _write(report_path, report)
    print(
        f"RI-5 confirmatory {args.baseline}: {report['status']} "
        f"records={len(report['records'])}/222 counts={report['counts']}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ConfirmatoryBaselineError, BaselineRunError) as exc:
        print(f"RI-5 confirmatory baseline error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


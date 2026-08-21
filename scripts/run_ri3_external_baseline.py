"""Run one locked external RI-3 baseline on prepared development inputs.

This runner is deliberately target-blind: it reads only the prepared input
paths from the runtime manifest and writes detector-shaped records. Containers
are single-threaded, memory-bounded, checkpointed, and never write Atlas.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.evaluator_format import (  # noqa: E402
    DetectorEvaluationRecord,
    adapt_fpocket_pockets,
    adapt_p2rank_rows,
    failed_record,
)


BASELINE_CONFIG = {
    "fpocket": {
        "display_name": "fpocket",
        "version": "4.2.3",
        "commit": "4bb0d8447f62fee77e2c3c29f54b5fcaf5e2c066",
        "image": "biovoid-fpocket-ri3:4.2.3",
        "memory": "2g",
        "timeout_seconds": 180,
    },
    "p2rank": {
        "display_name": "P2Rank",
        "version": "2.5.1",
        "commit": "9808a7723be9a94e2ffc21ab5f724cb6ae4ba01e",
        "image": "biovoid-p2rank-ri3:2.5.1",
        "memory": "2g",
        "timeout_seconds": 240,
    },
}
REPORT_SCHEMA_VERSION = "biovoid-ri3-external-baseline-run-v1"
DEFAULT_MANIFEST = REPO_ROOT / "data/runtime/ri3/cryptobench-development-runtime-manifest-v1.json"
DEFAULT_WORK_ROOT = REPO_ROOT / "data/runtime/ri3/external-baselines-v1"
DEFAULT_TIMEOUT_SECONDS = 240
MAX_CASES_PER_INVOCATION = 663


class BaselineRunError(RuntimeError):
    """Raised when a baseline run violates the frozen runtime contract."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineRunError(f"Cannot read JSON runtime file: {path}") from exc
    if not isinstance(payload, dict):
        raise BaselineRunError(f"Expected JSON object: {path}")
    return payload


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _docker_image_id(image: str) -> str:
    result = subprocess.run(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise BaselineRunError(f"Docker image is unavailable: {image}")
    return result.stdout.strip()


def _safe_child(root: Path, child: Path) -> Path:
    resolved_root = root.resolve()
    resolved_child = child.resolve()
    if resolved_child != resolved_root and resolved_root not in resolved_child.parents:
        raise BaselineRunError(f"Runtime path escapes work root: {resolved_child}")
    return resolved_child


def _parse_atom_center(path: Path) -> tuple[float, float, float] | None:
    coordinates: list[tuple[float, float, float]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not (line.startswith("ATOM") or line.startswith("HETATM")):
            continue
        try:
            coordinates.append(
                (
                    float(line[30:38].strip()),
                    float(line[38:46].strip()),
                    float(line[46:54].strip()),
                )
            )
        except (ValueError, IndexError):
            fields = line.split()
            if len(fields) >= 9:
                try:
                    coordinates.append((float(fields[6]), float(fields[7]), float(fields[8])))
                except ValueError:
                    continue
    if not coordinates:
        return None
    return tuple(
        sum(coordinate[index] for coordinate in coordinates) / len(coordinates)
        for index in range(3)
    )


def _parse_fpocket_info(path: Path) -> dict[int, dict[str, float]]:
    values: dict[int, dict[str, float]] = {}
    current_id: int | None = None
    pocket_pattern = re.compile(r"pocket\s*(\d+)", re.IGNORECASE)
    number_pattern = re.compile(r"(-?\d+(?:\.\d+)?)")
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        pocket_match = pocket_pattern.search(line)
        if pocket_match:
            current_id = int(pocket_match.group(1))
            values.setdefault(current_id, {})
        if current_id is None:
            continue
        numbers = [float(value) for value in number_pattern.findall(line)]
        if not numbers:
            continue
        lowered = line.lower()
        if "drugg" in lowered and "score" in lowered:
            values[current_id]["druggability_score"] = numbers[-1]
        elif "volume" in lowered and "volume score" not in lowered:
            values[current_id]["volume"] = numbers[-1]
        elif lowered.strip().startswith("score"):
            values[current_id]["score"] = numbers[-1]
    return values


def _parse_fpocket_output(output_dir: Path) -> list[dict[str, Any]]:
    info_files = sorted(output_dir.glob("*_info.txt"))
    info = _parse_fpocket_info(info_files[0]) if info_files else {}
    pockets_dir = output_dir / "pockets"
    rows: list[dict[str, Any]] = []
    for pocket_path in sorted(pockets_dir.glob("pocket*_atm.pdb")):
        match = re.search(r"pocket(\d+)_atm\.pdb", pocket_path.name, flags=re.IGNORECASE)
        if not match:
            continue
        pocket_id = int(match.group(1))
        center = _parse_atom_center(pocket_path)
        if center is None:
            continue
        metrics = info.get(pocket_id, {})
        score = metrics.get("score")
        rows.append(
            {
                "pocket_id": pocket_id,
                "center": center,
                "volume": metrics.get("volume"),
                "score": score,
                "druggability_score": metrics.get("druggability_score"),
            }
        )
    rows.sort(
        key=lambda row: (
            0 if isinstance(row.get("score"), (int, float)) and math.isfinite(row["score"]) else 1,
            -float(row["score"]) if isinstance(row.get("score"), (int, float)) and math.isfinite(row["score"]) else 0.0,
            int(row["pocket_id"]),
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows[:20]


def _normalize_csv_row(row: Mapping[str | None, str | None]) -> dict[str, Any]:
    normalized = {
        str(key).strip(): (value.strip() if isinstance(value, str) else value)
        for key, value in row.items()
        if key is not None
    }
    if not normalized.get("center_x"):
        raise BaselineRunError("P2Rank row has no center_x")
    normalized["rank"] = int(str(normalized["rank"]).strip())
    for field in ("score", "center_x", "center_y", "center_z", "probability"):
        if normalized.get(field) not in (None, ""):
            normalized[field] = float(str(normalized[field]))
    normalized["volume"] = None
    normalized["residues"] = tuple(
        value for value in str(normalized.get("residue_ids", "")).split() if value
    )
    return normalized


def _parse_p2rank_output(output_dir: Path, input_name: str) -> list[dict[str, Any]]:
    candidates = sorted(output_dir.glob(f"{input_name}_predictions.csv"))
    if not candidates:
        candidates = sorted(output_dir.glob("*_predictions.csv"))
    if not candidates:
        raise BaselineRunError("P2Rank predictions CSV is missing")
    with candidates[0].open(newline="", encoding="utf-8", errors="replace") as handle:
        rows = [_normalize_csv_row(row) for row in csv.DictReader(handle)]
    return rows[:20]


def _run_container(
    *,
    tool: str,
    config: Mapping[str, Any],
    work_dir: Path,
    input_name: str,
) -> tuple[int, str, str, float]:
    mount = f"type=bind,source={work_dir},target=/work"
    command = [
        "docker",
        "run",
        "--rm",
        "--memory",
        str(config["memory"]),
        "--cpus",
        "1",
        "--mount",
        mount,
        "-w",
        "/work",
        str(config["image"]),
    ]
    if tool == "fpocket":
        command.extend(["-f", f"/work/{input_name}"])
    elif tool == "p2rank":
        command.extend(
            [
                "predict",
                "-f",
                f"/work/{input_name}",
                "-o",
                "/work/p2rank-output",
                "-threads",
                "1",
                "-visualizations",
                "0",
            ]
        )
    else:
        raise BaselineRunError(f"Unsupported baseline: {tool}")
    started = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=int(config["timeout_seconds"]),
        )
    except subprocess.TimeoutExpired as exc:
        return 124, str(exc.stdout or ""), str(exc.stderr or ""), time.perf_counter() - started
    return result.returncode, result.stdout, result.stderr, time.perf_counter() - started


def _record_for_case(
    *,
    tool: str,
    config: Mapping[str, Any],
    image_id: str,
    structure: Mapping[str, Any],
    work_root: Path,
    runner_id: str = "ri3-external-baseline-v1",
) -> tuple[DetectorEvaluationRecord, dict[str, Any]]:
    structure_id = str(structure["structure_id"]).upper()
    prepared_path = (REPO_ROOT / str(structure["prepared_path"])).resolve()
    if not prepared_path.is_file():
        return (
            failed_record(tool, structure_id, f"Prepared structure is missing: {prepared_path}"),
            {"status": "failed", "error": "prepared_structure_missing"},
        )
    case_root = _safe_child(work_root, work_root / structure_id.lower())
    if case_root.exists():
        shutil.rmtree(case_root)
    case_root.mkdir(parents=True, exist_ok=True)
    input_name = "prepared_detector.pdb"
    shutil.copy2(prepared_path, case_root / input_name)
    return_code, stdout, stderr, runtime_seconds = _run_container(
        tool=tool,
        config=config,
        work_dir=case_root,
        input_name=input_name,
    )
    common = {
        "status": "completed" if return_code == 0 else "failed",
        "return_code": return_code,
        "runtime_seconds": round(runtime_seconds, 6),
        "stdout_tail": stdout[-2000:],
        "stderr_tail": stderr[-2000:],
    }
    if return_code != 0:
        return failed_record(tool, structure_id, f"Container exited with code {return_code}"), common
    try:
        if tool == "fpocket":
            output_dir = case_root / "prepared_detector_out"
            rows = _parse_fpocket_output(output_dir)
            record = adapt_fpocket_pockets(
                structure_id,
                rows,
                provenance={
                    "runner": runner_id,
                    "target_blind": True,
                    "prepared_structure_sha256": structure["prepared_structure_sha256"],
                    "tool_commit": config["commit"],
                    "container_image": config["image"],
                    "container_image_id": image_id,
                },
            )
        else:
            rows = _parse_p2rank_output(case_root / "p2rank-output", input_name)
            record = adapt_p2rank_rows(
                structure_id,
                rows,
                provenance={
                    "runner": runner_id,
                    "target_blind": True,
                    "prepared_structure_sha256": structure["prepared_structure_sha256"],
                    "tool_commit": config["commit"],
                    "container_image": config["image"],
                    "container_image_id": image_id,
                },
            )
    except (OSError, ValueError, KeyError, BaselineRunError) as exc:
        common["status"] = "failed"
        common["error"] = f"{type(exc).__name__}: {exc}"
        return failed_record(tool, structure_id, common["error"]), common
    common["pocket_count"] = len(record.pockets)
    common["detector_record"] = asdict(record)
    return record, common


def _initial_report(*, tool: str, manifest: Mapping[str, Any], image_id: str) -> dict[str, Any]:
    config = BASELINE_CONFIG[tool]
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_id": f"ri3-{tool}-baseline-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "status": "not_started",
        "tool": tool,
        "tool_version": config["version"],
        "tool_commit": config["commit"],
        "container_image": config["image"],
        "container_image_id": image_id,
        "manifest_sha256": manifest["manifest_sha256"],
        "target_blind": True,
        "sealed_evaluation_authorized": False,
        "resource_limits": {
            "workers": 1,
            "cpus": 1,
            "memory": config["memory"],
            "timeout_seconds": config["timeout_seconds"],
        },
        "records": {},
        "counts": {"completed": 0, "failed": 0},
    }


def _validate_report(report: Mapping[str, Any], *, tool: str, manifest: Mapping[str, Any], image_id: str) -> None:
    config = BASELINE_CONFIG[tool]
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise BaselineRunError("External baseline report schema mismatch")
    if report.get("tool") != tool or report.get("tool_commit") != config["commit"]:
        raise BaselineRunError("External baseline identity mismatch")
    if report.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise BaselineRunError("External baseline manifest hash mismatch")
    if report.get("container_image_id") != image_id:
        raise BaselineRunError("Container image changed after checkpoint")
    if report.get("target_blind") is not True or report.get("sealed_evaluation_authorized") is not False:
        raise BaselineRunError("Baseline report boundary is invalid")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", choices=tuple(BASELINE_CONFIG), required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--all-development", action="store_true")
    parser.add_argument("--max-cases", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.max_cases < 1 or args.max_cases > MAX_CASES_PER_INVOCATION:
        raise BaselineRunError("max-cases is outside the allowed development range")
    if args.batch_size < 1 or args.batch_size > 10:
        raise BaselineRunError("batch-size must be between 1 and 10")
    config = BASELINE_CONFIG[args.baseline]
    manifest_path = args.manifest if args.manifest.is_absolute() else REPO_ROOT / args.manifest
    work_root = args.work_root if args.work_root.is_absolute() else REPO_ROOT / args.work_root
    report_path = args.report
    if report_path is None:
        report_path = work_root / f"{args.baseline}-development-v1.json"
    elif not report_path.is_absolute():
        report_path = REPO_ROOT / report_path
    manifest = _read_json(manifest_path)
    structures = sorted(manifest.get("structures", []), key=lambda item: str(item["structure_id"]))
    if len(structures) != 663:
        raise BaselineRunError(f"Expected 663 prepared structures, found {len(structures)}")
    if len({str(item["structure_id"]).upper() for item in structures}) != len(structures):
        raise BaselineRunError("Prepared structure IDs are not unique")
    image_id = _docker_image_id(str(config["image"]))
    report = (
        _read_json(report_path)
        if report_path.is_file()
        else _initial_report(tool=args.baseline, manifest=manifest, image_id=image_id)
    )
    _validate_report(report, tool=args.baseline, manifest=manifest, image_id=image_id)
    report["records"] = dict(report.get("records", {}))
    pending = [
        structure
        for structure in structures
        if str(structure["structure_id"]).upper() not in report["records"]
    ]
    selected = pending if args.all_development else pending[: args.max_cases]
    work_root = _safe_child(REPO_ROOT / "data/runtime/ri3", work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    run_root = _safe_child(work_root, work_root / args.baseline)
    run_root.mkdir(parents=True, exist_ok=True)
    report["status"] = "running"
    report["updated_at_utc"] = _utc_now()
    for index, structure in enumerate(selected, start=1):
        structure_id = str(structure["structure_id"]).upper()
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
        report["counts"] = {
            "completed": sum(item.get("detector_status") == "completed" for item in report["records"].values()),
            "failed": sum(item.get("detector_status") == "failed" for item in report["records"].values()),
        }
        report["updated_at_utc"] = _utc_now()
        if index % args.batch_size == 0 or index == len(selected):
            _write_json_atomic(report_path, report)
            print(f"checkpoint counts={report['counts']}", flush=True)
    report["counts"] = {
        "completed": sum(item.get("detector_status") == "completed" for item in report["records"].values()),
        "failed": sum(item.get("detector_status") == "failed" for item in report["records"].values()),
    }
    report["status"] = "complete" if len(report["records"]) == len(structures) else "partial"
    report["updated_at_utc"] = _utc_now()
    _write_json_atomic(report_path, report)
    print(
        f"RI-3 {args.baseline} baseline: {report['status']} "
        f"records={len(report['records'])}/663 completed={report['counts']['completed']} "
        f"failed={report['counts']['failed']}",
    )
    print(f"baseline report: {report_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaselineRunError as exc:
        print(f"RI-3 external baseline error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

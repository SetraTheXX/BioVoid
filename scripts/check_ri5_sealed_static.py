"""Validate the RI-5 sealed static execution without promoting partial evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.benchmark_v1 import BenchmarkCase, BenchmarkManifest, phase6_frozen_protocol_v1  # noqa: E402


DEFAULT_ROOT = REPO_ROOT / "data/runtime/ri5"
DEFAULT_PREP = DEFAULT_ROOT / "sealed-preparation-v1.json"
DEFAULT_MANIFEST = DEFAULT_ROOT / "sealed-runtime-manifest-v1.json"
DEFAULT_LEDGER = DEFAULT_ROOT / "sealed-holdout-ledger-v1.json"
DEFAULT_RUN = DEFAULT_ROOT / "sealed-static-run-v1.json"
DEFAULT_EVALUATION = DEFAULT_ROOT / "sealed-static-evaluation-v1.json"


class RI5CheckError(RuntimeError):
    """Raised when an RI-5 runtime contract is invalid."""


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RI5CheckError(f"Expected JSON object: {path}")
    return payload


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _check_target_blind_manifest(manifest: Mapping[str, Any]) -> None:
    expected = _stable_hash({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    if manifest.get("manifest_sha256") != expected:
        raise RI5CheckError("RI-5 runtime manifest hash mismatch")
    if manifest.get("split") != "sealed" or manifest.get("structure_count") != 222:
        raise RI5CheckError("RI-5 manifest cohort is not the locked 222-structure sealed split")
    if manifest.get("case_count") != 272:
        raise RI5CheckError("RI-5 manifest case count must be 272")
    boundary = manifest.get("detector_boundary", {})
    if boundary.get("target_blind") is not True or boundary.get("evaluator_fields_in_manifest") is not False:
        raise RI5CheckError("RI-5 detector boundary is not target-blind")
    forbidden = {
        "holo_pdb_id",
        "holo_chain",
        "ligand",
        "ligand_center",
        "ligand_atoms",
        "target_center",
        "target_residues",
        "hit_label",
        "apo_pocket_selection",
    }
    encoded = json.dumps(manifest, ensure_ascii=True).lower()
    leaked = sorted(key for key in forbidden if f'"{key}"' in encoded)
    if leaked:
        raise RI5CheckError("Evaluator fields leaked into sealed manifest: " + ", ".join(leaked))
    BenchmarkManifest(
        cases=tuple(BenchmarkCase(**raw) for raw in manifest["benchmark_manifest"]["cases"])
    )


def _check_evaluation_integrity(evaluation: Mapping[str, Any]) -> dict[str, int]:
    """Require terminal RI-5 accounting without promoting partial evidence."""
    if evaluation.get("detector_target_blind") is not True:
        raise RI5CheckError("RI-5 evaluator does not record a target-blind detector boundary")
    if evaluation.get("sealed_evaluation_authorized") is not True:
        raise RI5CheckError("RI-5 evaluator does not record sealed authorization")
    records = evaluation.get("records")
    if not isinstance(records, Mapping) or len(records) != 272:
        raise RI5CheckError("RI-5 evaluator must account for all 272 target-site rows")

    status_counts = {
        "completed_ground_truth": sum(
            raw.get("status") == "completed_ground_truth"
            for raw in records.values()
            if isinstance(raw, Mapping)
        ),
        "alignment_unavailable": sum(
            raw.get("status") == "alignment_unavailable"
            for raw in records.values()
            if isinstance(raw, Mapping)
        ),
    }
    if sum(status_counts.values()) != 272:
        raise RI5CheckError("RI-5 evaluator contains an unknown or unaccounted record status")

    summary = evaluation.get("summary")
    if not isinstance(summary, Mapping):
        raise RI5CheckError("RI-5 evaluator has no summary")
    if evaluation.get("status") == "partial":
        if summary.get("expected_cases") != 272:
            raise RI5CheckError("RI-5 evaluator summary expected-case count drifted")
        if summary.get("completed_ground_truth") != status_counts["completed_ground_truth"]:
            raise RI5CheckError("RI-5 evaluator completed-case count disagrees with records")
        if summary.get("alignment_unavailable") != status_counts["alignment_unavailable"]:
            raise RI5CheckError("RI-5 evaluator unavailable-case count disagrees with records")
        if summary.get("status") != "partial_evaluator_coverage_not_for_claim":
            raise RI5CheckError("RI-5 partial evaluator lacks an explicit no-claim status")
    elif status_counts != {"completed_ground_truth": 272, "alignment_unavailable": 0}:
        raise RI5CheckError("RI-5 complete evaluator contains unavailable target-site rows")
    if summary.get("scientific_superiority_claim_authorized") is not False:
        raise RI5CheckError("RI-5 evaluator authorizes an unsupported scientific claim")

    report_hash = evaluation.get("report_sha256")
    expected_hash = _stable_hash(
        {key: value for key, value in evaluation.items() if key != "report_sha256"}
    )
    if report_hash != expected_hash:
        raise RI5CheckError("RI-5 evaluator report hash mismatch")
    return status_counts


def check(
    *,
    preparation_path: Path = DEFAULT_PREP,
    manifest_path: Path = DEFAULT_MANIFEST,
    ledger_path: Path = DEFAULT_LEDGER,
    run_path: Path = DEFAULT_RUN,
    evaluation_path: Path = DEFAULT_EVALUATION,
) -> dict[str, Any]:
    preparation = _read(preparation_path)
    if preparation.get("schema_version") != "biovoid-ri5-sealed-preparation-v1":
        raise RI5CheckError("Unexpected RI-5 preparation schema")
    if preparation.get("status") != "complete" or preparation.get("structure_count") != 222:
        raise RI5CheckError("RI-5 preparation is incomplete")
    if preparation.get("archive", {}).get("full_archive_downloaded") is not False:
        raise RI5CheckError("RI-5 preparation indicates a full archive download")
    prep_records = preparation.get("records", [])
    if len(prep_records) != 222 or any(item.get("status") != "eligible" for item in prep_records):
        raise RI5CheckError("RI-5 preparation has non-eligible records")

    manifest = _read(manifest_path)
    _check_target_blind_manifest(manifest)
    ledger = _read(ledger_path)
    expected_case_manifest_hash = manifest["benchmark_manifest"]["manifest_sha256"]
    if ledger.get("schema_version") != "sealed-holdout-ledger-v1" or ledger.get("opened") is not True:
        raise RI5CheckError("RI-5 sealed ledger is not open")
    if ledger.get("manifest_sha256") != expected_case_manifest_hash:
        raise RI5CheckError("RI-5 ledger and case manifest differ")
    if ledger.get("protocol_sha256") != phase6_frozen_protocol_v1().protocol_sha256:
        raise RI5CheckError("RI-5 ledger and protocol differ")

    run = _read(run_path)
    if run.get("schema_version") != "biovoid-ri5-sealed-static-run-v1":
        raise RI5CheckError("Unexpected RI-5 static run schema")
    if run.get("status") != "complete" or len(run.get("records", {})) != 222:
        raise RI5CheckError("RI-5 static arm is not complete")
    if run.get("execution", {}).get("workers") != 1:
        raise RI5CheckError("RI-5 static arm was not single-worker")
    if run.get("execution", {}).get("nma_started") is not False:
        raise RI5CheckError("RI-5 static arm has an unexpected NMA flag")
    if run.get("execution", {}).get("sealed_evaluation_authorized") is not True:
        raise RI5CheckError("RI-5 static arm does not record ledger authorization")
    counts = run.get("counts", {})
    if counts.get("failed") != 0 or counts.get("completed", 0) + counts.get("resource_blocked", 0) != 222:
        raise RI5CheckError("RI-5 static arm counts are inconsistent")

    evaluation = _read(evaluation_path)
    if evaluation.get("schema_version") != "biovoid-ri5-sealed-static-evaluation-v1":
        raise RI5CheckError("Unexpected RI-5 evaluation schema")
    if evaluation.get("status") not in {"partial", "complete"}:
        raise RI5CheckError("RI-5 evaluator has no terminal status")
    status_counts = _check_evaluation_integrity(evaluation)
    summary = evaluation["summary"]
    result = {
        "preparation": "PASS",
        "manifest": "PASS",
        "ledger": "PASS",
        "static_arm": "PASS",
        "evaluation_status": evaluation.get("status"),
        "static_counts": counts,
        "evaluator_coverage": {
            "completed_ground_truth": summary.get("completed_ground_truth"),
            "expected_cases": summary.get("expected_cases"),
            "alignment_unavailable": summary.get("alignment_unavailable"),
            "record_status_counts": status_counts,
        },
        "phase_disposition": "CLOSED_WITHOUT_CLAIM",
        "scientific_claim": "NO-GO",
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preparation", type=Path, default=DEFAULT_PREP)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--run", dest="run_path", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--evaluation", type=Path, default=DEFAULT_EVALUATION)
    args = parser.parse_args()
    result = check(
        preparation_path=args.preparation,
        manifest_path=args.manifest,
        ledger_path=args.ledger,
        run_path=args.run_path,
        evaluation_path=args.evaluation,
    )
    print(
        "RI-5 sealed static check: PASS "
        f"static={result['static_counts']} "
        f"evaluator={result['evaluation_status']} "
        f"claim={result['scientific_claim']}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RI5CheckError as exc:
        print(f"RI-5 check: FAIL {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

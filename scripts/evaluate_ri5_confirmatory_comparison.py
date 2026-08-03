"""Compare BioVoid static, fpocket, and P2Rank on the RI-5 confirmatory cohort."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluate_ri3_external_comparison import _load_baseline_records  # noqa: E402
from scripts.evaluate_ri3_static_development import (  # noqa: E402
    _ground_truth_from_payload,
    _load_detector_records,
)
from scripts.run_ri5_confirmatory_static import _ground_truth_payload  # noqa: E402
from src.benchmark_v1 import (  # noqa: E402
    BenchmarkCase,
    BenchmarkManifest,
    evaluate_split,
    phase6_frozen_protocol_v1,
)
from src.evaluator_v3 import stable_hash  # noqa: E402


DEFAULT_ROOT = REPO_ROOT / "data/runtime/ri5-confirmatory"
DEFAULT_MANIFEST = DEFAULT_ROOT / "confirmatory-runtime-manifest-v1.json"
DEFAULT_STATIC_RUN = DEFAULT_ROOT / "confirmatory-static-run-v1.json"
DEFAULT_EVALUATION = DEFAULT_ROOT / "confirmatory-static-evaluation-v1.json"
DEFAULT_FPOCKET = DEFAULT_ROOT / "external-baselines-v1/fpocket-confirmatory-v1.json"
DEFAULT_P2RANK = DEFAULT_ROOT / "external-baselines-v1/p2rank-confirmatory-v1.json"
DEFAULT_OUTPUT = DEFAULT_ROOT / "confirmatory-static-baseline-comparison-v1.json"
REPORT_SCHEMA = "biovoid-ri5-confirmatory-static-baseline-comparison-v1"


class ConfirmatoryComparisonError(RuntimeError):
    """Raised when confirmatory comparison evidence is incomplete or inconsistent."""


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ConfirmatoryComparisonError(f"Expected JSON object: {path}")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _baseline_payload_for_legacy_parser(payload: Mapping[str, Any]) -> dict[str, Any]:
    copy = dict(payload)
    copy["schema_version"] = "biovoid-ri3-external-baseline-run-v1"
    return copy


def _metric_at_rank(result: Mapping[str, Any], metric: str, rank: int) -> float:
    values = result.get(metric)
    if not isinstance(values, Mapping):
        raise ConfirmatoryComparisonError(f"Comparison result is missing {metric}")
    value = values.get(rank, values.get(str(rank)))
    if value is None:
        raise ConfirmatoryComparisonError(f"Comparison result is missing {metric}[{rank}]")
    return float(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--static-run", type=Path, default=DEFAULT_STATIC_RUN)
    parser.add_argument("--evaluation", type=Path, default=DEFAULT_EVALUATION)
    parser.add_argument("--fpocket", type=Path, default=DEFAULT_FPOCKET)
    parser.add_argument("--p2rank", type=Path, default=DEFAULT_P2RANK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    manifest = _read(args.manifest)
    static_run = _read(args.static_run)
    evaluation = _read(args.evaluation)
    fpocket = _read(args.fpocket)
    p2rank = _read(args.p2rank)
    if evaluation.get("status") != "complete":
        raise ConfirmatoryComparisonError("Confirmatory evaluator is incomplete")
    for baseline in (fpocket, p2rank):
        if baseline.get("schema_version") != "biovoid-ri5-confirmatory-external-baseline-v1":
            raise ConfirmatoryComparisonError("Unexpected confirmatory baseline schema")
        if baseline.get("status") != "complete" or baseline.get("target_blind") is not True:
            raise ConfirmatoryComparisonError("Confirmatory baseline is incomplete or not blind")
        if baseline.get("manifest_sha256") != manifest.get("manifest_sha256"):
            raise ConfirmatoryComparisonError("Baseline and confirmatory manifest differ")
    structures = {str(item["structure_id"]): item for item in manifest["structures"]}
    eligible_records = {
        case_id: raw
        for case_id, raw in evaluation["records"].items()
        if raw.get("status") == "completed_ground_truth"
    }
    cases = []
    truths = {}
    for case_id, raw in sorted(eligible_records.items()):
        truth = _ground_truth_from_payload(_ground_truth_payload(raw))
        truths[case_id.casefold()] = truth
        structure = structures[truth.structure_id.upper()]
        cases.append(
            BenchmarkCase(
                case_id=case_id,
                structure_id=truth.structure_id.upper(),
                family_id=next(
                    item["family_id"]
                    for item in manifest["structures"]
                    if item["structure_id"] == truth.structure_id.upper()
                ),
                split="validation",
                prepared_structure_sha256=structure["prepared_structure_sha256"],
                preparation_config_sha256=structure["preparation_config_sha256"],
            )
        )
    eligible_manifest = BenchmarkManifest(cases=tuple(cases))
    centers: dict[str, set[tuple[float, float, float]]] = {}
    for truth in truths.values():
        centers.setdefault(truth.structure_id.upper(), set()).add(truth.ligand_center)
    references = {key: tuple(sorted(value)) for key, value in centers.items()}
    detectors = {
        "biovoid_static": _load_detector_records(static_run, expected_count=222),
        "fpocket": _load_baseline_records(
            _baseline_payload_for_legacy_parser(fpocket), detector="fpocket"
        ),
        "p2rank": _load_baseline_records(
            _baseline_payload_for_legacy_parser(p2rank), detector="p2rank"
        ),
    }
    results = {
        detector: evaluate_split(
            detector=detector,
            split="validation",
            records=records,
            ground_truth=truths,
            binding_site_reference_centers=references,
            manifest=eligible_manifest,
            protocol=phase6_frozen_protocol_v1(),
        )
        for detector, records in detectors.items()
    }
    primary = {
        detector: _metric_at_rank(result, "top_k_dcc_recall", 3)
        for detector, result in results.items()
    }
    output: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA,
        "status": "complete_local_blinded_static_baseline_confirmation",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "protocol": phase6_frozen_protocol_v1().to_manifest(),
        "manifest_sha256": manifest["manifest_sha256"],
        "evaluation_report_sha256": _sha256_file(args.evaluation),
        "baseline_report_sha256": {
            "fpocket": _sha256_file(args.fpocket),
            "p2rank": _sha256_file(args.p2rank),
        },
        "coverage": {
            "planned_cases": evaluation["summary"]["planned_cases"],
            "evaluator_eligible": evaluation["summary"]["evaluator_eligible"],
            "evaluator_ineligible": evaluation["summary"]["evaluator_ineligible"],
        },
        "results": results,
        "primary_endpoint": {
            "name": "top_3_dcc_localization_recall_at_4A",
            "values": primary,
            "biovoid_minus_fpocket": round(primary["biovoid_static"] - primary["fpocket"], 8),
            "biovoid_minus_p2rank": round(primary["biovoid_static"] - primary["p2rank"], 8),
        },
        "decision": {
            "static_and_baselines_completed": True,
            "motion_required_by_protocol": False,
            "motion_started": False,
            "external_replication": False,
            "scientific_superiority_claim_authorized": False,
            "interpretation": "local_blinded_confirmation_with_cluster_bootstrap_not_external_replication",
        },
    }
    output["report_sha256"] = stable_hash(output)
    _write(args.output, output)
    print(
        "RI-5.3 confirmatory comparison complete: "
        f"cases={output['coverage']['evaluator_eligible']} primary={primary}"
    )
    print(
        "claim=NO-GO_EXTERNAL_REPLICATION_PENDING "
        f"motion_started={str(output['decision']['motion_started']).lower()}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ConfirmatoryComparisonError as exc:
        print(f"RI-5 confirmatory comparison error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

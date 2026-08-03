"""Close the bounded RI-6 v1 run without making a scientific claim."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_ri6_prospective_static import (  # noqa: E402
    _stable_hash,
    _validate_prospective_output,
)
from scripts.run_ri6_tem1_transfer_control import RI6ContractError  # noqa: E402


DEFAULT_ROOT = REPO_ROOT / "data/runtime/ri6/prospective-static"
CLOSURE_SCHEMA_VERSION = "biovoid-ri6-closure-v1"


def _build_closure_record(
    *,
    run_sha256: str,
    raw_pocket_count: int,
    candidate_count: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": CLOSURE_SCHEMA_VERSION,
        "status": "ri6_v1_closed_without_scientific_claim",
        "closure_scope": "bounded_target_blind_static_engineering_run",
        "source_run_sha256": run_sha256,
        "raw_pocket_count": int(raw_pocket_count),
        "candidate_count": int(candidate_count),
        "candidate_budget": 10,
        "motion_enabled": False,
        "scientific_interpretation_authorized": False,
        "independent_review_status": "pending",
        "next_gate": "independent_candidate_review",
        "claim_boundary": "unvalidated_research_leads_only",
        "closure_basis": [
            "Frozen target and source contract was applied",
            "One target-blind static run completed",
            "Candidate manifest was hash-linked and kept local",
            "No NMA, baseline, batch benchmark, or evaluator score was used",
        ],
        "limitations": [
            "One source cannot establish transferability or performance",
            "Candidate coordinates remain uninterpreted pending independent review",
            "No discovery, prediction, drug utility, or superiority claim is authorized",
        ],
    }
    payload["closure_sha256"] = _stable_hash(payload)
    return payload


def _validate_closure_record(
    payload: Mapping[str, Any], *, verify_hash: bool = True
) -> None:
    if verify_hash:
        expected = _stable_hash(
            {key: value for key, value in payload.items() if key != "closure_sha256"}
        )
        if payload.get("closure_sha256") != expected:
            raise RI6ContractError("RI-6 closure hash does not match its content")
    if payload.get("schema_version") != CLOSURE_SCHEMA_VERSION:
        raise RI6ContractError("Unexpected RI-6 closure schema")
    if payload.get("status") != "ri6_v1_closed_without_scientific_claim":
        raise RI6ContractError("RI-6 closure status is not the no-claim status")
    if payload.get("scientific_interpretation_authorized") is not False:
        raise RI6ContractError("RI-6 closure authorized scientific interpretation")
    if payload.get("independent_review_status") != "pending":
        raise RI6ContractError("RI-6 closure changed the independent review status")
    if payload.get("next_gate") != "independent_candidate_review":
        raise RI6ContractError("RI-6 closure is missing its independent-review gate")
    raw_count = int(payload.get("raw_pocket_count", -1))
    candidate_count = int(payload.get("candidate_count", -1))
    budget = int(payload.get("candidate_budget", -1))
    if raw_count < candidate_count or candidate_count < 0 or budget != 10:
        raise RI6ContractError("RI-6 closure candidate accounting is invalid")
    if candidate_count > budget:
        raise RI6ContractError("RI-6 closure exceeds the frozen candidate budget")
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True).lower()
    required_boundary = "no discovery, prediction, drug utility, or superiority claim is authorized"
    if required_boundary not in encoded:
        raise RI6ContractError("RI-6 closure does not state its no-claim boundary")


def close_run(output_root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    run_path = output_root / "ri6-prospective-static-run-v1.json"
    if not run_path.is_file():
        raise RI6ContractError(f"RI-6 prospective run is missing: {run_path}")
    output = json.loads(run_path.read_text(encoding="utf-8"))
    if not isinstance(output, dict):
        raise RI6ContractError("RI-6 prospective run must be a JSON object")
    _validate_prospective_output(output)
    closure = _build_closure_record(
        run_sha256=str(output["run_sha256"]),
        raw_pocket_count=int(output["detector_candidate_count"]),
        candidate_count=len(output["candidates"]),
    )
    _validate_closure_record(closure)
    destination = output_root / "ri6-closure-v1.json"
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(closure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return closure


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    closure = close_run(args.output_root.resolve())
    print(f"status={closure['status']}")
    print(f"closure_sha256={closure['closure_sha256']}")
    print(f"next_gate={closure['next_gate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

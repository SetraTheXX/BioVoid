"""Write the public RI-6 class-A beta-lactamase target/source lock."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_ri6_tem1_transfer_control import RI6ContractError  # noqa: E402


TARGET_ACCESSIONS = ("A0A5R8T042", "Q2PUH3", "Q9F663")
KNOWN_CLASS_A_CRYPTOBENCH_OVERLAP = ("A2RP81",)


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_target_lock(cryptobench_accessions: Iterable[str]) -> dict[str, Any]:
    benchmark = {str(value).strip().upper() for value in cryptobench_accessions}
    exact_overlap = sorted(set(TARGET_ACCESSIONS) & benchmark)
    if exact_overlap:
        raise RI6ContractError(
            "RI-6 target accessions overlap CryptoBench: " + ", ".join(exact_overlap)
        )
    family_overlap = sorted(set(KNOWN_CLASS_A_CRYPTOBENCH_OVERLAP) & benchmark)
    payload: dict[str, Any] = {
        "schema_version": "biovoid-ri6-target-lock-v1",
        "status": "frozen_before_candidate_screening",
        "biological_question": (
            "Can target-blind canonical static BioVoid analysis identify reproducible "
            "non-catalytic pocket candidates in eligible apo KPC-2 or CTX-M-15 structures?"
        ),
        "target": {
            "family": "class A serine beta-lactamases",
            "primary_subfamilies": ["KPC-2", "CTX-M-15"],
            "primary_uniprot_accessions": list(TARGET_ACCESSIONS),
            "excluded_subfamilies": ["PER"],
            "excluded_control_proteins": ["TEM-1"],
        },
        "source_snapshot": {
            "snapshot_date": "2026-08-02",
            "uniprot_release": "2026_02",
            "uniprot_release_date": "2026-06-10",
            "amrfinderplus_database": "2026-05-15.1",
            "rcsb_entry_count_observed": 257571,
            "coordinate_provider": "RCSB PDB",
        },
        "inclusion": {
            "experimental_method": "X-RAY DIFFRACTION",
            "maximum_resolution_angstrom": 2.2,
            "representation": "asymmetric_unit",
            "required_state": "experimentally unliganded target protein",
            "required_review": "manual metadata and structure review before detector execution",
        },
        "exclusion": [
            "PER subfamily and accession A2RP81",
            "catalytic or pocket-opening engineered mutations",
            "ligand-bound structures with the ligand computationally removed",
            "covalent adducts or inhibitor-bound target chains",
            "unresolved target identity or mixed-family assignment",
            "structures failing canonical full-heavy-atom preparation",
        ],
        "execution": {
            "canonical_arm": "static_only",
            "motion_arm": "disabled_not_eligible",
            "resource_profile": "safe-16gb",
            "heavy_concurrency": 1,
            "candidate_budget": 10,
            "ranking_rule": "canonical detector rank; raw components retained; no evaluator score",
            "interpretation_gate": "independent reviewer required",
        },
        "leakage_control": {
            "dataset": "CryptoBench",
            "exact_accession_overlap": exact_overlap,
            "known_family_overlap": family_overlap,
            "family_overlap_interpretation": (
                "Class-A family is not fully naive; PER-2 is excluded and the limitation remains public."
            ),
        },
        "claim_boundary": (
            "Outputs are unvalidated research leads, not discoveries, predictions, or drug candidates."
        ),
    }
    payload["lock_sha256"] = _stable_hash(payload)
    return payload


def _cryptobench_accessions(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    accessions: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() == "uniprot_id" and isinstance(item, str):
                    accessions.add(item.strip().upper())
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    if not accessions:
        raise RI6ContractError("CryptoBench metadata contains no structured uniprot_id fields")
    return accessions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cryptobench-dataset",
        type=Path,
        default=REPO_ROOT / "data/runtime/cryptobench-source/metadata/dataset.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "local-private/specs/ri6-target-lock-v1.json",
    )
    args = parser.parse_args()
    if not args.cryptobench_dataset.is_file():
        raise RI6ContractError(f"CryptoBench metadata is missing: {args.cryptobench_dataset}")
    lock = build_target_lock(_cryptobench_accessions(args.cryptobench_dataset))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"status={lock['status']}")
    print(f"lock_sha256={lock['lock_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Perform the user-authorized internal review of the bounded RI-6 run.

This review is intentionally not labelled independent or external validation.
It checks whether source non-protein components occupy the KPC-2 catalytic
core, then quarantines every candidate when the source fails that gate.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_ri6_prospective_static import _stable_hash  # noqa: E402
from scripts.run_ri6_tem1_transfer_control import RI6ContractError  # noqa: E402
from src.structure_preparation import (  # noqa: E402
    MODIFIED_AMINO_ACIDS,
    PROTEIN_RESIDUES,
    WATER_NAMES,
    load_structure_atoms,
)


DEFAULT_ROOT = REPO_ROOT / "data/runtime/ri6/prospective-static"
CORE_RESIDUE_IDS = frozenset(
    {69, 70, 73, 104, 105, 130, 131, 132, 166, 170, 220, 234, 235, 236, 237, 238}
)
CORE_PROXIMITY_ANGSTROM = 6.0
REVIEW_SCHEMA_VERSION = "biovoid-ri6-internal-review-v1"


def _distance(left: Sequence[float], right: Sequence[float]) -> float:
    return math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(left, right, strict=True)))


def _source_component_decision(component: Mapping[str, Any]) -> str:
    if float(component["minimum_core_distance_angstrom"]) <= CORE_PROXIMITY_ANGSTROM:
        return "source_rejected_active_site_occupancy"
    return "component_not_core_proximal"


def _residue_id(value: str) -> int | None:
    parts = str(value).split(":")
    if len(parts) != 3:
        return None
    try:
        return int(parts[-1])
    except ValueError:
        return None


def _review_candidate(
    *,
    rank: int,
    pocket_id: str,
    volume: float,
    residues: Sequence[str],
    minimum_core_distance_angstrom: float,
    source_eligible: bool,
) -> dict[str, Any]:
    core_residues = sorted(
        residue_id for residue in residues if (residue_id := _residue_id(residue)) in CORE_RESIDUE_IDS
    )
    if not source_eligible:
        decision = "rejected_source_active_site_occupancy"
    elif core_residues or minimum_core_distance_angstrom <= CORE_PROXIMITY_ANGSTROM:
        decision = "rejected_catalytic_adjacency"
    else:
        decision = "unvalidated_non_catalytic_candidate_pending_external_review"
    return {
        "rank": int(rank),
        "pocket_id": str(pocket_id),
        "volume": float(volume),
        "core_residue_ids": core_residues,
        "minimum_core_distance_angstrom": round(float(minimum_core_distance_angstrom), 6),
        "decision": decision,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RI6ContractError(f"Required RI-6 runtime evidence is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RI6ContractError(f"Expected a JSON object: {path}")
    return payload


def _core_atoms(source_path: Path) -> tuple[Any, ...]:
    protein_names = PROTEIN_RESIDUES | MODIFIED_AMINO_ACIDS
    atoms = load_structure_atoms(source_path)
    return tuple(
        atom
        for atom in atoms
        if atom.chain_id == "A"
        and atom.res_name in protein_names
        and atom.res_id in CORE_RESIDUE_IDS
        and atom.element not in {"H", "D"}
    )


def _source_components(source_path: Path, core_atoms: Sequence[Any]) -> list[dict[str, Any]]:
    protein_names = PROTEIN_RESIDUES | MODIFIED_AMINO_ACIDS
    atoms = load_structure_atoms(source_path)
    grouped: dict[tuple[str, str, int, str], list[Any]] = {}
    for atom in atoms:
        if atom.res_name in protein_names or atom.res_name in WATER_NAMES or atom.element in {"H", "D"}:
            continue
        key = (atom.res_name, atom.chain_id, atom.res_id, atom.ins_code)
        grouped.setdefault(key, []).append(atom)
    components: list[dict[str, Any]] = []
    for (name, chain, residue_id, insertion_code), component_atoms in sorted(grouped.items()):
        nearest = min(
            (
                (
                    _distance((atom.x, atom.y, atom.z), (core.x, core.y, core.z)),
                    atom,
                    core,
                )
                for atom in component_atoms
                for core in core_atoms
            ),
            key=lambda item: item[0],
        )
        distance, atom, core = nearest
        record: dict[str, Any] = {
            "component": name,
            "chain_id": chain,
            "residue_id": residue_id,
            "insertion_code": insertion_code,
            "minimum_core_distance_angstrom": round(distance, 6),
            "nearest_component_atom": atom.atom_name,
            "nearest_core_atom": f"A:{core.res_name}:{core.res_id}:{core.atom_name}",
        }
        record["decision"] = _source_component_decision(record)
        components.append(record)
    return components


def _minimum_center_distance(center: Sequence[float], core_atoms: Sequence[Any]) -> float:
    return min(_distance(center, (atom.x, atom.y, atom.z)) for atom in core_atoms)


def _validate_review(payload: Mapping[str, Any], *, verify_hash: bool = True) -> None:
    if verify_hash:
        expected = _stable_hash(
            {key: value for key, value in payload.items() if key != "review_sha256"}
        )
        if payload.get("review_sha256") != expected:
            raise RI6ContractError("RI-6 internal review hash does not match its content")
    if payload.get("schema_version") != REVIEW_SCHEMA_VERSION:
        raise RI6ContractError("Unexpected RI-6 internal review schema")
    if payload.get("review_authority") != "user_authorized_internal_review":
        raise RI6ContractError("RI-6 review authority is not explicit")
    if payload.get("scientific_interpretation_authorized") is not False:
        raise RI6ContractError("Internal review cannot authorize a scientific claim")
    if payload.get("status") != "completed_internal_review_no_eligible_prospective_candidate":
        raise RI6ContractError("RI-6 internal review did not report the source rejection")
    if payload.get("source_decision") != "source_rejected_active_site_occupancy":
        raise RI6ContractError("RI-6 source rejection reason is invalid")
    candidate_reviews = payload.get("candidate_reviews", [])
    if not candidate_reviews or any(
        record.get("decision") != "rejected_source_active_site_occupancy"
        for record in candidate_reviews
    ):
        raise RI6ContractError("RI-6 candidates were not quarantined after source rejection")


def review_run(output_root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    run = _read_json(output_root / "ri6-prospective-static-run-v1.json")
    source_path = output_root / "source" / "5UL8.cif"
    core_atoms = _core_atoms(source_path)
    if not core_atoms:
        raise RI6ContractError("KPC-2 catalytic core atoms are unavailable")
    components = _source_components(source_path, core_atoms)
    source_rejected = any(
        component["decision"] == "source_rejected_active_site_occupancy"
        for component in components
    )
    reviews = [
        _review_candidate(
            rank=int(candidate["rank"]),
            pocket_id=str(candidate["pocket"]["pocket_id"]),
            volume=float(candidate["pocket"]["volume"]),
            residues=tuple(str(value) for value in candidate["pocket"].get("residues", [])),
            minimum_core_distance_angstrom=_minimum_center_distance(
                candidate["pocket"]["center"], core_atoms
            ),
            source_eligible=not source_rejected,
        )
        for candidate in run.get("candidates", [])
    ]
    payload: dict[str, Any] = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "status": "completed_internal_review_no_eligible_prospective_candidate",
        "review_authority": "user_authorized_internal_review",
        "review_scope": "source component occupancy and top-10 candidate catalytic adjacency",
        "source_id": "5UL8",
        "source_run_sha256": run.get("run_sha256"),
        "catalytic_core_residue_ids": sorted(CORE_RESIDUE_IDS),
        "core_proximity_threshold_angstrom": CORE_PROXIMITY_ANGSTROM,
        "source_components": components,
        "source_decision": (
            "source_rejected_active_site_occupancy" if source_rejected else "source_not_rejected"
        ),
        "candidate_reviews": reviews,
        "candidate_decision_counts": dict(Counter(record["decision"] for record in reviews)),
        "scientific_interpretation_authorized": False,
        "external_review_recommended": True,
        "claim_boundary": "no_discovery_prediction_or_drug_utility_claim",
        "limitations": [
            "This is a user-authorized internal review, not an independent external review.",
            "The active-site-proximal sulfate makes 5UL8 unsuitable for this prospective source contract.",
            "No replacement source was selected after observing this review result.",
        ],
    }
    payload["review_sha256"] = _stable_hash(payload)
    _validate_review(payload)
    destination = output_root / "ri6-internal-review-v1.json"
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    review = review_run(args.output_root.resolve())
    print(f"status={review['status']}")
    print(f"source_decision={review['source_decision']}")
    print(f"review_sha256={review['review_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

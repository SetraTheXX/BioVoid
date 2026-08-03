"""Pure metadata adapter for CryptoBench target-site records.

This module does not download structures or expose holo data to a detector.
It only normalizes evaluator metadata supplied by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Iterable, Mapping, Sequence

from .benchmark_v1 import BenchmarkContractError, SplitName


CRYPTOBENCH_SITE_OVERLAP_THRESHOLD = 0.75


def family_component_ids(uniprot_ids: Iterable[str]) -> tuple[str, ...]:
    """Return the connected UniProt components represented by a structure.

    CryptoBench encodes multi-chain sequence groups as hyphen-separated
    identifiers. Its fold-construction code splits those identifiers before
    clustering and keeps all components of one apo structure together.
    """

    components: set[str] = set()
    for raw_id in uniprot_ids:
        text = str(raw_id).strip().upper()
        components.update(part.strip() for part in text.split("-") if part.strip())
    if not components:
        raise BenchmarkContractError("At least one UniProt component is required")
    return tuple(sorted(components))


def family_group_id(uniprot_ids: Iterable[str]) -> str:
    """Return a stable structure-level family/complex group identifier."""

    return "+".join(family_component_ids(uniprot_ids))


@dataclass(frozen=True)
class CryptoBenchObservation:
    uniprot_id: str
    apo_pdb_id: str
    apo_chain: str
    holo_pdb_id: str
    holo_chain: str
    ligand_id: str
    ligand_index: str
    ligand_chain: str
    apo_pocket_residues: tuple[str, ...]
    holo_pocket_residues: tuple[str, ...]
    pocket_rmsd_angstrom: float
    is_main_holo_structure: bool


@dataclass(frozen=True)
class CryptoBenchTargetSite:
    case_id: str
    dataset_id: str
    split: SplitName
    apo_pdb_id: str
    family_id: str
    required_apo_chains: tuple[str, ...]
    apo_pocket_residues: tuple[str, ...]
    representative: CryptoBenchObservation
    observation_count: int


def _required_text(record: Mapping[str, Any], key: str) -> str:
    value = str(record.get(key, "")).strip()
    if not value:
        raise BenchmarkContractError(f"CryptoBench field '{key}' is required")
    return value


def _residues(record: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = record.get(key)
    if not isinstance(value, (list, tuple)) or not value:
        raise BenchmarkContractError(f"CryptoBench field '{key}' must be a non-empty residue list")
    residues = tuple(sorted({str(item).strip() for item in value if str(item).strip()}))
    if not residues or any("_" not in residue for residue in residues):
        raise BenchmarkContractError(f"CryptoBench field '{key}' has invalid residues")
    return residues


def _observation(apo_pdb_id: str, record: Mapping[str, Any]) -> CryptoBenchObservation:
    try:
        pocket_rmsd = float(record["pRMSD"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BenchmarkContractError("CryptoBench pRMSD must be numeric") from exc
    if not math.isfinite(pocket_rmsd) or pocket_rmsd <= 0:
        raise BenchmarkContractError("CryptoBench pRMSD must be finite and positive")
    return CryptoBenchObservation(
        uniprot_id=_required_text(record, "uniprot_id").upper(),
        apo_pdb_id=apo_pdb_id.upper(),
        apo_chain=_required_text(record, "apo_chain"),
        holo_pdb_id=_required_text(record, "holo_pdb_id").upper(),
        holo_chain=_required_text(record, "holo_chain"),
        ligand_id=_required_text(record, "ligand").upper(),
        ligand_index=_required_text(record, "ligand_index"),
        ligand_chain=_required_text(record, "ligand_chain"),
        apo_pocket_residues=_residues(record, "apo_pocket_selection"),
        holo_pocket_residues=_residues(record, "holo_pocket_selection"),
        pocket_rmsd_angstrom=pocket_rmsd,
        is_main_holo_structure=bool(record.get("is_main_holo_structure", False)),
    )


def _overlaps_as_same_site(left: set[str], right: set[str]) -> bool:
    intersection = len(left & right)
    return (
        intersection / len(left) > CRYPTOBENCH_SITE_OVERLAP_THRESHOLD
        or intersection / len(right) > CRYPTOBENCH_SITE_OVERLAP_THRESHOLD
    )


def _merge_sites(
    observations: Sequence[CryptoBenchObservation],
) -> list[tuple[set[str], list[CryptoBenchObservation]]]:
    clusters = [
        (set(observation.apo_pocket_residues), [observation]) for observation in observations
    ]
    changed = True
    while changed:
        changed = False
        left_index = 0
        while left_index < len(clusters):
            right_index = left_index + 1
            while right_index < len(clusters):
                left_residues, left_observations = clusters[left_index]
                right_residues, right_observations = clusters[right_index]
                if _overlaps_as_same_site(left_residues, right_residues):
                    clusters[left_index] = (
                        left_residues | right_residues,
                        left_observations + right_observations,
                    )
                    del clusters[right_index]
                    changed = True
                    continue
                right_index += 1
            left_index += 1
    return clusters


def _stable_case_id(
    dataset_id: str,
    apo_pdb_id: str,
    residues: tuple[str, ...],
) -> str:
    payload = json.dumps(
        {
            "dataset_id": dataset_id,
            "apo_pdb_id": apo_pdb_id,
            "apo_pocket_residues": residues,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    suffix = hashlib.sha256(payload).hexdigest()[:12]
    return f"{dataset_id}:{apo_pdb_id}:{suffix}"


def build_target_sites(
    dataset: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    dataset_id: str,
    split: SplitName,
) -> tuple[CryptoBenchTargetSite, ...]:
    """Normalize CryptoBench pairs into unique, reproducible target sites."""
    if not dataset_id.strip():
        raise BenchmarkContractError("dataset_id is required")
    if split not in {"development", "validation", "sealed"}:
        raise BenchmarkContractError("Unsupported benchmark split")

    sites: list[CryptoBenchTargetSite] = []
    for raw_apo_pdb_id, records in sorted(dataset.items()):
        apo_pdb_id = str(raw_apo_pdb_id).strip().upper()
        if not apo_pdb_id or not records:
            raise BenchmarkContractError("Each CryptoBench apo structure needs observations")
        observations = tuple(_observation(apo_pdb_id, record) for record in records)
        structure_family_id = family_group_id(
            observation.uniprot_id for observation in observations
        )

        for residue_set, members in _merge_sites(observations):
            residues = tuple(sorted(residue_set))
            representative = max(
                members,
                key=lambda item: (
                    item.pocket_rmsd_angstrom,
                    item.holo_pdb_id,
                    item.holo_chain,
                    item.ligand_id,
                    item.ligand_index,
                ),
            )
            required_chains = {member.apo_chain for member in members} | {
                residue.split("_", 1)[0] for residue in residues
            }
            sites.append(
                CryptoBenchTargetSite(
                    case_id=_stable_case_id(dataset_id, apo_pdb_id, residues),
                    dataset_id=dataset_id,
                    split=split,
                    apo_pdb_id=apo_pdb_id,
                    family_id=structure_family_id,
                    required_apo_chains=tuple(sorted(required_chains)),
                    apo_pocket_residues=residues,
                    representative=representative,
                    observation_count=len(members),
                )
            )

    return tuple(sorted(sites, key=lambda site: site.case_id))

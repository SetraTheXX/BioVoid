"""Evaluator-only rigid alignment for holo ligand ground truth.

The fitted transform is derived exclusively from matched protein C-alpha atoms.
Ligand coordinates are transformed only after the protein fit is fixed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from itertools import islice, product
import json
import math
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from Bio.Align import PairwiseAligner
import numpy as np

from .benchmark_v1 import EvaluatorGroundTruth
from .structure_preparation import (
    MODIFIED_AMINO_ACIDS,
    PROTEIN_RESIDUES,
    load_structure_atoms,
)


AlignmentStatus = Literal["ACCEPTED", "ACCEPTED_WITH_WARNINGS"]
AmbiguousSequencePolicy = Literal["reject", "structural_fit"]

_THREE_TO_ONE = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
    "CSO": "C",
    "HYP": "P",
    "MSE": "M",
    "PTR": "Y",
    "SEP": "S",
    "TPO": "T",
}


class GroundTruthAlignmentError(ValueError):
    """Raised when evaluator ground truth cannot be aligned reproducibly."""


def _coordinate(value: Sequence[float], field_name: str) -> tuple[float, float, float]:
    if len(value) != 3:
        raise GroundTruthAlignmentError(f"{field_name} must contain three coordinates")
    coordinate = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in coordinate):
        raise GroundTruthAlignmentError(f"{field_name} must contain finite coordinates")
    return coordinate


def _sha256(value: str, field_name: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise GroundTruthAlignmentError(f"{field_name} must be a lowercase SHA-256")
    return normalized


def _stable_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class AlignmentPolicy:
    minimum_matched_residues: int = 50
    minimum_sequence_identity: float = 0.9
    warning_rmsd_angstrom: float = 3.0
    maximum_rmsd_angstrom: float = 8.0
    policy_version: str = "ground-truth-alignment-v1"
    ambiguous_sequence_policy: AmbiguousSequencePolicy = "reject"
    maximum_alignment_candidates: int = 128
    maximum_alignment_combinations: int = 512
    structural_tie_rmsd_tolerance_angstrom: float = 0.001

    def __post_init__(self) -> None:
        if self.minimum_matched_residues < 3:
            raise GroundTruthAlignmentError("At least three matched residues are required")
        if not 0 <= self.minimum_sequence_identity <= 1:
            raise GroundTruthAlignmentError("minimum_sequence_identity must be in [0, 1]")
        if self.warning_rmsd_angstrom <= 0:
            raise GroundTruthAlignmentError("warning_rmsd_angstrom must be positive")
        if self.maximum_rmsd_angstrom < self.warning_rmsd_angstrom:
            raise GroundTruthAlignmentError(
                "maximum_rmsd_angstrom must cover the warning threshold"
            )
        if self.ambiguous_sequence_policy not in {"reject", "structural_fit"}:
            raise GroundTruthAlignmentError(
                "ambiguous_sequence_policy must be 'reject' or 'structural_fit'"
            )
        if self.maximum_alignment_candidates < 2:
            raise GroundTruthAlignmentError("At least two alignment candidates must be allowed")
        if self.maximum_alignment_combinations < 2:
            raise GroundTruthAlignmentError("At least two alignment combinations must be allowed")
        if self.structural_tie_rmsd_tolerance_angstrom < 0:
            raise GroundTruthAlignmentError(
                "structural_tie_rmsd_tolerance_angstrom cannot be negative"
            )


@dataclass(frozen=True)
class ChainPair:
    apo_chain_id: str
    holo_chain_id: str

    def __post_init__(self) -> None:
        if not self.apo_chain_id.strip() or not self.holo_chain_id.strip():
            raise GroundTruthAlignmentError("Chain IDs cannot be empty")


@dataclass(frozen=True)
class ProteinAlignmentAtom:
    chain_id: str
    residue_id: int
    insertion_code: str
    residue_name: str
    atom_name: str
    coordinate: tuple[float, float, float]

    def __post_init__(self) -> None:
        if not self.chain_id.strip() or not self.residue_name.strip():
            raise GroundTruthAlignmentError("Protein atom identity is incomplete")
        object.__setattr__(self, "coordinate", _coordinate(self.coordinate, "protein atom"))


@dataclass(frozen=True)
class LigandAtom:
    atom_name: str
    element: str
    coordinate: tuple[float, float, float]

    def __post_init__(self) -> None:
        if not self.atom_name.strip() or not self.element.strip():
            raise GroundTruthAlignmentError("Ligand atom identity is incomplete")
        object.__setattr__(self, "coordinate", _coordinate(self.coordinate, "ligand atom"))


@dataclass(frozen=True)
class LigandSelector:
    residue_name: str
    chain_id: str
    residue_id: int
    insertion_code: str = ""

    def __post_init__(self) -> None:
        if not self.residue_name.strip() or not self.chain_id.strip():
            raise GroundTruthAlignmentError("Ligand residue name and chain are required")


@dataclass(frozen=True)
class GroundTruthAlignmentResult:
    status: AlignmentStatus
    ground_truth: EvaluatorGroundTruth
    rotation: tuple[tuple[float, float, float], ...]
    translation: tuple[float, float, float]
    matched_residue_count: int
    sequence_identity: float
    fit_rmsd_angstrom: float
    alignment_sha256: str
    ground_truth_sha256: str
    prepared_structure_sha256: str
    holo_structure_sha256: str
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _ResiduePoint:
    identity: tuple[str, int, str]
    residue_name: str
    coordinate: tuple[float, float, float]


@dataclass(frozen=True)
class _ChainMatch:
    apo_residues: tuple[_ResiduePoint, ...]
    holo_residues: tuple[_ResiduePoint, ...]
    identical_residue_count: int


def _chain_residues(
    atoms: Sequence[ProteinAlignmentAtom],
    chain_id: str,
) -> tuple[_ResiduePoint, ...]:
    residues: dict[tuple[str, int, str], _ResiduePoint] = {}
    for atom in atoms:
        if atom.chain_id != chain_id or atom.atom_name.strip().upper() != "CA":
            continue
        key = (atom.chain_id, int(atom.residue_id), atom.insertion_code.strip())
        if key in residues:
            raise GroundTruthAlignmentError(f"Ambiguous duplicate C-alpha atom for residue {key}")
        residues[key] = _ResiduePoint(
            identity=key,
            residue_name=atom.residue_name.strip().upper(),
            coordinate=atom.coordinate,
        )
    if not residues:
        raise GroundTruthAlignmentError(f"Chain '{chain_id}' has no C-alpha atoms")
    return tuple(residues[key] for key in sorted(residues, key=lambda item: (item[1], item[2])))


def _sequence(residues: Sequence[_ResiduePoint]) -> str:
    return "".join(_THREE_TO_ONE.get(residue.residue_name, "X") for residue in residues)


def _alignment_match(
    alignment: Any,
    apo_residues: Sequence[_ResiduePoint],
    holo_residues: Sequence[_ResiduePoint],
) -> _ChainMatch:
    matched_apo: list[_ResiduePoint] = []
    matched_holo: list[_ResiduePoint] = []
    identical = 0
    for apo_block, holo_block in zip(
        alignment.aligned[0],
        alignment.aligned[1],
        strict=True,
    ):
        apo_start, apo_end = (int(value) for value in apo_block)
        holo_start, holo_end = (int(value) for value in holo_block)
        if apo_end - apo_start != holo_end - holo_start:
            raise GroundTruthAlignmentError("Sequence alignment produced unequal blocks")
        for apo_index, holo_index in zip(
            range(apo_start, apo_end),
            range(holo_start, holo_end),
            strict=True,
        ):
            apo_residue = apo_residues[apo_index]
            holo_residue = holo_residues[holo_index]
            matched_apo.append(apo_residue)
            matched_holo.append(holo_residue)
            apo_code = _THREE_TO_ONE.get(apo_residue.residue_name, "X")
            holo_code = _THREE_TO_ONE.get(holo_residue.residue_name, "X")
            identical += apo_code != "X" and apo_code == holo_code
    return _ChainMatch(
        apo_residues=tuple(matched_apo),
        holo_residues=tuple(matched_holo),
        identical_residue_count=identical,
    )


def _chain_match_candidates(
    apo_residues: Sequence[_ResiduePoint],
    holo_residues: Sequence[_ResiduePoint],
    policy: AlignmentPolicy,
) -> tuple[_ChainMatch, ...]:
    aligner = PairwiseAligner()
    aligner.mode = "global"
    aligner.match_score = 2.0
    aligner.mismatch_score = -1.0
    aligner.open_gap_score = -5.0
    aligner.extend_gap_score = -0.5
    alignments = aligner.align(_sequence(apo_residues), _sequence(holo_residues))
    candidates = tuple(
        _alignment_match(alignment, apo_residues, holo_residues)
        for alignment in islice(alignments, policy.maximum_alignment_candidates + 1)
    )
    if not candidates:
        raise GroundTruthAlignmentError("Sequence alignment produced no mappings")
    if len(candidates) > policy.maximum_alignment_candidates:
        raise GroundTruthAlignmentError(
            "Sequence alignment candidate count exceeds the recovery safety limit "
            f"({policy.maximum_alignment_candidates})"
        )
    if len(candidates) > 1 and policy.ambiguous_sequence_policy == "reject":
        raise GroundTruthAlignmentError("Ambiguous sequence alignment has multiple mappings")
    return candidates


def _match_chain(
    apo_residues: Sequence[_ResiduePoint],
    holo_residues: Sequence[_ResiduePoint],
    policy: AlignmentPolicy = AlignmentPolicy(),
) -> tuple[list[_ResiduePoint], list[_ResiduePoint], int]:
    candidates = _chain_match_candidates(apo_residues, holo_residues, policy)
    if len(candidates) != 1:
        raise GroundTruthAlignmentError("Ambiguous sequence alignment has multiple mappings")
    match = candidates[0]
    return (
        list(match.apo_residues),
        list(match.holo_residues),
        match.identical_residue_count,
    )


def _fit_holo_to_apo(
    holo_coordinates: np.ndarray,
    apo_coordinates: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, float]:
    holo_center = holo_coordinates.mean(axis=0)
    apo_center = apo_coordinates.mean(axis=0)
    centered_holo = holo_coordinates - holo_center
    centered_apo = apo_coordinates - apo_center
    if np.linalg.matrix_rank(centered_holo) < 2:
        raise GroundTruthAlignmentError("Matched C-alpha geometry is degenerate")
    covariance = centered_holo.T @ centered_apo
    left, _singular_values, right_transpose = np.linalg.svd(covariance)
    rotation = left @ right_transpose
    if np.linalg.det(rotation) < 0:
        left[:, -1] *= -1
        rotation = left @ right_transpose
    translation = apo_center - holo_center @ rotation
    fitted = holo_coordinates @ rotation + translation
    rmsd = float(np.sqrt(np.mean(np.sum((fitted - apo_coordinates) ** 2, axis=1))))
    return rotation, translation, rmsd


def build_aligned_ground_truth(
    *,
    case_id: str,
    structure_id: str,
    apo_atoms: Sequence[ProteinAlignmentAtom],
    holo_atoms: Sequence[ProteinAlignmentAtom],
    ligand_atoms: Sequence[LigandAtom],
    chain_pairs: Sequence[ChainPair],
    prepared_structure_sha256: str,
    holo_structure_sha256: str,
    provenance_label: str,
    policy: AlignmentPolicy = AlignmentPolicy(),
    ligand_residues: Sequence[str] = (),
    ligand_identity: Mapping[str, Any] | None = None,
) -> GroundTruthAlignmentResult:
    """Build ligand ground truth in the prepared apo coordinate frame."""
    if not case_id.strip() or not structure_id.strip() or not provenance_label.strip():
        raise GroundTruthAlignmentError("case_id, structure_id, and provenance_label are required")
    prepared_hash = _sha256(prepared_structure_sha256, "prepared_structure_sha256")
    holo_hash = _sha256(holo_structure_sha256, "holo_structure_sha256")
    if not chain_pairs:
        raise GroundTruthAlignmentError("At least one apo/holo chain pair is required")
    if len({pair.apo_chain_id for pair in chain_pairs}) != len(chain_pairs):
        raise GroundTruthAlignmentError("An apo chain cannot be aligned more than once")
    if len({pair.holo_chain_id for pair in chain_pairs}) != len(chain_pairs):
        raise GroundTruthAlignmentError("A holo chain cannot be aligned more than once")

    warnings: list[str] = []
    chain_candidate_sets: list[tuple[_ChainMatch, ...]] = []
    for pair in chain_pairs:
        apo_chain = _chain_residues(apo_atoms, pair.apo_chain_id)
        holo_chain = _chain_residues(holo_atoms, pair.holo_chain_id)
        chain_candidate_sets.append(_chain_match_candidates(apo_chain, holo_chain, policy))

    if all(len(candidates) == 1 for candidates in chain_candidate_sets):
        selected_chain_matches = tuple(candidates[0] for candidates in chain_candidate_sets)
    elif policy.ambiguous_sequence_policy != "structural_fit":
        raise GroundTruthAlignmentError("Ambiguous sequence alignment has multiple mappings")
    else:
        combination_count = math.prod(len(candidates) for candidates in chain_candidate_sets)
        if combination_count > policy.maximum_alignment_combinations:
            raise GroundTruthAlignmentError(
                "Sequence alignment combination count exceeds the recovery safety limit "
                f"({policy.maximum_alignment_combinations})"
            )

        scored_combinations: list[tuple[float, int, int, tuple[_ChainMatch, ...]]] = []
        for combination in product(*chain_candidate_sets):
            candidate_apo = tuple(
                residue for chain in combination for residue in chain.apo_residues
            )
            candidate_holo = tuple(
                residue for chain in combination for residue in chain.holo_residues
            )
            candidate_count = len(candidate_apo)
            candidate_identical = sum(chain.identical_residue_count for chain in combination)
            if candidate_count < policy.minimum_matched_residues:
                continue
            if candidate_identical / candidate_count < policy.minimum_sequence_identity:
                continue
            try:
                _, _, candidate_rmsd = _fit_holo_to_apo(
                    np.asarray([residue.coordinate for residue in candidate_holo]),
                    np.asarray([residue.coordinate for residue in candidate_apo]),
                )
            except GroundTruthAlignmentError:
                continue
            scored_combinations.append(
                (
                    candidate_rmsd,
                    -candidate_count,
                    -candidate_identical,
                    tuple(combination),
                )
            )

        if not scored_combinations:
            raise GroundTruthAlignmentError(
                "No structurally valid sequence alignment candidate met the recovery policy"
            )
        scored_combinations.sort(key=lambda item: item[:3])
        best = scored_combinations[0]
        if (
            len(scored_combinations) > 1
            and scored_combinations[1][0] - best[0] <= policy.structural_tie_rmsd_tolerance_angstrom
        ):
            raise GroundTruthAlignmentError(
                "Structural sequence alignment tie remains within the recovery tolerance"
            )
        selected_chain_matches = best[3]
        warnings.append("ambiguous_sequence_alignment_resolved_by_structural_fit")

    matched_apo = [residue for chain in selected_chain_matches for residue in chain.apo_residues]
    matched_holo = [residue for chain in selected_chain_matches for residue in chain.holo_residues]
    identical = sum(chain.identical_residue_count for chain in selected_chain_matches)

    matched_count = len(matched_apo)
    if matched_count < policy.minimum_matched_residues:
        raise GroundTruthAlignmentError(
            f"Only {matched_count} residues aligned; minimum is {policy.minimum_matched_residues}"
        )
    sequence_identity = identical / matched_count
    if sequence_identity < policy.minimum_sequence_identity:
        raise GroundTruthAlignmentError(
            f"Sequence identity {sequence_identity:.3f} is below "
            f"{policy.minimum_sequence_identity:.3f}"
        )

    apo_coordinates = np.asarray([residue.coordinate for residue in matched_apo])
    holo_coordinates = np.asarray([residue.coordinate for residue in matched_holo])
    rotation, translation, fit_rmsd = _fit_holo_to_apo(
        holo_coordinates,
        apo_coordinates,
    )
    if fit_rmsd > policy.maximum_rmsd_angstrom:
        raise GroundTruthAlignmentError(
            f"Protein alignment RMSD {fit_rmsd:.3f} A exceeds {policy.maximum_rmsd_angstrom:.3f} A"
        )

    heavy_ligand_atoms = [
        atom for atom in ligand_atoms if atom.element.strip().upper() not in {"H", "D"}
    ]
    if not heavy_ligand_atoms:
        raise GroundTruthAlignmentError("Ligand has no heavy atoms")
    ligand_coordinates = np.asarray([atom.coordinate for atom in heavy_ligand_atoms])
    transformed_ligand = ligand_coordinates @ rotation + translation
    ligand_center = transformed_ligand.mean(axis=0)

    status: AlignmentStatus = "ACCEPTED"
    if fit_rmsd > policy.warning_rmsd_angstrom:
        status = "ACCEPTED_WITH_WARNINGS"
        warnings.append("protein_alignment_rmsd_above_warning_threshold")
    removed_hydrogens = len(ligand_atoms) - len(heavy_ligand_atoms)
    if removed_hydrogens:
        warnings.append("ligand_hydrogens_excluded")

    rotation_tuple = tuple(tuple(round(float(value), 12) for value in row) for row in rotation)
    translation_tuple = tuple(round(float(value), 12) for value in translation)
    alignment_payload = {
        "policy": asdict(policy),
        "prepared_structure_sha256": prepared_hash,
        "holo_structure_sha256": holo_hash,
        "chain_pairs": [asdict(pair) for pair in chain_pairs],
        "matched_residues": [
            {
                "apo": apo.identity,
                "holo": holo.identity,
                "apo_residue_name": apo.residue_name,
                "holo_residue_name": holo.residue_name,
            }
            for apo, holo in zip(matched_apo, matched_holo, strict=True)
        ],
        "rotation": rotation_tuple,
        "translation": translation_tuple,
    }
    alignment_sha256 = _stable_hash(alignment_payload)
    transformed_ligand_tuple = tuple(
        tuple(float(value) for value in coordinate) for coordinate in transformed_ligand
    )
    normalized_ligand_identity = dict(ligand_identity or {"source": "caller_supplied"})
    ground_truth_sha256 = _stable_hash(
        {
            "alignment_sha256": alignment_sha256,
            "ligand_identity": normalized_ligand_identity,
            "ligand_atoms": transformed_ligand_tuple,
            "ligand_residues": tuple(str(residue) for residue in ligand_residues),
        }
    )
    provenance = {
        "schema_version": policy.policy_version,
        "label": provenance_label,
        "status": status,
        "prepared_structure_sha256": prepared_hash,
        "holo_structure_sha256": holo_hash,
        "alignment_sha256": alignment_sha256,
        "ground_truth_sha256": ground_truth_sha256,
        "ligand_identity": normalized_ligand_identity,
        "matched_residue_count": matched_count,
        "sequence_identity": round(sequence_identity, 8),
        "fit_rmsd_angstrom": round(fit_rmsd, 8),
        "ligand_heavy_atom_count": len(heavy_ligand_atoms),
        "ligand_hydrogens_excluded": removed_hydrogens,
        "warnings": warnings,
    }
    ground_truth = EvaluatorGroundTruth(
        case_id=case_id,
        structure_id=structure_id,
        coordinate_frame_sha256=prepared_hash,
        alignment_sha256=alignment_sha256,
        ligand_center=tuple(float(value) for value in ligand_center),
        ligand_atoms=transformed_ligand_tuple,
        ligand_residues=tuple(str(residue) for residue in ligand_residues),
        quality="exact",
        provenance=json.dumps(provenance, sort_keys=True, separators=(",", ":")),
    )
    return GroundTruthAlignmentResult(
        status=status,
        ground_truth=ground_truth,
        rotation=rotation_tuple,
        translation=translation_tuple,
        matched_residue_count=matched_count,
        sequence_identity=round(sequence_identity, 8),
        fit_rmsd_angstrom=round(fit_rmsd, 8),
        alignment_sha256=alignment_sha256,
        ground_truth_sha256=ground_truth_sha256,
        prepared_structure_sha256=prepared_hash,
        holo_structure_sha256=holo_hash,
        warnings=tuple(warnings),
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_aligned_ground_truth_from_files(
    *,
    case_id: str,
    structure_id: str,
    prepared_apo_path: str | Path,
    holo_path: str | Path,
    ligand: LigandSelector,
    chain_pairs: Sequence[ChainPair],
    provenance_label: str,
    policy: AlignmentPolicy = AlignmentPolicy(),
    ligand_residues: Sequence[str] = (),
    additional_ligands: Sequence[LigandSelector] = (),
) -> GroundTruthAlignmentResult:
    """Extract exact local-file identities and build evaluator ground truth."""
    prepared_path = Path(prepared_apo_path).resolve()
    resolved_holo_path = Path(holo_path).resolve()
    prepared_atoms = load_structure_atoms(prepared_path)
    holo_atoms = load_structure_atoms(resolved_holo_path)

    protein_names = PROTEIN_RESIDUES | MODIFIED_AMINO_ACIDS
    apo_alignment_atoms = tuple(
        ProteinAlignmentAtom(
            chain_id=atom.chain_id,
            residue_id=atom.res_id,
            insertion_code=atom.ins_code,
            residue_name=atom.res_name,
            atom_name=atom.atom_name,
            coordinate=(atom.x, atom.y, atom.z),
        )
        for atom in prepared_atoms
        if atom.res_name in protein_names
    )
    holo_alignment_atoms = tuple(
        ProteinAlignmentAtom(
            chain_id=atom.chain_id,
            residue_id=atom.res_id,
            insertion_code=atom.ins_code,
            residue_name=atom.res_name,
            atom_name=atom.atom_name,
            coordinate=(atom.x, atom.y, atom.z),
        )
        for atom in holo_atoms
        if atom.res_name in protein_names
    )

    ligands = (ligand, *tuple(additional_ligands))
    selected_identities = {
        (
            item.residue_name.strip().upper(),
            item.chain_id.strip(),
            int(item.residue_id),
            item.insertion_code.strip(),
        )
        for item in ligands
    }
    selected_ligand_atoms = tuple(
        LigandAtom(
            atom_name=atom.atom_name,
            element=atom.element,
            coordinate=(atom.x, atom.y, atom.z),
        )
        for atom in holo_atoms
        if (
            atom.res_name,
            atom.chain_id,
            int(atom.res_id),
            atom.ins_code.strip(),
        )
        in selected_identities
    )
    if not selected_ligand_atoms:
        raise GroundTruthAlignmentError(
            "Exact ligand selector matched no atoms in the holo structure"
        )

    return build_aligned_ground_truth(
        case_id=case_id,
        structure_id=structure_id,
        apo_atoms=apo_alignment_atoms,
        holo_atoms=holo_alignment_atoms,
        ligand_atoms=selected_ligand_atoms,
        chain_pairs=chain_pairs,
        prepared_structure_sha256=_file_sha256(prepared_path),
        holo_structure_sha256=_file_sha256(resolved_holo_path),
        provenance_label=provenance_label,
        policy=policy,
        ligand_residues=ligand_residues,
        ligand_identity=(
            asdict(ligand)
            if not additional_ligands
            else {"selectors": [asdict(item) for item in ligands]}
        ),
    )

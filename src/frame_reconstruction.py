"""Full-atom reconstruction and quality gates for experimental motion samples."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import biotite.structure.io.pdb as pdb
import numpy as np
from scipy.spatial import cKDTree


RECONSTRUCTION_VERSION = "frame-reconstruction-v1"
QUALITY_POLICY_VERSION = "frame-quality-v1"


class FrameStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    ACCEPTED_WITH_WARNINGS = "ACCEPTED_WITH_WARNINGS"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class FrameQualityPolicy:
    ca_target_max_error: float = 0.02
    bond_warning_deviation: float = 0.15
    bond_rejection_deviation: float = 0.35
    peptide_bond_max_length: float = 2.0
    clash_scale: float = 0.65
    clash_warning_count: int = 1
    clash_rejection_count: int = 5
    displacement_warning: float = 3.0
    displacement_rejection: float = 5.0
    version: str = QUALITY_POLICY_VERSION


@dataclass(frozen=True)
class ReconstructionStats:
    atoms_total: int
    residues_total: int
    residues_mapped: int
    mapping_coverage: float
    mean_ca_displacement: float
    max_ca_displacement: float

    @classmethod
    def synthetic(cls) -> "ReconstructionStats":
        return cls(0, 0, 0, 1.0, 0.0, 0.0)


@dataclass(frozen=True)
class FrameQualityReport:
    status: FrameStatus
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    atom_count_preserved: bool
    atom_identities_preserved: bool
    residue_mapping_complete: bool
    residue_leakage_detected: bool
    ca_target_rmsd: float
    ca_target_max_error: float
    bond_geometry_rms_deviation: float
    bond_geometry_max_deviation: float
    backbone_rmsd_from_reference: float
    chain_break_count: int
    clash_count: int
    introduced_clash_count: int
    clash_score: float
    maximum_atom_displacement: float
    reconstruction_method: str
    reconstruction_version: str
    minimization_applied: bool
    quality_policy_version: str

    @classmethod
    def synthetic(
        cls,
        *,
        status: FrameStatus = FrameStatus.ACCEPTED,
        reconstruction_method: str = "synthetic",
    ) -> "FrameQualityReport":
        return cls(
            status=status,
            reasons=(),
            warnings=(),
            atom_count_preserved=True,
            atom_identities_preserved=True,
            residue_mapping_complete=True,
            residue_leakage_detected=False,
            ca_target_rmsd=0.0,
            ca_target_max_error=0.0,
            bond_geometry_rms_deviation=0.0,
            bond_geometry_max_deviation=0.0,
            backbone_rmsd_from_reference=0.0,
            chain_break_count=0,
            clash_count=0,
            introduced_clash_count=0,
            clash_score=0.0,
            maximum_atom_displacement=0.0,
            reconstruction_method=reconstruction_method,
            reconstruction_version=RECONSTRUCTION_VERSION,
            minimization_applied=False,
            quality_policy_version=QUALITY_POLICY_VERSION,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["reasons"] = list(self.reasons)
        payload["warnings"] = list(self.warnings)
        return payload


@dataclass(frozen=True)
class ReconstructionResult:
    stats: ReconstructionStats
    quality: FrameQualityReport
    output_path: Path | None


def _load_first_model(pdb_file: str | Path):
    path = Path(pdb_file)
    if not path.exists():
        raise FileNotFoundError(f"PDB file not found: {path}")
    return pdb.PDBFile.read(str(path)).get_structure()[0]


def _residue_key(structure, atom_index: int) -> tuple[str, int, str, str]:
    insertion = (
        str(structure.ins_code[atom_index]).strip() if hasattr(structure, "ins_code") else ""
    )
    return (
        str(structure.chain_id[atom_index]),
        int(structure.res_id[atom_index]),
        insertion,
        str(structure.res_name[atom_index]),
    )


def _atom_identities(structure) -> tuple[tuple[Any, ...], ...]:
    identities: list[tuple[Any, ...]] = []
    for index in range(len(structure)):
        identities.append(
            (
                *_residue_key(structure, index),
                str(structure.atom_name[index]),
                str(structure.element[index]),
                bool(structure.hetero[index]),
            )
        )
    return tuple(identities)


def _extract_ca_entries(structure) -> list[tuple[tuple[str, int, str, str], int, np.ndarray]]:
    entries = []
    for index in np.where(structure.atom_name == "CA")[0]:
        entries.append(
            (
                _residue_key(structure, int(index)),
                int(index),
                np.asarray(structure.coord[int(index)], dtype=float),
            )
        )
    return entries


def _bond_pairs(structure) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    atom_lookup: dict[tuple[tuple[str, int, str, str], str], int] = {}
    residue_order: list[tuple[str, int, str, str]] = []
    for index in range(len(structure)):
        key = _residue_key(structure, index)
        if key not in residue_order:
            residue_order.append(key)
        atom_lookup[(key, str(structure.atom_name[index]))] = index

    for key in residue_order:
        for first, second in (("N", "CA"), ("CA", "C"), ("C", "O")):
            if (key, first) in atom_lookup and (key, second) in atom_lookup:
                pairs.append((atom_lookup[(key, first)], atom_lookup[(key, second)]))
    for left, right in zip(residue_order, residue_order[1:]):
        if left[0] != right[0]:
            continue
        pair = (atom_lookup.get((left, "C")), atom_lookup.get((right, "N")))
        if pair[0] is not None and pair[1] is not None:
            reference_distance = float(
                np.linalg.norm(structure.coord[pair[0]] - structure.coord[pair[1]])
            )
            if reference_distance <= 2.0:
                pairs.append((int(pair[0]), int(pair[1])))
    return pairs


_VDW_RADII = {
    "H": 1.20,
    "C": 1.70,
    "N": 1.55,
    "O": 1.52,
    "P": 1.80,
    "S": 1.80,
    "SE": 1.90,
}


def _clash_pairs(structure, *, scale: float) -> set[tuple[int, int]]:
    coordinates = np.asarray(structure.coord, dtype=float)
    residue_keys = [_residue_key(structure, index) for index in range(len(structure))]
    bonded = {tuple(sorted(pair)) for pair in _bond_pairs(structure)}
    maximum_radius = max(_VDW_RADII.values())
    candidates = cKDTree(coordinates).query_pairs(2.0 * maximum_radius * scale)
    clashes: set[tuple[int, int]] = set()
    for left, right in candidates:
        pair = (int(left), int(right))
        if pair in bonded:
            continue
        left_key, right_key = residue_keys[left], residue_keys[right]
        if left_key[0] == right_key[0] and abs(left_key[1] - right_key[1]) <= 1:
            continue
        left_radius = _VDW_RADII.get(str(structure.element[left]).upper(), 1.70)
        right_radius = _VDW_RADII.get(str(structure.element[right]).upper(), 1.70)
        threshold = scale * (left_radius + right_radius)
        if np.linalg.norm(coordinates[left] - coordinates[right]) < threshold:
            clashes.add(pair)
    return clashes


def reconstruct_and_validate_frame(
    template_pdb: str | Path,
    target_ca_coordinates: np.ndarray,
    *,
    output_pdb: str | Path,
    sample_metadata: dict[str, Any] | None = None,
    reconstruction_method: str = "residue_rigid_translation_v1",
    policy: FrameQualityPolicy | None = None,
) -> ReconstructionResult:
    """Translate each residue with its CA target, then apply strict frame QC."""
    del sample_metadata
    supported_methods = {
        "residue_rigid_translation_v1",
        "backbone_blended_translation_v1",
    }
    if reconstruction_method not in supported_methods:
        raise ValueError(f"Unsupported reconstruction method: {reconstruction_method}")
    quality_policy = policy or FrameQualityPolicy()
    template = _load_first_model(template_pdb)
    ca_entries = _extract_ca_entries(template)
    targets = np.asarray(target_ca_coordinates, dtype=float)
    if targets.shape != (len(ca_entries), 3):
        raise ValueError(
            f"Expected CA target shape {(len(ca_entries), 3)}, received {targets.shape}"
        )
    if not np.all(np.isfinite(targets)):
        raise ValueError("CA targets must be finite")

    reconstructed = template.copy()
    displacement_map: dict[tuple[str, int, str, str], np.ndarray] = {}
    displacement_norms: list[float] = []
    for (key, _index, reference), target in zip(ca_entries, targets):
        displacement = target - reference
        displacement_map[key] = displacement
        displacement_norms.append(float(np.linalg.norm(displacement)))
    residue_order = [entry[0] for entry in ca_entries]
    residue_position = {key: index for index, key in enumerate(residue_order)}
    for index in range(len(reconstructed)):
        key = _residue_key(reconstructed, index)
        if key not in displacement_map:
            continue
        displacement = displacement_map[key]
        if reconstruction_method == "backbone_blended_translation_v1":
            position = residue_position[key]
            atom_name = str(reconstructed.atom_name[index])
            if atom_name == "N" and position > 0 and residue_order[position - 1][0] == key[0]:
                displacement = 0.5 * (displacement_map[residue_order[position - 1]] + displacement)
            elif (
                atom_name in {"C", "O"}
                and position + 1 < len(residue_order)
                and residue_order[position + 1][0] == key[0]
            ):
                displacement = 0.5 * (displacement + displacement_map[residue_order[position + 1]])
        reconstructed.coord[index] = reconstructed.coord[index] + displacement

    stats = ReconstructionStats(
        atoms_total=int(len(reconstructed)),
        residues_total=len(ca_entries),
        residues_mapped=len(displacement_map),
        mapping_coverage=round(len(displacement_map) / max(1, len(ca_entries)), 6),
        mean_ca_displacement=round(float(np.mean(displacement_norms)), 6),
        max_ca_displacement=round(float(np.max(displacement_norms)), 6),
    )
    atom_count_preserved = len(template) == len(reconstructed)
    atom_identities_preserved = _atom_identities(template) == _atom_identities(reconstructed)
    residue_mapping_complete = stats.mapping_coverage == 1.0
    reconstructed_ca = np.asarray(reconstructed.coord[reconstructed.atom_name == "CA"], dtype=float)
    ca_errors = np.linalg.norm(reconstructed_ca - targets, axis=1)

    bonds = _bond_pairs(template)
    bond_deviations = np.asarray(
        [
            abs(
                np.linalg.norm(reconstructed.coord[left] - reconstructed.coord[right])
                - np.linalg.norm(template.coord[left] - template.coord[right])
            )
            for left, right in bonds
        ],
        dtype=float,
    )
    chain_break_count = 0
    for left, right in bonds:
        if str(template.atom_name[left]) == "C" and str(template.atom_name[right]) == "N":
            if np.linalg.norm(reconstructed.coord[left] - reconstructed.coord[right]) > (
                quality_policy.peptide_bond_max_length
            ):
                chain_break_count += 1

    reference_clashes = _clash_pairs(template, scale=quality_policy.clash_scale)
    reconstructed_clashes = _clash_pairs(reconstructed, scale=quality_policy.clash_scale)
    introduced_clashes = reconstructed_clashes - reference_clashes
    maximum_displacement = float(
        np.max(np.linalg.norm(reconstructed.coord - template.coord, axis=1))
    )
    backbone_mask = np.isin(reconstructed.atom_name, ("N", "CA", "C", "O"))
    backbone_displacements = np.linalg.norm(
        reconstructed.coord[backbone_mask] - template.coord[backbone_mask],
        axis=1,
    )
    backbone_rmsd = (
        float(np.sqrt(np.mean(backbone_displacements**2))) if len(backbone_displacements) else 0.0
    )

    ca_rmsd = float(np.sqrt(np.mean(ca_errors**2))) if len(ca_errors) else float("inf")
    ca_max = float(np.max(ca_errors)) if len(ca_errors) else float("inf")
    bond_rms = float(np.sqrt(np.mean(bond_deviations**2))) if len(bond_deviations) else 0.0
    bond_max = float(np.max(bond_deviations)) if len(bond_deviations) else 0.0

    reasons: list[str] = []
    warnings: list[str] = []
    if not atom_count_preserved:
        reasons.append("atom_count_changed")
    if not atom_identities_preserved:
        reasons.append("atom_identity_changed")
    if not residue_mapping_complete:
        reasons.append("incomplete_residue_mapping")
    if ca_max > quality_policy.ca_target_max_error:
        reasons.append("ca_target_mismatch")
    if bond_max > quality_policy.bond_rejection_deviation:
        reasons.append("bond_geometry_rejected")
    elif bond_max > quality_policy.bond_warning_deviation:
        warnings.append("bond_geometry_warning")
    if chain_break_count:
        reasons.append("chain_break_detected")
    if len(introduced_clashes) > quality_policy.clash_rejection_count:
        reasons.append("steric_clashes_rejected")
    elif len(introduced_clashes) >= quality_policy.clash_warning_count:
        warnings.append("steric_clash_warning")
    if maximum_displacement > quality_policy.displacement_rejection:
        reasons.append("maximum_displacement_rejected")
    elif maximum_displacement > quality_policy.displacement_warning:
        warnings.append("maximum_displacement_warning")

    status = (
        FrameStatus.REJECTED
        if reasons
        else FrameStatus.ACCEPTED_WITH_WARNINGS
        if warnings
        else FrameStatus.ACCEPTED
    )
    quality = FrameQualityReport(
        status=status,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
        atom_count_preserved=atom_count_preserved,
        atom_identities_preserved=atom_identities_preserved,
        residue_mapping_complete=residue_mapping_complete,
        residue_leakage_detected=not atom_identities_preserved,
        ca_target_rmsd=round(ca_rmsd, 8),
        ca_target_max_error=round(ca_max, 8),
        bond_geometry_rms_deviation=round(bond_rms, 8),
        bond_geometry_max_deviation=round(bond_max, 8),
        backbone_rmsd_from_reference=round(backbone_rmsd, 8),
        chain_break_count=chain_break_count,
        clash_count=len(reconstructed_clashes),
        introduced_clash_count=len(introduced_clashes),
        clash_score=round(float(len(introduced_clashes)) / max(1, len(template)), 8),
        maximum_atom_displacement=round(maximum_displacement, 8),
        reconstruction_method=reconstruction_method,
        reconstruction_version=RECONSTRUCTION_VERSION,
        minimization_applied=False,
        quality_policy_version=quality_policy.version,
    )

    persisted_path: Path | None = None
    output_path = Path(output_pdb)
    if status is FrameStatus.ACCEPTED:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output = pdb.PDBFile()
        output.set_structure(reconstructed)
        output.write(str(output_path))
        persisted_path = output_path
    elif output_path.exists():
        output_path.unlink()

    return ReconstructionResult(stats=stats, quality=quality, output_path=persisted_path)


def reconstruct_all_atom_frame_from_ca(
    template_pdb: str | Path,
    ca_frame_pdb: str | Path,
    output_pdb: str | Path,
) -> ReconstructionStats:
    """Compatibility wrapper around the validated reconstruction path."""
    ca_frame = _load_first_model(ca_frame_pdb)
    targets = np.asarray(ca_frame.coord[ca_frame.atom_name == "CA"], dtype=float)
    result = reconstruct_and_validate_frame(
        template_pdb,
        targets,
        output_pdb=output_pdb,
    )
    if result.quality.status is not FrameStatus.ACCEPTED:
        raise ValueError(
            "Reconstructed frame did not pass strict quality gates: "
            + ", ".join(result.quality.reasons or result.quality.warnings)
        )
    return result.stats


def stats_to_dict(stats: ReconstructionStats) -> dict[str, Any]:
    return asdict(stats)

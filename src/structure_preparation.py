"""Deterministic full-heavy-atom structure preparation and provenance."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import biotite.structure.io.pdbx as pdbx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src import __version__
from src.cache import environment_manifest

PREPARATION_POLICY_VERSION = "structure-preparation-v1"

WATER_NAMES = {"HOH", "WAT", "DOD"}
COFACTOR_NAMES = {
    "ADP",
    "ATP",
    "COA",
    "FAD",
    "FMN",
    "GDP",
    "GTP",
    "HEM",
    "NAD",
    "NAP",
    "PLP",
    "SAH",
    "SAM",
    "TPP",
}
MODIFIED_AMINO_ACIDS = {"CSO", "HYP", "MSE", "PTR", "SEP", "TPO"}
PROTEIN_RESIDUES = {
    "ALA",
    "ARG",
    "ASN",
    "ASP",
    "ASX",
    "CYS",
    "GLN",
    "GLU",
    "GLX",
    "GLY",
    "HIS",
    "ILE",
    "LEU",
    "LYS",
    "MET",
    "PHE",
    "PRO",
    "PYL",
    "SEC",
    "SER",
    "THR",
    "TRP",
    "TYR",
    "UNK",
    "VAL",
}
METAL_ELEMENTS = {
    "AG",
    "AL",
    "AU",
    "BA",
    "BE",
    "CA",
    "CD",
    "CO",
    "CR",
    "CS",
    "CU",
    "FE",
    "HG",
    "K",
    "LI",
    "MG",
    "MN",
    "MO",
    "NA",
    "NI",
    "PB",
    "PT",
    "RB",
    "SR",
    "V",
    "W",
    "ZN",
}
ION_NAMES = {
    "BR",
    "CL",
    "F",
    "IOD",
    "NO3",
    "PO4",
    "SO4",
}
CHAIN_SYMBOLS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
BACKBONE_ATOMS = {"N", "CA", "C", "O"}


class PreparationError(RuntimeError):
    """Raised when an input cannot produce a valid detector structure."""


class StructureSource(BaseModel):
    """Typed identity and biological representation for a structure input."""

    provider: Literal["rcsb", "alphafold", "local"]
    identifier: str = Field(min_length=1, max_length=64)
    representation: Literal[
        "asymmetric_unit",
        "biological_assembly",
        "predicted_model",
        "local",
    ]
    assembly_id: str | None = None
    model_entity_id: str | None = None
    local_path: Path | None = None

    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("identifier")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("assembly_id")
    @classmethod
    def normalize_assembly_id(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def validate_provider_contract(self) -> StructureSource:
        if self.provider == "rcsb":
            if not re.fullmatch(r"[A-Z0-9]{4}", self.identifier):
                raise ValueError("RCSB identifiers must be four alphanumeric characters")
            if self.representation not in {"asymmetric_unit", "biological_assembly"}:
                raise ValueError("RCSB source requires asymmetric_unit or biological_assembly")
            if self.representation == "biological_assembly" and not self.assembly_id:
                raise ValueError("biological_assembly requires assembly_id")
        elif self.provider == "alphafold":
            if self.representation != "predicted_model":
                raise ValueError("AlphaFold source requires predicted_model representation")
        elif self.representation != "local" or self.local_path is None:
            raise ValueError("Local source requires representation=local and local_path")
        return self


class PreparationConfig(BaseModel):
    """Versioned scientific contract for detector input preparation."""

    chain_ids: tuple[str, ...] | None = None
    altloc_policy: Literal["highest_occupancy"] = "highest_occupancy"
    detector_atom_policy: Literal["protein_heavy_atoms_only"] = "protein_heavy_atoms_only"
    preserve_metals_in_context: bool = True
    preserve_cofactors_in_context: bool = True
    preserve_ions_in_context: bool = False
    include_modified_amino_acids: bool = True
    model_index: Literal[1] = 1
    min_protein_residues: int = Field(default=10, ge=1, le=100000)
    min_protein_atoms: int = Field(default=50, ge=4, le=1000000)
    max_missing_backbone_fraction: float = Field(default=0.20, ge=0.0, le=1.0)

    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("chain_ids")
    @classmethod
    def normalize_chains(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if value is None:
            return None
        normalized = tuple(sorted({chain.strip() for chain in value if chain.strip()}))
        if not normalized:
            raise ValueError("chain_ids cannot be empty")
        return normalized


@dataclass(frozen=True)
class ParsedAtom:
    record: str
    atom_name: str
    altloc: str
    res_name: str
    chain_id: str
    res_id: int
    ins_code: str
    x: float
    y: float
    z: float
    occupancy: float
    b_factor: float
    element: str


@dataclass(frozen=True)
class PreparationResult:
    prepared_path: Path
    context_path: Path
    report_path: Path
    manifest_path: Path
    input_sha256: str
    prepared_sha256: str
    config_sha256: str
    report_sha256: str


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n").encode("utf-8")


def _git_identity() -> dict[str, Any]:
    repository = Path(__file__).resolve().parent.parent
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repository,
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            ).stdout.strip()
        )
        return {"commit": commit, "worktree_dirty": dirty}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "worktree_dirty": None}


def _infer_element(atom_name: str) -> str:
    stripped = "".join(char for char in atom_name if char.isalpha()).upper()
    if not stripped:
        return ""
    if len(stripped) >= 2 and stripped[:2] in METAL_ELEMENTS:
        return stripped[:2]
    return stripped[0]


def _parse_pdb(path: Path) -> tuple[list[ParsedAtom], dict[str, Any]]:
    atoms: list[ParsedAtom] = []
    model_count = 0
    current_model = 1
    seqres_counts: dict[str, int] = {}

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("MODEL"):
                model_count += 1
                try:
                    current_model = int(line[10:14].strip())
                except ValueError:
                    current_model = model_count
                continue
            if line.startswith("ENDMDL") and current_model == 1:
                break
            if line.startswith("SEQRES"):
                chain = line[11:12].strip() or "_"
                try:
                    seqres_counts[chain] = max(seqres_counts.get(chain, 0), int(line[13:17]))
                except ValueError:
                    pass
                continue
            if not (line.startswith("ATOM  ") or line.startswith("HETATM")):
                continue
            if model_count and current_model != 1:
                continue
            try:
                atoms.append(
                    ParsedAtom(
                        record=line[0:6].strip(),
                        atom_name=line[12:16].strip().upper(),
                        altloc=line[16:17].strip().upper(),
                        res_name=line[17:20].strip().upper(),
                        chain_id=line[21:22].strip() or "_",
                        res_id=int(line[22:26]),
                        ins_code=line[26:27].strip().upper(),
                        x=float(line[30:38]),
                        y=float(line[38:46]),
                        z=float(line[46:54]),
                        occupancy=float(line[54:60] or 0.0),
                        b_factor=float(line[60:66] or 0.0),
                        element=(line[76:78].strip().upper() or _infer_element(line[12:16])),
                    )
                )
            except (ValueError, IndexError) as exc:
                raise PreparationError(
                    f"Invalid PDB atom record in {path}: {line.rstrip()}"
                ) from exc
    return atoms, {
        "input_format": "pdb",
        "model_count": max(1, model_count),
        "declared_residue_counts": seqres_counts,
        "expected_residues": [],
    }


def _parse_mmcif(path: Path) -> tuple[list[ParsedAtom], dict[str, Any]]:
    try:
        cif_file = pdbx.CIFFile.read(path)
        structure = pdbx.get_structure(
            cif_file,
            model=1,
            altloc="all",
            extra_fields=["occupancy", "b_factor", "atom_id"],
            use_author_fields=True,
        )
    except Exception as exc:
        raise PreparationError(f"Unable to parse mmCIF structure: {path}") from exc

    atoms = [
        ParsedAtom(
            record="HETATM" if bool(structure.hetero[index]) else "ATOM",
            atom_name=str(structure.atom_name[index]).strip().upper(),
            altloc=(
                ""
                if str(structure.altloc_id[index]).strip() in {"", ".", "?"}
                else str(structure.altloc_id[index]).strip().upper()
            ),
            res_name=str(structure.res_name[index]).strip().upper(),
            chain_id=str(structure.chain_id[index]).strip() or "_",
            res_id=int(structure.res_id[index]),
            ins_code=str(structure.ins_code[index]).strip(),
            x=float(structure.coord[index, 0]),
            y=float(structure.coord[index, 1]),
            z=float(structure.coord[index, 2]),
            occupancy=float(structure.occupancy[index]),
            b_factor=float(structure.b_factor[index]),
            element=str(structure.element[index]).strip().upper(),
        )
        for index in range(structure.array_length())
    ]

    expected_residues: list[tuple[str, int, str]] = []
    block = cif_file.block
    if "pdbx_poly_seq_scheme" in block:
        scheme = block["pdbx_poly_seq_scheme"]
        chains = scheme["pdb_strand_id"].as_array(str)
        residue_ids = scheme["pdb_seq_num"].as_array(str)
        residue_names = scheme["pdb_mon_id"].as_array(str)
        for chain, residue_id, residue_name in zip(chains, residue_ids, residue_names):
            try:
                expected_residues.append(
                    (str(chain).strip() or "_", int(residue_id), str(residue_name).strip().upper())
                )
            except ValueError:
                continue

    return atoms, {
        "input_format": "mmcif",
        "model_count": 1,
        "declared_residue_counts": {},
        "expected_residues": expected_residues,
    }


def _parse_structure(path: Path) -> tuple[list[ParsedAtom], dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix in {".cif", ".mmcif"}:
        return _parse_mmcif(path)
    return _parse_pdb(path)


def load_structure_atoms(path: str | Path) -> tuple[ParsedAtom, ...]:
    """Load first-model atoms with the canonical highest-occupancy altloc policy."""
    source_path = Path(path).resolve()
    if not source_path.is_file():
        raise PreparationError(f"Structure input not found: {source_path}")
    atoms, _metadata = _parse_structure(source_path)
    if not atoms:
        raise PreparationError("Structure contains no atom records")
    _validate_coordinates(atoms)
    selected, _removed = _select_altlocs(atoms)
    return tuple(sorted(selected, key=_atom_sort_key))


def _altloc_rank(atom: ParsedAtom) -> tuple[float, int, int]:
    preference = 2 if atom.altloc == "" else 1 if atom.altloc == "A" else 0
    lexical_preference = -ord(atom.altloc[0]) if atom.altloc else 0
    return (atom.occupancy, preference, lexical_preference)


def _select_altlocs(atoms: list[ParsedAtom]) -> tuple[list[ParsedAtom], int]:
    selected: dict[tuple[str, int, str, str], ParsedAtom] = {}
    for atom in atoms:
        key = (atom.chain_id, atom.res_id, atom.ins_code, atom.atom_name)
        current = selected.get(key)
        if current is None or _altloc_rank(atom) > _altloc_rank(current):
            selected[key] = atom
    return list(selected.values()), len(atoms) - len(selected)


def _classify(atom: ParsedAtom, config: PreparationConfig) -> str:
    if atom.res_name in PROTEIN_RESIDUES or (
        config.include_modified_amino_acids and atom.res_name in MODIFIED_AMINO_ACIDS
    ):
        return "protein"
    if atom.res_name in WATER_NAMES:
        return "water"
    if atom.res_name in COFACTOR_NAMES:
        return "cofactor"
    if atom.element in METAL_ELEMENTS or atom.res_name in METAL_ELEMENTS:
        return "metal"
    if atom.res_name in ION_NAMES:
        return "ion"
    if atom.record == "ATOM":
        return "nonprotein_polymer"
    return "ligand"


def _chain_map(chain_ids: list[str]) -> dict[str, str]:
    if len(chain_ids) > len(CHAIN_SYMBOLS):
        raise PreparationError("Prepared PDB supports at most 62 selected chains")
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for chain in chain_ids:
        if len(chain) == 1 and chain != "_" and chain in CHAIN_SYMBOLS and chain not in used:
            mapping[chain] = chain
            used.add(chain)
    available = iter(symbol for symbol in CHAIN_SYMBOLS if symbol not in used)
    for chain in chain_ids:
        if chain not in mapping:
            mapping[chain] = next(available)
    return mapping


def _atom_sort_key(atom: ParsedAtom) -> tuple[Any, ...]:
    return (
        atom.chain_id,
        atom.res_id,
        atom.ins_code,
        atom.res_name,
        atom.atom_name,
        atom.element,
        atom.x,
        atom.y,
        atom.z,
    )


def _pdb_bytes(
    atoms: list[ParsedAtom],
    chain_mapping: dict[str, str],
    *,
    force_atom_records: bool = False,
) -> bytes:
    lines = [f"REMARK 900 GENERATED BY BIOVOID {PREPARATION_POLICY_VERSION}"]
    for serial, atom in enumerate(sorted(atoms, key=_atom_sort_key), start=1):
        if serial > 99999 or not (-999 <= atom.res_id <= 9999):
            raise PreparationError("Prepared structure exceeds legacy PDB numbering limits")
        record = "ATOM" if force_atom_records or atom.record == "ATOM" else "HETATM"
        chain = chain_mapping[atom.chain_id]
        lines.append(
            f"{record:<6}{serial:5d} {atom.atom_name:>4s} {atom.res_name:>3s} "
            f"{chain:1s}{atom.res_id:4d}{atom.ins_code[:1]:1s}   "
            f"{atom.x:8.3f}{atom.y:8.3f}{atom.z:8.3f}"
            f"{atom.occupancy:6.2f}{atom.b_factor:6.2f}          {atom.element:>2s}"
        )
    lines.extend(["TER", "END", ""])
    return "\n".join(lines).encode("ascii")


def _component_records(atoms: list[ParsedAtom], category: str, reason: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int, str, str], int] = {}
    for atom in atoms:
        key = (atom.chain_id, atom.res_id, atom.ins_code, atom.res_name)
        grouped[key] = grouped.get(key, 0) + 1
    return [
        {
            "category": category,
            "chain_id": chain,
            "residue_id": residue_id,
            "insertion_code": insertion_code,
            "residue_name": residue_name,
            "atom_count": atom_count,
            "reason": reason,
            "detector_visible": False,
        }
        for (chain, residue_id, insertion_code, residue_name), atom_count in sorted(grouped.items())
    ]


def _validate_coordinates(atoms: list[ParsedAtom]) -> None:
    for atom in atoms:
        if not all(math.isfinite(value) for value in (atom.x, atom.y, atom.z)):
            raise PreparationError("Structure contains NaN or infinite coordinates")


def prepare_structure(
    input_path: str | Path,
    source: StructureSource,
    config: PreparationConfig,
    output_dir: str | Path,
    run_id: str,
    *,
    source_metadata: dict[str, Any] | None = None,
    analysis_config: dict[str, Any] | None = None,
) -> PreparationResult:
    """Prepare a deterministic protein-heavy-atom detector input."""
    source_path = Path(input_path).resolve()
    if not source_path.is_file():
        raise PreparationError(f"Structure input not found: {source_path}")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    atoms, parse_metadata = _parse_structure(source_path)
    if not atoms:
        raise PreparationError("Structure contains no atom records")
    _validate_coordinates(atoms)

    selected_altlocs, alternate_atoms_removed = _select_altlocs(atoms)
    classified = [(atom, _classify(atom, config)) for atom in selected_altlocs]
    available_protein_chains = sorted(
        {atom.chain_id for atom, category in classified if category == "protein"}
    )
    selected_chains = list(config.chain_ids or tuple(available_protein_chains))
    missing_chains = sorted(set(selected_chains) - set(available_protein_chains))
    if missing_chains:
        raise PreparationError(f"Requested protein chains are absent: {missing_chains}")

    protein_atoms = [
        atom
        for atom, category in classified
        if category == "protein"
        and atom.chain_id in selected_chains
        and atom.element not in {"H", "D"}
    ]
    atom_names = {atom.atom_name for atom in protein_atoms}
    if atom_names and atom_names == {"CA"}:
        raise PreparationError("C-alpha-only input cannot produce a canonical detector structure")

    residues: dict[tuple[str, int, str, str], set[str]] = {}
    for atom in protein_atoms:
        key = (atom.chain_id, atom.res_id, atom.ins_code, atom.res_name)
        residues.setdefault(key, set()).add(atom.atom_name)
    if len(residues) < config.min_protein_residues:
        raise PreparationError(
            f"Too few protein residues after preparation: {len(residues)} "
            f"(minimum {config.min_protein_residues})"
        )
    if len(protein_atoms) < config.min_protein_atoms:
        raise PreparationError(
            f"Too few protein atoms after preparation: {len(protein_atoms)} "
            f"(minimum {config.min_protein_atoms})"
        )

    missing_backbone = [
        {
            "chain_id": chain,
            "residue_id": residue_id,
            "insertion_code": insertion_code,
            "residue_name": residue_name,
            "missing_atoms": sorted(BACKBONE_ATOMS - names),
        }
        for (chain, residue_id, insertion_code, residue_name), names in sorted(residues.items())
        if not BACKBONE_ATOMS.issubset(names)
    ]
    missing_backbone_fraction = len(missing_backbone) / len(residues)
    if missing_backbone_fraction > config.max_missing_backbone_fraction:
        raise PreparationError(
            f"Structure missing backbone atoms in {missing_backbone_fraction:.1%} of residues; "
            f"limit is {config.max_missing_backbone_fraction:.1%}"
        )

    observed_residue_keys = {(chain, residue_id) for chain, residue_id, _, _ in residues}
    expected_residues = [
        (chain, residue_id, residue_name)
        for chain, residue_id, residue_name in parse_metadata["expected_residues"]
        if chain in selected_chains
    ]
    missing_residues = [
        {"chain_id": chain, "residue_id": residue_id, "residue_name": residue_name}
        for chain, residue_id, residue_name in expected_residues
        if (chain, residue_id) not in observed_residue_keys
    ]
    coordinate_numbering_gaps = 0
    for chain in selected_chains:
        chain_ids = sorted(
            {residue_id for residue_chain, residue_id, _, _ in residues if residue_chain == chain}
        )
        coordinate_numbering_gaps += sum(
            max(0, right - left - 1) for left, right in zip(chain_ids, chain_ids[1:])
        )

    categories: dict[str, list[ParsedAtom]] = {
        "water": [],
        "metal": [],
        "cofactor": [],
        "ion": [],
        "ligand": [],
        "nonprotein_polymer": [],
    }
    for atom, category in classified:
        if category in categories:
            categories[category].append(atom)

    context_atoms: list[ParsedAtom] = []
    context_components: list[dict[str, Any]] = []
    context_policies = (
        ("metal", config.preserve_metals_in_context, "preserved_metal_context_only"),
        ("cofactor", config.preserve_cofactors_in_context, "preserved_cofactor_context_only"),
        ("ion", config.preserve_ions_in_context, "preserved_ion_context_only"),
    )
    for category, preserve, reason in context_policies:
        category_atoms = categories[category]
        if preserve:
            context_atoms.extend(category_atoms)
            context_components.extend(_component_records(category_atoms, category, reason))

    chain_mapping = _chain_map(sorted({atom.chain_id for atom in [*protein_atoms, *context_atoms]}))
    prepared_content = _pdb_bytes(
        protein_atoms,
        chain_mapping,
        force_atom_records=True,
    )
    context_content = _pdb_bytes(context_atoms, chain_mapping) if context_atoms else b"END\n"
    prepared_path = output / "prepared_detector.pdb"
    context_path = output / "preserved_context.pdb"
    prepared_path.write_bytes(prepared_content)
    context_path.write_bytes(context_content)

    input_sha256 = _sha256_file(source_path)
    prepared_sha256 = _sha256_bytes(prepared_content)
    config_payload = config.model_dump(mode="json")
    config_sha256 = _sha256_bytes(_json_bytes(config_payload))
    analysis_config_payload = analysis_config or {}
    analysis_config_sha256 = _sha256_bytes(_json_bytes(analysis_config_payload))
    warnings: list[str] = []
    if parse_metadata["model_count"] > 1:
        warnings.append("multiple_models_present_first_model_selected")
    if missing_backbone:
        warnings.append("missing_backbone_atoms_below_hard_fail_threshold")
    if missing_residues:
        warnings.append("declared_residues_missing_from_coordinates")
    elif coordinate_numbering_gaps:
        warnings.append("coordinate_numbering_gaps_present_sequence_confirmation_unavailable")

    alpha_confidence: dict[str, Any] | None = None
    if source.provider == "alphafold":
        ca_scores = [atom.b_factor for atom in protein_atoms if atom.atom_name == "CA"]
        alpha_confidence = {
            "plddt_source": "pdb_b_factor_field",
            "mean_plddt": round(sum(ca_scores) / len(ca_scores), 3) if ca_scores else None,
            "min_plddt": round(min(ca_scores), 3) if ca_scores else None,
            "pae_url": (source_metadata or {}).get("pae_url"),
            "sequence_start": (source_metadata or {}).get("sequence_start"),
            "sequence_end": (source_metadata or {}).get("sequence_end"),
            "fragmented_model": (source_metadata or {}).get("fragmented_model", False),
            "model_entity_id": (source_metadata or {}).get("model_entity_id"),
            "latest_version": (source_metadata or {}).get("latest_version"),
        }

    report = {
        "schema_version": PREPARATION_POLICY_VERSION,
        "status": "valid",
        "source": source.model_dump(mode="json"),
        "source_metadata": source_metadata or {},
        "config": config_payload,
        "detector_atom_policy": config.detector_atom_policy,
        "selected_chains": selected_chains,
        "available_protein_chains": available_protein_chains,
        "chain_id_map": chain_mapping,
        "altloc_policy": config.altloc_policy,
        "model_policy": "first_model_only",
        "input_format": parse_metadata["input_format"],
        "counts": {
            "input_atoms": len(atoms),
            "alternate_atoms_removed": alternate_atoms_removed,
            "protein_atoms_selected": len(protein_atoms),
            "protein_residues_selected": len(residues),
            "water_removed": len(categories["water"]),
            "ligand_removed": len(categories["ligand"]),
            "nonprotein_polymer_atoms_removed": len(categories["nonprotein_polymer"]),
            "ion_removed": len(categories["ion"]),
            "metal_context_preserved": (
                len(categories["metal"]) if config.preserve_metals_in_context else 0
            ),
            "cofactor_context_preserved": (
                len(categories["cofactor"]) if config.preserve_cofactors_in_context else 0
            ),
            "missing_backbone_residues": len(missing_backbone),
            "missing_declared_residues": len(missing_residues),
            "coordinate_numbering_gaps": coordinate_numbering_gaps,
        },
        "missing_backbone": missing_backbone,
        "missing_residues": missing_residues,
        "missing_residue_assessment": (
            "mmcif_polymer_sequence"
            if expected_residues
            else "coordinate_numbering_and_optional_pdb_seqres"
        ),
        "context_components": context_components,
        "alphafold_confidence": alpha_confidence,
        "warnings": warnings,
        "hashes": {
            "input_sha256": input_sha256,
            "prepared_sha256": prepared_sha256,
            "preparation_config_sha256": config_sha256,
        },
    }
    report_path = output / "preparation_report.json"
    report_content = _json_bytes(report)
    report_path.write_bytes(report_content)
    report_sha256 = _sha256_bytes(report_content)

    manifest = {
        "schema_version": "run-manifest-v1",
        "analysis_run_id": run_id,
        "source": source.model_dump(mode="json"),
        "preparation_policy_version": PREPARATION_POLICY_VERSION,
        "preparation_status": "valid",
        "software": {
            "biovoid_version": __version__,
            "python_version": platform.python_version(),
            "platform": sys.platform,
            "git": _git_identity(),
        },
        "environment": environment_manifest(),
        "analysis_config": analysis_config_payload,
        "files": {
            "input_name": source_path.name,
            "prepared_detector": prepared_path.name,
            "preserved_context": context_path.name,
            "preparation_report": report_path.name,
        },
        "hashes": {
            "input_sha256": input_sha256,
            "prepared_sha256": prepared_sha256,
            "preparation_config_sha256": config_sha256,
            "analysis_config_sha256": analysis_config_sha256,
            "preparation_report_sha256": report_sha256,
        },
        "canonical_detector_input": prepared_path.name,
        "evaluator_target_included": False,
    }
    manifest_path = output / "run_manifest.json"
    manifest_path.write_bytes(_json_bytes(manifest))

    return PreparationResult(
        prepared_path=prepared_path,
        context_path=context_path,
        report_path=report_path,
        manifest_path=manifest_path,
        input_sha256=input_sha256,
        prepared_sha256=prepared_sha256,
        config_sha256=config_sha256,
        report_sha256=report_sha256,
    )

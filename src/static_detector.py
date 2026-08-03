"""Canonical full-heavy-atom static pocket geometry for recovery Phase 3.

The detector uses Voronoi vertices only as candidate empty-space centers.
Candidate acceptance is based on van der Waals surface clearance and
directional ray enclosure; a protein-wide convex hull is not used as a
molecular surface. Merged pocket volume is the union of candidate spheres.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from scipy.cluster.hierarchy import fclusterdata
from scipy.spatial import KDTree, Voronoi
from scipy.stats import qmc

from .resources import ResourceProfile, SAFE_16GB, get_available_memory_bytes
from .runtime import CanonicalInputError, require_full_atom_structure
from .structure_preparation import (
    METAL_ELEMENTS,
    MODIFIED_AMINO_ACIDS,
    PROTEIN_RESIDUES,
    WATER_NAMES,
)

DETECTOR_VERSION = "canonical-static-v1"
ATOM_RADIUS_POLICY_VERSION = "protein-heavy-bondi-v1"
SURFACE_MODEL = "vdw_directional_ray_enclosure"
SURFACE_MODEL_VERSION = "vdw-directional-ray-v1"
VOLUME_METHOD = "voxel_union_v1"
VOLUME_CANDIDATE_METHOD = "sobol_union_v1"

# Bondi, J. Phys. Chem. 1964, 68, 441-451, DOI: 10.1021/j100785a001.
# Values absent from the original compact table are explicit policy extensions.
VDW_RADII_ANGSTROM = {
    "C": 1.70,
    "N": 1.55,
    "O": 1.52,
    "F": 1.47,
    "P": 1.80,
    "S": 1.80,
    "CL": 1.75,
    "SE": 1.90,
    "BR": 1.85,
    "I": 1.98,
}
VDW_RADIUS_PROVENANCE = {
    "policy_version": ATOM_RADIUS_POLICY_VERSION,
    "primary_reference": "Bondi 1964, DOI 10.1021/j100785a001",
    "selenium_policy": "explicit 1.90 A extension",
    "metals": "context_only_not_detector_atoms",
}
HYDROPHOBIC_RESIDUES = {"ALA", "ILE", "LEU", "MET", "PHE", "PRO", "TRP", "VAL"}


@dataclass(frozen=True)
class Sphere:
    center: tuple[float, float, float]
    radius: float

    def __post_init__(self) -> None:
        if len(self.center) != 3 or not np.all(np.isfinite(self.center)):
            raise ValueError("Sphere center must contain three finite coordinates")
        if not math.isfinite(self.radius) or self.radius <= 0:
            raise ValueError("Sphere radius must be positive and finite")


@dataclass(frozen=True)
class VolumeEstimate:
    volume: float
    surface_area: float | None
    method: str
    resolution: float | None
    sample_count: int
    occupied_count: int
    runtime_seconds: float


@dataclass(frozen=True)
class EnclosureMeasurement:
    enclosure_fraction: float
    blocked_rays: int
    total_rays: int
    ray_length: float
    method: str = SURFACE_MODEL_VERSION


@dataclass(frozen=True)
class ClassifiedAtoms:
    counts: dict[str, int]
    protein_elements: tuple[str, ...]


@dataclass(frozen=True)
class ProteinAtomSet:
    coordinates: np.ndarray
    elements: tuple[str, ...]
    radii: np.ndarray
    atom_names: tuple[str, ...]
    residue_keys: tuple[str, ...]
    residue_names: tuple[str, ...]


@dataclass(frozen=True)
class StaticDetectorConfig:
    minimum_surface_clearance: float = 1.4
    maximum_surface_clearance: float = 4.5
    minimum_enclosure: float = 0.42
    enclosure_ray_length: float = 8.0
    enclosure_ray_count: int = 96
    merge_threshold: float = 4.0
    minimum_volume: float = 20.0
    maximum_volume: float = 5000.0
    volume_spacing: float = 0.40
    convergence_spacing: float = 0.80
    maximum_convergence_delta: float = 0.20
    residue_search_radius: float = 6.0

    def __post_init__(self) -> None:
        positive = (
            self.minimum_surface_clearance,
            self.maximum_surface_clearance,
            self.enclosure_ray_length,
            self.merge_threshold,
            self.maximum_volume,
            self.volume_spacing,
            self.convergence_spacing,
            self.residue_search_radius,
        )
        if any(not math.isfinite(value) or value <= 0 for value in positive):
            raise ValueError("Detector distances, limits, and resolutions must be positive")
        if self.minimum_surface_clearance >= self.maximum_surface_clearance:
            raise ValueError("minimum_surface_clearance must be below maximum_surface_clearance")
        if not 0 <= self.minimum_enclosure <= 1:
            raise ValueError("minimum_enclosure must be in [0, 1]")
        if self.enclosure_ray_count < 12:
            raise ValueError("enclosure_ray_count must be at least 12")
        if self.minimum_volume < 0 or self.minimum_volume >= self.maximum_volume:
            raise ValueError("Volume limits are invalid")
        if not 0 <= self.maximum_convergence_delta <= 1:
            raise ValueError("maximum_convergence_delta must be in [0, 1]")


@dataclass(frozen=True)
class StaticPocket:
    pocket_id: str
    center: tuple[float, float, float]
    center_method: str
    volume: float
    volume_method: str
    volume_resolution: float
    volume_convergence_delta: float
    surface_area: float
    surface_model: str
    depth: float
    depth_method: str
    minimum_surface_clearance: float
    enclosure_ray_length: float
    enclosure: float
    open_fraction: float
    radius_geom: float
    radius_clear: float
    merged_vertices: int
    vertices: tuple[tuple[float, float, float], ...]
    vertex_radii: tuple[float, ...]
    residues: tuple[str, ...]
    hydrophobic_ratio: float
    polar_atoms: int
    prepared_structure_sha256: str
    detector_version: str
    detector_config_sha256: str
    atom_policy_version: str
    warnings: tuple[str, ...]
    validity: str

    def to_portable_dict(self) -> dict[str, Any]:
        return {
            "pocket_id": self.pocket_id,
            "center": [_rounded(value) for value in self.center],
            "center_method": self.center_method,
            "volume": _rounded(self.volume),
            "volume_method": self.volume_method,
            "volume_resolution": self.volume_resolution,
            "volume_convergence_delta": _rounded(self.volume_convergence_delta),
            "surface_area": _rounded(self.surface_area),
            "surface_model": self.surface_model,
            "depth": _rounded(self.depth),
            "depth_method": self.depth_method,
            "minimum_surface_clearance": _rounded(self.minimum_surface_clearance),
            "enclosure_ray_length": self.enclosure_ray_length,
            "enclosure": _rounded(self.enclosure),
            "open_fraction": _rounded(self.open_fraction),
            "radius_geom": _rounded(self.radius_geom),
            "radius_clear": _rounded(self.radius_clear),
            "merged_vertices": self.merged_vertices,
            "vertices": [[_rounded(value) for value in vertex] for vertex in self.vertices],
            "vertex_radii": [_rounded(value) for value in self.vertex_radii],
            "residues": list(self.residues),
            "hydrophobic_ratio": _rounded(self.hydrophobic_ratio),
            "polar_atoms": self.polar_atoms,
            "prepared_structure_sha256": self.prepared_structure_sha256,
            "detector_version": self.detector_version,
            "detector_config_sha256": self.detector_config_sha256,
            "atom_policy_version": self.atom_policy_version,
            "warnings": list(self.warnings),
            "validity": self.validity,
        }

    def to_legacy_dict(self) -> dict[str, Any]:
        payload = self.to_portable_dict()
        payload.update(
            {
                "radius": payload["radius_clear"],
                "merge_threshold": None,
                "druggable": None,
            }
        )
        return payload


@dataclass(frozen=True)
class StaticDetectionResult:
    pockets: tuple[StaticPocket, ...]
    candidate_count: int
    detector_version: str
    config_sha256: str
    atom_policy_version: str
    radius_provenance: dict[str, str]
    surface_model: str
    volume_method: str
    prepared_structure_sha256: str
    protein_atom_count: int
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _AtomRecord:
    record: str
    atom_name: str
    residue_name: str
    chain_id: str
    residue_id: str
    element: str
    coordinate: tuple[float, float, float]


def _rounded(value: float) -> float:
    return round(float(value), 6)


def _config_sha256(config: StaticDetectorConfig) -> str:
    payload = json.dumps(asdict(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def static_detector_config_sha256(config: StaticDetectorConfig | None = None) -> str:
    """Return the content identity of the effective static detector policy."""
    return _config_sha256(config or StaticDetectorConfig())


def _parse_pdb_records(path: str | Path) -> list[_AtomRecord]:
    records: list[_AtomRecord] = []
    with Path(path).open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.startswith(("ATOM  ", "HETATM")):
                continue
            try:
                coordinate = (
                    float(line[30:38]),
                    float(line[38:46]),
                    float(line[46:54]),
                )
            except ValueError as exc:
                raise CanonicalInputError("Invalid coordinate in detector PDB input") from exc
            atom_name = line[12:16].strip().upper()
            element = line[76:78].strip().upper()
            if not element:
                element = "".join(char for char in atom_name if char.isalpha())[:1]
            records.append(
                _AtomRecord(
                    record=line[:6].strip().upper(),
                    atom_name=atom_name,
                    residue_name=line[17:20].strip().upper(),
                    chain_id=line[21:22].strip() or "_",
                    residue_id=(line[22:26].strip() + line[26:27].strip()) or "_",
                    element=element,
                    coordinate=coordinate,
                )
            )
    return records


def _atom_category(record: _AtomRecord) -> str:
    if record.record == "ATOM" and record.residue_name in (PROTEIN_RESIDUES | MODIFIED_AMINO_ACIDS):
        if record.element in {"H", "D"}:
            return "protein_hydrogen"
        return "protein_heavy"
    if record.residue_name in WATER_NAMES:
        return "water"
    if record.element in METAL_ELEMENTS or record.residue_name in METAL_ELEMENTS:
        return "metal"
    if record.record == "HETATM":
        return "ligand"
    return "other"


def classify_pdb_atoms(path: str | Path) -> ClassifiedAtoms:
    counts = {
        "protein_heavy": 0,
        "protein_hydrogen": 0,
        "water": 0,
        "ligand": 0,
        "metal": 0,
        "other": 0,
    }
    protein_elements: list[str] = []
    for record in _parse_pdb_records(path):
        category = _atom_category(record)
        counts[category] += 1
        if category == "protein_heavy":
            protein_elements.append(record.element)
    return ClassifiedAtoms(counts=counts, protein_elements=tuple(protein_elements))


def radius_for_element(element: str) -> float:
    normalized = element.strip().upper()
    if normalized in METAL_ELEMENTS:
        raise CanonicalInputError(
            f"Metal {normalized} is context-only and cannot enter canonical detector geometry"
        )
    try:
        return VDW_RADII_ANGSTROM[normalized]
    except KeyError as exc:
        raise CanonicalInputError(
            f"No radius policy exists for detector element {normalized or '<blank>'}"
        ) from exc


def load_protein_atom_set(path: str | Path) -> ProteinAtomSet:
    require_full_atom_structure(path)
    records = [
        record for record in _parse_pdb_records(path) if _atom_category(record) == "protein_heavy"
    ]
    if len(records) < 50:
        raise CanonicalInputError(
            f"Canonical static detector requires at least 50 protein heavy atoms; got {len(records)}"
        )
    coordinates = np.asarray([record.coordinate for record in records], dtype=float)
    if not np.all(np.isfinite(coordinates)):
        raise CanonicalInputError("Detector coordinates contain NaN or infinity")
    extents = np.ptp(coordinates, axis=0)
    if np.any(extents > 1000.0):
        raise CanonicalInputError(f"Detector structure bounding box is too large: {extents}")
    elements = tuple(record.element for record in records)
    return ProteinAtomSet(
        coordinates=coordinates,
        elements=elements,
        radii=np.asarray([radius_for_element(element) for element in elements], dtype=float),
        atom_names=tuple(record.atom_name for record in records),
        residue_keys=tuple(
            f"{record.chain_id}:{record.residue_name}:{record.residue_id}" for record in records
        ),
        residue_names=tuple(record.residue_name for record in records),
    )


def _normalized_spheres(spheres: list[Sphere] | tuple[Sphere, ...]) -> tuple[Sphere, ...]:
    unique: dict[tuple[float, float, float, float], Sphere] = {}
    for sphere in spheres:
        key = (
            round(float(sphere.center[0]), 9),
            round(float(sphere.center[1]), 9),
            round(float(sphere.center[2]), 9),
            round(float(sphere.radius), 9),
        )
        unique[key] = Sphere((key[0], key[1], key[2]), key[3])
    return tuple(unique[key] for key in sorted(unique))


def exact_one_or_two_sphere_union_volume(spheres: list[Sphere]) -> float:
    normalized = _normalized_spheres(spheres)
    if not normalized or len(normalized) > 2:
        raise ValueError("Analytic reference supports one or two unique spheres")
    first_volume = 4.0 * math.pi * normalized[0].radius ** 3 / 3.0
    if len(normalized) == 1:
        return first_volume
    first, second = normalized
    second_volume = 4.0 * math.pi * second.radius**3 / 3.0
    distance = float(np.linalg.norm(np.asarray(first.center) - np.asarray(second.center)))
    if distance >= first.radius + second.radius:
        return first_volume + second_volume
    if distance <= abs(first.radius - second.radius):
        return max(first_volume, second_volume)
    intersection = (
        math.pi
        * (first.radius + second.radius - distance) ** 2
        * (
            distance**2
            + 2.0 * distance * (first.radius + second.radius)
            - 3.0 * (first.radius - second.radius) ** 2
        )
        / (12.0 * distance)
    )
    return first_volume + second_volume - intersection


def _sphere_bounds(spheres: tuple[Sphere, ...]) -> tuple[np.ndarray, np.ndarray]:
    centers = np.asarray([sphere.center for sphere in spheres], dtype=float)
    radii = np.asarray([sphere.radius for sphere in spheres], dtype=float)
    return np.min(centers - radii[:, None], axis=0), np.max(centers + radii[:, None], axis=0)


def voxel_union_volume(
    spheres: list[Sphere] | tuple[Sphere, ...],
    *,
    spacing: float,
    maximum_cells: int = 8_000_000,
) -> VolumeEstimate:
    """Estimate sphere-union volume with a deterministic cell-center voxel grid."""
    if not math.isfinite(spacing) or spacing <= 0:
        raise ValueError("Voxel spacing must be positive and finite")
    normalized = _normalized_spheres(spheres)
    if not normalized:
        return VolumeEstimate(0.0, 0.0, VOLUME_METHOD, spacing, 0, 0, 0.0)

    started = time.perf_counter()
    lower, upper = _sphere_bounds(normalized)
    shape = np.maximum(1, np.ceil((upper - lower) / spacing).astype(int))
    cell_count = int(np.prod(shape, dtype=np.int64))
    if cell_count > maximum_cells:
        raise MemoryError(
            f"Voxel union requires {cell_count:,} cells, above limit {maximum_cells:,}"
        )
    axes = [lower[index] + (np.arange(shape[index]) + 0.5) * spacing for index in range(3)]
    occupied: np.ndarray = np.zeros(
        tuple(int(value) for value in shape),
        dtype=bool,
    )
    centers = np.asarray([sphere.center for sphere in normalized], dtype=float)
    radii_squared = np.asarray([sphere.radius**2 for sphere in normalized], dtype=float)

    xy_x, xy_y = np.meshgrid(axes[0], axes[1], indexing="ij")
    for z_index, z_value in enumerate(axes[2]):
        layer = np.zeros((shape[0], shape[1]), dtype=bool)
        for center, radius_squared in zip(centers, radii_squared, strict=True):
            distance_squared = (
                (xy_x - center[0]) ** 2 + (xy_y - center[1]) ** 2 + (z_value - center[2]) ** 2
            )
            layer |= distance_squared <= radius_squared
        occupied[:, :, z_index] = layer

    occupied_count = int(np.count_nonzero(occupied))
    padded = np.pad(occupied, 1, mode="constant", constant_values=False)
    exposed_faces = 0
    for axis in range(3):
        exposed_faces += int(np.count_nonzero(np.diff(padded.astype(np.int8), axis=axis)))
    surface_area = exposed_faces * spacing**2
    return VolumeEstimate(
        volume=occupied_count * spacing**3,
        surface_area=surface_area,
        method=VOLUME_METHOD,
        resolution=spacing,
        sample_count=cell_count,
        occupied_count=occupied_count,
        runtime_seconds=time.perf_counter() - started,
    )


def sobol_union_volume(
    spheres: list[Sphere] | tuple[Sphere, ...],
    *,
    sample_count: int = 65536,
) -> VolumeEstimate:
    """Estimate sphere-union volume using deterministic scrambled-free Sobol points."""
    normalized = _normalized_spheres(spheres)
    if not normalized:
        return VolumeEstimate(0.0, None, VOLUME_CANDIDATE_METHOD, None, 0, 0, 0.0)
    if sample_count < 2 or sample_count & (sample_count - 1):
        raise ValueError("Sobol sample_count must be a power of two")

    started = time.perf_counter()
    lower, upper = _sphere_bounds(normalized)
    sampler = qmc.Sobol(d=3, scramble=False)
    unit_points = sampler.random_base2(int(math.log2(sample_count)))
    points = qmc.scale(unit_points, lower, upper)
    occupied: np.ndarray = np.zeros(sample_count, dtype=bool)
    for sphere in normalized:
        delta = points - np.asarray(sphere.center)
        occupied |= np.einsum("ij,ij->i", delta, delta) <= sphere.radius**2
    occupied_count = int(np.count_nonzero(occupied))
    box_volume = float(np.prod(upper - lower))
    return VolumeEstimate(
        volume=box_volume * occupied_count / sample_count,
        surface_area=None,
        method=VOLUME_CANDIDATE_METHOD,
        resolution=None,
        sample_count=sample_count,
        occupied_count=occupied_count,
        runtime_seconds=time.perf_counter() - started,
    )


@lru_cache(maxsize=16)
def _ray_directions(count: int) -> np.ndarray:
    golden_angle = math.pi * (3.0 - math.sqrt(5.0))
    points = []
    for index in range(count):
        y = 1.0 - (2.0 * index) / max(1, count - 1)
        radial = math.sqrt(max(0.0, 1.0 - y * y))
        angle = golden_angle * index
        points.append([radial * math.cos(angle), y, radial * math.sin(angle)])
    directions = np.asarray(points, dtype=float)
    directions.setflags(write=False)
    return directions


def directional_enclosure(
    center: np.ndarray,
    atom_coordinates: np.ndarray,
    atom_radii: np.ndarray,
    *,
    ray_length: float = 8.0,
    ray_count: int = 96,
) -> EnclosureMeasurement:
    """Measure the fraction of directions blocked by a van der Waals sphere."""
    center_array = np.asarray(center, dtype=float)
    coordinates = np.asarray(atom_coordinates, dtype=float)
    radii = np.asarray(atom_radii, dtype=float)
    if len(coordinates) != len(radii):
        raise ValueError("atom_coordinates and atom_radii must have equal length")
    directions = _ray_directions(ray_count)
    vectors = coordinates - center_array
    distance_squared = np.einsum("ij,ij->i", vectors, vectors)
    nearby = distance_squared <= (ray_length + radii) ** 2
    vectors = vectors[nearby]
    radii = radii[nearby]
    if not len(vectors):
        return EnclosureMeasurement(0.0, 0, ray_count, ray_length)

    projections = directions @ vectors.T
    perpendicular_squared = distance_squared[nearby][None, :] - projections**2
    intersections = (
        (projections > 0.0)
        & (projections <= ray_length)
        & (perpendicular_squared <= radii[None, :] ** 2)
    )
    blocked = int(np.count_nonzero(np.any(intersections, axis=1)))
    return EnclosureMeasurement(blocked / ray_count, blocked, ray_count, ray_length)


def _surface_clearance(
    point: np.ndarray,
    atom_set: ProteinAtomSet,
    atom_tree: KDTree,
) -> tuple[float, float]:
    k = min(24, len(atom_set.coordinates))
    distances, indices = atom_tree.query(point, k=k)
    distances = np.atleast_1d(distances)
    indices = np.atleast_1d(indices)
    clearances = distances - atom_set.radii[indices]
    nearest = int(np.argmin(clearances))
    return float(clearances[nearest]), float(distances[nearest])


def _candidate_voids(
    atom_set: ProteinAtomSet,
    config: StaticDetectorConfig,
) -> list[dict[str, Any]]:
    try:
        voronoi = Voronoi(atom_set.coordinates)
    except Exception as exc:
        raise CanonicalInputError(f"Voronoi candidate generation failed: {exc}") from exc
    atom_tree = KDTree(atom_set.coordinates)
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[float, float, float]] = set()
    for vertex in voronoi.vertices:
        if not np.all(np.isfinite(vertex)):
            continue
        key = (
            round(float(vertex[0]), 5),
            round(float(vertex[1]), 5),
            round(float(vertex[2]), 5),
        )
        if key in seen:
            continue
        clearance, nearest_center_distance = _surface_clearance(vertex, atom_set, atom_tree)
        if not config.minimum_surface_clearance <= clearance <= config.maximum_surface_clearance:
            continue
        measurement = directional_enclosure(
            vertex,
            atom_set.coordinates,
            atom_set.radii,
            ray_length=config.enclosure_ray_length,
            ray_count=config.enclosure_ray_count,
        )
        if measurement.enclosure_fraction < config.minimum_enclosure:
            continue
        seen.add(key)
        candidates.append(
            {
                "center": np.asarray(key, dtype=float),
                "radius": clearance,
                "nearest_atom_center_distance": nearest_center_distance,
                "enclosure": measurement.enclosure_fraction,
            }
        )
    candidates.sort(key=lambda item: tuple(item["center"]))
    return candidates


def _clusters(candidates: list[dict[str, Any]], threshold: float) -> list[list[dict[str, Any]]]:
    if not candidates:
        return []
    if len(candidates) == 1:
        return [candidates]
    centers = np.asarray([candidate["center"] for candidate in candidates])
    labels = fclusterdata(centers, t=threshold, criterion="distance", method="complete")
    return [
        [candidate for candidate, label in zip(candidates, labels, strict=True) if label == cluster]
        for cluster in sorted(np.unique(labels))
    ]


def _nearby_chemistry(
    center: np.ndarray,
    radius: float,
    atom_set: ProteinAtomSet,
    tree: KDTree,
    search_radius: float,
) -> tuple[tuple[str, ...], float, int]:
    indices = tree.query_ball_point(center, radius + search_radius)
    residues = tuple(sorted({atom_set.residue_keys[index] for index in indices}))
    residue_names = {atom_set.residue_names[index] for index in indices}
    hydrophobic = len(residue_names & HYDROPHOBIC_RESIDUES)
    hydrophobic_ratio = hydrophobic / len(residue_names) if residue_names else 0.0
    polar_atoms = sum(atom_set.elements[index] in {"N", "O", "S"} for index in indices)
    return residues, hydrophobic_ratio, polar_atoms


def _build_pocket(
    cluster: list[dict[str, Any]],
    atom_set: ProteinAtomSet,
    atom_tree: KDTree,
    config: StaticDetectorConfig,
    config_sha256: str,
    prepared_sha256: str,
) -> StaticPocket | None:
    spheres = [
        Sphere(
            (
                float(candidate["center"][0]),
                float(candidate["center"][1]),
                float(candidate["center"][2]),
            ),
            candidate["radius"],
        )
        for candidate in cluster
    ]
    spheres = list(_normalized_spheres(spheres))
    fine = voxel_union_volume(spheres, spacing=config.volume_spacing)
    if fine.volume < config.minimum_volume or fine.volume > config.maximum_volume:
        return None
    coarse = voxel_union_volume(spheres, spacing=config.convergence_spacing)
    convergence_delta = abs(fine.volume - coarse.volume) / max(fine.volume, 1e-12)
    weights = np.asarray([sphere.radius**3 for sphere in spheres], dtype=float)
    centers = np.asarray([sphere.center for sphere in spheres], dtype=float)
    center = np.average(centers, axis=0, weights=weights)
    extent = np.linalg.norm(centers - center, axis=1) + np.asarray(
        [sphere.radius for sphere in spheres]
    )
    radius_geom = float(np.max(extent))
    radius_clear = float(np.max([sphere.radius for sphere in spheres]))
    enclosure = float(
        np.average(
            np.asarray([candidate["enclosure"] for candidate in cluster]),
            weights=np.asarray([candidate["radius"] ** 3 for candidate in cluster]),
        )
    )
    residues, hydrophobic_ratio, polar_atoms = _nearby_chemistry(
        center, radius_geom, atom_set, atom_tree, config.residue_search_radius
    )
    warnings: list[str] = []
    if convergence_delta > config.maximum_convergence_delta:
        warnings.append("volume_resolution_convergence_above_policy")
    stable_material = {
        "prepared_sha256": prepared_sha256,
        "config_sha256": config_sha256,
        "spheres": [
            [*[_rounded(value) for value in sphere.center], _rounded(sphere.radius)]
            for sphere in spheres
        ],
    }
    pocket_id = (
        "BV-"
        + hashlib.sha256(json.dumps(stable_material, sort_keys=True).encode("ascii"))
        .hexdigest()[:12]
        .upper()
    )
    return StaticPocket(
        pocket_id=pocket_id,
        center=(float(center[0]), float(center[1]), float(center[2])),
        center_method="clearance_volume_weighted_alpha_sphere_centers_v1",
        volume=fine.volume,
        volume_method=fine.method,
        volume_resolution=config.volume_spacing,
        volume_convergence_delta=convergence_delta,
        surface_area=float(fine.surface_area or 0.0),
        surface_model=SURFACE_MODEL,
        depth=enclosure * config.enclosure_ray_length,
        depth_method="enclosure_fraction_times_ray_length_proxy_v1",
        minimum_surface_clearance=float(min(sphere.radius for sphere in spheres)),
        enclosure_ray_length=config.enclosure_ray_length,
        enclosure=enclosure,
        open_fraction=1.0 - enclosure,
        radius_geom=radius_geom,
        radius_clear=radius_clear,
        merged_vertices=len(spheres),
        vertices=tuple(sphere.center for sphere in spheres),
        vertex_radii=tuple(sphere.radius for sphere in spheres),
        residues=residues,
        hydrophobic_ratio=hydrophobic_ratio,
        polar_atoms=polar_atoms,
        prepared_structure_sha256=prepared_sha256,
        detector_version=DETECTOR_VERSION,
        detector_config_sha256=config_sha256,
        atom_policy_version=ATOM_RADIUS_POLICY_VERSION,
        warnings=tuple(warnings),
        validity="valid_with_warnings" if warnings else "valid",
    )


def detect_static_pockets(
    pdb_path: str | Path,
    *,
    prepared_sha256: str,
    config: StaticDetectorConfig | None = None,
    resource_profile: ResourceProfile | None = None,
) -> StaticDetectionResult:
    """Run the static detector on a prepared full-heavy-atom PDB.

    The default profile is the canonical safe-16gb policy. A caller may opt
    into a separately recorded bounded profile for local recovery experiments;
    the profile is part of the caller's provenance and does not change the
    detector algorithm or ranking contract.
    """
    if len(prepared_sha256) != 64 or any(
        char not in "0123456789abcdef" for char in prepared_sha256
    ):
        raise ValueError("prepared_sha256 must be a lowercase SHA-256 hex digest")
    effective_config = config or StaticDetectorConfig()
    effective_resource_profile = resource_profile or SAFE_16GB
    config_sha256 = _config_sha256(effective_config)
    atom_set = load_protein_atom_set(pdb_path)
    available_memory = get_available_memory_bytes()
    effective_resource_profile.validate_static_request(
        atom_count=len(atom_set.coordinates),
        available_memory_bytes=available_memory,
    )
    candidates = _candidate_voids(atom_set, effective_config)
    effective_resource_profile.validate_static_request(
        atom_count=len(atom_set.coordinates),
        candidate_count=len(candidates),
        available_memory_bytes=available_memory,
    )
    atom_tree = KDTree(atom_set.coordinates)
    pockets = [
        pocket
        for cluster in _clusters(candidates, effective_config.merge_threshold)
        if (
            pocket := _build_pocket(
                cluster,
                atom_set,
                atom_tree,
                effective_config,
                config_sha256,
                prepared_sha256,
            )
        )
        is not None
    ]
    pockets.sort(key=lambda pocket: (-pocket.volume, pocket.pocket_id))
    warnings: list[str] = []
    if not pockets:
        warnings.append("no_pockets_passed_static_detector_policy")
    return StaticDetectionResult(
        pockets=tuple(pockets),
        candidate_count=len(candidates),
        detector_version=DETECTOR_VERSION,
        config_sha256=config_sha256,
        atom_policy_version=ATOM_RADIUS_POLICY_VERSION,
        radius_provenance=VDW_RADIUS_PROVENANCE,
        surface_model=SURFACE_MODEL,
        volume_method=VOLUME_METHOD,
        prepared_structure_sha256=prepared_sha256,
        protein_atom_count=len(atom_set.coordinates),
        warnings=tuple(warnings),
    )

"""Phase 3 canonical static geometry and interoperability regressions."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest


def _fibonacci_sphere(count: int, radius: float = 1.0) -> np.ndarray:
    points = []
    golden_angle = math.pi * (3.0 - math.sqrt(5.0))
    for index in range(count):
        y = 1.0 - (2.0 * index) / max(1, count - 1)
        radial = math.sqrt(max(0.0, 1.0 - y * y))
        angle = golden_angle * index
        points.append(
            [radius * radial * math.cos(angle), radius * y, radius * radial * math.sin(angle)]
        )
    return np.asarray(points, dtype=float)


def _write_ca_only(path: Path) -> None:
    lines = []
    for index, coord in enumerate(_fibonacci_sphere(60, radius=5.0), start=1):
        lines.append(
            f"ATOM  {index:5d}  CA  ALA A{index:4d}    "
            f"{coord[0]:8.3f}{coord[1]:8.3f}{coord[2]:8.3f}  1.00 20.00           C"
        )
    path.write_text("\n".join(lines) + "\nEND\n", encoding="ascii")


def _write_closed_full_atom_shell(path: Path) -> None:
    lines = []
    serial = 1
    atom_names = ("N", "CA", "C", "O")
    elements = ("N", "C", "C", "O")
    for residue, anchor in enumerate(_fibonacci_sphere(32, radius=5.2), start=1):
        tangent = np.cross(anchor, np.array([0.0, 0.0, 1.0]))
        if np.linalg.norm(tangent) < 1e-6:
            tangent = np.array([1.0, 0.0, 0.0])
        tangent = tangent / np.linalg.norm(tangent)
        for offset_index, (atom_name, element) in enumerate(zip(atom_names, elements, strict=True)):
            coord = anchor + tangent * (offset_index - 1.5) * 0.18
            lines.append(
                f"ATOM  {serial:5d} {atom_name:>4s} ALA A{residue:4d}    "
                f"{coord[0]:8.3f}{coord[1]:8.3f}{coord[2]:8.3f}  1.00 20.00"
                f"          {element:>2s}"
            )
            serial += 1
    path.write_text("\n".join(lines) + "\nEND\n", encoding="ascii")


def test_atom_policy_classifies_records_and_covers_non_chon_elements(tmp_path: Path) -> None:
    from src.static_detector import (
        ATOM_RADIUS_POLICY_VERSION,
        classify_pdb_atoms,
        radius_for_element,
    )

    pdb = tmp_path / "mixed.pdb"
    pdb.write_text(
        "ATOM      1  N   MSE A   1       0.000   0.000   0.000  1.00 20.00           N\n"
        "ATOM      2  SE  MSE A   1       1.000   0.000   0.000  1.00 20.00          SE\n"
        "ATOM      3  P   SEP A   2       2.000   0.000   0.000  1.00 20.00           P\n"
        "ATOM      4  H   SEP A   2       3.000   0.000   0.000  1.00 20.00           H\n"
        "HETATM    5  O   HOH A 101       4.000   0.000   0.000  1.00 20.00           O\n"
        "HETATM    6  C1  LIG A 102       5.000   0.000   0.000  1.00 20.00           C\n"
        "HETATM    7 ZN   ZN  A 103       6.000   0.000   0.000  1.00 20.00          ZN\n"
        "END\n",
        encoding="ascii",
    )

    classified = classify_pdb_atoms(pdb)
    assert classified.counts == {
        "protein_heavy": 3,
        "protein_hydrogen": 1,
        "water": 1,
        "ligand": 1,
        "metal": 1,
        "other": 0,
    }
    assert classified.protein_elements == ("N", "SE", "P")
    assert radius_for_element("P") > 0
    assert radius_for_element("SE") > 0
    assert radius_for_element("CL") > 0
    assert radius_for_element("BR") > 0
    assert ATOM_RADIUS_POLICY_VERSION.startswith("protein-heavy-")


def test_union_volume_matches_analytic_single_disjoint_and_overlap_cases() -> None:
    from src.static_detector import (
        Sphere,
        exact_one_or_two_sphere_union_volume,
        sobol_union_volume,
        voxel_union_volume,
    )

    unit = Sphere((0.0, 0.0, 0.0), 1.0)
    disjoint = Sphere((3.0, 0.0, 0.0), 1.0)
    overlap = Sphere((1.0, 0.0, 0.0), 1.0)
    exact_single = 4.0 * math.pi / 3.0
    exact_disjoint = 2.0 * exact_single
    exact_overlap = exact_one_or_two_sphere_union_volume([unit, overlap])

    assert exact_one_or_two_sphere_union_volume([unit]) == pytest.approx(exact_single)
    assert exact_one_or_two_sphere_union_volume([unit, disjoint]) == pytest.approx(exact_disjoint)
    assert exact_overlap < exact_disjoint
    assert voxel_union_volume([unit], spacing=0.15).volume == pytest.approx(exact_single, rel=0.035)
    assert voxel_union_volume([unit, overlap], spacing=0.15).volume == pytest.approx(
        exact_overlap, rel=0.04
    )
    assert sobol_union_volume([unit, overlap], sample_count=65536).volume == pytest.approx(
        exact_overlap, rel=0.025
    )


def test_union_volume_is_duplicate_translation_order_and_rotation_stable() -> None:
    from src.static_detector import Sphere, voxel_union_volume

    spheres = [
        Sphere((0.0, 0.0, 0.0), 1.3),
        Sphere((1.1, 0.2, -0.1), 1.0),
        Sphere((-0.4, 1.0, 0.3), 0.8),
    ]
    base = voxel_union_volume(spheres, spacing=0.18).volume
    duplicated = voxel_union_volume(spheres + [spheres[0]] * 10, spacing=0.18).volume
    translated = voxel_union_volume(
        [
            Sphere(tuple(np.asarray(s.center) + np.array([11.25, -7.5, 3.0])), s.radius)
            for s in spheres
        ],
        spacing=0.18,
    ).volume
    rotation = np.array(
        [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]],
        dtype=float,
    )
    rotated = voxel_union_volume(
        [Sphere(tuple(rotation @ np.asarray(s.center)), s.radius) for s in spheres],
        spacing=0.18,
    ).volume

    assert duplicated == base
    assert translated == pytest.approx(base, abs=1e-9)
    assert voxel_union_volume(list(reversed(spheres)), spacing=0.18).volume == base
    assert rotated == pytest.approx(base, rel=0.025)


def test_voxel_resolution_converges_toward_known_volume() -> None:
    from src.static_detector import Sphere, voxel_union_volume

    sphere = Sphere((0.0, 0.0, 0.0), 2.0)
    exact = 4.0 * math.pi * 8.0 / 3.0
    coarse = voxel_union_volume([sphere], spacing=0.8).volume
    medium = voxel_union_volume([sphere], spacing=0.4).volume
    fine = voxel_union_volume([sphere], spacing=0.2).volume

    assert abs(fine - exact) < abs(coarse - exact)
    assert abs(fine - medium) / exact < 0.05


def test_directional_enclosure_separates_closed_shell_from_open_surface() -> None:
    from src.static_detector import directional_enclosure

    directions = _fibonacci_sphere(96)
    closed_atoms = directions * 5.0
    open_atoms = directions[directions[:, 2] >= 0.0] * 5.0
    closed_radii = np.full(len(closed_atoms), 1.7)
    open_radii = np.full(len(open_atoms), 1.7)

    closed = directional_enclosure(np.zeros(3), closed_atoms, closed_radii, ray_length=8.0)
    opened = directional_enclosure(np.zeros(3), open_atoms, open_radii, ray_length=8.0)

    assert closed.enclosure_fraction >= 0.85
    assert opened.enclosure_fraction <= 0.65
    assert closed.enclosure_fraction > opened.enclosure_fraction


def test_canonical_detector_rejects_ca_only_and_is_deterministic(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from src.runtime import CanonicalInputError
    from src.static_detector import StaticDetectorConfig, detect_static_pockets

    # This unit test targets geometry and determinism, not the host's transient RAM state.
    monkeypatch.setattr(
        "src.static_detector.get_available_memory_bytes",
        lambda: 12 * 1024**3,
    )

    ca_only = tmp_path / "ca-only.pdb"
    full_atom = tmp_path / "closed-shell.pdb"
    _write_ca_only(ca_only)
    _write_closed_full_atom_shell(full_atom)
    config = StaticDetectorConfig(
        minimum_surface_clearance=1.0,
        maximum_surface_clearance=4.5,
        minimum_enclosure=0.55,
        minimum_volume=1.0,
        volume_spacing=0.35,
        convergence_spacing=0.7,
    )

    with pytest.raises(CanonicalInputError, match="C-alpha-only"):
        detect_static_pockets(ca_only, prepared_sha256="a" * 64, config=config)

    first = detect_static_pockets(full_atom, prepared_sha256="b" * 64, config=config)
    second = detect_static_pockets(full_atom, prepared_sha256="b" * 64, config=config)
    assert first.detector_version == second.detector_version
    assert first.config_sha256 == second.config_sha256
    assert first.atom_policy_version == second.atom_policy_version
    assert first.surface_model == "vdw_directional_ray_enclosure"
    assert first.pockets
    assert [p.to_portable_dict() for p in first.pockets] == [
        p.to_portable_dict() for p in second.pockets
    ]
    pocket = first.pockets[0].to_portable_dict()
    assert pocket["pocket_id"].startswith("BV-")
    assert pocket["prepared_structure_sha256"] == "b" * 64
    assert pocket["volume_method"] == "voxel_union_v1"
    assert pocket["center_method"]
    assert isinstance(pocket["residues"], list)
    assert 0.0 <= pocket["enclosure"] <= 1.0
    assert pocket["validity"] in {"valid", "valid_with_warnings"}


def test_baseline_adapters_share_one_evaluator_schema() -> None:
    from src.evaluator_format import (
        adapt_biovoid_pockets,
        adapt_fpocket_pockets,
        adapt_p2rank_rows,
    )

    biovoid = adapt_biovoid_pockets(
        "1ABC",
        [{"pocket_id": "BV-1", "center": [1.0, 2.0, 3.0], "volume": 100.0}],
    )
    fpocket = adapt_fpocket_pockets(
        "1ABC",
        [{"id": 1, "center": [1.0, 2.0, 3.0], "volume": 101.0, "score": 0.4}],
    )
    p2rank = adapt_p2rank_rows(
        "1ABC",
        [{"rank": 1, "center_x": 1.0, "center_y": 2.0, "center_z": 3.0, "score": 0.8}],
    )

    records = [biovoid, fpocket, p2rank]
    assert {record.detector for record in records} == {
        "biovoid_static",
        "fpocket",
        "p2rank",
    }
    assert all(record.schema_version == "pocket-evaluator-input-v1" for record in records)
    assert all(record.structure_id == "1ABC" for record in records)
    assert all(record.status == "completed" for record in records)
    assert all(record.pockets[0].center == (1.0, 2.0, 3.0) for record in records)


@pytest.mark.performance
def test_volume_methods_are_benchmarked_against_analytic_reference() -> None:
    from src.geometry_benchmark import run_synthetic_volume_benchmark

    report = run_synthetic_volume_benchmark(
        voxel_spacings=(0.4, 0.2),
        sobol_sample_count=16384,
    )
    methods = {row.method for row in report.rows}
    assert methods == {"voxel_union_v1", "sobol_union_v1"}
    assert {row.case for row in report.rows} == {
        "single_sphere",
        "disjoint_spheres",
        "overlapping_spheres",
    }
    assert all(row.runtime_seconds >= 0 for row in report.rows)
    assert all(row.python_peak_allocated_bytes >= 0 for row in report.rows)
    assert all(row.process_peak_rss_bytes > 0 for row in report.rows)
    assert max(row.relative_error for row in report.rows) < 0.08
    assert report.canonical_method == "voxel_union_v1"


@pytest.mark.integration
@pytest.mark.parametrize("pdb_id", ["1BRF", "1AKE"])
def test_real_prepared_static_set_is_deterministic_and_evaluator_ready(
    pdb_id: str,
    tmp_path: Path,
) -> None:
    from src.evaluator_format import adapt_biovoid_pockets
    from src.fetcher import fetch_structure_input
    from src.static_detector import detect_static_pockets
    from src.structure_preparation import (
        PreparationConfig,
        StructureSource,
        prepare_structure,
    )

    source = StructureSource(
        provider="rcsb",
        identifier=pdb_id,
        representation="biological_assembly",
        assembly_id="1",
    )
    fetched = fetch_structure_input(source, cache_dir=tmp_path / "raw")
    prepared = prepare_structure(
        fetched.path,
        source,
        PreparationConfig(),
        tmp_path / "prepared",
        f"phase3-{pdb_id.lower()}",
        source_metadata=fetched.metadata,
    )
    first = detect_static_pockets(
        prepared.prepared_path,
        prepared_sha256=prepared.prepared_sha256,
    )
    second = detect_static_pockets(
        prepared.prepared_path,
        prepared_sha256=prepared.prepared_sha256,
    )
    first_payload = [pocket.to_portable_dict() for pocket in first.pockets]
    second_payload = [pocket.to_portable_dict() for pocket in second.pockets]
    evaluator = adapt_biovoid_pockets(pdb_id, first_payload)

    assert first_payload == second_payload
    assert first.pockets
    assert evaluator.status == "completed"
    assert evaluator.schema_version == "pocket-evaluator-input-v1"
    assert len(evaluator.pockets) == len(first.pockets)

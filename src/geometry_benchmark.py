"""Synthetic reference benchmark for Phase 3 pocket-volume implementations."""

from __future__ import annotations

import tracemalloc
from dataclasses import asdict, dataclass
from typing import Callable

from .resources import get_process_memory_snapshot
from .static_detector import (
    Sphere,
    VolumeEstimate,
    exact_one_or_two_sphere_union_volume,
    sobol_union_volume,
    voxel_union_volume,
)

GEOMETRY_BENCHMARK_VERSION = "geometry-volume-benchmark-v1"


@dataclass(frozen=True)
class VolumeBenchmarkRow:
    case: str
    method: str
    method_parameter: str
    reference_volume: float
    measured_volume: float
    absolute_error: float
    relative_error: float
    runtime_seconds: float
    python_peak_allocated_bytes: int
    process_peak_rss_bytes: int


@dataclass(frozen=True)
class VolumeBenchmarkReport:
    schema_version: str
    rows: tuple[VolumeBenchmarkRow, ...]
    canonical_method: str
    canonical_decision: str

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "rows": [asdict(row) for row in self.rows],
            "canonical_method": self.canonical_method,
            "canonical_decision": self.canonical_decision,
        }


def _measure(
    case: str,
    method_parameter: str,
    reference: float,
    operation: Callable[[], VolumeEstimate],
) -> VolumeBenchmarkRow:
    tracemalloc.start()
    estimate = operation()
    _, peak_allocated = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    absolute_error = abs(estimate.volume - reference)
    memory = get_process_memory_snapshot()
    return VolumeBenchmarkRow(
        case=case,
        method=estimate.method,
        method_parameter=method_parameter,
        reference_volume=reference,
        measured_volume=estimate.volume,
        absolute_error=absolute_error,
        relative_error=absolute_error / reference,
        runtime_seconds=estimate.runtime_seconds,
        python_peak_allocated_bytes=peak_allocated,
        process_peak_rss_bytes=memory.peak_rss_bytes,
    )


def run_synthetic_volume_benchmark(
    *,
    voxel_spacings: tuple[float, ...] = (0.40, 0.20),
    sobol_sample_count: int = 65536,
) -> VolumeBenchmarkReport:
    """Compare both union-aware methods against analytic one/two-sphere cases."""
    cases = {
        "single_sphere": [Sphere((0.0, 0.0, 0.0), 2.0)],
        "disjoint_spheres": [
            Sphere((0.0, 0.0, 0.0), 1.3),
            Sphere((3.0, 0.0, 0.0), 1.0),
        ],
        "overlapping_spheres": [
            Sphere((0.0, 0.0, 0.0), 1.3),
            Sphere((1.0, 0.2, 0.0), 1.0),
        ],
    }
    rows: list[VolumeBenchmarkRow] = []
    for case, spheres in cases.items():
        reference = exact_one_or_two_sphere_union_volume(spheres)
        for spacing in voxel_spacings:
            rows.append(
                _measure(
                    case,
                    f"spacing={spacing}",
                    reference,
                    lambda spheres=spheres, spacing=spacing: voxel_union_volume(
                        spheres, spacing=spacing
                    ),
                )
            )
        rows.append(
            _measure(
                case,
                f"samples={sobol_sample_count}",
                reference,
                lambda spheres=spheres: sobol_union_volume(
                    spheres, sample_count=sobol_sample_count
                ),
            )
        )
    return VolumeBenchmarkReport(
        schema_version=GEOMETRY_BENCHMARK_VERSION,
        rows=tuple(rows),
        canonical_method="voxel_union_v1",
        canonical_decision=(
            "Deterministic voxel union is the recovery-v1 canonical method because it "
            "provides an explicit resolution and surface estimate. Sobol union remains "
            "an independent candidate/check; neither method implies biological validation."
        ),
    )

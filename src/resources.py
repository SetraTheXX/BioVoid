"""Conservative local resource policies for recovery workloads."""

from __future__ import annotations

import ctypes
from math import ceil, isfinite
import os
from dataclasses import dataclass

from ctypes import wintypes


class ResourceLimitError(RuntimeError):
    """Raised before a request exceeds the selected local resource profile."""


@dataclass(frozen=True)
class ProcessMemorySnapshot:
    current_rss_bytes: int
    peak_rss_bytes: int


def get_process_memory_snapshot() -> ProcessMemorySnapshot:
    """Measure current and peak resident process memory using the host OS."""
    if os.name == "nt":

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("page_fault_count", ctypes.c_ulong),
                ("peak_working_set_size", ctypes.c_size_t),
                ("working_set_size", ctypes.c_size_t),
                ("quota_peak_paged_pool_usage", ctypes.c_size_t),
                ("quota_paged_pool_usage", ctypes.c_size_t),
                ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
                ("quota_non_paged_pool_usage", ctypes.c_size_t),
                ("pagefile_usage", ctypes.c_size_t),
                ("peak_pagefile_usage", ctypes.c_size_t),
            ]

        # WinDLL is only exposed by ctypes on Windows; getattr keeps Linux CI
        # type-checking honest while preserving the Windows runtime path.
        win_dll = getattr(ctypes, "WinDLL", None)
        if win_dll is None:
            raise ResourceLimitError("Windows memory API is unavailable")
        kernel32 = win_dll("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.K32GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        kernel32.K32GetProcessMemoryInfo.restype = wintypes.BOOL

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(ProcessMemoryCounters)
        measured = kernel32.K32GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(),
            ctypes.byref(counters),
            counters.cb,
        )
        if not measured:
            raise ResourceLimitError("Unable to measure process memory")
        return ProcessMemorySnapshot(
            current_rss_bytes=int(counters.working_set_size),
            peak_rss_bytes=int(counters.peak_working_set_size),
        )

    try:
        resource_module = __import__("resource")

        getrusage = getattr(resource_module, "getrusage")
        rusage_self = getattr(resource_module, "RUSAGE_SELF")
        peak_rss = int(getrusage(rusage_self).ru_maxrss)
        uname = getattr(os, "uname")
        if uname().sysname != "Darwin":
            peak_rss *= 1024
        return ProcessMemorySnapshot(
            current_rss_bytes=peak_rss,
            peak_rss_bytes=peak_rss,
        )
    except (AttributeError, ImportError, OSError) as exc:
        raise ResourceLimitError("Unable to measure process memory") from exc


def estimate_hessian_bytes(atom_count: int, safety_factor: float = 2.5) -> int:
    """Estimate dense ANM Hessian/eigensolver memory with conservative overhead."""
    if atom_count <= 0:
        raise ResourceLimitError("atom_count must be positive")
    matrix_bytes = (3 * atom_count) ** 2 * 8
    return int(matrix_bytes * safety_factor)


def estimate_sparse_hessian_bytes(
    atom_count: int,
    *,
    estimated_neighbors: int = 64,
    safety_factor: float = 2.5,
) -> int:
    """Estimate CSR ANM Hessian memory without assuming a dense 3N x 3N matrix."""
    if atom_count <= 0:
        raise ResourceLimitError("atom_count must be positive")
    if estimated_neighbors < 1:
        raise ResourceLimitError("estimated_neighbors must be positive")

    degrees_of_freedom = 3 * atom_count
    nonzero_values = degrees_of_freedom * (3 * estimated_neighbors + 3)
    csr_bytes = nonzero_values * (8 + 4) + (degrees_of_freedom + 1) * 4
    eigensolver_workspace = degrees_of_freedom * 32 * 8
    return int((csr_bytes + eigensolver_workspace) * safety_factor)


def estimate_static_detector_bytes(
    atom_count: int,
    candidate_count: int,
    *,
    safety_factor: float = 2.5,
) -> int:
    """Conservatively estimate Voronoi/KD-tree and complete-linkage memory."""
    if atom_count <= 0:
        raise ResourceLimitError("atom_count must be positive")
    if candidate_count < 0:
        raise ResourceLimitError("candidate_count cannot be negative")
    atom_geometry = atom_count * 4096
    condensed_distances = candidate_count * max(0, candidate_count - 1) // 2 * 8
    candidate_geometry = candidate_count * 512
    return int((atom_geometry + condensed_distances + candidate_geometry) * safety_factor)


def get_available_memory_bytes() -> int:
    """Return currently available physical memory without a third-party dependency."""
    if os.name == "nt":

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        windll = getattr(ctypes, "windll", None)
        if windll is None or not windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise ResourceLimitError("Unable to measure available physical memory")
        return int(status.available_physical)

    sysconf = getattr(os, "sysconf")
    page_size = sysconf("SC_PAGE_SIZE")
    available_pages = sysconf("SC_AVPHYS_PAGES")
    return int(page_size * available_pages)


@dataclass(frozen=True)
class ResourceProfile:
    name: str
    soft_memory_budget_bytes: int
    minimum_available_memory_bytes: int
    max_heavy_jobs: int
    max_analysis_workers: int
    max_download_workers: int
    max_nma_atoms: int
    max_motion_modes: int
    max_samples_per_mode: int
    max_motion_samples: int
    max_static_atoms: int
    max_static_candidates: int
    static_candidate_estimate_multiplier: float = 4.0

    def validate_static_request(
        self,
        *,
        atom_count: int,
        available_memory_bytes: int,
        candidate_count: int | None = None,
    ) -> int:
        """Reject static jobs before Voronoi or clustering can exhaust local RAM."""
        if atom_count < 50 or atom_count > self.max_static_atoms:
            raise ResourceLimitError(
                f"{self.name} static detector allows 50-{self.max_static_atoms} protein atoms"
            )
        if not isfinite(self.static_candidate_estimate_multiplier) or (
            self.static_candidate_estimate_multiplier <= 0
        ):
            raise ResourceLimitError("static candidate estimate multiplier must be positive")
        estimated_candidates = (
            min(
                self.max_static_candidates,
                max(1, ceil(atom_count * self.static_candidate_estimate_multiplier)),
            )
            if candidate_count is None
            else candidate_count
        )
        if estimated_candidates > self.max_static_candidates:
            raise ResourceLimitError(
                f"{self.name} limits static candidate clustering to "
                f"{self.max_static_candidates} candidates"
            )
        estimated = estimate_static_detector_bytes(atom_count, estimated_candidates)
        if estimated > self.soft_memory_budget_bytes:
            raise ResourceLimitError(
                f"Estimated static detector memory {estimated} exceeds the soft process budget"
            )
        if available_memory_bytes < self.minimum_available_memory_bytes + estimated:
            raise ResourceLimitError("Insufficient available memory for a safe static detector job")
        return estimated

    def validate_request(
        self,
        *,
        atom_count: int,
        analysis_workers: int,
        available_memory_bytes: int,
    ) -> int:
        """Validate concurrency and memory before starting a heavy analysis."""
        if analysis_workers < 1 or analysis_workers > self.max_analysis_workers:
            raise ResourceLimitError(
                f"{self.name} allows 1-{self.max_analysis_workers} analysis workers"
            )
        if atom_count > self.max_nma_atoms:
            raise ResourceLimitError(f"{self.name} limits heavy NMA to {self.max_nma_atoms} atoms")
        estimated = estimate_hessian_bytes(atom_count)
        if estimated > self.soft_memory_budget_bytes:
            raise ResourceLimitError(
                f"Estimated Hessian memory {estimated} exceeds the soft process budget"
            )
        if available_memory_bytes < self.minimum_available_memory_bytes + estimated:
            raise ResourceLimitError("Insufficient available memory for a safe heavy job")
        return estimated

    def validate_motion_request(
        self,
        *,
        atom_count: int,
        samples_per_mode: int,
        mode_count: int,
        available_memory_bytes: int,
        solver: str = "auto",
    ) -> int:
        """Reject motion jobs that exceed memory or bounded ensemble sampling."""
        if samples_per_mode < 1 or samples_per_mode > self.max_samples_per_mode:
            raise ResourceLimitError(
                f"{self.name} allows 1-{self.max_samples_per_mode} samples per mode"
            )
        if mode_count < 1 or mode_count > self.max_motion_modes:
            raise ResourceLimitError(f"{self.name} allows 1-{self.max_motion_modes} motion modes")
        total_samples = samples_per_mode * mode_count
        if total_samples > self.max_motion_samples:
            raise ResourceLimitError(
                f"{self.name} limits a motion ensemble to {self.max_motion_samples} samples"
            )
        if atom_count > self.max_nma_atoms:
            raise ResourceLimitError(f"{self.name} limits heavy NMA to {self.max_nma_atoms} atoms")
        if solver not in {"auto", "dense", "sparse"}:
            raise ResourceLimitError("solver must be auto, dense, or sparse")

        use_sparse = solver == "sparse" or (solver == "auto" and atom_count >= 250)
        estimated = (
            estimate_sparse_hessian_bytes(atom_count)
            if use_sparse
            else estimate_hessian_bytes(atom_count)
        )
        if estimated > self.soft_memory_budget_bytes:
            raise ResourceLimitError(
                f"Estimated NMA memory {estimated} exceeds the soft process budget"
            )
        if available_memory_bytes < self.minimum_available_memory_bytes + estimated:
            raise ResourceLimitError("Insufficient available memory for a safe motion job")
        return estimated


SAFE_16GB = ResourceProfile(
    name="safe-16gb",
    soft_memory_budget_bytes=8 * 1024**3,
    minimum_available_memory_bytes=4 * 1024**3,
    max_heavy_jobs=1,
    max_analysis_workers=2,
    max_download_workers=6,
    max_nma_atoms=3500,
    max_motion_modes=12,
    max_samples_per_mode=8,
    max_motion_samples=64,
    max_static_atoms=5000,
    max_static_candidates=25000,
)


# This is an opt-in, secondary arm for structures blocked by the conservative
# primary profile. It remains single-process and is never used by NMA or the
# canonical product path. The subprocess runner adds an independent RSS cap.
RI3_STATIC_RECOVERY = ResourceProfile(
    name="ri3-static-recovery-v1",
    soft_memory_budget_bytes=3 * 1024**3,
    minimum_available_memory_bytes=3 * 1024**3,
    max_heavy_jobs=1,
    max_analysis_workers=1,
    max_download_workers=1,
    max_nma_atoms=3500,
    max_motion_modes=1,
    max_samples_per_mode=1,
    max_motion_samples=1,
    max_static_atoms=12500,
    max_static_candidates=14000,
    static_candidate_estimate_multiplier=1.5,
)

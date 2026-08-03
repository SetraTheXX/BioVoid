"""Run-scoped workspace and canonical input safety helpers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class RuntimeSafetyError(RuntimeError):
    """Base class for recovery runtime safety violations."""


class StaleFrameError(RuntimeSafetyError):
    """Raised when a frame directory contains files outside its manifest."""


class CanonicalInputError(RuntimeSafetyError):
    """Raised when an input cannot enter canonical pocket detection."""


@dataclass(frozen=True)
class RunWorkspace:
    """Identity and filesystem root for one isolated analysis run."""

    run_id: str
    path: Path


def create_run_workspace(root: str | Path, run_id: str | None = None) -> RunWorkspace:
    """Create a new, initially empty run directory without reusing an old path."""
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    identity = run_id or uuid.uuid4().hex
    workspace = root_path / identity
    try:
        workspace.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise RuntimeSafetyError(f"Run workspace already exists: {workspace}") from exc
    return RunWorkspace(run_id=identity, path=workspace)


def validate_frame_manifest(
    frames_dir: str | Path,
    expected_files: Iterable[str | Path],
) -> list[Path]:
    """Require the frame directory to match the explicit run manifest exactly."""
    root = Path(frames_dir).resolve()
    expected = {Path(path).resolve() for path in expected_files}
    outside = [path for path in expected if not path.is_relative_to(root)]
    if outside:
        raise StaleFrameError(f"Frame manifest contains files outside run workspace: {outside}")

    missing = sorted(path for path in expected if not path.is_file())
    actual = {path.resolve() for path in root.glob("frame_*.pdb")} if root.exists() else set()
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        raise StaleFrameError(
            f"Frame manifest mismatch: missing={missing}, unexpected={unexpected}"
        )
    return sorted(expected)


def require_full_atom_structure(pdb_path: str | Path) -> dict[str, int]:
    """Reject C-alpha-only PDB input before canonical pocket detection begins."""
    path = Path(pdb_path)
    atom_names: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("ATOM  "):
                atom_name = line[12:16].strip().upper()
                if atom_name:
                    atom_names.append(atom_name)

    if not atom_names:
        raise CanonicalInputError(f"No protein ATOM records found in {path}")

    ca_count = sum(name == "CA" for name in atom_names)
    non_ca_count = len(atom_names) - ca_count
    if ca_count and non_ca_count == 0:
        raise CanonicalInputError(
            "C-alpha-only input is not accepted for canonical pocket detection."
        )
    if not {"N", "C", "O"}.issubset(set(atom_names)):
        raise CanonicalInputError(
            "Canonical pocket detection requires prepared full-atom backbone records."
        )

    return {
        "atom_count": len(atom_names),
        "ca_count": ca_count,
        "non_ca_count": non_ca_count,
    }

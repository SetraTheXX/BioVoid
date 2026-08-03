"""Run one bounded RCSB/mmCIF -> preparation -> static detector smoke check."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fetcher import fetch_structure_input
from src.resources import ResourceProfile
from src.static_detector import detect_static_pockets
from src.structure_preparation import (
    PreparationConfig,
    StructureSource,
    load_structure_atoms,
    prepare_structure,
)

SMOKE_STATIC_PROFILE = ResourceProfile(
    name="bounded-rcsb-smoke-v1",
    soft_memory_budget_bytes=512 * 1024**2,
    minimum_available_memory_bytes=0,
    max_heavy_jobs=1,
    max_analysis_workers=1,
    max_download_workers=1,
    max_nma_atoms=1000,
    max_motion_modes=1,
    max_samples_per_mode=1,
    max_motion_samples=1,
    max_static_atoms=1000,
    max_static_candidates=4000,
)


def _run_smoke(
    pdb_id: str,
    *,
    output_root: Path,
    representation: str,
    assembly_id: str | None,
) -> dict[str, Any]:
    source = StructureSource(
        provider="rcsb",
        identifier=pdb_id,
        representation=representation,
        assembly_id=assembly_id,
    )
    cache_dir = output_root / "source-cache"
    fetched = fetch_structure_input(source, cache_dir=cache_dir)
    if fetched.path.suffix.lower() not in {".cif", ".mmcif"}:
        raise RuntimeError(f"Expected an mmCIF file, received {fetched.path.name}")

    input_atoms = load_structure_atoms(fetched.path)
    run_dir = output_root / f"run-{uuid.uuid4().hex[:10]}"
    preparation = prepare_structure(
        fetched.path,
        source,
        PreparationConfig(),
        run_dir,
        run_id=f"smoke-{source.identifier.lower()}",
        source_metadata=fetched.metadata,
        analysis_config={"purpose": "bounded_rcsb_smoke"},
    )
    detection = detect_static_pockets(
        preparation.prepared_path,
        prepared_sha256=preparation.prepared_sha256,
        resource_profile=SMOKE_STATIC_PROFILE,
    )

    return {
        "status": "ok",
        "pdb_id": source.identifier,
        "representation": source.representation,
        "input_format": fetched.path.suffix.lower().lstrip("."),
        "input_atom_count": len(input_atoms),
        "prepared_sha256": preparation.prepared_sha256,
        "protein_atom_count": detection.protein_atom_count,
        "candidate_count": detection.candidate_count,
        "pocket_count": len(detection.pockets),
        "detector_version": detection.detector_version,
        "resource_profile": SMOKE_STATIC_PROFILE.name,
        "warnings": list(detection.warnings),
        "output_retained": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one bounded RCSB/mmCIF preparation and static detector smoke check."
    )
    parser.add_argument("--pdb-id", default="1CRN", help="Four-character RCSB identifier")
    parser.add_argument(
        "--representation",
        choices=("asymmetric_unit", "biological_assembly"),
        default="asymmetric_unit",
    )
    parser.add_argument("--assembly-id", default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional local output root; keep it outside the repository tree",
    )
    args = parser.parse_args()

    try:
        if args.output_dir is None:
            with tempfile.TemporaryDirectory(prefix="biovoid-rcsb-smoke-") as temporary:
                summary = _run_smoke(
                    args.pdb_id,
                    output_root=Path(temporary),
                    representation=args.representation,
                    assembly_id=args.assembly_id,
                )
                summary["output_retained"] = False
        else:
            output_root = args.output_dir.resolve()
            output_root.mkdir(parents=True, exist_ok=True)
            summary = _run_smoke(
                args.pdb_id,
                output_root=output_root,
                representation=args.representation,
                assembly_id=args.assembly_id,
            )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    except Exception as exc:  # pragma: no cover - CLI failure boundary
        print(f"RCSB smoke check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

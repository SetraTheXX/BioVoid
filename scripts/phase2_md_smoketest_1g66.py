#!/usr/bin/env python3
"""1G66 için kısa OpenMM smoke-test koşusu.

Amaç:
- Verilen PDB dosyasını okuyup OpenMM context açılabilirliğini doğrulamak
- Çok kısa bir MD entegrasyonu (varsayılan 5000 adım) çalıştırmak
- Kısa log ve artefakt üretmek (CSV + final PDB + JSON özet)

Not:
- Bu script bilimsel üretim MD değildir; yalnızca çalıştırılabilirlik smoke-test'idir.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import openmm as mm
import openmm.unit as unit
from openmm.app import PDBFile, Simulation, StateDataReporter


def _to_kj_per_mol(value):
    return value.value_in_unit(unit.kilojoule_per_mole)


def _build_smoke_system(pdb: PDBFile) -> mm.System:
    """Topolojiden bağımsız, stabil bir smoke-test sistemi kur.

    Her atom için bir parçacık eklenir ve başlangıç koordinatına harmonik restrain uygulanır.
    Böylece parametrizasyon/forcefield bağımlılığı olmadan entegrasyon smoke-test yapılır.
    """
    system = mm.System()

    restraint = mm.CustomExternalForce("k*((x-x0)^2 + (y-y0)^2 + (z-z0)^2)")
    restraint.addGlobalParameter("k", 1000.0 * unit.kilojoule_per_mole / unit.nanometer**2)
    restraint.addPerParticleParameter("x0")
    restraint.addPerParticleParameter("y0")
    restraint.addPerParticleParameter("z0")

    for atom, pos in zip(pdb.topology.atoms(), pdb.positions):
        if atom.element is not None:
            mass = atom.element.mass
        else:
            mass = 12.0 * unit.amu

        system.addParticle(mass)
        pos_nm = pos.value_in_unit(unit.nanometer)
        xyz = [float(pos_nm[0]), float(pos_nm[1]), float(pos_nm[2])]
        restraint.addParticle(system.getNumParticles() - 1, xyz)

    system.addForce(restraint)
    return system


def run_smoketest(
    input_pdb: Path,
    platform_name: str,
    steps: int,
    output_dir: Path,
    report_interval: int,
) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)

    pdb = PDBFile(str(input_pdb))
    system = _build_smoke_system(pdb)

    integrator = mm.LangevinMiddleIntegrator(
        300.0 * unit.kelvin,
        1.0 / unit.picosecond,
        0.002 * unit.picoseconds,
    )

    platform = mm.Platform.getPlatformByName(platform_name)
    simulation = Simulation(pdb.topology, system, integrator, platform)
    simulation.context.setPositions(pdb.positions)
    simulation.context.setVelocitiesToTemperature(300.0 * unit.kelvin)

    csv_path = output_dir / "md_smoke_1g66_log.csv"
    final_pdb_path = output_dir / "md_smoke_1g66_final.pdb"
    summary_json_path = output_dir / "md_smoke_1g66_summary.json"

    simulation.reporters.append(
        StateDataReporter(
            str(csv_path),
            reportInterval=max(1, report_interval),
            step=True,
            potentialEnergy=True,
            kineticEnergy=True,
            totalEnergy=True,
            temperature=True,
            progress=True,
            remainingTime=True,
            speed=True,
            totalSteps=steps,
            separator=",",
        )
    )

    pre = simulation.context.getState(getEnergy=True)
    pre_pe = _to_kj_per_mol(pre.getPotentialEnergy())

    simulation.step(steps)

    post = simulation.context.getState(getEnergy=True, getPositions=True)
    post_pe = _to_kj_per_mol(post.getPotentialEnergy())

    with final_pdb_path.open("w", encoding="utf-8") as handle:
        PDBFile.writeFile(simulation.topology, post.getPositions(), handle)

    summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "input_pdb": str(input_pdb),
        "platform": platform_name,
        "steps": steps,
        "atoms": pdb.topology.getNumAtoms(),
        "residues": pdb.topology.getNumResidues(),
        "initial_potential_energy_kj_per_mol": pre_pe,
        "final_potential_energy_kj_per_mol": post_pe,
        "csv_log": str(csv_path),
        "final_pdb": str(final_pdb_path),
    }
    summary_json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("SMOKE_TEST_OK")
    print(f"input={input_pdb}")
    print(f"platform={platform_name}")
    print(f"steps={steps}")
    print(f"atoms={summary['atoms']} residues={summary['residues']}")
    print(f"initial_PE_kJmol={pre_pe:.6f} final_PE_kJmol={post_pe:.6f}")
    print(f"csv_log={csv_path}")
    print(f"final_pdb={final_pdb_path}")
    print(f"summary_json={summary_json_path}")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="1G66 OpenMM MD smoke-test")
    parser.add_argument("--input", required=True, help="Giriş PDB dosya yolu")
    parser.add_argument(
        "--platform",
        default="OpenCL",
        choices=["OpenCL", "CPU"],
        help="OpenMM platformu",
    )
    parser.add_argument("--steps", type=int, default=5000, help="MD adım sayısı")
    parser.add_argument(
        "--output-dir",
        default="BioVoid/data/md_smoke/1g66",
        help="Çıktı dizini",
    )
    parser.add_argument(
        "--report-interval",
        type=int,
        default=500,
        help="CSV rapor intervali (adım)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_pdb = Path(args.input)
    if not input_pdb.exists():
        print(f"ERROR: input PDB not found: {input_pdb}", file=sys.stderr)
        return 2

    if args.steps <= 0:
        print("ERROR: --steps must be > 0", file=sys.stderr)
        return 2

    try:
        return run_smoketest(
            input_pdb=input_pdb,
            platform_name=args.platform,
            steps=args.steps,
            output_dir=Path(args.output_dir),
            report_interval=args.report_interval,
        )
    except Exception as exc:  # pragma: no cover - smoke test runtime guard
        print(f"SMOKE_TEST_FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

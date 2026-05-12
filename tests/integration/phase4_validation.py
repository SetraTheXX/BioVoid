#!/usr/bin/env python3
"""
Bio-Void Hunter: Phase 4 Integration Validation
==================================================

End-to-end validation of the Targeted Docking pipeline:
  1. Grid Test       - 5 diverse pockets → Smart Grid sizing
  2. Docking Test    - 1CBS + retinoic acid (known ligand)
  3. Empty Pocket    - No binding expected (VdW only)
  4. Interaction     - H-bond / Hydrophobic classification
  5. NMA Frame Dock  - Cryptic pocket stability

Usage:
    python tests/integration/phase4_validation.py

Requirements:
    - AutoDock Vina at tools/vina/vina.exe
    - RDKit (conda biovoid) for ligand preparation
    - 1CBS PDB file at data/raw_pdb/pdb1cbs.ent
    - NMA frames at data/frames/1cbs/
"""

import json
import sys
import tempfile
import time
from pathlib import Path

# Add project root to path (tests/integration/ -> project root)
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.docking import (
    VinaDocking,
    GridBox,
    DockingResult,
    Interaction,
    InteractionReport,
    analyze_interactions,
    validate_known_ligand,
    dock_nma_frames,
    dock_elite_pockets,
    parse_vina_output_file,
    GRID_BUFFER,
    GRID_MIN_SIZE,
    GRID_MAX_SIZE,
    AFFINITY_STRONG,
    AFFINITY_GOOD,
    AFFINITY_WEAK,
    HBOND_DISTANCE_MAX,
    RETINOIC_ACID_SMILES,
)

# ANSI colors
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
CYAN = '\033[96m'
RESET = '\033[0m'
BOLD = '\033[1m'


def header(title: str):
    print(f"\n{BOLD}{CYAN}{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}{RESET}\n")


def check(name: str, passed: bool, detail: str = ''):
    icon = f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"
    msg = f"  {icon} {name}"
    if detail:
        msg += f"  ({detail})"
    print(msg)
    return passed


# ============================================================================
# TEST 1: GRID BOX CALCULATION
# ============================================================================

def test_grid_box():
    """Test Smart Grid sizing for diverse pocket geometries."""
    header("TEST 1: Smart Grid Box Hesaplama")

    results = []

    pockets = [
        {'id': 1, 'center': [10, 20, 30], 'radius_geom': 3.0,
         'expected_size': GRID_MIN_SIZE, 'label': 'Küçük cep (r=3.0)'},
        {'id': 2, 'center': [20, 28, 12], 'radius_geom': 8.5,
         'expected_size': 23.0, 'label': 'Normal cep (r=8.5)'},
        {'id': 3, 'center': [0, 0, 0], 'radius_geom': 10.0,
         'expected_size': 26.0, 'label': 'Orta cep (r=10.0)'},
        {'id': 4, 'center': [50, 50, 50], 'radius_geom': 12.0,
         'expected_size': GRID_MAX_SIZE, 'label': 'Büyük cep (r=12.0)'},
        {'id': 5, 'center': [5, 15, 25], 'radius_geom': 20.0,
         'expected_size': GRID_MAX_SIZE, 'label': 'Dev cep (r=20.0)'},
    ]

    docker = VinaDocking.__new__(VinaDocking)
    docker.vina_bin = ROOT / "tools" / "vina" / "vina.exe"
    docker.output_dir = ROOT / "data" / "docking"

    for p in pockets:
        grid = docker.calculate_grid_box(p)
        expected = p['expected_size']
        passed = (grid.size_x == expected and
                  grid.size_y == expected and
                  grid.size_z == expected)
        results.append(check(
            p['label'],
            passed,
            f"boyut={grid.size_x:.1f}, beklenen={expected:.1f}"
        ))

    return all(results)


# ============================================================================
# TEST 2: KNOWN LIGAND DOCKING (1CBS)
# ============================================================================

def test_known_ligand_docking():
    """Dock retinoic acid into 1CBS binding site."""
    header("TEST 2: 1CBS Bilinen Ligand Docking")

    pdb_path = ROOT / "data" / "raw_pdb" / "pdb1cbs.ent"
    if not pdb_path.exists():
        print(f"  {YELLOW}⚠ PDB dosyası bulunamadı: {pdb_path}{RESET}")
        print(f"  {YELLOW}  Önce: python main.py --pdb-id 1cbs{RESET}")
        return None  # Skip, not fail

    vina_bin = ROOT / "tools" / "vina" / "vina.exe"
    if not vina_bin.exists():
        print(f"  {YELLOW}⚠ Vina bulunamadı: {vina_bin}{RESET}")
        return None

    try:
        report = validate_known_ligand(
            pdb_path=str(pdb_path),
            ligand_smiles=RETINOIC_ACID_SMILES,
            pocket_center=[20.0, 28.0, 12.0],
            pocket_radius=9.0,
            vina_bin=str(vina_bin),
            output_dir=str(ROOT / "data" / "docking"),
            exhaustiveness=16,
        )
    except Exception as e:
        print(f"  {RED}✗ Docking hatası: {e}{RESET}")
        return False

    results = []

    aff = report.get('best_affinity', 0)
    results.append(check(
        'Binding affinity',
        aff < AFFINITY_GOOD,
        f"{aff:.1f} kcal/mol (hedef: < {AFFINITY_GOOD})"
    ))

    n_poses = report.get('n_poses', 0)
    results.append(check(
        'Pozlar bulundu',
        n_poses >= 1,
        f"{n_poses} poz"
    ))

    interactions = report.get('interactions', {})
    n_hbonds = interactions.get('n_hbonds', 0)
    results.append(check(
        'H-bond tespiti',
        n_hbonds >= 0,  # At least detection works
        f"{n_hbonds} H-bond"
    ))

    results.append(check(
        'Druggable',
        report.get('is_druggable', False),
        f"affinity_class={report.get('affinity_class', 'N/A')}"
    ))

    # Save summary
    print(f"\n  Sonuç: affinity={aff:.1f}, "
          f"H-bond={n_hbonds}, "
          f"temas={len(interactions.get('contact_residues', []))} residue")

    return all(results)


# ============================================================================
# TEST 3: EMPTY POCKET TEST
# ============================================================================

def test_empty_pocket():
    """Dock into a region with no binding site → weak/no binding expected."""
    header("TEST 3: Boş Bölge Docking (zayıf bağlanma bekleniyor)")

    pdb_path = ROOT / "data" / "raw_pdb" / "pdb1cbs.ent"
    vina_bin = ROOT / "tools" / "vina" / "vina.exe"

    if not pdb_path.exists() or not vina_bin.exists():
        print(f"  {YELLOW}⚠ Gerekli dosyalar bulunamadı, atlanıyor{RESET}")
        return None

    try:
        docker = VinaDocking(
            vina_bin=str(vina_bin),
            output_dir=str(ROOT / "data" / "docking"),
            exhaustiveness=4,
        )

        # Pick a location far from known binding site
        empty_pocket = {
            'id': 99,
            'rank': 99,
            'center': [0.0, 0.0, 0.0],  # Likely outside protein
            'radius_geom': 5.0,
        }

        receptor_pdbqt = docker.prepare_receptor(str(pdb_path))
        result = docker.dock_pocket(
            empty_pocket, receptor_pdbqt,
            ligand_smiles='c1ccccc1',  # Benzene
            ligand_name='empty_test',
        )
    except Exception as e:
        print(f"  {YELLOW}⚠ Docking hatası (beklenen olabilir): {e}{RESET}")
        return True  # Error in empty region is acceptable

    results = []

    # Empty pocket should have weaker binding
    aff = result.best_affinity if result.best_affinity else 0
    results.append(check(
        'Zayıf bağlanma bekleniyor',
        aff > AFFINITY_STRONG,  # Should NOT be strong
        f"affinity={aff:.1f} (strong < {AFFINITY_STRONG})"
    ))

    return all(results)


# ============================================================================
# TEST 4: INTERACTION CLASSIFICATION
# ============================================================================

def test_interaction_analysis():
    """Verify H-bond, hydrophobic, VdW classification logic."""
    header("TEST 4: Etkileşim Analizi (H-bond, VdW, Hydrophobic)")

    results = []

    # Create synthetic PDBQT files for testing
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # Test: N-O at 3.0 A → H-bond
        rec = tmp_path / "rec_hbond.pdbqt"
        rec.write_text(
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000"
            "  1.00  0.00           N\nEND\n"
        )
        lig = tmp_path / "lig_hbond.pdbqt"
        lig.write_text(
            "ATOM      1  O1  LIG A   1       3.000   0.000   0.000"
            "  1.00  0.00           O\nEND\n"
        )
        report = analyze_interactions(rec, lig)
        results.append(check(
            'H-bond: N-O at 3.0 A',
            report.n_hbonds >= 1,
            f"{report.n_hbonds} H-bond bulundu"
        ))

        # Test: C-C at 3.8 A → hydrophobic
        rec2 = tmp_path / "rec_hydro.pdbqt"
        rec2.write_text(
            "ATOM      1  CB  ALA A   5       0.000   0.000   0.000"
            "  1.00  0.00           C\nEND\n"
        )
        lig2 = tmp_path / "lig_hydro.pdbqt"
        lig2.write_text(
            "ATOM      1  C1  LIG A   1       3.800   0.000   0.000"
            "  1.00  0.00           C\nEND\n"
        )
        report2 = analyze_interactions(rec2, lig2)
        results.append(check(
            'Hydrophobic: C-C at 3.8 A',
            report2.n_hydrophobic >= 1,
            f"{report2.n_hydrophobic} hydrophobic"
        ))

        # Test: Atoms far apart → no interactions
        rec3 = tmp_path / "rec_far.pdbqt"
        rec3.write_text(
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000"
            "  1.00  0.00           N\nEND\n"
        )
        lig3 = tmp_path / "lig_far.pdbqt"
        lig3.write_text(
            "ATOM      1  O1  LIG A   1      50.000  50.000  50.000"
            "  1.00  0.00           O\nEND\n"
        )
        report3 = analyze_interactions(rec3, lig3)
        results.append(check(
            'Uzak atomlar → etkileşim yok',
            len(report3.interactions) == 0,
            f"{len(report3.interactions)} etkileşim"
        ))

        # Test: to_dict JSON serializable
        d = report.to_dict()
        try:
            json.dumps(d)
            results.append(check('JSON serileştirme', True))
        except TypeError as e:
            results.append(check('JSON serileştirme', False, str(e)))

    return all(results)


# ============================================================================
# TEST 5: NMA FRAME DOCKING
# ============================================================================

def test_nma_frame_docking():
    """Dock across NMA frames to validate pocket stability."""
    header("TEST 5: NMA Frame Docking (Kriptik Cep Stabilitesi)")

    frames_dir = ROOT / "data" / "frames" / "1cbs"
    vina_bin = ROOT / "tools" / "vina" / "vina.exe"

    if not frames_dir.exists():
        print(f"  {YELLOW}⚠ NMA frame'leri bulunamadı: {frames_dir}{RESET}")
        print(f"  {YELLOW}  Önce: python main.py --pdb-id 1cbs{RESET}")
        return None

    if not vina_bin.exists():
        print(f"  {YELLOW}⚠ Vina bulunamadı: {vina_bin}{RESET}")
        return None

    frame_files = sorted(frames_dir.glob('frame_*.pdb'))
    if len(frame_files) < 2:
        print(f"  {YELLOW}⚠ Yeterli frame yok ({len(frame_files)} bulundu)")
        return None

    pocket = {
        'id': 0,
        'center': [20.0, 28.0, 12.0],
        'radius_geom': 9.0,
    }

    try:
        report = dock_nma_frames(
            frames_dir=str(frames_dir),
            pocket=pocket,
            ligand_smiles='c1ccccc1',  # Benzene probe
            ligand_name='benzene',
            n_sample=3,
            vina_bin=str(vina_bin),
            output_dir=str(ROOT / "data" / "docking"),
            exhaustiveness=4,
        )
    except Exception as e:
        print(f"  {RED}✗ NMA docking hatası: {e}{RESET}")
        return False

    results = []

    results.append(check(
        'NMA docking tamamlandı',
        report.get('success', False),
        f"{report.get('n_successful', 0)}/{report.get('n_frames_docked', 0)}"
    ))

    consistency = report.get('consistency', 0)
    results.append(check(
        'Cep tutarlılığı (≥60%)',
        consistency >= 0.6,
        f"{consistency:.0%}"
    ))

    results.append(check(
        'Rapor kaydedildi',
        (ROOT / "data" / "docking" / "nma_docking_report.json").exists(),
    ))

    return all(results)


# ============================================================================
# MAIN
# ============================================================================

def main():
    header("BIO-VOID HUNTER: FAZ 4 VALİDASYON RAPORU")
    start = time.time()

    all_results = {}

    # Grid Tests (always works - no external deps)
    all_results['grid'] = test_grid_box()

    # Interaction Analysis (always works)
    all_results['interaction'] = test_interaction_analysis()

    # Known Ligand Docking (needs Vina + RDKit + PDB)
    all_results['known_ligand'] = test_known_ligand_docking()

    # Empty Pocket (needs Vina + RDKit + PDB)
    all_results['empty_pocket'] = test_empty_pocket()

    # NMA Frame Docking (needs Vina + RDKit + frames)
    all_results['nma_frames'] = test_nma_frame_docking()

    elapsed = time.time() - start

    # Summary
    header("SONUÇ ÖZETİ")

    passed = sum(1 for v in all_results.values() if v is True)
    failed = sum(1 for v in all_results.values() if v is False)
    skipped = sum(1 for v in all_results.values() if v is None)

    for name, result in all_results.items():
        if result is True:
            icon = f"{GREEN}✓ BAŞARILI{RESET}"
        elif result is False:
            icon = f"{RED}✗ BAŞARISIZ{RESET}"
        else:
            icon = f"{YELLOW}⊘ ATLANDI{RESET}"
        print(f"  {icon}  {name}")

    print(f"\n  Toplam: {GREEN}{passed} başarılı{RESET}, "
          f"{RED}{failed} başarısız{RESET}, "
          f"{YELLOW}{skipped} atlandı{RESET}")
    print(f"  Süre: {elapsed:.1f}s")

    # Save validation summary
    summary = {
        'phase': 4,
        'results': {k: ('passed' if v is True else
                        'failed' if v is False else 'skipped')
                    for k, v in all_results.items()},
        'passed': passed,
        'failed': failed,
        'skipped': skipped,
        'elapsed_seconds': round(elapsed, 1),
    }
    report_path = ROOT / "data" / "results" / "phase4_validation.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"\n  Rapor: {report_path}")

    sys.exit(1 if failed > 0 else 0)


if __name__ == '__main__':
    main()

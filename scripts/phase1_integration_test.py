"""
Bio-Void Hunter: Phase 1 Integration Test (FINAL CHALLENGE)
============================================================
Bu test, Faz 1'in tüm bileşenlerini gerçek bir protein üzerinde test eder.

Test Akışı:
1. Büyük bir proteini indir (1AKE - ~3800 atom)
2. NMA ile titreşim modlarını hesapla
3. Her modda Voronoi ile boşlukları tara
4. PyMOL ile görselleştir
5. Performans ölç (Hedef: < 30 saniye)

Başarı Kriterleri:
- ✅ 3000+ atom işlenebilmeli
- ✅ 10+ titreşim modu hesaplanmalı
- ✅ Her modda 50+ boşluk bulunmalı
- ✅ Toplam süre < 30 saniye
- ✅ PyMOL görseli oluşturulmalı

Referanslar:
- NMA: Bahar et al. (1997) - Anisotropic Network Model
- Voronoi: Liang et al. (1998) - Analytical Molecular Surface
"""

import sys
import time
import numpy as np
from pathlib import Path
from scipy.spatial import Voronoi, ConvexHull
import biotite.structure.io.pdb as pdb
import biotite.database.rcsb as rcsb

# Proje dizinleri
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RESULTS_DIR = DATA_DIR / "results"
PDB_DIR = DATA_DIR / "raw_pdb"

# Klasörleri oluştur
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
PDB_DIR.mkdir(parents=True, exist_ok=True)

# Test parametreleri
TEST_PDB_ID = "1ake"  # Adenylate Kinase - ~3800 atom
NUM_MODES = 10  # Hesaplanacak titreşim modu sayısı
MIN_VOIDS_PER_MODE = 50  # Her modda bulunması gereken minimum boşluk
MAX_TOTAL_TIME = 30  # Maksimum toplam süre (saniye)

class IntegrationTestResults:
    """Test sonuçlarını saklayan sınıf"""
    def __init__(self):
        self.pdb_id = TEST_PDB_ID
        self.atom_count = 0
        self.download_time = 0
        self.nma_time = 0
        self.voronoi_time = 0
        self.visualization_time = 0
        self.total_time = 0
        self.modes_calculated = 0
        self.voids_found = []
        self.success = False
        self.errors = []

def download_protein():
    """1. Proteini indir ve yükle"""
    print("\n" + "="*60)
    print("🧬 FAZ 1 ENTEGRASYON TESTİ - BAŞLANGIÇ")
    print("="*60)
    print(f"\n1️⃣ PROTEİN İNDİRME: {TEST_PDB_ID.upper()}")
    
    start = time.time()
    
    # PDB dosyasını indir
    pdb_file = PDB_DIR / f"{TEST_PDB_ID}.pdb"
    
    if not pdb_file.exists():
        print(f"   📥 İndiriliyor: {TEST_PDB_ID.upper()}")
        file_path = rcsb.fetch(TEST_PDB_ID, "pdb", target_path=str(PDB_DIR))
        print(f"   ✅ İndirildi: {file_path}")
    else:
        print(f"   ✅ Zaten mevcut: {pdb_file}")
    
    # PDB dosyasını yükle
    pdb_file_obj = pdb.PDBFile.read(str(pdb_file))
    structure = pdb_file_obj.get_structure()[0]  # İlk model
    
    # Sadece CA atomlarını al (NMA için)
    ca_atoms = structure[structure.atom_name == "CA"]
    
    elapsed = time.time() - start
    
    print(f"\n   📊 Protein Bilgileri:")
    print(f"      • Toplam atom: {len(structure)}")
    print(f"      • CA atomları: {len(ca_atoms)}")
    print(f"      • Süre: {elapsed:.4f} saniye")
    
    return ca_atoms, elapsed

def calculate_nma(ca_atoms):
    """2. NMA ile titreşim modlarını hesapla"""
    print(f"\n2️⃣ NMA TİTREŞİM HESAPLAMA:")
    print(f"   🎯 Hedef: {NUM_MODES} mod hesapla")
    
    start = time.time()
    
    # Koordinatları al
    coords = ca_atoms.coord
    n_atoms = len(coords)
    
    print(f"   ⚙️ Hessian matrisi oluşturuluyor ({n_atoms}x{n_atoms})...")
    
    # Hessian matrisi (ANM/GNM yaklaşımı)
    cutoff = 15.0  # Angstrom
    hessian = np.zeros((n_atoms, n_atoms))
    
    for i in range(n_atoms):
        for j in range(i + 1, n_atoms):
            dist = np.linalg.norm(coords[i] - coords[j])
            if dist < cutoff:
                hessian[i, j] = -1.0
                hessian[j, i] = -1.0
                hessian[i, i] += 1.0
                hessian[j, j] += 1.0
    
    print(f"   ⚙️ Eigendecomposition yapılıyor...")
    
    # Özdeğer ve özvektörleri hesapla
    eigenvalues, eigenvectors = np.linalg.eigh(hessian)
    
    # İlk 6 mod trivial (sıfıra yakın), gerçek modlar 7'den başlar
    modes = eigenvectors[:, 6:6+NUM_MODES]
    frequencies = np.sqrt(np.abs(eigenvalues[6:6+NUM_MODES]))
    
    elapsed = time.time() - start
    
    print(f"\n   ✅ NMA Tamamlandı:")
    print(f"      • Hesaplanan mod: {NUM_MODES}")
    print(f"      • Frekans aralığı: {frequencies.min():.4f} - {frequencies.max():.4f}")
    print(f"      • Süre: {elapsed:.4f} saniye")
    
    return coords, modes, frequencies, elapsed

def generate_conformations(coords, modes, num_frames=5, amplitude=3.0):
    """3. Her mod için farklı konformasyonlar üret"""
    print(f"\n3️⃣ KONFORMASYON ÜRETME:")
    print(f"   🎯 Her mod için {num_frames} frame")
    
    conformations = []
    
    for mode_idx in range(modes.shape[1]):
        mode = modes[:, mode_idx]
        
        for frame in range(num_frames):
            # Sinüzoidal hareket
            t = (frame / num_frames) * 2 * np.pi
            displacement = amplitude * np.sin(t) * mode.reshape(-1, 1) * np.array([1, 1, 1])
            new_coords = coords + displacement
            conformations.append(new_coords)
    
    print(f"   ✅ {len(conformations)} konformasyon oluşturuldu")
    return conformations

def scan_voids_all_conformations(conformations):
    """4. Tüm konformasyonlarda Voronoi ile boşlukları tara"""
    print(f"\n4️⃣ VORONOİ BOŞLUK TARAMASI:")
    print(f"   🎯 {len(conformations)} konformasyon taranacak")
    
    start = time.time()
    
    all_voids = []
    
    for conf_idx, coords in enumerate(conformations):
        try:
            # Voronoi diyagramı oluştur
            vor = Voronoi(coords)
            
            # ConvexHull (yüzey kontrolü için)
            hull = ConvexHull(coords)
            hull_points = set(hull.vertices)
            
            # Boşlukları filtrele
            valid_voids = []
            
            for vertex_idx, vertex in enumerate(vor.vertices):
                # Yüzey kontrolü
                if vertex_idx in hull_points:
                    continue
                
                # En yakın atoma mesafe
                distances = np.linalg.norm(coords - vertex, axis=1)
                min_dist = distances.min()
                
                # Mesafe filtresi (2.5 - 8.0 Angstrom)
                if 2.5 <= min_dist <= 8.0:
                    # Hacim tahmini (küre yaklaşımı)
                    volume = (4/3) * np.pi * (min_dist ** 3)
                    valid_voids.append({
                        'position': vertex,
                        'radius': min_dist,
                        'volume': volume
                    })
            
            all_voids.append(valid_voids)
            
            if (conf_idx + 1) % 10 == 0:
                print(f"   ⚙️ {conf_idx + 1}/{len(conformations)} tamamlandı...")
        
        except Exception as e:
            print(f"   ⚠️ Konformasyon {conf_idx} hatası: {e}")
            all_voids.append([])
    
    elapsed = time.time() - start
    
    # İstatistikler
    void_counts = [len(voids) for voids in all_voids]
    total_voids = sum(void_counts)
    avg_voids = np.mean(void_counts)
    
    print(f"\n   ✅ Voronoi Taraması Tamamlandı:")
    print(f"      • Toplam boşluk: {total_voids}")
    print(f"      • Ortalama/konformasyon: {avg_voids:.1f}")
    print(f"      • Min/Max: {min(void_counts)} / {max(void_counts)}")
    print(f"      • Süre: {elapsed:.4f} saniye")
    
    return all_voids, elapsed

def visualize_results(coords, all_voids):
    """5. PyMOL ile sonuçları görselleştir"""
    print(f"\n5️⃣ PYMOL GÖRSELLEŞTİRME:")
    
    start = time.time()
    
    try:
        import pymol
        
        # PyMOL'ü başlat (headless)
        pymol.finish_launching(['pymol', '-c'])
        
        # Proteini yükle (ilk konformasyon)
        pymol.cmd.delete('all')
        
        # CA atomlarını göster
        for i, coord in enumerate(coords):
            pymol.cmd.pseudoatom(f'protein', pos=coord.tolist(), name=f'CA{i}')
        
        pymol.cmd.show('spheres', 'protein')
        pymol.cmd.color('cyan', 'protein')
        pymol.cmd.set('sphere_scale', 0.5)
        
        # En büyük 20 boşluğu göster (tüm konformasyonlardan)
        all_voids_flat = []
        for voids in all_voids:
            all_voids_flat.extend(voids)
        
        # Hacme göre sırala
        all_voids_flat.sort(key=lambda v: v['volume'], reverse=True)
        top_voids = all_voids_flat[:20]
        
        for i, void in enumerate(top_voids):
            pos = void['position']
            radius = void['radius']
            pymol.cmd.pseudoatom(f'void_{i}', pos=pos.tolist())
            pymol.cmd.show('spheres', f'void_{i}')
            pymol.cmd.color('red', f'void_{i}')
            pymol.cmd.set('sphere_scale', radius * 0.3, f'void_{i}')
        
        # Görünüm ayarları
        pymol.cmd.bg_color('white')
        pymol.cmd.orient()
        pymol.cmd.zoom('all', buffer=5)
        
        # Render ve kaydet
        output_path = RESULTS_DIR / "phase1_integration_test.png"
        pymol.cmd.ray(1920, 1080)
        pymol.cmd.png(str(output_path), dpi=300)
        
        pymol.cmd.quit()
        
        elapsed = time.time() - start
        
        print(f"   ✅ Görselleştirme Tamamlandı:")
        print(f"      • Dosya: {output_path}")
        print(f"      • En büyük {len(top_voids)} boşluk gösterildi")
        print(f"      • Süre: {elapsed:.4f} saniye")
        
        return elapsed
    
    except Exception as e:
        print(f"   ⚠️ PyMOL hatası: {e}")
        return 0

def generate_report(results):
    """Test raporunu oluştur"""
    print("\n" + "="*60)
    print("📊 FAZ 1 ENTEGRASYON TESTİ - SONUÇLAR")
    print("="*60)
    
    print(f"\n🧬 Protein: {results.pdb_id.upper()}")
    print(f"   • Atom sayısı: {results.atom_count}")
    
    print(f"\n⏱️ Performans:")
    print(f"   • İndirme: {results.download_time:.4f}s")
    print(f"   • NMA: {results.nma_time:.4f}s")
    print(f"   • Voronoi: {results.voronoi_time:.4f}s")
    print(f"   • Görselleştirme: {results.visualization_time:.4f}s")
    print(f"   • TOPLAM: {results.total_time:.4f}s")
    
    print(f"\n🎯 Başarı Kriterleri:")
    
    # Kriter 1: Atom sayısı
    criterion1 = results.atom_count >= 3000
    print(f"   {'✅' if criterion1 else '❌'} 3000+ atom: {results.atom_count}")
    
    # Kriter 2: Mod sayısı
    criterion2 = results.modes_calculated >= 10
    print(f"   {'✅' if criterion2 else '❌'} 10+ mod: {results.modes_calculated}")
    
    # Kriter 3: Boşluk sayısı
    avg_voids = np.mean([len(v) for v in results.voids_found]) if results.voids_found else 0
    criterion3 = avg_voids >= MIN_VOIDS_PER_MODE
    print(f"   {'✅' if criterion3 else '❌'} {MIN_VOIDS_PER_MODE}+ boşluk/mod: {avg_voids:.1f}")
    
    # Kriter 4: Süre
    criterion4 = results.total_time <= MAX_TOTAL_TIME
    print(f"   {'✅' if criterion4 else '❌'} < {MAX_TOTAL_TIME}s: {results.total_time:.2f}s")
    
    # Kriter 5: Görselleştirme
    criterion5 = results.visualization_time > 0
    print(f"   {'✅' if criterion5 else '❌'} PyMOL görseli oluşturuldu")
    
    # Genel sonuç
    all_passed = all([criterion1, criterion2, criterion3, criterion4, criterion5])
    
    print("\n" + "="*60)
    if all_passed:
        print("🎉 TÜM KRİTERLER BAŞARILI!")
        print("   Faz 1 entegrasyon testi GEÇTI ✅")
        print("\n   Sistem gerçek proteinlerde çalışmaya HAZIR!")
    else:
        print("⚠️ BAZI KRİTERLER BAŞARISIZ")
        print("   Optimizasyon gerekebilir.")
    print("="*60)
    
    return all_passed

def main():
    """Ana test fonksiyonu"""
    results = IntegrationTestResults()
    
    try:
        total_start = time.time()
        
        # 1. Protein indir
        ca_atoms, download_time = download_protein()
        results.atom_count = len(ca_atoms)
        results.download_time = download_time
        
        # 2. NMA hesapla
        coords, modes, frequencies, nma_time = calculate_nma(ca_atoms)
        results.modes_calculated = modes.shape[1]
        results.nma_time = nma_time
        
        # 3. Konformasyonlar üret
        conformations = generate_conformations(coords, modes, num_frames=5)
        
        # 4. Voronoi taraması
        all_voids, voronoi_time = scan_voids_all_conformations(conformations)
        results.voids_found = all_voids
        results.voronoi_time = voronoi_time
        
        # 5. Görselleştirme
        viz_time = visualize_results(coords, all_voids)
        results.visualization_time = viz_time
        
        # Toplam süre
        results.total_time = time.time() - total_start
        
        # Rapor
        results.success = generate_report(results)
        
        return 0 if results.success else 1
    
    except Exception as e:
        print(f"\n❌ HATA: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())

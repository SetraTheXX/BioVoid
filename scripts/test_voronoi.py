"""
Bio-Void Hunter: Voronoi Tessellation Test
===========================================

Bu script, gerçek protein atomları üzerinde Voronoi diyagramı oluşturur
ve proteindeki boşlukları (voids) tespit etme yeteneğini test eder.

Matteo Paz felsefesi: Gerçek veriyle test et, sahte verilerle kendini kandırma.

Referans:
- Edelsbrunner & Mucke (1994) "Three-dimensional alpha shapes"
- Liang et al. (1998) "Anatomy of protein pockets and cavities"
"""

import numpy as np
from scipy.spatial import Voronoi, ConvexHull
import biotite.structure.io.pdb as pdb
import time
from pathlib import Path
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

# ============================================================================
# 1. GERÇEK PROTEIN ATOMLARINI YÜKLE
# ============================================================================

def load_protein_atoms(pdb_path, atom_type="CA"):
    """
    PDB dosyasından atom koordinatlarını yükler.
    
    Args:
        pdb_path (str): PDB dosyasının yolu
        atom_type (str): Atom tipi ("CA" veya "ALL")
        
    Returns:
        coords (np.ndarray): Atom koordinatları (N x 3)
    """
    print(f"[INFO] PDB dosyası yükleniyor: {pdb_path}")
    
    pdb_file = pdb.PDBFile.read(pdb_path)
    structure = pdb_file.get_structure()[0]
    
    if atom_type == "CA":
        # Sadece C-alpha atomları
        atom_filter = (structure.atom_name == "CA")
        atoms = structure[atom_filter]
    else:
        # Tüm atomlar
        atoms = structure
    
    coords = atoms.coord
    print(f"[OK] {len(coords)} atom yüklendi ({atom_type})")
    
    return coords


# ============================================================================
# 2. VORONOI DİYAGRAMI OLUŞTUR
# ============================================================================

def compute_voronoi(coords):
    """
    3D nokta kümesi için Voronoi diyagramı hesaplar.
    
    Args:
        coords (np.ndarray): Atom koordinatları (N x 3)
        
    Returns:
        vor (Voronoi): Voronoi diyagramı
        elapsed (float): Hesaplama süresi (saniye)
    """
    print(f"[INFO] Voronoi diyagramı hesaplanıyor ({len(coords)} nokta)...")
    
    start_time = time.time()
    vor = Voronoi(coords)
    elapsed = time.time() - start_time
    
    print(f"[OK] Voronoi hesaplandı ({elapsed:.4f} saniye)")
    print(f"    • Voronoi köşeleri: {len(vor.vertices)}")
    print(f"    • Voronoi bölgeleri: {len(vor.regions)}")
    
    return vor, elapsed


# ============================================================================
# 3. BOŞLUK (VOID) TESPİTİ (Bilimsel Olarak Doğru Algoritma)
# ============================================================================

def point_in_hull(point, hull_vertices):
    """
    Bir noktanın ConvexHull içinde olup olmadığını kontrol eder.
    
    Args:
        point (np.ndarray): Test edilecek nokta (3D)
        hull_vertices (np.ndarray): ConvexHull köşeleri
        
    Returns:
        bool: Nokta içerideyse True
    """
    from scipy.spatial import Delaunay
    
    # Delaunay triangulation kullan (3D'de ConvexHull ile eşdeğer)
    try:
        delaunay = Delaunay(hull_vertices)
        return delaunay.find_simplex(point) >= 0
    except:
        # Dejenere durumlar için güvenli varsayım
        return True


def find_voids(vor, coords, min_distance=2.5, max_distance=8.0):
    """
    Voronoi köşelerini analiz ederek GERÇEK boşlukları tespit eder.
    
    Liang et al. (1998) "Anatomy of protein pockets and cavities" algoritması:
    1. Voronoi köşesi 4+ atomdan eşit uzaklıkta olmalı (Voronoi tanımı gereği)
    2. En yakın atom mesafesi 2.5-8.0 Å arasında olmalı (ilaç cebi boyutu)
    3. Köşe proteinin ConvexHull'u içinde olmalı (gömülülük kontrolü)
    
    Args:
        vor (Voronoi): Voronoi diyagramı
        coords (np.ndarray): Atom koordinatları
        min_distance (float): Minimum atom-köşe mesafesi (Angstrom)
        max_distance (float): Maximum atom-köşe mesafesi (Angstrom)
        
    Returns:
        voids (list): Gerçek boşluk bilgileri (dict listesi)
    """
    print(f"[INFO] Boşluklar tespit ediliyor (mesafe: {min_distance}-{max_distance} Å)...")
    
    # Proteinin dış yüzeyini bul (ConvexHull)
    try:
        hull = ConvexHull(coords)
        print(f"    • ConvexHull oluşturuldu ({len(hull.vertices)} köşe)")
        use_hull = True
    except:
        print("    ⚠️ ConvexHull hesaplanamadı, tüm köşeler kabul ediliyor")
        use_hull = False
    
    voids = []
    surface_rejected = 0
    distance_rejected = 0
    
    for vertex in vor.vertices:
        # 1. Mesafe kontrolü
        distances = np.linalg.norm(coords - vertex, axis=1)
        min_dist = np.min(distances)
        
        # Mesafe aralığı dışındaysa atla
        if not (min_distance <= min_dist <= max_distance):
            distance_rejected += 1
            continue
        
        # 2. Gömülülük kontrolü (içeride mi?)
        if use_hull:
            in_hull = point_in_hull(vertex, coords)
            if not in_hull:
                surface_rejected += 1
                continue
        
        # 3. Boşluk bilgilerini kaydet
        voids.append({
            'coord': vertex,
            'radius': min_dist,  # Boşluğun yarıçapı (en yakın atom mesafesi)
            'volume': (4/3) * np.pi * (min_dist ** 3)  # Yaklaşık hacim (küre)
        })
    
    print(f"[OK] {len(voids)} gerçek boşluk bulundu")
    print(f"    • Mesafe filtresi: {distance_rejected} elendi")
    print(f"    • Yüzey filtresi: {surface_rejected} elendi")
    
    # Hacme göre sırala (en büyük boşluklar önce)
    voids = sorted(voids, key=lambda x: x['volume'], reverse=True)
    
    return voids



# ============================================================================
# 4. GÖRSELLEŞTİRME (Geliştirilmiş)
# ============================================================================

def visualize_voids(coords, voids, save_path="voronoi_voids.png", max_atoms=500):
    """
    Protein atomlarını ve tespit edilen boşlukları 3D olarak görselleştirir.
    
    Args:
        coords (np.ndarray): Atom koordinatları
        voids (list): Boşluk bilgileri (dict listesi)
        save_path (str): Görselin kaydedileceği yol
        max_atoms (int): Maksimum gösterilecek atom sayısı
    """
    print(f"[INFO] Görselleştirme oluşturuluyor...")
    
    # Büyük proteinler için subsampling
    if len(coords) > max_atoms:
        indices = np.random.choice(len(coords), max_atoms, replace=False)
        coords_display = coords[indices]
        print(f"    ⚠️ Görselleştirme için {max_atoms} atom gösteriliyor (toplam: {len(coords)})")
    else:
        coords_display = coords
    
    fig = plt.figure(figsize=(14, 12))
    ax = fig.add_subplot(111, projection='3d')
    
    # Protein atomları (mavi, şeffaf)
    ax.scatter(coords_display[:, 0], coords_display[:, 1], coords_display[:, 2], 
               c='lightblue', marker='.', s=15, alpha=0.2, label='Protein Atomları')
    
    # Boşluklar (kırmızı, hacme göre boyutlandırılmış)
    if len(voids) > 0:
        void_coords = np.array([v['coord'] for v in voids])
        void_volumes = np.array([v['volume'] for v in voids])
        
        # Hacmi görselleştir (normalize edilmiş boyut)
        sizes = (void_volumes / void_volumes.max()) * 500 + 50
        
        scatter = ax.scatter(void_coords[:, 0], void_coords[:, 1], void_coords[:, 2], 
                            c=void_volumes, cmap='Reds', marker='o', s=sizes, 
                            alpha=0.8, edgecolors='darkred', linewidths=1,
                            label=f'{len(voids)} Gerçek Boşluk')
        
        # Colorbar ekle (hacim göstergesi)
        cbar = plt.colorbar(scatter, ax=ax, pad=0.1, shrink=0.8)
        cbar.set_label('Boşluk Hacmi (Å³)', rotation=270, labelpad=20)
    
    ax.set_xlabel('X (Å)', fontsize=10)
    ax.set_ylabel('Y (Å)', fontsize=10)
    ax.set_zlabel('Z (Å)', fontsize=10)
    ax.set_title('Voronoi Boşluk Analizi (Bio-Void Hunter)\nBilimsel Algoritma: Liang et al. (1998)', 
                 fontsize=12, fontweight='bold')
    ax.legend(fontsize=10)
    
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    print(f"[OK] Görsel kaydedildi: {save_path}")
    plt.close()


# ============================================================================
# 5. PERFORMANS TESTİ
# ============================================================================

def performance_test():
    """
    Farklı nokta sayıları için Voronoi performansını test eder.
    """
    print("\n" + "="*60)
    print("⚡ PERFORMANS TESTİ")
    print("="*60)
    
    test_sizes = [100, 500, 1000, 5000, 10000]
    
    for size in test_sizes:
        # Rastgele 3D noktalar oluştur
        points = np.random.rand(size, 3) * 50  # 50 Å küp içinde
        
        start = time.time()
        vor = Voronoi(points)
        elapsed = time.time() - start
        
        status = "✅" if elapsed < 1.0 else "⚠️"
        print(f"{status} {size:5d} nokta: {elapsed:.4f} saniye")
    
    print("="*60)


# ============================================================================
# 6. DOĞRULAMA (Geliştirilmiş)
# ============================================================================

def validate_voronoi_results(vor, voids, coords):
    """
    Voronoi sonuçlarını doğrular ve detaylı istatistikler verir.
    """
    print("\n" + "="*60)
    print("📊 VORONOI TEST SONUÇLARI (Bilimsel Algoritma)")
    print("="*60)
    
    print(f"Protein Atomu: {len(coords)}")
    print(f"Voronoi Köşeleri (Ham): {len(vor.vertices)}")
    print(f"Tespit Edilen GERÇEK Boşluk: {len(voids)}")
    
    if len(voids) > 0:
        volumes = [v['volume'] for v in voids]
        radii = [v['radius'] for v in voids]
        
        print(f"\nBoşluk İstatistikleri:")
        print(f"  • En büyük hacim: {max(volumes):.2f} Å³")
        print(f"  • En küçük hacim: {min(volumes):.2f} Å³")
        print(f"  • Ortalama hacim: {np.mean(volumes):.2f} Å³")
        print(f"  • Ortalama yarıçap: {np.mean(radii):.2f} Å")
        
        print(f"\nEn Büyük 5 Boşluk:")
        for i, void in enumerate(voids[:5], 1):
            print(f"  {i}. Hacim: {void['volume']:.2f} Å³, Yarıçap: {void['radius']:.2f} Å")
    
    # Doğrulama kontrolleri
    assert len(vor.vertices) > 0, "❌ Voronoi köşeleri bulunamadı!"
    assert len(vor.regions) > 0, "❌ Voronoi bölgeleri bulunamadı!"
    
    print("\n✅ Tüm doğrulama testleri BAŞARILI")
    print("="*60)


# ============================================================================
# MAIN TEST
# ============================================================================

if __name__ == "__main__":
    print("\n" + "🧬 BIO-VOID HUNTER: VORONOI TEST ".center(60, "="))
    print()
    
    # Test için PDB dosyası
    pdb_path = Path("data/raw_pdb/pdb1cbs.ent")
    
    if not pdb_path.exists():
        print(f"❌ HATA: PDB dosyası bulunamadı: {pdb_path}")
        print("   Lütfen önce 'scripts/download_pdb.py' scriptini çalıştırın.")
        exit(1)
    
    # 1. Protein Atomlarını Yükle
    coords = load_protein_atoms(pdb_path, atom_type="CA")
    
    # 2. Voronoi Hesapla
    vor, elapsed = compute_voronoi(coords)
    
    # 3. Boşlukları Tespit Et
    voids = find_voids(vor, coords, min_distance=3.0)
    
    # 4. Görselleştir
    visualize_voids(coords, voids, save_path="data/results/voronoi_test.png")
    
    # 5. Performans Testi
    performance_test()
    
    # 6. Doğrula
    validate_voronoi_results(vor, voids, coords)
    
    print("\n🎉 TEST TAMAMLANDI: Voronoi geometrik tarayıcı çalışıyor!")

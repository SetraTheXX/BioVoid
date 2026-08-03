"""
Bio-Void Hunter: PyMOL Test Suite
==================================
Bu script PyMOL kurulumunu kapsamlı olarak test eder.

Test Senaryosu:
1. PyMOL import kontrolü
2. Versiyon kontrolü
3. PDB yükleme testi
4. PNG görsel kaydetme
5. Headless mode testi

Referanslar:
- PyMOL: https://pymol.org/
- PyMOL Open-Source: https://github.com/schrodinger/pymol-open-source
"""

import sys
import time
from pathlib import Path

# Proje dizinleri
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "results"
PDB_DIR = PROJECT_ROOT / "data" / "raw_pdb"

# Sonuç klasörünü oluştur
DATA_DIR.mkdir(parents=True, exist_ok=True)

def test_pymol_import():
    """Test 1: PyMOL import edilebiliyor mu?"""
    print("\n1️⃣ PYMOL IMPORT KONTROLÜ:")
    
    try:
        import pymol
        print(f"   ✅ PyMOL başarıyla import edildi")
        return True, pymol
    except ImportError as e:
        print(f"   ❌ PyMOL import edilemedi: {e}")
        return False, None

def test_pymol_version(pymol):
    """Test 2: PyMOL versiyonu kontrol et."""
    print("\n2️⃣ PYMOL VERSİYON KONTROLÜ:")
    
    try:
        # PyMOL'ü başlat (headless mode)
        pymol.finish_launching(['pymol', '-c'])
        
        # Versiyon bilgisini al
        version = pymol.cmd.get_version()
        print(f"   ✅ PyMOL versiyonu: {version[0]}")
        
        # Versiyon 2.5+ mı kontrol et
        version_parts = version[0].split('.')
        major = int(version_parts[0])
        minor = int(version_parts[1]) if len(version_parts) > 1 else 0
        
        if major >= 3 or (major == 2 and minor >= 5):
            print(f"   ✅ Versiyon {major}.{minor} - Uyumlu!")
            return True
        else:
            print(f"   ⚠️ Versiyon 2.5+ önerilir (mevcut: {major}.{minor})")
            return True
            
    except Exception as e:
        print(f"   ❌ Versiyon kontrolü başarısız: {e}")
        return False

def test_pdb_loading(pymol):
    """Test 3: PDB dosyası yüklenebiliyor mu?"""
    print("\n3️⃣ PDB YÜKLEME TESTİ:")
    
    try:
        # Test için basit bir PDB dosyası oluştur (1CRN - küçük protein)
        # Eğer yoksa, fetch komutu ile indir
        pymol.cmd.fetch('1crn', name='test_protein', type='pdb')
        
        # Yüklenen atomları say
        atom_count = pymol.cmd.count_atoms('test_protein')
        print(f"   ✅ PDB dosyası yüklendi: 1CRN")
        print(f"   ✅ Atom sayısı: {atom_count}")
        
        if atom_count > 0:
            return True
        else:
            print(f"   ❌ Atom sayısı 0!")
            return False
            
    except Exception as e:
        print(f"   ❌ PDB yükleme başarısız: {e}")
        return False

def test_png_export(pymol):
    """Test 4: PNG görsel kaydedilebiliyor mu?"""
    print("\n4️⃣ PNG EXPORT TESTİ:")
    
    try:
        # Görsel ayarları
        pymol.cmd.bg_color('white')
        pymol.cmd.set('ray_opaque_background', 0)
        pymol.cmd.show('cartoon', 'test_protein')
        pymol.cmd.color('cyan', 'test_protein')
        pymol.cmd.orient('test_protein')
        
        # PNG kaydet
        output_path = DATA_DIR / "pymol_test.png"
        pymol.cmd.png(str(output_path), width=800, height=600, dpi=150)
        
        # Dosya oluşturuldu mu?
        if output_path.exists():
            file_size = output_path.stat().st_size
            print(f"   ✅ PNG dosyası oluşturuldu: {output_path}")
            print(f"   ✅ Dosya boyutu: {file_size / 1024:.2f} KB")
            return True
        else:
            print(f"   ❌ PNG dosyası oluşturulamadı!")
            return False
            
    except Exception as e:
        print(f"   ❌ PNG export başarısız: {e}")
        return False

def test_headless_mode(pymol):
    """Test 5: Headless mode (GUI olmadan) çalışıyor mu?"""
    print("\n5️⃣ HEADLESS MODE TESTİ:")
    
    try:
        # Headless modda zaten çalışıyoruz (-c flag ile başlattık)
        # Basit bir komut çalıştırarak test edelim
        pymol.cmd.select('test_selection', 'test_protein and name CA')
        ca_count = pymol.cmd.count_atoms('test_selection')
        
        print(f"   ✅ Headless mode çalışıyor")
        print(f"   ✅ CA atomları seçildi: {ca_count}")
        
        # Renklendirme testi
        pymol.cmd.color('red', 'test_selection')
        print(f"   ✅ Renklendirme başarılı")
        
        return True
            
    except Exception as e:
        print(f"   ❌ Headless mode testi başarısız: {e}")
        return False

def test_ray_tracing(pymol):
    """Test 6: Ray-tracing çalışıyor mu?"""
    print("\n6️⃣ RAY-TRACING TESTİ:")
    
    try:
        start_time = time.time()
        
        # Ray-tracing ile render et
        pymol.cmd.ray(800, 600)
        
        elapsed = time.time() - start_time
        print(f"   ✅ Ray-tracing başarılı")
        print(f"   ✅ Render süresi: {elapsed:.2f} saniye")
        
        # Performans kontrolü (< 10s)
        if elapsed < 10:
            print(f"   ✅ Performans hedefi karşılandı (< 10s)")
        else:
            print(f"   ⚠️ Render yavaş (> 10s)")
        
        return True
            
    except Exception as e:
        print(f"   ❌ Ray-tracing başarısız: {e}")
        return False

def generate_summary(results):
    """Test özeti oluştur."""
    print("\n" + "="*60)
    print("📊 TEST ÖZETİ")
    print("="*60)
    
    passed = sum(results.values())
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅" if result else "❌"
        print(f"   {status} {test_name}")
    
    print(f"\n   Sonuç: {passed}/{total} test başarılı")
    
    if passed == total:
        print("\n🎉 TÜM TESTLER BAŞARILI!")
        print("   PyMOL kurulumu tamamlandı.")
        return True
    else:
        print("\n⚠️ Bazı testler başarısız.")
        return False

def main():
    print("\n" + "="*60)
    print("🧬 BIO-VOID HUNTER: PYMOL TEST SUITE")
    print("="*60)
    
    start_time = time.time()
    
    # Test 1: Import
    success, pymol = test_pymol_import()
    if not success:
        print("\n❌ PyMOL import edilemedi. Kurulum başarısız!")
        return 1
    
    # Testleri çalıştır
    results = {}
    results["Import Kontrolü"] = success
    results["Versiyon Kontrolü"] = test_pymol_version(pymol)
    results["PDB Yükleme"] = test_pdb_loading(pymol)
    results["PNG Export"] = test_png_export(pymol)
    results["Headless Mode"] = test_headless_mode(pymol)
    results["Ray-tracing"] = test_ray_tracing(pymol)
    
    # PyMOL'ü kapat
    pymol.cmd.quit()
    
    elapsed = time.time() - start_time
    
    # Özet
    success = generate_summary(results)
    print(f"\n   ⏱️ Toplam süre: {elapsed:.2f} saniye")
    
    # Sonraki adımlar
    print("\n📋 SONRAKİ ADIMLAR:")
    print("   1. Faz 1 tamamlandı - Faz 2'ye geçiş")
    print("   2. NMA Simülasyon Motoru (Faz 2.2)")
    print("   3. Voronoi Geometrik Tarayıcı (Faz 2.3)")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())

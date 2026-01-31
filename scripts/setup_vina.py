"""
Bio-Void Hunter: AutoDock Vina Setup Script
============================================
Bu script Vina kurulumunu otomatikleştirmek için yardımcı bir araçtır.

MANUEL KURULUM ADIMLARI:
1. https://github.com/ccsb-scripps/AutoDock-Vina/releases/tag/v1.2.7 adresine git
2. "vina_1.2.7_windows_x64.exe" dosyasını indir
3. İndirilen dosyayı bu scriptin bulunduğu "tools/vina/" klasörüne kopyala
4. Dosya adını "vina.exe" olarak değiştir
5. Bu scripti çalıştır: python scripts/setup_vina.py --verify

Alternatif olarak, WSL2 veya Conda kullanabilirsiniz:
- conda install -c conda-forge autodock-vina
"""

import os
import subprocess
import sys
from pathlib import Path

VINA_DIR = Path("tools/vina")
VINA_EXE = VINA_DIR / "vina.exe"

def check_vina_installed():
    """Vina'nın kurulu olup olmadığını kontrol et."""
    
    # 1. Proje içindeki vina.exe'yi kontrol et
    if VINA_EXE.exists():
        print(f"✅ Vina bulundu: {VINA_EXE.absolute()}")
        return str(VINA_EXE.absolute())
    
    # 2. PATH'teki vina'yı kontrol et
    try:
        result = subprocess.run(
            ["vina", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            print(f"✅ Vina PATH'te bulundu")
            print(f"   Versiyon: {result.stdout.strip()}")
            return "vina"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    return None

def verify_vina():
    """Vina'nın çalıştığını doğrula."""
    vina_path = check_vina_installed()
    
    if not vina_path:
        print("❌ AutoDock Vina bulunamadı!")
        print("\n📥 MANUEL KURULUM:")
        print("1. https://github.com/ccsb-scripps/AutoDock-Vina/releases/tag/v1.2.7")
        print("2. 'vina_1.2.7_windows_x64.exe' indir")
        print(f"3. Dosyayı şuraya kopyala: {VINA_DIR.absolute()}")
        print("4. Dosya adını 'vina.exe' yap")
        return False
    
    # Versiyon kontrolü
    try:
        if vina_path == "vina":
            result = subprocess.run(["vina", "--version"], capture_output=True, text=True)
        else:
            result = subprocess.run([vina_path, "--version"], capture_output=True, text=True)
        
        version_output = result.stdout.strip() or result.stderr.strip()
        print(f"\n📊 VINA VERSİYON BİLGİSİ:")
        print(f"   {version_output}")
        
        # Versiyon 1.2.x mi?
        if "1.2" in version_output:
            print("   ✅ Versiyon 1.2.x - Uyumlu!")
        else:
            print("   ⚠️ Versiyon 1.2.x önerilir")
        
        return True
        
    except Exception as e:
        print(f"❌ Vina çalıştırılamadı: {e}")
        return False

def create_test_config():
    """Basit bir test config dosyası oluştur."""
    config_content = """# AutoDock Vina Test Config
# Bu dosya sadece kurulumu test etmek içindir

receptor = protein.pdbqt
ligand = ligand.pdbqt

center_x = 0
center_y = 0
center_z = 0

size_x = 20
size_y = 20
size_z = 20

exhaustiveness = 8
num_modes = 9
energy_range = 3
"""
    
    config_path = VINA_DIR / "test_config.txt"
    config_path.write_text(config_content)
    print(f"✅ Test config oluşturuldu: {config_path}")

def main():
    print("\n" + "="*60)
    print("🧬 BIO-VOID HUNTER: AUTODOCK VINA SETUP")
    print("="*60 + "\n")
    
    # Klasör yapısını oluştur
    VINA_DIR.mkdir(parents=True, exist_ok=True)
    
    # Argüman kontrolü
    if len(sys.argv) > 1 and sys.argv[1] == "--verify":
        success = verify_vina()
        if success:
            print("\n🎉 Vina kurulumu doğrulandı!")
            create_test_config()
        else:
            print("\n⚠️ Kurulum tamamlanmadı. Manuel adımları takip edin.")
        return
    
    # Normal çalışma - kurulum rehberi göster
    print("📋 AUTODOCK VINA KURULUM REHBERİ")
    print("-"*40)
    print()
    print("Vina'yı kurmak için aşağıdaki adımları takip edin:")
    print()
    print("1️⃣  GitHub Releases sayfasına git:")
    print("    https://github.com/ccsb-scripps/AutoDock-Vina/releases/tag/v1.2.7")
    print()
    print("2️⃣  Windows binary'sini indir:")
    print("    'vina_1.2.7_windows_x64.exe'")
    print()
    print(f"3️⃣  İndirilen dosyayı şuraya kopyala:")
    print(f"    {VINA_DIR.absolute()}")
    print()
    print("4️⃣  Dosya adını 'vina.exe' olarak değiştir")
    print()
    print("5️⃣  Kurulumu doğrula:")
    print("    python scripts/setup_vina.py --verify")
    print()
    print("="*60)
    
    # Mevcut durumu kontrol et
    print("\n📊 MEVCUT DURUM:")
    vina_path = check_vina_installed()
    if vina_path:
        print("✅ Vina zaten kurulu!")
        verify_vina()
    else:
        print("⚠️ Vina henüz kurulu değil")

if __name__ == "__main__":
    main()

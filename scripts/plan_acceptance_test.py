"""
Plan Acceptance Test Runner
Bio-Void Hunter: Faz 6 Öncesi Düzenleme ve Validasyon Planı
"""
import sqlite3
import json
import sys
import os

# Ensure project root is in sys.path for src imports
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

def check(label, condition, detail=""):
    status = "✅ PASS" if condition else "❌ FAIL"
    print(f"  {status}  {label}" + (f" ({detail})" if detail else ""))
    return condition

def main():
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    results = []
    
    print("=" * 60)
    print("BIO-VOID HUNTER: PLAN ACCEPTANCE TESTS")
    print("=" * 60)
    
    # ---------- FAZ 1: Bilimsel Validasyon ----------
    print("\n📋 FAZ 1: Bilimsel Validasyon")
    
    # 1.1 Test seti
    test_set_path = "data/validation/known_cryptic_pockets.json"
    exists = os.path.exists(test_set_path)
    results.append(check("Test seti dosyası mevcut", exists, test_set_path))
    
    if exists:
        with open(test_set_path, "r") as f:
            data = json.load(f)
        case_count = len(data.get("test_cases", []))
        results.append(check("Test seti 10-20 case içeriyor", 10 <= case_count <= 20, f"{case_count} cases"))
    
    # 1.2 Validasyon scripti
    val_script = "scripts/validate_known_pockets.py"
    results.append(check("Validasyon scripti mevcut", os.path.exists(val_script), val_script))
    
    # 1.3 Validasyon raporu
    report_path = "docs/validation_report.md"
    results.append(check("Validasyon raporu mevcut", os.path.exists(report_path), report_path))
    
    # 1.3b Recall threshold
    val_results = "data/validation/validation_results.json"
    if os.path.exists(val_results):
        with open(val_results) as f:
            vr = json.load(f)
        recall = vr.get("summary", {}).get("recall", 0)
        results.append(check("Recall >= 30%", recall >= 0.30, f"Recall={recall*100:.1f}%"))
    else:
        results.append(check("Validasyon sonuçları mevcut", False))
    
    # ---------- FAZ 2: Altyapı ve Pilot ----------
    print("\n📋 FAZ 2: Altyapı ve Pilot Çalışma")
    
    # 2.1 Pilot run
    db_path = "data/atlas.db"
    results.append(check("atlas.db mevcut", os.path.exists(db_path)))
    
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM proteins")
        protein_count = c.fetchone()[0]
        results.append(check("1000 protein işlendi (>900 başarılı)", protein_count >= 900, f"{protein_count} proteins"))
        
        c.execute("SELECT COUNT(*) FROM pockets")
        pocket_count = c.fetchone()[0]
        results.append(check("Pocket verileri DB'de", pocket_count > 0, f"{pocket_count} pockets"))
        
        # DB boyutu
        db_size = os.path.getsize(db_path)
        results.append(check("DB boyutu > 1MB", db_size > 1_000_000, f"{db_size / 1_000_000:.1f}MB"))
        conn.close()
    
    # 2.2 Dashboard
    try:
        from src.dashboard import load_statistics
        results.append(check("Dashboard import çalışıyor", True))
    except ImportError as e:
        results.append(check("Dashboard import çalışıyor", False, str(e)))
    
    # ---------- FAZ 3: Kod Kalitesi ----------
    print("\n📋 FAZ 3: Kod Kalitesi ve Temizlik")
    
    # 3.1 requirements.txt
    if os.path.exists("requirements.txt"):
        with open("requirements.txt") as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
        results.append(check("requirements.txt <= 65 paket", len(lines) <= 65, f"{len(lines)} packages"))
    
    # 3.2 docker.py refactoring
    results.append(check("src/docking/__init__.py mevcut", os.path.exists("src/docking/__init__.py")))
    results.append(check("src/docking/vina_wrapper.py mevcut", os.path.exists("src/docking/vina_wrapper.py")))
    results.append(check("src/docking/interactions.py mevcut", os.path.exists("src/docking/interactions.py")))
    results.append(check("src/docking/validation.py mevcut", os.path.exists("src/docking/validation.py")))
    
    # 3.2b Backward compatibility
    try:
        from src.docking import VinaDocking, dock_elite_pockets, GridBox
        results.append(check("Docking imports çalışıyor", True))
    except ImportError as e:
        results.append(check("Docking imports çalışıyor", False, str(e)))
    
    # 3.3 Import düzeltmeleri
    with open("main.py", "r", encoding="utf-8") as f:
        main_content = f.read()
    results.append(check("main.py: src.docking import", "src.docking" in main_content or "from src.docking" in main_content))
    
    # ---------- SUMMARY ----------
    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    rate = passed / total * 100 if total > 0 else 0
    
    print(f"SONUÇ: {passed}/{total} test geçti ({rate:.0f}%)")
    
    if rate == 100:
        print("🎉 TÜM TESTLER GEÇTİ — Plan TAMAMLANDI!")
    elif rate >= 80:
        print("✅ Plan büyük ölçüde tamamlandı. Küçük düzeltmeler gerekli.")
    else:
        print("⚠️ Bazı testler başarısız. Düzeltme gerekli.")
    
    print("=" * 60)
    return 0 if rate >= 80 else 1

if __name__ == "__main__":
    sys.exit(main())

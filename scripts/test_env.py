import sys
import importlib

print("="*50)
print("🧬 BIO-VOID HUNTER ENVIRONMENT CHECK (UPDATED)")
print("="*50)

required_packages = [
    ("Bio", "1.86"),
    ("numpy", "1.20"),
    ("scipy", "1.10"),
    ("pandas", "1.5"),
    ("sklearn", "1.0"),
    ("matplotlib", "3.5"),
    ("biotite", "1.0") # Replaced ProDy with Biotite
]

all_passed = True

for package_name, min_version in required_packages:
    try:
        module = importlib.import_module(package_name)
        version = getattr(module, "__version__", "unknown")
        print(f"[OK] {package_name:<15} detected (v{version})")
    except ImportError:
        print(f"[ERROR] {package_name:<15} NOT FOUND!")
        all_passed = False

print("-" * 50)
if all_passed:
    print("✅ ENVIRONMENT READY FOR PHASE 1")
    print("   (Using Biotite instead of ProDy for NMA)")
else:
    print("❌ ENVIRONMENT INCOMPLETE. PLEASE FIX ERRORS ABOVE.")

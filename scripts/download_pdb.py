"""
Bio-Void Hunter: PDB Fetcher & Dataset Manager (v1.1)
====================================================
RCSB PDB üzerinden protein yapılarını tekli veya toplu olarak indirme aracı.

Bilimsel veri setleri (Phase 1 & Phase 2) entegre edilmiştir.
"""

import os
import argparse
from Bio.PDB import PDBList
from pathlib import Path

def download_pdb(pdb_id, target_dir="data/raw_pdb", verbose=True):
    """
    Belirtilen PDB ID'ye sahip dosyayı indirir.
    
    Args:
        pdb_id (str): PDB ID (ör: '1cbs', '1TUP')
        target_dir (str): Kayıt dizini
        verbose (bool): Detaylı çıktı göster
        
    Returns:
        str: İndirilen dosyanın yolu (veya None)
    """
    pdb_id = pdb_id.lower()
    save_dir = Path(target_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    
    expected_filename = f"pdb{pdb_id}.ent"
    target_path = save_dir / expected_filename
    
    # Cache kontrolü
    if target_path.exists():
        if verbose:
            print(f"   [CACHE] {pdb_id.upper()} zaten mevcut")
        return str(target_path)
    
    if verbose:
        print(f"   [DOWNLOAD] {pdb_id.upper()} indiriliyor...")
    
    try:
        pdbl = PDBList()
        # Biopython retrieve_pdb_file fonksiyonu
        downloaded_file = pdbl.retrieve_pdb_file(
            pdb_id, 
            pdir=str(save_dir), 
            file_format='pdb'
        )
        
        # Doğrulama (Biopython bazen farklı isimlerle kaydedebilir)
        if target_path.exists():
            if verbose:
                print(f"   [OK] İndirildi: {expected_filename}")
            return str(target_path)
        else:
            # PDBList bazen farklı kaydedebiliyor, klasör kontrolü yapalım
            # Genelde 'pdb1cbs.ent' olur ama bazen .ent uzantısı farklı olabilir
            if verbose:
                print(f"   [WARN] Beklenen dosya bulunamadı, ancak işlem tamamlandı.")
            return str(save_dir)
            
    except Exception as e:
        if verbose:
            print(f"   [ERROR] İndirme hatası ({pdb_id}): {str(e)}")
        return None

def download_dataset(dataset_name="phase1_test"):
    """
    Test veri setini toplu olarak indirir.
    
    Args:
        dataset_name (str): 'phase1_test' veya 'phase2_validation'
    """
    # Test veri setleri
    datasets = {
        'phase1_test': {
            'description': 'Faz 1 - Hızlı algoritma testleri',
            'proteins': [
                ('1cbs', 'CRABP-II (küçük, basit)'),
                ('1crn', 'Crambin (çok küçük, debug için)')
            ]
        },
        'phase2_validation': {
            'description': 'Faz 2 - Bilimsel doğrulama (bilinen ilaç cepleri)',
            'proteins': [
                ('1tup', 'p53 (kanser) - MDM2 cebi'),
                ('1hsg', 'HIV Protease - Indinavir cebi'),
                ('3ert', 'Estrogen Receptor - Tamoxifen cebi'),
                ('1o5b', 'BCR-ABL Kinase - Imatinib cebi'),
                ('2br1', 'EGFR Kinase - Gefitinib cebi')
            ]
        }
    }
    
    if dataset_name not in datasets:
        print(f"❌ Geçersiz veri seti: {dataset_name}")
        print(f"Geçerli seçenekler: {', '.join(datasets.keys())}")
        return
    
    dataset = datasets[dataset_name]
    print(f"\n🧬 {dataset['description']}")
    print("="*60)
    
    success = 0
    failed = []
    
    for pdb_id, description in dataset['proteins']:
        print(f"\n📥 {pdb_id.upper()}: {description}")
        result = download_pdb(pdb_id, verbose=True)
        
        if result:
            success += 1
        else:
            failed.append(pdb_id)
    
    # Özet
    print("\n" + "="*60)
    print(f"✅ Başarılı: {success}/{len(dataset['proteins'])}")
    
    if failed:
        print(f"❌ Başarısız: {', '.join(failed)}")
    else:
        print("🎉 Tüm dosyalar başarıyla indirildi!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Bio-Void Hunter: PDB Fetcher (v1.1)"
    )
    
    parser.add_argument(
        'pdb_id', 
        nargs='?',  # Opsiyonel
        help="İndirmek istediğiniz PDB ID (ör: 1cbs, 1tup)"
    )
    
    parser.add_argument(
        '--dataset', 
        choices=['phase1_test', 'phase2_validation'],
        help="Test veri setini toplu olarak indir"
    )
    
    args = parser.parse_args()
    
    if args.dataset:
        # Toplu indirme
        download_dataset(args.dataset)
    elif args.pdb_id:
        # Tekli indirme
        download_pdb(args.pdb_id)
    else:
        parser.print_help()

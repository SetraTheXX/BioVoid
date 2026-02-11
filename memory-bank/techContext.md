<!-- cspell:disable -->

# Teknik Bağlam

## Temel Teknolojiler

- **Dil:** Python 3.10+ (Anaconda Ortamı).
- **Framework'ler:**
  - **Biopython:** Yapısal ayrıştırma (PDB/MMCIF).
  - **Biotite:** Protein Dinamikleri (NMA/ENM) ve Yapısal Analiz. (ProDy yerine seçildi: Python 3.13 uyumluluğu için).
  - **Numpy/Scipy:** Vektör matematiği ve uzamsal algoritmalar.
  - **Pandas:** Sonuçlar için veri yönetimi.
  - **Scikit-learn:** Keşfedilen cepleri kümeleme (DBSCAN/K-Means).

## Harici Araçlar

- **AutoDock Vina:** Açık kaynaklı moleküler docking yazılımı. PATH üzerinden kurulu ve erişilebilir olmalıdır.
- **PyMOL:** Moleküler görselleştirme sistemi (çıktı oturumları oluşturmak için).
- **Open Babel:** Kimyasal dosya formatı dönüşümü (docking için PDB -> PDBQT).

## Donanım Kısıtlamaları & Optimizasyonlar

- **GPU (AMD RX 580):**
  - **Birincil Kullanım:** Moleküler docking (Vina-GPU veya benzer fork'lar tarafından destekleniyorsa) ve lineer cebir işlemleri için OpenCL hızlandırma.
  - **Kısıt:** Derin Öğrenme'ye özgü devasa VRAM kullanımından kaçın. "Compute" görevlerine odaklan.
- **CPU:** Sıralı NMA mantığını ve geometrik döngüyü işler.

## Geliştirme Ortamı

- **IDE:** VS Code / Antigravity Agent.
- **Ortam:** Conda `bio-void-env`.
- **Versiyon Kontrolü:** Git.

## Dizin Yapısı

```
BioVoid/
├── data/
│   ├── raw_pdb/       # İndirilen PDB'ler
│   ├── frames/        # Oluşturulan konformasyonlar
│   ├── results/       # Analiz raporları
│   └── docking/       # Docking çıktıları
├── src/
│   ├── fetcher.py
│   ├── dynamics.py    # NMA mantığı
│   ├── geometry.py    # Voronoi mantığı
│   └── docker.py      # Vina sarmalayıcı
├── memory-bank/       # Dokümantasyon
└── main.py            # Orkestratör
```

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

## Dizin Yapısı (Güncel - 2026-02-22)

```
BioVoid/
├── src/
│   ├── api/
│   │   ├── app.py              # FastAPI backend (Phase 6)
│   │   ├── orchestrator.py     # Job queue & worker
│   │   ├── portal.py           # Unified web portal
│   │   ├── models.py           # Pydantic models
│   │   ├── rate_limit.py       # Rate limiting
│   │   └── errors.py           # API errors
│   ├── docking/
│   │   ├── vina_wrapper.py     # AutoDock Vina wrapper
│   │   ├── validation.py       # Docking validation
│   │   └── interactions.py     # Protein-ligand interactions
│   ├── fetcher.py              # PDB fetch
│   ├── dynamics.py             # NMA simulation
│   ├── geometry.py             # Voronoi scanning
│   ├── cavities.py             # Cavity analysis
│   ├── scoring.py              # Druggability scoring
│   ├── multiframe.py           # Multi-frame analysis
│   ├── parallel_crawler.py     # Parallel protein scanner
│   ├── database.py             # SQLite atlas DB
│   ├── frame_reconstruction.py # Frame rebuilding
│   ├── visualizer.py           # Visualization
│   └── dashboard.py            # Streamlit dashboard (legacy)
├── tests/                      # Unit tests
├── scripts/                    # Utility & integration scripts
├── data/                       # Benchmark & validation data
├── docs/                       # Governance, reports, runbooks
├── docker/                     # Docker configs (fpocket)
├── artifacts/                  # Generated artifacts
├── memory-bank/                # Progress & planning memory
├── main.py                     # Pipeline orchestrator
├── main_parallel.py            # Parallel pipeline
├── requirements.txt            # Python dependencies
└── README.md
```

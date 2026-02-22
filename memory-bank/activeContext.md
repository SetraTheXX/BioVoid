# Aktif Baglam

## Su Anki Mod

- **Mod:** Surekli Kod Gelistirme
- **Faz:** Phase 7 Hazirlik (Phase 6 Complete)
- **Aktif Plan:** `memory-bank/dev_plan_2026_02_22.md`
- **Son Guncelleme:** 2026-02-22

## Proje Durumu

| Alan | Durum |
|------|-------|
| Core Pipeline | Stabil + profiling + caching |
| Phase 6 API + Portal | Tamamlandi + Portal v2 (birlesik) |
| ML Scaffold | Tamamlandi (features, dataset, classifier, evaluation) |
| Bilimsel Metrikler | Recall 0.35, Overlap 0.26, FPR 0.13 |
| 3D Viewer | Entegre (3Dmol.js + Plotly 3D fallback) |

## Birlestirilen Ozellikler

Eski ayri arayuzler (Streamlit dashboard + API portal) tek bir BioVoid sitesine
birlestirildi: http://127.0.0.1:8000/portal

Sekmeler: Dashboard, New Analysis, Job History, Pocket Atlas, Reports, Gallery, System

## Canonical SoT

1. Dev plan: `memory-bank/dev_plan_2026_02_22.md`
2. Strict gate: `docs/phase5_5_gate_decision.md`
3. Faz 6 roadmap: `memory-bank/phase6_plus_roadmap.plan.md`
4. Kod analiz: `CODE_ANALYSIS_REPORT.md`

## Bu Oturumda Yapilan Degisiklikler

### Yeni Dosyalar (17)
- `src/config.py` - Merkezi config
- `src/profiling.py` - Pipeline profiling
- `src/cache.py` - Analiz caching
- `src/comparison.py` - Cross-protein similarity
- `src/benchmark.py` - Benchmark suite
- `src/cli.py` - Modern CLI
- `src/ml/__init__.py` - ML module
- `src/ml/features.py` - 17 feature columns
- `src/ml/dataset.py` - Label policy, splits, leakage guard
- `src/ml/classifier.py` - RF/GB/Logistic + calibration
- `src/ml/evaluation.py` - PR-AUC, ECE, recall@k, ablation
- `pyproject.toml` - Modern packaging
- `memory-bank/dev_plan_2026_02_22.md` - Gelistirme plani
- `memory-bank/current_snapshot_2026-02-22.md` - Durum snapshot

### Guncellenen Dosyalar (12+)
- `src/__init__.py` - 264 -> 55 satir, lazy import
- `src/scoring.py` - v2: sphericity, confidence, CustomProfile
- `src/multiframe.py` - Persistence tracking
- `src/fetcher.py` - AlphaFold DB + batch download
- `src/docker.py` - 45KB dead code temizlendi
- `src/api/app.py` - WebSocket, batch, visualization, protein endpoints
- `src/api/models.py` - Batch + WS + full_analysis modelleri
- `src/api/orchestrator.py` - Gercek pipeline runner + DB save + cancel + list
- `src/api/portal.py` - Tamamen yeniden yazildi (birlestirilen portal v2)
- `main.py` - DRY, logging, config, profiling, cache entegrasyonu
- `memory-bank/techContext.md` - Dizin yapisi guncellendi

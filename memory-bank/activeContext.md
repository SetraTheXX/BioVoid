# Aktif Baglam

## Su Anki Faz

- Faz: **5.5 Recovery v2**
- Konum: **SG1 sonrasi CP-A pivot**
- SoT: `docs/phase5_5_gate_decision.md`
- Faz 6 durumu: **BLOCKED**

## Son Dogrulanmis Gate Sonucu (2026-02-13)

- Recall: **0.1500 (3/20)** -> FAIL (hedef >= 0.30)
- fpocket overlap: **0.0577** -> FAIL (hedef >= 0.40)
- Conservative FPR: **0.1311** -> PASS (hedef <= 0.60)
- MD validated proteins: **1** -> PASS (hedef >= 1)
- Final karar: **FAIL**

## Recovery v2 Workstream Ozeti

### WS-A (Recall Specialist)

- SG1 tamamlandi ancak checkpoint gecilemedi.
- `docs/recall_recovery_experiments_v3.md`:
  - Recall: **15.0% (3/20)**
  - Domain-motion: **0/4**
  - SG1 checkpoint (>=0.22): **FAIL**
- Durum: **CP-A pivot zorunlu** (yalniz mini-set).

### WS-B (Overlap Specialist)

- B0-B3 tamamlandi ve merge-ready birakildi.
- `docs/fpocket_benchmark_report_v3.md`:
  - Official overlap: **0.0577** (FAIL)
  - Center-only overlap: **0.3099**
  - Center-only upper bound: **0.3188**
- Durum: resmi gate metriği degismeden overlap sorunu acik.

### WS-C (Guard/QA Specialist)

- `docs/recovery_v2_regression_guard_report.md`: **PASS**
- Drift guard: **PASS**
- Report alignment: **PASS**
- Durum: Recall/Overlap disinda aktif regression riski yok.

## Hemen Sonraki Adimlar

1. WS-A: CP-A mini-set pivot kosusu (full 20 yok).
2. WS-B: yeni algoritmik degisikligi bekle; SoT kalibrasyon uyumunu koru.
3. WS-C: WS-A patch sonrasi guard + drift + alignment rerun.


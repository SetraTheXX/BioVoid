# Aktif Baglam

## Su Anki Faz

- Faz: **5.5 Recovery v2**
- Konum: **SG5 NO-GO closure (SG4 full rerun tamamlandi, Faz 6 acilmadi)**
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

- SG1 tamamlandi ve mini checkpoint gecildi.
- `docs/recall_recovery_experiments_v3.md`:
  - Recall: **15.0% (3/20)**
  - Domain-motion: **0/4**
  - SG1 checkpoint (>=0.22): **FAIL**
- CP-A mini son gecerli artefakt (`docs/recovery_v2_recall_domain_motion_report.md`):
  - En iyi trial: `t4_atom_mode_heavy`
  - Recall: **2/7 = 0.2857**
  - Domain-motion: **2/4**
  - Karar: **SG2_CANDIDATE**
- Durum: **CP-A cikis kriteri saglandi** (recall >= 0.22).
- SG4 full recall rerun (gate-path) sonucu:
  - Recall: **0.0000 (0/20)**
  - Domain-motion: **0/4**
  - Avg best distance: **25.9256A**
  - Failed runs: **0**
  - Sonuc: gate-level recall kriteri saglanmadi.

### WS-B (Overlap Specialist)

- B0-B3 tamamlandi.
- CP-B Option-1 spike tamamlandi:
  - Pilot overlap: **0.0871 -> 0.3010**
  - Candidate Top10 overlap: **0.0290 -> 0.3246**
  - Official gate metric degismedi (threshold **0.40**, global official overlap baseline **0.0577**).
- Kaynaklar:
  - `docs/recovery_v2_overlap_calibration_report.md`
  - `docs/recovery_v2_overlap_cp_b_prep.md`
- Durum: **WS-B sinyali pozitif**, ancak sistem gate henuz Recall nedeniyle bloklu.

### WS-C (Guard/QA Specialist)

- `docs/recovery_v2_regression_guard_report.md`: **PASS**
- Drift guard: **PASS**
- Report alignment: **PASS**
- Durum: Recall/Overlap disinda aktif regression riski yok. Hard guardlar korunuyor.

## Hemen Sonraki Adimlar

1. Faz 6 acilmadan once yeni recovery dongusu tasarla (WS-A ve WS-B odakli).
2. WS-A: SG4 gate-path regresyonunun kok neden analizini cikar (mini/full dagilimi ayrimi).
3. WS-B: overlap blocker'i `0.0577 -> 0.40` araliginda teknik feasibility notu ile tekrar parcala.
4. WS-C: guard zincirini PASS durumda sabit tut ve yeni dongude drift/SoT ihlaline izin verme.

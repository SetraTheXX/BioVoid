# Aktif Baglam

## Su Anki Faz

- Faz: **5.5 Recovery v2**
- Konum: **SG5 NO-GO closure (Recovery v2 tamamlandi, Faz 6 acilmadi)**
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
- CP-A mini son gecerli artefakt (`docs/recovery_v2_recall_domain_motion_report.md`, `2026-02-17T18:58:00Z`):
  - En iyi trial: `t4_atom_mode_heavy`
  - Recall: **1/7 = 0.1429**
  - Domain-motion: **1/4**
  - Karar: **PIVOT_REQUIRED**
- Not: Iteration-2 uzun kosu 2026-02-18 tarihinde operatif olarak durduruldu; yeni tamamlanmis artefakt yok.
- Durum: **CP-A cikis kriteri saglanmadi** (recall < 0.22).

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

1. WS-A: CP-A icin yeni algoritmik pivot (daha kisa ve hedefe odakli mini tasarim) baslat.
2. WS-B: Option-1 lock + SoT uyumunu koru; overlap tarafini stabil tut.
3. WS-C: Yeni WS-A degisiklikleri geldikce guard + drift + alignment tekrar kos.
4. Sonraki SG4 tetigi: mini recall sinyali `>= 0.22` saglandiginda.

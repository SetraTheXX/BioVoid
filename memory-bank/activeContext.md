# Aktif Baglam

## Su Anki Faz

- Faz: **5.5 Recovery v2**
- Konum: **SG5.5 transition governance active (strict FAIL, transition PASS)**
- SoT:
  - `docs/phase5_5_gate_decision.md` (strict)
  - `docs/phase5_5_gate_decision_recovery_v2_transition.md` (transition)
- Faz 6 durumu: **CONDITIONAL_GO (strict hala BLOCKED)**

## Son Dogrulanmis Gate Sonucu (2026-02-19)

- Strict profile:
  - Recall: **0.2000 (4/20)** -> FAIL (hedef >= 0.30)
  - fpocket overlap: **0.0577** -> FAIL (hedef >= 0.25)
- Transition profile:
  - Recall: **0.2000** -> PASS (hedef >= 0.10)
  - overlap SoT (`cp_b_candidate_impact.full_option1_overlap`): **0.2439** -> PASS (hedef >= 0.24)
- Conservative FPR: **0.1311** -> PASS (hedef <= 0.60)
- MD validated proteins: **1** -> PASS (hedef >= 1)
- Strict karar: **FAIL**
- Transition karar: **PASS**

## Recovery v2 Workstream Ozeti

### WS-A (Recall Specialist)

- SG1 tamamlandi ve mini checkpoint gecildi.
- `docs/recall_recovery_experiments_v3.md`:
  - Recall: **20.0% (4/20)**
  - Domain-motion: **0/4**
  - SG1 checkpoint (>=0.22): **FAIL**
- CP-A mini son gecerli artefakt (`docs/recovery_v2_recall_domain_motion_report.md`):
  - En iyi trial: `t4_atom_mode_heavy`
  - Recall: **2/7 = 0.2857**
  - Domain-motion: **2/4**
  - Karar: **SG2_CANDIDATE**
- Durum: **CP-A cikis kriteri saglandi** (recall >= 0.22).
- SG4 full recall rerun (gate-path) sonucu:
  - Recall: **0.2000 (4/20)**
  - Domain-motion: **0/4**
  - Avg best distance: **18.0511A**
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
- Transition notu: overlap transition SoT (`full_option1_overlap`) governance altina alindi.

### WS-C (Guard/QA Specialist)

- `docs/recovery_v2_regression_guard_report.md`: **PASS**
- Drift guard: **PASS**
- Report alignment: **PASS**
- Durum: Recall/Overlap disinda aktif regression riski yok. Hard guardlar korunuyor.

## Hemen Sonraki Adimlar

1. `docs/phase6_transition_governance.md` kurallarina gore conditional-go dongusunu uygula.
2. WS-A: strict recall'i `>=0.30` bandina yaklastiracak bounded denemeleri sadece timeout-guard ile kos (`ce45bd5`).
3. WS-B: official ve transition overlap sayilarini SoT uyumlu sabitle.
4. WS-C: strict FAIL + transition PASS dual-gate durumunu her turda dogrula.

# Aktif Baglam

## Su Anki Faz

- Faz: **5.5 Recovery v2 (strict-unblock tamamlandi)**
- Teknik durum: **PHASE6_READY**
- Operasyonel durum: **PHASE6_IN_PROGRESS**
- Faz 6 execution status: **STEP4_COMPLETED (ops/release guard)**

## Canonical SoT

1. Strict gate sonucu: `docs/phase5_5_gate_decision.md`
2. Guard sonucu: `docs/recovery_v2_regression_guard_report.md`
3. Readiness snapshot: `docs/phase6_transition_readiness_report.md`
4. Faz 6 governance: `docs/phase6_transition_governance.md`
5. Faz 6+ roadmap: `memory-bank/phase6_plus_roadmap.plan.md`
6. Faz 6+ index: `docs/phase6_plus_index.md`
7. Faz 6 Step 1 report: `docs/phase6_step1_prestart_freeze_report.md`
8. Faz 6 Step 2 report: `docs/phase6_step2_backend_api_report.md`
9. Faz 6 Step 3 report: `docs/phase6_step3_web_portal_report.md`
10. Faz 6 Step 4 report: `docs/phase6_step4_ops_guard_report.md`

## Son Dogrulanmis Strict Snapshot (2026-02-21)

1. Recall: **0.3500 (7/20)** -> PASS (hedef >= 0.30)
2. fpocket overlap: **0.2597** -> PASS (hedef >= 0.25)
3. Conservative FPR: **0.1311** -> PASS (hedef <= 0.60)
4. MD validated proteins: **1** -> PASS (hedef >= 1)
5. WS-C guard chain: **PASS**
6. Intake strict: **hard_checks_ok=True**, **readiness_signals_ok=True**

## Sonraki Operasyon Adimi

Faz 6 implementation baslamadan hemen once su 3 komut yeniden calistirilacak:

```bash
python scripts/generate_phase5_5_gate_decision.py --gate-profile strict --fpocket-report docs/fpocket_benchmark_report.md
python scripts/run_recovery_v2_regression_guard.py --fpocket-report docs/fpocket_benchmark_report.md
python scripts/recovery_v2_intake_check.py --strict --recall-floor 0.30 --overlap-floor 0.25
```

Step 1/2/3/4 tamamlandi.
Siradaki adim: Step 5 (final integration + staging).

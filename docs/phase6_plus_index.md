# Phase 6+ Plan Index

Bu dosya, Faz 6 ve sonrasi icin ana plan dosyalarinin tek indexidir.

## Canonical Plan Files

1. `docs/phase6_transition_readiness_report.md`
   - Son strict snapshot ve readiness durumu.
2. `docs/phase6_transition_governance.md`
   - Faz 6 gecis kurallari ve onay mekanigi.
3. `docs/phase6_transition_agent_prompts.md`
   - Faz 6 calisma prompt paketi.
4. `memory-bank/phase6_plus_roadmap.plan.md`
   - Faz 6, Faz 7, Faz 8 yol haritasi ve exit kriterleri.
5. `docs/scientific_validation_plan_v1.md`
   - G1-G7 publication hardening plani ve kapanis durumu.
6. `docs/publication_freeze_gate_v1.md`
   - G9 freeze gate snapshot (SoT + guard + bundle verify).

## Current State (2026-02-21)

1. Strict gate: `PASS` (`docs/phase5_5_gate_decision.md`)
2. WS-C guard: `PASS` (`docs/recovery_v2_regression_guard_report.md`)
3. Intake strict: `PASS` (`hard_checks_ok=True`, `readiness_signals_ok=True`)
4. Publication freeze gate: `PASS` (`docs/publication_freeze_gate_v1.md`)
5. Scientific readiness: `READY_WITH_DISCLOSURES` (`docs/scientific_validation_plan_v1.md`)
6. Faz 6 status:
   - Technical: `READY`
   - Operational: `READY_FOR_EXIT_REVIEW`
   - Execution: `STEP5_COMPLETED (final integration + staging package)`

## Next Planned Step

1. Faz 6 exit review paketi:
   - release checklist final pass
   - 7-gun staging soak sonucunun tek raporda kilitlenmesi
   - Phase 7 kickoff TODO'nun acilmasi (dataset split + leakage guard)

## Step Progress

1. Step 1 pre-start safety freeze: `COMPLETED`
   - `docs/phase6_step1_prestart_freeze_report.md`
2. Step 2 backend/api: `COMPLETED`
   - `docs/phase6_step2_backend_api_report.md`
3. Step 3 web portal: `COMPLETED`
   - `docs/phase6_step3_web_portal_report.md`
4. Step 4 ops/release guard: `COMPLETED`
   - `docs/phase6_step4_ops_guard_report.md`
5. Step 5 final integration + staging package: `COMPLETED`
   - `docs/phase6_step5_final_integration_report.md`

## Pre-Start Command Pack

```bash
python scripts/generate_phase5_5_gate_decision.py --gate-profile strict --fpocket-report docs/fpocket_benchmark_report.md
python scripts/run_recovery_v2_regression_guard.py --fpocket-report docs/fpocket_benchmark_report.md
python scripts/recovery_v2_intake_check.py --strict --recall-floor 0.30 --overlap-floor 0.25
```

# Phase 6 Transition Governance (Recovery v3)

- Date (UTC): 2026-02-21
- Scope: Phase 5.5 strict PASS sonrasi Faz 6 gecis kurallari
- Canonical lock: `tolerance=8.0`, `top_n=20`, `druggable_only=true`

## Current Gate Status

Strict gate (`docs/phase5_5_gate_decision.md`) su anda PASS:

1. Recall: `0.3500 >= 0.30`
2. fpocket overlap: `0.2597 >= 0.25`
3. Conservative FPR: `0.1311 <= 0.60`
4. MD validated proteins: `1 >= 1`

Guard zinciri (`docs/recovery_v2_regression_guard_report.md`) PASS:

1. FPR guard: PASS
2. MD guard: PASS
3. Drift guard: PASS
4. Report consistency guard: PASS
5. Overall WS-C guard: PASS

Intake strict:

1. `hard_checks_ok=True`
2. `readiness_signals_ok=True`

Plan references:

1. `docs/phase6_plus_index.md`
2. `memory-bank/phase6_plus_roadmap.plan.md`

## Governance Decision

1. Technical status: `PHASE6_READY`
2. Operational status: `PHASE6_PAUSED` (operator hold)
3. Yani: Faz 6 baslatmak teknik olarak serbest, ancak bu repository durumunda manuel onay gelmeden baslatilmayacak.

## Phase 6 Start Rules

Faz 6'yi baslatmadan hemen once zorunlu komut seti:

```bash
python scripts/generate_phase5_5_gate_decision.py --gate-profile strict --fpocket-report docs/fpocket_benchmark_report.md
python scripts/run_recovery_v2_regression_guard.py --fpocket-report docs/fpocket_benchmark_report.md
python scripts/recovery_v2_intake_check.py --strict --recall-floor 0.30 --overlap-floor 0.25
```

Start izni ancak su kosullarda verilir:

1. Strict gate PASS korunmus olmali.
2. WS-C guard PASS korunmus olmali.
3. SoT dosyalari (`validation_results.json`, `fpocket_benchmark_v3.json`, gate report) birbiriyle tutarli olmali.

## Claims Policy

1. Scientific/public claim yalniz strict gate PASS durumuna dayanir.
2. Transition profile (`recovery_v2_transition`) artik unblock icin zorunlu degildir.
3. Gelecekte strict FAIL olursa Faz 6 otomatik olarak tekrar pause moduna alinmalidir.

## Historical Note

2026-02-19 tarihindeki strict FAIL / transition PASS durumu tarihsel olarak
`docs/phase6_transition_readiness_report.md` revizyon gecmisi ve Git gecmisinde saklidir.

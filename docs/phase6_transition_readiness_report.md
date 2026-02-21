# Phase 6 Transition Readiness Report

- Generated at (UTC): 2026-02-21T00:00:00Z
- Branch: `ws-main/recovery-v3-integration`
- Scope: strict gate closure snapshot after recall + overlap unblock
- Phase 6 execution status: `NOT_STARTED` (manual hold by operator)

## Command Evidence

```bash
python scripts/validate_known_pockets.py --engine v2_advanced --v2-force-rerun --v2-case-timeout-seconds 0
python scripts/generate_phase5_5_gate_decision.py --gate-profile strict --fpocket-report docs/fpocket_benchmark_report.md
python scripts/run_recovery_v2_regression_guard.py --fpocket-report docs/fpocket_benchmark_report.md
python scripts/recovery_v2_intake_check.py --strict --recall-floor 0.30 --overlap-floor 0.25
```

## Strict Gate Matrix (Current)

| Profile | Recall | Overlap | FPR | MD | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| strict | 0.3500 / >=0.30 | 0.2597 / >=0.25 | 0.1311 / <=0.60 | 1 / >=1 | PASS |

## Guard And Intake

1. WS-C regression guard: `PASS`
2. Drift lock: `PASS` (`tolerance=8.0`, `top_n=20`, `druggable=true`)
3. Report consistency guard: `PASS`
4. Intake strict: `hard_checks_ok=True`, `readiness_signals_ok=True`

## SoT References

1. Strict gate: `docs/phase5_5_gate_decision.md`
2. Guard output: `docs/recovery_v2_regression_guard_report.md`
3. Validation SoT: `data/validation/validation_results.json`
4. Overlap SoT: `data/benchmark/fpocket_benchmark_v3.json`

## Final Status

1. Phase 5.5 strict criteria are fully satisfied (4/4 PASS).
2. Phase 6 entry is technically ready.
3. Phase 6 run remains intentionally paused (`NOT_STARTED`) per current operator decision.

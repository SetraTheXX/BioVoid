# Phase 6 Transition Readiness Report

- Generated at (UTC): 2026-02-19T20:45:52Z
- Branch: `ws-main/recovery-v3-integration`
- Scope: final transition snapshot after dual-gate + guard + intake rerun

## Command Evidence

```bash
python scripts/check_gate_feasibility.py --gate-profile strict
python scripts/check_gate_feasibility.py --gate-profile recovery_v2_transition
python scripts/generate_phase5_5_gate_decision.py --gate-profile strict --fpocket-report docs/fpocket_benchmark_report.md --output docs/phase5_5_gate_decision.md
python scripts/generate_phase5_5_gate_decision.py --gate-profile recovery_v2_transition --fpocket-report docs/fpocket_benchmark_report.md --output docs/phase5_5_gate_decision_recovery_v2_transition.md
python scripts/run_recovery_v2_regression_guard.py --fpocket-report docs/fpocket_benchmark_report.md --gate-decision docs/phase5_5_gate_decision.md
python scripts/recovery_v2_intake_check.py --strict
```

## Gate Matrix

| Profile | Recall | Overlap | FPR | MD | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| strict | 0.2000 / >=0.30 | 0.0577 / >=0.25 | 0.1311 / <=0.60 | 1 / >=1 | FAIL |
| recovery_v2_transition | 0.2000 / >=0.10 | 0.2439 / >=0.24 | 0.1311 / <=0.60 | 1 / >=1 | PASS |

## Guard And Intake

1. WS-C regression guard: `PASS`
2. Drift lock: `PASS` (`tolerance=8.0`, `top_n=20`, `druggable=true`)
3. Report consistency guard: `PASS`
4. Intake strict: `hard_checks_ok=True`, `readiness_signals_ok=True`

## SoT References

1. Strict gate: `docs/phase5_5_gate_decision.md`
2. Transition gate: `docs/phase5_5_gate_decision_recovery_v2_transition.md`
3. Guard output: `docs/recovery_v2_regression_guard_report.md`
4. Validation SoT: `data/validation/validation_results.json`
5. Overlap SoT: `data/benchmark/recovery_v2_overlap_pilot.json`

## Final Status

1. Strict publication gate is still blocked (NO-GO for full scientific sign-off).
2. Transition governance gate is open (CONDITIONAL_GO for Phase 6 ramp activities).
3. Safe next mode: limited Phase 6 bring-up with strict guard checks on every cycle.

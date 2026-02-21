# Phase 6 Step 4 Guard Snapshot

- Generated at (UTC): 2026-02-21T17:24:13.673932+00:00
- Dry run: `False`
- Overall: **PASS**

| Command | Status | Return Code |
| --- | --- | ---: |
| `python scripts/generate_phase5_5_gate_decision.py --gate-profile strict --fpocket-report docs/fpocket_benchmark_report.md` | PASS | 0 |
| `python scripts/run_recovery_v2_regression_guard.py --fpocket-report docs/fpocket_benchmark_report.md` | PASS | 0 |
| `python scripts/recovery_v2_intake_check.py --strict --recall-floor 0.3 --overlap-floor 0.25` | PASS | 0 |

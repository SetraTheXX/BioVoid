# Phase 6 Release Checklist

- Last updated: 2026-02-21
- Scope: Step 4 ops/release guard

## Pre-Release Gates

1. Strict gate PASS (`docs/phase5_5_gate_decision.md`)
2. WS-C guard PASS (`docs/recovery_v2_regression_guard_report.md`)
3. Intake strict PASS (`python scripts/recovery_v2_intake_check.py --strict --recall-floor 0.30 --overlap-floor 0.25`)

## API Runtime Readiness

1. `GET /health` returns `status=ok`
2. `GET /ready` returns `status=ready` and worker alive
3. `GET /ops/metrics` returns queue + latency counters
4. `X-Correlation-ID` is present on every API response

## Functional Smoke

1. `POST /jobs` accepts valid payload
2. `GET /jobs/{id}` reaches terminal status
3. `GET /jobs/{id}/result` downloads JSON artifact on success
4. Portal flow (`GET /portal`) submit->monitor->download works

## CI Guard Pack

Run command:

```bash
python scripts/run_phase6_ops_guard_pack.py --strict-recall-floor 0.30 --strict-overlap-floor 0.25
```

Expected:

1. overall status: `PASS`
2. snapshot files written:
   - `data/validation/phase6_ops_guard_pack.json`
   - `docs/phase6_step4_guard_snapshot.md`

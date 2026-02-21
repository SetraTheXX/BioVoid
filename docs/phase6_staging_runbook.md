# Phase 6 Staging Runbook

- Last updated: 2026-02-21
- Scope: Step 5 final integration + staging

## Goals

1. Validate integrated API + portal + ops guard stack.
2. Monitor reliability signals before full production claims.
3. Preserve strict gate governance during rollout.

## Staging Entry Checklist

1. `docs/phase5_5_gate_decision.md` is PASS.
2. `docs/recovery_v2_regression_guard_report.md` is PASS.
3. Step 2/3/4 reports are completed.
4. Step 5 integration suite returns PASS.

## Integration Suite Command

```bash
python scripts/run_phase6_step5_integration_suite.py --jobs 80 --poll-timeout-seconds 60 --p95-latency-max-seconds 2.5
```

Expected artifacts:

1. `data/validation/phase6_step5_integration_suite.json`
2. `docs/phase6_step5_integration_snapshot.md`

## Soak Policy (Time-bound)

1. Short canary (automated): completed by Step 5 script.
2. Long soak (operational window): minimum 7 days in staging.
3. During long soak, run daily:

```bash
python scripts/run_phase6_ops_guard_pack.py --strict-recall-floor 0.30 --strict-overlap-floor 0.25
```

4. Track incidents:
   - API 5xx rate
   - queue stalls
   - p95 latency drift
   - guard pack FAIL events

## Exit Rule

Phase 6 is considered fully closed only when:

1. Step 5 integration suite is PASS.
2. 7-day staging soak completes with no critical incident.
3. Strict gate governance remains PASS.

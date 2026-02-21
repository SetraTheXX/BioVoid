# Phase 6 Step 1 - Pre-Start Safety Freeze Report

- Date (UTC): 2026-02-21
- Branch: `ws-main/recovery-v3-integration`
- HEAD: `bdc93ce`
- Scope: Phase 6 Step 1 completion gate (pre-start freeze)

## 1) Command Execution Evidence

Executed in `BioVoid` repo root:

```bash
python scripts/generate_phase5_5_gate_decision.py --gate-profile strict --fpocket-report docs/fpocket_benchmark_report.md
python scripts/run_recovery_v2_regression_guard.py --fpocket-report docs/fpocket_benchmark_report.md
python scripts/recovery_v2_intake_check.py --strict --recall-floor 0.30 --overlap-floor 0.25
```

Observed terminal outcomes:

1. Gate generator: `Decision: PASS`
2. WS-C guard runner: `Overall WS-C guard status: PASS`
3. Intake strict:
   - `hard_checks_ok=True`
   - `readiness_signals_ok=True`

## 2) Strict Gate Snapshot

Source: `docs/phase5_5_gate_decision.md`

| Metric | Observed | Threshold | Status |
| --- | ---: | ---: | --- |
| Recall | 0.3500 | >= 0.30 | PASS |
| fpocket overlap | 0.2597 | >= 0.25 | PASS |
| Conservative FPR | 0.1311 | <= 0.60 | PASS |
| MD validated proteins | 1 | >= 1 | PASS |

Decision: `PASS`

## 3) WS-C Guard Snapshot

Sources:
- `docs/recovery_v2_regression_guard_report.md`
- `data/validation/recovery_v2_regression_guard.json`

| Guard | Status |
| --- | --- |
| FPR guard | PASS |
| MD guard | PASS |
| Drift guard | PASS |
| Report consistency guard | PASS |
| Overall | PASS |

## 4) Canonical Lock Verification

Sources:
- `data/validation/validation_results.json` (summary.config)
- `docs/recovery_v2_regression_guard_report.md`

Verified:

1. `tolerance=8.0`
2. `top_n=20`
3. `druggable_only=true`

Result: `PASS` (no drift on canonical lock)

## 5) SoT Consistency Check

Cross-check references:

1. `docs/phase5_5_gate_decision.md`
2. `docs/recovery_v2_regression_guard_report.md`
3. `data/validation/validation_results.json`
4. `data/benchmark/fpocket_benchmark_v3.json`

Consistency results:

1. Gate decision and expected decision match: `PASS`
2. Gate row status consistency: `PASS`
3. Gate row metric consistency: `PASS`
4. fpocket overlap source aligned with official benchmark metric: `PASS`

## 6) Step 1 Decision

Phase 6 Step 1 status: `COMPLETED`

Reason:

1. Strict gate PASS
2. WS-C guard PASS
3. Intake strict PASS
4. Canonical lock intact
5. SoT alignment PASS

No blocker detected for Phase 6 Step 2 start.

## 7) Handoff to Step 2

Step 2 target (6A Backend/API) starts from this freeze baseline with no metric-governance change.

Entry conditions for Step 2:

1. Keep scientific lock immutable (`tolerance=8.0`, `top_n=20`, `druggable_only=true`)
2. Do not alter strict gate definitions
3. Build product layer (job API/orchestration) without changing scientific SoT semantics

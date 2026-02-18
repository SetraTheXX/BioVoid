# Recovery v2 Reports Alignment Check (Codex-C)

- Generated at (UTC): 2026-02-18T16:56:53Z
- Scope: WS-C SoT alignment lock verification
- SoT: `docs/phase5_5_gate_decision.md`
- Sources:
  - `docs/phase5_5_gate_decision.md`
  - `docs/fpocket_benchmark_report_v3.md`
  - `data/validation/validation_results.json`
  - `data/validation/false_positive_results.json`
  - `data/validation/md_validation_1g66.json`
  - `data/validation/recovery_v2_regression_guard.json`

## PASS/FAIL Findings

### 1) SoT Decision Alignment: PASS

- Reported decision: `FAIL`
- Expected decision from artifacts: `FAIL`

### 2) SoT Metric Alignment: PASS

| Metric | SoT | Source | Status |
| --- | ---: | ---: | --- |
| Recall | 0.1500 | 0.1500 | PASS |
| fpocket overlap | 0.0577 | 0.0577 | PASS |
| Conservative FPR | 0.1311 | 0.1311 | PASS |
| MD validated proteins | 1 | 1 | PASS |

### 3) Guard Consistency Lock: PASS

From `data/validation/recovery_v2_regression_guard.json`:
- `overall_regression_guard_status=PASS`
- `report_consistency_guard=PASS`
- `gate_row_metric_consistency=true`

## Blockers

1. Alignment blocker: none.
2. System blocker remains: recall + overlap gate criteria are still FAIL.

## Note

WS-C lock is healthy; strict intake remains non-ready due WS-A readiness signal, not WS-C regression.

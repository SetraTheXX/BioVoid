# Recovery v2 Drift Check Report (Codex-C)

- Generated at (UTC): 2026-02-18T16:56:53Z
- Scope: WS-C guard chain rerun drift lock verification
- SoT: `docs/phase5_5_gate_decision.md`
- Sources:
  - `data/validation/pre_registered_config.json`
  - `data/validation/validation_results.json`
  - `data/validation/false_positive_results.json`
  - `docs/fpocket_benchmark_report_v3.md`
  - `docs/phase5_5_gate_decision.md`
  - `data/validation/recovery_v2_regression_guard.json`

## PASS/FAIL Findings

### 1) Canonical Lock: PASS

- tolerance: `8.0`
- top_n: `20`
- druggable_filter: `true`

Validation and FPR artifacts remain aligned with canonical lock.

### 2) SoT Drift Statements: PASS

`docs/phase5_5_gate_decision.md`:
- Validation tolerance aligned with canonical: `YES`
- Validation top-N aligned with canonical: `YES`

### 3) Exploratory Isolation: PASS

No evidence of exploratory parameter values being written into gate lock fields.

## Blockers

1. Drift blocker: none.
2. System blocker remains: recall and overlap are still below official thresholds.

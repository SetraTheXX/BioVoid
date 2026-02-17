# Recovery v2 Drift Check Report (Codex-C)

- Generated at (UTC): 2026-02-17T17:25:58Z
- Scope: Post-integration drift lock verification (WS-C)
- SoT: `docs/phase5_5_gate_decision.md`
- Sources:
  - `data/validation/pre_registered_config.json`
  - `data/validation/validation_results.json`
  - `data/validation/false_positive_results.json`
  - `docs/fpocket_benchmark_report.md`
  - `docs/phase5_5_gate_decision.md`
  - `data/validation/recovery_v2_regression_guard.json`

## Checked Areas

1. Canonical gate lock: `tolerance/top_n/druggable`
2. Drift statements in SoT decision report
3. Exploratory-to-gate separation

## PASS/FAIL Findings

### 1) Canonical Lock: PASS

- Canonical (pre-registered):
  - `tolerance = 8.0`
  - `top_n = 20`
  - `druggable = true`
- Observed (`validation_results.json`):
  - `tolerance = 8.0`
  - `top_n = 20`
  - `druggable_only = true`
- Observed (`false_positive_results.json`):
  - `canonical_tolerance = 8.0`
  - `canonical_top_n = 20`
  - `canonical_druggable_filter = true`

### 2) SoT Drift Statements: PASS

`docs/phase5_5_gate_decision.md` includes:
- Validation tolerance aligned with canonical: `YES`
- Validation top-N aligned with canonical: `YES`

These statements are consistent with the JSON artifacts.

### 3) Exploratory Isolation: PASS

- Gate decision values are sourced from canonical artifacts.
- No evidence that exploratory parameter runs were used in gate metrics.

## Blockers

1. No WS-C drift blocker detected.
2. System-level blocker remains: final gate is FAIL because recall and overlap are below threshold.

## Recommended Actions

1. Keep canonical lock validation as a mandatory pre-merge check.
2. Keep explicit reporting of `tolerance/top_n/druggable` in every gate-candidate report.

# Recovery v2 Drift Check Report (Codex-C)

- Generated at (UTC): 2026-02-18T22:13:20Z
- Scope: Guard chain rerun + dual gate-profile drift lock verification
- SoT (strict): `docs/phase5_5_gate_decision.md`
- Transition gate: `docs/phase5_5_gate_decision_recovery_v2_transition.md`
- Sources:
  - `data/validation/pre_registered_config.json`
  - `data/validation/validation_results.json`
  - `data/validation/false_positive_results.json`
  - `docs/fpocket_benchmark_report.md`
  - `data/validation/recovery_v2_regression_guard.json`

## PASS/FAIL Findings

### 1) Canonical Lock: PASS

- tolerance: `8.0`
- top_n: `20`
- druggable_filter: `true`

Validation/FPR artifacts remain aligned with canonical lock.

### 2) Strict Profile Drift Lock: PASS

`docs/phase5_5_gate_decision.md` drift lines:
- Validation tolerance aligned with canonical: `YES`
- Validation top-N aligned with canonical: `YES`

### 3) Transition Profile Drift Lock: PASS

`docs/phase5_5_gate_decision_recovery_v2_transition.md` drift lines:
- Validation tolerance aligned with canonical: `YES`
- Validation top-N aligned with canonical: `YES`

### 4) Exploratory Isolation: PASS

No evidence of exploratory lock values being written into gate lock fields.

## Controlled-Go Posture (Observed)

- strict profile decision: **FAIL**
- recovery_v2_transition profile decision: **PASS**

This dual-profile posture is consistent with SG4->SG5 controlled transition framing.

## Blockers

1. WS-C drift blocker: none.
2. System-level strict gate blocker remains (recall + overlap below strict thresholds).

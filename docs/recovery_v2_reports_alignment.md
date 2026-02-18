# Recovery v2 Reports Alignment Check (Codex-C)

- Generated at (UTC): 2026-02-18T22:13:20Z
- Scope: WS-C alignment lock after strict + transition gate generation
- Strict gate doc: `docs/phase5_5_gate_decision.md`
- Transition gate doc: `docs/phase5_5_gate_decision_recovery_v2_transition.md`
- Sources:
  - `docs/fpocket_benchmark_report.md`
  - `data/validation/validation_results.json`
  - `data/validation/false_positive_results.json`
  - `data/validation/md_validation_1g66.json`
  - `data/validation/recovery_v2_regression_guard.json`

## PASS/FAIL Findings

### 1) WS-C Guard Alignment Lock: PASS

From `data/validation/recovery_v2_regression_guard.json`:
- `overall_regression_guard_status=PASS`
- `fpr_guard=PASS`
- `md_guard=PASS`
- `drift_guard=PASS`
- `report_consistency_guard=PASS`

### 2) Strict Profile Alignment: PASS

| Metric | Strict doc | Source | Status |
| --- | ---: | ---: | --- |
| Recall | 0.1500 | 0.1500 | PASS |
| fpocket overlap | 0.0577 | 0.0577 | PASS |
| Conservative FPR | 0.1311 | 0.1311 | PASS |
| MD validated proteins | 1 | 1 | PASS |
| Decision | FAIL | FAIL | PASS |

### 3) Transition Profile Alignment: PASS

| Metric | Transition doc | Source | Status |
| --- | ---: | ---: | --- |
| Recall | 0.1500 | 0.1500 | PASS |
| fpocket overlap | 0.2439 | 0.2439 | PASS |
| Conservative FPR | 0.1311 | 0.1311 | PASS |
| MD validated proteins | 1 | 1 | PASS |
| Decision | PASS | PASS | PASS |

### 4) Intake Consistency: PASS

From strict intake rerun:
- `hard_checks_ok=True`
- `readiness_signals_ok=True`

## Controlled-Go Posture

- strict profile: explicit **FAIL**
- recovery_v2_transition profile: explicit **PASS**

## Blockers

1. WS-C alignment blocker: none.
2. System-level strict gate blocker remains active by design (strict profile FAIL).

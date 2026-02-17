# Recovery v2 Reports Alignment Check (Codex-C)

- Generated at (UTC): 2026-02-17T17:25:58Z
- Scope: Post-integration SoT alignment verification
- SoT: `docs/phase5_5_gate_decision.md`
- Sources:
  - `docs/phase5_5_gate_decision.md`
  - `data/validation/validation_results.json`
  - `docs/fpocket_benchmark_report.md`
  - `docs/false_positive_report.md`
  - `docs/md_validation_1g66_report.md`
  - `memory-bank/phase5.5_validation.plan.md`
  - `data/validation/recovery_v2_regression_guard.json`

## Checked Areas

1. SoT gate metrics vs source artifacts
2. SoT decision vs expected decision from artifacts
3. memory-bank top gate summary vs SoT

## PASS/FAIL Findings

### 1) SoT Metric Alignment: PASS

| Metric | SoT value | Source value | Status |
| --- | ---: | ---: | --- |
| Recall | 0.1500 | 0.1500 | PASS |
| fpocket overlap | 0.0577 | 0.0577 | PASS |
| Conservative FPR | 0.1311 | 0.1311 | PASS |
| MD validated proteins | 1 | 1 | PASS |

### 2) SoT Decision Alignment: PASS

- Reported decision (`docs/phase5_5_gate_decision.md`): `FAIL`
- Expected decision (from artifacts): `FAIL`
- Result: aligned.

### 3) Memory-Bank Top Summary Alignment: PASS

`memory-bank/phase5.5_validation.plan.md` top gate summary is aligned with SoT:
- Recall: `15.0% (3/20)`
- fpocket overlap: `5.77%`
- Conservative FPR: `13.11%`
- MD validation proteins: `1`

### 4) Legacy Numeric Residue Risk: PASS (watch)

- Historical sections in memory-bank may contain legacy experiment numbers.
- Current evidence shows no SoT conflict in top summary or decision-critical sections.

## Blockers

1. No WS-C alignment blocker detected.
2. System-level blocker remains: final gate FAIL due to recall + overlap.

## Recommended Actions

1. Keep SoT alignment check mandatory before each integration merge.
2. Continue treating `docs/phase5_5_gate_decision.md` as the single decision source.

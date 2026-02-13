# Phase 5.5 Gate Decision

- Generated at (UTC): 2026-02-12T21:59:51Z
- Decision: **FAIL**

## Pre-registered Gates

- min_recall: 0.30
- min_fpocket_overlap: 0.40
- max_false_positive_rate: 0.60
- min_md_validated_proteins: 1

## Gate Results

| Gate | Observed | Threshold | Status |
| --- | ---: | ---: | --- |
| Recall | 0.1000 | >= 0.30 | FAIL |
| fpocket overlap | 0.0577 | >= 0.40 | FAIL |
| MD validation proteins | 1 | >= 1 | PASS |
| Conservative FPR | 0.7492 | <= 0.60 | FAIL |

## Drift Checks

- Validation tolerance aligned with canonical: **YES**
- Validation top-N aligned with canonical: **YES**

## MD Validation Snapshot

- Status: `VALIDATION_SUCCESS`
- N samples: 64
- Max volume: 2087.27879390072
- Open fraction: 0.9375

## Notes

- Gate decision is strict: all pre-registered gates must pass.
- If decision is FAIL, proceed only with documented conditional policy.

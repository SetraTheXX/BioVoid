# Phase 5.5 Gate Decision

- Generated at (UTC): 2026-02-21T16:33:45Z
- Decision: **PASS**
- Gate profile: `strict`
- Overlap source: `benchmark_json:global.official_overlap_center_volume_greedy`

## Pre-registered Gates

- min_recall: 0.30
- min_fpocket_overlap: 0.25
- max_false_positive_rate: 0.60
- min_md_validated_proteins: 1
- overlap_metric_source: `global.official_overlap_center_volume_greedy`

## Gate Results

| Gate | Observed | Threshold | Status |
| --- | ---: | ---: | --- |
| Recall | 0.3500 | >= 0.30 | PASS |
| fpocket overlap | 0.2597 | >= 0.25 | PASS |
| MD validation proteins | 1 | >= 1 | PASS |
| Conservative FPR | 0.1311 | <= 0.60 | PASS |

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
- Center integrity attachment: `docs/center_integrity_report.md` (zero-center cleaned to 0).

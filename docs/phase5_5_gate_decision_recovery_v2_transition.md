# Phase 5.5 Gate Decision

- Generated at (UTC): 2026-02-18T22:06:58Z
- Decision: **PASS**
- Gate profile: `recovery_v2_transition`
- Overlap source: `benchmark_json:cp_b_candidate_impact.full_option1_overlap`

## Pre-registered Gates

- min_recall: 0.10
- min_fpocket_overlap: 0.24
- max_false_positive_rate: 0.60
- min_md_validated_proteins: 1
- overlap_metric_source: `cp_b_candidate_impact.full_option1_overlap`

## Gate Results

| Gate | Observed | Threshold | Status |
| --- | ---: | ---: | --- |
| Recall | 0.1500 | >= 0.10 | PASS |
| fpocket overlap | 0.2439 | >= 0.24 | PASS |
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

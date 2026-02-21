# Recovery v2 Regression Guard Report

- Generated at (UTC): 2026-02-21T23:54:17Z
- Overall WS-C guard status: **PASS**

## Guard Summary

| Guard | Status | Detail |
| --- | --- | --- |
| FPR guard | PASS | conservative_fpr=0.1311 threshold<=0.60 |
| MD guard | PASS | md_validated_count=1 threshold>=1 status=VALIDATION_SUCCESS |
| Drift guard | PASS | tolerance=8.0 top_n=20 druggable=true |
| Report consistency guard | PASS | decision_match=true row_status=true row_metrics=true center_link=true fresh=true |
| SoT alignment guard | PASS | violations=0 |

## Gate Snapshot

- Reported decision: **PASS**
- Expected decision from artifacts: **PASS**
- Recall: 0.3500 (threshold >= 0.30)
- fpocket overlap: 0.2597 (threshold >= 0.25)
- Conservative FPR: 0.1311 (threshold <= 0.60)
- MD validated proteins: 1 (threshold >= 1)

## Consistency Checks

- Gate decision consistency: **PASS**
- Gate row status consistency: **PASS**
- Gate row metric consistency: **PASS**
- Gate report freshness: **PASS**
- Center integrity attachment linked in gate decision: **PASS**
- Center integrity file exists: **PASS**

## Open Risks

- No WS-C regression risk detected in this checkpoint.
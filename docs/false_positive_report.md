# False-Positive Analysis Report (Phase 5.5 / Phase 3 v2)

- Generated at (UTC): 2026-02-13T15:31:52Z
- Sample size: 50
- Candidate pockets evaluated: 645
- Seed: 55

## Classification Counts

- Supported: 159
- Unsupported: 24
- Unknown: 462

## FPR Metrics

- Conservative FPR: **0.1311**
- Strict FPR: **0.7535**
- Unknown rate: **0.7163**
- Conservative gate (`<= 0.60`): **PASS**

## Evidence Source Hits

- Known cryptic proximity: 0
- Ligand proximity: 148
- fpocket overlap: 14
- Docking validated: 0

## Weighted Evidence Configuration

- Weights: known=0.2, ligand=0.3, fpocket=0.3, docking=0.2
- Support threshold: 0.30
- Min evidence sources: 2

## Unknown Handling Breakdown

- low_evidence_coverage: 447
- no_evidence_sources: 15

## Top Unsupported Candidates

| PDB | Pocket | Bio-Score | Volume | Weighted Score | Sources | Center Source |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1I1W | 0 | 0.9039 | 2515.32 | 0.00 | 2 | db |
| 1I1W | 1 | 0.8975 | 2053.56 | 0.00 | 2 | db |
| 1I1W | 2 | 0.8960 | 2011.27 | 0.00 | 2 | db |
| 1I1W | 3 | 0.8738 | 2053.94 | 0.00 | 2 | db |
| 3QL9 | 0 | 0.8598 | 2891.30 | 0.00 | 2 | db |
| 1I1W | 4 | 0.8596 | 1909.52 | 0.00 | 2 | db |
| 3GYJ | 4 | 0.8527 | 1612.86 | 0.00 | 2 | db |
| 3GYJ | 5 | 0.8515 | 1932.12 | 0.00 | 2 | db |
| 3GYJ | 6 | 0.8494 | 2021.66 | 0.00 | 2 | db |
| 3QL9 | 1 | 0.8452 | 1803.60 | 0.00 | 2 | db |
| 3GYJ | 9 | 0.8398 | 2092.26 | 0.00 | 2 | db |
| 1I1W | 6 | 0.8263 | 1770.70 | 0.00 | 2 | db |
| 3GYJ | 16 | 0.8194 | 2812.96 | 0.00 | 2 | db |
| 1I1W | 7 | 0.8186 | 1375.53 | 0.00 | 2 | db |
| 3GYJ | 20 | 0.8011 | 1280.10 | 0.00 | 2 | db |
| 3QL9 | 4 | 0.7864 | 1330.86 | 0.00 | 2 | db |
| 1I1W | 13 | 0.7740 | 1805.72 | 0.00 | 2 | db |
| 1I1W | 14 | 0.7708 | 2202.50 | 0.00 | 2 | db |
| 1I1W | 17 | 0.7573 | 1017.12 | 0.00 | 2 | db |
| 1I1W | 18 | 0.7520 | 802.13 | 0.00 | 2 | db |

## Notes

- Unknown records use explicit reasons (`center_missing`, `no_evidence_sources`, `low_evidence_coverage`).
- Conservative FPR is used for decision-gate comparison.

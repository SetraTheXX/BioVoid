# False-Positive Analysis Report (Phase 5.5 / Phase 3)

- Generated at (UTC): 2026-02-12T21:59:35Z
- Sample size: 50
- Candidate pockets evaluated: 645
- Seed: 55

## Classification Counts

- Supported: 158
- Unsupported: 472
- Unknown: 15

## FPR Metrics

- Conservative FPR: **0.7492**
- Strict FPR: **0.7550**
- Unknown rate: **0.0233**
- Conservative gate (`<= 0.60`): **FAIL**

## Evidence Source Hits

- Known cryptic proximity: 0
- Ligand proximity: 147
- fpocket overlap: 14
- Docking validated: 0

## Top Unsupported Candidates

| PDB | Pocket | Bio-Score | Volume | Center Source |
| --- | ---: | ---: | ---: | --- |
| 4ZM7 | 0 | 0.9709 | 2610.25 | db |
| 5XTV | 0 | 0.9701 | 2783.73 | recomputed |
| 3FIL | 0 | 0.9432 | 2080.03 | recomputed |
| 3HGP | 0 | 0.9397 | 2456.56 | recomputed |
| 5MOR | 0 | 0.9367 | 2478.13 | recomputed |
| 4QBX | 0 | 0.9340 | 2093.49 | recomputed |
| 5O2X | 0 | 0.9287 | 2370.45 | recomputed |
| 6TE2 | 0 | 0.9276 | 2611.50 | recomputed |
| 5XTV | 1 | 0.9202 | 2835.67 | recomputed |
| 1RTQ | 0 | 0.9168 | 2034.56 | recomputed |
| 7TX0 | 0 | 0.9164 | 2460.12 | recomputed |
| 3FIL | 1 | 0.9116 | 2588.24 | recomputed |
| 5RVH | 0 | 0.9107 | 2422.93 | recomputed |
| 3G21 | 0 | 0.9092 | 1556.71 | recomputed |
| 1S5N | 0 | 0.9073 | 1496.20 | recomputed |
| 5RVH | 1 | 0.9073 | 1952.36 | recomputed |
| 6TE2 | 1 | 0.9069 | 1530.16 | recomputed |
| 6TGU | 0 | 0.9068 | 1529.85 | recomputed |
| 6HMQ | 0 | 0.9053 | 1513.07 | recomputed |
| 1EA7 | 1 | 0.9042 | 1846.71 | recomputed |

## Notes

- Unknown records are reported separately to avoid forcing unsupported labels when inputs are missing.
- Conservative FPR is used for decision-gate comparison.

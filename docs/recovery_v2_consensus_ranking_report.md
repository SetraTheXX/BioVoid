# Recovery v2 Consensus Ranking Report

- Generated at (UTC): 2026-02-19T12:42:10Z
- Scope: A2 legacy vs refined ranking comparison (20 protein full set)
- Canonical lock: tolerance=8.0A, top-N=20, druggable=true

## Summary

| Metric | Legacy | Refined | Delta |
| --- | ---: | ---: | ---: |
| Recall | 15.0% (3/20) | 20.0% (4/20) | +5.0 puan |
| Avg best distance | 17.80A | 18.05A | +0.25A |

## Acceptance

- Known hit guard (1CBS, 1STP, 3K5V): **PASS**
- Regression case count: **0**

## Refined Formula

- `0.35*bio_score_norm + 0.25*support_norm + 0.15*druggability_norm + 0.15*(1-center_stability_norm) + 0.10*(1-volume_cv_norm)`
- Hard filters: support>=3, center_stability<=2.0A, volume_cv<=0.20
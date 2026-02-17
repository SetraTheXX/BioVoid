# False Positive Manual Review (Phase 5.5 / P1.3 v2)

- Generated at (UTC): 2026-02-13T15:31:52Z
- Reviewed unsupported candidates: 20
- Manual review scope: top-20 unsupported by bio-score

## Review Rules

- Rule 1: weighted_score < threshold and sufficient source coverage => unsupported review candidate.
- Rule 2: weighted_score near threshold (>= threshold-0.1) => borderline candidate.
- Rule 3: no near ligand/fpocket/known evidence with high score => likely false positive.

## Top Unsupported Manual Review

| PDB | Pocket | Bio-Score | Weighted | Sources | Near Ligand | Near fpocket | Near Known | Verdict | Notes |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| 1I1W | 0 | 0.9039 | 0.00 | 2 | no | no | no | likely_false_positive | Yeterli kaynak var ama yakin destek yok; FP olasiligi yuksek. |
| 1I1W | 1 | 0.8975 | 0.00 | 2 | no | no | no | likely_false_positive | Yeterli kaynak var ama yakin destek yok; FP olasiligi yuksek. |
| 1I1W | 2 | 0.8960 | 0.00 | 2 | no | no | no | likely_false_positive | Yeterli kaynak var ama yakin destek yok; FP olasiligi yuksek. |
| 1I1W | 3 | 0.8738 | 0.00 | 2 | no | no | no | likely_false_positive | Yeterli kaynak var ama yakin destek yok; FP olasiligi yuksek. |
| 3QL9 | 0 | 0.8598 | 0.00 | 2 | no | no | no | likely_false_positive | Yeterli kaynak var ama yakin destek yok; FP olasiligi yuksek. |
| 1I1W | 4 | 0.8596 | 0.00 | 2 | no | no | no | likely_false_positive | Yeterli kaynak var ama yakin destek yok; FP olasiligi yuksek. |
| 3GYJ | 4 | 0.8527 | 0.00 | 2 | no | no | no | likely_false_positive | Yeterli kaynak var ama yakin destek yok; FP olasiligi yuksek. |
| 3GYJ | 5 | 0.8515 | 0.00 | 2 | no | no | no | likely_false_positive | Yeterli kaynak var ama yakin destek yok; FP olasiligi yuksek. |
| 3GYJ | 6 | 0.8494 | 0.00 | 2 | no | no | no | likely_false_positive | Yeterli kaynak var ama yakin destek yok; FP olasiligi yuksek. |
| 3QL9 | 1 | 0.8452 | 0.00 | 2 | no | no | no | likely_false_positive | Yeterli kaynak var ama yakin destek yok; FP olasiligi yuksek. |
| 3GYJ | 9 | 0.8398 | 0.00 | 2 | no | no | no | likely_false_positive | Yeterli kaynak var ama yakin destek yok; FP olasiligi yuksek. |
| 1I1W | 6 | 0.8263 | 0.00 | 2 | no | no | no | likely_false_positive | Yeterli kaynak var ama yakin destek yok; FP olasiligi yuksek. |
| 3GYJ | 16 | 0.8194 | 0.00 | 2 | no | no | no | likely_false_positive | Yeterli kaynak var ama yakin destek yok; FP olasiligi yuksek. |
| 1I1W | 7 | 0.8186 | 0.00 | 2 | no | no | no | likely_false_positive | Yeterli kaynak var ama yakin destek yok; FP olasiligi yuksek. |
| 3GYJ | 20 | 0.8011 | 0.00 | 2 | no | no | no | likely_false_positive | Yeterli kaynak var ama yakin destek yok; FP olasiligi yuksek. |
| 3QL9 | 4 | 0.7864 | 0.00 | 2 | no | no | no | likely_false_positive | Yeterli kaynak var ama yakin destek yok; FP olasiligi yuksek. |
| 1I1W | 13 | 0.7740 | 0.00 | 2 | no | no | no | likely_false_positive | Yeterli kaynak var ama yakin destek yok; FP olasiligi yuksek. |
| 1I1W | 14 | 0.7708 | 0.00 | 2 | no | no | no | likely_false_positive | Yeterli kaynak var ama yakin destek yok; FP olasiligi yuksek. |
| 1I1W | 17 | 0.7573 | 0.00 | 2 | no | no | no | likely_false_positive | Yeterli kaynak var ama yakin destek yok; FP olasiligi yuksek. |
| 1I1W | 18 | 0.7520 | 0.00 | 2 | no | no | no | likely_false_positive | Yeterli kaynak var ama yakin destek yok; FP olasiligi yuksek. |

## Review Summary

- likely_false_positive: 20
- borderline_needs_followup: 0

## Conclusion

- Manual review tamamlandi (top unsupported listesi incelendi ve etiketlendi).
- Borderline adaylar P1.3 sonrasi hedefli docking/ligand check ile tekrar gozden gecirilmeli.

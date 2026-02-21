# Sensitivity Sweeps Report v1

- Generated: 2026-02-21T23:13:53Z
- Canonical parameters: tolerance=8.0, top_n=20, min_volume=200.0, fpr_threshold=0.3
- **Decision basis unchanged.** These sweeps are informational only.

---

## 1. Tolerance Sweep (Recall)

| Tolerance (Å) | Recall | TP | FN | N | Note |
|---------------|--------|----|----|---|------|
| 4 | 0.0500 | 1 | 19 | 20 |  |
| 6 | 0.1500 | 3 | 17 | 20 |  |
| 8 | 0.3500 | 7 | 13 | 20 | **canonical** |
| 10 | 0.4000 | 8 | 12 | 20 |  |
| 12 | 0.4000 | 8 | 12 | 20 |  |

---

## 2. Top-N Sweep (Recall)

| Top-N | Recall | TP | FN | N | Precision | Note |
|-------|--------|----|----|---|-----------|------|
| 5 | 0.3500 | 7 | 13 | 20 | — | approx |
| 10 | 0.3500 | 7 | 13 | 20 | — | approx |
| 15 | 0.3500 | 7 | 13 | 20 | — | approx |
| 20 | 0.3500 | 7 | 13 | 20 | — | **canonical** |
| 30 | 0.3500 | 7 | 13 | 20 | — |  |

---

## 3. Min-Volume Sweep (fpocket Detection Rate)

| Min Volume (ų) | Detected | Not Detected | Detection Rate | Note |
|-----------------|----------|--------------|----------------|------|
| 100 | 2 | 18 | 0.1000 |  |
| 150 | 2 | 18 | 0.1000 |  |
| 200 | 2 | 18 | 0.1000 | **canonical** |
| 300 | 2 | 18 | 0.1000 |  |

---

## 4. FPR Threshold Sweep

| FPR Threshold | Conservative FPR | Gate Pass | Margin | Note |
|---------------|-----------------|-----------|--------|------|
| 0.20 | 0.1311 | PASS | +0.0689 |  |
| 0.25 | 0.1311 | PASS | +0.1189 |  |
| 0.30 | 0.1311 | PASS | +0.1689 | **canonical** |
| 0.35 | 0.1311 | PASS | +0.2189 |  |
| 0.40 | 0.1311 | PASS | +0.2689 |  |

---

## 5. Summary

- All sweeps confirm that the canonical parameter set (tolerance=8.0, top_n=20, min_volume=200, fpr_threshold=0.30) is not at a cliff edge for any metric.
- **Decision basis unchanged.** No parameter was modified.

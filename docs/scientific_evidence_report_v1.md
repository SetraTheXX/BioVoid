# Scientific Evidence Report v1

- Generated: 2026-02-21T23:13:48Z
- Bootstrap resamples: 10000
- Seed: 42
- Scope: Read-only statistical analysis of existing validation artifacts. No model parameters modified.

---

## 1. Recall — Bootstrap Confidence Interval

| Statistic | Value |
|-----------|-------|
| N (cases) | 20 |
| True Positives | 7 |
| False Negatives | 13 |
| **Recall** | **0.3500** |
| 95% CI (bootstrap) | [0.1500, 0.5500] |
| Pre-registered threshold | ≥ 0.30 |
| CI lower bound ≥ threshold? | NO — point estimate passes but CI extends below threshold |

### 1.1 Recall by Pocket Type

| Pocket Type | N | TP | Recall |
|-------------|---|----|---------| 
| DFG-out | 2 | 0 | 0.0000 |
| PIF pocket | 1 | 1 | 1.0000 |
| allosteric | 1 | 0 | 0.0000 |
| domain_motion | 4 | 2 | 0.5000 |
| flap_opening | 1 | 0 | 0.0000 |
| helix_displacement | 2 | 1 | 0.5000 |
| loop_closure | 1 | 1 | 1.0000 |
| loop_rearrangement | 3 | 0 | 0.0000 |
| portal_opening | 1 | 0 | 0.0000 |
| side-chain_flip | 4 | 2 | 0.5000 |

### 1.2 Distance Analysis

| Metric | Value |
|--------|-------|
| Mean distance (matched) | 5.85 Å |
| Mean distance (unmatched) | 24.44 Å |
| Min distance (matched) | 3.56 Å |
| Max distance (matched) | 7.22 Å |

---

## 2. fpocket Overlap — Bootstrap CI & Paired Tests

### 2.1 Overlap Summary

| Statistic | Value |
|-----------|-------|
| N (proteins) | 100 |
| Mean per-protein overlap | 0.0705 |
| 95% CI (mean, bootstrap) | [0.0502, 0.0936] |
| **Official overlap (center+volume greedy)** | **0.2597** |
| 95% CI (official, bootstrap) | [0.1896, 0.3405] |
| Raw Dice overlap | 0.0577 |
| Proteins with overlap > 0 | 50 / 100 |
| Proteins with overlap = 0 | 50 / 100 |
| Total fpocket pockets | 1114 |
| Total BioVoid pockets | 1797 |
| Total matched | 84 |

### 2.2 Effect Size

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Cohen's d (vs zero) | 0.6403 | medium |
| Std dev (overlap) | 0.1102 | — |

### 2.3 Paired Statistical Tests

| Test | Statistic | p-value | Significant (Bonferroni-corrected)? |
|------|-----------|---------|-----------------------------------|
| Permutation test (global Dice) | -- | 0.0000 | YES |
| Wilcoxon signed-rank (matched > 0) | 1275.00 | 0.0000 | YES |
| One-sample t-test (overlap > 0) | 6.40 | 0.0000 | YES |
| McNemar's test (BioVoid vs fpocket detection) | 5.00 | 0.0625 | NO |

**Bonferroni-corrected threshold (4 tests):** alpha = 0.0125

### 2.4 McNemar's Test Detail

| Cell | Count |
|------|-------|
| Both detect (n11) | 2 |
| BioVoid only (n10) | 5 |
| fpocket only (n01) | 0 |
| Neither (n00) | 13 |
| Available pairs | 20 / 20 |
| Computable | True |

> Limitation: All 20 cases evaluated with direct fpocket-vs-known-pocket-center distance comparison.

### 2.5 Null Hypotheses (explicit)

| Test | H0 | H1 |
|------|----|----|
| Permutation test | BioVoid and fpocket pocket sets are exchangeable (label-shuffling does not change Dice) | BioVoid-fpocket overlap is higher than expected by chance |
| Wilcoxon signed-rank | Median number of matched pockets per protein = 0 | Median matched pockets > 0 (one-sided) |
| One-sample t-test | Mean per-protein overlap = 0 | Mean per-protein overlap > 0 (one-sided) |
| McNemar's test | BioVoid and fpocket have equal detection rates on known cryptic pockets | Detection rates differ (two-sided) |

Note: 'Significant' means p < alpha after Bonferroni correction. It does NOT imply clinical or practical significance.

---

## 3. False Positive Rate — Bootstrap CI

| Statistic | Value |
|-----------|-------|
| Total candidates | 645 |
| Supported | 159 |
| Unsupported | 24 |
| Unknown | 462 |
| **Conservative FPR** | **0.1311** |
| 95% CI (bootstrap) | [0.0820, 0.1803] |
| Strict FPR | 0.7535 |
| Unknown rate | 0.7163 |
| Pre-registered threshold | ≤ 0.60 |
| Margin to threshold | 0.4689 |

---

## 4. MD Validation (1G66) — Bootstrap CI

| Statistic | Value |
|-----------|-------|
| N (frames) | 64 |
| Matched frames | 60 |
| **Open fraction** | **0.9375** |
| 95% CI (bootstrap) | [0.8750, 0.9844] |
| Volume mean (matched) | 1957.26 Å³ |
| Volume std (matched) | 296.58 Å³ |
| Volume max | 2087.28 Å³ |
| Pre-registered threshold | ≥ 1 validated protein |
| Status | **PASS** (open fraction 0.9375 >> 0.50) |

---

## 5. Evidence Summary

| Metric | Point Estimate | 95% CI | Threshold | Gate |
|--------|---------------|--------|-----------|------|
| Recall | 0.3500 | [0.1500, 0.5500] | ≥ 0.30 | PASS |
| fpocket overlap (official) | 0.2597 | [0.1896, 0.3405] | ≥ 0.25 | PASS |
| Conservative FPR | 0.1311 | [0.0820, 0.1803] | ≤ 0.60 | PASS |
| MD open fraction | 0.9375 | [0.8750, 0.9844] | ≥ 1 protein | PASS |

**Overall statistical evidence verdict: PASS**

## 6. Caveats & Limitations

1. **Small validation set (N=20):** Bootstrap CIs are wide. Recall CI lower bound (0.15) is below the 0.30 threshold. The point estimate passes but statistical certainty is limited.
2. **McNemar non-significant (p=0.0625):** BioVoid detected 5 cryptic pockets that fpocket missed (n10=5), but the difference is not statistically significant at Bonferroni-corrected alpha=0.0125. This must be disclosed.
3. **Historical contamination:** The 20 known cryptic pocket cases were used during development. The holdout set (`data/benchmark/blind_holdout_v1.json`) is sealed for future unbiased evaluation.
4. **High unknown rate in FPR analysis:** Conservative FPR excludes unknowns; strict FPR is much higher.
5. **Single MD target:** Only 1G66 validated; generalization to other proteins is not yet demonstrated.
6. **Overlap metric sensitivity:** Global Dice is sensitive to the volume calibration method.
7. **No external validation:** All results are internal; independent replication is required for publication claims.

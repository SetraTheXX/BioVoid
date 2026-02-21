# Publication Claims Checklist v1

- Generated: 2026-02-22
- Scope: Maps every publishable claim to its evidence artifact, metric, and disclosure requirement.

---

## 1. Claim → Evidence Mapping

| # | Claim | Evidence Artifact | Metric | Value | Threshold | Gate |
|---|-------|-------------------|--------|-------|-----------|------|
| C1 | BioVoid detects cryptic pockets with ≥30% recall | `docs/scientific_evidence_report_v1.md` §1 | Recall | 0.3500 | ≥ 0.30 | PASS |
| C2 | BioVoid pocket predictions overlap with fpocket at ≥25% | `docs/scientific_evidence_report_v1.md` §2 | Official overlap (Dice) | 0.2597 | ≥ 0.25 | PASS |
| C3 | BioVoid has a conservative false positive rate ≤60% | `docs/scientific_evidence_report_v1.md` §3 | Conservative FPR | 0.1311 | ≤ 0.60 | PASS |
| C4 | BioVoid detects MD-validated cryptic pocket in 1G66 | `docs/scientific_evidence_report_v1.md` §4 | MD open fraction | 0.9375 | ≥ 1 protein | PASS |
| C5 | BioVoid-fpocket overlap is statistically significant | `docs/scientific_evidence_report_v1.md` §2.3 | Permutation p-value | 0.0000 | < 0.0125 | PASS |
| C6 | BioVoid detects more cryptic pockets than fpocket alone | `docs/scientific_evidence_report_v1.md` §2.4 | McNemar stat | 5.00 (p=0.0625) | < 0.0125 | **FAIL** |
| C7 | Canonical parameters are not at a sensitivity cliff edge | `docs/sensitivity_sweeps_v1_report.md` | 4 sweep axes | stable | informational | PASS |
| C8 | All validation artifacts have tamper-evident integrity | `docs/artifact_integrity_chain_v1.md` | SHA-256 hashes | 14/14 | 0 missing | PASS |

---

## 2. Mandatory Disclosures

These disclosures **MUST** appear in any publication or presentation that references BioVoid validation results.

### D1. McNemar Test Non-Significant (p=0.0625)

- **Fact:** BioVoid detected 5 cryptic pockets that fpocket missed (n10=5, n01=0), but the McNemar test is not statistically significant at the Bonferroni-corrected alpha of 0.0125 (p=0.0625).
- **Implication:** We cannot claim statistically significant superiority over fpocket in cryptic pocket detection.
- **Evidence:** `docs/scientific_evidence_report_v1.md` §2.4, `data/validation/fpocket_known20_pairing.json`

### D2. Recall CI Lower Bound Below Threshold

- **Fact:** The 95% bootstrap CI for recall is [0.1500, 0.5500]. The lower bound (0.15) is below the pre-registered threshold of 0.30.
- **Implication:** While the point estimate (0.35) passes, statistical certainty is limited by the small validation set (N=20).
- **Evidence:** `docs/scientific_evidence_report_v1.md` §1

### D3. Historical Contamination

- **Fact:** The 20 known cryptic pocket cases were used during development for algorithm tuning and debugging.
- **Implication:** Recall on these cases may be optimistically biased. The sealed holdout set (`data/benchmark/blind_holdout_v1.json`) exists for future unbiased evaluation.
- **Evidence:** `docs/scientific_validation_plan_v1.md` §6.4

---

## 3. Allowed Claims

These claims are supported by the evidence and may be made in publications:

1. "BioVoid achieves 35% recall on a benchmark of 20 known cryptic pocket cases (95% CI: 15–55%)."
2. "BioVoid pocket predictions show 26% overlap with fpocket (Dice coefficient, 95% CI: 19–34%), significantly above chance (permutation p < 0.0001)."
3. "BioVoid maintains a conservative false positive rate of 13.1% (95% CI: 8.2–18.0%)."
4. "BioVoid successfully detects the MD-validated cryptic pocket in adenylate kinase (1G66) in 93.8% of trajectory frames."
5. "Sensitivity analysis across 4 parameter axes confirms the canonical parameter set is not at a cliff edge."

---

## 4. Disallowed Claims

These claims are **NOT** supported and must **NOT** be made:

1. ~~"BioVoid is statistically significantly better than fpocket at detecting cryptic pockets."~~ (McNemar p=0.0625, not significant)
2. ~~"BioVoid reliably detects at least 30% of cryptic pockets."~~ (CI lower bound is 0.15)
3. ~~"BioVoid has been validated on an independent test set."~~ (Historical contamination; holdout not yet evaluated)
4. ~~"BioVoid generalizes to all protein families."~~ (Only 20 cases tested, single MD target)
5. ~~"BioVoid has zero false positives."~~ (Conservative FPR is 13.1%; strict FPR is 75.4%)

---

## 5. Pre-Registration Reference

All thresholds and metrics are defined in:
- `data/validation/pre_registered_config.json` (SHA-256 in `docs/artifact_integrity_chain_v1.md`)
- `docs/scientific_validation_plan_v1.md` §1–3

---

## 6. Reproducibility

To reproduce all validation results:

```bash
python scripts/run_publication_freeze_gate.py
```

This runs SoT guard, regression guard, bundle build, and bundle verification in sequence.

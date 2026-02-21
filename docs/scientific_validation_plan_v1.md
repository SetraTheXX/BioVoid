# Scientific Validation Plan v1 — SoT Freeze

- Document ID: `scientific_validation_plan_v1`
- Created: 2026-02-22
- Status: **LOCKED**
- Scope: Freeze all metric definitions, thresholds, data splits, and statistical test protocols before any further scientific claims.
- Authority: This document is the single source of truth (SoT) for the Bio-Void Hunter scientific validation framework.

> **Rule:** No metric definition, threshold, formula, or data split described in this document may be changed after lock date without a formal amendment section appended at the bottom with justification and re-validation evidence.

---

## 1. Single Source of Truth — Metric Registry

All decision-grade metrics, their definitions, computation formulas, pre-registered thresholds, and canonical source files are listed below. Any metric not in this table is informational only and **cannot** be used for PASS/FAIL decisions.

### 1.1 Primary Decision Metrics

| # | Metric | Definition | Formula | Threshold | Direction | Observed (2026-02-21) | Status | Canonical Source File |
|---|--------|------------|---------|-----------|-----------|----------------------|--------|----------------------|
| M1 | **Recall** | Fraction of known cryptic pockets detected within tolerance distance by BioVoid top-N druggable pockets | `TP / (TP + FN)` where TP = known pocket matched within 8.0 Å by any of top-20 druggable BioVoid pockets | ≥ 0.30 | Higher is better | 0.3500 (7/20) | **PASS** | `data/validation/validation_results.json` |
| M2 | **fpocket Overlap** | Dice-like overlap between BioVoid and fpocket pocket sets (center + volume greedy matching) | `global.official_overlap_center_volume_greedy` from benchmark JSON = greedy center-distance match (≤ 8.0 Å) weighted by quantile-calibrated volume similarity | ≥ 0.25 | Higher is better | 0.2597 | **PASS** | `data/benchmark/fpocket_benchmark_v3.json` |
| M3 | **Conservative FPR** | False positive rate excluding unknown cases | `unsupported / (supported + unsupported)` where classification uses weighted evidence score ≥ 0.30 threshold | ≤ 0.60 | Lower is better | 0.1311 | **PASS** | `data/validation/false_positive_results.json` |
| M4 | **MD Validated Proteins** | Count of required proteins where NMA-predicted pocket is confirmed open in MD trajectory | At least 1 required protein (1G66) with `open_fraction ≥ 0.50` and `max_volume > 200 Å³` across NMA frames | ≥ 1 | Higher is better | 1 | **PASS** | `data/validation/md_validation_1g66.json` |

### 1.2 Canonical Parameters (Locked)

These parameters are frozen and must be identical across all pipeline runs, scripts, reports, and JSON artifacts.

| Parameter | Locked Value | Source |
|-----------|-------------|--------|
| Proximity tolerance | 8.0 Å | `pre_registered_config.json → canonical_parameters.proximity_tolerance_angstrom` |
| Top-N pockets | 20 | `pre_registered_config.json → canonical_parameters.top_n_pockets_to_consider` |
| Druggable filter | `true` | `pre_registered_config.json → canonical_parameters.druggable_filter` |
| Min druggable volume | 200.0 Å³ | `pre_registered_config.json → canonical_parameters.min_druggable_volume_angstrom3` |
| Gate profile | `strict` | `pre_registered_config.json → gate_profiles.strict` |
| Decision policy | `all_gates_must_pass` | `pre_registered_config.json → gate_profiles.strict.decision_policy` |
| Overlap metric source | `global.official_overlap_center_volume_greedy` | `pre_registered_config.json → gate_profiles.strict.overlap_metric_source` |
| Forbidden tolerance values | 15.0 Å | `pre_registered_config.json → methodology_guardrails.forbidden_tolerance_values_angstrom` |

**Drift policy:** Any run using a tolerance other than 8.0 Å within the Phase 5.5 balanced profile is invalid and must be rejected.

### 1.3 Secondary / Informational Metrics (Non-decision)

These metrics are reported for transparency but do **not** gate any PASS/FAIL decision.

| Metric | Definition | Observed | Source |
|--------|------------|----------|--------|
| Strict FPR | `(unsupported + unknown) / total` | 0.7535 | `docs/statistical_appendix.md` |
| Unknown rate | `unknown / total` | 0.7163 | `docs/statistical_appendix.md` |
| Raw recomputed overlap | Center-only overlap without volume calibration | 0.0577 | `fpocket_benchmark_v3.json → global.official_overlap_center_volume_greedy_raw` |
| Center-only overlap (greedy) | Distance-only match without volume filter | 0.3099 | `fpocket_benchmark_v3.json → global.center_only_overlap_greedy` |
| MD open fraction (1G66) | Fraction of NMA frames where pocket is matched | 0.9375 | `docs/phase5_5_gate_decision.md` |
| MD max volume (1G66) | Maximum pocket volume across frames | 2087.28 Å³ | `docs/phase5_5_gate_decision.md` |

---

## 2. Data Split & Holdout Protocol

### 2.1 Current Data Sets

| Dataset | Size | Purpose | Source File |
|---------|------|---------|-------------|
| Known cryptic pockets (validation set) | 20 cases | Recall measurement (M1) | `data/validation/known_cryptic_pockets.json` |
| Benchmark protein set | 100 proteins (99 valid) | fpocket overlap (M2) | `data/benchmark/fpocket_benchmark_v3.json` |
| FPR sample | 50 proteins | False positive analysis (M3) | `data/validation/false_positive_results.json` |
| MD validation target | 1 protein (1G66) | MD confirmation (M4) | `data/validation/md_validation_1g66.json` |

### 2.2 Holdout Protocol (Blind)

**Purpose:** Prevent overfitting of pipeline parameters to the validation set.

**Rules:**

1. **Holdout subset definition:**
   - From the 20 known cryptic pocket cases, a minimum of 5 cases (25%) must be designated as a **blind holdout**.
   - Holdout case IDs must be selected by deterministic hash (e.g., SHA-256 of PDB ID, sorted, take last 5) and recorded in a sealed manifest before any parameter tuning.
   - **Current status:** Holdout subset is **SEALED** (see `data/benchmark/blind_holdout_v1.json`).
   - **Historical contamination:** All 20 known cryptic pocket cases were used in recovery v2/v3 experiments. The holdout is valid for forward-looking Faz 7+ use only; retrospective blindness claims are not valid.

2. **Holdout usage rules:**
   - Holdout cases must **never** be used for parameter selection, threshold tuning, or algorithm design decisions.
   - Holdout recall is reported separately as a secondary metric after all tuning is finalized.
   - If holdout recall drops below `0.20` (absolute floor), the tuning round is invalidated.

3. **Benchmark set holdout:**
   - From the 100 benchmark proteins, 20 proteins (20%) should be reserved as a blind benchmark holdout.
   - Selection: deterministic seed-based random sample (seed = 42, `random.sample` after sorting PDB IDs).
   - Overlap metric on holdout-only subset is reported as a secondary check.

4. **Seal procedure:**
   - Holdout manifests must be written to `data/validation/holdout_manifest.json` with:
     - `holdout_recall_ids`: list of 5 PDB IDs
     - `holdout_benchmark_ids`: list of 20 PDB IDs
     - `selection_method`: description of deterministic selection
     - `sealed_at_utc`: timestamp
   - Once sealed, the manifest file must not be modified. Any modification invalidates all subsequent results.

### 2.3 Leakage Prevention Rules

| Rule ID | Rule | Enforcement |
|---------|------|-------------|
| L1 | No validation set case may appear in any training/tuning set for Faz 7 classifier | Automated check in CI: intersection of train IDs and validation IDs must be empty |
| L2 | No benchmark protein may be used for parameter sweep if it is in the holdout subset | Script-level guard: `run_parameter_sweep.py` must exclude holdout IDs |
| L3 | Canonical parameters (Section 1.2) must not be tuned on the full validation set | Any parameter change requires holdout-only evaluation first |
| L4 | FPR sample proteins must not overlap with known cryptic pocket validation set | Automated check: intersection must be empty or explicitly documented |
| L5 | No post-hoc metric selection: if a new metric is introduced, it is informational only until the next formal plan revision | Governance review required for any metric promotion to decision-grade |
| L6 | Temporal leakage: MD validation frames must not be generated with knowledge of the validation pocket center coordinates | MD simulation setup must use only PDB coordinates, not BioVoid output |

---

## 3. Statistical Test Plan

### 3.1 Bootstrap Confidence Intervals

All primary metrics must be reported with 95% bootstrap confidence intervals.

| Metric | Bootstrap Method | N resamples | Unit of resampling | Current CI |
|--------|-----------------|-------------|-------------------|------------|
| Recall (M1) | Non-parametric bootstrap | 10,000 | Per-case (resample 20 cases with replacement) | [0.1500, 0.5500] (computed 2026-02-22, recall=0.35) |
| fpocket Overlap (M2) | Non-parametric bootstrap | 10,000 | Per-protein (resample 99 proteins with replacement, recompute global overlap) | [0.1896, 0.3405] (official overlap, computed 2026-02-22) |
| Conservative FPR (M3) | Non-parametric bootstrap | 10,000 | Per-pocket (resample classified pockets with replacement) | [0.082, 0.180] |
| MD open fraction (M4) | Non-parametric bootstrap | 10,000 | Per-frame (resample 64 frames with replacement) | [0.8750, 0.9844] (computed 2026-02-22) |

**Implementation:**

```python
import numpy as np

def bootstrap_ci(data, statistic_fn, n_resamples=10000, ci=0.95, seed=42):
    rng = np.random.default_rng(seed)
    stats = []
    for _ in range(n_resamples):
        sample = rng.choice(data, size=len(data), replace=True)
        stats.append(statistic_fn(sample))
    lower = np.percentile(stats, (1 - ci) / 2 * 100)
    upper = np.percentile(stats, (1 + ci) / 2 * 100)
    return lower, upper
```

### 3.2 Paired Comparison Tests (BioVoid vs fpocket)

For the head-to-head benchmark, the following paired tests must be performed:

| Test | Purpose | Method | Null Hypothesis | Significance Level |
|------|---------|--------|----------------|-------------------|
| Paired overlap difference | Is BioVoid overlap significantly different from random? | Permutation test (10,000 permutations) on per-protein overlap scores | BioVoid and fpocket pocket sets are exchangeable | α = 0.05 |
| Wilcoxon signed-rank | Per-protein matched pocket count difference | `scipy.stats.wilcoxon` on (BioVoid_matched - fpocket_matched) per protein | Median difference = 0 | α = 0.05 |
| McNemar's test | Per-case recall difference (known cryptic set) | McNemar's test on 2×2 table of (BioVoid detects, fpocket detects) per case | Detection rates are equal | α = 0.05 |

**Reporting rule:** p-values must be reported alongside effect sizes. Multiple comparison correction (Bonferroni) applies if more than 3 tests are run on the same dataset.

### 3.3 Effect Size Reporting

| Metric | Effect Size Measure |
|--------|-------------------|
| Recall | Absolute difference and odds ratio vs fpocket (if fpocket recall available) |
| Overlap | Cohen's d on per-protein overlap distribution |
| FPR | Absolute difference from threshold (0.60 - 0.1311 = 0.4689 margin) |

### 3.4 Sensitivity Analysis

| Analysis | Description | Required Output |
|----------|-------------|-----------------|
| Tolerance sweep | Recompute recall at tolerance = {4, 6, 8, 10, 12} Å | Table + line plot |
| Top-N sweep | Recompute recall at top_n = {5, 10, 15, 20, 30} | Table + line plot |
| Volume threshold sweep | Recompute overlap at min_volume = {100, 150, 200, 300} Å³ | Table + line plot |
| FPR evidence threshold sweep | Recompute conservative FPR at weighted_score = {0.20, 0.25, 0.30, 0.35, 0.40} | Table |

**Rule:** Sensitivity analyses are informational. The canonical locked values (Section 1.2) remain the decision basis regardless of sensitivity results.

---

## 4. Governance & Amendment Protocol

### 4.1 Document Lifecycle

```
DRAFT → LOCKED → ACTIVE → AMENDED (if needed) → SUPERSEDED
```

Current status: **LOCKED** (effective 2026-02-22).

### 4.2 Amendment Rules

1. Any change to a primary metric definition, threshold, or formula requires:
   - Written justification with scientific rationale
   - Re-run of all gate checks with new parameters
   - Holdout evaluation showing no degradation
   - Append-only amendment section at the bottom of this document
2. Adding a new informational metric does **not** require an amendment.
3. Promoting an informational metric to decision-grade requires a full amendment.

### 4.3 Artifact Integrity Chain

All artifacts referenced in this plan must be verifiable:

| Artifact | Integrity Check |
|----------|----------------|
| `data/validation/pre_registered_config.json` | SHA-256 hash recorded at lock time |
| `data/validation/known_cryptic_pockets.json` | Case count = 20, no additions/removals after lock |
| `data/benchmark/fpocket_benchmark_v3.json` | Protein count = 99 (valid), canonical_lock matches Section 1.2 |
| `data/validation/md_validation_1g66.json` | Status = VALIDATION_SUCCESS, n_samples = 64 |
| `data/validation/false_positive_results.json` | Sample size = 50 proteins, seed deterministic |
| `docs/phase5_5_gate_decision.md` | Decision = PASS, all 4 gates PASS |
| `docs/recovery_v2_regression_guard_report.md` | Overall WS-C guard = PASS, all 4 sub-guards PASS |

### 4.4 Guard Commands (Pre-release Mandatory)

Before any scientific claim or publication, these three commands must return PASS:

```bash
python scripts/generate_phase5_5_gate_decision.py --gate-profile strict --fpocket-report docs/fpocket_benchmark_report.md
python scripts/run_recovery_v2_regression_guard.py --fpocket-report docs/fpocket_benchmark_report.md
python scripts/recovery_v2_intake_check.py --strict --recall-floor 0.30 --overlap-floor 0.25
```

---

## 5. Known Gaps & Required Actions

| # | Gap | Severity | Required Action | Deadline | Status |
|---|-----|----------|----------------|----------|--------|
| G1 | Holdout manifest not yet sealed | **HIGH** | Create holdout manifest per Section 2.2 | Before Faz 7 starts | **CLOSED** -- `data/benchmark/blind_holdout_v1.json` sealed. Historical contamination documented. |
| G2 | Recall bootstrap CI is stale | **MEDIUM** | Recompute with current validation_results.json | Before publication | **CLOSED** -- Recall CI [0.1500, 0.5500] computed in `docs/scientific_evidence_report_v1.md` |
| G3 | fpocket overlap bootstrap CI not computed | **MEDIUM** | Implement per-protein bootstrap on benchmark data | Before publication | **CLOSED** -- Official overlap CI [0.1896, 0.3405] computed |
| G4 | MD open fraction bootstrap CI not computed | **LOW** | Implement per-frame bootstrap on 1G66 data | Before publication | **CLOSED** -- Open fraction CI [0.8750, 0.9844] computed |
| G5 | Paired statistical tests not yet executed | **MEDIUM** | Run permutation test, Wilcoxon, McNemar | Before publication | **CLOSED** -- All 4 paired tests executed. Permutation, Wilcoxon, t-test significant (p < 0.0001). McNemar: stat=5.00, p=0.0625 (n11=2, n10=5, n01=0, n00=13). 20/20 paired via Docker fpocket backend. |
| G6 | Sensitivity sweeps (Section 3.4) not yet executed | **LOW** | Run tolerance/top-N/volume/FPR sweeps | Before publication | **CLOSED** -- 4 sweep axes executed (tolerance, top_n, min_volume, FPR threshold). Canonical point not at cliff edge. See `docs/sensitivity_sweeps_v1_report.md`. |
| G7 | Artifact SHA-256 hashes not recorded | **LOW** | Compute and append to this document | Before Faz 7 starts | **CLOSED** -- 14/14 artifacts hashed. See `docs/artifact_integrity_chain_v1.md`. |

---

## 6. Readiness Assessment

### 6.1 Gate Status Summary (2026-02-21 Snapshot)

| Gate | Observed | Threshold | Margin | Status |
|------|----------|-----------|--------|--------|
| Recall (M1) | 0.3500 | ≥ 0.30 | +0.0500 | **PASS** |
| fpocket Overlap (M2) | 0.2597 | ≥ 0.25 | +0.0097 | **PASS** |
| Conservative FPR (M3) | 0.1311 | ≤ 0.60 | -0.4689 | **PASS** |
| MD Validated (M4) | 1 | ≥ 1 | +0 | **PASS** |

### 6.2 Guard Chain Status

| Guard | Status |
|-------|--------|
| FPR guard | PASS |
| MD guard | PASS |
| Drift guard | PASS (tolerance=8.0, top_n=20, druggable=true) |
| Report consistency guard | PASS |
| WS-C overall | **PASS** |

### 6.3 Validation Plan Readiness Verdict

| Criterion | Status |
|-----------|--------|
| All 4 primary gates PASS | **YES** |
| Pre-registered config locked | **YES** |
| Metric definitions documented | **YES** |
| Canonical parameters frozen | **YES** |
| Guard chain PASS | **YES** |
| Holdout protocol defined | **YES** -- manifest sealed (`data/benchmark/blind_holdout_v1.json`) |
| Leakage rules defined | **YES** -- historical contamination documented |
| Statistical test plan defined | **YES** -- bootstrap CIs and 4/4 paired tests executed (G5 closed) |
| Sensitivity analysis plan defined | **YES** -- 4 sweep axes executed (G6 closed). See `docs/sensitivity_sweeps_v1_report.md`. |

### 6.4 Overall Readiness

**READY_WITH_DISCLOSURES**

- **Rationale:** All four pre-registered scientific gates PASS. All 7 gaps (G1-G7) are CLOSED. Bootstrap CIs computed for all 4 metrics. All 4 paired tests executed: permutation, Wilcoxon, t-test significant (p < 0.0001); McNemar stat=5.00, p=0.0625 (computable, 20/20 paired via Docker fpocket). Sensitivity sweeps confirm canonical point is not at cliff edge. Artifact integrity chain sealed (14/14 hashed).
- **Remaining gaps:** None.
- **Blocking for Faz 7:** None.
- **Blocking for publication:** None (disclosures required, see below).
- **Caveat:** Recall CI lower bound (0.15) is below the 0.30 threshold. The point estimate passes but statistical certainty is limited by the small validation set (N=20). This must be disclosed in any publication.

---

## Amendments

_(No amendments yet. Append here if any metric, threshold, or protocol change is required.)_

# Blind Holdout Set v1 — Report

- Generated: 2026-02-21T21:46:06Z
- Seed: 42
- Selection method: SHA-256 deterministic hash, pocket-type stratified round-robin

## 1. Data Sources

| Source | Path | Count |
|--------|------|-------|
| Known cryptic pockets | `data/validation/known_cryptic_pockets.json` | 20 |
| Benchmark proteins | `data/benchmark/fpocket_benchmark_v3.json` | 99 |
| Tuning/recovery IDs (excluded) | recovery_v2 + v3 + parameter_sweep | 20 |

## 2. Pocket Type Distribution (Full Validation Set)

| Pocket Type | Count |
|-------------|-------|
| domain_motion | 4 |
| side-chain_flip | 4 |
| loop_rearrangement | 3 |
| DFG-out | 2 |
| helix_displacement | 2 |
| PIF pocket | 1 |
| allosteric | 1 |
| flap_opening | 1 |
| loop_closure | 1 |
| portal_opening | 1 |

## 3. Recall Holdout Set

- Size: 5 / 20

| PDB ID | Name | Pocket Type | Reference |
|--------|------|-------------|-----------|
| 3K5V | PDK1 Kinase | PIF pocket | Engel et al. 2010, Nat Chem Biol |
| 1T46 | HIV-1 Reverse Transcriptase | allosteric | Ren et al. 2001 |
| 1OHR | Plasmepsin II | flap_opening | Meller et al. 2023 |
| 1STP | Streptavidin | loop_closure | Weber et al. 1989 |
| 1JWP | Fatty Acid Binding Protein | portal_opening | Richieri et al. 2000 |

### Holdout Pocket Type Coverage

| Pocket Type | In Holdout | In Full Set | Represented |
|-------------|-----------|-------------|-------------|
| DFG-out | 0 | 2 | NO |
| PIF pocket | 1 | 1 | YES |
| allosteric | 1 | 1 | YES |
| domain_motion | 0 | 4 | NO |
| flap_opening | 1 | 1 | YES |
| helix_displacement | 0 | 2 | NO |
| loop_closure | 1 | 1 | YES |
| loop_rearrangement | 0 | 3 | NO |
| portal_opening | 1 | 1 | YES |
| side-chain_flip | 0 | 4 | NO |

## 4. Benchmark Holdout Set

- Size: 20 / 99

| # | PDB ID |
|---|--------|
| 1 | 1GVT |
| 2 | 1SSX |
| 3 | 2PPP |
| 4 | 3GYJ |
| 5 | 3QL9 |
| 6 | 4A7U |
| 7 | 4MZC |
| 8 | 4TJZ |
| 9 | 4WKA |
| 10 | 4YXI |
| 11 | 5YCE |
| 12 | 6HSA |
| 13 | 6T81 |
| 14 | 6Y1P |
| 15 | 7TWT |
| 16 | 7XFA |
| 17 | 8A3H |
| 18 | 8AQP |
| 19 | 8SH6 |
| 20 | 9HDW |

## 5. Excluded Tuning/Recovery IDs

Total excluded: 20

| PDB ID |
|--------|
| 1AKE |
| 1CBS |
| 1F41 |
| 1G4E |
| 1GWR |
| 1JWP |
| 1LI2 |
| 1M17 |
| 1OHR |
| 1RX4 |
| 1STP |
| 1T46 |
| 1YET |
| 2BXR |
| 2HYY |
| 2P2I |
| 2VTA |
| 3C79 |
| 3ERT |
| 3K5V |

## 6. Leakage Checks

| Check | Status | Overlap |
|-------|--------|---------|
| recall_holdout_vs_tuning_ids | CONTAMINATED | 1JWP, 1OHR, 1STP, 1T46, 3K5V |
| benchmark_holdout_vs_tuning_ids | PASS | none |
| recall_holdout_vs_benchmark_holdout | INFO | none |
| historical_contamination | CONTAMINATED | 1AKE, 1CBS, 1F41, 1G4E, 1GWR, 1JWP, 1LI2, 1M17, 1OHR, 1RX4, 1STP, 1T46, 1YET, 2BXR, 2HYY, 2P2I, 2VTA, 3C79, 3ERT, 3K5V |

## 7. Usage Rules

1. **Recall holdout** cases must NOT be used for parameter tuning, threshold selection, or algorithm design.
2. **Benchmark holdout** proteins must NOT be included in parameter sweep evaluations.
3. Holdout metrics are reported as secondary checks AFTER all tuning is finalized.
4. If holdout recall drops below 0.20 (absolute floor), the tuning round is invalidated.
5. This manifest is sealed. Any modification invalidates all subsequent results.

## 8. Reproduction Command

```bash
python scripts/build_blind_holdout_set.py --seed 42 --holdout-recall-k 5 --holdout-benchmark-k 20
```

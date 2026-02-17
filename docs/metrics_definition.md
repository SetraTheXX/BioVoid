# Metrics Definition (Phase 5.5)

## Pre-registered decision metrics

- Recall: `TP / (TP + FN)`
- fpocket overlap (Dice-like): `2 * matches / (N_fpocket + N_biovoid)`
- MD validation pass rule: at least one required protein validated (`min_md_validated_proteins = 1`)
- False Positive Rate (FPR) gate: `FPR <= 0.60`

## FPR variants in this report

- Weighted support score:
  - `score = 0.2*known + 0.3*ligand + 0.3*fpocket + 0.2*docking`
  - `supported` if `score >= 0.30`
- Explicit unknown handling: `unknown` if available sources < 2

- Conservative FPR: `unsupported / (supported + unsupported)`
- Strict FPR: `(unsupported + unknown) / total_candidates`
- Unknown rate: `unknown / total_candidates`

# Metrics Definition (Phase 5.5)

## Pre-registered decision metrics

- Recall: `TP / (TP + FN)`
- fpocket overlap (Dice-like): `2 * matches / (N_fpocket + N_biovoid)`
- MD validation pass rule: at least one required protein validated (`min_md_validated_proteins = 1`)
- False Positive Rate (FPR) gate: `FPR <= 0.60`

## FPR variants in this report

- Conservative FPR: `unsupported / (supported + unsupported)`
- Strict FPR: `(unsupported + unknown) / total_candidates`
- Unknown rate: `unknown / total_candidates`

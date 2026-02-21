# Recall Recovery Experiments v3

- Generated at (UTC): 2026-02-21T15:53:35Z
- Scope: A3 full rerun (20 proteins, refined ranking)

## Metrics

- Recall: **35.0%** (7/20)
- Precision: **1.009%**
- F1: **1.961%**
- Avg best distance: **17.94A**
- Domain-motion: **2/4** (50.0%)

## Config Lock

- tolerance=8.0
- top_n=20
- druggable_only=True
- aggregation_mode=multi
- analysis_atom_mode=frame_ca
- frame_selection_mode=domain_motion_weighted
- frame_selection_fraction=1.00

## Decision

- SG1 recall checkpoint (>=0.22): **PASS**
- Gate-level recall target (>=0.30): **PASS**
# Recovery v2 Recall Domain-Motion Report

- Generated at (UTC): 2026-02-17T18:58:00Z
- Scope: CP-A pivot mini-set (domain_motion + loop_rearrangement)
- Canonical lock: tolerance=8.0A, top-N=20, druggable=true
- Mini-set size: 7

## Denenen Degisiklikler

- Sampling: uniform vs domain_motion_weighted, fraction=0.35/0.60
- Ranking: legacy vs refined ranking formula + hard filters
- Atom mode: frame_ca vs reconstructed_heavy

## Trial Sonuclari

| Trial | Degisiklik | Recall | Domain-motion | Error Count | Avg Best Distance |
| --- | --- | ---: | ---: | ---: | ---: |
| t0_baseline | Baseline frame_ca + uniform + legacy | 0.0% (0/7) | 0/4 | 0 | 20.78A |
| t1_rank_refine | frame_ca + uniform + refined | 0.0% (0/7) | 0/4 | 0 | 21.57A |
| t2_sampling_weighted | frame_ca + domain_motion_weighted + refined | 0.0% (0/7) | 0/4 | 0 | 21.56A |
| t3_sampling_deeper | frame_ca + domain_motion_weighted(0.60) + refined | 0.0% (0/7) | 0/4 | 0 | 21.56A |
| t4_atom_mode_heavy | reconstructed_heavy + domain_motion_weighted + refined | 14.3% (1/7) | 1/4 | 0 | 25.70A |

## En Iyi Aday Konfig

- Trial: `t4_atom_mode_heavy` - reconstructed_heavy + domain_motion_weighted + refined
- Recall: 14.3% (1/7)
- Domain-motion: 1/4 (25.0%)
- Error count: 0

## CP-A Karar

- Kural: `if recall < 0.22 => PIVOT_REQUIRED else SG2_CANDIDATE`
- Karar: **PIVOT_REQUIRED**
# Recovery v2 Recall Domain-Motion Report

- Generated at (UTC): 2026-02-18T05:12:08Z
- Scope: CP-A pivot mini-set (domain_motion + loop_rearrangement)
- Canonical lock: tolerance=8.0A, top-N=20, druggable=true
- Mini-set size: 7

## Execution Policy

- Profile: `balanced`
- Executed trials: `t0_baseline, t2_sampling_weighted, t4_atom_mode_heavy, t5_atom_mode_heavy_legacy, t6_atom_mode_heavy_relaxed`
- Time budget (min): `1000000.0`
- Stopped early: `False`

## Denenen Degisiklikler

- Sampling: uniform vs domain_motion_weighted, fraction=0.35/0.60
- Ranking: legacy vs refined ranking formula + hard filters
- Atom mode: frame_ca vs reconstructed_heavy
- Mini runtime tuning: n_frames=7 (frame reuse) + bounded trial execution
- Consensus varyanti: standard vs relaxed (min_frames=2, stability/volume relaxed)

## Trial Sonuclari

| Trial | Degisiklik | Recall | Domain-motion | Error Count | Coverage | Elapsed (min) | Avg Best Distance |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| t0_baseline | Baseline frame_ca + uniform + legacy | 0.0% (0/7) | 0/4 | 0 | 7/7 | 8.78 | 20.78A |
| t2_sampling_weighted | frame_ca + domain_motion_weighted + refined | 0.0% (0/7) | 0/4 | 0 | 7/7 | 7.93 | 21.56A |
| t4_atom_mode_heavy | reconstructed_heavy + domain_motion_weighted + refined | 14.3% (1/7) | 1/4 | 0 | 7/7 | 57.38 | 27.39A |
| t5_atom_mode_heavy_legacy | reconstructed_heavy + domain_motion_weighted + legacy | 0.0% (0/7) | 0/4 | 0 | 7/7 | 0.00 | 29.39A |
| t6_atom_mode_heavy_relaxed | reconstructed_heavy + domain_motion_weighted + refined + relaxed_consensus | 14.3% (1/7) | 1/4 | 0 | 7/7 | 55.15 | 27.39A |

## En Iyi Aday Konfig

- Trial: `t4_atom_mode_heavy` - reconstructed_heavy + domain_motion_weighted + refined
- Recall: 14.3% (1/7)
- Domain-motion: 1/4 (25.0%)
- Error count: 0

## CP-A Karar

- Kural: `if recall < 0.22 => PIVOT_REQUIRED else SG2_CANDIDATE`
- Karar: **PIVOT_REQUIRED**
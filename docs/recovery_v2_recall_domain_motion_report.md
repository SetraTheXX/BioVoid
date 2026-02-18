# Recovery v2 Recall Domain-Motion Report

- Generated at (UTC): 2026-02-18T17:32:12Z
- Scope: CP-A pivot mini-set (domain_motion + loop_rearrangement)
- Canonical lock: tolerance=8.0A, top-N=20, druggable=true
- Mini-set size: 7

## Execution Policy

- Profile: `balanced`
- Executed trials: `t4_atom_mode_heavy`
- Time budget (min): `1000000.0`
- Stopped early: `True`

## Denenen Degisiklikler

- Sampling: uniform vs domain_motion_weighted, fraction=0.35/0.60
- Ranking: legacy vs refined ranking formula + hard filters
- Atom mode: frame_ca vs reconstructed_heavy
- Mini runtime tuning: n_frames=7 (frame reuse) + bounded trial execution
- Consensus varyanti: standard vs relaxed (min_frames=2, stability/volume relaxed)

## Trial Sonuclari

| Trial | Degisiklik | Recall | Domain-motion | Error Count | Coverage | Elapsed (min) | Avg Best Distance |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| t4_atom_mode_heavy | reconstructed_heavy + domain_motion_weighted + refined | 28.6% (2/7) | 2/4 | 0 | 7/7 | 83.82 | 22.29A |

## En Iyi Aday Konfig

- Trial: `t4_atom_mode_heavy` - reconstructed_heavy + domain_motion_weighted + refined
- Recall: 28.6% (2/7)
- Domain-motion: 2/4 (50.0%)
- Error count: 0

## CP-A Karar

- Kural: `if recall < 0.22 => PIVOT_REQUIRED else SG2_CANDIDATE`
- Karar: **SG2_CANDIDATE**
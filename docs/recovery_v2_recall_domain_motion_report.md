# Recovery v2 Recall Domain-Motion Report

- Generated at (UTC): 2026-02-18T23:43:53Z
- Scope: CP-A pivot mini-set (domain_motion + loop_rearrangement)
- Canonical lock: tolerance=8.0A, top-N=20, druggable=true
- Mini-set size: 7

## Execution Policy

- Profile: `balanced`
- Executed trials: `t4_atom_mode_heavy`
- Time budget (min): `90.0`
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
| t4_atom_mode_heavy | reconstructed_heavy + domain_motion_weighted + refined | 20.0% (1/5) | 1/3 | 0 | 5/7 | 90.43 | 24.52A |

## En Iyi Aday Konfig

- Trial: `t4_atom_mode_heavy` - reconstructed_heavy + domain_motion_weighted + refined
- Recall: 20.0% (1/5)
- Domain-motion: 1/3 (33.3%)
- Error count: 0

## Mini vs Full20 Delta Analizi

- Mini (bu kosu, bounded CP-A): recall **20.0%** (1/5), domain-motion **1/3**.
- Full20 (v2_advanced, `validation_results.json`): recall **15.0%** (3/20), domain-motion **0/4**.
- Recall farki (oran bazli): **+5.0 puan** mini lehine.
- Domain-motion farki (oran bazli): **+33.3 puan** mini lehine.
- Ortalama en iyi mesafe: mini **24.52A**, full20 **18.26A**.
- Kritik not: mini kosu sure butcesi nedeniyle **5/7 coverage** ile tamamlandi; bu nedenle mini sinyali full20'e birebir genellenemez.

## CP-A Karar

- Kural: `if recall < 0.22 => PIVOT_REQUIRED else SG2_CANDIDATE`
- Karar: **PIVOT_REQUIRED**

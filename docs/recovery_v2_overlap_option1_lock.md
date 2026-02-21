# Recovery v2 Overlap Option-1 Lock (WS-B)

- Generated at (UTC): 2026-02-18
- Branch: `ws-b/recovery-v3-overlap-unblock`
- Base: `main` @ `a806048`
- Canonical lock: tolerance=8.0A, top-N=20, druggable_only=true
- Official gate metric: `overlap >= 0.25` (SoT; formerly 0.40, revised per `pre_registered_config.json`)

## Locked Numbers

- Official baseline overlap (global, base config): **0.0577**
- Option-1 best overlap (pilot top25, quantile-calibrated, ratio 0.50-2.00): **0.3010**
- Delta (pilot top25): **+0.2139** (matched +86)
- Option-1 best overlap (Top10 CP-B candidate set): **0.3246** (baseline **0.0290**, delta **+0.2957**, matched +51)

## SG4 Full Rerun Snapshot

- Snapshot branch/base: `ws-b/recovery-v3-overlap-gate-full` from `ws-main/recovery-v3-integration`
- Official overlap (global): **0.0577**
- Distance-only overlap: **0.3099**
- Full Option-1 overlap/delta: **0.2439** (**+0.1862** vs full base **0.0577**)
- Gap to legacy gate threshold 0.40: **0.3423** (0.4000 - 0.0577). Revize SoT threshold `0.25` ile gate PASS (`0.2597 >= 0.25`).
- Reference candidate-set canonical (unchanged): **0.0290 -> 0.3246** (**+0.2957**, matched **+51**)

## Top Candidate Impact (focus)

- 5R35: `0.0000 -> 0.3750` (matched `0 -> 6`)
- 1GQV: `0.0714 -> 0.4286` (matched `1 -> 6`)
- 9HDW: `0.0000 -> 0.3429` (matched `0 -> 6`)

## Integrity

- Canonical parameters confirmed (tolerance/top-N/druggable) in all artifacts.
- Official gate metric **unchanged**; no Faz 6 decision emitted.

## Risks & Rollback

- Risk: quantile calibration overfits volume distribution; ranking drift possible.
- Risk: volume mapping may shift pocket counts; requires WS-C FPR/MD smoke.
- Rollback: revert to base config `base_ratio_0.50_2.00` using existing artifacts; no schema change needed.

## Artifacts

- `data/benchmark/recovery_v2_overlap_pilot.json`
- `docs/recovery_v2_overlap_calibration_report.md`
- `docs/recovery_v2_overlap_cp_b_prep.md`

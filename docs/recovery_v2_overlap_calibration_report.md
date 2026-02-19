# Recovery v2 Overlap Calibration Report (WS-B / B2)

- Generated at (UTC): 2026-02-19
- Canonical lock sabit: tolerance=8.0A, top-N=20, druggable_only=true
- Not: Bu calisma exploratory calibration/spike niteligindedir; resmi gate metriği degismez.

## Pilot Design

- Pilot protein sayisi: **25**
- Secim kurali: `top25_transition_drop_prioritizing_nonzero_official_matches`
- Pilot artifact: `data/benchmark/recovery_v2_overlap_pilot.json`
- Bu surumde eklenen spike: **Option-1 / quantile-calibrated volume representation**

## Pilot Results (Option-1 dahil)

| Config | Volume handling | Matched | Pilot overlap |
| --- | --- | ---: | ---: |
| base_ratio_0.50_2.00 | raw ratio [0.50, 2.00] | 35 | 0.0871 |
| option1_quantile_calibrated_ratio_0.50_2.00 | quantile-calibrated + ratio [0.50, 2.00] | 121 | 0.3010 |
| calib_ratio_0.40_2.50 | raw ratio [0.40, 2.50] | 51 | 0.1269 |
| calib_ratio_0.33_3.00 | raw ratio [0.33, 3.00] | 65 | 0.1617 |
| calib_ratio_0.25_4.00 | raw ratio [0.25, 4.00] | 86 | 0.2139 |

## Option-1 Spike Delta

### Top25 pilot deltalari

- Overlap: **0.0871 -> 0.3010** (`+0.2139`)
- Matched pockets: **35 -> 121** (`+86`)

### CP-B candidate-set deltalari (Top10 aday seti)

- Overlap: **0.0290 -> 0.3246** (`+0.2957`)
- Matched pockets: **5 -> 56** (`+51`)

## Focus Candidate Impact (Requested)

- **5R35**: overlap `0.0000 -> 0.3750`, matched `0 -> 6`
- **1GQV**: overlap `0.0714 -> 0.4286`, matched `1 -> 6`
- **9HDW**: overlap `0.0000 -> 0.3429`, matched `0 -> 6`

## Quantile Calibration Readiness

- Calibrator status: **ready**
- Sample count: fpocket=498, biovoid=498 (nearest-center pairs)
- Volume quantiles:
  - fpocket p10/p50/p90: 167.519 / 284.291 / 549.266
  - biovoid p10/p50/p90: 611.495 / 1440.362 / 2435.922

## Gate Metric Integrity Check

- Official overlap metric (global, unchanged): **0.0577**
- Gate threshold (unchanged): **0.40**
- Faz 6 karar ciktisi uretilmedi; sadece WS-B spike raporlamasi yapildi.

## Day1 Strict Root-Cause Snapshot

- Distance-only overlap (global): **0.3099**
- Center upper-bound overlap (global): **0.3188**
- Official strict overlap (global): **0.0577**
- Gate reachability under current center upper bound: **not reachable** (`0.3188 < 0.40`)
- Distance-only matches: **498**
- Distance+volume matches (official strict): **89**
- Transition drop (distance -> volume): **409**
- Volume-gate drop reason distribution:
  - `low_ratio`: **409**
  - `high_ratio`: **0**
  - `missing_volume`: **0**
- Full Option-1 overlap snapshot (`cp_b_candidate_impact`): **0.2439** (`+0.1862` vs **0.0577**)
- Top10 CP-B candidate-set snapshot: **0.0290 -> 0.3246** (`+0.2957`, matched **+51**)

## Unblock Candidate (Strict Metric Unchanged)

1. Teknik mudahale:
   - Nearest-center adaylari icin quantile-calibrated volume representation (Option-1) uygula;
     gate kurali ve official metric tanimi degismeden kalir.
2. Beklenen etki (JSON SoT dayanakli):
   - Full overlap: **0.0577 -> 0.2439** (`+0.1862`)
   - Top10 candidate-set overlap: **0.0290 -> 0.3246** (`+0.2957`)
3. Risk:
   - Volume mapping overfit riski ve ranking dagilimi kaymasi.
   - WS-C guard (FPR/MD) ve drift lock zorunlu.

## Risk / Regression Note

1. Option-1 belirgin kazanc veriyor ancak calibration fit overfitting riski tasiyor.
2. Volume representation kaymasi pocket ranking dagilimlarini etkileyebilir.
3. Sonraki adimda WS-C guard ile birlikte drift/FPR/MD smoke kontrolu zorunlu.

## Output Artifact

- `data/benchmark/recovery_v2_overlap_pilot.json`

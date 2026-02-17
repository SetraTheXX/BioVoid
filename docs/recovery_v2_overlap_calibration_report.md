# Recovery v2 Overlap Calibration Report (WS-B / B2)

- Generated at (UTC): 2026-02-16T20:41:46Z
- Canonical lock sabit: tolerance=8.0A, top-N=20, druggable_only=true
- Not: Bu calisma exploratory kalibrasyon sinyalidir; resmi gate karari degistirmez.

## Pilot Design

- Pilot protein sayisi: **25**
- Secim kurali: `top25_transition_drop_prioritizing_nonzero_official_matches`
- Pilot artifact: `data/benchmark/recovery_v2_overlap_pilot.json`

## Pilot Results (20-30 protein hedef bandinda)

| Config | Volume ratio | Matched | Pilot overlap |
| --- | --- | ---: | ---: |
| base_ratio_0.50_2.00 | [0.50, 2.00] | 35 | 0.0871 |
| calib_ratio_0.40_2.50 | [0.40, 2.50] | 51 | 0.1269 |
| calib_ratio_0.33_3.00 | [0.33, 3.00] | 65 | 0.1617 |
| calib_ratio_0.25_4.00 | [0.25, 4.00] | 86 | 0.2139 |

## Pilot Gate Signal Check

- Sprint acceptance sinyal bandi: `pilot overlap >= 0.15`
- Sonuc:
  - [0.33, 3.00]: **PASS**
  - [0.25, 4.00]: **PASS**

## Hypothesis Validation

1. Denenen: Volume ratio penceresini adim adim genisletme.
2. Sayisal etki: 0.0871 -> 0.2139 (delta +0.1268).
3. Dogrulanan varsayim: Overlap bottleneck'inin ana parcasi volume kapisi.
4. Yanlislanan varsayim: "center sorunu baskin" varsayimi pilotta birincil degil.

## Recommended B3 Candidate

- Exploratory candidate: `calib_ratio_0.25_4.00`
- Neden:
  - Pilotta en yuksek overlap
  - Artis monoton (genisleyen pencere ile duzenli iyilesme)

## Output Artifact

- `data/benchmark/recovery_v2_overlap_pilot.json`

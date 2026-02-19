# Recovery v3 Strict Overlap Unblock - Day1 (WS-B)

- Generated at (UTC): 2026-02-19
- Scope: WS-B strict overlap root-cause + unblock snapshot
- Official metric: **unchanged** (`overlap >= 0.40`)
- Canonical lock: `tolerance=8.0A`, `top-N=20`, `druggable_only=true`

## SoT Snapshot

- Official strict overlap (global): **0.0577**
- Distance-only overlap (global): **0.3099**
- Full Option-1 overlap (`cp_b_candidate_impact.full_option1_overlap`): **0.2439**
- Full Option-1 delta: **+0.1862**
- Top10 candidate-set overlap: **0.0290 -> 0.3246** (`+0.2957`, matched **+51**)

## 1) Top Transition-Drop Proteins (Strict Root-Cause)

Kaynak: `data/benchmark/recovery_v2_metric_validity_audit.json` (`top_transition_drop`)

| Rank | PDB | Transition drop | Center-only match | Official strict match | Ratio low fail |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1 | 8PB6 | 9 | 9 | 0 | 10 |
| 2 | 7OTU | 8 | 9 | 1 | 8 |
| 3 | 9HDW | 8 | 8 | 0 | 8 |
| 4 | 4YXI | 7 | 7 | 0 | 10 |
| 5 | 5R2O | 7 | 8 | 1 | 8 |
| 6 | 5R35 | 7 | 7 | 0 | 8 |
| 7 | 5RC2 | 7 | 7 | 0 | 8 |
| 8 | 2FVY | 7 | 7 | 0 | 7 |
| 9 | 8AUU | 7 | 7 | 0 | 7 |
| 10 | 3G9X | 6 | 5 | 0 | 7 |

## 2) Volume-Gate Drop Reason Dagilimi

Kaynak: `data/benchmark/recovery_v2_metric_validity_audit.json` (`ratio_statistics.volume_fail_reason_counts`)

Toplam volume-gate drop: **409**

| Reason | Count | Share |
| --- | ---: | ---: |
| low_ratio | 409 | 100.00% |
| high_ratio | 0 | 0.00% |
| missing_volume | 0 | 0.00% |

## 3) Strict Overlap'i En Cok Baskilayan 10 Protein + Sayisal Etki

Kaynak: `data/benchmark/recovery_v2_metric_validity_audit.json` (`top_transition_drop`)

Etki metrigi:
- `drop_share_pct = transition_drop / 409`
- `per_protein_delta = upper_bound_overlap - official_overlap`

| Rank | PDB | Drop share | Official overlap | Upper-bound overlap | Delta overlap |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1 | 8PB6 | 2.20% | 0.0000 | 0.2903 | +0.2903 |
| 2 | 7OTU | 1.96% | 0.0278 | 0.3214 | +0.2937 |
| 3 | 9HDW | 1.96% | 0.0000 | 0.2963 | +0.2963 |
| 4 | 4YXI | 1.71% | 0.0000 | 0.2500 | +0.2500 |
| 5 | 5R2O | 1.71% | 0.0312 | 0.3200 | +0.2888 |
| 6 | 5R35 | 1.71% | 0.0000 | 0.2800 | +0.2800 |
| 7 | 5RC2 | 1.71% | 0.0000 | 0.2692 | +0.2692 |
| 8 | 2FVY | 1.71% | 0.0000 | 0.2121 | +0.2121 |
| 9 | 8AUU | 1.71% | 0.0000 | 0.2258 | +0.2258 |
| 10 | 3G9X | 1.47% | 0.0000 | 0.2143 | +0.2143 |

Top10 toplami: **73 / 409** drop (**17.85%**)

## Kisa Kök Neden Karari

1. Strict overlap blokajinin ana nedeni volume-gate tarafinda **tamamen low_ratio** kaynakli kayip.
2. Center upper-bound overlap **0.3188** oldugu icin mevcut center aday dagilimiyla gate `0.40` dogrudan erisilebilir degil.
3. En yuksek baski, transition-drop listesinde yogunlasan proteinlerde (ozellikle 8PB6, 7OTU, 9HDW).

## Uygulanabilir Teknik Mudahale (Day1)

1. Mudahale:
   - Option-1 quantile-calibrated volume representation'i strict pipeline'a uygula
   - Official metric tanimi ve gate kurali degismez
2. Beklenen etki (SoT dayanakli):
   - Full overlap: **0.0577 -> 0.2439** (**+0.1862**)
   - Top10 candidate-set: **0.0290 -> 0.3246** (**+0.2957**, matched **+51**)
3. Kalan gap:
   - `0.40 - 0.2439 = 0.1561`
4. Risk/regresyon:
   - Volume mapping kaynakli ranking kaymasi; WS-C guard + drift lock gerekli.

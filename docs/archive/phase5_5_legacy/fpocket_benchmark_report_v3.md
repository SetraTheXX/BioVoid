# fpocket vs BioVoid Benchmark Report v3 (WS-B / B3)

- Generated at (UTC): 2026-02-16T20:41:46Z
- Benchmark protein count: 99 (common fpocket ok + BioVoid result)
- Canonical lock: tolerance=8.0A, top-N=20, druggable_only=true
- Official gate threshold: overlap >= 0.40

## Global Snapshot

- Official overlap (center+volume, ratio 0.50-2.00): **0.0577** (FAIL)
- Center-only overlap (greedy): **0.3099**
- Center-only upper bound (max matching): **0.3188**
- Center+volume upper bound (base ratio): **0.0577**

## Full Benchmark Re-evaluation (Exploratory Calibration)

| Config | Volume ratio | Matched | Full overlap |
| --- | --- | ---: | ---: |
| base_ratio_0.50_2.00 | [0.50, 2.00] | 84 | 0.0577 |
| calib_ratio_0.40_2.50 | [0.40, 2.50] | 121 | 0.0831 |
| calib_ratio_0.33_3.00 | [0.33, 3.00] | 157 | 0.1079 |
| calib_ratio_0.25_4.00 | [0.25, 4.00] | 223 | 0.1532 |

## Decision Context

1. Resmi gate metriği degismedi; resmi sonuc halen FAIL.
2. Kalibrasyonla belirgin artis var (0.0577 -> 0.1532), ancak gate hedefi 0.40'in altinda.
3. Center-only ust sinirin 0.3188 olmasi, mevcut pocket uzayiyla 0.40 hedefinin teknik olarak zor oldugunu gosteriyor.

## Next Technical Move

1. B2 kalibrasyon bulgularini governance notu ile kaydet.
2. B3 sonrasi odak: pocket-generation/representation tarafinda center-eslesebilirligi arttiran degisiklik.
3. Regression guard: FPR ve MD PASS durumunu koruyarak ilerle.

## Reproducibility

- Data artifact: `data/benchmark/fpocket_benchmark_v3.json`
- Audit artifact: `data/benchmark/recovery_v2_metric_validity_audit.json`

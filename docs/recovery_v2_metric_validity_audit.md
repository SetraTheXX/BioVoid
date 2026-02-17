# Recovery v2 Metric Validity Audit (WS-B / B0)

- Generated at (UTC): 2026-02-16T20:41:46Z
- Canonical lock: tolerance=8.0A, top-N=20, druggable_only=true
- Inputs:
  - `data/benchmark/fpocket_results/fpocket_batch_summary.json`
  - `data/benchmark/biovoid_results.json`

## Scope

Bu audit, resmi gate metrigini degistirmeden fpocket-BioVoid overlap zorlugunun metrik kaynakli olup olmadigini sayisal olarak test eder.

## Key Findings

- Resmi overlap (center+volume, ratio=0.50-2.00, greedy): **0.0577** (84 match / 2911 toplam pocket).
- Center-only overlap (greedy): **0.3099**.
- Center-only teorik ust sinir (max bipartite matching): **0.3188**.
- Gate hedefi `>=0.40` icin center-only ust sinir bile yetersiz: **Reachable = false**.
- Distance-only aday sinyali: **0.4470** (`498 / 1114` fpocket pocket en az bir BioVoid merkeze 8A icinde yakin).

## Volume Compatibility Signal

- Base ratio penceresi: `[0.50, 2.00]`
- Nearest center pair volume ratio p50: **0.2122**
- Nearest center pair volume ratio p90: **0.5772**
- Volume fail reason:
  - low_ratio: **409**
  - high_ratio: **0**
  - missing_volume: **0**

Yorum: Merkez yakalanan cogu eslesmede fpocket/BioVoid hacim oranlari 0.50 altinda kaliyor; sorun "high ratio" degil, sistematik "low ratio".

## Top Transition-Drop Proteins

En yuksek `center_match_upper_bound - center_volume_match_base` farkina sahip proteinler:

- 8PB6: 9 -> 0 (drop 9)
- 7OTU: 9 -> 1 (drop 8)
- 9HDW: 8 -> 0 (drop 8)
- 4YXI: 7 -> 0 (drop 7)
- 5R2O: 8 -> 1 (drop 7)

## Audit Decision

1. Resmi gate metrigi korunur (degisiklik yok).
2. Teknik olarak mevcut pocket uzayinda `>=0.40` overlap hedefi, center-only ust sinira gore ulasilabilir gorunmuyor.
3. Bu nedenle B1-B2 asamalarinda odak:
   - Hacim kalibrasyonu (ratio pencere etkisi)
   - Pocket set kalitesini ve uzamsal eslesebilirligi artirma

## Output Artifact

- `data/benchmark/recovery_v2_metric_validity_audit.json`

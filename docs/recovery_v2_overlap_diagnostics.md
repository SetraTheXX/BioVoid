# Recovery v2 Overlap Diagnostics (WS-B / B1)

- Generated at (UTC): 2026-02-16T20:41:46Z
- Canonical lock: tolerance=8.0A, top-N=20, druggable_only=true
- Base volume rule: `0.50 <= fpocket_volume / biovoid_volume <= 2.00`

## Diagnostic Summary

- fpocket valid pockets: **1114**
- BioVoid valid pockets: **1797**
- fpocket pockets with at least one center candidate (<=8A): **498**
- distance-only candidate rate: **44.70%**
- official center+volume matched: **84**
- net volume-gate drop from center candidates: **409**

## Failure Pattern

1. Distance fail:
   - 616 pocket icin 8A icinde hic aday yok.
2. Volume fail (center aday var ama ratio disi):
   - 409 pocket.
   - Fail reason dagilimi:
     - low_ratio: 409
     - high_ratio: 0
     - missing_volume: 0

## Ratio Distribution

- Nearest candidate ratio:
  - p10: 0.1004
  - p50: 0.2122
  - p90: 0.5772
- Tum center-candidate pair ratio:
  - p10: 0.0983
  - p50: 0.2256
  - p90: 0.6121

Yorum: Hacim uyumsuzlugu tek tarafli ve sistematik sekilde "fpocket << BioVoid" yonunde.

## Highest-Risk Proteins (Transition Drop)

- 8PB6, 7OTU, 9HDW, 4YXI, 5R2O, 5R35, 5RC2, 2FVY, 8AUU, 3G9X

Bu proteinlerde center sinyali olmasina ragmen volume kapisi eslesmeyi buyuk olcude dusuruyor.

## Working Hypotheses

1. Pocket geometry/volume tanimlari iki yontemde farkli olcekte.
2. Mevcut ratio penceresi (0.50-2.00), bu benchmark icin asiri dar.
3. Sorun yuksek hacim degil, dusuk hacim tarafinda konsantre.

## Next Technical Move

B2 kalibrasyonunda kontrollu ratio pencere genisletmeleri (0.40-2.50, 0.33-3.00, 0.25-4.00) pilot sonra full sette test edilir.

## Output Artifact

- `data/validation/recovery_v2_overlap_diagnostics.json`

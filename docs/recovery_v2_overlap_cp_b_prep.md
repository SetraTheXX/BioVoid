# Recovery v2 Overlap CP-B Prep (WS-B)

- Generated at (UTC): 2026-02-17
- Scope: WS-B only (overlap track)
- Official gate metric: **unchanged** (`overlap >= 0.40`)
- Protected areas: Recall / FPR / MD algorithms untouched

## Inputs

1. `docs/fpocket_benchmark_report.md`
2. `docs/recovery_v2_metric_validity_audit.md`
3. `docs/recovery_v2_overlap_diagnostics.md`
4. `data/benchmark/fpocket_benchmark_v3.json`
5. `data/benchmark/recovery_v2_metric_validity_audit.json`

## CP-B Candidate Extraction

- Output artifact: `data/benchmark/recovery_v2_overlap_cp_b_candidates.json`
- Candidate pool: `recovery_v2_metric_validity_audit.top_transition_drop`
- Reference improvement config (exploratory): `calib_ratio_0.25_4.00`
- Priority score:
  - `2.0*delta_matched + 1.5*transition_drop_upper_bound + 20.0*delta_overlap`

## Top 10 CP-B Candidate Proteins

| Rank | PDB | Priority | Base overlap | Ref overlap | Delta overlap | Delta matched | Transition drop |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 5R35 | 26.7500 | 0.0000 | 0.3125 | 0.3125 | 5 | 7 |
| 2 | 1GQV | 26.1429 | 0.0714 | 0.4286 | 0.3571 | 5 | 6 |
| 3 | 9HDW | 24.5714 | 0.0000 | 0.2286 | 0.2286 | 4 | 8 |
| 4 | 9LH0 | 22.9259 | 0.0000 | 0.2963 | 0.2963 | 4 | 6 |
| 5 | 3VOR | 20.3485 | 0.1212 | 0.3636 | 0.2424 | 4 | 5 |
| 6 | 7BDR | 18.6364 | 0.0000 | 0.1818 | 0.1818 | 3 | 6 |
| 7 | 7TWT | 18.1579 | 0.0000 | 0.1579 | 0.1579 | 3 | 6 |
| 8 | 9V69 | 18.0769 | 0.0000 | 0.1538 | 0.1538 | 3 | 6 |
| 9 | 4A7U | 18.0000 | 0.0500 | 0.2000 | 0.1500 | 3 | 6 |
| 10 | 8SH6 | 18.0000 | 0.0500 | 0.2000 | 0.1500 | 3 | 6 |

## Option-1 Spike v1 (Measured)

- Pilot top25 overlap: `0.0871 -> 0.3010` (`+0.2139`)
- Top10 CP-B candidate-set overlap: `0.0290 -> 0.3246` (`+0.2957`)
- Focus proteins:
  - 5R35: `0.0000 -> 0.3750` (matched `0 -> 6`)
  - 1GQV: `0.0714 -> 0.4286` (matched `1 -> 6`)
  - 9HDW: `0.0000 -> 0.3429` (matched `0 -> 6`)
- Official global gate metric: **unchanged** (`0.0577`, threshold `0.40`)

## CP-B Technical Options (3)

### Option 1 - Quantile-Calibrated Volume Representation

- Pocket representation improvement step:
  - Matched-center alt kumesinde fpocket/BioVoid volume dagilimlari arasina monotonic quantile mapping ekle.
  - Evaluation yine official rule ile kalir: `0.50 <= ratio <= 2.00`.
- Measured effect (v1 spike):
  - Pilot top25 overlap: **0.0871 -> 0.3010**
  - Top10 candidate-set overlap: **0.0290 -> 0.3246**
- Risk / regression effect:
  - Dusuk/orta risk. Global pocket ranking dagilimini kaydirabilir.
  - Guard ihtiyaci: FPR smoke + MD smoke + drift lock.

### Option 2 - Multi-Lobe Pocket Merge Representation

- Pocket representation improvement step:
  - Uzamsal olarak yakin ve ayni cavity familyasina giren alt-pocketlari tek temsile birlestir (center+volume fused representation).
  - Hedef: center candidate rate'i artirmak ve volume fragmentation etkisini azaltmak.
- Expected effect (full benchmark target band):
  - Official overlap: **0.11 - 0.18**
  - Distance-only candidate rate: **0.45 -> 0.50-0.58**
- Risk / regression effect:
  - Orta risk. Asiri birlesim false merge uretebilir; pocket sayisi duserek recall tarafina dolayli etki yapabilir.
  - Guard ihtiyaci: pocket-count delta audit + FPR smoke.

### Option 3 - Shape-Aware Envelope Representation

- Pocket representation improvement step:
  - Hacim tek degiskeni yerine compactness/enclosure/radius profile ile sekil-zarf temsilini normalize et.
  - Official gate hesaplama ayni kalir; sadece temsil katmani degisir.
- Expected effect (full benchmark target band):
  - Official overlap: **0.12 - 0.20**
  - Top-10 adaylarda high-drop vakalarda +2 ila +4 matched pocket kazanimi
- Risk / regression effect:
  - Orta/yuksek risk. Hesaplama maliyeti artar, parametre hassasiyeti yuksek.
  - Guard ihtiyaci: runtime budget check + drift lock + WS-C guard.

## Recommended First Try (Single Recommendation)

**Option 1 (Quantile-Calibrated Volume Representation) once denenmeli.**

Gerekce:
1. B0/B1 bulgulariyla dogrudan uyumlu (sorun sistematik `low_ratio`).
2. Official metrici degistirmeden representation katmaninda uygulanabilir.
3. Uygulama riski Option 2/3'e gore daha dusuk ve CP-B icin hizli geri bildirim verir.

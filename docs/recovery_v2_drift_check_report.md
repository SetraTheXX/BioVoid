# Recovery v2 Drift Check Report (Codex-C)

- Generated at (UTC): 2026-02-17T20:03:52Z
- Scope: Post-change drift lock verification (WS-C)
- SoT: `docs/phase5_5_gate_decision.md`
- Sources:
  - `data/validation/pre_registered_config.json`
  - `data/validation/validation_results.json`
  - `data/validation/false_positive_results.json`
  - `docs/fpocket_benchmark_report.md`
  - `docs/phase5_5_gate_decision.md`
  - `data/validation/recovery_v2_regression_guard.json`

## Kontrol Edilen Alanlar

1. Canonical lock: `tolerance=8.0`, `top_n=20`, `druggable=true`
2. SoT gate dokumanindaki drift satirlari ile artifact uyumu
3. Exploratory parametrelerin gate sonucuna yazilmamasi

## PASS/FAIL Bulgulari

### 1) Canonical Parameter Lock: PASS

- `pre_registered_config.json` canonical:
  - tolerance: `8.0`
  - top_n: `20`
  - druggable_filter: `true`
- `validation_results.json` observed:
  - tolerance: `8.0`
  - top_n: `20`
  - druggable_only: `true`
- `false_positive_results.json` canonical fields:
  - canonical_tolerance: `8.0`
  - canonical_top_n: `20`
  - canonical_druggable_filter: `true`

### 2) SoT Drift Statements: PASS

`docs/phase5_5_gate_decision.md`:
- Validation tolerance aligned with canonical: `YES`
- Validation top-N aligned with canonical: `YES`

### 3) Exploratory-to-Gate Separation: PASS

- Gate decision metrikleri canonical artifact setinden geliyor.
- Exploratory kosularin gate sonucuna yazildigina dair bulgu yok.

## Blokerler

1. Drift ihlali yok.
2. Sistem blokeri devam ediyor: final gate recall + overlap nedeniyle FAIL.

## Ana Ekibe Onerilen Aksiyon

1. Her gate-aday kosuda `tolerance/top_n/druggable` satirlarini zorunlu raporlayin.
2. Drift lock kontrolunu merge-oncesi zorunlu adim olarak koruyun.

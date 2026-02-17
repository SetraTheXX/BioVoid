# Recovery v2 Reports Alignment Check (Codex-C)

- Generated at (UTC): 2026-02-17T20:03:52Z
- Scope: WS-A/WS-B post-change SoT alignment verification
- SoT: `docs/phase5_5_gate_decision.md`
- Sources:
  - `docs/phase5_5_gate_decision.md`
  - `data/validation/validation_results.json`
  - `docs/fpocket_benchmark_report.md`
  - `docs/false_positive_report.md`
  - `docs/md_validation_1g66_report.md`
  - `memory-bank/phase5.5_validation.plan.md`
  - `data/validation/recovery_v2_regression_guard.json`

## Kontrol Edilen Alanlar

1. SoT gate metrikleri ile kaynak artifact metriklerinin birebir uyumu
2. SoT karar metni (`FAIL/PASS`) ile artifactlerden turetilen karar uyumu
3. `memory-bank/phase5.5_validation.plan.md` ust gate ozetinin SoT ile hizasi

## PASS/FAIL Bulgulari

### 1) SoT Metric Alignment: PASS

| Metric | SoT | Source | Status |
| --- | ---: | ---: | --- |
| Recall | 0.1500 | 0.1500 | PASS |
| fpocket overlap | 0.0577 | 0.0577 | PASS |
| Conservative FPR | 0.1311 | 0.1311 | PASS |
| MD validated proteins | 1 | 1 | PASS |

### 2) SoT Decision Alignment: PASS

- Reported decision: `FAIL`
- Expected decision from artifacts: `FAIL`
- Result: aligned.

### 3) Memory-Bank Top Summary Alignment: PASS

`memory-bank/phase5.5_validation.plan.md` top summary values SoT ile uyumlu:
- Recall: `15.0% (3/20)`
- fpocket overlap: `5.77%`
- Conservative FPR: `13.11%`
- MD validation proteins: `1`

### 4) Legacy Numeric Residue Risk: PASS (watch)

- Dokumanin tarihsel bolumlerinde eski deney sayilari bulunabilir.
- Bu checkpointte karar-kritik SoT metrikleriyle celiski tespit edilmedi.

## Blokerler

1. WS-C alignment blokeri yok.
2. Sistem blokeri devam ediyor: final gate recall + overlap nedeniyle FAIL.

## Ana Ekibe Onerilen Aksiyon

1. SoT alignment kontrolunu her entegrasyon oncesi zorunlu tutun.
2. Nihai karar icin tek referansi `docs/phase5_5_gate_decision.md` olarak koruyun.

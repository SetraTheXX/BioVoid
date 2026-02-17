# Faz 5.5 P1.1 - Recall Recovery Experiments

> **Uretim Tarihi:** 2026-02-13T14:00:35
> **Controlled Set:** 20 known cryptic pocket
> **Tolerance:** 8.0A (sabit)
> **Top-N:** 20 (sabit)
> **Consensus Min Support:** 3 frame

---

## 1) Genel Karsilastirma

| Metrik | Baseline (Single) | Multi-frame Consensus | Delta |
|---|---:|---:|---:|
| Recall | 10.0% (2/20) | 10.0% (2/20) | +0.0 puan |
| Avg Best Distance | 23.8A | 23.5A | -0.4A |
| Avg Frames Analyzed | 230.0 | 230.0 | +0.0 |
| Avg Consensus Support | 0.00 | 183.47 | +183.47 |

---

## 2) Pocket Type Bazli Kazanim

| Pocket Type | Single Hits/Total | Single Rate | Multi Hits/Total | Multi Rate | Delta |
|---|---:|---:|---:|---:|---:|
| DFG-out | 0/2 | 0.0% | 0/2 | 0.0% | +0.0 puan |
| PIF pocket | 1/1 | 100.0% | 1/1 | 100.0% | +0.0 puan |
| allosteric | 0/1 | 0.0% | 0/1 | 0.0% | +0.0 puan |
| domain_motion | 0/4 | 0.0% | 0/4 | 0.0% | +0.0 puan |
| flap_opening | 0/1 | 0.0% | 0/1 | 0.0% | +0.0 puan |
| helix_displacement | 0/2 | 0.0% | 0/2 | 0.0% | +0.0 puan |
| loop_closure | 0/1 | 0.0% | 0/1 | 0.0% | +0.0 puan |
| loop_rearrangement | 0/3 | 0.0% | 0/3 | 0.0% | +0.0 puan |
| portal_opening | 0/1 | 0.0% | 0/1 | 0.0% | +0.0 puan |
| side-chain_flip | 1/4 | 25.0% | 1/4 | 25.0% | +0.0 puan |

---

## 3) P1.1 Kabul Kriterleri

| Kriter | Hedef | Sonuc | Durum |
|---|---:|---:|---|
| Recall artisi | >= +10 puan | +0.0 puan | FAIL |
| Recall seviyesi | >= 20% | 10.0% | FAIL |
| Domain motion recall artisi | >= +25 puan | +0.0 puan | FAIL |

---

## 4) Teknik Notlar

- Multi-frame konsensus sadece en az 3 frame'de gorulen pocket'lari tuttu.
- Multi mode ortalama center stability: 0.30A
- Multi mode ortalama volume CV: 0.050
- Tolerance/Top-N pre-registered sabit parametrelerle korunmustur.

---

## 5) Sonuc

- Baseline recall: **10.0%** -> Multi-frame recall: **10.0%** (+0.0 puan).
- Domain-motion recall: **0.0%** -> **0.0%** (+0.0 puan).

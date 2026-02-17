# Faz 5.5 P1.1 - Recall Recovery Experiments

> **Uretim Tarihi:** 2026-02-13T19:19:22
> **Controlled Set:** 20 known cryptic pocket
> **Tolerance:** 8.0A (sabit)
> **Top-N:** 20 (sabit)
> **Consensus Min Support:** 3 frame
> **Analysis Atom Mode:** reconstructed_heavy

---

## 1) Genel Karsilastirma

| Metrik | Baseline (Single) | Multi-frame Consensus | Delta |
|---|---:|---:|---:|
| Recall | 0.0% (0/20) | 0.0% (0/20) | +0.0 puan |
| Avg Best Distance | 29.1A | 24.4A | -4.7A |
| Avg Frames Analyzed | 200.0 | 182.2 | -17.8 |
| Avg Consensus Support | 0.00 | 108.07 | +108.07 |

---

## 2) Pocket Type Bazli Kazanim

| Pocket Type | Single Hits/Total | Single Rate | Multi Hits/Total | Multi Rate | Delta |
|---|---:|---:|---:|---:|---:|
| DFG-out | 0/2 | 0.0% | 0/2 | 0.0% | +0.0 puan |
| PIF pocket | 0/1 | 0.0% | 0/1 | 0.0% | +0.0 puan |
| allosteric | 0/1 | 0.0% | 0/1 | 0.0% | +0.0 puan |
| domain_motion | 0/4 | 0.0% | 0/4 | 0.0% | +0.0 puan |
| flap_opening | 0/1 | 0.0% | 0/1 | 0.0% | +0.0 puan |
| helix_displacement | 0/2 | 0.0% | 0/2 | 0.0% | +0.0 puan |
| loop_closure | 0/1 | 0.0% | 0/1 | 0.0% | +0.0 puan |
| loop_rearrangement | 0/3 | 0.0% | 0/3 | 0.0% | +0.0 puan |
| portal_opening | 0/1 | 0.0% | 0/1 | 0.0% | +0.0 puan |
| side-chain_flip | 0/4 | 0.0% | 0/4 | 0.0% | +0.0 puan |

---

## 3) P1.1 Kabul Kriterleri

| Kriter | Hedef | Sonuc | Durum |
|---|---:|---:|---|
| Recall artisi | >= +10 puan | +0.0 puan | FAIL |
| Recall seviyesi | >= 20% | 0.0% | FAIL |
| Domain motion recall artisi | >= +25 puan | +0.0 puan | FAIL |

---

## 4) Teknik Notlar

- Multi-frame konsensus sadece en az 3 frame'de gorulen pocket'lari tuttu.
- Multi mode ortalama center stability: 0.36A
- Multi mode ortalama volume CV: 0.116
- Tolerance/Top-N pre-registered sabit parametrelerle korunmustur.

---

## 5) Sonuc

- Baseline recall: **0.0%** -> Multi-frame recall: **0.0%** (+0.0 puan).
- Domain-motion recall: **0.0%** -> **0.0%** (+0.0 puan).

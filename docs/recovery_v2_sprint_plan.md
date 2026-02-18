# Faz 5.5 Recovery v2 Sprint Plani

> **Durum:** EXECUTION TRACKED (SG0-SG2 tamam, SG3 preflight acik, SG4-SG5 beklemede)  
> **Tarih:** 2026-02-13  
> **Kapsam:** Recall + Overlap eksiklerini kapatip Faz 6 gecisine hazir hale gelmek  
> **Ana Hedef:** Final gate'te 4/4 PASS almak  
> **Revizyon:** Harici AI geri bildirimi ile sure, metrik ve feasibility katmanlari guclendirildi

---

## 0) Revizyon Notlari (Bu Surumde Eklenenler)

Bu surumde onceki plana gore asagidaki kritik iyilestirmeler eklendi:

1. Sure tahmini gercekci hale getirildi: **10-14 is gunu** (hizli yol: 7-9 is gunu).
2. A2 (consensus/ranking) soyutluktan cikarildi, **acik scoring formulu** ve acceptance metrikleri eklendi.
3. Overlap icin **Metric Validity Audit** eklendi (fpocket vs BioVoid hacim/sekil uyumlulugu).
4. Mid-sprint karar noktasi eklendi: ilerleme yetersizse erken pivot karari alinacak.
5. WS-A ve WS-B'nin **paralel ilerleme stratejisi** netlestirildi.

---

## 1) Mevcut Durum (Baseline)

Son final gate sonucu (`docs/phase5_5_gate_decision.md`):

| Gate | Hedef | Sonuc | Durum |
| --- | ---: | ---: | --- |
| Recall | >= 0.30 | 0.1500 (3/20) | FAIL |
| fpocket overlap | >= 0.40 | 0.0577 | FAIL |
| MD validation proteins | >= 1 | 1 | PASS |
| Conservative FPR | <= 0.60 | 0.1311 | PASS |

Ek teknik durum:

- Center integrity temiz: zero-center = 0.
- Domain-motion recall halen 0/4.
- Distance-only eslesme guclu (~44.70%), distance+volume dusuk (~7.99%).
- Bu, "yer yakalama" tarafinda kismi basari oldugunu, ancak "hacim/sekil uyumu" ve "zor hareket yakalama" tarafinda acik oldugunu gosteriyor.

---

## 1.5) Execution Snapshot (2026-02-18)

| Stage | Durum | Kanit | Not |
| --- | --- | --- | --- |
| SG0 Baseline Freeze | TAMAMLANDI | `docs/phase5_5_gate_decision.md` | Baseline kilitli |
| SG0.5 Metric Audit (B0) | TAMAMLANDI | `docs/recovery_v2_metric_validity_audit.md` | Resmi gate metriği degismedi |
| SG1 WS-A Spike + Mini | TAMAMLANDI (HEDEF DISI) | `docs/recovery_v2_recall_domain_motion_report.md`, `data/validation/recovery_v2_domain_motion_eval.json` | CP-A sonucu `PIVOT_REQUIRED` |
| SG2 WS-B Spike + Pilot | TAMAMLANDI | `docs/recovery_v2_overlap_option1_lock.md`, `data/benchmark/recovery_v2_overlap_pilot.json` | Top10 candidate-set `0.0290 -> 0.3246` |
| SG3 Entegrasyon + Guard | KISMEN TAMAM | `docs/recovery_v2_regression_guard_report.md`, `docs/recovery_v2_drift_check_report.md`, `docs/recovery_v2_reports_alignment.md` | WS-C guard/drift/alignment PASS |
| SG4 Final Gate Rerun | BEKLEMEDE | - | WS-A mini sinyal esigi (`recall >= 0.22`) saglanmadi |
| SG5 Faz 6 Go/No-Go | BEKLEMEDE | - | Su anki durum: NO-GO (BLOCKED) |

Current locked WS-A snapshot (latest completed mini artifact):
- `cp_a_decision = PIVOT_REQUIRED`
- `best_trial = t4_atom_mode_heavy`
- `best_recall = 1/7 = 0.1429`
- `domain_motion_hits = 1/4`
- `error_count = 0`

Execution verdict:
1. WS-B ve WS-C tarafi plan kapsaminda ilerledi.
2. Kritik blocker WS-A recall esigi oldugu icin sprint hedefi (4/4 final PASS) henuz kapanmadi.
3. Plan "tamamlandi" olarak degil, "aktif recovery dongusu" olarak izlenmeli.

---

## 2) Nihai Basari Tanimi (Faz 6 Acilis Kriteri)

Asagidaki kosullar **ayni gate rerun** icinde saglanmadan Faz 6 acilmaz:

1. Recall >= 0.30
2. fpocket overlap >= 0.40
3. Conservative FPR <= 0.60
4. MD validated proteins >= 1
5. Drift check PASS (tolerance/top-N/druggable canonical ile ayni)
6. Data integrity PASS (center integrity + summary consistency)

---

## 3) Non-Negotiable Kurallar

1. Gate kosusunda `tolerance = 8.0A`, `top-N = 20`, `druggable = true` sabit.
2. Tolerance/top-N ile oynanan kosular sadece exploratory; gate kararina girmez.
3. Her buyuk degisiklik once mini set, sonra full set.
4. Uzun kosular checkpoint/resume ile.
5. Known pocket merkezleri **sadece degerlendirme** icin kullanilacak; ranking egitimi/kararinda leakage yapilmayacak.

---

## 4) Workstream Yapisi

## WS-A: Recall Recovery v2 (Kritik)

**Amac:** Recall'i 0.15'ten >=0.30'a cekmek, domain-motion tarafinda en az 1 hit uretmek.

### A1. Domain-Motion Capture Guclendirme

**Neden:** Harmonik NMA buyuk konformasyonel gecisleri eksik yakaliyor.

**Yapilacaklar:**

1. Domain-motion vakalarinda hareket genligi raporu cikar (mode bazli).
2. Ek ornekleme stratejisi uygula (domain-motion agirlikli frame secimi/uretim).
3. Zor vaka mini setinde hizli A/B kosu yap (domain_motion + loop_rearrangement odakli).

**Ciktilar:**

- `docs/recovery_v2_recall_domain_motion_report.md`
- `data/validation/recovery_v2_domain_motion_eval.json`

**Kabul Kriteri:**

- Domain-motion recall: `0/4 -> >=1/4`
- Recall trendi pozitif olmalı (mini sette net kazanım)

### A2. Consensus ve Ranking Refine (Somut Kural Seti)

**Neden:** Multi-frame stabil ama recall artisi sinirli, bazi regresyonlar var.

**Refined rank skoru (ornek politika):**

`rank_score = 0.35*bio_score_norm + 0.25*support_norm + 0.15*druggability_norm + 0.15*(1-center_stability_norm) + 0.10*(1-volume_cv_norm)`

**Hard filtreler:**

- `support >= 3`
- `center_stability <= 2.0A`
- `volume_cv <= 0.20`

**Yapilacaklar:**

1. Ranking pipeline'a yukaridaki normalize metrikleri ekle.
2. Regresyon vakalari icin vaka bazli kontrol listesi uygula.
3. "Neden bu pocket secildi?" alanlarini rapora yaz (aciklanabilirlik).

**Ciktilar:**

- `docs/recovery_v2_consensus_ranking_report.md`
- `data/validation/recovery_v2_consensus_deltas.json`

**Kabul Kriteri:**

- Mevcut hitler korunur (1CBS, 1STP, 3K5V).
- Ortalama best-distance >=2.0A iyilesir (18.1A -> <=16.1A hedef bandi).
- Regresyon vaka sayisi azaltilir.

### A3. Recall Full Rerun (Gate Adayi)

**Yapilacaklar:**

1. 20 protein full kosu.
2. Recall/precision/F1/avg-distance/pocket-type raporu.
3. Domain-motion satiri ayrica.

**Ciktilar:**

- `docs/recall_recovery_experiments_v3.md`
- `data/validation/recall_recovery_experiments_v3.json`

**Kabul Kriteri:**

- Recall >=0.30 (ideal)
- En azindan recall >=0.22 alti kalmiyorsa bir sonraki stage'e gecis

---

## WS-B: Overlap Recovery v2 (Kritik)

**Amac:** Overlap tarafindaki hacim/sekil uyumsuzlugunu kapatmak.

### B0. Metric Validity Audit (Yeni)

**Neden:** fpocket ve BioVoid hacim/sekil tanimlari dogal olarak farkli olabilir.

**Yapilacaklar:**

1. Metrik tanim farklarini teknik olarak dokumante et.
2. Eslesme uzayinda teorik ust sinir analizi yap (fair mapping altinda).
3. "Overlap 0.40 teknik olarak ulasilabilir mi?" sorusuna sayisal cevap uret.

**Ciktilar:**

- `docs/recovery_v2_metric_validity_audit.md`
- `data/benchmark/recovery_v2_metric_validity_audit.json`

**Kural:**

- Resmi gate metriği degismez (>=0.40).
- Audit sonucu zorluk gosterirse governance notu acilir; gate disiplini bozulmaz.

### B1. Volume/Shape Diagnostigi

**Yapilacaklar:**

1. Protein bazli hacim dagilim karsilastirmasi.
2. Eslesen merkezlerde volume-ratio ve shape uyumsuzluk dagilimi.
3. Volume kapisi nedeniyle elenen vakalari reason-code ile etiketle.

**Ciktilar:**

- `docs/recovery_v2_overlap_diagnostics.md`
- `data/validation/recovery_v2_overlap_diagnostics.json`

### B2. Geometry/Volume Kalibrasyon

**Yapilacaklar:**

1. Hacim olceginde kalibrasyon (matched-center alt kumesiyle).
2. Shape/volume kriterlerinde kontrollu ayar.
3. 20-30 protein pilot benchmark kosusu.

**Ciktilar:**

- `docs/recovery_v2_overlap_calibration_report.md`
- `data/benchmark/recovery_v2_overlap_pilot.json`

**Kabul Kriteri:**

- Pilotta distance+volume metriginde belirgin artis
- Pilot overlap >=0.15 sinyal bandina cikis

### B3. Overlap Full Benchmark Rerun

**Yapilacaklar:**

1. 100 protein full benchmark.
2. Global overlap + distance-only + distance+volume raporu.
3. v2-v3 fark tablosu.

**Ciktilar:**

- `docs/fpocket_benchmark_report_v3.md`
- `data/benchmark/fpocket_benchmark_v3.json`

**Kabul Kriteri:**

- Resmi hedef: overlap >=0.40
- Yardimci KPI: distance-only gucunu koru, distance+volume'u belirgin yukari cek

---

## WS-C: PASS Gate Koruma (Regression Guard)

### C1. FPR Guard

1. Weighted evidence fusion korunur.
2. Unknown handling explicit kalir.
3. Her buyuk degisiklikten sonra FPR smoke kosulur.

**Kabul Kriteri:** Conservative FPR <=0.60 korunur.

### C2. MD Guard

1. 1G66 PASS referansi korunur.
2. Pipeline degisiklikleri MD artefaktlarini bozmaz.

**Kabul Kriteri:** MD gate PASS korunur.

---

## 5) Stage-Gate Akisi ve Paralel Yurutme

1. **SG0 - Baseline Freeze (0.5 gun)**
2. **SG0.5 - Metric Validity Audit (B0) (0.5-1 gun)**
3. **SG1 - WS-A Spike + Mini set (2-4 gun)**
4. **SG2 - WS-B Spike + Pilot benchmark (2-4 gun)**
5. **SG3 - Entegrasyon + Regression guard (1-2 gun)**
6. **SG4 - Final Gate Rerun (1 gun)**
7. **SG5 - Faz 6 Go/No-Go**

**Paralel calisma prensibi:**

- WS-A ve WS-B ayri branch/sorumlu ile paralel yurutulecek.
- SG3'te birlestirme ve ortak regression kontrolu yapilacak.

---

## 6) Feasibility Checkpoint'leri (Erken Pivot Mekanizmasi)

1. **CP-A (A2 sonrasi):**
   - Eger recall <0.22 ise, domain-motion tarafi icin algoritma pivot toplantisi zorunlu.
2. **CP-B (B2 sonrasi):**
   - Eger pilot overlap <0.15 ise, shape/volume modeli icin alternatif temsil stratejisi zorunlu.
3. **CP-G (Final oncesi):**
   - Eger iki ana gate'te trend yoksa, tam rerun ertelenir ve bir sprint daha recovery yapilir.

---

## 7) Sure ve Kaynak Plani

- **Gercekci plan:** 10-14 is gunu
- **Hizli plan (riskli):** 7-9 is gunu (buyuk matematiksel refactor cikmazsa)

Sureyi etkileyen ana faktorler:

1. Domain-motion algoritma degisimi derinligi
2. Overlap metric uyumluluk analizi sonucu
3. Uzun kosularin checkpoint ile ne kadar sorunsuz aktigi

---

## 8) Riskler ve Mitigasyon

| Risk | Olasilik | Etki | Mitigasyon |
| --- | --- | --- | --- |
| Recall yine <0.30 | Orta | Kritik | WS-A icin CP-A, domain-motion odakli pivot |
| Overlap artmaz | Orta | Kritik | B0 audit + B2 kalibrasyon + CP-B |
| Sure asimi | Orta | Yuksek | Paralel yurutme, mini set onceleme, checkpoint |
| FPR regress | Dusuk | Orta | WS-C smoke gate |
| Drift ihlali | Dusuk | Yuksek | Canonical config lock + rapor config dogrulamasi |

---

## 9) Definition of Done (Recovery v2)

Bu plan tamamlandi sayilmasi icin:

1. WS-A kabul kriterleri saglanmis olmali.
2. WS-B kabul kriterleri saglanmis olmali.
3. FPR ve MD gate'leri korunmus olmali.
4. Final gate rerun'da 4/4 PASS alinmis olmali.
5. Faz 6 icin acik GO karari dokumante edilmis olmali.

---

## 10) Final Karar Agaci

1. Final gate 4/4 PASS:
   - Faz 6 baslat.
   - `memory-bank/progress.md` ve `memory-bank/phase5.5_validation.plan.md` PASS olarak guncelle.
2. Recall FAIL:
   - WS-A iterasyon/pivot dongusune don.
3. Overlap FAIL:
   - WS-B iterasyon/pivot dongusune don.
4. FPR/MD regress:
   - WS-C duzeltme dongusu calistir.

---

## 11) Sprint Sonu Beklenen Durum

Hedef:

- Faz 5.5 PASS
- Faz 6 UNBLOCKED
- Kritik teknik borclarin olculebilir seviyede azalmasi
- Domain-motion ve overlap problemlerinin kanita dayali sekilde kapatilmasi

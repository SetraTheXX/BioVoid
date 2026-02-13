# Faz 5.5: Bilimsel Validasyon ve Benchmarking (REVİZE EDİLMİŞ)

> **Durum:** 🔴 EXECUTION COMPLETE / GATE FAIL  
> **Başlangıç:** 2026-02-12  
> **Bitiş:** 2026-02-13  
> **Tamamlanma:** 50% (Raporlama tamam, recovery başlanmadı)  
> **Sonraki Adım:** Recovery Sprint (P0 → P1 → Gate Rerun)  
> **Revizyon:** ChatGPT feedback ile sayısal tutarsızlıklar düzeltildi, riskli teknik öneriler işaretlendi

---

## ⚠️ **KRİTİK NOTLAR (ChatGPT Feedback)**

Bu plan dosyası ChatGPT'nin eleştirileri doğrultusunda revize edilmiştir:

1. **Sayısal Tutarsızlıklar Düzeltildi:**
   - FPR evidence counts: Supported=158, Unsupported=472, Unknown=15
   - MD NMA reference volume: 2008.3Ų (önceki 1344.5Ų yanlıştı)
   - fpocket benchmark: 99/100 ok (önceki 95/98 yanlıştı)

2. **Riskli Teknik Öneriler İşaretlendi:**
   - Resume without DB → FAIL et (silent warning riski)
   - [0,0,0] guard → Soft warning + metadata (hard error riski)
   - total_ids → Normalize with current list (blind checkpoint read riski)
   - Tolerance drift → Exploratory run only (pre-registration violation riski)

---

## 🎯 Faz 5.5 Hedefi

**NEDEN:**  
Faz 6'ya (120K protein taraması) geçmeden önce Bio-Void Hunter'ın **bilimsel güvenilirliğini** kanıtlamak. 4 kritik metrikle kalite kapısından geçmek gerekiyor:

1. **Recall ≥ 30%:** Bilinen cryptic pocket'ları bulabilir miyiz?
2. **fpocket Overlap ≥ 40%:** Sektör standardı ile uyumlu muyuz?
3. **MD Validation ≥ 1 protein:** Fiziksel simülasyonda pocket açılıyor mu?
4. **False Positive Rate ≤ 60%:** Bulduklarımız gerçek mi?

**NASIL:**  
Pre-registered (kilitli) test parametreleri ile 4 fazlı validasyon:

- Faz 1: fpocket benchmark (100 protein)
- Faz 2: MD validation (1G66)
- Faz 3: False positive analizi (50 protein)
- Faz 4: Publication paketi (otomatik raporlama)

**KURALLAR:**

- Tolerance = 8.0Å (sabit, drift yasak)
- Top-N = 20 (sabit)
- Druggable filter = true (sabit)
- Tüm 4 gate PASS olmalı, yoksa Faz 6 engellenir

---

## 📊 Gate Sonuçları (Final - Doğrulanmış Sayılar)

| Gate                 | Hedef       | Gerçek Sonuç         | Durum   | Kaynak                         |
| -------------------- | ----------- | -------------------- | ------- | ------------------------------ |
| **Recall**           | ≥ 30%       | **10.0%** (2/20)     | ❌ FAIL | `validation_report.md`         |
| **fpocket Overlap**  | ≥ 40%       | **5.77%**            | ❌ FAIL | `fpocket_benchmark_report.md`  |
| **MD Validation**    | ≥ 1 protein | **1 protein** (1G66) | ✅ PASS | `md_validation_1g66_report.md` |
| **Conservative FPR** | ≤ 60%       | **74.92%**           | ❌ FAIL | `false_positive_report.md`     |

**Nihai Karar:** ❌ **FAIL** (4'te 3 metrik başarısız)  
**Faz 6 Durumu:** 🔒 **BLOCKED** (Gate geçilene kadar başlanamaz)

---

## 🔴 Executive Summary: Neden Başarısız Olduk?

### 1. **Recall FAIL (10% < 30%)**

**Neden:** Tek NMA frame kullanıyoruz, çoklu frame agregasyonu yok.  
**Etki:** Domain motion (0/4), loop rearrangement (0/3) gibi zor pocket'lar kaçırılıyor.  
**Kanıt:** Side-chain flip: 1/4 (25%), Domain motion: 0/4 (0%)

### 2. **fpocket Overlap FAIL (5.77% < 40%)**

**Neden:** Atlas DB'deki pocket merkezlerinin **%88.16'sı bozuk** ([0,0,0]).  
**Etki:** Geometrik karşılaştırmalar anlamsız hale geliyor.  
**Kanıt:** `SELECT COUNT(*) FROM pockets WHERE center_x=0 AND center_y=0 AND center_z=0` → 34,458 / 39,085

### 3. **Conservative FPR FAIL (74.92% > 60%)**

**Neden:** Kanıt füzyonu zayıf, center bozukluğu evidence matching'i engelliyor.  
**Etki:** Çoğu pocket "unsupported" olarak işaretleniyor.  
**Kanıt (Doğrulanmış):** 645 aday pocket → Supported: 158, Unsupported: 472, Unknown: 15  
**Evidence Hits:** Known: 0, Ligand: 147, fpocket: 14, Docking: 0

### 4. **MD Validation PASS ✅**

**Neden:** 1G66 için snapshot-based analiz iyi çalıştı.  
**Kanıt (Doğrulanmış):** 64 snapshot, NMA reference volume: **2008.3Ų**, max volume: **2087.3Ų** (NMA'nın %103.9'u), open fraction %93.75

---

## 📋 Recovery Sprint (Öncelik Sırası)

### 🔴 **Hafta 1: P0 - Veri Temizliği (Blocker'lar)**

**Hedef:** Atlas DB'yi kullanılabilir hale getir

---

#### **P0.1 - Center Integrity Repair (1-2 gün) - EN KRİTİK**

**Sahip:** Codex  
**Durum:** ✅ Tamamlandı (2026-02-13)  
**Öncelik:** 🔴 CRITICAL (Blocker)

**NEDEN:**  
Atlas DB'deki pocket merkezlerinin %88.16'sı [0,0,0]. Bu, overlap ve FPR analizlerini anlamsız hale getiriyor.

**NASIL:**

1. **Backup Al**
   - `atlas.db` dosyasını `atlas.db.backup_20260213` olarak kopyala

2. **Repair Script Yaz**
   - `scripts/repair_atlas_centers.py`
   - Repair stratejisi (sırayla):
     a) Checkpoint JSON'dan geri yükle
     b) Yoksa recompute (cavity detection)
     c) Hala yoksa `invalid_center=1` metadata ekle

3. **⚠️ Write-Time Guard Ekle (DİKKAT!)**
   - `src/database.py` dosyasına kontrol ekle
   - **❌ RİSKLİ YAKLAŞIM:** Her [0,0,0] için hard error → legitimate degenerate case'leri kırabilir
   - **✅ GÜVENLİ YAKLAŞIM:** Fallback kaynaklı [0,0,0]'ı yakala → `invalid_center=1` metadata + warning
   - **UYGULAMA:** Soft warning + metadata approach kullan

**KURALLAR:**

- Backup olmadan repair yapma
- Recompute sırasında canonical parametreleri kullan
- Invalid center'ları metadata ile işaretle (silme)

**Kontrol Listesi:**

- [x] `atlas.db` backup al (`data/atlas.db.backup_20260213`)
- [x] `scripts/repair_atlas_centers.py` yaz
- [x] Checkpoint JSON'dan center'ları oku (`data/checkpoints/crawler_log.jsonl`)
- [x] Zero-center'ları tespit et (34,458 pocket)
- [x] Repair stratejisi uygula (checkpoint → recompute → invalid)
- [x] ⚠️ Write-time guard ekle (soft warning + metadata)
- [x] Doğrulama: Zero-center count → 0 (veya sadece invalid_center=1 olanlar)
- [x] `docs/center_integrity_report.md` üret

**Kabul Kriterleri:**

- [x] Zero-center count = 0 (veya çok az, sadece invalid_center=1)
- [x] Checkpoint JSON'dan geri yükleme %80+ başarılı
- [x] Write-time guard test'i PASS

**Tamamlanma Sonuçları (2026-02-13):**

- Backup: `data/atlas.db.backup_20260213` oluşturuldu.
- Repair komutu: `python scripts/repair_atlas_centers.py`
- Sonuç metrikleri:
  - Toplam pocket: `39,085`
  - Zero-center (önce): `34,458`
  - Checkpoint ile düzelen: `34,458`
  - Recompute ile düzelen: `0`
  - `invalid_center=1` işaretlenen: `0`
  - Zero-center (sonra): `0`
  - Checkpoint recovery: `%100.00`
- Rapor: `docs/center_integrity_report.md`
- Write-time guard doğrulaması:
  - `numpy.ndarray` center parse PASS
  - `[0,0,0]` insert için soft-guard + `invalid_center=1` PASS

**Tahmini Süre:** 1-2 gün

---

#### **P0.2 - Resume/DB Fix (1 gün)**

**Sahip:** Codex  
**Durum:** ✅ Tamamlandı (2026-02-13)  
**Öncelik:** 🔴 CRITICAL (Blocker)

**NEDEN:**  
`main_parallel.py` resume komutu `--db` parametresini almıyor. Resume sonrası veriler DB'ye yazılmıyor.

**NASIL:**

1. **Resume Parser'ı Düzelt**
   - `main_parallel.py` resume komutuna `--db` ekle
   - Resume crawler init'e db_path geçir

2. **⚠️ Runtime Behavior Tanımla (DİKKAT!)**
   - **❌ RİSKLİ YAKLAŞIM:** Resume without DB → silent warning + checkpoint-only → veri ayrışması riski
   - **✅ GÜVENLİ YAKLAŞIM:** Resume without DB → **FAIL et** (veri ayrışmasını engelle)
   - **🟡 ALTERNATİF:** Explicit `--checkpoint-only` flag ekle (açık karar)
   - **UYGULAMA:** FAIL approach kullan (en güvenli)

3. **DB Path Validation Ekle**
   - Eğer `--db` verilmişse, dosyanın var olduğunu kontrol et
   - Yoksa hata ver

**KURALLAR:**

- Resume without DB → **FAIL** (checkpoint-only mode explicit olmalı)
- DB path validation zorunlu

**Kontrol Listesi:**

- [x] `main_parallel.py` resume parser'a `--db` ekle
- [x] Resume crawler init'e db_path geçir
- [x] ⚠️ Resume without DB → **FAIL** (silent warning yerine)
- [x] DB path validation ekle
- [x] Test: Resume sonrası DB'ye yazım doğrula
- [x] Regression test yaz

**Kabul Kriterleri:**

- [x] Resume with `--db` çalışıyor
- [x] Resume without `--db` → **FAIL** (veya explicit `--checkpoint-only` flag gerekli)
- [x] Regression test PASS

**Tamamlanma Sonuçları (2026-02-13):**

- Kod değişiklikleri:
  - `main_parallel.py` resume parser'a `--db` eklendi.
  - `cmd_resume()` içinde `--db` zorunlu fail davranışı eklendi (DB verilmezse `return 1`).
  - `cmd_resume()` içinde DB path doğrulaması eklendi (`exists` + `is_file`).
  - Resume crawler init artık `db_path=str(db_path)` geçiriyor.
  - Resume akışına input path varlık/format doğrulaması eklendi.
  - `cmd_resume()` sonunda `crawler.close_db()` garanti edildi (`finally` bloğu).
- Regression testler:
  - Dosya: `tests/test_main_parallel.py`
  - Sonuç: `python -m pytest tests/test_main_parallel.py -q` → **4 passed**
- CLI doğrulaması:
  - `python main_parallel.py resume --input ... --checkpoint-dir ...` → `--db` olmadığı için **FAIL**
  - `python main_parallel.py resume --input data/_tmp_resume_ids.json --db data/atlas.db --checkpoint-dir data/checkpoints` → **PASS** (`Resume complete: 1000 total results.`)

**Tahmini Süre:** 1 gün

---

#### **P0.3 - Accounting Fix (1 gün)**

**Sahip:** TBD  
**Durum:** ⚪ Başlanmadı  
**Öncelik:** 🟡 HIGH

**NEDEN:**  
`parallel_crawler.py` elapsed time double-counted, `total_ids` resume'da güncellenmemiş.

**NASIL:**

1. **Elapsed Time Düzelt**
   - Loop sonunda bir kere hesapla (loop içinde değil)

2. **⚠️ Total IDs Düzelt (DİKKAT!)**
   - **❌ RİSKLİ YAKLAŞIM:** Checkpoint'tan kör al → stale değer riski
   - **✅ GÜVENLİ YAKLAŞIM:** Mevcut hedef listesiyle normalize et: `total_ids = len(current_target_list)`
   - **UYGULAMA:** Normalize approach kullan

3. **Throughput Metriklerini Yeniden Hesapla**

**KURALLAR:**

- Elapsed time: Sadece bir kere
- total_ids: Current list ile normalize

**Kontrol Listesi:**

- [ ] Elapsed double-count düzelt
- [ ] ⚠️ total_ids → normalize with current list (checkpoint'tan kör almak yerine)
- [ ] Throughput metriklerini yeniden hesapla
- [ ] Test: 50 proteinlik smoke test
- [ ] Test proving consistency yaz

**Kabul Kriterleri:**

- [ ] Elapsed time tutarlı
- [ ] total_ids doğru (current list ile)
- [ ] Smoke test PASS

**Tahmini Süre:** 1 gün

---

#### **P0.4 - Timeout Enforcement (1 gün)**

**Sahip:** TBD  
**Durum:** ⚪ Başlanmadı  
**Öncelik:** 🟡 HIGH

**NEDEN:**  
Timeout enforcement zayıf, hung worker'lar timeout'u aşabiliyor.

**NASIL:**

1. **Wall-Clock Timeout Ekle**
2. **Hung Worker Isolation Ekle**
3. **Deterministic Test Yaz**

**Kontrol Listesi:**

- [ ] Wall-clock timeout enforcement ekle
- [ ] Hung worker isolation ekle
- [ ] Deterministic test yaz (synthetic sleeper worker)
- [ ] Timeout behavior tests yaz

**Kabul Kriterleri:**

- [ ] Timeout tests PASS
- [ ] Hung worker isolated
- [ ] Deterministic test PASS

**Tahmini Süre:** 1 gün

---

**Hafta 1 Exit Criteria:**

- [ ] No silent zero-center writes
- [ ] Resume writes correctly to DB (or explicit checkpoint-only)
- [ ] Summary totals coherent
- [ ] Timeout tests pass

---

### 🟡 **Hafta 2: P1 - Bilimsel İyileştirmeler**

**Hedef:** Recall ve FPR'yi geçer hale getir

---

#### **P1.1 - Multi-Frame Aggregation (2-3 gün)**

**Sahip:** TBD  
**Durum:** ⚪ Başlanmadı  
**Öncelik:** 🔴 CRITICAL (Recall için)

**NEDEN:**  
Tek frame kullanımı domain motion, loop rearrangement gibi zor pocket'ları kaçırıyor.

**NASIL:**

1. **Multi-Frame Aggregation Ekle**
   - Tüm NMA frame'lerini kullan (sadece 1 değil)
   - Consensus scoring: En az 3 frame'de görülen pocket'lar

2. **Controlled Experiments**
   - 20 known cryptic pocket'ta test et
   - Pocket type bazında kazanım ölç

**Kontrol Listesi:**

- [ ] Multi-frame aggregation ekle
- [ ] Consensus scoring ekle (min 3 frame)
- [ ] Volume/center stability metrikleri ekle
- [ ] Controlled experiments (20 known pocket)
- [ ] Report gains by pocket type
- [ ] `docs/recall_recovery_experiments.md` üret

**Kabul Kriterleri:**

- [ ] Multi-frame aggregation çalışıyor
- [ ] Recall artışı ≥ %10 (10% → 20%+)
- [ ] Domain motion recall artışı ≥ %25

**Tahmini Süre:** 2-3 gün

---

#### **P1.2 - Overlap Recovery (1-2 gün)**

**Sahip:** TBD  
**Durum:** ⚪ Başlanmadı  
**Öncelik:** 🟡 HIGH

**NEDEN:**  
Center repair sonrası overlap'ın ne kadar artacağını ölçmek.

**Kontrol Listesi:**

- [ ] Center repair sonrası fpocket benchmark tekrar koştur
- [ ] Distance-only match hesapla
- [ ] Distance+volume match hesapla
- [ ] Overlap gain ölç (5.77% → ?)
- [ ] `docs/fpocket_benchmark_report.md` (v2) üret

**Kabul Kriterleri:**

- [ ] Overlap artışı ≥ %20 (5.77% → 25%+)
- [ ] Distance-only match ≥ %30

**Tahmini Süre:** 1-2 gün

---

#### **P1.3 - FPR Recovery (1-2 gün)**

**Sahip:** TBD  
**Durum:** ⚪ Başlanmadı  
**Öncelik:** 🟡 HIGH

**NEDEN:**  
Evidence fusion güçlendirerek FPR'yi düşürmek.

**NASIL:**

1. **Evidence Fusion Güçlendir**
   - Weighted scoring: Ligand (0.3), fpocket (0.3), Known (0.2), Docking (0.2)

2. **Manual Review**
   - Top 20 unsupported pocket'ı manuel incele

**Kontrol Listesi:**

- [ ] Evidence fusion weighted scoring ekle
- [ ] Unknown handling explicit yap
- [ ] Top 20 unsupported pocket manual review
- [ ] FPR analizi tekrar koştur
- [ ] `docs/false_positive_report.md` (v2) üret
- [ ] `docs/false_positive_manual_review.md` üret

**Kabul Kriterleri:**

- [ ] Conservative FPR ≤ 60%
- [ ] Manual review tamamlandı

**Tahmini Süre:** 1-2 gün

---

### 🟢 **Gate Rerun (1 gün)**

**Sahip:** TBD  
**Durum:** ⚪ Başlanmadı  
**Öncelik:** 🔴 CRITICAL (Final step)

**Kontrol Listesi:**

- [ ] Validation known set koştur
- [ ] fpocket benchmark koştur
- [ ] MD validation (skip, zaten PASS)
- [ ] False positive analysis koştur
- [ ] Gate decision generation
- [ ] Drift check PASS
- [ ] Center integrity report attach

**Kabul Kriterleri:**

- [ ] Tüm 4 gate PASS
- [ ] Drift check PASS
- [ ] Reports aligned

**Tahmini Süre:** 1 gün

---

## 🌳 Karar Ağacı (Gate Rerun Sonrası)

```
Gate Rerun
    ↓
Tüm Metrikler PASS?
    ├─ Evet → ✅ Faz 6'ya Geç (120K Protein Taraması)
    │
    └─ Hayır → Hangi Metrik FAIL?
        ├─ Recall → Multi-frame stratejisini güçlendir
        │           ⚠️ DİKKAT: Tolerance artırma (8Å → 10Å) PRE-REGISTRATION DRIFT olur!
        │           Eğer tolerance değiştirilecekse → AYRI "exploratory" koşu olarak yap
        │           Gate rerun için tolerance SABİT kalmalı (8.0Å)
        │
        ├─ Overlap → Center repair'i doğrula
        │            fpocket versiyonunu kontrol et
        │
        └─ FPR → Evidence fusion ağırlıklarını ayarla
                 Manual review ekle
```

---

## ⚠️ Risk Mitigation

| Risk                                  | Olasılık | Etki   | Mitigasyon                                                                                           |
| ------------------------------------- | -------- | ------ | ---------------------------------------------------------------------------------------------------- |
| **Center repair başarısız olursa**    | Orta     | Yüksek | Checkpoint JSON'dan geri yükle. Yoksa recompute. Hala yoksa `invalid_center` metadata ekle.          |
| **Multi-frame recall'ü yükseltmezse** | Orta     | Kritik | ⚠️ Tolerance artırma (8Å → 10Å) **pre-registration drift** olur! Ayrı "exploratory" koşu olarak yap. |
| **FPR hala %60 üstündeyse**           | Düşük    | Orta   | "Screening complement" olarak position et, MD validation gerektiğini vurgula.                        |
| **MD validation tekrarlanamıyorsa**   | Düşük    | Düşük  | 1G66 zaten PASS, tekrar koşturmaya gerek yok.                                                        |
| **Resume bug'ları devam ederse**      | Düşük    | Orta   | Resume yerine fresh scan kullan, checkpoint sadece monitoring için.                                  |

---

## 📊 Faz 5.5 Exit Rules (Strict)

**Faz 6'ya geçiş şartları (HEPSİ gerekli):**

1. ✅ Recall ≥ 0.30
2. ✅ fpocket overlap ≥ 0.40
3. ✅ Conservative FPR ≤ 0.60
4. ✅ MD validated proteins ≥ 1
5. ✅ Data integrity checks PASS (center integrity + summary consistency)

**Eğer herhangi biri FAIL:**

- ❌ Faz 6 remains blocked
- 🔄 Recovery loop continues

---

## 📝 Öğrenilenler

### ✅ Başarılar

1. **MD Validation PASS:** Fiziksel doğrulama başarılı (1G66)
2. **Otomatik Raporlama:** Publication paketi iyi çalıştı
3. **Pre-registration Discipline:** Drift kontrolü PASS

### ❌ Başarısızlıklar

1. **Center Integrity:** %88 zero-center (veri bozukluğu)
2. **Single-Frame Limitation:** Domain motion kaçırıldı
3. **Weak Evidence Fusion:** FPR çok yüksek (docking=0, known=0)

### 📚 Dersler

1. **Veri Integrity Kritik:** Benchmark'tan önce veri doğrulama şart
2. **Multi-Frame Gerekli:** Tek frame zor pocket'ları kaçırıyor
3. **Evidence Fusion Önemli:** Docking validation güçlendirilmeli
4. **Pre-registration Disiplini:** Tolerance drift = gate invalidation

---

## 🎯 Immediate Next Step

**ŞU AN:** Phase 5.5 execution complete, gate FAIL, Phase 6 BLOCKED

**SONRAKI ADIM:** Execute P0 backlog (data and pipeline correctness), then rerun the full gate.

**Timeline:**

- Hafta 1: P0 (veri + kod düzeltmeleri) + 50 proteinlik smoke test
- Hafta 2: P1 (bilimsel iyileştirmeler) + Full gate rerun

**Başarı Kriteri:** Tüm 4 gate metriği PASS → Faz 6'ya geç

---

_Son güncelleme: 2026-02-13 (ChatGPT feedback ile revize edildi)_  
_Durum: Recovery Sprint Başlangıcı_  
_Sonraki Adım: P0.1 - Center Integrity Repair_

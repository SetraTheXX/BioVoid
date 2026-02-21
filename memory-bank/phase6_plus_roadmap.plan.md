# Faz 6+ Yol Haritasi (Guncel)

- Last update: 2026-02-21
- Source of truth:
  - `docs/phase5_5_gate_decision.md`
  - `docs/recovery_v2_regression_guard_report.md`
  - `docs/phase6_transition_readiness_report.md`

## Mevcut Durum

Phase 5.5 strict gate sonucu PASS:

1. Recall: `0.3500 (7/20)`
2. fpocket overlap: `0.2597`
3. Conservative FPR: `0.1311`
4. MD validated proteins: `1`

Phase 6 durum etiketi:

1. Technical: `READY`
2. Operational: `IN_PROGRESS`

---

## Faz 6: Productization ve Controlled Release

Amac:

1. Bilimsel motoru kontrollu sekilde kullaniciya acmak.
2. Analiz kosularini izlenebilir, tekrar uretilebilir ve operasyonel hale getirmek.

Tahmini sure: 2-3 hafta
Durum: `IN_PROGRESS (Step 1/2/3 tamamlandi)`

### 6A Backend/API

Teslimatlar:

1. Job tabanli API (`submit`, `status`, `result`)
2. Worker queue + retry/backoff + timeout
3. OpenAPI/Swagger

Kabul kriteri:

1. 50 ardisik job smoke test PASS
2. Idempotency ve validation hatalari deterministic
3. Canonical lock request-level override edilemiyor

### 6B Web Portal

Teslimatlar:

1. Job submit ekrani
2. Job progress ve sonuc goruntuleme
3. Artifact download akisi

Kabul kriteri:

1. E2E: submit -> run -> result -> download PASS
2. Mobil/desktop uyumlu
3. Uzun sureli islerde UX fallback var (polling/cancel feedback)

### 6C Ops/Release Guard

Teslimatlar:

1. Health/readiness endpoints
2. Log correlation ids + temel dashboard
3. Release checklist + rollback runbook

Kabul kriteri:

1. Rollback provasi tek denemede PASS
2. CI icinde strict gate/guard snapshot adimlari calisiyor

### Faz 6 Exit Criteria

1. 6A/6B/6C kabul kriterleri PASS
2. En az 1 haftalik staging run'da kritik incident yok
3. Strict gate PASS korunuyor (drift yok)

### Faz 6 Execution Snapshot

1. Step 1 (Pre-start safety freeze): `COMPLETED`
   - `docs/phase6_step1_prestart_freeze_report.md`
2. Step 2 (6A Backend/API): `COMPLETED`
   - `docs/phase6_step2_backend_api_report.md`
3. Step 3 (6B Web portal): `COMPLETED`
   - `docs/phase6_step3_web_portal_report.md`
4. Step 4 (6C Ops/release guard): `PENDING`
5. Step 5 (Final integration + staging): `PENDING`

---

## Faz 7: AI Signal Layer (Classifier)

Amac:

1. Rule-based skora ek olarak model tabanli sinyal katmani eklemek.
2. False-positive azaltimi ve ranking kalitesini artirmak.

Tahmini sure: 3-4 hafta
Durum: `NOT_STARTED`

### 7A Dataset ve Labeling

1. Net etiket politikasi (positive/negative/uncertain)
2. Train/val/test split ve leakage kontrolu
3. Reproducible dataset manifest

### 7B Model ve Evaluation

1. Baseline model + calibration
2. Metrics: PR-AUC, ROC-AUC, recall@k, calibration error
3. Ablation ve error analysis

### Faz 7 Exit Criteria

1. Baseline'e gore anlamli iyilesme:
   - PR-AUC artisi
   - recall@k korunurken precision artisi
2. Leakage ve overfitting kontrolleri PASS
3. Model inference pipeline'da reproducible

---

## Faz 8: Performance ve Scale

Amac:

1. Buyuk olcekli tarama throughput'unu artirmak.
2. Cost/performance dengesini optimize etmek.

Tahmini sure: 2-3 hafta
Durum: `NOT_STARTED`

### 8A Compute Optimization

1. Hotspot profiling
2. CPU parallel tuning + optional GPU acceleration
3. Caching ve I/O iyilestirme

### 8B Atlas/Index Layer

1. Sonuc indexleme
2. Arama ve filtreleme katmani
3. Batch export/reporting

### Faz 8 Exit Criteria

1. Throughput hedefi staging'de dogrulandi
2. P95 latency hedefi saglandi
3. 24 saatlik stability test PASS

---

## Risk Register (Faz 6+)

1. SoT drift riski:
   - Onlem: gate/guard komutlari release oncesi zorunlu
2. Uzun kosu stabilitesi:
   - Onlem: timeout + bounded retry policy
3. Operasyonel maliyet:
   - Onlem: staging metriklerine gore autoscaling/cost caps
4. Bilimsel claim riski:
   - Onlem: strict gate PASS ve dis validasyon olmadan iddia yayini yok

---

## Faz 6 Baslatma Komutu (Sadece Onay Geldiginde)

```bash
python scripts/generate_phase5_5_gate_decision.py --gate-profile strict --fpocket-report docs/fpocket_benchmark_report.md
python scripts/run_recovery_v2_regression_guard.py --fpocket-report docs/fpocket_benchmark_report.md
python scripts/recovery_v2_intake_check.py --strict --recall-floor 0.30 --overlap-floor 0.25
```

Yukaridaki uc komut PASS ise Faz 6 implementation branch'leri acilir.

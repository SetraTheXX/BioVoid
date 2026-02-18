# Faz 6+ Yol Haritasi ve Uzun Vade Plani

> Kaynak: `memory-bank/progress.md` icinden tasindi
> Tasinma tarihi: 2026-02-18

## Not

- Bu dosya Faz 6 ve sonrasi uzun vade plan bloklarini toplar.
- Aktif Faz 5.5 / Recovery v2 takibi `memory-bank/progress.md`, `memory-bank/activeContext.md` ve `docs/recovery_v2_sprint_plan.md` uzerinden surer.

---

## Faz 6: Üretim ve Yayın

**Hedef:** Bio-Void Hunter'ı bir web portalı veya open-source araç olarak dünyaya duyurmak.

**Durum:** ⚪ Başlanmadı (0%)  
**Tahmini Süre:** 14 gün

**NEDEN:**  
Bilimsel araçlar, topluluk tarafından kullanılabildiği ölçüde değerlidir. Profesyonel bir lansman ve erişim kanalı şarttır.

### Alt Görevler

**Sahip:** Geliştirici  
**Durum:** ⚪ Başlanmadı  
**Tahmini Süre:** 8 saat

**NEDEN:**  
Topluluk erişimi için web portalı şarttır.

**NASIL:**

- **User Portal:** Araştırmacıların kendi PDB dosyalarını yükleyip analiz başlatabildiği bir web arayüzü.
- **Cloud Integration:** Analizlerin sunucu tarafında yapılıp sonucun mail veya link ile iletilmesi.

**KURALLAR:**

- API rate limiting olmalı.
- Kullanıcı authentication (opsiyonel).
- HTTPS zorunlu (production).

**Kontrol Listesi:**

- [ ] Örnek analiz sonuçlarından oluşan bir "Showcase" sayfası hazırla
- [ ] Kullanıcı portalı giriş noktasını aktif et
- [ ] Bulut entegrasyonu (AWS/Vercel) prototipini hazırla
- [ ] Rate limiting middleware ekle

**Kabul Kriterleri:**

```bash
# Web app deployment test
# Localhost'ta çalışıyor mu?
# API endpoint'ler response veriyor mu?
```

**Test Senaryosu:**

1. **Deployment:**
   - [ ] Localhost'ta açılıyor mu?
   - [ ] API erişilebilir mi?
2. **Kullanıcı Deneyimi:**
   - [ ] PDB yükleme çalışıyor mu?
   - [ ] Sonuç mail/link ile geliyor mu?

**Bağımlılıklar:**

- Gerektirir: Faz 5.3 (Dashboard) ⚪

**Engelleyiciler:**

- Hosting maliyeti → Vercel/Netlify free tier

**Öğrenilenler (Faz 6.1):**

_(Faz tamamlandığında doldurulacak)_

#### 6.2 Documentation & API Access

**Sahip:** Geliştirici
**Durum:** ⚪ Başlanmadı
**Tahmini Süre:** 6 saat

**NEDEN:**
Dokümantasyon olmadan araç kullanılamaz.

**NASIL:**

- **Bio-Void Docs:** Kapsamlı kurulum, kullanım ve bilimsel metodoloji rehberi.
- **REST API:** Diğer yazılımların Bio-Void Hunter skorlarını çekebilmesi için FastAPI tabanlı bir arayüz.

**KURALLAR:**

- README.md kapsamlı olmalı.
- API dokümantasyonu Swagger formatında.
- Kurulum scripti test edilmeli.

**Kontrol Listesi:**

- [ ] README.md'yi yayın standartlarına getir
- [ ] Kurulum scriptlerini (install.sh/bat) oluştur ve test et
- [ ] API dokümantasyonunu (Swagger/OpenAPI) tamamla
- [ ] Biyoinformatik topluluğu için "Quick Start Guide" ekle

**Kabul Kriterleri:**

**Test Adımları:**

1. **Fresh Install Test:** Tertemiz bir sanal ortamda (venv) kurulum yap ve hiçbir paketin eksik olmadığını doğrula.
2. **API Endpoint Test:** Tüm API uç noktalarını (endpoints) stres testine tabi tut.
3. **User Experience Test:** Bir meslektaşın (veya AI simülasyonunun) dashboard'u kullanarak ilk analizini yapmasını sağla.

**Öğrenilenler (Faz 6):**

_(Faz tamamlandığında doldurulacak)_

### Faz 6 Çıkış Kriterleri

- [ ] Tüm Faz 6 alt görevleri tamamlandı
- [ ] API üzerinden `GET /analyze` sorgusu geçerli JSON döndürüyor
- [ ] Dokümantasyon (README + Wiki) tam ve güncel
- [ ] Kurulum scripti (install.sh) temiz bir ortamda başarıyla çalıştı

---

## Faz 7: Bio-Void AI Intelligence (Deep Learning Classifier)

**Hedef:** Matteo Paz'ın "VARnet" algoritması gibi, hiyerarşik kuralları bir kenara bırakıp, derin öğrenme (Deep Learning) ile cepleri %90+ doğrulukla "İlaçlanabilir" veya "Gürültü" olarak sınıflandırmak.

**Durum:** ⚪ Başlanmadı (0%)  
**Tahmini Süre:** 21 gün

**NEDEN:**  
Matteo'nun kara delikleri değişkenlikten (variability) ayırması gibi, bizim de dinamik cepleri statik yüzey gürültülerinden ayırmamız gerekir.

### Alt Görevler

**Sahip:** Geliştirici  
**Durum:** ⚪ Başlanmadı  
**Tahmini Süre:** 10 saat

**NEDEN:**  
AI modeli için kaliteli veri seti şarttır.

**NASIL:**

- **Data Fragmenter:** 200,000+ protein yapısını küçük tensör paketlerine böl.
- **Labeling:** PDBbind cepleri "Positive Class" olarak işaretle.

**KURALLAR:**

- Veri seti dengeli olmalı (positive/negative).
- Fragmentasyon deterministik olmalı.
- Etiketleme doğrulanmalı.

**Kontrol Listesi:**

- [ ] 13,000+ veri paketi oluştur (Data Fragmenter)
- [ ] PDBbind ve BindingDB veri setlerini temizle (Cleaning)
- [ ] Etiketlenmiş (labeled) tensör veri setini doğrula
- [ ] Train/Val/Test split yap (70/15/15)

**Kabul Kriterleri:**

```python
from src.ai.fragmenter import DataFragmenter

fragmenter = DataFragmenter()
dataset = fragmenter.create_dataset(n_samples=1000)

assert len(dataset) == 1000
assert 'label' in dataset[0]
print("✅ Dataset oluşturuldu")
```

**Test Senaryosu:**

1. **Veri Kalitesi:**
   - [ ] Etiketler doğru mu?
   - [ ] Veri dengeli mi?
2. **Fragmentasyon:**
   - [ ] Deterministik mi?

**Bağımlılıklar:**

- Gerektirir: Faz 5 (Veri Havuzu) ⚪

**Engelleyiciler:**

- Yetersiz veri → Augmentation kullan

**Öğrenilenler (Faz 7.1):**

_(Faz tamamlandığında doldurulacak)_

**Sahip:** Geliştirici  
**Durum:** ⚪ Başlanmadı  
**Tahmini Süre:** 11 saat

**NEDEN:**  
Kural tabanlı puanlama yerine AI ile %90+ doğruluk hedefliyoruz.

**NASIL:**

- **Hierarchical Classification:** Orthosteric, Allosteric, Cryptic ayrımı.
- **Feature Fusion:** Voronoi + Elektrostatik + NMA RMSF → GNN.

**KURALLAR:**

- Model accuracy > %90.
- Training reproducible olmalı (seed).
- Validation set ayrı tutulmalı.

**Kontrol Listesi:**

- [ ] AI tabanlı "Druggability Classifier" (GNN) implementasyonu
- [ ] Kriptik cep tespit yeteneği testi (Validation set)
- [ ] Model doğruluk (Accuracy > %90) hedefine ulaşıldığını doğrula
- [ ] Overfitting kontrolü (Early stopping)

**Kabul Kriterleri:**

```python
from src.ai.classifier import BioClassifier

model = BioClassifier()
model.train(dataset, epochs=50)
accuracy = model.evaluate(validation_set)

assert accuracy > 0.90
print("✅ Model trained")
```

**Test Senaryosu:**

1. **Model Performansı:**
   - [ ] Accuracy > %90?
   - [ ] Overfitting yok mu?
2. **Tahmin Hızı:**
   - [ ] Cep başına < 10ms?

**Bağımlılıklar:**

- Gerektirir: Faz 7.1 (Dataset) ⚪
- Gerektirir: PyTorch

**Engelleyiciler:**

- Düşük accuracy → Daha fazla veri veya model tuning

**Öğrenilenler (Faz 7.2):**

_(Faz tamamlandığında doldurulacak)_

**Bağımlılıklar:**

- Gerektirir: Faz 5 (Veri Havuzu) ⚪
- Gerektirir: PyTorch ve PyTorch Geometric kütüphaneleri

**Öğrenilenler (Faz 7):**

_(Faz tamamlandığında doldurulacak)_

### Faz 7 Çıkış Kriterleri

- [ ] Tüm Faz 7 alt görevleri tamamlandı
- [ ] Bio-Classifier model doğruluğu (Accuracy) > %90
- [ ] CrypticSite validasyon setinde başarılı tahminler yapıldı
- [ ] Tahmin süresi cep başına < 10ms

---

## Faz 8: High-Performance GPU Core (The Speed Monster)

**Hedef:** Analiz hızını "53 Mikrosaniye" hedefine yaklaştırmak; tüm PDB'yi günler içinde tarayarak "Proteome Discovery Atlas" oluşturmak.

**Durum:** ⚪ Başlanmadı (0%)  
**Tahmini Süre:** 15 gün

### Alt Görevler

**Sahip:** Geliştirici  
**Durum:** ⚪ Başlanmadı  
**Tahmini Süre:** 8 saat

**NEDEN:**  
CPU çok yavaş, GPU ile 100x hızlanma hedefliyoruz.

**NASIL:**

- **Zero-Latency Processing:** GPU üzerinde CuPy ve PyTorch kullan.
- **Batch Analysis:** Saatte 5,000+ protein tara.

**KURALLAR:**

- GPU memory yönetimi olmalı.
- CPU fallback olmalı.
- Batch processing optimize edilmeli.

**Kontrol Listesi:**

- [ ] GPU optimizasyonu (Protein başına < 500ms hedefi)
- [ ] CUDA kernel darboğazlarını (bottlenecks) tespit et ve iyileştir
- [ ] CuPy/PyTorch bellek yönetimini (VRAM) optimize et
- [ ] CPU fallback modu ekle

**Kabul Kriterleri:**

```python
from src.gpu.cuda_pipeline import CUDAPipeline

pipeline = CUDAPipeline(device='cuda:0')
results = pipeline.process_batch(proteins, batch_size=32)

assert len(results) == len(proteins)
print("✅ CUDA pipeline çalışıyor")
```

**Test Senaryosu:**

1. **GPU Performansı:**
   - [ ] Protein başına < 500ms?
   - [ ] Memory leak yok mu?
2. **Fallback:**
   - [ ] GPU yoksa CPU'ya geçiyor mu?

**Bağımlılıklar:**

- Gerektirir: NVIDIA GPU + CUDA
- Gerektirir: CuPy

**Engelleyiciler:**

- GPU yok → CPU fallback

**Öğrenilenler (Faz 8.1):**

_(Faz tamamlandığında doldurulacak)_

**Sahip:** Geliştirici  
**Durum:** ⚪ Başlanmadı  
**Tahmini Süre:** 7 saat

**NEDEN:**  
Tüm keşifleri tek bir "galaksi haritası" gibi sunmak.

**NASIL:**

- **The Atlas:** 1-2 milyon cep verisi.
- **Disease Mapping:** Hastalık ilişkilendirmesi.

**KURALLAR:**

- Atlas 1M+ veri noktası desteklemeli.
- Arama < 1 saniye.
- Görselleştirme optimize edilmeli.

**Kontrol Listesi:**

- [ ] Tüm Proteom (İnsan) tarama testini tamamla
- [ ] Final "Discovery Atlas" interaktif görselleştirmesi (Plotly Web)
- [ ] Arama motoru ve hastalık filtreleme sistemini doğrula
- [ ] Indexleme ve caching ekle

**Kabul Kriterleri:**

```python
from src.atlas import GlobalAtlas

atlas = GlobalAtlas()
atlas.load_data('data/global_atlas.db')
results = atlas.search(disease='cancer', min_score=0.8)

assert len(results) > 0
print("✅ Global Atlas çalışıyor")
```

**Test Senaryosu:**

1. **Ölçeklenebilirlik:**
   - [ ] 1M kayıt yüklen

**Bağımlılıklar:**

- Gerektirir: NVIDIA GPU ve CUDA Toolkit
- Gerektirir: Faz 7 (AI Classifier) ⚪

**Öğrenilenler (Faz 8):**

_(Faz tamamlandığında doldurulacak)_

### Faz 8 Çıkış Kriterleri

- [ ] Tüm Faz 8 alt görevleri tamamlandı
- [ ] Analiz hızı hedefi (protein başına < 500ms) yakalandı
- [ ] Atlas arayüzü 1 milyon veri noktasını akıcı şekilde yönetiyor
- [ ] Sistem 24 saatlik stres testini (High-Throughput) başarıyla geçti

---

## Bilinen Sorunlar / Riskler

- **Donanım Limitleri:** Çok büyük proteinler (>5000 atom) Python'da bellek sorununa yol açabilir. Çözüm: C++ modülleri veya GPU hızlandırma (Faz 5.2).
- **Yanlış Pozitifler:** Geometrik analiz birçok boşluk bulur. Hidrofobik filtre çok sağlam olmalı. Çözüm: AI tabanlı sınıflandırma (Faz 7.2).
- **Vina Performansı:** CPU-only Vina yavaş. Çözüm: Vina-GPU fork'u kullan (Faz 8.1).

---

## Öğrenilenler

- **Donanım Limitleri:** Çok büyük proteinler (>5000 atom) Python'da bellek sorununa yol açabilir. Çözüm: C++ modülleri veya GPU hızlandırma (Faz 5.2/8.1).
- **Yanlış Pozitifler:** Geometrik analiz birçok boşluk bulur. Hidrofobik filtre çok sağlam olmalı. Çözüm: AI tabanlı sınıflandırma (Faz 7.2).
- **Vina Performansı:** CPU-only Vina yavaş. Çözüm: Vina-GPU fork'u kullan (Faz 8.1).
- **Veri Kirliliği:** PDB'deki her yapı kaliteli değil. Çözüm: Crawler filtreleri (Faz 5.1).

---

## Öğrenilenler (Genel)

- **Faz 0:** Kapsamlı dokümantasyon, AI'ın bağlamı koruması için hayati.
- **Faz 1:**
  - ✅ NMA matematiği NumPy ile saf bir şekilde kurulmalı.
  - ✅ Voronoi analizi Liang et al. (1998) algoritmasına uymalı (Sadece mesafe yetmez!).
  - ✅ Test senaryoları "Matteo Paz Standartları"nda çok katı olmalı.
- **Faz 2.6 (Görselleştirme):** Non-druggable cepleri tamamen silmek yerine context olarak tutmak, bilimsel derinliği artırıyor.
- **Yol Haritası:** Matteo Paz'ın VARnet mimarisi (Fragmenting & Classification), büyük ölçekli taramalar için "Altın Standart" olarak projeye eklendi.

---

## 🏛️ Bilimsel Manifesto & Stratejik Konumlandırma

Bu proje artık sadece bir araç değil; **"Milyonlarca Protein Verisini Milisaniyeler İçinde Tarayıp Yeni İlaç Hedefleri Keşfeden Bir Uzay Teleskobu"** gibi konumlandırılmıştır. Faz 2.5 itibarıyla "Hype-driven" bir dilden, ağırbaşlı ve bilimsel olarak savunulabilir bir dile geçiş yapmıştır.

### 🔍 Bilimsel Prensipler:

1.  **NMA vs MD (Mikroskop vs Teleskop):** Bio-Void Hunter, Moleküler Dinamiğin (MD) yerine geçmez. MD'nin pratik olmadığı devasa yapı setlerini (High-Throughput) tarayıp, derinlemesine incelenmesi gereken adayları seçen bir **"Pre-filtering Engine" (Ön Filtreleme Motoru)**'dur.
2.  **Akademik Duruş (Complementation):** Mateo Paz gibi araştırmacıların derinlemesine çalışmalarına rakip değil, onlara yüksek hacimli ön veri sağlayan bir **"Tamamlayıcı Katman"**dır.
3.  **Dürüst Bilim:** "%100 Kanıt" gibi mutlak ifadelerden kaçınılır. Bunun yerine, "Deneysel verilerle **yüksek korelasyon (consistency)** sağlayan sonuçlar" dili kullanılır.
4.  **Kod vs Anlatım Uyumu:** Projenin modüler ve profesyonel kod mimarisi, anlatım dilindeki ciddiyetle desteklenmelidir.

### 🧭 Stratejik Kararlar:

- **Framing (Çerçeveleme):** Proje artık "Dünya deviren yazılım" değil; **"Geniş Ölçekli Cryptic Pocket Taraması için Hızlı ve Ölçeklenebilir Bir Ön Filtreleme Motoru"** olarak tanımlanır.
- **Kalıcı Önlem:** İddialarda "Replacement" (Yerine geçme) değil, "Complementation" (Tamamlama) vurgusu esastır. Hız avantajı (3 saniyede analiz), bu tamamlayıcılığın en büyük teknik kanıtıdır.

---

**Not:** Bu dosya her faz sonunda güncellenecek.


---

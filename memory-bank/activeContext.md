# Aktif Bağlam

## Şu Anki Odak

Şu anda **Başlatma & Mimari Tasarım Aşaması**ndayız.
Birincil hedef, gelişmiş biyolojik simülasyonlar gerçekleştirmek için tüketici donanımından (RX 580) yararlanan "Bio-Void Hunter" için sağlam, bilimsel olarak geçerli bir boru hattı oluşturmaktır.

## Son Kararlar

- **Astronomiden Biyolojiye Geçiş:** "Matteo Paz" metodolojisini (Gürültülü verideki gizli sinyaller) protein yapılarındaki Gizli Cepleri bulmaya uyarlama.
- **Dinamik Analiz (NMA):** Yalnızca statik yapıları kullanmamaya karar verdik. Protein nefes alma hareketlerini simüle etmek için Normal Mod Analizi (ProDy) kullanacağız.
- **Geometrik Çekirdek:** Çıkarım motoru için ağır Derin Öğrenme eğitiminden kaçınıyor, hızlı, fizik tabanlı geometrik algoritmaları (Voronoi) tercih ediyoruz. Bu, VRAM-ağır LLM eğitiminden daha iyi RX 580'in hesaplama yeteneklerine uyuyor.

## Sonraki Adımlar

1.  **Ortam Kurulumu:** `ProDy`, `Scipy`, `AutoDock Vina` kur.
2.  **NMA Prototipi:** Bir protein al (örn: p53), 50 konformasyon simüle et ve kaydet.
3.  **Voronoi Prototipi:** Bu konformasyonlarda boşlukları bulmak için geometrik tarayıcıyı yaz.
4.  **Entegrasyon:** Bunları `BioBuildContext` boru hattında birleştir.

## Aktif Sorular

- Kullanıcıda `AutoDock Vina` kurulu mu yoksa kurulumu yönlendirmemiz mi gerekiyor?
- RX 580, Vina için OpenCL üzerinden mi kullanılacak, yoksa ilk prototip için CPU'ya mı güveneceğiz? (Öneri: Stabilite için CPU ile başla, daha sonra GPU ile optimize et).

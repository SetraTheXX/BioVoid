# Bio-Void Hunter 🧬

**Bio-Void Hunter**, proteinler üzerindeki "gizli cepleri" (cryptic pockets) keşfetmek için tasarlanmış yüksek performanslı bir biyoinformatik aracıdır. Bu proje, Matteo Paz'ın astronomik keşif metodolojisini biyolojik verilere (protein dinamikleri) uyarlar.

## 🚀 Temel Özellikler

- **Dinamik Analiz:** Statik yapılar yerine Protein Normal Mod Analizi (NMA) kullanarak proteinlerin hareketlerini simüle eder.
- **Geometrik Keşif:** Voronoi diyagramları kullanarak protein içinde geçici olarak açılan boşlukları tespit eder.
- **Akıllı Filtreleme:** Hidrofobik özelliklere dayalı olarak keşfedilen boşlukların ilaçlanabilirliğini analiz eder.
- **Hesaplamalı Doğrulama:** AutoDock Vina entegrasyonu ile bulunan ceplere sanal docking testi uygular.
- **Donanım Optimizasyonu:** Tüketici sınıfı donanımlarda (örn: AMD RX 580) OpenCL hızlandırma ile çalışacak şekilde tasarlanmıştır.

## 🛠️ Kurulum

```bash
# Depoyu klonlayın
git clone https://github.com/SetraTheXX/BioVoid.git
cd BioVoid

# Gerekli paketleri kurun
pip install -r requirements.txt
```

### Faz 5.5 Hazırbulunuşluk (fpocket)

```bash
# fpocket (önerilen)
conda install -c bioconda fpocket=4.1

# alternatif (mamba)
mamba install -c bioconda fpocket=4.1
```

Kurulum sonrası doğrulama:

```bash
fpocket -h
```

## 📂 Dizin Yapısı

- `src/`: Ana kaynak kodları (dynamics, geometry, docking).
- `data/`: PDB verileri, simülasyon kareleri ve sonuçlar.
- `memory-bank/`: Proje dokümantasyonu ve hafıza bankası.

## 📜 Lisans

Bu proje MIT Lisansı ile lisanslanmıştır. Daha fazla bilgi için `LICENSE` dosyasına bakın.

<!-- cspell:disable -->

# Sistem Kalıpları

## Mimari Genel Bakış

Bio-Void Hunter, bellek yükünü minimize ederken hesaplama verimini maksimize eden sıralı bir boru hattı olarak çalışır.

```mermaid
flowchart TD
    Input[Kullanıcı Girişi: PDB ID] --> Fetch[Getirici Modül\n(Biopython)]
    Fetch --> Clean[PDB Temizleyici\n(Çözücü/ligand kaldır)]
    Clean --> NMA[Dinamik Motor\n(ProDy NMA)]

    subgraph Simülasyon Döngüsü
        NMA --> Conf[50-100 Konformasyon Oluştur]
        Conf --> Geo[Geometrik Tarayıcı\n(Voronoi/Alpha Shapes)]
        Geo --> Filter{Filtre Metrikleri}

        Filter -- Başarısız --> Trash[At]
        Filter -- Geçti --> Candidate[Aday Cep]
    end

    Candidate --> Cluster[Tekrarlanan Cepleri Kümele]
    Cluster --> Dock[Doğrulama Motoru\n(AutoDock Vina)]
    Dock --> Report[Nihai Rapor & PyMOL Script]
```

## Temel Bileşenler

### 1. Dinamik Motor (NMA)

- **Yöntem:** Anizotropik Ağ Modeli (ANM) veya Gauss Ağ Modeli (GNM).
- **Rol:** Proteinin düşük frekanslı normal modlarını (titreşimlerini) hesaplar.
- **Çıktı:** Proteini farklı "açık" durumlarda temsil eden bir 3D yapı topluluğu.

### 2. Geometrik Tarayıcı

- **Algoritma:** Voronoi Tessellation (birincil) ve Alpha Shape hesaplaması (ikincil).
- **Rol:** Protein yapısı içindeki boş hacimleri tanımlar.
- **Optimizasyon:** Python çok yavaşsa `scipy.spatial.Voronoi` veya optimize edilmiş C++ bağlantıları kullanır.

### 3. Filtreleme Mantığı ("Beyin")

Bir cep yalnızca katı kriterleri karşılarsa "geçerli"dir:

- **Hacim:** > 200 Å³ (Küçük bir molekül için yeterince büyük).
- **Gömülülük:** Yüzeye erişim var ama çoğunlukla kapalı.
- **Hidrofobiklik:** Cebi kaplayan hidrofobik kalıntıların oranı > Eşik (ilaçlanabilirliği garanti eder).

### 4. Doğrulama Motoru (Docking)

- **Araç:** AutoDock Vina.
- **Süreç:** Genel bir prob (örn: benzen veya bilinen bir fragment) kullanarak yeni bulunan cebe kör docking.
- **Metrik:** Bağlanma Enerjisi (kcal/mol).

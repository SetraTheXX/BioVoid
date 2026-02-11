<!-- cspell:disable -->

# Proje Özeti: Bio-Void Hunter

## Temel Felsefe

"Bio-Void Hunter", bilimsel keşfi demokratikleştirmek için tasarlanmış yüksek performanslı bir hesaplamalı biyoloji girişimidir. Matteo Paz'ın "gürültülü" veri kullanarak yaptığı astronomik keşiflerden ilham alarak, bu proje biyolojik verilere gelişmiş geometrik algoritmalar ve Normal Mod Analizi (NMA) uygular. Amaç, tüketici sınıfı donanım (özellikle RX 580 GPU'lar için optimize edilmiş) kullanarak proteinler üzerindeki "gizli cepleri"—görünmeyen, geçici ilaçlanabilir bölgeleri—tespit etmektir.

## Hedefler

1.  **Bilimsel Keşif:** Statik kristal yapılarda görünmeyen, hedef bir protein üzerinde (örn: p53, RAS) en az bir yeni, geçerli "gizli cep" tespit etmek.
2.  **Teknolojik İnovasyon:** Karmaşık biyolojik simülasyonların (NMA + Geometrik Analiz) devasa süper bilgisayarlara veya derin öğrenme modeli eğitimine ihtiyaç duymadan tüketici donanımında verimli bir şekilde çalıştırılabileceğini kanıtlamak.
3.  **Doğrulama:** Bulguları Moleküler Docking (AutoDock Vina) kullanarak hesaplamalı olarak doğrulamak ve teorik ilaçlanabilirliği göstermek.

## Temel Farklılaştırıcılar

- **Dinamik vs Statik:** Statik PDB dosyalarına bakan geleneksel yöntemlerin aksine, proteinlerin "nefes alma" hareketlerini analiz ediyoruz.
- **Matematik vs AI Eğitimi:** Büyük Dil Modelleri veya Derin Sinir Ağları eğitiminin ağır VRAM maliyetinden kaçınarak, çıkarım için saf matematiksel/fizik tabanlı yaklaşımlar (Elastik Ağ Modelleri, Voronoi Tessellation) kullanıyoruz.
- **Tüketici Donanımı:** Kullanıcının özel RX 580 kurulumu için optimize edilmiş, uygun yerlerde OpenCL/Compute shader'lardan yararlanıyor.

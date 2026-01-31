"""
Bio-Void Hunter: PyMOL Kurulum Raporu
=====================================

DURUM: ⚠️ Kısmi Başarısız

SORUN:
------
PyMOL 3.2.0a0 pip ile kuruldu ancak DLL hatası veriyor:
"DLL load failed while importing _cmd: Belirtilen modül bulunamadı."

NEDEN:
------
Windows'ta PyMOL'ün C++ extension'ları için Visual C++ Redistributable gerekiyor.
pymol-open-source paketi bu bağımlılıkları otomatik yüklemiyor.

ÇÖZÜM SEÇENEKLERİ:
------------------

1. **CONDA KURULUMU (ÖNERİLEN):**
   ```bash
   # Miniconda indir: https://docs.conda.io/en/latest/miniconda.html
   conda create -n biovoid python=3.13
   conda activate biovoid
   conda install -c conda-forge pymol-open-source
   ```
   
   Avantajlar:
   - Tüm bağımlılıklar otomatik yüklenir
   - Windows'ta en stabil çözüm
   - Bilimsel Python paketleri için optimize edilmiş
   
   Dezavantajlar:
   - Ekstra kurulum gerektirir (~500 MB)
   - Yeni bir environment yönetimi

2. **VISUAL C++ REDISTRIBUTABLE KURULUMU:**
   ```
   # Microsoft Visual C++ 2015-2022 Redistributable indir:
   https://aka.ms/vs/17/release/vc_redist.x64.exe
   
   # Kurulumdan sonra:
   pip uninstall pymol-open-source
   pip install pymol-open-source
   ```
   
   Avantajlar:
   - Mevcut Python ortamını kullanır
   - Daha az disk alanı
   
   Dezavantajlar:
   - Manuel kurulum gerektirir
   - Başarı garantisi yok

3. **ALTERNATİF: MATPLOTLIB 3D (GEÇİCİ ÇÖZÜM):**
   ```python
   # Matplotlib zaten kurulu (v3.10.8)
   # 3D scatter plot ile basit görselleştirme
   from mpl_toolkits.mplot3d import Axes3D
   ```
   
   Avantajlar:
   - Hemen kullanılabilir
   - Ek kurulum gerektirmez
   - Basit görselleştirmeler için yeterli
   
   Dezavantajlar:
   - PyMOL kadar gelişmiş değil
   - Protein yapılarını göstermek zor
   - Bilimsel yayınlar için yetersiz

4. **ALTERNATİF: NGLView (JUPYTER NOTEBOOK):**
   ```bash
   pip install nglview
   # Jupyter notebook gerektirir
   ```
   
   Avantajlar:
   - Modern web-based görselleştirme
   - İnteraktif
   
   Dezavantajlar:
   - Jupyter notebook gerektirir
   - Script modunda kullanılamaz

ÖNERİ:
------
Faz 1.4'ü şimdilik "Kısmi Tamamlandı" olarak işaretleyelim ve iki yol izleyelim:

1. **KISA VADEDE:** Matplotlib 3D ile basit görselleştirme (Faz 2 için yeterli)
2. **UZUN VADEDE:** Conda kurulumu (Faz 5 - Yayın hazırlığı için)

KARAR:
------
Kullanıcıya sorulacak:
- Şimdi Conda kurmak ister misiniz? (15 dakika)
- Yoksa Matplotlib ile devam edip Faz 2'ye geçelim mi?

TEST SONUÇLARI:
--------------
✅ PyMOL paketi kuruldu (3.2.0a0)
❌ Import başarısız (DLL hatası)
⚪ Diğer testler yapılamadı

SONRAKI ADIMLAR:
---------------
1. Kullanıcı kararı bekle
2. Eğer Matplotlib: `scripts/test_matplotlib_3d.py` oluştur
3. Eğer Conda: Conda kurulum rehberi göster
"""

print(__doc__)

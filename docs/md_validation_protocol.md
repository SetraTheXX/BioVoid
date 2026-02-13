# Faz 2 (1G66) MD Validation Protocol — Preflight & Smoke-Test

- Tarih (UTC): 2026-02-12T20:45:38Z
- Kapsam: Faz 2 hazırlık; uzun 100ns koşu başlatılmaz
- Hedef protein: **1G66**

---

## 1) Motor Seçimi

### Birincil motor
- **GROMACS** (eğer `gmx` erişilebilir ise)

### Fallback motor (bu ortamda aktif)
- **OpenMM 8.4.0 + MDAnalysis 2.9.0** (Python 3.10 venv: `.mdvenv`)

### Ortam sonucu (özet)
- `gmx`: bulunamadı
- `nvidia-smi`/`nvcc`: bulunamadı
- GPU: AMD Radeon RX 580
- OpenMM platformları: `Reference`, `CPU`, `OpenCL`
- OpenCL cihazı: `Ellesmere`

Bu nedenle Faz 2 için işletilebilir motor: **OpenMM (OpenCL/CPU fallback)**.

---

## 2) 1G66 Giriş Dosyaları

Zorunlu giriş:
- `data/raw_pdb/1g66.pdb`

Doğrulama:
- OpenMM ile PDB okuma başarılı (`PDB_READ_OK 3130 514`)
- MDAnalysis ile PDB parse başarılı (`1G66_atoms 3223`, `1G66_residues 514`)

---

## 3) Preflight Kontrol Komutları ve Sonuçları

Aşağıdaki komutlar `c:/Users/tunca/Desktop/Proje` altında çalıştırılmıştır:

1. Python/env
```cmd
python --version
.venv\Scripts\python --version
py -3.10 --version
```
Sonuç: Python 3.13.6 + Python 3.10.11 mevcut

2. GROMACS/GPU sistem kontrolü
```cmd
where gmx
where nvidia-smi
where nvcc
wmic path win32_VideoController get Name
```
Sonuç: `gmx/nvidia-smi/nvcc` bulunamadı; GPU adı `Radeon RX 580 Series`

3. Faz 2 bağımlılık kurulumu (fallback)
```cmd
py -3.10 -m venv .mdvenv
.mdvenv\Scripts\python -m pip install --upgrade pip
.mdvenv\Scripts\python -m pip install openmm MDAnalysis
```
Sonuç: kurulum başarılı (`openmm-8.4.0.post2`, `MDAnalysis-2.9.0`)

4. OpenMM smoke test (toy system)
```cmd
.mdvenv\Scripts\python -c "import openmm as mm; import openmm.unit as u; s=mm.System(); [s.addParticle(39.9*u.amu) for _ in range(2)]; f=mm.HarmonicBondForce(); f.addBond(0,1,0.3*u.nanometer,300*u.kilojoule_per_mole/u.nanometer**2); s.addForce(f); i=mm.LangevinIntegrator(300*u.kelvin,1/u.picosecond,0.002*u.picoseconds); p=mm.Platform.getPlatformByName('OpenCL'); c=mm.Context(s,i,p); c.setPositions([(0,0,0),(0.35,0,0)]*u.nanometer); print('OpenCL_Device',p.getPropertyValue(c,'DeviceName'))"
```
Sonuç: OpenCL cihazı `Ellesmere` ile context açıldı

5. 1G66 dosya smoke test
```cmd
.mdvenv\Scripts\python -c "from openmm.app import PDBFile; p=PDBFile('BioVoid/data/raw_pdb/1g66.pdb'); print('PDB_READ_OK', p.topology.getNumAtoms(), p.topology.getNumResidues())"
.mdvenv\Scripts\python -c "import MDAnalysis as mda; u=mda.Universe('BioVoid/data/raw_pdb/1g66.pdb'); print('MDAnalysis',mda.__version__,u.atoms.n_atoms,u.residues.n_residues)"
```
Sonuç: başarılı

---

## 4) Kısa Koşu Planı (Smoke-Test)

Amaç: Uzun üretim (100ns) öncesi başlatılabilirlik doğrulaması

Plan:
1. `1g66.pdb` yükle
2. OpenMM forcefield ile sistem kurulum denemesi
3. 1000–5000 adım minimizasyon + çok kısa NVT (ör. 10 ps)
4. Çıktı dosyaları: kısa log + kısa trajectory (opsiyonel)

Not: Bu adım “bilimsel doğrulama” değil, yalnızca runtime/araç zinciri doğrulamasıdır.

---

## 5) Başarı / Başarısızlık Kriterleri

### Başarı
- OpenMM context OpenCL veya CPU’da açılmalı
- 1G66 giriş dosyası parse edilebilmeli
- Kısa minimizasyon ve kısa integrasyon adımları hata vermeden tamamlanmalı
- Log dosyasında NaN/instability olmamalı

### Başarısızlık
- Context oluşturulamaması
- Topoloji/parametrizasyon hatası
- İlk kısa adımlarda numerik patlama veya NaN

---

## 6) Checkpoint ve Yeniden Deneme Kuralı

- Önce OpenCL ile dene
- OpenCL hata verirse CPU platformuna otomatik fallback uygula
- Parametrizasyon hatasında:
  1. PDB temizliği (hetero/water/eksik atom kontrolü)
  2. forcefield uyumluluğu kontrolü
  3. yeniden minimizasyon
- En fazla 3 kısa deneme; her deneme sebep/çıktı ile loglanır

---

## 7) Faz 2 Başlatma Ön Koşul Kararı

- Bu aşamada Faz 2 için **smoke-test hazır** durumuna geçilmiştir.
- Uzun 100ns koşu bu protokol kapsamında **başlatılmamıştır**.

---

## 8) 1G66 Kısa MD Smoke-Test Çalıştırma (OpenMM)

Çalıştırma komutu (birebir):

```cmd
.mdvenv\Scripts\python BioVoid\scripts\phase2_md_smoketest_1g66.py --input BioVoid\data\raw_pdb\1g66.pdb --platform OpenCL --steps 5000
```

Beklenen artefaktlar:
- `BioVoid/data/md_smoke/1g66/md_smoke_1g66_log.csv`
- `BioVoid/data/md_smoke/1g66/md_smoke_1g66_final.pdb`
- `BioVoid/data/md_smoke/1g66/md_smoke_1g66_summary.json`

Not:
- OpenCL hata verirse aynı komut `--platform CPU` ile yeniden çalıştırılır.

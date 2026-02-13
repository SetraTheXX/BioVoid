# Center Integrity Report (P0.1)

- Tarih (UTC): `2026-02-13T07:07:54.874777+00:00`
- DB: `data/atlas.db`
- Checkpoint JSONL: `data/checkpoints/crawler_log.jsonl`
- Dry run: `False`

## Özet

- Toplam pocket: **39085**
- Zero-center (önce): **34458**
- Checkpoint ile düzeltildi: **34458**
- Recompute ile düzeltildi: **0**
- `invalid_center=1` olarak işaretlendi: **0**
- Zero-center (sonra): **0**
- Zero-center + invalid_center=1 (sonra): **0**
- Zero-center + invalid_center!=1 (sonra): **0**

## Checkpoint Geri Yükleme

- JSONL satır sayısı: **1010**
- JSONL parse error: **0**
- JSONL protein (cavity olan): **932**
- JSONL cavity sayısı: **39269**
- JSONL valid center sayısı: **39269**
- Checkpoint recovery oranı (zero-center bazında): **100.00%**

## Recompute

- Recompute denenen protein: **0**
- Recompute başarısız protein: **0**
- Recompute merkez eşleşmesi bulunamayan satır: **0**

## Kabul Kriteri Kontrolü

- Zero-center count = 0 (veya sadece invalid): **PASS**
- Checkpoint restore >= %80: **PASS**

## Write-Time Guard Testi

- Test yaklaşımı: geçici DB üzerinde `AtlasDB.insert_discovery()` ile iki kayıt denendi.
- Test 1: `center=np.array([1.2, -3.4, 5.6])` için center parse doğrulandı (**PASS**).
- Test 2: `center=[0,0,0]` için soft-guard devreye girip metadata'ya `invalid_center=1` eklendi (**PASS**).

## Write-Time Guard Production Doğrulaması

- Implementasyon yeri: `src/database.py:393` (`insert_discovery`)
- Guard metadata satırları: `src/database.py:468` (`invalid_center=1`), `src/database.py:469` (`invalid_center_reason`), `src/database.py:470` (`center_guard_mode`)
- Runtime warning satırı: `src/database.py:472`


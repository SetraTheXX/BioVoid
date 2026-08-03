# BioVoid Run Manifest v1

> **Durum:** DRAFT
> **Specification ID:** `biovoid-run-manifest-v1`
> **Recovery fazı:** Faz 0-2
> **Normative amaç:** Her analizin input, config, code, environment ve output kimliğini tekrar üretilebilir biçimde kaydetmek

This specification contains only the technical run-manifest contract.

## 1. Temel İlkeler

1. Her analysis run benzersiz, immutable bir `run_id` taşır.
2. Aynı PDB ID farklı preparation veya config ile ayrı run olarak coexist eder.
3. Legacy dosya yolları yeni run workspace'i olarak kullanılamaz.
4. Manifest analizin başında oluşturulur, aşamalar ilerledikçe append-only durum alanlarıyla tamamlanır.
5. Hash alınamayan zorunlu input canonical analizi durdurur.
6. Generated data public Git commit kapsamına girmez.

## 2. Zorunlu Alanlar

```json
{
  "schema_version": "biovoid-run-manifest-v1",
  "run_id": "uuid",
  "created_at_utc": "ISO-8601",
  "finished_at_utc": null,
  "status": "created|running|succeeded|failed|cancelled",
  "validation_status": "legacy_non_validated|experimental|canonical",
  "canonical_eligible": false,
  "source": {
    "provider": "rcsb|alphafold|local",
    "accession": "string",
    "revision": "string|null",
    "format": "pdb|mmcif",
    "input_sha256": "hex"
  },
  "preparation": {
    "policy_id": "string",
    "config_sha256": "hex",
    "prepared_structure_sha256": "hex|null",
    "assembly": "string|null",
    "chains": [],
    "warnings": []
  },
  "pipeline": {
    "git_commit": "hex",
    "dirty_worktree": false,
    "detector_id": "string",
    "detector_config_sha256": "hex",
    "scoring_contract_id": "string",
    "experimental_features": []
  },
  "environment": {
    "python_version": "string",
    "platform": "string",
    "dependency_lock_sha256": "hex|null"
  },
  "resources": {
    "resource_profile": "safe-16gb",
    "worker_limit": 2,
    "peak_rss_bytes": null,
    "wall_clock_seconds": null
  },
  "outputs": {
    "workspace": "data/runtime/runs/<run_id>",
    "report_sha256": null,
    "pocket_count": null,
    "warnings": []
  }
}
```

## 3. Kimlik ve Hash Kuralları

- SHA-256 lowercase hexadecimal olarak saklanır.
- Config hash canonical JSON serialization üzerinden üretilir.
- Absolute kullanıcı path'leri portable manifest alanına yazılmaz.
- Public manifest kişisel kullanıcı adı veya makine dizini taşımaz.
- Dirty worktree analizi yapılabilir ancak `canonical_eligible=false` olmak zorundadır.

## 4. Workspace Kuralları

- Root: `data/runtime/runs/<run_id>/`
- Workspace başlangıçta boş ve run'a özel olmalıdır.
- Başka run'a ait frame veya report dosyası okunamaz.
- Legacy `data/frames`, `data/results`, `data/.cache` ve `data/atlas.db` yazma hedefi olamaz.
- Canonical file listesi manifestten okunur; directory glob tek başına kaynak olamaz.

## 5. Faz 0 Durumu

Faz 0 sırasında:

- Runtime ve legacy path sınırları oluşturulur.
- Current pipeline çıktıları `legacy_non_validated` olarak işaretlenir.
- ML, docking ve motion-aware katmanlar default-off tutulur.
- Content-addressed full cache ve canonical run writer sonraki fazlarda uygulanır.

Bu taslak Faz 2 structure-preparation sözleşmesiyle birlikte normative implementation seviyesine yükseltilecektir.

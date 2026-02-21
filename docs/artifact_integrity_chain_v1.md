# Artifact Integrity Chain v1

- Generated: 2026-02-21T23:13:59Z
- Total artifacts: 14
- Found: 14
- Missing: 0

---

## SHA-256 Hashes

| # | Artifact | SHA-256 | Size | Status |
|---|----------|---------|------|--------|
| 1 | `data/validation/pre_registered_config.json` | `2fae95d44b5532ee...` | 1,904 | found |
| 2 | `data/validation/known_cryptic_pockets.json` | `cabfd92396db89c9...` | 8,002 | found |
| 3 | `data/benchmark/fpocket_benchmark_v3.json` | `2e01e5d0acc66491...` | 162,539 | found |
| 4 | `data/validation/md_validation_1g66.json` | `8ca6674ea757b48b...` | 31,253 | found |
| 5 | `data/validation/false_positive_results.json` | `66161aed3a03727a...` | 560,096 | found |
| 6 | `data/validation/validation_results.json` | `51f9639e5e846bb8...` | 21,941 | found |
| 7 | `data/validation/fpocket_known20_direct_eval.json` | `018a0523f50a23f9...` | 13,188 | found |
| 8 | `data/validation/fpocket_known20_pairing.json` | `3bd81431fce288df...` | 6,759 | found |
| 9 | `data/validation/sensitivity_sweeps_v1.json` | `a8558a1b055343a4...` | 3,711 | found |
| 10 | `docs/phase5_5_gate_decision.md` | `606ef19d2c2aeaa6...` | 1,200 | found |
| 11 | `docs/recovery_v2_regression_guard_report.md` | `708884d36a3d7609...` | 1,167 | found |
| 12 | `docs/scientific_evidence_report_v1.md` | `c5e7cc5b577e811c...` | 5,981 | found |
| 13 | `docs/scientific_validation_plan_v1.md` | `afb40056dde0780f...` | 17,885 | found |
| 14 | `docs/sensitivity_sweeps_v1_report.md` | `7dff1e12b4485061...` | 1,876 | found |

---

## Verification

To verify artifact integrity, run:

```bash
python scripts/generate_artifact_hash_manifest.py
```

Then compare the output `data/validation/artifact_hash_manifest_v1.json` against this document. Any SHA-256 mismatch indicates the artifact was modified after the manifest was generated.

## Full Hashes

```
2fae95d44b5532ee7d186cc217dc93dacf6f40fccf5a33693324f20ff737219c  data/validation/pre_registered_config.json
cabfd92396db89c91c03527dd4ba52274e3a3a33f1790f37f8827d1a4a9d4487  data/validation/known_cryptic_pockets.json
2e01e5d0acc664918d586132b9fd6e9173a7f96f28235e7151181b0760e79b84  data/benchmark/fpocket_benchmark_v3.json
8ca6674ea757b48b46b467f3f46196c709e2f92abf17e935711ea6551d0797aa  data/validation/md_validation_1g66.json
66161aed3a03727ababd2b17cb26bc09d529f47964d4594df1d79f9439e4664a  data/validation/false_positive_results.json
51f9639e5e846bb8c3c51bc6801ea12e6f3f3526bf43c0677272c9696482642c  data/validation/validation_results.json
018a0523f50a23f972127a2670950749f39a638d0b916a8e85e860dc9cf66d21  data/validation/fpocket_known20_direct_eval.json
3bd81431fce288dfd4ccf6eda84331e46c0337acdb719cc4cdc15b3c3de3f1d9  data/validation/fpocket_known20_pairing.json
a8558a1b055343a4bbc26724471e064aefcb2e42b5f3161e8074e852605bc534  data/validation/sensitivity_sweeps_v1.json
606ef19d2c2aeaa6377065e3d95f1322f6deca266065ac4691daf7df752d5e08  docs/phase5_5_gate_decision.md
708884d36a3d7609b63fe984e9ed0ce04cdcc98b4ce11eeb827216c79576e324  docs/recovery_v2_regression_guard_report.md
c5e7cc5b577e811cdf0422cb4d5d4d999f70934915d92aadf06d2895eafac173  docs/scientific_evidence_report_v1.md
afb40056dde0780f7269e42bf4faca446343b19b57f95731ec422d6bd29a7243  docs/scientific_validation_plan_v1.md
7dff1e12b4485061d51926f8df416ac28c7f50a54975b4930806c83f66290150  docs/sensitivity_sweeps_v1_report.md
```

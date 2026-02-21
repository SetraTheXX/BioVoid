# SoT Alignment Guard Report

- Generated: 2026-02-21T23:54:17Z
- Status: **PASS**
- SoT overlap threshold: `0.25`
- Files scanned: 113
- Violations: 0

---

## SoT Snapshot

| Parameter | Value |
|-----------|-------|
| `min_recall` | `0.3` |
| `min_fpocket_overlap` | `0.25` |
| `max_false_positive_rate` | `0.6` |
| `min_md_validated_proteins` | `1` |

---

## Result

No SoT drift violations found. All active docs and scripts are aligned with `pre_registered_config.json`.

---

## Guard Rules

1. Active files must not claim `overlap >= 0.40` as current SoT.
2. Historical mentions are allowed if marked with: `legacy`, `formerly`, `eski`.
3. Archive files (`docs/archive/**`) are excluded from scanning.
4. FPR threshold sweep grids containing `0.40` are whitelisted (not overlap).

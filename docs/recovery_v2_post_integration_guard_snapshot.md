# Recovery v2 Post-Integration Guard Snapshot (Codex-C)

- Generated at (UTC): 2026-02-17T20:03:52Z
- Branch: `ws-c-guard-after-ab-v1`
- Base branch: `recovery-v2-integration`
- Base commit: `7563f26`
- Integration method for A/B refs: merge (`Already up to date`)

## Zorunlu Snapshot Maddeleri

1. overall guard status: **PASS**
2. drift lock durumu: **PASS** (`tolerance=8.0`, `top_n=20`, `druggable=true`)
3. SoT decision uyumu (`docs/phase5_5_gate_decision.md`): **PASS**
4. acik riskler:
   - WS-C regression riski: tespit edilmedi.
   - Sistem riski: recall ve overlap gate FAIL oldugu icin Faz 6 halen bloklu.

## PASS/FAIL Table

| Check | Status | Evidence |
| --- | --- | --- |
| FPR Guard | PASS | conservative_fpr=0.1311 <= 0.60 |
| MD Guard | PASS | md_validated_count=1, status=VALIDATION_SUCCESS |
| Drift Lock | PASS | tolerance=8.0, top_n=20, druggable=true |
| Alignment | PASS | SoT decision+metric alignment PASS |
| Overall WS-C | PASS | `data/validation/recovery_v2_regression_guard.json` |

## Blocker List

1. WS-C blocker: yok.
2. Sistem blocker: var (`Recall FAIL`, `fpocket overlap FAIL`).

## CP-A Patch Sonrasi Tekrar Kosulacak Checklist

1. `python .\BioVoid\scripts\run_recovery_v2_regression_guard.py`
2. `docs/recovery_v2_regression_guard_report.md` overall status PASS mi?
3. Drift lock (`8.0/20/true`) korunuyor mu?
4. SoT decision alignment (`reported == expected`) PASS mi?
5. `docs/recovery_v2_drift_check_report.md` ve `docs/recovery_v2_reports_alignment.md` icinde yeni mismatch var mi?
6. Merge/cherry-pick oncesi gate-metric mismatch olmadigini dogrula.

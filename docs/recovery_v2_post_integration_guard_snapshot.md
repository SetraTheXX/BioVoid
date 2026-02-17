# Recovery v2 Post-Integration Guard Snapshot (Codex-C)

- Generated at (UTC): 2026-02-17T17:25:58Z
- Branch: `ws-c-guard-loop`
- Base reference: `recovery-v2-integration`
- Scope: WS-C post-integration verification (guard + drift + alignment)

## PASS/FAIL Table

| Check | Status | Detail |
| --- | --- | --- |
| Overall guard status | PASS | `data/validation/recovery_v2_regression_guard.json` |
| FPR guard | PASS | conservative_fpr=0.1311 <= 0.60 |
| MD guard | PASS | md_validated_count=1, status=VALIDATION_SUCCESS |
| Drift lock | PASS | tolerance=8.0, top_n=20, druggable=true |
| Report consistency guard | PASS | decision/rows/metrics/freshness all aligned |
| SoT decision alignment | PASS | reported FAIL == expected FAIL |
| SoT metric alignment | PASS | recall/overlap/FPR/MD all matched |

## Mandatory Snapshot Statements

1. Overall guard status: **PASS**
2. Drift lock status: **PASS** (`tolerance=8.0`, `top_n=20`, `druggable=true`)
3. SoT decision alignment with `docs/phase5_5_gate_decision.md`: **PASS**
4. Open risks:
   - WS-C regression risk: none detected in this checkpoint.
   - System-level risk remains: gate still FAIL because recall and overlap are below target.
   - Documentation watch-item: legacy historical numbers may exist in non-decision narrative sections.

## Blockers

1. No WS-C blocker.
2. System-level blocker remains: final gate FAIL (recall + overlap).

## CP-A Patch Sonrasi Re-run Checklist

1. Run `python scripts/run_recovery_v2_regression_guard.py`.
2. Verify `docs/recovery_v2_regression_guard_report.md` shows overall status PASS.
3. Verify drift lock values remain `8.0 / 20 / true`.
4. Verify SoT decision alignment (reported vs expected) stays aligned.
5. Re-check `docs/recovery_v2_drift_check_report.md` and `docs/recovery_v2_reports_alignment.md` for regressions.
6. Confirm no SoT metric mismatch before merge/cherry-pick.

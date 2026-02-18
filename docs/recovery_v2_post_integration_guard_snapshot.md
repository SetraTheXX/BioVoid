# Recovery v2 Post-Integration Guard Snapshot (Codex-C)

- Generated at (UTC): 2026-02-18T16:56:53Z
- Branch: `ws-c/recovery-v3-guard-after-a-final`
- Base: `ws-main/recovery-v3-integration` (current head)
- A commit status: `4a0953a` already present in base (no-op cherry-pick)
- Scope: SG3/SG4 verification only (no Phase 6 decision)

## Signals

- hard_checks_ok: **true**
- readiness_signals_ok: **false**

## PASS/FAIL Table

| Check | Status | Detail |
| --- | --- | --- |
| Overall | PASS | overall_regression_guard_status=PASS |
| FPR | PASS | conservative_fpr=0.1311 <= 0.60 |
| MD | PASS | md_validated_count=1 |
| Drift | PASS | tolerance=8.0, top_n=20, druggable=true |
| Alignment | PASS | report_consistency_guard=PASS |

## Blocker List

1. WS-C blocker: none.
2. System blocker remains: gate still FAIL on recall and overlap thresholds.
3. Intake readiness blocker: `readiness_signals_ok=false` (WS-A recall floor not met).

## Notes

- Faz 6 kararı verilmedi.
- Bu snapshot yalnızca WS-C guard/alignment readiness durumunu raporlar.

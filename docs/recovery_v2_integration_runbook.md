# Recovery v2 Integration Runbook

## Purpose

Standardize how WS-A, WS-B, and WS-C outputs are received, validated, and merged.

## Base Reference

- Integration branch: `recovery-v2-integration`
- Base commit used for current cycle: `2367583`

## Intake Order

1. WS-A report and artifacts
2. WS-B report and artifacts
3. WS-C guard report after A/B changes are present

## Required Artifacts

- WS-A:
  - `data/validation/recovery_v2_domain_motion_eval.json`
  - `docs/recovery_v2_recall_domain_motion_report.md`
- WS-B:
  - `data/benchmark/recovery_v2_overlap_pilot.json`
  - `docs/recovery_v2_overlap_calibration_report.md`
- WS-C:
  - `data/validation/recovery_v2_regression_guard.json`
  - `docs/recovery_v2_regression_guard_report.md`
  - `docs/recovery_v2_drift_check_report.md`
  - `docs/recovery_v2_reports_alignment.md`

## Canonical Lock (Non-Negotiable)

- `tolerance = 8.0`
- `top_n = 20`
- `druggable_only = true`

## Validation Command

```bash
python scripts/recovery_v2_intake_check.py
```

Gate feasibility pre-check (kill-switch):

```bash
python scripts/check_gate_feasibility.py
```

Preflight mode (A/B/C outputs still geliyorken):

```bash
python scripts/recovery_v2_intake_check.py --allow-missing
```

Strict mode (for merge gate):

```bash
python scripts/recovery_v2_intake_check.py --strict
```

Not:

- Intake checker artik WS-B SoT alignment kontrolunu da yapar (`overlap_option1_lock` / `cp_b_prep` / `overlap_calibration_report` sayilari JSON ile uyumlu olmali).
- Bu kontrol gecici olarak pas gecilecekse: `--skip-ws-b-doc-alignment`.

## WS-A Runtime Guard

Use CP-A mini mode with explicit runtime control to avoid multi-hour hangs.

Recommended command:

```bash
python scripts/run_recovery_v2_recall_workstream.py --cp-a-mini-only --cp-a-profile balanced --cp-a-max-minutes 90
```

Fast sanity command:

```bash
python scripts/run_recovery_v2_recall_workstream.py --cp-a-mini-only --cp-a-profile fast --cp-a-max-minutes 45
```

## Decision Rule

Run full SG4 final gate rerun only if all are true:

1. Hard checks pass (canonical locks + WS-C guards).
2. WS-A mini recall signal reaches `>= 0.22`.
3. WS-B pilot overlap signal reaches `>= 0.15`.

If these are not met, continue Recovery v2 iteration and do not trigger full rerun.


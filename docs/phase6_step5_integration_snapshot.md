# Phase 6 Step 5 Integration Snapshot

- Generated at (UTC): 2026-02-21T17:30:40.061396+00:00
- Overall status: **PASS**
- Dry run: `False`

## Command Pack

| Command | Status | Return Code |
| --- | --- | ---: |
| `python scripts/run_phase6_ops_guard_pack.py --strict-recall-floor 0.30 --strict-overlap-floor 0.25` | PASS | 0 |
| `python -m pytest tests/test_phase6_api.py tests/test_phase6_portal.py tests/test_phase6_ops.py tests/test_phase6_guard_pack.py -q` | PASS | 0 |

## Canary Summary

- status: `PASS`
- jobs_requested: `80`
- jobs_submitted: `80`
- jobs_succeeded: `80`
- jobs_failed: `0`
- p95_latency_seconds: `0.001291` (max `2.5`)
- result_download_ok: `80`
- result_download_fail: `0`
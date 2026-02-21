# Phase 6 Step 3 - Web Portal Completion Report

- Date (UTC): 2026-02-21
- Branch: `ws-main/recovery-v3-integration`
- Scope: Phase 6B (submit + monitor + download)

## 1) Delivered Scope

1. Web portal route: `GET /portal`
2. Submit UX integrated with Step 2 API (`POST /jobs`)
3. Monitor UX with live polling (`GET /jobs/{id}`)
4. Client-side cancellation feedback ("Stop Tracking" button)
5. Artifact download route: `GET /jobs/{id}/result`

## 2) Implementation Notes

### Portal UI

1. File: `src/api/portal.py`
2. Features:
   - PDB + idempotency submit form
   - Option inputs (`priority`, `timeout_seconds`, `max_retries`)
   - Job status pill and event timeline
   - Download button enabled only on success
   - Stop tracking feedback (client stops polling, server job continues)
3. Responsive behavior:
   - Mobile/desktop layout via CSS grid + media query

### API Integration

1. File: `src/api/app.py`
2. Added:
   - `GET /portal` (HTML response)
   - `GET /jobs/{job_id}/result` (JSON attachment download)
3. Guard behavior:
   - If job not succeeded, `/result` returns `409 JOB_RESULT_NOT_READY`

## 3) Verification Commands

```bash
python -m py_compile src/api/__init__.py src/api/app.py src/api/models.py src/api/errors.py src/api/orchestrator.py src/api/rate_limit.py src/api/portal.py scripts/run_phase6_api.py
python -m pytest tests/test_phase6_api.py tests/test_phase6_portal.py -q
python -c "import json;from src.api.app import app;from pathlib import Path;Path('docs/phase6_step2_openapi_snapshot.json').write_text(json.dumps(app.openapi(), indent=2))"
```

Observed test result:

- `10 passed in 4.83s`

## 4) Acceptance Matrix (Step 3)

| Requirement | Status | Evidence |
| --- | --- | --- |
| Job submit screen | PASS | `src/api/portal.py` |
| Job status monitoring | PASS | `src/api/portal.py` + `src/api/app.py` |
| Artifact download flow | PASS | `GET /jobs/{id}/result` in `src/api/app.py` |
| E2E submit->done->download | PASS | `tests/test_phase6_portal.py::test_portal_submit_poll_download_path` |
| Invalid pre-download handling | PASS | `tests/test_phase6_portal.py::test_result_endpoint_rejects_when_job_not_ready` |
| Responsive layout baseline | PASS | `src/api/portal.py` CSS media query |
| Polling/cancel feedback | PASS | `src/api/portal.py` stop tracking flow |

## 5) Status

Step 3 (`6B Web Portal`) is `COMPLETED`.

Next phase action:

- Step 4 (`6C Ops/Release Guard`) implementation.

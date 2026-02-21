# BioVoid

BioVoid is a cryptic-pocket discovery and validation project focused on recovery/guarded scientific workflows (Phase 5.5) and operational productization (Phase 6).

## Unified UI (Default)

Project UI is now **single-entry**:

- Start API + Unified Portal:

```bash
python scripts/run_phase6_api.py --host 127.0.0.1 --port 8000
```

- Open:
  - `http://127.0.0.1:8000/portal`

Legacy path compatibility:

- `http://127.0.0.1:8000/` redirects to `/portal`
- `http://127.0.0.1:8000/dashboard` redirects to `/portal`

## Legacy Streamlit Dashboard (Deprecated)

The old Streamlit dashboard (`src/dashboard.py`) is kept only for backward compatibility and legacy analysis snapshots.

- Legacy run command:

```bash
streamlit run src/dashboard.py -- --db data/atlas.db
```

- Recommendation: use `/portal` for daily operations.

## Install

```bash
git clone https://github.com/SetraTheXX/BioVoid.git
cd BioVoid
python -m pip install -r requirements.txt
```

## Key Paths

- `src/api/` -> Phase 6 API + unified portal
- `scripts/` -> runners, guards, integration suites
- `data/` -> benchmark and validation artifacts
- `docs/` -> governance, reports, runbooks
- `memory-bank/` -> progress and planning memory

## Validation Commands

```bash
python -m pytest tests/test_phase6_api.py tests/test_phase6_portal.py tests/test_phase6_ops.py tests/test_phase6_guard_pack.py tests/test_phase6_step5_suite.py -q
python -m pytest tests/test_dashboard.py -q
```

## License

MIT (see `LICENSE`).

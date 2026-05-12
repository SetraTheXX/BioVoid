# BioVoid

BioVoid is a local research prototype for analyzing protein structures with
normal mode analysis, geometry-based cavity detection, scoring heuristics, and a
small FastAPI/React interface.

This repository contains source code only. It does not include local databases,
trained model files, raw PDB downloads, generated reports, or benchmark
artifacts.

> BioVoid is not a clinical, diagnostic, or validated drug-development system.
> Outputs should be treated as computational research signals that require
> independent scientific review.

## What Is Included

- Python analysis pipeline for fetching structures, generating NMA frames,
  finding candidate cavities, scoring results, and saving JSON reports.
- FastAPI backend with job submission, status, result download, Atlas queries,
  and health/readiness endpoints.
- React/Vite frontend for local dashboard, analysis submission, Atlas browsing,
  and system status.
- SQLite Atlas schema and helper APIs. The actual local `data/atlas.db` file is
  intentionally excluded from git.
- Tests for the core pipeline, API, database layer, docking wrapper, and portal
  flows.

## Repository Hygiene

The following are intentionally ignored and should not be committed:

- `data/`
- `artifacts/`
- `memory-bank/`
- SQLite databases such as `*.db`
- model files such as `*.pkl` and `*.joblib`
- raw PDB files and generated reports
- `frontend/node_modules/`
- `frontend/dist/`

If you need to share generated data, use a separate release artifact or an
external storage location rather than committing it to the repository.

## Requirements

- Python 3.10+ (tested locally with Python 3.13)
- Node.js and npm for the React frontend
- Optional: AutoDock Vina/fpocket tooling for docking or external comparisons

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Install frontend dependencies:

```bash
cd frontend
npm install
```

## Run Locally

Start the API:

```bash
python scripts/run_phase6_api.py --host 127.0.0.1 --port 8000
```

Open the backend-served portal:

```text
http://127.0.0.1:8000/portal
```

For the React frontend during development:

```bash
cd frontend
npm run dev
```

The Vite dev server proxies API requests to `http://127.0.0.1:8000`.

## CLI Examples

Analyze one structure:

```bash
python -m src.cli analyze 1CBS --n-frames 50 --profile default
```

Run the direct pipeline:

```bash
python main.py --pdb-id 1CBS --n-frames 50 --profile default
```

Show project info:

```bash
python -m src.cli info
```

## Tests

Run the Python suite:

```bash
python -m pytest tests/ -q
```

Build the frontend:

```bash
cd frontend
npm run build
```

The frontend currently bundles Plotly, so Vite may warn about a large JavaScript
chunk. That warning is expected and is not a build failure.

## Notes For Contributors

- Keep generated data out of git.
- Keep public documentation conservative: describe the tool as a research
  prototype and avoid unsupported claims.
- Prefer small, reviewable commits.
- Do not push or force-push release branches without explicit maintainer
  approval.

## License

MIT. See `LICENSE`.

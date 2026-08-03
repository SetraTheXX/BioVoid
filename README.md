# BioVoid

BioVoid is a local computational research prototype for preparing protein
structures, detecting geometry-based pocket candidates, and inspecting
versioned heuristic measurements through a FastAPI/React application.

This repository contains source code only. It does not include local databases,
trained model files, raw PDB downloads, generated reports, or benchmark
artifacts.

The `v0.1.0` release is a public source release for local experimentation. It
does not represent scientific validation, a benchmark result, or a claim that
motion-aware analysis improves pocket localization.

> BioVoid is not a clinical, diagnostic, validated binding-prediction, or
> drug-development system. Its outputs are unvalidated pocket candidates that
> require independent scientific review.

## What Is Included

- Deterministic full-heavy-atom structure preparation with hashes and run
  manifests.
- A canonical static pocket detector and versioned heuristic product ranking.
- An experimental, quality-gated NMA ensemble that cannot alter canonical
  output unless a future sealed benchmark satisfies the integration gate.
- FastAPI backend with job submission, status, result download, Atlas queries,
  and health/readiness endpoints.
- React/Vite frontend for local dashboard, analysis submission, Atlas browsing,
  and system status.
- SQLite Atlas schema and helper APIs. The actual local Atlas database under
  `data/runtime/` is intentionally excluded from git.
- Tests for scientific invariants, the pipeline, API, Atlas persistence,
  docking wrapper, and React flows.

## Repository Hygiene

The following are intentionally ignored and should not be committed:

- `data/`
- `artifacts/`
- `memory-bank/`
- `local-private/` and `research-local/`
- SQLite databases such as `*.db`
- model files such as `*.pkl`, `*.joblib`, and `*.onnx`
- raw PDB/mmCIF files, archives, and generated reports
- `frontend/node_modules/`
- `frontend/dist/`

If you need to share generated data, use a separate release artifact or an
external storage location rather than committing it to the repository.

PDB and AlphaFold inputs are fetched or supplied locally at runtime. They are
not distributed by this repository, and results produced from them remain
local unless an independently documented release artifact is prepared.

## Requirements

- Python 3.12 or 3.13 (the supported release range is `>=3.12,<3.14`)
- Node.js and npm for the React frontend
- Optional: AutoDock Vina/fpocket tooling for docking or external comparisons

Install Python dependencies:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

Install frontend dependencies:

```powershell
cd frontend
npm ci
```

## Run Locally

Build the canonical React UI, then start the API:

```powershell
cd frontend
npm run build
cd ..
python scripts/run_phase6_api.py --host 127.0.0.1 --port 8000
```

Open the application:

```text
http://127.0.0.1:8000/
```

`/portal` is retained only as a compatibility redirect to the canonical React
interface at `/`. For React development:

```powershell
cd frontend
npm run dev
```

The Vite dev server proxies API requests to `http://127.0.0.1:8000`.

For a local Docker run, use Compose:

```powershell
docker compose up --build
```

Compose publishes the API only on `127.0.0.1`. A standalone image remains
loopback-only by default; enabling `--allow-remote` is an explicit operator
choice and requires an authenticated network boundary.

## CLI Examples

Analyze one structure:

```powershell
python -m src.cli analyze 1CBS --profile default
```

Run the direct pipeline:

```powershell
python main.py --pdb-id 1CBS --profile default
```

Show project info:

```powershell
python -m src.cli info
```

## Tests

Run the Python suite:

```powershell
python -m pytest tests/ -q
```

Run opt-in scientific invariants and build the frontend:

```powershell
python -m pytest tests/ -m scientific -q
cd frontend
npm run lint
npm run test
npm run build
npm run test:e2e
```

Plotly is lazy-loaded as an optional visualization chunk. Vite may still warn
about that chunk's size; it is not part of the initial application bundle.

Run the public hygiene check before preparing a release:

```powershell
python scripts/check_public_hygiene.py --history
```

The public release checklist and scope are recorded in
[`docs/releases/v0.1.0.md`](docs/releases/v0.1.0.md).

## Scientific Status

BioVoid is a local computational research prototype. The canonical path
prepares a full-atom structure and ranks geometry-based pocket candidates with
versioned heuristic measurements. The NMA/motion path is experimental and is
kept separate from the canonical static ranking.

The repository does not claim discovery, binding prediction, drug utility,
clinical relevance, or superiority over other tools. Local benchmark records,
phase reports, evaluator-only inputs, databases, structures, and generated
outputs are deliberately excluded from the public source tree. Any future
scientific result must be released with a frozen protocol, case-level evidence,
checksums, limitations, and independent rerun instructions.

Public method contracts are under `docs/specs/`. Personal planning, internal
audits, research execution reports, and evaluator-only inputs stay local.

## Scientific Boundaries

- `heuristic_shortlist` and quality tiers are ranking aids, not validated
  druggability, confidence, or success probabilities.
- NMA frames are conformational samples, not an MD time series.
- Motion-aware output is experimental and currently not eligible to change the
  canonical static result.
- Preserved metals and cofactors are recorded as context but are not yet part of
  detector geometry.
- Pocket volume and depth are geometric proxies whose real-protein reference
  validation remains ongoing.

## Notes For Contributors

- Keep generated data out of git.
- Keep public documentation conservative: describe the tool as a research
  prototype and avoid unsupported claims.
- Prefer small, reviewable commits.
- Do not push or force-push release branches without explicit maintainer
  approval.

## License

MIT. See `LICENSE`.

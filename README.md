# BioVoid — Cryptic Pocket Discovery

BioVoid is a computational pipeline that discovers hidden drug-binding pockets (cryptic pockets) in proteins using NMA dynamics, Voronoi geometry, and AI-powered scoring.

## Quick Start

```bash
git clone https://github.com/SetraTheXX/BioVoid.git
cd BioVoid
pip install -r requirements.txt
```

## Usage

### Web Interface (Recommended)

```bash
python scripts/run_phase6_api.py --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/portal — unified dashboard with analysis, 3D viewer, atlas, and reports.

### CLI

```bash
# Analyze a single protein
python -m src.cli analyze 1CBS --n-frames 50 --profile enzyme

# Batch analyze
python -m src.cli batch 1CBS,1AKE,1TUP --n-frames 20

# Run benchmark
python -m src.cli benchmark --tolerance 8.0

# Cache management
python -m src.cli cache stats

# Project info
python -m src.cli info
```

### Pipeline (Direct)

```bash
python main.py --pdb-id 1CBS --n-frames 50 --profile default --dock
```

## Architecture

```
src/
├── api/              FastAPI backend + unified portal
│   ├── app.py        API endpoints (jobs, atlas, protein, artifacts)
│   ├── orchestrator.py  Job queue with real pipeline runner
│   └── portal.py     Unified web dashboard
├── ml/               Machine learning module
│   ├── features.py   17-feature extraction
│   ├── dataset.py    Labeled datasets with leakage guard
│   ├── classifier.py RF/GB/Logistic + calibration
│   └── evaluation.py PR-AUC, ECE, recall@k, ablation
├── docking/          AutoDock Vina integration
├── cavities.py       Cavity detection & merging
├── dynamics.py       NMA simulation engine
├── geometry.py       Voronoi void scanning
├── scoring.py        Druggability scoring v2 (confidence, sphericity)
├── multiframe.py     Consensus + persistence tracking
├── comparison.py     Cross-protein pocket similarity
├── benchmark.py      Structured benchmark suite
├── cache.py          Analysis result caching
├── profiling.py      Pipeline performance profiling
├── config.py         Central configuration
├── cli.py            Modern CLI interface
├── database.py       SQLite atlas database
├── fetcher.py        PDB + AlphaFold DB fetcher
└── visualizer.py     3D visualization & PyMOL scripts
```

## Scientific Metrics

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Recall | 0.3500 (7/20) | >= 0.30 | PASS |
| fpocket Overlap | 0.2597 | >= 0.25 | PASS |
| Conservative FPR | 0.1311 | <= 0.60 | PASS |
| MD Validated | 1 protein | >= 1 | PASS |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /portal | Unified web interface |
| GET | /health | Health check |
| GET | /jobs | List all jobs |
| POST | /jobs | Submit analysis |
| POST | /jobs/batch | Batch submit |
| POST | /jobs/{id}/cancel | Cancel job |
| GET | /jobs/{id} | Job status |
| GET | /jobs/{id}/result | Download result |
| GET | /jobs/{id}/visualization | Plotly chart data |
| WS | /ws/jobs/{id} | Real-time progress |
| GET | /atlas/overview | Atlas statistics |
| GET | /atlas/pockets | Search pockets |
| GET | /protein/{id}/structure | PDB file content |
| GET | /protein/{id}/pockets | Pocket positions |
| GET | /artifacts | Visualization gallery |

## Tests

```bash
python -m pytest tests/ -q
```

## License

MIT (see `LICENSE`).

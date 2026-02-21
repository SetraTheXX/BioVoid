# fpocket Runtime Setup - Windows

## Status: RESOLVED (Docker backend)

Native `fpocket` binary is still not available directly on this Windows host,
but the project now runs fpocket with Docker backend and closes G5 coverage.

## Active Runtime Path

1. Build image once:

```powershell
docker build -t biovoid-fpocket:latest docker/fpocket
```

2. Run direct known-20 fpocket eval with Docker backend:

```powershell
python scripts/run_fpocket_known20_direct_eval.py --fpocket-backend docker --tolerance 8.0 --min-volume 200
```

3. Rebuild pairing and stats pack:

```powershell
python scripts/build_fpocket_known20_pairing.py
python scripts/run_scientific_stats_pack.py --n-resamples 10000 --seed 42
```

## Notes

1. `docker/fpocket/Dockerfile` builds fpocket from upstream source (`Discngine/fpocket`) during image build.
2. Vendored fpocket source/zips are intentionally not kept in repo to avoid large payload drift.
3. Canonical evaluation lock remains:
   - tolerance: `8.0 A`
   - top_n: `20`
   - druggable_only: `true`
   - min_volume: `200 A^3`

## Troubleshooting

1. If Docker is not running, `run_fpocket_known20_direct_eval.py` will return unavailable status for new cases.
2. If image is missing, rebuild with:

```powershell
docker build -t biovoid-fpocket:latest docker/fpocket
```


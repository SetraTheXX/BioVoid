# BioVoid Atlas v1 Contract

Status: recovery contract

## Purpose

Atlas v1 stores immutable analysis runs with enough provenance to distinguish
input, preparation, detector, scoring, motion, code, and environment identity.

## Required tables

- `structures`
- `prepared_structures`
- `analysis_runs`
- `pockets`
- `pocket_observations`
- `models`
- `benchmark_evaluations`

## Invariants

- `run_id` is immutable and cannot be overwritten.
- Pockets are unique by `(run_id, pocket_local_id)`.
- A second run cannot inherit pockets from an earlier run.
- Distinct preparation policies coexist even when prepared coordinates are
  byte-identical.
- `detected_total` and `persisted_total` are separate and must agree before a
  run is completed.
- Structure, preparation, run, pockets, and observations are written in one
  transaction.
- Persistence failures are included in the job report.
- Static and experimental motion observations use separate layers.
- Legacy Atlas remains isolated and read-only. Atlas v1 never migrates or
  overwrites it implicitly.

Current schema: `atlas-run-scoped-v1`.

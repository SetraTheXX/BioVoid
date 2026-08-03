# BioVoid Cache Contract v1

Status: recovery contract

## Cached layer

The cache stores only a completed, unscored analysis core. Reports,
visualizations, Atlas persistence, and run IDs are never reused.

## Identity

Each key includes:

- Raw input hash
- Prepared structure hash
- Preparation config hash
- Static detector config hash
- Motion config hash
- Model hash or explicit disabled identity
- Executable code identity, including dirty local Python sources
- Runtime and dependency identity
- Cache schema version
- Benchmark cache policy

## Safety rules

- Exact identity match is mandatory.
- Payload integrity is verified before reuse.
- Incomplete, expired, malformed, or tampered entries are misses.
- Writes use a temporary file and atomic replacement.
- A failed experimental motion layer is not cached as a valid fallback.
- Cache hits still create a new run and execute scoring, reporting,
  visualization, and Atlas persistence.
- Sealed benchmark cache reuse requires an explicit read-only policy. Normal
  pipeline runs use `not_benchmark`.

Current schema: `analysis-core-cache-v2`.

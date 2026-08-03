# Changelog

This file records public source-release changes only. Private research logs,
phase reports, benchmark records, and planning documents remain outside the
repository.

## [Unreleased]

- Tightened the source-only boundary for local data, models, structures,
  generated outputs, archives, and private documents.
- Added fail-closed public-hygiene checks for the working tree and reachable
  history.
- Kept the canonical React interface and the local API on a bounded,
  conservative runtime path.
- Added citation metadata and clarified the research-prototype claim boundary.

## [0.1.0] - 2026-08-01

### Added

- Local FastAPI and React application for controlled protein pocket analysis.
- Full-heavy-atom structure preparation with hashes and run manifests.
- Canonical static geometry path with versioned heuristic measurements.
- Experimental, quality-gated NMA ensemble reporting.
- Atlas schema and provenance-aware local persistence helpers.
- Offline Python tests, opt-in scientific invariant tests, frontend tests, and
  browser smoke coverage.

### Public Scope

- No databases, raw structures, trained models, generated outputs, benchmark
  artifacts, caches, or private planning files are distributed.
- Motion-aware output remains experimental and cannot change the canonical
  static result.
- Outputs are unvalidated research candidates and are not clinical,
  diagnostic, binding, or drug-development conclusions.

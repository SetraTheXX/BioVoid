# BioVoid Motion Ensemble v1

> **Status:** EXPERIMENTAL RECOVERY V1
> **Specification ID:** `biovoid-motion-ensemble-v1`
> **Canonical effect:** None

This document defines BioVoid's experimental normal-mode ensemble layer. It
does not establish physical trajectories, molecular-dynamics time scales,
validated cryptic pockets, or improved localization performance.

## Input And Isolation

- Motion sampling starts from the prepared full-atom static detector input.
- The prepared static result remains the canonical result.
- Motion output is run-scoped and cannot replace or rerank static pockets.
- Samples from previous runs are never discovered with a shared-directory
  glob.
- CA-only structures are diagnostic intermediates and are not pocket detector
  inputs.

## Sampling Semantics

- Total requested samples equal `mode_count * samples_per_mode`.
- Each sample records mode ID, eigenvalue, direction, phase label, amplitude,
  and amplitude fraction.
- Phase labels describe displacement sign; they are not timestamps.
- Zero-displacement duplicates of the reference structure are excluded.
- Positive and negative displacement directions are sampled independently.
- Sample IDs include mode, direction, amplitude, and maximum-amplitude tokens.
- AlphaFold amplitude sweeps pass each configured amplitude to the NMA engine.

## Reconstruction Candidates

Recovery v1 compares these experimental coordinate-transfer methods:

- `residue_rigid_translation_v1`
- `backbone_blended_translation_v1`

The selected method is the candidate with the strongest quality status,
followed by lower bond deviation, fewer introduced clashes, and lower maximum
atom displacement. Selection is recorded per sample. Neither method is
assumed to produce an energy-minimized or physically equilibrated structure.

## Frame Quality

Every reconstructed sample has one status:

- `ACCEPTED`
- `ACCEPTED_WITH_WARNINGS`
- `REJECTED`

Only `ACCEPTED` samples are persisted as detector inputs and included in
motion evidence. The quality record contains:

- atom count and identity preservation;
- residue mapping completeness;
- CA target RMSD and maximum error;
- backbone bond RMS and maximum deviation;
- chain-break count;
- total and newly introduced steric clashes;
- maximum atom displacement;
- reconstruction method and version;
- whether minimization was applied;
- quality-policy version;
- warning and rejection reasons.

Recovery v1 uses explicit conservative thresholds from
`FrameQualityPolicy`. These thresholds are engineering quality gates, not
evidence that an accepted sample is a physically populated conformation.

## Pocket Evidence

- The full-atom static detector runs independently on each accepted sample.
- Matching uses pocket-center distance and residue-set overlap.
- One sample can support a cluster at most once.
- `ensemble_support` uses accepted samples as its denominator.
- `mode_support` is the fraction of requested modes supporting a pocket.
- `mode_diversity` is the inverse-Simpson effective mode count normalized by
  requested modes, so concentration in one heavily sampled mode is visible.
- Bidirectional support requires both displacement directions within at least
  one mode.
- Static linkage is reported with the static pocket ID and center distance.
- An unmatched cluster is an experimental motion-emergent candidate, not a
  confirmed cryptic pocket.
- Ranking prioritizes mode support before sample support to reduce inflation
  from many similar samples of one mode.

## Resource Policy

- `safe-16gb` permits one heavy NMA job at a time.
- It allows at most 12 modes, 8 samples per mode, and 64 total samples.
- Dense and sparse Hessian memory are estimated before execution.
- Sparse Hessian construction and a partial eigensolver are selected for
  larger CA sets.
- CA diagnostic PDB files are not persisted by the motion pipeline.
- A request that exceeds sampling or memory limits is rejected before NMA.

## Required Provenance

The run-scoped motion manifest records:

- sampling, reconstruction, and quality policy versions;
- requested configuration and solver;
- estimated memory;
- every sample's displacement metadata;
- all reconstruction candidate outcomes;
- selected frame quality;
- accepted sample IDs and quality counts;
- the `accepted_only` evidence policy;
- `canonical_ranking_affected: false`;
- a deterministic manifest SHA-256.

Heavy real-protein validation and comparative benchmark evidence are separate
opt-in work. This specification alone does not establish scientific benefit.

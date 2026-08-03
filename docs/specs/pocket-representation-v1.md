# BioVoid Pocket Representation v1

> **Status:** RECOVERY V1
> **Specification ID:** `biovoid-pocket-representation-v1`
> **Scope:** Prepared full-heavy-atom static structures

This document defines what the recovery-v1 static detector measures. It does
not claim that a detected pocket binds a ligand, is druggable, or is a
biologically validated cryptic pocket.

## Atom Policy

- Detector input is the `prepared_detector.pdb` emitted by structure
  preparation.
- Only protein heavy atoms enter geometry.
- Hydrogen and deuterium are excluded.
- Water, ligands, ions, and metals do not enter detector geometry.
- Preserved metal/cofactor context remains separate and cannot silently alter
  detector coordinates.
- Supported protein elements are C, N, O, F, P, S, Cl, Se, Br, and I.
- Missing radius policy is a hard error.
- Radius policy ID is `protein-heavy-bondi-v1`.
- Primary radius provenance is Bondi 1964,
  DOI `10.1021/j100785a001`; extensions and exclusions are reported.

## Surface And Candidates

- Voronoi vertices are candidate empty-space centers, not a molecular surface.
- Protein-wide convex hull membership is not a canonical acceptance rule.
- Surface clearance is the minimum atom-center distance minus that atom's van
  der Waals radius.
- Directional enclosure casts a fixed Fibonacci sphere of rays and measures
  the fraction intersecting a van der Waals atom sphere within the configured
  ray length.
- Candidate thresholds and ray sampling are part of the detector config hash.

## Pocket Grouping And Volume

- Nearby accepted candidates are clustered with a versioned distance
  threshold.
- Each candidate contributes an empty-space sphere whose radius is its van der
  Waals surface clearance.
- Duplicate spheres are removed before measurement.
- Pocket volume is the union of these spheres, never the sum of their
  individual volumes.
- Recovery-v1 canonical volume method is deterministic cell-center voxel union
  (`voxel_union_v1`).
- Grid spacing and coarse/fine convergence delta are stored with each pocket.
- Deterministic Sobol union (`sobol_union_v1`) is an independent comparison
  method, not the canonical result.
- Single-sphere and two-sphere cases are checked against analytic references.

## Raw Pocket Record

Each static pocket contains:

- stable local `pocket_id`;
- center and center method;
- volume, volume method, resolution, and convergence delta;
- voxel surface area;
- directional enclosure and open fraction;
- explicitly named depth proxy and method;
- geometric and clearance radii;
- contributing centers and clearance radii;
- nearby residue identifiers;
- raw hydrophobic residue ratio and nearby polar atom count;
- prepared structure SHA-256;
- detector version and config SHA-256;
- atom/radius policy version;
- warnings and validity.

The depth value is a named recovery proxy, not a solvent-excluded-surface
geodesic depth. Scoring may consume raw measurements, but it cannot change
their values.

## Interoperability

BioVoid static, fpocket, and P2Rank predictions are normalized to
`pocket-evaluator-input-v1`. Tool absence is recorded as `unavailable`; missing
baseline output is never represented as zero pockets or a successful run.

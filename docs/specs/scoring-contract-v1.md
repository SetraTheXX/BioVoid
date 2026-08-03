# BioVoid Scoring Contract v1

Status: recovery contract

## Scope

BioScore is a versioned heuristic ranking function. It is not a probability,
confidence interval, clinical claim, ligand property, or validated prediction.

## Required separation

- Detector measurements are extracted once and stored under
  `scoring_measurements`.
- Profile changes may only recompute ranking fields.
- Reranking must not mutate raw or normalized measurements.
- Every result records the scoring contract, profile manifest, profile hash,
  component values, and score semantics.
- Static and motion contributions are separate. In recovery v1, motion does not
  change the canonical score.
- Measurement quality is an engineering data-quality tier, not statistical
  confidence.
- Pocket fit is a geometry heuristic and must not be labeled Lipinski
  drug-likeness.

## Version identities

- Contract: `heuristic-pocket-ranking-v1`
- Measurements: `pocket-scoring-measurements-v1`
- Profiles: `scoring-profiles-v1`

Changing a formula, threshold, required measurement, or profile weight requires
a version change.

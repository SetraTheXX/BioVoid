# Target-family detection-vs-ranking diagnostic v1

Status: **frozen diagnostic contract; no scientific claim.**

This contract defines the next read-only analysis of the bounded RI-3
CryptoBench static pilot. It is a diagnosis of the current detector artifact,
not a new benchmark, validation, superiority comparison, discovery scan, NMA
run, or ML experiment.

## Immediate scope

The diagnostic may read the sealed local RI-3 static and evaluator artifacts,
but it must not:

- download coordinates or rerun the detector;
- change thresholds, features, ranking formulas, or candidate filtering;
- open a new second-family source screen;
- run fpocket, P2Rank, NMA/motion, docking, or ML;
- use evaluator labels to modify detector-owned data.

The resource-blocked `1D7K` rows remain visible as resource status. They are not
silently removed from the audit and are not counted as detector successes.

## Artifact boundary established by the RI-3 audit

The current RI-3 pilot stores two different quantities:

- `candidate_count`: the number of accepted raw Voronoi empty-space candidates
  before clustering and final pocket construction;
- `pocket_count` and `detector_record.pockets`: the final merged pockets that
  passed the static volume policy and were sorted by the canonical volume
  ranking.

The nine completed structures store every final pocket returned by
`canonical-static-v1`: the stored list length equals `pocket_count`, and ranks
are contiguous from 1 through the final rank. The evaluator's DCC/DCA arrays
have the same length for all 12 aligned case rows. Therefore the current
artifact supports a **final-pocket-list** localization ceiling and ranking
recall; it is not Top-10-truncated.

The raw Voronoi candidate universe is not serialized as a separate list. A
case whose target is absent from the final pocket list must therefore be
reported as a **final detector-pipeline miss**. This artifact alone cannot say
whether the cause was raw candidate generation, clustering, volume filtering,
or another upstream geometry stage. It must not be called a proven raw
Voronoi-detector miss.

## Required case-level analysis

For every accepted evaluator row, retain a table with:

- structure and opaque case identifiers;
- evaluator/alignment status;
- raw `candidate_count` and final `pocket_count`;
- best DCC and DCA values and their final-list ranks;
- Top-1, Top-3, Top-5 and Top-10 DCC/DCA hit flags;
- whether any final pocket is within the frozen 4 Å tolerance;
- descriptive raw measurements of the best site-like pocket and the top-ranked
  pocket (volume, enclosure, depth proxy, clearance, hydrophobic ratio);
- one taxonomy status.

The taxonomy is:

- **A — final-list candidate, low rank:** a final pocket localizes the site,
  but the canonical rank is outside the selected Top-k;
- **B — metric disagreement:** DCC and DCA localize differently or one is
  within tolerance while the other is not;
- **C — final detector-pipeline miss:** no final pocket is within the chosen
  tolerance; the raw-stage cause is not identifiable from this artifact;
- **D — resource blocked:** the canonical static run was rejected by the
  declared `safe-16gb` policy (including `1D7K`);
- **E — evaluator/alignment unavailable:** no independent ground-truth row is
  available.

Statuses must be reported separately when more than one applies; an
unavailable or blocked row is never converted into a negative localization.

## Aggregate metrics

Report both of these, with D/E denominators shown explicitly:

1. **Final-pocket-list localization ceiling:** the fraction of eligible aligned
   rows with any final pocket inside the frozen DCC or DCA tolerance. This is
   not a full raw-candidate-universe ceiling.
2. **Canonical ranking recall:** Top-1/3/5/10 DCC and DCA recall within the
   stored final pocket list.

The diagnostic must also report how many rows are C rather than hiding them in
the ranking denominator. No single percentage may be described as detector
accuracy or discovery probability.

## Decision gate

After the read-only report:

- If most eligible rows have a final-list candidate but canonical Top-k recall
  is low, open a separate, pre-registered ranking-policy study. Use only the
  existing locked A/B/C interpretable policies on a newly defined development
  cohort; do not select a policy from this evaluator-exposed pilot.
- If many rows are C, close the enclosure-ranking branch for now and design a
  versioned geometry/candidate-generation study that can observe the relevant
  intermediate stages. Do not loosen the `safe-16gb` limit after seeing the
  result.
- If the pattern is mixed, keep the C subset as a detector-pipeline issue and
  study ranking only on the final-list subset.

The second-family source gate V1–V5 remains closed. Reopening it requires a
new versioned source/catalog or cohort contract with early resource metadata
filters; it is not an automatic next step.

## Motion and ML boundary

NMA remains an experimental evidence layer and cannot alter the canonical
static result. Use `ensemble_support`, `mode_support`, `amplitude_support`,
`mode_diversity`, `bidirectional_support`, and `conformational_recurrence` for
future evidence summaries. Do not use `persistence`, `lifetime`, or `flicker`
unless a real time-series/MD contract is later introduced.

ML remains closed until a new cohort has independent labels and a leakage-
audited held-out split. A first model, if eventually justified, is a small
interpretable baseline for localization or recurrence—not a drug-discovery or
binding-success predictor.

## Claim boundary

This contract authorizes only a read-only diagnostic report. It authorizes no
validated prediction, biological discovery, drug-development, clinical, or
superiority claim.

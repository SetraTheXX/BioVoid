# Target-family leakage-audited cohort v1

Status: design contract. This contract is a readiness gate, not a benchmark,
model result, validation, or discovery claim.

## Private input

The evaluator-side cohort is kept in ignored local storage. Each case records
an apo structure, its paired holo structure, an independent label source, an
exact UniProt grouping, a sequence-cluster identifier, and release dates. The
allowed label sources are `holo_ligand_contact_v1` and
`independent_annotation_v1`; BioVoid heuristic scores are explicitly rejected.
Release dates may be calendar dates or RFC3339/ISO timestamps as returned by
RCSB; the detector manifest canonicalizes the temporal cutoff to a date.

The split strategy is `sequence_cluster_temporal_holdout_v1`:

- no UniProt group or sequence cluster may occur in more than one split;
- development and validation apo structures precede the temporal cutoff;
- test apo structures are on or after the cutoff;
- development, validation, and test must all be populated before held-out work
  is considered ready.

The first local gate is bounded to at most ten cases and reports fewer than six
cases as insufficient for a held-out experiment. This is a conservative
readiness rule, not a claim that six cases are scientifically sufficient.

## Detector boundary

`src/target_family_cohort.py` and
`scripts/check_target_family_cohort.py` can emit a detector manifest containing
only apo structure IDs, family IDs, split names, hashes, and static resource
limits. Holo IDs, labels, grouping metadata, and evaluator fields are removed
before detector use. The command performs no network access, coordinate
download, detector run, NMA, or ML training.

## Next decision

The current PF00497 metadata pilot has two cases and therefore remains
`blocked_insufficient_cohort` for held-out/ML work. The next research task is
metadata curation and sequence-cluster review for a larger cohort; only after
that review can a bounded static benchmark be considered. A later ML baseline
must use the redacted manifest plus independent labels and family-aware splits.

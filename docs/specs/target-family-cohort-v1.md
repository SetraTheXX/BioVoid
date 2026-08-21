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
metadata curation and sequence-cluster review for a larger cohort. The local
metadata-only candidate audit currently finds two strict paired UniProt groups
and three under the relaxed 120-residue length policy, but no independent
contact labels have been materialized yet. Sequence clusters are now materialized
only as review-required metadata; only after that review can a bounded
static benchmark be considered. A later ML baseline must use the redacted
manifest plus independent labels and family-aware splits.

## Sequence-cluster materialization boundary

`scripts/materialize_target_family_sequence_clusters.py` is the bounded
metadata curation step. With an explicit `--allow-network` acknowledgement it
requests only RCSB entry and polymer-entity JSON, sequentially, for at most 100
inventory records. It selects the protein entity whose RCSB UniProt metadata
matches the inventory group, stores sequence lengths and SHA-256 digests in the
ignored local report, and never stores raw sequences in the public repository.
Coordinate URLs are rejected by the command boundary.

The current local run materialized all 42 inventory records into eight
sequence components using `global_pairwise_identity_v1` at a 0.90 identity
threshold, with 283 threshold edges. This is a curation diagnostic only:
single-linkage clusters are explicitly marked `review_required`, do not create
independent labels, and are not yet eligible to authorize a detector,
benchmark, ML training, or discovery claim. The next gate remains independent
apo--holo contact-label curation followed by the leakage-audited cohort
contract.

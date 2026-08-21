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

The bounded PF00497 metadata expansion now contains 98 records and nine strict
paired UniProt groups. Six pairs produced exact independent holo-derived contact
labels; three remain explicitly unavailable because ligand selection or sequence
alignment was ambiguous. The private cohort therefore contains six usable cases,
two development, two validation, and two temporal-test cases. The readiness
checker now reports `ready_for_explicit_user_approval`; this is an approval gate,
not a benchmark or ML authorization. The three unavailable cases remain in the
evaluator report and are recorded in the cohort's `excluded_cases` audit trail;
they are not silently relabelled or counted as negatives.

Sequence clusters remain review-required metadata. The next research task is a
review of the three unavailable pairs and an explicit user decision on a bounded
static comparison. A later ML baseline must use the redacted manifest plus
independent labels and family-aware splits.

## Sequence-cluster materialization boundary

`scripts/materialize_target_family_sequence_clusters.py` is the bounded
metadata curation step. With an explicit `--allow-network` acknowledgement it
requests only RCSB entry and polymer-entity JSON, sequentially, for at most 100
inventory records. It selects the protein entity whose RCSB UniProt metadata
matches the inventory group, stores sequence lengths and SHA-256 digests in the
ignored local report, and never stores raw sequences in the public repository.
Coordinate URLs are rejected by the command boundary.

The original local run materialized 42 inventory records into eight sequence
components using `global_pairwise_identity_v1` at a 0.90 identity threshold,
with 283 threshold edges. The bounded PFAM expansion materialized 98 records
into 48 components with 203 threshold edges. Both are curation diagnostics:
single-linkage clusters are explicitly marked `review_required`, do not create
independent labels, and are not eligible to authorize a detector, benchmark, ML
training, or discovery claim. The next gate remains independent contact-label
review followed by the leakage-audited cohort contract.

`scripts/build_target_family_pfam_inventory.py` is a separate bounded
preflight for the exact PF00497 annotation. It requests only the first 100
RCSB entry results (the service reported 126 total), skips entries with
ambiguous multiple PF00497 polymer entities, and produced 98 metadata records
across 42 UniProt groups. The same quality policy found nine strict paired
groups. Its expanded sequence report contains 98 records and 48
review-required components; these candidates are not automatically promoted
into the private labelled cohort or a detector manifest. Six were later
materialized only through the explicit independent contact-label gate; three
ambiguous cases remain excluded with reasons.

## Independent contact-label boundary

`scripts/materialize_target_family_contact_labels.py` is the bounded private
label step. With explicit `--allow-network`, it downloads at most ten apo/holo
mmCIF files under a 1 GB quota, prepares only the apo side for alignment, and
never starts the pocket detector, benchmark, NMA or ML. It accepts ambiguous
ligand/sequence cases only as failed records; it never guesses a label.

`scripts/materialize_target_family_cohort.py` then joins the ignored pilot-pair
metadata, the ignored sequence-cluster report and the evaluator-only report. It
accepts only `completed_ground_truth` cases whose benchmark evaluation records
`score_used: false`, whose ligand component matches the independent holo
metadata, and whose alignment quality is exact.
The private case label contains the transformed holo ligand geometry, digest and
alignment provenance under `holo_ligand_contact_v1`; it never enters a detector
manifest. The materializer performs no network access or coordinate download.

The current private PFAM cohort contains six usable cases. The materializer can
be run with the explicit `--allow-unavailable-labels` flag; this excludes only
evaluator records that fail the independent label contract and records each
reason. With `--split auto_temporal --validation-cutoff 2014-01-01
--temporal-cutoff 2018-01-01`, two cases are development, two validation, and
two test under the pre-registered `temporal_three_way_v1` policy. The readiness
checker reports `ready_for_explicit_user_approval`; the redacted detector
manifest is still apo-only and no computation starts at this gate.

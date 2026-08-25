# Ranking-study source/catalog v1

Status: metadata-only source gate. This document defines a readiness contract;
it is not a detector result, benchmark, validation, model result, or discovery
claim.

## Source boundary

The first independent source candidate is the PocketMiner supplementary
metadata table. BioVoid uses only the curated **novel cryptic pocket set**:
apo (ligand-free) structure, holo (ligand-bound) structure, chain IDs, ligand
provenance, source row, and the source's descriptive motion fields. CryptoSite
rows, rigid-protein negatives, and PocketMiner/GVP model outputs are not
treated as this catalog's independent labels.

The catalog records the source URL, MIT license, retrieval timestamp, source
XLSX SHA-256, bounded RCSB metadata snapshot SHA-256, sequence-cluster report
SHA-256, and allocation SHA-256. Raw structures and raw sequences remain local
and ignored.

## Metadata-only eligibility

Before any coordinate is materialized, every pair must have:

- matching apo/holo chain metadata from the RCSB Data API;
- an independent curated experimental apo--holo label provenance class;
- UniProt identifiers and a review-required global sequence-cluster ID;
- an apo release date for the temporal window;
- an entry-level resource proxy using the unchanged `safe-16gb` atom/model
  boundary;
- no structure, UniProt, or sequence-cluster overlap with RI-3 or historical
  PF00497 diagnostic inputs.

The resource proxy is only a preflight hint. Prepared heavy-atom counts remain
the authoritative detector gate.

## Pre-sealed allocation

The allocation policy is `sequence_cluster_date_window_hash_v1`:

- development: apo release before `2014-01-01`, target 6;
- validation: apo release from `2014-01-01` up to (but excluding) `2018-01-01`,
  target 2;
- temporal test: apo release on or after `2018-01-01`, target 2;
- one sequence cluster may contribute at most one selected case;
- stable hash ordering resolves overflow and ties;
- no ranking result, detector score, evaluator score, or BioVoid heuristic is
  used for selection.

The split IDs are sealed before development coordinates or detector output are
opened. A `PASS` authorizes manifest freezing and a later bounded development
materialization gate; it does not authorize a benchmark, NMA, external
baseline, ML training, or a scientific claim.

The current catalog passed with 26 eligible cases and a sealed 6/2/2
allocation. The redacted manifest and private cohort are frozen. The six
development apo structures passed preparation and `safe-16gb` resource
preflight (1,894,912 raw bytes; 1,287--2,921 selected protein heavy atoms).
This still does not authorize using validation/temporal rows or evaluator
fields.

## Stop rules

Do not raise the atom cap, change temporal cutoffs, reuse RI-3/PF00497 rows,
or select a case because it is difficult/easy for BioVoid. If a future source
is needed, create another versioned catalog contract instead of mutating this
snapshot.

Reproducible local report (ignored):
`local-private/research/ranking-study-source-catalog/pocketminer-v1/`.

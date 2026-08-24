# Target-family metadata resource proxy v1

Status: source-only screening contract. This contract does not authorize a
coordinate download, detector run, benchmark, NMA, docking, or ML training.

## Purpose

Candidate-family inventories should expose likely local resource problems before
BioVoid downloads coordinates. The PFAM metadata builder therefore records these
RCSB entry-level fields when available:

- deposited atom count,
- deposited model count,
- deposited polymer-entity instance count,
- molecular weight in kDa,
- polymer composition.

The screen is tied to the versioned `safe-16gb` profile and its current
`max_static_atoms=5000` limit. It has three statuses:

- `likely_within_static_atom_cap`: one deposited model and no more than 5,000
  deposited atoms;
- `likely_above_static_atom_cap`: one deposited model and more than 5,000
  deposited atoms;
- `review_required`: atom count is unavailable or the entry does not contain
  exactly one deposited model.

## Interpretation boundary

Deposited atom count is an entry-level proxy, not BioVoid's prepared
protein-heavy-atom count. Solvent, ligands, alternate locations, non-protein
components, and preparation policy can change the final count. Available host
memory can also block an entry that appears to fit the atom proxy.

For those reasons every record and inventory summary declares
`authoritative_resource_gate=false` and
`coordinates_required_for_authoritative_gate=true`. A proxy result can rank
metadata candidates for later review, but it cannot silently exclude a case,
mark a canonical run successful, or replace `SAFE_16GB.validate_static_request`
after structure preparation.

## Data and claim boundary

The inventory remains metadata-only and records that no coordinate file was
downloaded. Holo/ligand metadata remains evaluator-side; none of these resource
fields are detector evidence or pocket ground truth. The screen makes no claim
about pocket accuracy, biological relevance, discovery, or method superiority.

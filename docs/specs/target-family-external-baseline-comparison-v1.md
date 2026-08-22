# Target-family external-baseline comparison v1

Status: experimental development diagnostic. This contract is not a validation,
superiority, or discovery claim.

## Scope

This document records an earlier two-case comparison and the later bounded
six-case PF00497 development comparison. The two-case result is retained as
historical diagnostic evidence; the six-case result is the current G4
development diagnostic. Each comparison combines three detector-shaped
records on the same prepared apo inputs:

- BioVoid `canonical-static-v1` for the canonical case and the explicitly marked
  secondary recovery arm for the resource-blocked case;
- pinned fpocket 4.2.3;
- pinned P2Rank 2.5.1.

All external tools receive only the prepared apo structure. The comparison opens
the private evaluator report only after detector records have been written. The
frozen `phase6-cryptobench-v1` protocol supplies 4 Å DCC/DCA and Top-1/3/5
endpoints. Missing or failed detector records remain in the denominator.

## Resource and claim boundary

The target-family runner is separate from the 663-case RI-3 runner. It requires
an explicit `--approve-baselines` flag, uses one CPU and one worker, limits each
tool to 2 GB and its pinned timeout, and enforces a 1 GB local output quota.
The report records image IDs, manifest hashes, and target-blind provenance.

The evaluator comparison is written under ignored `data/runtime/`; it has
`diagnostic_dcc_dca_only`, `scientific_superiority_claim_authorized: false`, and
`discovery_claim_authorized: false`. A two-case, one-family pilot can expose
failure patterns and data-pipeline bugs, but cannot establish general accuracy
or superiority. The six-case comparison was run only after its separate
readiness record and explicit approval, and remains one-family development
diagnostic evidence rather than a held-out or confirmatory benchmark.

## Current six-case development diagnostic

On 22 August 2026, six PF00497 cases completed with zero detector failures using
the same prepared apo manifest, one worker/CPU, pinned fpocket 4.2.3 and
P2Rank 2.5.1 containers, and the frozen `phase6-cryptobench-v1` DCC/DCA
protocol. Top-1/3/5 recall was:

| Detector | DCC Top-1/3/5 | DCA Top-1/3/5 |
|---|---|---|
| BioVoid canonical static | 0 / 0.333 / 0.333 | 0.333 / 0.5 / 0.5 |
| fpocket | 0.333 / 0.333 / 0.333 | 0.333 / 0.333 / 0.333 |
| P2Rank | 0.5 / 0.667 / 0.667 | 0.833 / 1 / 1 |

These values are descriptive only: one protein family and six cases cannot
support superiority, validation, or discovery claims. Motion/NMA and ML were
not used, and the detector records were written before evaluator ground truth
was opened. False-pocket burden and resource reporting remain unavailable in
this comparison and are not silently imputed.

## Next gate

Review the six-case failure patterns, representative-chain/alignment warnings,
and family/sequence limitations. Then either close the bounded diagnostic as a
negative/equivalent result or design a larger family/sequence-aware,
leakage-audited apo--holo cohort. Only that cohort can support a real held-out
benchmark or a later ML decision.

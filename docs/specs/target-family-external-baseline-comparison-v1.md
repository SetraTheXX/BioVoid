# Target-family external-baseline comparison v1

Status: experimental development diagnostic. This contract is not a validation,
superiority, or discovery claim.

## Scope

This document records an earlier two-case comparison and is retained as
historical diagnostic evidence. It combines three detector-shaped records on
the same two prepared apo inputs:

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
or superiority. It does not describe the current six-case PF00497 evaluator
cohort; a future six-case external comparison requires its own explicit
readiness and approval record.

## Next gate

Review the representative-chain policy and the secondary recovery limitation,
then build a larger family/sequence-aware, leakage-audited apo--holo cohort.
Only that cohort can support a real held-out benchmark or a later ML decision.

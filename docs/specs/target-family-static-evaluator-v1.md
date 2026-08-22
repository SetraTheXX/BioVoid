# Target-family static evaluator v1

Status: experimental development contract. This document defines a bounded
evaluator workflow; it is not a validation, superiority, or discovery claim.

## Scope

The target-family pilot evaluates geometry-based pocket candidates on a small,
predeclared apo-only structure manifest. The detector sees only the prepared
apo structure. Holo coordinates and ligand-contact information are opened only
by a separate evaluator after the detector run has been recorded.

The pilot is intentionally bounded:

- at most 10 cases;
- one worker;
- motion/NMA disabled;
- external baselines disabled in the canonical static run;
- a hard local disk quota;
- no ML training or generated model artifacts.

## Canonical and secondary arms

The canonical arm uses `canonical-static-v1` with the `SAFE_16GB` resource
profile. A resource-blocked canonical case remains blocked; it is not silently
replaced by a more permissive run.

A separate recovery arm may reuse an already prepared apo file under an explicit
resource profile. Recovery output is marked secondary and cannot be promoted to
canonical evidence by the evaluator.

For multi-chain apo/holo pairs, the current evaluator diagnostic policy is
`representative-common-chain-v1`: the lexicographically first common chain that
meets the residue minimum is aligned, and its corresponding ligand copy is
selected deterministically. This policy is evaluator-only and must be reviewed
before any larger comparison; it does not change detector input or canonical
static ranking.

## Metrics and claim boundary

The frozen `phase6-cryptobench-v1` protocol supplies 4 Å DCC and DCA tolerances
and Top-1/3/5 localization endpoints. Detector scores are not used to compute
these distances. Missing, failed, resource-blocked, and alignment-unavailable
cases remain visible in the report denominator or failure counts.

Every report must retain:

- manifest and protocol hashes;
- canonical versus secondary arm identity;
- alignment policy and warnings;
- disk and worker limits;
- `diagnostic_only_not_for_claim` status;
- an explicit roadmap current gate and next step.

The evaluator guard rejects reports that enable sealed evaluation, discovery or
scientific-superiority claims, violate the single-worker boundary, exceed the
disk quota, or drift from the locked representative-chain policy.

## Next gate

An earlier bounded two-case fpocket/P2Rank comparison is retained as historical
diagnostic evidence; it is not the current PF00497 evaluator cohort. The current
PF00497 static/evaluator pilot contains six usable apo--holo-labelled cases
(two development, two validation, and two temporal-test cases) and remains
diagnostic-only. The representative-chain/error-pattern review and the bounded
external-baseline comparison are complete; their metrics do not authorize
superiority, validation, or discovery claims. The next gate is design of a new,
family/sequence-aware leakage-audited cohort. NMA, ML, broad PDB scans and
discovery language remain out of scope until a separately approved held-out
experiment and independent evidence support them.

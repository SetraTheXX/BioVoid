# Target-family held-out ranking v1

Status: **frozen preparation contract; one local diagnostic full-candidate run completed; no held-out result has been claimed**.

This contract defines how BioVoid may later inspect the complete static
candidate universe without changing the canonical detector ranking or leaking
the holo/evaluator label into the detector. It is a preparation gate for a
future PF00497 analysis, not a benchmark result.

## Candidate retention

The normal static pilot remains `top10`: it stores the first ten candidates in
the canonical volume-descending order. A separate run may explicitly select
`full` retention. That run must use a different empty output directory and may
store every candidate returned by `canonical-static-v1` as `all_pockets` while
retaining the same `top_pockets` compatibility view.

Both modes remain bounded by the existing contract:

- at most 10 cases;
- one worker;
- `SAFE_16GB` resource checks;
- motion/NMA, external baselines and ML disabled;
- one-gigabyte output quota;
- explicit user approval before coordinate download.

Full retention is not a resource-limit bypass. A blocked or failed case remains
visible and is never replaced by a recovery result in the canonical arm. The
evaluator and offline shadow analyzer accept `--candidate-scope full` only when
the static artifact is sealed with full retention; the evaluator records the
static-run hash and keeps the full-candidate workspace separate from the
top-10 workspace.

The 22 August 2026 local diagnostic run completed all six cases with zero
failures and zero resource blocks. Its evaluator report also completed all six
DCC/DCA alignments. These ignored local artifacts are implementation evidence
only; they do not authorize a benchmark, superiority, validated-prediction or
discovery claim.

## Held-out split and label boundary

The six-case PF00497 cohort keeps the existing sequence-aware temporal split:
two development, two validation and two temporal-test cases. Ranking policy
selection or feature decisions may inspect development only. Validation is used
once for a predeclared check; temporal-test remains locked until the policy and
all hashes are frozen.

The detector input is apo structure data only. Holo coordinates, ligand contact
labels, DCC/DCA distances, split labels and evaluator metadata are opened only
after the target-blind static artifact is sealed. No ranking policy may use
those fields during candidate generation or tuning.

## Ranking and measurement

The canonical comparator stays `canonical-static-v1-volume-descending`. Any new
ranking policy must have a new version, a written formula, deterministic tie
breaks and an input-feature whitelist recorded before evaluator access. The
current exploratory volume/enclosure shadow formula is not promoted by this
contract.

The evaluator reports DCC and DCA with the frozen 4 Å tolerance at Top-1/3/5,
case-level failures, candidate counts, tail coverage, alignment warnings and
runtime/resource status. Missing or unavailable cases remain visible; no
post-hoc threshold, split, candidate cutoff or pair policy change is allowed.

## Decision boundary

This contract authorizes implementation of a separate full-candidate artifact,
not a scientific claim. Each run must be approved explicitly, sealed with
manifest/protocol/input hashes, and reviewed before any confirmatory use of the
temporal-test split. Negative or unchanged results are valid outcomes. ML,
NMA, docking, broad PDB scanning, superiority language and discovery claims
remain closed.

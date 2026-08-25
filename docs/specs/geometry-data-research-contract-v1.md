# Geometry/data research contract v1

Status: **active development/held-out gate; AHoJ development diagnostic is
complete, while validation and temporal-test remain sealed**.

This contract starts a new research branch after the bounded PocketMiner
held-out study and external comparison. It does not reopen the PocketMiner
policy, alter `canonical-static-v1`, or turn the four-case diagnostic into a
scientific claim.

## Preregistered question

On a new, leakage-independent apo/holo source, can BioVoid's geometry pipeline
produce a final-pocket candidate near an independently labelled ligand site?
If the candidate is present, does a predeclared interpretable ranking policy
place it in the early shortlist without reducing candidate-universe coverage?

The two failure modes are kept separate:

1. **candidate-generation/acceptance bottleneck:** the labelled site is absent
   from the retained final-pocket list or the required raw-stage diagnostic;
2. **ranking bottleneck:** a site-like final candidate exists but is ranked
   below the predeclared Top-k boundary.

The output is a diagnostic and a shortlist of unvalidated structural
hypotheses. It is not a discovery, binding predictor, drug-design system, or
clinical result.

## Metadata-only source gate

Before any coordinate or ligand file is materialized, a new versioned source
catalog must provide all of the following:

- at least ten eligible cases: six development, two validation, and two
  temporal-test cases; fewer cases may only produce a feasibility closure;
- independent apo/holo or annotation label provenance with an explicit quality
  class and no guessed ligand mapping;
- PDB, UniProt, and sequence-cluster independence from RI-3, PF00497, and
  PocketMiner v1 inputs;
- release dates sufficient for a deterministic temporal split;
- deposited atom/model/chain and molecular-weight proxies for the unchanged
  `safe-16gb` preflight;
- source snapshot hash, retrieval timestamp, license/provenance, and a stable
  deterministic allocation/tie-breaker;
- no selection criterion derived from BioVoid scores, failure cases, or
  evaluator results.

The metadata report must end in exactly `PASS`, `DIAGNOSTIC_ONLY`, or `NO_GO`.
`NO_GO` is a valid result and does not authorize a second-family search by
changing pagination, thresholds, or names.

## Split and detector boundary

Sequence clusters are assigned to development/validation/temporal-test before
coordinates, holo labels, or detector output are opened. The apo-only detector
manifest is frozen with hashes. Holo coordinates, ligand contacts, DCC/DCA
labels, and evaluator metadata remain outside detector input.

The bounded first run is at most ten cases, one worker, motion off, unchanged
`safe-16gb`, and a one-gigabyte local output quota. It must retain the complete
final merged pocket list. To diagnose the generation/acceptance branch, the
versioned runtime artifact should also retain raw-stage candidate counts and,
when feasible within the quota, an ignored raw candidate-center table. The raw
stage must never be confused with the final-pocket list.

## Ranking and comparison lock

The canonical volume-descending ranking remains the baseline. Any shadow
ranking study must preregister a finite interpretable policy set, deterministic
tie breaks, and a feature whitelist before evaluator access. Policy selection
is development-only; validation and temporal-test are measured once without
retuning. External fpocket/P2Rank runs, if used, receive the same prepared apo
inputs and are reported with their own retained-candidate scope.

NMA/motion, docking, broad PDB scans, neural models, and ML labels generated
from BioVoid's own heuristic score are outside this contract.

## Decision gate

- **Generation/acceptance signal:** write a separate geometry-stage contract;
  do not tune ranking to compensate for absent candidates.
- **Ranking signal:** run only the preregistered policy comparison on the new
  development split, then lock it for held-out evaluation.
- **Mixed/negative/equivalent:** keep both limitations visible and close the
  branch rather than accumulating more families without a sharper question.

No result may be described as accuracy, validated prediction, druggability,
discovery, or superiority without an independent rerun and expert/experimental
review.

## Initial design action (closed)

Build a metadata-only candidate catalog under a new versioned source ID. Do not
download coordinates, open holo labels, start NMA/ML, or change the static
detector while that feasibility gate is running. This was the initial source
gate; the AHoJ catalog, split reservation, apo-only manifest, and development
static artifact below now supersede it.

## First catalog feasibility result — AHoJ subset 1 (2026-08-25)

The first bounded source attempt used the versioned AHoJ-DB v1 subset 1
snapshot. The audit read the local query summary and requested only AHoJ and
RCSB entry metadata; no coordinate or ligand file was downloaded. Twenty
apo/holo pair responses were returned, six had an apo resource proxy within
the unchanged `safe-16gb` atom cap, and four metadata requests had no
independent pair after prior-structure exclusion.

The result is **DIAGNOSTIC_ONLY**, not `PASS`: apo/holo chain mapping and
sequence-cluster resolution are still review-required, and the safe pairs do
not yet constitute a sealed independent 6/2/2 cohort. This is a source
feasibility state, not a detector or biological negative. The next gate is to
resolve chain IDs and sequence clusters from metadata, remove duplicate and
prior-overlap cases, and then make a deterministic capacity decision. Until
that gate passes, coordinates, detector runs, evaluator labels, NMA, and ML
remain closed.

The bounded audit was then expanded to a maximum of 192 deterministic
metadata queries under the same source-selection rule. It returned 154 pair
responses and 52 apo pairs within the unchanged `safe-16gb` proxy. RCSB
entry/polymer-entity metadata resolved 52 distinct apo sequence clusters;
after checking the evaluator-side ligand component and chain metadata, 20
cases were labelable without guessing a ligand mapping.

The AHoJ-specific chronological allocation is frozen before coordinates:
development uses apo release before `2018-01-01`, validation uses
`2018-01-01` through `2020-12-31`, and temporal-test uses releases on or after
`2021-01-01`. This yields exactly 6 development, 2 validation, and 2
temporal reservations. The external AHoJ/BioLiP2 site-assignment semantics
are recorded as evaluator-only independent provenance. The source gate is now
**PASS** at metadata level; the redacted full-structure apo-only manifest is
sealed locally. This authorizes only the next development preparation gate,
not a benchmark result, validation claim, NMA run, ML training, or discovery
wording.

Ignored local artifacts are
`local-private/research/geometry-data-source-catalog/ahoj-v1/` and
`data/runtime/target-family/cohort-ahoj-geometry-v1/`; the public repository
contains only the versioned contracts and bounded scripts, never structures or
evaluator labels.

## Development preparation and static pilot gate (2026-08-25)

The six development apo structures were materialized as asymmetric-unit CIFs
and prepared with `PreparationConfig(chain_ids=None)`, preserving the
canonical full-heavy-atom input boundary. The first preflight attempt prepared
6/6 but was blocked for 3/6 by the live available-memory guard; that report is
retained as an operational record. A second run under the same unchanged
`safe-16gb` contract passed 6/6. Raw downloads totaled 2,856,701 bytes and
the selected protein heavy-atom counts were 920–3,927.

The target-blind canonical static pilot then completed 6/6 sequential cases,
retaining every final merged pocket (not only Top-10). It produced a
diagnostic artifact with 79–315 final pockets per case and no evaluator data,
motion, external baseline, or ML activity. This is not a validation result;
the next gate is to materialize the six evaluator-side AHoJ labels and run a
read-only DCC/DCA decomposition against this frozen static artifact.

## AHoJ evaluator and development policy gate (2026-08-25)

The evaluator opened only the six development holo structures after the
target-blind static artifact was sealed. Protein C-alpha alignment was fitted
in the prepared apo frame and ligand coordinates were transformed only after
that fit. The first reject-only alignment attempt remains as a private
fail-closed audit; a deterministic structural-fit recovery policy already
implemented by the alignment module was then used for ambiguous sequence
alignments. The recovery policy is versioned, does not inspect DCC/DCA results,
and does not alter detector output or ranking.

All six development labels aligned successfully. Validation and temporal-test
coordinates/labels were not opened. The full final-pocket list was evaluated
with the frozen `phase6-cryptobench-v1` 4 Å DCC/DCA protocol. The joint
final-list candidate-universe count was **5/6**; joint Top-1/3/5/10 recall was
**1/6, 3/6, 3/6, and 4/6**. Three cases had joint Top-5 support, two were
late-ranking cases (best joint ranks 8 and 15), and one was a final-list miss.
These are small development diagnostics, not accuracy or discovery claims.

The pre-registered A/B/C shadow ranking comparison then ran only on these six
development cases. A is canonical volume-descending, B is the fixed
70/30 volume/enclosure variant, and C is the fixed 50/50 variant. DCC Top-3,
DCA Top-3, and DCC Top-1 tie-breaks were equal for A and B; the final frozen
tie-break retained **`A-canonical-volume-v1`**. No policy was promoted to
`canonical-static-v1`, and no validation/temporal label was opened.

The next gate is a target-blind, bounded materialization/static run for the
reserved 2 validation + 2 temporal cases, followed by one locked-A evaluator
readout. No retuning, NMA, external baseline, ML, or new source search is
authorized before that held-out result.

## AHoJ locked-policy held-out gate (2026-08-25)

The four reserved apo inputs (2 validation + 2 temporal-test) passed the same
one-worker `safe-16gb` preflight and completed target-blind canonical static
analysis with full final-pocket retention. The locked A policy was not changed
or rerun as a different detector.

The held-out evaluator opened only the four reserved holo structures. Three
rows aligned under the versioned structural-fit recovery policy; the
`6J6F`–`5FB7` pair remained **E — evaluator/alignment unavailable** because its
protein fit exceeded the frozen 8 Å maximum RMSD. That row stays visible and
is not converted into a detector miss or success. Among the three aligned
rows, the joint final-list candidate-universe count was **2/3**, while joint
Top-1/3/5/10 was **0/3** at every cutoff. The validation subset contributes
one aligned row (6EHF, best joint rank 111); the temporal subset contributes
two aligned rows (8SBN, best joint rank 32; 8BCL, final-list miss).

This is a small negative/equivalent diagnostic with an explicit E-status, not
a validated held-out result and not a superiority or discovery claim. The
current decision is to keep the locked A policy and open a separate
source/alignment-quality decision: either close this branch with the E row
retained, or create a new versioned cohort/alignment contract. Replacing the
6J6F case ad hoc after seeing outcomes is prohibited. NMA, external baselines,
ML, and new source search remain closed until that decision is recorded.

# Target-family external-baseline readiness v1

Status: experimental development contract. This document describes a
preflight gate; it is not a benchmark result, superiority claim, validation,
or discovery claim.

## Purpose

The current bounded PF00497 pilot contains six usable cases (two development,
two validation, and two temporal-test cases). It can be compared with fpocket
and P2Rank only after the representative-chain policy and the current
six-case diagnostic evaluator have been reviewed. The earlier two-case
evaluator/external-baseline record is historical evidence, not the active
cohort. `scripts/check_target_family_baseline_readiness.py` prepares that next
gate without running either external tool.

The generated local manifest contains only the already prepared apo inputs:

- at most ten predeclared cases (the active PFAM cohort has six; never more than
  ten);
- prepared full-heavy-atom coordinates and their hashes;
- one worker, motion/NMA disabled, and a one-gigabyte local output quota;
- no holo coordinates, ligand contacts, evaluator labels, or ML artifacts.

The manifest and report are generated under ignored `data/runtime/`. They are
local runtime evidence and are intentionally not part of the public tree.

## Read-only tool preflight

The checker may inspect the Docker daemon and the pinned fpocket/P2Rank image
IDs. It never invokes `docker pull`, `docker build`, or `docker run`. Each
future baseline invocation is separately bounded to one CPU, two gigabytes of
container memory, and a 180-second fpocket or 240-second P2Rank timeout.

The checker fails closed when a prepared input hash, static/recovery binding,
or target-blind boundary drifts. It also keeps the representative-chain review
and explicit user approval as separate gates. A ready report therefore means
“safe to consider starting a run”, never “the run has started” or “the method
is scientifically validated”.

The existing RI-3 baseline runner remains locked to its 663-structure cohort and
must not be pointed at the historical two-case manifest. The separate target-family
adapter is `scripts/run_target_family_external_baseline.py`; it has its own
explicit `--approve-baselines` gate and preserves the same target-blind,
single-worker boundary.

## Current development gate

The current local report is expected to remain one of:
`blocked_review_and_tooling`, `blocked_independent_review`,
`blocked_tooling_unavailable`, or `ready_for_explicit_user_approval`.
The historical two-case run was started only after the then-current state and
explicit user approval; its ignored output is diagnostic-only and does not
authorize superiority or discovery claims. No six-case external-baseline run is
implied by this readiness contract. Until the representative-chain review and
an explicit bounded-run approval are complete, NMA, broad scans, ML training,
and discovery language remain out of scope.
